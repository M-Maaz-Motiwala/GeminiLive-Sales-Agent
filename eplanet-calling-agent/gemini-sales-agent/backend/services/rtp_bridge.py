"""Async UDP RTP bridge — receives audio from Asterisk ExternalMedia, sends back Gemini audio."""
import asyncio
import logging
import struct
from typing import Optional, TYPE_CHECKING

from backend.config import get_settings

if TYPE_CHECKING:
    from backend.services.gemini_live import GeminiLiveSession

logger = logging.getLogger(__name__)
settings = get_settings()

RTP_HEADER_SIZE = 12


def _parse_rtp(data: bytes) -> Optional[bytes]:
    """Strip 12-byte RTP header and return PCM payload."""
    if len(data) < RTP_HEADER_SIZE:
        return None
    return data[RTP_HEADER_SIZE:]


def _build_rtp(payload: bytes, seq: int, timestamp: int, ssrc: int) -> bytes:
    """Build minimal RTP packet (no extensions, no CSRC, ulaw PT=0)."""
    header = struct.pack(
        "!BBHII",
        0x80,      # V=2, P=0, X=0, CC=0
        0x00,      # M=0, PT=0 (ulaw)
        seq & 0xFFFF,
        timestamp & 0xFFFFFFFF,
        ssrc & 0xFFFFFFFF,
    )
    return header + payload


class RTPBridgeProtocol(asyncio.DatagramProtocol):
    def __init__(self, bridge: "RTPBridge"):
        self.bridge = bridge
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        logger.info(f"RTP bridge listening on UDP {settings.rtp_listen_host}:{settings.rtp_listen_port}")

    def datagram_received(self, data: bytes, addr):
        pcm_payload = _parse_rtp(data)
        if pcm_payload:
            asyncio.create_task(self.bridge._on_rtp_received(pcm_payload, addr))

    def error_received(self, exc):
        logger.error(f"RTP error: {exc}")


