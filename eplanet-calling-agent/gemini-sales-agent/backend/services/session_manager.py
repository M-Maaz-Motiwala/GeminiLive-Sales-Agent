"""In-memory registry of active GeminiLiveSession objects, keyed by session_id."""
from typing import Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from backend.services.gemini_live import GeminiLiveSession

logger = logging.getLogger(__name__)

_sessions: dict[int, "GeminiLiveSession"] = {}


def register(session_id: int, session: "GeminiLiveSession"):
    _sessions[session_id] = session
    logger.info(f"Session {session_id} registered. Active: {len(_sessions)}")


def unregister(session_id: int):
    _sessions.pop(session_id, None)
    logger.info(f"Session {session_id} unregistered. Active: {len(_sessions)}")


def get(session_id: int) -> Optional["GeminiLiveSession"]:
    return _sessions.get(session_id)


def all_sessions() -> dict[int, "GeminiLiveSession"]:
    return dict(_sessions)


def count() -> int:
    return len(_sessions)
