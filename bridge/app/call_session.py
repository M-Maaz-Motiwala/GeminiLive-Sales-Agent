"""Per-call state for concurrent Gemini Live telephony sessions."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.main import CallState


@dataclass
class CallSession:
    """One Stasis call — isolated queues, RTP port, and Gemini task."""

    human_channel_id: str
    state: "CallState"
    rtp_port: int = 0
    rtp_transport: Optional[asyncio.DatagramTransport] = None

    audio_ingest_queue: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=500)
    )
    rtp_out_queue: asyncio.Queue = field(
        default_factory=lambda: asyncio.Queue(maxsize=1000)
    )
    session_ready: asyncio.Event = field(default_factory=asyncio.Event)
    human_answered: asyncio.Event = field(default_factory=asyncio.Event)
    call_active: asyncio.Event = field(default_factory=asyncio.Event)
    gemini_task: Optional[asyncio.Task] = None
    pacer_task: Optional[asyncio.Task] = None
    session: Optional[object] = None
