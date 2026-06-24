"""Asterisk ARI WebSocket client — controls calls and creates ExternalMedia bridges."""
import asyncio
import json
import logging
from typing import Optional

import aiohttp
from sqlalchemy import select

from backend.config import get_settings
from backend.db.database import AsyncSessionLocal
from backend.db.models import Agent, Session as DBSession, ChannelType, SessionStatus
from backend.services.gemini_live import GeminiLiveSession

logger = logging.getLogger(__name__)
settings = get_settings()


class ARIClient:
    def __init__(self):
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._active_bridges: dict = {}  # channel_id → session_id
        self._rtp_dest: Optional[tuple] = None  # (host, port) for ExternalMedia

    @property
    def _base_url(self):
        return f"http://{settings.asterisk_host}:{settings.asterisk_ari_port}/ari"

    @property
    def _auth(self):
        return aiohttp.BasicAuth(settings.asterisk_ari_user, settings.asterisk_ari_pass)

    async def connect(self):
        """Connect to ARI WebSocket event stream."""
        while True:
            try:
                self._session = aiohttp.ClientSession()
                ws_url = (
                    f"ws://{settings.asterisk_host}:{settings.asterisk_ari_port}/ari/events"
                    f"?app={settings.asterisk_ari_app}&api_key={settings.asterisk_ari_user}:{settings.asterisk_ari_pass}"
                )
                async with self._session.ws_connect(ws_url) as ws:
                    self._ws = ws
                    logger.info("ARI WebSocket connected.")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            event = json.loads(msg.data)
                            await self._handle_event(event)
            except Exception as e:
                logger.warning(f"ARI connection lost: {e}. Retrying in 5s...")
                await asyncio.sleep(5)
            finally:
                if self._session:
                    await self._session.close()

    async def _handle_event(self, event: dict):
        event_type = event.get("type")
        logger.debug(f"ARI event: {event_type}")

        if event_type == "StasisStart":
            channel = event.get("channel", {})
            channel_id = channel.get("id")
            channel_name = channel.get("name", "")
            # Skip ExternalMedia (UnicastRTP) channels — they are created by us, not real calls
            if channel_name.startswith("UnicastRTP"):
                logger.debug(f"Ignoring ExternalMedia StasisStart: {channel_name}")
                return
            asyncio.create_task(self._handle_stasis_start(channel_id, channel))

        elif event_type == "StasisEnd":
            channel_id = event.get("channel", {}).get("id")
            if channel_id in self._active_bridges:
                session_id = self._active_bridges.pop(channel_id)
                from backend.services import session_manager
                live = session_manager.get(session_id)
                if live:
                    await live.close()

    async def _handle_stasis_start(self, channel_id: str, channel_info: dict):
        """When a call enters the Stasis app, bridge it to Gemini via ExternalMedia."""
        logger.info(f"StasisStart: {channel_id}")

        # Load agent FIRST — fail fast before touching the call
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Agent).where(Agent.is_active == True).limit(1))
            agent = result.scalar_one_or_none()
        if not agent:
            logger.error("No active agent found — create one via the admin UI or run seed_agent.py")
            await self._ari_post(f"/channels/{channel_id}/hangup")
            return

        # Answer the call
        await self._ari_post(f"/channels/{channel_id}/answer")
        await asyncio.sleep(0.3)

        # Create ExternalMedia channel pointing to our RTP bridge
        # Use the fastapi service hostname so Asterisk can reach it inside Docker
        em_response = await self._ari_post("/channels/externalMedia", json={
            "app": settings.asterisk_ari_app,
            "external_host": f"{settings.rtp_external_host}:{settings.rtp_listen_port}",
            "format": "ulaw",
            "encapsulation": "rtp",
            "transport": "udp",
            "direction": "both",
        })
        if not em_response:
            logger.error("Failed to create ExternalMedia channel")
            await self._ari_post(f"/channels/{channel_id}/hangup")
            return

        em_channel_id = em_response.get("id")
        logger.info(f"ExternalMedia channel created: {em_channel_id}")
        await asyncio.sleep(0.3)

        # Query Asterisk's RTP listen address — this is where we send AI audio back
        rtp_host = await self._ari_get_variable(em_channel_id, "UNICASTRTP_LOCAL_ADDRESS")
        rtp_port = await self._ari_get_variable(em_channel_id, "UNICASTRTP_LOCAL_PORT")
        if rtp_host and rtp_port:
            asterisk_rtp_addr = (rtp_host, int(rtp_port))
            logger.info(f"ExternalMedia RTP target: {asterisk_rtp_addr}")
        else:
            asterisk_rtp_addr = None
            logger.warning(f"Could not get UNICASTRTP variables for {em_channel_id}, will learn from first inbound RTP")

        # Create a bridge and add both channels
        bridge_response = await self._ari_post("/bridges", json={"type": "mixing"})
        if not bridge_response:
            await self._ari_post(f"/channels/{channel_id}/hangup")
            return
        bridge_id = bridge_response.get("id")

        # Add channels individually — Asterisk doesn't support comma-separated IDs
        await self._ari_post(f"/bridges/{bridge_id}/addChannel", json={"channel": channel_id})
        await self._ari_post(f"/bridges/{bridge_id}/addChannel", json={"channel": em_channel_id})

        agent_config = {
            "id": agent.id, "type": agent.type, "name": agent.name,
            "system_prompt_template": agent.system_prompt_template,
            "voice": agent.voice, "model": agent.model,
            "enabled_tools": agent.enabled_tools or [],
        }

        async with AsyncSessionLocal() as db:
            db_session = DBSession(
                agent_id=agent.id,
                caller_id=channel_info.get("caller", {}).get("number"),
                channel_type=ChannelType.sip,
                status=SessionStatus.active,
                meta={"ari_channel_id": channel_id, "bridge_id": bridge_id},
            )
            db.add(db_session)
            await db.flush()
            session_id = db_session.id
            await db.commit()

        self._active_bridges[channel_id] = session_id

        # Long-lived DB session for the entire call — closed in StasisEnd handler
        from backend.services import rtp_bridge as rtp
        session_db = AsyncSessionLocal()
        live = GeminiLiveSession(
            db_session_id=session_id,
            agent_config=agent_config,
            db=session_db,
            on_audio=lambda pcm: rtp.rtp_bridge.queue_audio(pcm, channel_id),
        )
        try:
            await live.start()
        except Exception as e:
            logger.error(f"Failed to start Gemini session for call {channel_id}: {e}", exc_info=True)
            await session_db.close()
            await self._ari_post(f"/channels/{channel_id}/hangup")
            return
        rtp.rtp_bridge.register_session(channel_id, live, asterisk_rtp_addr)

    async def originate(self, endpoint: str, agent_id: int) -> str:
        """Originate an outbound call."""
        response = await self._ari_post("/channels", json={
            "endpoint": endpoint,
            "app": settings.asterisk_ari_app,
            "callerId": "Aura AI",
        })
        return response.get("id", "") if response else ""

    async def _ari_get_variable(self, channel_id: str, variable: str) -> Optional[str]:
        """Query a channel variable from Asterisk ARI."""
        try:
            async with aiohttp.ClientSession() as s:
                url = f"{self._base_url}/channels/{channel_id}/variable?variable={variable}"
                async with s.get(url, auth=self._auth) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("value")
                    logger.warning(f"ARI GET variable {variable} returned {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"ARI GET variable {variable} failed: {e}")
            return None

    async def _ari_post(self, path: str, json: dict = None) -> Optional[dict]:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"{self._base_url}{path}",
                    json=json or {},
                    auth=self._auth,
                ) as resp:
                    if resp.status in (200, 201):
                        return await resp.json()
                    if resp.status == 204:
                        return {}  # No Content — success (answer, addChannel)
                    body = await resp.text()
                    logger.warning(f"ARI POST {path} returned {resp.status}: {body}")
                    return None
        except Exception as e:
            logger.error(f"ARI POST {path} failed: {e}")
            return None


ari_client = ARIClient()
