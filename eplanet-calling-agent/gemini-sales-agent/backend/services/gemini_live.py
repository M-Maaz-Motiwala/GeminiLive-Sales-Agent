"""GeminiLiveSession — core async class bridging audio streams to Gemini Live API."""
import asyncio
import base64
import logging
from typing import Callable, Optional, Awaitable

from google import genai
from google.genai import types

import json

from backend.config import get_settings
from backend.services import tool_executor, session_manager
from backend.services.token_meter import SessionTokenUsage, extract_usage_metadata
from backend.db.models import Session as DBSession, Message, SessionStatus

logger = logging.getLogger(__name__)
settings = get_settings()

SYSTEM_PROMPTS = {
    "sales": (
        "You are a professional sales agent for 'Aura Tech', a company that sells high-end smart home "
        "ecosystems. Your goal is to be helpful, persuasive, and friendly. Answer questions about Aura Tech "
        "products (Aura Hub, Aura Lights, Aura Security) and try to close a discovery call. "
        "Keep responses concise and conversational — this is a voice interaction. "
        "Use tools to save leads and search the knowledge base when relevant."
    ),
    "research": (
        "You are an expert research agent. Help the user explore topics in depth, synthesize information, "
        "and produce clear research summaries. Use Google Search and the knowledge base to ground your answers."
    ),
    "code_analysis": (
        "You are a senior software engineer specializing in code review and architecture analysis. "
        "Help the user understand codebases, identify issues, suggest improvements, and make architectural decisions."
    ),
    "document_qa": (
        "You are a document analysis expert. Answer questions strictly based on the provided knowledge base. "
        "If information is not in the knowledge base, say so clearly."
    ),
    "lead_qualification": (
        "You are a lead qualification specialist. Engage with prospects, ask BANT questions "
        "(Budget, Authority, Need, Timeline), and use tools to save qualified leads."
    ),
    "outbound_sales": (
        "You are an outbound sales representative. Place professional cold calls, "
        "respect opt-outs, and use tools to capture leads or book callbacks."
    ),
    "summarization": (
        "You are a professional summarization agent. Condense information accurately, "
        "highlight key points, and produce structured outputs on request."
    ),
}


