"""FastAPI bridge: Asterisk ARI/ExternalMedia <-> Gemini Live.

Single-call demo. One Asterisk channel at a time enters Stasis, we attach an
ExternalMedia RTP leg pointed at this container's UDP port, and we relay
audio to/from a per-call Gemini Live WebSocket session.

Audio path follows the pattern used by Google's official
gemini-live-telephony reference (GoogleCloudPlatform/generative-ai) plus
WebRTC-style audio pre-processing to make telephony audio look like the
mic-direct audio Gemini's automatic VAD was trained on:

- Inbound  (caller -> Gemini):
    PCMU 8 kHz RTP frame
    -> PCM16 8 kHz
    -> libsamplerate polyphase up to PCM16 16 kHz
    -> WebRTC Audio Processing Module: AEC3 + NS + AGC2 + high-pass
       (echo canceller fed with Gemini's outbound audio as far-end)
    -> 20 ms (640 B) chunks streamed continuously via
       session.send_realtime_input(audio=...).
  The APM step is what `getUserMedia({audio:true})` gives the browser
  for free: it removes the softphone speaker -> mic acoustic loop,
  cleans line/codec noise, and normalises amplitude. Gemini's automatic
  VAD is trained on this kind of pre-processed signal; raw telephony
  audio causes it to miss subsequent turns.
- Outbound (Gemini -> caller): variable-size 24 kHz PCM16 chunks ->
  libsamplerate down to 8 kHz -> ulaw -> 20 ms RTP frames -> paced sender
  that emits exactly one frame every 20 ms wall-clock. Asterisk's
  jitter buffer expects ptime-paced RTP. The same 24 kHz chunk is also
  resampled in parallel down to 16 kHz and fed into the APM as the AEC
  far-end reference, so the echo canceller knows what we just sent and
  can subtract its return path from the inbound mic stream.

Turn detection and interruption are owned by Gemini (automatic VAD +
START_OF_ACTIVITY_INTERRUPTS). The bridge does NOT do client-side VAD.
The combination "WebRTC APM + Gemini automatic VAD" is the same shape
the React gemini-sales-agent uses (browser AEC/NS/AGC + Gemini VAD);
we just do the APM on the server because phone audio arrives raw.

TTS gating and echo gates are OFF by default (same as the React
gemini-sales-agent reference). Phone audio has no speaker->mic loop;
Gemini's default automatic VAD owns turn detection. Only interruption
(clear playback queue) is handled client-side, matching React.

Why libsamplerate instead of audioop.ratecv: ratecv is a one-tap IIR
documented as "a simple digital filter"; it loses HF detail and weakens
VAD pickup on already-narrow telephony audio. libsamplerate (sinc
polyphase) is what Google's own telephony sample uses.
"""

from __future__ import annotations

import asyncio
import audioop
import json
import logging
import os
import socket
import struct
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

import httpx
import numpy as np
import samplerate
import websockets
from fastapi import FastAPI
from google import genai
from google.genai import types

try:
    from pywebrtc_audio import AudioProcessor as _WebRTCAudioProcessor
    _WEBRTC_APM_AVAILABLE = True
except ImportError:  # pragma: no cover -- container is built with the wheel.
    _WebRTCAudioProcessor = None  # type: ignore[assignment]
    _WEBRTC_APM_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("gemini-bridge")


PTIME_MS = 20
SAMPLES_PER_FRAME_8K = 8000 * PTIME_MS // 1000  # 160
FRAME_BYTES_PCM16_8K = SAMPLES_PER_FRAME_8K * 2  # 320 bytes
ULAW_FRAME_BYTES = SAMPLES_PER_FRAME_8K  # 160 bytes per 20 ms

# Gemini wants raw PCM16 at 16 kHz. The React reference
# (gemini-sales-agent) uses a ScriptProcessorNode with a 4096-sample
# buffer at 16 kHz, which dispatches a send every 256 ms (~4 Hz).
# That low rate keeps the model's state machine happy across many
# turns. Higher rates (we previously sent at 50 Hz) appear to
# destabilise multi-turn conversations on the preview models.
GEMINI_CHUNK_MS = int(os.getenv("GEMINI_CHUNK_MS", "256"))
GEMINI_CHUNK_BYTES = 16000 * 2 * GEMINI_CHUNK_MS // 1000

# WebRTC Audio Processing Module (APM). This is the same pipeline a
# Chrome tab gets when you call getUserMedia({audio:true}): AEC3 (echo
# cancellation), noise suppression, automatic gain control, and an HP
# filter. We run it on the inbound (caller -> Gemini) path so Gemini's
# automatic VAD sees an audio signal in the same shape it was trained
# on. Browser clients get this for free; phone callers do not.
APM_ENABLED = os.getenv("APM_ENABLED", "0") not in {"0", "false", "False", ""}
APM_AEC = os.getenv("APM_AEC", "1") not in {"0", "false", "False", ""}
APM_NS = os.getenv("APM_NS", "1") not in {"0", "false", "False", ""}
APM_AGC = os.getenv("APM_AGC", "1") not in {"0", "false", "False", ""}
APM_HP = os.getenv("APM_HP", "1") not in {"0", "false", "False", ""}
# Noise suppression level: 0=6dB, 1=12dB, 2=18dB, 3=21dB. 2 is the
# Chrome default and works well for telephony codec hiss.
APM_NS_LEVEL = int(os.getenv("APM_NS_LEVEL", "2"))
# AEC stream-delay hint in ms. This is roughly: time from Gemini emitting
# a sample to that sample coming back through the softphone mic. For a
# local softphone over LAN it is ~150 ms (RTP -> Asterisk jitter buffer
# -> SIP -> softphone playout -> acoustic -> mic -> SIP -> Asterisk ->
# RTP back). APM also auto-tracks delay internally; this is just a hint.
APM_STREAM_DELAY_MS = int(os.getenv("APM_STREAM_DELAY_MS", "150"))
# Cap on AGC adaptive gain (dB). The default 50 dB is too aggressive on
# already-quiet phone audio and will amplify background noise. ~24-30 dB
# is a good telephony range.
APM_AGC_MAX_GAIN_DB = float(os.getenv("APM_AGC_MAX_GAIN_DB", "30"))

# Static pre-gain applied BEFORE the APM. AGC handles dynamic levelling
# but it can only attenuate -- it needs a signal in a reasonable range to
# start with. ulaw -> upsampled audio is often quite quiet, so we add a
# small lift here. If APM_AGC is disabled, this acts as the only gain.
# Set to 1.0 to disable.
INBOUND_GAIN = float(os.getenv("INBOUND_GAIN", "1.5"))

# Optional TTS/echo gating (OFF by default — React sends mic always).
TTS_GATING_ENABLED = os.getenv("TTS_GATING", "0") not in {"0", "false", "False", ""}
GATE_TAIL_MS = float(os.getenv("TTS_GATE_TAIL_MS", "200"))
ECHO_GATE_SEC = float(os.getenv("ECHO_GATE_SEC", "0.5"))

# (Nudge / speech-activity tracking constants removed -- they were
# part of the cookbook#1228 workaround that turned out to make
# multi-turn worse, not better, by polluting the conversation with
# injected text. The React reference doesn't have any of this.)

# Ring the caller while Gemini connects (standard telephony UX).
RING_MIN_SEC = float(os.getenv("RING_MIN_SEC", "3"))
GEMINI_READY_TIMEOUT_SEC = float(os.getenv("GEMINI_READY_TIMEOUT_SEC", "20"))

# WebRTC APM operates on fixed 10 ms frames. At 16 kHz that's 160
# samples / 320 bytes PCM16.
APM_FRAME_SAMPLES_16K = 16000 * 10 // 1000  # 160
APM_FRAME_BYTES_16K = APM_FRAME_SAMPLES_16K * 2  # 320