class RTPBridge:
    def __init__(self):
        self._sessions: dict[str, "GeminiLiveSession"] = {}
        self._audio_destinations: dict[str, tuple] = {}  # channel_id → (host, port)
        self._source_to_channel: dict[tuple, str] = {}  # (host, port) -> channel_id
        self._seq: dict[str, int] = {}
        self._ts: dict[str, int] = {}
        self._ssrc: int = 0xABCDEF01
        self._transport = None   # asyncio DatagramTransport (bound to RTP_LISTEN_PORT)
        self._send_queues: dict[str, asyncio.Queue] = {}
        self._send_tasks: dict[str, asyncio.Task] = {}
        self._recv_count: int = 0

    async def start(self):
        loop = asyncio.get_event_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: RTPBridgeProtocol(self),
            local_addr=(settings.rtp_listen_host, settings.rtp_listen_port),
        )
        self._transport = transport
        logger.info("RTP bridge started.")

    def register_session(self, channel_id: str, session: "GeminiLiveSession",
                         asterisk_rtp_addr: Optional[tuple] = None):
        """Register a Gemini session. asterisk_rtp_addr pre-sets the AI→caller RTP destination."""
        self._sessions[channel_id] = session
        self._seq[channel_id] = 0
        self._ts[channel_id] = 0
        self._send_queues[channel_id] = asyncio.Queue()
        self._send_tasks[channel_id] = asyncio.create_task(self._send_loop(channel_id))

        if asterisk_rtp_addr:
            self._audio_destinations[channel_id] = asterisk_rtp_addr
            self._source_to_channel[asterisk_rtp_addr] = channel_id
            logger.info(f"RTP: pre-set destination {asterisk_rtp_addr} for channel {channel_id}")

    def unregister_session(self, channel_id: str):
        self._sessions.pop(channel_id, None)
        self._seq.pop(channel_id, None)
        self._ts.pop(channel_id, None)
        self._audio_destinations.pop(channel_id, None)
        stale_sources = [src for src, cid in self._source_to_channel.items() if cid == channel_id]
        for src in stale_sources:
            self._source_to_channel.pop(src, None)
        if channel_id in self._send_tasks:
            self._send_tasks[channel_id].cancel()
            self._send_tasks.pop(channel_id)
        self._send_queues.pop(channel_id, None)

    async def _on_rtp_received(self, ulaw_payload: bytes, addr: tuple):
        """Receive caller audio from Asterisk, convert to 16kHz PCM, forward to Gemini."""
        from backend.services.audio_processor import ulaw_to_gemini_pcm

        self._recv_count += 1
        # Log first 3 packets and every 200th to confirm Asterisk→FastAPI is flowing
        if self._recv_count <= 3 or self._recv_count % 200 == 0:
            logger.info(f"RTP inbound #{self._recv_count}: {len(ulaw_payload)}B from {addr}")

        pcm16k = ulaw_to_gemini_pcm(ulaw_payload)

        channel_id = self._source_to_channel.get(addr)
        if channel_id is None:
            # Fallback when source wasn't pre-mapped (e.g., Asterisk changed RTP port).
            for cid, dest in self._audio_destinations.items():
                if dest == addr:
                    channel_id = cid
                    self._source_to_channel[addr] = cid
                    break

        if channel_id is None and len(self._sessions) == 1:
            channel_id = next(iter(self._sessions.keys()))
            self._source_to_channel[addr] = channel_id
            self._audio_destinations[channel_id] = addr
            logger.info(f"RTP: learned source {addr} for channel {channel_id}")

        if channel_id is None:
            logger.warning(f"RTP: dropping inbound packet from unknown source {addr}")
            return

        session = self._sessions.get(channel_id)
        if not session:
            return

        prev = self._audio_destinations.get(channel_id)
        if prev != addr:
            logger.info(f"RTP: destination updated {prev} → {addr} for channel {channel_id}")
            self._audio_destinations[channel_id] = addr
            self._source_to_channel[addr] = channel_id

        if session.is_running:
            await session.send_audio_bytes(pcm16k)

    async def _send_loop(self, channel_id: str):
        """Pace outgoing RTP frames to Asterisk at 20ms intervals via raw socket."""
        queue = self._send_queues.get(channel_id)
        if not queue:
            return
        frame_size = 160  # 20ms at 8kHz ulaw
        frames_sent = 0
        try:
            while True:
                frame = await queue.get()
                dest = self._audio_destinations.get(channel_id)
                if dest and self._transport:
                    seq = self._seq.get(channel_id, 0)
                    ts = self._ts.get(channel_id, 0)
                    pkt = _build_rtp(frame, seq, ts, self._ssrc)
                    try:
                        # Use transport bound on RTP_LISTEN_PORT so source tuple remains stable (fastapi:5004).
                        self._transport.sendto(pkt, dest)
                        frames_sent += 1
                        if frames_sent <= 5 or frames_sent % 100 == 0:
                            logger.info(f"RTP _send_loop: sent frame #{frames_sent} → {dest}")
                    except Exception as e:
                        logger.error(f"RTP sendto {dest} failed: {e}")
                    self._seq[channel_id] = (seq + 1) & 0xFFFF
                    self._ts[channel_id] = (ts + frame_size) & 0xFFFFFFFF
                else:
                    logger.warning(
                        f"RTP _send_loop: dropping frame — dest={dest}, transport={self._transport is not None}"
                    )
                await asyncio.sleep(0.02)  # 20ms pacing matches G.711 frame rate
        except asyncio.CancelledError:
            logger.info(f"RTP _send_loop: finished — sent {frames_sent} frames for {channel_id}")

    async def queue_audio(self, gemini_pcm24k: bytes, channel_id: str):
        """Receive Gemini 24kHz PCM, convert to ulaw frames, enqueue for paced delivery."""
        queue = self._send_queues.get(channel_id)
        if not queue:
            logger.warning(f"queue_audio: no send queue for channel {channel_id}")
            return

        from backend.services.audio_processor import gemini_pcm_to_ulaw
        ulaw = gemini_pcm_to_ulaw(gemini_pcm24k)

        frame_size = 160
        frames_queued = 0
        for i in range(0, len(ulaw), frame_size):
            frame = ulaw[i:i + frame_size]
            if len(frame) < frame_size:
                frame = frame.ljust(frame_size, b'\xff')  # pad with ulaw silence (0xFF)
            queue.put_nowait(frame)
            frames_queued += 1

        logger.info(
            f"queue_audio: queued {frames_queued} frames "
            f"({len(gemini_pcm24k)} bytes from Gemini) for {channel_id}"
        )


rtp_bridge = RTPBridge()