class GeminiLiveSession:
    """Manages a single Gemini Live session with full tool calling and DB persistence."""

    def __init__(
        self,
        db_session_id: int,
        agent_config: dict,
        db,
        on_audio: Optional[Callable[[bytes], Awaitable[None]]] = None,
        on_text: Optional[Callable[[str, str], Awaitable[None]]] = None,
        on_close: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        self.db_session_id = db_session_id
        self.agent_config = agent_config
        self.db = db
        self.on_audio = on_audio   # callback(pcm_bytes)
        self.on_text = on_text     # callback(role, text)
        self.on_close = on_close

        self._session = None
        self._client = None
        self._receive_task: Optional[asyncio.Task] = None
        self._session_task: Optional[asyncio.Task] = None
        self._session_ready = asyncio.Event()
        self.is_running = False
        self.token_usage = SessionTokenUsage()

    def _build_config(self) -> dict:
        agent_type = self.agent_config.get("type", "sales")
        system_prompt = self.agent_config.get("system_prompt_template") or SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS["sales"])
        voice = self.agent_config.get("voice", "Zephyr")
        enabled_tools = self.agent_config.get("enabled_tools", [])

        tools = []
        tool_decls = tool_executor.get_tool_declarations(enabled_tools)
        if tool_decls:
            tools.append({"function_declarations": tool_decls})
        if "google_search" in enabled_tools:
            tools.append({"google_search": {}})

        config = {
            "response_modalities": ["AUDIO"],
            "speech_config": {
                "voice_config": {"prebuilt_voice_config": {"voice_name": voice}}
            },
            "system_instruction": system_prompt,
        }
        if tools:
            config["tools"] = tools

        return config

    async def start(self):
        self._client = genai.Client(api_key=settings.gemini_api_key)
        model = self.agent_config.get("model", "gemini-3.1-flash-live-preview")
        config = self._build_config()
        self.token_usage.add_text_context(config.get("system_instruction", ""))
        # Launch session in a background task that keeps the async with block open
        self._session_task = asyncio.create_task(self._run_session(model, config))
        # Wait until the session is actually connected before returning
        await asyncio.wait_for(self._session_ready.wait(), timeout=15)

    async def _run_session(self, model: str, config: dict):
        """Holds the async with context open for the full call duration."""
        try:
            async with self._client.aio.live.connect(model=model, config=config) as session:
                self._session = session
                self.is_running = True
                session_manager.register(self.db_session_id, self)
                self._session_ready.set()
                logger.info(f"GeminiLiveSession {self.db_session_id} started.")
                await self._receive_loop()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Session {self.db_session_id} connection error: {e}", exc_info=True)
            self._session_ready.set()  # unblock start() on error
        finally:
            self.is_running = False
            self._session = None

    async def send_initial_greeting(self):
        """Prompt Gemini to introduce itself at the start of the call."""
        greeting = (
            "The call has just connected. Please greet the caller warmly and introduce yourself."
        )
        if self._session and self.is_running:
            self.token_usage.add_text_context(greeting)
            await self._session.send_client_content(
                turns=[{"role": "user", "parts": [{"text": greeting}]}],
                turn_complete=False,
            )

    async def send_audio(self, pcm_base64: str):
        """Send base64-encoded 16-bit PCM (16kHz) audio to Gemini (used by WebSocket browser path)."""
        if self._session and self.is_running:
            raw_bytes = base64.b64decode(pcm_base64)
            self.token_usage.add_audio_input(len(raw_bytes), sample_rate_hz=16000)
            await self._session.send_realtime_input(
                audio=types.Blob(data=raw_bytes, mime_type="audio/pcm;rate=16000")
            )

    async def send_audio_bytes(self, pcm_bytes: bytes):
        """Send raw PCM bytes to Gemini (used by RTP bridge / SIP path)."""
        if self._session and self.is_running:
            self.token_usage.add_audio_input(len(pcm_bytes), sample_rate_hz=16000)
            await self._session.send_realtime_input(
                audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
            )

    async def _receive_loop(self):
        logger.info(f"Session {self.db_session_id} receive loop starting.")
        empty_receive_cycles = 0
        try:
            while self.is_running and self._session:
                got_response = False
                async for response in self._session.receive():
                    got_response = True
                    self.token_usage.merge_api_usage(extract_usage_metadata(response))
                    sc = response.server_content
                    mt = sc.model_turn if sc else None
                    parts = mt.parts if mt else []
                    audio_parts = [p for p in parts if p.inline_data and p.inline_data.data]
                    logger.info(
                        f"Session {self.db_session_id} response: "
                        f"sc={bool(sc)}, model_turn={bool(mt)}, "
                        f"parts={len(parts)}, audio_parts={len(audio_parts)}, "
                        f"tc={getattr(sc, 'turn_complete', None)}, "
                        f"tool={bool(response.tool_call)}"
                    )
                    # Audio output — lives in server_content.model_turn.parts[*].inline_data
                    if response.server_content and response.server_content.model_turn:
                        for part in response.server_content.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                logger.info(f"Session {self.db_session_id} sending {len(part.inline_data.data)} audio bytes to on_audio, on_audio set={self.on_audio is not None}")
                                audio_data = part.inline_data.data
                                if isinstance(audio_data, str):
                                    audio_data = audio_data.encode()
                                self.token_usage.add_audio_output(len(audio_data), sample_rate_hz=24000)
                                if self.on_audio:
                                    await self.on_audio(part.inline_data.data)

                    # Text output
                    if response.server_content:
                        sc = response.server_content

                        # Model transcription text
                        if sc.model_turn:
                            for part in sc.model_turn.parts:
                                if part.text and self.on_text:
                                    await self.on_text("model", part.text)
                                    await self._persist_message("model", part.text)

                        # User audio transcription
                        if sc.input_transcription and sc.input_transcription.text:
                            text = sc.input_transcription.text
                            self.token_usage.add_text_output(text)
                            if self.on_text:
                                await self.on_text("user", text)
                            await self._persist_message("user", text)

                        # Output transcription (model speech as text)
                        if sc.output_transcription and sc.output_transcription.text:
                            text = sc.output_transcription.text
                            self.token_usage.add_text_output(text)
                            if self.on_text:
                                await self.on_text("model", text)

                    # Tool calls
                    if response.tool_call:
                        await self._handle_tool_call(response.tool_call)

                # Some SDK versions end receive() at turn boundaries; continue listening.
                if self.is_running and self._session:
                    if got_response:
                        empty_receive_cycles = 0
                        logger.info(f"Session {self.db_session_id} receive stream ended at turn boundary; continuing.")
                        continue
                    empty_receive_cycles += 1
                    if empty_receive_cycles >= 3:
                        logger.info(f"Session {self.db_session_id} receive stream ended (no responses); treating as closed.")
                        break
                    await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info(f"Session {self.db_session_id} receive loop cancelled.")
        except Exception as e:
            logger.error(f"Session {self.db_session_id} receive loop error: {e}")
        else:
            logger.info(f"Session {self.db_session_id} receive loop exited normally (server closed).")
        finally:
            self.is_running = False
            session_manager.unregister(self.db_session_id)
            if self.on_close:
                await self.on_close()

    async def _handle_tool_call(self, tool_call) -> None:
        """Dispatch tool calls in parallel and send responses back to Gemini."""
        async def run_one(fc):
            fr = await tool_executor.dispatch(
                tool_name=fc.name,
                call_id=fc.id,
                params=dict(fc.args) if fc.args else {},
                db=self.db,
                session_id=self.db_session_id,
                agent_id=self.agent_config.get("id"),
            )
            return fr

        responses = await asyncio.gather(
            *[run_one(fc) for fc in tool_call.function_calls]
        )
        for fr in responses:
            try:
                payload = json.dumps(fr.response) if fr.response is not None else ""
            except (TypeError, ValueError):
                payload = str(fr.response)
            self.token_usage.add_text_context(payload)
        await self._session.send_tool_response(function_responses=list(responses))

    async def _persist_message(self, role: str, text: str):
        try:
            msg = Message(session_id=self.db_session_id, role=role, text=text)
            self.db.add(msg)
            await self.db.flush()
        except Exception as e:
            logger.warning(f"Failed to persist message: {e}")

    async def close(self):
        self.is_running = False
        if self._receive_task:
            self._receive_task.cancel()
        if self._session_task:
            self._session_task.cancel()
            try:
                await self._session_task
            except asyncio.CancelledError:
                pass
        session_id = self.db_session_id
        try:
            from sqlalchemy import update
            from backend.db.models import Session as DBSession, SessionStatus
            from datetime import datetime, timezone
            from sqlalchemy import select

            result = await self.db.execute(select(DBSession).where(DBSession.id == session_id))
            db_session = result.scalar_one_or_none()
            if db_session:
                meta = dict(db_session.meta or {})
                meta["token_usage"] = self.token_usage.to_dict()
                db_session.status = SessionStatus.ended
                db_session.ended_at = datetime.now(timezone.utc)
                db_session.meta = meta
            else:
                await self.db.execute(
                    update(DBSession)
                    .where(DBSession.id == session_id)
                    .values(status=SessionStatus.ended, ended_at=datetime.now(timezone.utc))
                )
            await self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to update session status: {e}")
        session_manager.unregister(session_id)
        logger.info(f"GeminiLiveSession {session_id} closed.")
        try:
            from backend.services.post_call import process_call_end
            from backend.services.session_metrics import finalize_session_metrics
            from backend.db.database import AsyncSessionLocal

            async def _finalize_and_post_call():
                async with AsyncSessionLocal() as db:
                    await finalize_session_metrics(db, session_id)
                    await db.commit()
                await process_call_end(session_id)

            asyncio.create_task(_finalize_and_post_call())
        except Exception as e:
            logger.warning(f"Failed to queue post-call for session {session_id}: {e}")
        try:
            await self.db.close()
        except Exception:
            pass