# Pre-built silence buffers for substituting inbound user audio while
# TTS gating is engaged. One per chunk size we use.
_SILENCE_CHUNK_16K = b"\x00" * GEMINI_CHUNK_BYTES
# A 10 ms (320 B) buffer of PCM16 silence used as the APM far-end
# reference whenever no AI audio is currently in flight.
_SILENCE_10MS_16K = b"\x00" * APM_FRAME_BYTES_16K

# Watchdog: if the Gemini send loop is unable to drain queued audio for
# this long, the WebSocket is considered hung and we tear it down so
# the per-call _gemini_loop can reconnect. The 1011 keepalive timeout
# from the websockets library is 40s; we want to react faster than that.
SEND_LOOP_HUNG_SEC = float(os.getenv("SEND_LOOP_HUNG_SEC", "3.0"))

# Auto-greeting: when the call is fully bridged, kick the model to
# speak first. Without this the caller hears silence until they say
# something, which they (rightly) experience as a slow agent. The
# React reference does the same -- it doesn't wait for user input
# before producing initial audio (the user can interrupt anytime).
_DEFAULT_AUTO_GREETING = (
    "Greet the caller warmly in one natural sentence, introduce yourself by name, "
    "and ask how you can help. Use your preloaded knowledge context — do not stay silent."
)
_auto_greet_env = os.getenv("AUTO_GREETING")
AUTO_GREETING = (
    _auto_greet_env.strip()
    if _auto_greet_env is not None and _auto_greet_env.strip()
    else _DEFAULT_AUTO_GREETING
)


def _join_transcript_fragments(parts: list[str]) -> str:
    """Merge streaming transcription fragments into one readable paragraph."""
    if not parts:
        return ""
    combined = ""
    for raw in parts:
        part = raw.strip()
        if not part:
            continue
        if not combined:
            combined = part
            continue
        # Cumulative stream: newer text extends or replaces prior
        if part.startswith(combined):
            combined = part
        elif combined.startswith(part):
            continue
        elif part in combined:
            continue
        elif combined.endswith(part):
            continue
        else:
            combined = combined.rstrip() + (" " if not combined.endswith(" ") and not part.startswith(" ") else "") + part.lstrip()
    return combined.strip()


# ---------------------------------------------------------- resampling helpers


def _pcm16_to_float32(pcm: bytes) -> np.ndarray:
    """Decode little-endian PCM16 bytes to float32 in [-1.0, 1.0]."""
    if not pcm:
        return np.empty(0, dtype=np.float32)
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    samples *= 1.0 / 32768.0
    return samples


def _float32_to_pcm16(samples: np.ndarray) -> bytes:
    """Encode float32 samples in [-1.0, 1.0] to little-endian PCM16 bytes."""
    if samples.size == 0:
        return b""
    scaled = np.clip(samples, -1.0, 1.0) * 32767.0
    return scaled.astype(np.int16).tobytes()


def _resample_pcm16(
    pcm: bytes,
    resampler: samplerate.Resampler,
    ratio: float,
) -> bytes:
    """Resample a PCM16 mono fragment through a streaming libsamplerate
    Resampler. ratio = output_rate / input_rate.

    The Resampler holds state across calls so 20 ms streaming chunks are
    joined smoothly without filter ringing at the boundaries.
    """
    if not pcm:
        return b""
    samples = _pcm16_to_float32(pcm)
    out = resampler.process(samples, ratio, end_of_input=False)
    return _float32_to_pcm16(out)


def _build_apm():
    """Construct a fresh WebRTC AudioProcessor configured for telephony.

    Returns None if the pywebrtc-audio wheel is not available or APM is
    disabled by env. Each call gets its own instance because AEC carries
    internal state (delay history, NS spectrum estimate, AGC level) that
    must not leak between calls.
    """
    if not _WEBRTC_APM_AVAILABLE or not APM_ENABLED:
        return None
    return _WebRTCAudioProcessor(
        sample_rate=16000,
        num_channels=1,
        echo_cancellation=APM_AEC,
        noise_suppression=APM_NS,
        auto_gain_control=APM_AGC,
        high_pass_filter=APM_HP,
        ns_level=APM_NS_LEVEL,
        agc_max_gain_db=APM_AGC_MAX_GAIN_DB,
        stream_delay_ms=APM_STREAM_DELAY_MS,
    )


