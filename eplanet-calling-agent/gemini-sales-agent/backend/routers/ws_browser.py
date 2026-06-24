"""WebSocket endpoint for browser ↔ FastAPI ↔ Gemini Live proxying."""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.deps import get_ws_user
from backend.db.database import get_db, AsyncSessionLocal
from backend.db.models import Agent, Session as DBSession, ChannelType, SessionStatus
from backend.services.gemini_live import GeminiLiveSession

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/live")
async def ws_live(
    websocket: WebSocket,
    agent_id: int = Query(1),
    token: Optional[str] = Query(None),
):
    await websocket.accept()

    # Authenticate
    async with AsyncSessionLocal() as db:
        user = await get_ws_user(token or "", db) if token else None

    # Load agent config
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.is_active == True))
        agent = result.scalar_one_or_none()
        if not agent:
            await websocket.send_json({"type": "error", "message": "Agent not found"})
            await websocket.close()
            return

        agent_config = {
            "id": agent.id, "type": agent.type, "name": agent.name,
            "system_prompt_template": agent.system_prompt_template,
            "voice": agent.voice, "model": agent.model,
            "enabled_tools": agent.enabled_tools or [],
        }

        # Create DB session record
        db_session = DBSession(
            agent_id=agent_id,
            channel_type=ChannelType.web,
            status=SessionStatus.active,
        )
        db.add(db_session)
        await db.flush()
        session_id = db_session.id
        await db.commit()

    async with AsyncSessionLocal() as session_db:
        async def send_audio(pcm_bytes: bytes):
            import base64
            b64 = base64.b64encode(pcm_bytes).decode()
            try:
                await websocket.send_json({"type": "audio", "data": b64})
            except Exception:
                pass

        async def send_text(role: str, text: str):
            msg_type = "transcript_user" if role == "user" else "transcript_model"
            try:
                await websocket.send_json({"type": msg_type, "text": text, "timestamp": ""})
            except Exception:
                pass

        async def on_close():
            try:
                await websocket.send_json({"type": "disconnected"})
                await websocket.close()
            except Exception:
                pass

        live = GeminiLiveSession(
            db_session_id=session_id,
            agent_config=agent_config,
            db=session_db,
            on_audio=send_audio,
            on_text=send_text,
            on_close=on_close,
        )

        try:
            await live.start()
            await websocket.send_json({"type": "connected", "session_id": session_id})

            while True:
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                    msg = json.loads(raw)
                    if msg.get("type") == "audio":
                        await live.send_audio(msg["data"])
                    elif msg.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "ping"})
                except WebSocketDisconnect:
                    break

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"WebSocket session {session_id} error: {e}")
        finally:
            await live.close()