def getenv(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def parse_rtp(packet: bytes) -> tuple[int, int, int, bytes]:
    if len(packet) < 12:
        raise ValueError("RTP packet too small")

    b1, b2, seq, ts, _ssrc = struct.unpack("!BBHII", packet[:12])
    version = b1 >> 6
    if version != 2:
        raise ValueError(f"Unsupported RTP version: {version}")

    payload_type = b2 & 0x7F
    csrc_count = b1 & 0x0F
    header_len = 12 + csrc_count * 4
    payload = packet[header_len:]
    return payload_type, seq, ts, payload


def build_rtp_packet(
    payload: bytes,
    sequence_number: int,
    timestamp: int,
    ssrc: int,
    payload_type: int = 0,
    marker: int = 0,
) -> bytes:
    v_p_x_cc = 0x80  # version 2, no padding/extension/csrc
    m_pt = ((marker & 0x01) << 7) | (payload_type & 0x7F)
    header = struct.pack(
        "!BBHII",
        v_p_x_cc,
        m_pt,
        sequence_number & 0xFFFF,
        timestamp & 0xFFFFFFFF,
        ssrc & 0xFFFFFFFF,
    )
    return header + payload


@dataclass
class CallState:
    bridge_id: Optional[str] = None
    human_channel_id: Optional[str] = None
    external_channel_id: Optional[str] = None
    asterisk_rtp_addr: Optional[tuple[str, int]] = None

    tx_seq: int = 1
    tx_timestamp: int = 0
    tx_ssrc: int = field(default_factory=lambda: uuid.uuid4().int & 0xFFFFFFFF)

    # libsamplerate Resampler instances. `sinc_fastest` is the lightest
    # polyphase preset and is still vastly higher fidelity than
    # audioop.ratecv. Each direction needs its own instance because they
    # carry independent filter state.
    rx_resampler: samplerate.Resampler = field(
        default_factory=lambda: samplerate.Resampler("sinc_fastest", channels=1)
    )  # Gemini 24k -> 8k for Asterisk
    tx_resampler: samplerate.Resampler = field(
        default_factory=lambda: samplerate.Resampler("sinc_fastest", channels=1)
    )  # Asterisk 8k -> 16k for Gemini
    far_resampler: samplerate.Resampler = field(
        default_factory=lambda: samplerate.Resampler("sinc_fastest", channels=1)
    )  # Gemini 24k -> 16k for APM far-end (AEC reference)

    # Leftover 8 kHz PCM16 awaiting 20 ms framing.
    out_pcm8_buffer: bytes = b""
    # Raw inbound 16 kHz PCM16 awaiting 10 ms framing for the APM.
    in_pcm16k_buffer: bytes = b""
    # APM-cleaned 16 kHz PCM16 awaiting 20 ms framing for Gemini.
    in_pcm16k_clean_buffer: bytes = b""
    # Rolling buffer of AI audio at 16 kHz that the APM uses as its AEC
    # far-end reference. Appended whenever Gemini delivers audio,
    # consumed in 10 ms slices by each APM.process() call. If empty,
    # silence is used (which is correct when no AI audio is in flight).
    far_end_buf: bytes = b""

    # Per-call WebRTC Audio Processing Module. Holds AEC delay history,
    # NS spectrum, and AGC adaptive gain. Constructed on StasisStart so
    # there's no cross-call leakage. None if APM is disabled.
    apm: Optional[object] = None
    apm_frames: int = 0

    active: bool = False

    # ---- Diagnostic counters (reset per call) ----
    rtp_in_frames: int = 0
    rtp_out_frames: int = 0
    gemini_in_chunks: int = 0
    gemini_in_bytes: int = 0
    gemini_out_bytes: int = 0
    gemini_turn_completes: int = 0
    gemini_interruptions: int = 0
    last_user_tx_ts: float = 0.0
    last_gemini_audio_ts: float = 0.0

    # Running max RMS of inbound audio (post-gain) over the last stats
    # window. Reset by _stats_loop after each log. Useful to confirm the
    # caller's voice is actually loud at our RTP listener -- a quiet
    # window combined with a stuck VAD points at the mic / Zoiper /
    # codec side; a loud window with a stuck VAD points at Gemini.
    in_rms_peak: int = 0
    in_rms_sum: int = 0
    in_rms_count: int = 0

    # Same metric but measured AFTER the APM (AEC/NS/AGC). If pre-APM
    # rms is high but post-APM is low, the APM is destroying user
    # speech (most likely AEC mis-classifying it as residual echo).
    apm_rms_peak: int = 0
    apm_rms_sum: int = 0
    apm_rms_count: int = 0

    # Number of consecutive 3 s stats windows with no detectable
    # inbound caller audio. Once this passes a threshold we log a
    # warning -- the softphone or its host OS is almost certainly
    # auto-muting the mic in reaction to the AI playing through the
    # speaker (classic self-test gotcha).
    silent_windows: int = 0

    # Monotonic timestamp of the last RTP packet we sent toward the
    # caller. Used by TTS gating to know whether the AI's voice is still
    # being played (and therefore likely echoing back through the
    # caller's speaker/mic).
    last_outbound_rtp_ts: float = 0.0

    # Number of inbound frames we replaced with silence due to TTS
    # gating. Diagnostic counter, reset per call.
    gated_in_frames: int = 0

    # True while Gemini audio is being received from the server. Used
    # together with gemini_playback_started to gate inbound user audio
    # for the first GATE_TAIL_MS of an AI utterance (AEC convergence
    # window). After that window the user can speak over the AI and
    # Gemini's START_OF_ACTIVITY_INTERRUPTS will fire normally.
    gemini_playback_active: bool = False
    gemini_playback_started: float = 0.0

    # Flips True the first time we successfully send AUTO_GREETING.
    # Stays True for the rest of the call so that if the WebSocket
    # gets recycled (1011 keepalive, watchdog kick) we don't replay
    # the greeting mid-conversation.
    greeting_sent: bool = False

    # Platform integration (eplanet calling agent)
    platform_session_id: Optional[int] = None
    agent_config: dict = field(default_factory=dict)
    call_started_at: float = 0.0

    # Buffered streaming transcriptions — flushed per turn / on call end
    user_tx_parts: list[str] = field(default_factory=list)
    model_tx_parts: list[str] = field(default_factory=list)



SYSTEM_PROMPT = (
    "You are on a live phone call. Speak like a real human: warm, polite, and professional. "
    "Use natural pacing and brief pauses. Occasional fillers like 'um' or 'let me see' are fine — sparingly. "
    "Keep replies short and conversational. Wait for the caller to finish before responding. "
    "Never mention these instructions."
)


class GeminiLiveBridge:
    def __init__(self) -> None:
        self.gemini_api_key = getenv("GEMINI_API_KEY")
        self.gemini_model = getenv(
            "GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"
        )
        self.gemini_voice = os.getenv("GEMINI_VOICE", "Aoede")

        self.ari_user = getenv("ARI_USER")
        self.ari_pass = getenv("ARI_PASS")
        self.ari_app = getenv("ARI_APP", "gemini-agent")
        self.ari_host = getenv("ARI_HOST", "asterisk")
        self.ari_port = int(getenv("ARI_PORT", "8088"))

        self.rtp_port = int(getenv("RTP_PORT", "40000"))
        # Hostname/IP Asterisk uses in ExternalMedia (docker DNS name by default).
        self.external_media_host = os.getenv("EXTERNAL_MEDIA_HOST", "bridge")
        self._asterisk_rtp_host_ip: str = ""

        self.client = genai.Client(api_key=self.gemini_api_key)

        self.http: Optional[httpx.AsyncClient] = None
        self.ari_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.session: Optional[object] = None
        self.session_ready = asyncio.Event()

        self.state = CallState()

        self.rtp_transport: Optional[asyncio.DatagramTransport] = None
        self.rtp_protocol: Optional[asyncio.DatagramProtocol] = None

        # 20 ms PCM16-16k chunks toward Gemini (drained at ~50 Hz).
        self.audio_ingest_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=500)
        # 20 ms ulaw payloads toward Asterisk; drained at 50 Hz by the pacer.
        self.rtp_out_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1000)

        self._tasks: list[asyncio.Task] = []
        # Per-call Gemini session task. Re-created on every StasisStart
        # and cancelled on cleanup. We deliberately do NOT keep a
        # bridge-global Gemini session because that leaks conversation
        # context, VAD state, and buffered audio across calls. This
        # matches Google's official telephony reference (run_gemini_session
        # lives for the duration of a single call) and the React
        # gemini-sales-agent (session per connect()).
        self._gemini_task: Optional[asyncio.Task] = None
        self._call_active = asyncio.Event()
        self._stopping = asyncio.Event()

        self.platform_url = os.getenv("PLATFORM_URL", "").rstrip("/")
        self.platform_token = os.getenv("BRIDGE_INTERNAL_TOKEN", "")

    @staticmethod
    def _resolve_udp_host(host: str) -> str:
        """Resolve a hostname to an IPv4 address for UDP sendto (uvloop)."""
        host = host.strip()
        try:
            socket.inet_pton(socket.AF_INET, host)
            return host
        except OSError:
            pass
        infos = socket.getaddrinfo(
            host, None, family=socket.AF_INET, type=socket.SOCK_DGRAM
        )
        if not infos:
            raise RuntimeError(f"Could not resolve UDP host {host!r}")
        return infos[0][4][0]

    def _resolve_asterisk_rtp_host(self, host: str) -> str:
        """Map loopback to a reachable address when Asterisk uses host networking."""
        if host in ("127.0.0.1", "0.0.0.0", "::1", "localhost"):
            if self._asterisk_rtp_host_ip:
                return self._asterisk_rtp_host_ip
            return self._resolve_udp_host(
                os.getenv("ASTERISK_RTP_HOST", "host.docker.internal")
            )
        return self._resolve_udp_host(host)

    def _send_rtp(self, packet: bytes, addr: tuple[str, int]) -> None:
        """Send RTP, ensuring the destination host is a numeric IP."""
        host, port = addr
        if not host.replace(".", "").isdigit():
            host = self._resolve_udp_host(host)
        assert self.rtp_transport is not None
        self.rtp_transport.sendto(packet, (host, port))

    async def start(self) -> None:
        self.http = httpx.AsyncClient(
            base_url=f"http://{self.ari_host}:{self.ari_port}/ari",
            auth=(self.ari_user, self.ari_pass),
            timeout=30.0,
        )

        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: RTPProtocol(self),
            local_addr=("0.0.0.0", self.rtp_port),
        )
        self.rtp_transport = transport
        self.rtp_protocol = protocol

        # Only needed when Asterisk runs on host network (loopback in channel vars).
        self._asterisk_rtp_host_ip = ""
        asterisk_rtp_host = os.getenv("ASTERISK_RTP_HOST", "")
        if asterisk_rtp_host:
            self._asterisk_rtp_host_ip = self._resolve_udp_host(asterisk_rtp_host)
            logger.info(
                "Asterisk RTP return path: %s -> %s",
                asterisk_rtp_host,
                self._asterisk_rtp_host_ip,
            )

        # Note: no global Gemini session task here. Gemini is connected
        # only when a real call enters Stasis (see _handle_stasis_start)
        # and disconnected in cleanup_call.
        await self._wait_for_asterisk_ari()
        self._tasks.append(asyncio.create_task(self._ari_event_loop(), name="ari-event-loop"))
        self._tasks.append(asyncio.create_task(self._rtp_pacer_loop(), name="rtp-pacer-loop"))
        self._tasks.append(asyncio.create_task(self._stats_loop(), name="stats-loop"))

        apm_status = "off"
        if _WEBRTC_APM_AVAILABLE and APM_ENABLED:
            apm_status = (
                f"aec={int(APM_AEC)} ns={int(APM_NS)}(L{APM_NS_LEVEL}) "
                f"agc={int(APM_AGC)}(<= {APM_AGC_MAX_GAIN_DB:.0f}dB) hp={int(APM_HP)}"
            )
        elif APM_ENABLED and not _WEBRTC_APM_AVAILABLE:
            apm_status = "unavailable (pywebrtc-audio not importable)"

        logger.info(
            "Bridge started. model=%s voice=%s RTP=%s ext_media=%s:%s gain=%.2fx apm=[%s] "
            "mode=react-minimal chunk=%dms ring_min=%.0fs gemini_timeout=%.0fs "
            "auto_greet=%s",
            self.gemini_model,
            self.gemini_voice,
            self.rtp_port,
            self.external_media_host,
            self.rtp_port,
            INBOUND_GAIN,
            apm_status,
            GEMINI_CHUNK_MS,
            RING_MIN_SEC,
            GEMINI_READY_TIMEOUT_SEC,
            "on" if AUTO_GREETING else "off",
        )

    async def _stats_loop(self) -> None:
        """Every 3 seconds during an active call, log audio flow counters."""
        while not self._stopping.is_set():
            await asyncio.sleep(3.0)
            if not self.state.active:
                continue
            now = time.monotonic()
            since_user = (
                f"{now - self.state.last_user_tx_ts:.1f}s"
                if self.state.last_user_tx_ts
                else "never"
            )
            since_gem = (
                f"{now - self.state.last_gemini_audio_ts:.1f}s"
                if self.state.last_gemini_audio_ts
                else "never"
            )
            # in_rms_peak is in PCM16 units (0..32767). >=2000 = clearly
            # audible speech, ~500-1500 = quiet speech, <300 = effectively
            # silence/line noise.
            rms_peak = self.state.in_rms_peak
            rms_mean = (
                self.state.in_rms_sum // self.state.in_rms_count
                if self.state.in_rms_count
                else 0
            )
            self.state.in_rms_peak = 0
            self.state.in_rms_sum = 0
            self.state.in_rms_count = 0
            apm_rms_peak = self.state.apm_rms_peak
            apm_rms_mean = (
                self.state.apm_rms_sum // self.state.apm_rms_count
                if self.state.apm_rms_count
                else 0
            )
            self.state.apm_rms_peak = 0
            self.state.apm_rms_sum = 0
            self.state.apm_rms_count = 0

            # Watchdog: caller audio absent for too long. Almost always
            # the softphone auto-muting on speaker output.
            if (
                rms_peak < 100
                and self.state.rtp_in_frames > 50
                and self._call_active.is_set()
                and self.state.human_channel_id
            ):
                self.state.silent_windows += 1
                if self.state.silent_windows == 3:
                    logger.warning(
                        "No caller audio detected for ~9s while RTP "
                        "packets ARE arriving (rms_peak=%d). The "
                        "softphone is likely auto-muting your mic in "
                        "response to the AI playing through your "
                        "speakers. Plug in headphones or test from a "
                        "separate device. (Disable Zoiper's 'Echo "
                        "Cancellation' under Settings > Audio Codecs "
                        "if using Zoiper.)",
                        rms_peak,
                    )
            else:
                self.state.silent_windows = 0
            speech_prob = None
            if self.state.apm is not None:
                try:
                    speech_prob = float(self.state.apm.speech_probability())
                except Exception:
                    speech_prob = None
            logger.info(
                "STATS rtp_in=%d rtp_out=%d gemini_in=%d (%dB) gemini_out=%dB "
                "turns_complete=%d interruptions=%d last_user_tx=%s last_gem_audio=%s "
                "q_in=%d q_out=%d in_rms=p%d/m%d apm_rms=p%d/m%d gated=%d "
                "apm_frames=%d far_buf=%dB apm_speech_prob=%s",
                self.state.rtp_in_frames,
                self.state.rtp_out_frames,
                self.state.gemini_in_chunks,
                self.state.gemini_in_bytes,
                self.state.gemini_out_bytes,
                self.state.gemini_turn_completes,
                self.state.gemini_interruptions,
                since_user,
                since_gem,
                self.audio_ingest_queue.qsize(),
                self.rtp_out_queue.qsize(),
                rms_peak,
                rms_mean,
                apm_rms_peak,
                apm_rms_mean,
                self.state.gated_in_frames,
                self.state.apm_frames,
                len(self.state.far_end_buf),
                f"{speech_prob:.2f}" if speech_prob is not None else "n/a",
            )

    async def stop(self) -> None:
        self._stopping.set()
        self._call_active.clear()

        if self._gemini_task is not None and not self._gemini_task.done():
            self._gemini_task.cancel()
            try:
                await self._gemini_task
            except (asyncio.CancelledError, Exception):
                pass
            self._gemini_task = None

        for task in self._tasks:
            task.cancel()

        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        if self.ari_ws is not None:
            try:
                await self.ari_ws.close()
            except Exception:
                pass

        if self.http is not None:
            await self.http.aclose()

        if self.rtp_transport is not None:
            self.rtp_transport.close()

    # ------------------------------------------------------------------ ARI

    async def _wait_for_asterisk_ari(self) -> None:
        """Block until Asterisk ARI accepts TCP (compose starts us after its healthcheck)."""
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline and not self._stopping.is_set():
            try:
                await asyncio.wait_for(
                    asyncio.open_connection(self.ari_host, self.ari_port),
                    timeout=3.0,
                )
                logger.info(
                    "Asterisk ARI reachable at %s:%s",
                    self.ari_host,
                    self.ari_port,
                )
                return
            except Exception:
                await asyncio.sleep(2.0)
        logger.warning(
            "Asterisk ARI not reachable at %s:%s; will retry in the event loop",
            self.ari_host,
            self.ari_port,
        )

    async def _ari_event_loop(self) -> None:
        ws_url = (
            f"ws://{self.ari_host}:{self.ari_port}/ari/events"
            f"?api_key={self.ari_user}:{self.ari_pass}&app={self.ari_app}"
            f"&subscribeAll=true"
        )

        while not self._stopping.is_set():
            try:
                logger.info("Connecting to ARI websocket: ws://%s:%s/ari/events", self.ari_host, self.ari_port)
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.ari_ws = ws
                    logger.info("ARI websocket connected; app=%s", self.ari_app)
                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                        except Exception:
                            logger.exception("Bad ARI event JSON")
                            continue

                        etype = event.get("type")
                        if etype == "StasisStart":
                            await self._handle_stasis_start(event)
                        elif etype == "StasisEnd":
                            await self._handle_stasis_end(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("ARI loop error: %s; reconnecting in 2s", exc)
                await asyncio.sleep(2)

    async def _handle_stasis_start(self, event: dict) -> None:
        channel = event["channel"]
        channel_id = channel["id"]
        args = event.get("args") or []

        if args and args[0] == "external_media":
            logger.info("ExternalMedia channel entered Stasis: %s", channel_id)
            self.state.external_channel_id = channel_id
            return

        if self.state.active:
            logger.warning("A call is already active; hanging up new channel %s", channel_id)
            try:
                assert self.http is not None
                await self.http.delete(f"/channels/{channel_id}")
            except Exception:
                pass
            return

        self.state = CallState()
        self.state.active = True
        self.state.human_channel_id = channel_id
        self.state.apm = _build_apm()
        if self.state.apm is not None:
            logger.info(
                "APM enabled per-call: aec=%s ns=%s(level=%d) agc=%s(max=%.0fdB) "
                "hp=%s stream_delay=%dms",
                APM_AEC,
                APM_NS,
                APM_NS_LEVEL,
                APM_AGC,
                APM_AGC_MAX_GAIN_DB,
                APM_HP,
                APM_STREAM_DELAY_MS,
            )

        assert self.http is not None

        try:
            ring_started = time.monotonic()
            caller = channel.get("caller") or {}
            caller_id = caller.get("number") or channel.get("name")
            agent_slug = args[0] if args else None
            dialplan = channel.get("dialplan") or {}
            dialed_extension = dialplan.get("exten")

            await self._platform_call_start(
                channel_id, caller_id, agent_slug, dialed_extension
            )

            # 1) Open Gemini while the phone is still ringing (not answered).
            self._call_active.set()
            self._gemini_task = asyncio.create_task(
                self._gemini_loop(), name=f"gemini-loop-{channel_id}"
            )

            # 2) Ringback so the caller hears ringing while we connect.
            try:
                await self.http.post(f"/channels/{channel_id}/ring")
                logger.info("Ringing channel %s while Gemini connects", channel_id)
            except Exception:
                logger.warning("ARI ring failed for %s (continuing)", channel_id)

            # 3) Wait for Gemini session (with timeout).
            try:
                await asyncio.wait_for(
                    self.session_ready.wait(),
                    timeout=GEMINI_READY_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "Gemini not ready within %.0fs; hanging up %s",
                    GEMINI_READY_TIMEOUT_SEC,
                    channel_id,
                )
                await self.cleanup_call()
                try:
                    await self.http.delete(f"/channels/{channel_id}")
                except Exception:
                    pass
                return

            # 4) Minimum ring time so setup never feels instant/dead-air.
            elapsed = time.monotonic() - ring_started
            if elapsed < RING_MIN_SEC:
                await asyncio.sleep(RING_MIN_SEC - elapsed)

            gemini_wait = time.monotonic() - ring_started
            logger.info(
                "Gemini ready after %.1fs; answering channel %s",
                gemini_wait,
                channel_id,
            )

            # 5) Now answer and wire audio (caller hears agent immediately).
            await self.http.post(f"/channels/{channel_id}/answer")

            bridge_resp = await self.http.post("/bridges", params={"type": "mixing"})
            bridge_resp.raise_for_status()
            bridge_obj = bridge_resp.json()
            self.state.bridge_id = bridge_obj["id"]

            await self.http.post(
                f"/bridges/{self.state.bridge_id}/addChannel",
                params={"channel": channel_id},
            )

            ext_resp = await self.http.post(
                "/channels/externalMedia",
                params={
                    "app": self.ari_app,
                    "external_host": f"{self.external_media_host}:{self.rtp_port}",
                    "format": "ulaw",
                    "direction": "both",
                    "data": "external_media",
                },
            )
            ext_resp.raise_for_status()
            ext_channel = ext_resp.json()
            self.state.external_channel_id = ext_channel["id"]

            await self.http.post(
                f"/bridges/{self.state.bridge_id}/addChannel",
                params={"channel": self.state.external_channel_id},
            )

            await self._bootstrap_external_rtp(self.state.external_channel_id)

            logger.info(
                "Call ready: human=%s bridge=%s external=%s (setup %.1fs)",
                self.state.human_channel_id,
                self.state.bridge_id,
                self.state.external_channel_id,
                time.monotonic() - ring_started,
            )

        except Exception:
            logger.exception("Failed to set up call %s", channel_id)
            await self.cleanup_call()

    async def _bootstrap_external_rtp(self, external_channel_id: str) -> None:
        """Kick-start Asterisk UnicastRTP strict-RTP with outbound silence.

        ExternalMedia often waits for the first RTP from us before it
        forwards mixed caller audio to bridge:40000. Without this,
        rtp_in can stay at 0 (especially on physical phones where the
        phone→Asterisk leg is still learning).
        """
        assert self.http is not None
        if self.rtp_transport is None:
            return

        try:
            addr_resp = await self.http.get(
                f"/channels/{external_channel_id}/variable",
                params={"variable": "UNICASTRTP_LOCAL_ADDRESS"},
            )
            port_resp = await self.http.get(
                f"/channels/{external_channel_id}/variable",
                params={"variable": "UNICASTRTP_LOCAL_PORT"},
            )
            addr_resp.raise_for_status()
            port_resp.raise_for_status()
            port = int(port_resp.json().get("value", "0"))
            # Always send RTP to the Asterisk container by name (numeric IP for uvloop).
            host = self._resolve_udp_host("asterisk")
            if not host or port <= 0:
                logger.warning(
                    "Could not read UnicastRTP vars for %s", external_channel_id
                )
                return
            self.state.asterisk_rtp_addr = (host, port)
            logger.info(
                "ExternalMedia RTP send target: %s:%d (Asterisk UnicastRTP listener)",
                host,
                port,
            )
        except Exception:
            logger.exception("Failed to read UnicastRTP channel variables")
            return

        silence = b"\xff" * ULAW_FRAME_BYTES
        for _ in range(25):
            packet = build_rtp_packet(
                payload=silence,
                sequence_number=self.state.tx_seq,
                timestamp=self.state.tx_timestamp,
                ssrc=self.state.tx_ssrc,
                payload_type=0,
            )
            try:
                self._send_rtp(packet, self.state.asterisk_rtp_addr)
            except Exception:
                logger.exception("Bootstrap RTP send failed")
                break
            self.state.tx_seq = (self.state.tx_seq + 1) & 0xFFFF
            self.state.tx_timestamp = (
                self.state.tx_timestamp + SAMPLES_PER_FRAME_8K
            ) & 0xFFFFFFFF
            self.state.last_outbound_rtp_ts = time.monotonic()
            self.state.rtp_out_frames += 1
            await asyncio.sleep(PTIME_MS / 1000.0)
        logger.info(
            "Bootstrap sent %d RTP frames to Asterisk at %s:%d",
            25,
            self.state.asterisk_rtp_addr[0],
            self.state.asterisk_rtp_addr[1],
        )

    async def _handle_stasis_end(self, event: dict) -> None:
        channel_id = event["channel"]["id"]

        if channel_id == self.state.external_channel_id:
            logger.info("External media channel ended: %s", channel_id)
            return

        if channel_id != self.state.human_channel_id:
            return

        logger.info(
            "Human channel ended: %s (cause=%s %s)",
            channel_id,
            event.get("channel", {}).get("cause", "?"),
            event.get("channel", {}).get("cause_txt", ""),
        )
        await self.cleanup_call()

    async def cleanup_call(self) -> None:
        # Flush any buffered transcript before ending the platform session.
        await self._flush_all_transcripts()
        # Notify platform while session metadata is still in self.state.
        await self._platform_call_end()

        # Stop the per-call Gemini session FIRST so it stops touching
        # state/queues we're about to reset. The async with inside
        # _gemini_loop will close the WebSocket cleanly on cancellation.
        self._call_active.clear()
        if self._gemini_task is not None and not self._gemini_task.done():
            self._gemini_task.cancel()
            try:
                await self._gemini_task
            except (asyncio.CancelledError, Exception):
                pass
        self._gemini_task = None
        self.session_ready.clear()
        self.session = None

        if self.http is not None:
            try:
                if self.state.external_channel_id:
                    await self.http.delete(f"/channels/{self.state.external_channel_id}")
            except Exception:
                pass

            try:
                if self.state.bridge_id:
                    await self.http.delete(f"/bridges/{self.state.bridge_id}")
            except Exception:
                pass

        self.state = CallState()
        self._drain_queue(self.audio_ingest_queue)
        self._drain_queue(self.rtp_out_queue)
        logger.info("Call cleaned up; Gemini session closed")

    @staticmethod
    def _drain_queue(q: asyncio.Queue) -> None:
        while not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _platform_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.platform_token:
            headers["X-Bridge-Token"] = self.platform_token
        return headers

    async def _platform_call_start(
        self,
        channel_id: str,
        caller_id: Optional[str],
        agent_slug: Optional[str] = None,
        dialed_extension: Optional[str] = None,
    ) -> None:
        """Load per-call agent config from the platform API."""
        self.state.call_started_at = time.monotonic()
        fallback = {
            "model": self.gemini_model,
            "voice": self.gemini_voice,
            "system_instruction": SYSTEM_PROMPT,
            "tools": [],
            "agent_id": None,
        }
        if not self.platform_url:
            self.state.agent_config = fallback
            return
        try:
            assert self.http is not None
            payload: dict = {"channel_id": channel_id, "caller_id": caller_id}
            if agent_slug:
                payload["agent_slug"] = agent_slug
            if dialed_extension:
                payload["dialed_extension"] = dialed_extension
            resp = await self.http.post(
                f"{self.platform_url}/internal/calls/start",
                json=payload,
                headers=self._platform_headers(),
                timeout=10.0,
            )
            resp.raise_for_status()
            cfg = resp.json()
            self.state.platform_session_id = cfg.get("session_id")
            self.state.agent_config = cfg
            logger.info(
                "Platform call session=%s agent=%s",
                self.state.platform_session_id,
                cfg.get("agent_slug", "?"),
            )
        except Exception:
            logger.exception("Platform /internal/calls/start failed; using fallback config")
            self.state.agent_config = fallback

    async def _platform_transcript(self, role: str, text: str) -> None:
        if not self.platform_url or not self.state.platform_session_id or not text.strip():
            return
        try:
            assert self.http is not None
            await self.http.post(
                f"{self.platform_url}/internal/calls/transcript",
                json={
                    "session_id": self.state.platform_session_id,
                    "role": role,
                    "text": text,
                },
                headers=self._platform_headers(),
                timeout=5.0,
            )
        except Exception:
            logger.warning("Failed to post transcript to platform", exc_info=True)

    def _buffer_transcript(self, role: str, text: str) -> None:
        if not text or not text.strip():
            return
        if role == "user":
            self.state.user_tx_parts.append(text)
        else:
            self.state.model_tx_parts.append(text)

    async def _flush_transcript_role(self, role: str) -> None:
        parts = self.state.user_tx_parts if role == "user" else self.state.model_tx_parts
        merged = _join_transcript_fragments(parts)
        if role == "user":
            self.state.user_tx_parts = []
        else:
            self.state.model_tx_parts = []
        if merged:
            await self._platform_transcript(role, merged)

    async def _flush_all_transcripts(self) -> None:
        await self._flush_transcript_role("user")
        await self._flush_transcript_role("model")

    async def _on_turn_complete(self) -> None:
        """Flush buffered transcriptions at each turn boundary."""
        await self._flush_transcript_role("user")
        await self._flush_transcript_role("model")

    async def _platform_tool(
        self, tool_name: str, call_id: str, params: dict
    ) -> dict:
        if not self.platform_url or not self.state.platform_session_id:
            return {"id": call_id, "name": tool_name, "response": {"error": "no platform session"}}
        try:
            assert self.http is not None
            resp = await self.http.post(
                f"{self.platform_url}/internal/calls/tool",
                json={
                    "session_id": self.state.platform_session_id,
                    "agent_id": self.state.agent_config.get("agent_id"),
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "params": params,
                },
                headers=self._platform_headers(),
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.exception("Platform tool %s failed", tool_name)
            return {"id": call_id, "name": tool_name, "response": {"error": str(exc)}}

    async def _platform_call_end(self) -> None:
        if not self.platform_url or not self.state.platform_session_id:
            return
        duration = None
        if self.state.call_started_at:
            duration = time.monotonic() - self.state.call_started_at
        try:
            assert self.http is not None
            await self.http.post(
                f"{self.platform_url}/internal/calls/end",
                json={
                    "session_id": self.state.platform_session_id,
                    "channel_id": self.state.human_channel_id,
                    "duration_sec": duration,
                    "stats": {
                        "rtp_in": self.state.rtp_in_frames,
                        "rtp_out": self.state.rtp_out_frames,
                        "gemini_turns": self.state.gemini_turn_completes,
                        "interruptions": self.state.gemini_interruptions,
                    },
                },
                headers=self._platform_headers(),
                timeout=5.0,
            )
        except Exception:
            logger.warning("Failed to notify platform of call end", exc_info=True)

    def _build_live_config(self, cfg: dict) -> types.LiveConnectConfig:
        gemini_tools: list[types.Tool] = []
        for entry in cfg.get("tools") or []:
            if "function_declarations" in entry:
                decls = []
                for fd in entry["function_declarations"]:
                    decls.append(
                        types.FunctionDeclaration(
                            name=fd["name"],
                            description=fd.get("description"),
                            parameters=fd.get("parameters"),
                        )
                    )
                gemini_tools.append(types.Tool(function_declarations=decls))
            elif "google_search" in entry:
                gemini_tools.append(types.Tool(google_search=types.GoogleSearch()))

        kwargs: dict = {
            "response_modalities": [types.Modality.AUDIO],
            "input_audio_transcription": types.AudioTranscriptionConfig(),
            "output_audio_transcription": types.AudioTranscriptionConfig(),
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=cfg.get("voice", self.gemini_voice),
                    ),
                ),
            ),
            "system_instruction": cfg.get("system_instruction", SYSTEM_PROMPT),
        }
        if gemini_tools:
            kwargs["tools"] = gemini_tools
        return types.LiveConnectConfig(**kwargs)

    # --------------------------------------------------------------- Gemini

    async def _gemini_loop(self) -> None:
        cfg = self.state.agent_config or {}
        model = cfg.get("model") or self.gemini_model
        config = self._build_live_config(cfg)

        # Per-call session loop. We reconnect on transient errors (network
        # blips, 1011 keepalive timeouts) but exit cleanly when the call
        # ends, so a fresh WebSocket is opened for the next call.
        while self._call_active.is_set() and not self._stopping.is_set():
            try:
                logger.info(
                    "Connecting to Gemini Live model: %s (agent=%s)",
                    model,
                    cfg.get("agent_slug", "fallback"),
                )
                async with self.client.aio.live.connect(
                    model=model,
                    config=config,
                ) as session:
                    self.session = session
                    self.session_ready.set()
                    logger.info(
                        "Gemini Live connected (voice=%s)",
                        cfg.get("voice", self.gemini_voice),
                    )

                    send_task = asyncio.create_task(
                        self._gemini_send_loop(session), name="gemini-send-loop"
                    )
                    recv_task = asyncio.create_task(
                        self._gemini_recv_loop(session), name="gemini-recv-loop"
                    )

                    try:
                        done, pending = await asyncio.wait(
                            {send_task, recv_task},
                            return_when=asyncio.FIRST_EXCEPTION,
                        )

                        for task in pending:
                            task.cancel()
                        for task in pending:
                            try:
                                await task
                            except (asyncio.CancelledError, Exception):
                                pass

                        for task in done:
                            exc = task.exception()
                            if exc:
                                raise exc
                    finally:
                        self.session_ready.clear()
                        self.session = None

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._call_active.is_set():
                    break
                logger.warning(
                    "Gemini loop error: %s; reconnecting in 2s", exc
                )
                await asyncio.sleep(2)

        logger.info("Gemini per-call session loop exited")

    async def _gemini_send_loop(self, session) -> None:
        # Same shape as React: stream 256 ms PCM16 chunks continuously.
        self.state.last_user_tx_ts = time.monotonic()
        while not self._stopping.is_set():
            try:
                audio_chunk = await asyncio.wait_for(
                    self.audio_ingest_queue.get(), timeout=0.01
                )
            except asyncio.TimeoutError:
                continue
            if not audio_chunk:
                continue
            if AUTO_GREETING and not self.state.greeting_sent:
                self.state.greeting_sent = True
                try:
                    await session.send_client_content(
                        turns=types.Content(
                            role="user",
                            parts=[types.Part(text=AUTO_GREETING)],
                        ),
                        turn_complete=True,
                    )
                except Exception:
                    logger.exception("AUTO_GREETING send failed")
            await session.send_realtime_input(
                audio=types.Blob(
                    data=audio_chunk,
                    mime_type="audio/pcm;rate=16000",
                ),
            )
            self.state.gemini_in_chunks += 1
            self.state.gemini_in_bytes += len(audio_chunk)
            self.state.last_user_tx_ts = time.monotonic()

    @staticmethod
    def _is_gemini_session_closed(exc: BaseException) -> bool:
        name = type(exc).__name__
        if "ConnectionClosed" in name:
            return True
        return "1000" in str(exc)

    async def _gemini_recv_loop(self, session) -> None:
        # session.receive() yields ONE model turn then returns (it breaks on
        # turn_complete). Google's cookbook re-enters receive() in a while
        # loop for every subsequent turn — without that, turn 2+ is deaf.
        try:
            while not self._stopping.is_set():
                async for response in session.receive():
                    tool_call = getattr(response, "tool_call", None)
                    if tool_call is not None:
                        await self._handle_tool_call(session, tool_call)

                    server_content = getattr(response, "server_content", None)
                    if server_content is None:
                        continue

                    # React reference: only handle interruption (clear playback).
                    if getattr(server_content, "interrupted", False):
                        self.state.gemini_interruptions += 1
                        logger.info(
                            "Gemini interrupted (#%d); flushing playback queue",
                            self.state.gemini_interruptions,
                        )
                        self._drain_queue(self.rtp_out_queue)
                        self.state.out_pcm8_buffer = b""
                        self.state.rx_resampler.reset()

                    in_tx = getattr(server_content, "input_transcription", None)
                    if in_tx is not None:
                        text = getattr(in_tx, "text", None)
                        if text:
                            logger.info("USER: %s", text)
                            self._buffer_transcript("user", text)

                    out_tx = getattr(server_content, "output_transcription", None)
                    if out_tx is not None:
                        text = getattr(out_tx, "text", None)
                        if text:
                            logger.info("GEMINI: %s", text)
                            self._buffer_transcript("model", text)

                    if getattr(server_content, "turn_complete", False):
                        self.state.gemini_turn_completes += 1
                        logger.info(
                            "Gemini turn_complete (#%d) — ready for next turn",
                            self.state.gemini_turn_completes,
                        )
                        asyncio.create_task(self._on_turn_complete())

                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn is None:
                        continue

                    for part in getattr(model_turn, "parts", None) or []:
                        inline_data = getattr(part, "inline_data", None)
                        if inline_data is None:
                            continue
                        audio_bytes = inline_data.data
                        if not audio_bytes:
                            continue
                        if isinstance(audio_bytes, str):
                            audio_bytes = audio_bytes.encode()
                        ab = bytes(audio_bytes)
                        self.state.gemini_out_bytes += len(ab)
                        self.state.last_gemini_audio_ts = time.monotonic()
                        self._enqueue_output_audio(ab)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._is_gemini_session_closed(exc):
                return
            raise

    async def _handle_tool_call(self, session, tool_call) -> None:
        async def run_one(fc):
            params = dict(fc.args) if fc.args else {}
            result = await self._platform_tool(fc.name, fc.id, params)
            return types.FunctionResponse(
                id=result.get("id", fc.id),
                name=result.get("name", fc.name),
                response=result.get("response", {}),
            )

        responses = await asyncio.gather(
            *[run_one(fc) for fc in tool_call.function_calls]
        )
        logger.info("Tool call batch: %s", [r.name for r in responses])
        await session.send_tool_response(function_responses=list(responses))

    # ----------------------------------------------------------------- RTP

    def _enqueue_output_audio(self, pcm24: bytes) -> None:
        """Convert Gemini's 24 kHz PCM16 chunk into 20 ms ulaw RTP payloads
        and enqueue them for the paced sender. Pacing is done elsewhere.

        Also tees the same chunk (resampled to 16 kHz) into the APM's
        far-end buffer so the echo canceller knows what the caller will
        be hearing.
        """
        if self.state.asterisk_rtp_addr is None:
            return

        # 24 kHz -> 8 kHz for Asterisk (zero-phase polyphase sinc).
        # Stateful: filter ringing at chunk boundaries is absorbed by the
        # Resampler so the spliced audio sounds continuous.
        pcm8 = _resample_pcm16(pcm24, self.state.rx_resampler, ratio=1.0 / 3.0)
        self.state.out_pcm8_buffer += pcm8

        # 24 kHz -> 16 kHz for the APM far-end reference. Independent
        # resampler so its filter state doesn't fight with the 8 kHz one.
        if self.state.apm is not None:
            pcm16_ref = _resample_pcm16(
                pcm24, self.state.far_resampler, ratio=2.0 / 3.0
            )
            self.state.far_end_buf += pcm16_ref
            # Cap the far-end buffer at ~2 s so a slow inbound (or a
            # cleanup race) can't grow it unboundedly. AEC only needs
            # ~stream_delay_ms of history aligned with the near-end.
            max_bytes = 16000 * 2 * 2  # 2 s
            if len(self.state.far_end_buf) > max_bytes:
                self.state.far_end_buf = self.state.far_end_buf[-max_bytes:]

        while len(self.state.out_pcm8_buffer) >= FRAME_BYTES_PCM16_8K:
            frame_pcm16 = self.state.out_pcm8_buffer[:FRAME_BYTES_PCM16_8K]
            self.state.out_pcm8_buffer = self.state.out_pcm8_buffer[FRAME_BYTES_PCM16_8K:]
            ulaw_payload = audioop.lin2ulaw(frame_pcm16, 2)
            try:
                self.rtp_out_queue.put_nowait(ulaw_payload)
            except asyncio.QueueFull:
                logger.warning("RTP out queue full; dropping outbound frame")
                return

    async def _rtp_pacer_loop(self) -> None:
        """Send one ulaw RTP packet every 20 ms when audio is queued.

        Asterisk's jitter buffer expects ptime-paced RTP. Without this the
        bursts of frames we get whenever Gemini delivers a chunk cause
        audible clicks/gaps even though the bytes arrive correctly.
        """
        next_send = time.monotonic()
        while not self._stopping.is_set():
            try:
                ulaw_payload = await asyncio.wait_for(
                    self.rtp_out_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                next_send = time.monotonic()
                continue

            if (
                self.rtp_transport is None
                or self.state.asterisk_rtp_addr is None
            ):
                # Lost the call; drop the frame.
                continue

            packet = build_rtp_packet(
                payload=ulaw_payload,
                sequence_number=self.state.tx_seq,
                timestamp=self.state.tx_timestamp,
                ssrc=self.state.tx_ssrc,
                payload_type=0,  # PCMU
            )

            try:
                self._send_rtp(packet, self.state.asterisk_rtp_addr)
            except Exception:
                logger.exception("Failed to send RTP packet")
                continue

            self.state.rtp_out_frames += 1
            # Record outbound timestamp for TTS gating. Inbound audio
            # arriving within GATE_TAIL_MS of this is treated as likely
            # acoustic echo of our own output.
            self.state.last_outbound_rtp_ts = time.monotonic()
            self.state.tx_seq = (self.state.tx_seq + 1) & 0xFFFF
            self.state.tx_timestamp = (self.state.tx_timestamp + SAMPLES_PER_FRAME_8K) & 0xFFFFFFFF

            # Wall-clock pace: sleep until next_send. If we fell behind,
            # reset the schedule so we don't burst-catch-up.
            next_send += PTIME_MS / 1000.0
            now = time.monotonic()
            delay = next_send - now
            if delay < -0.1:
                next_send = now
            elif delay > 0:
                await asyncio.sleep(delay)

    async def handle_rtp_packet(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            payload_type, _seq, _ts, payload = parse_rtp(data)
        except Exception as exc:
            logger.debug("Bad RTP packet from %s: %s", addr, exc)
            return

        if payload_type != 0:  # PCMU
            logger.debug("Ignoring RTP payload type %s from %s", payload_type, addr)
            return

        # State guard: drop RTP unless a call is fully wired up. Asterisk
        # can leak stray packets from the previous call's ExternalMedia
        # channel after we delete it; learning that address would taint
        # the next call's outbound path.
        if not self.state.active or self.state.external_channel_id is None:
            return

        if self.state.asterisk_rtp_addr is None:
            rip = addr[0]
            if rip in ("127.0.0.1", "::1", "localhost") and self._asterisk_rtp_host_ip:
                rip = self._asterisk_rtp_host_ip
            self.state.asterisk_rtp_addr = (rip, addr[1])
            logger.info("Learned Asterisk RTP remote address: %s", self.state.asterisk_rtp_addr)

        if self.state.rtp_in_frames == 0:
            logger.info(
                "First RTP from Asterisk: %d bytes from %s (pcmu)",
                len(payload),
                addr,
            )
        self.state.rtp_in_frames += 1

        # PCMU -> PCM16 8 kHz -> PCM16 16 kHz for Gemini.
        # libsamplerate (sinc_fastest) gives Gemini a clean upsampled
        # signal; audioop.ratecv loses HF detail and weakens VAD pickup
        # on telephony audio (see GoogleCloudPlatform/generative-ai
        # gemini-live-telephony-app reference).
        pcm8 = audioop.ulaw2lin(payload, 2)
        pcm16k = _resample_pcm16(pcm8, self.state.tx_resampler, ratio=2.0)
        # Small static lift so the APM's AGC has signal to work with.
        # AGC will then dynamically normalise from here. audioop.mul
        # saturates at int16 bounds, so brief peaks just clip instead
        # of wrapping.
        if INBOUND_GAIN != 1.0:
            pcm16k = audioop.mul(pcm16k, 2, INBOUND_GAIN)

        try:
            frame_rms = audioop.rms(pcm16k, 2)
            if frame_rms > self.state.in_rms_peak:
                self.state.in_rms_peak = frame_rms
            self.state.in_rms_sum += frame_rms
            self.state.in_rms_count += 1
        except audioop.error:
            frame_rms = 0

        # First-frames-after-bridge diagnostic. If these are all 0 even
        # before the AI says anything, audio isn't reaching us at all
        # (Asterisk mis-bridge or softphone muted from the start). If
        # they're nonzero but go to 0 only after the AI speaks, the
        # softphone is auto-muting on speaker output (use headphones).
        if self.state.rtp_in_frames <= 5:
            logger.info(
                "RTP early frame #%d: frame_rms=%d (raw 8k bytes=%d)",
                self.state.rtp_in_frames,
                frame_rms,
                len(payload),
            )

        if not self.session_ready.is_set():
            return

        now = time.monotonic()

        self.state.in_pcm16k_buffer += pcm16k

        # Optional APM stage (off by default). Only runs if a working
        # AudioProcessor was constructed at session start.
        if self.state.apm is not None:
            while len(self.state.in_pcm16k_buffer) >= APM_FRAME_BYTES_16K:
                near = self.state.in_pcm16k_buffer[:APM_FRAME_BYTES_16K]
                self.state.in_pcm16k_buffer = self.state.in_pcm16k_buffer[
                    APM_FRAME_BYTES_16K:
                ]
                if len(self.state.far_end_buf) >= APM_FRAME_BYTES_16K:
                    far = self.state.far_end_buf[:APM_FRAME_BYTES_16K]
                    self.state.far_end_buf = self.state.far_end_buf[
                        APM_FRAME_BYTES_16K:
                    ]
                else:
                    far = _SILENCE_10MS_16K
                try:
                    near_np = np.frombuffer(near, dtype=np.int16)
                    far_np = np.frombuffer(far, dtype=np.int16)
                    out_np = self.state.apm.process(near_np, far_np)
                    processed = out_np.tobytes()
                    self.state.apm_frames += 1
                    try:
                        rms = int(audioop.rms(processed, 2))
                        if rms > self.state.apm_rms_peak:
                            self.state.apm_rms_peak = rms
                        self.state.apm_rms_sum += rms
                        self.state.apm_rms_count += 1
                    except audioop.error:
                        pass
                except Exception:
                    processed = near
                self.state.in_pcm16k_clean_buffer += processed
        else:
            # No APM: pass the raw 16 kHz buffer through unchanged.
            self.state.in_pcm16k_clean_buffer += self.state.in_pcm16k_buffer
            self.state.in_pcm16k_buffer = b""

        # Re-frame to GEMINI_CHUNK_BYTES and enqueue for the send loop.
        while len(self.state.in_pcm16k_clean_buffer) >= GEMINI_CHUNK_BYTES:
            chunk = self.state.in_pcm16k_clean_buffer[:GEMINI_CHUNK_BYTES]
            self.state.in_pcm16k_clean_buffer = self.state.in_pcm16k_clean_buffer[
                GEMINI_CHUNK_BYTES:
            ]
            try:
                self.audio_ingest_queue.put_nowait(chunk)
            except asyncio.QueueFull:
                logger.warning("Inbound audio queue full; dropping chunk")
                break


class RTPProtocol(asyncio.DatagramProtocol):
    def __init__(self, bridge: GeminiLiveBridge) -> None:
        self.bridge = bridge

    def datagram_received(self, data: bytes, addr) -> None:
        asyncio.create_task(self.bridge.handle_rtp_packet(data, addr))


bridge = GeminiLiveBridge()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await bridge.start()
    try:
        yield
    finally:
        await bridge.stop()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "session_ready": bridge.session_ready.is_set(),
        "bridge_active": bridge.state.active,
        "bridge_id": bridge.state.bridge_id,
        "human_channel_id": bridge.state.human_channel_id,
        "external_channel_id": bridge.state.external_channel_id,
        "asterisk_rtp_addr": (
            list(bridge.state.asterisk_rtp_addr)
            if bridge.state.asterisk_rtp_addr
            else None
        ),
        "model": (
            bridge.state.agent_config.get("model")
            if bridge.state.agent_config
            else bridge.gemini_model
        ),
        "voice": (
            bridge.state.agent_config.get("voice")
            if bridge.state.agent_config
            else bridge.gemini_voice
        ),
        "platform_session_id": bridge.state.platform_session_id,
        "platform_url": bridge.platform_url or None,
        "rtp_port": bridge.rtp_port,
        "inbound_gain": INBOUND_GAIN,
        "tts_gating": TTS_GATING_ENABLED,
        "tts_gate_tail_ms": GATE_TAIL_MS,
        "rtp_out_queue_depth": bridge.rtp_out_queue.qsize(),
        "audio_ingest_queue_depth": bridge.audio_ingest_queue.qsize(),
    }
