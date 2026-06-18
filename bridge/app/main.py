"""FastAPI bridge: Asterisk ARI/ExternalMedia <-> Gemini Live.

Concurrent-call bridge. Each Asterisk channel entering Stasis gets its own
ExternalMedia RTP leg on a dedicated UDP port and a per-call Gemini Live
WebSocket session.

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
import secrets
import socket
import struct
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
import numpy as np
import samplerate
import websockets
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types

from app.call_session import CallSession
from app.token_meter import SessionTokenUsage, extract_usage_metadata

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
# Applies to INBOUND calls only — outbound skips ringback (see use_inbound_ringback).
RING_MIN_SEC = float(os.getenv("RING_MIN_SEC", "3"))
GEMINI_READY_TIMEOUT_SEC = float(os.getenv("GEMINI_READY_TIMEOUT_SEC", "20"))
# How long RTP inbound frame count must be frozen before the bridge force-cleans
# an outbound call. 15 s was too aggressive for live PSTN calls with brief
# network hiccups. Raise with OUTBOUND_RTP_STALL_SEC env var.
OUTBOUND_RTP_STALL_SEC = float(os.getenv("OUTBOUND_RTP_STALL_SEC", "45"))
OUTBOUND_ANSWER_TIMEOUT_SEC = float(os.getenv("OUTBOUND_ANSWER_TIMEOUT_SEC", "90"))

_DIAL_PHASE_LABELS = {
    "originating": "Starting outbound call…",
    "ringing": "Ringing prospect…",
    "connecting": "Prospect answered — connecting AI agent…",
    "in_call": "In call with prospect",
    "ended": "Call ended",
}
_OUTCOME_LABELS = {
    "completed": "Call completed",
    "answered": "Prospect answered",
    "no_answer": "No answer",
    "busy": "Line busy",
    "rejected": "Call declined",
    "failed": "Call failed",
}


def _hangup_outcome(
    *,
    cause: Optional[str],
    cause_txt: Optional[str],
    dial_phase: str,
    had_media: bool,
) -> str:
    txt = (cause_txt or "").lower()
    cause_i: Optional[int] = None
    if cause is not None and str(cause).strip().isdigit():
        cause_i = int(str(cause).strip())
    if cause_i == 17 or "busy" in txt:
        return "busy"
    if cause_i in (19, 18) or "no answer" in txt or "noanswer" in txt:
        return "no_answer"
    if cause_i == 21 or "reject" in txt or "declin" in txt:
        return "rejected"
    if had_media or dial_phase == "in_call":
        return "completed"
    if dial_phase in ("ringing", "connecting", "originating"):
        return "no_answer"
    return "failed"


def _dial_status_message(phase: str, outcome: Optional[str] = None) -> str:
    if phase == "ended" and outcome:
        return _OUTCOME_LABELS.get(outcome, _OUTCOME_LABELS["failed"])
    return _DIAL_PHASE_LABELS.get(phase, phase.replace("_", " ").title())


def use_inbound_ringback(call_direction: str) -> bool:
    """True for caller-dialed extensions (701–704). False for CRM-originated outbound."""
    return call_direction != "outbound"

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
# end_call: wait for farewell audio to finish before hanging up.
END_CALL_MIN_WAIT_SEC = float(os.getenv("END_CALL_MIN_WAIT_SEC", "0.5"))
END_CALL_PLAYBACK_GRACE_SEC = float(os.getenv("END_CALL_PLAYBACK_GRACE_SEC", "1.0"))
END_CALL_MAX_WAIT_SEC = float(os.getenv("END_CALL_MAX_WAIT_SEC", "15.0"))

# Auto-greeting: when the call is fully bridged, kick the model to
# speak first. Without this the caller hears silence until they say
# something, which they (rightly) experience as a slow agent. The
# React reference does the same -- it doesn't wait for user input
# before producing initial audio (the user can interrupt anytime).
_DEFAULT_AUTO_GREETING = (
    "Greet the caller warmly in one natural sentence, introduce yourself by name, "
    "and ask how you can help. Use your preloaded knowledge context — do not stay silent."
)
_DEFAULT_OUTBOUND_AUTO_GREETING = (
    "The outbound call just connected. Say ONLY a brief warm hello and your name — "
    "one short sentence. Do NOT mention Trango Tech, pitch, ask for time, or ask about "
    "their business yet. Stop and wait for the prospect to respond."
)
_auto_greet_env = os.getenv("AUTO_GREETING")
AUTO_GREETING = (
    _auto_greet_env.strip()
    if _auto_greet_env is not None and _auto_greet_env.strip()
    else _DEFAULT_AUTO_GREETING
)
_AUTO_GREETING_CUSTOM = bool(_auto_greet_env is not None and _auto_greet_env.strip())


def _auto_greeting_for_direction(call_direction: str) -> str:
    """Return the kick prompt that triggers the model's first spoken turn."""
    if _AUTO_GREETING_CUSTOM:
        return AUTO_GREETING
    if call_direction == "outbound":
        return _DEFAULT_OUTBOUND_AUTO_GREETING
    return _DEFAULT_AUTO_GREETING


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
    cleaning_up: bool = False
    platform_end_sent: bool = False
    last_rtp_in_count: int = 0
    rtp_stall_since: float = 0.0

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
    call_direction: str = "inbound"  # inbound | outbound
    dialed_endpoint: Optional[str] = None
    channel_state: str = ""
    dial_phase: str = ""
    prospect_answered: bool = False
    dial_outcome: Optional[str] = None
    connect_experience: str = "auto_greeting"
    bridge_ready: bool = False
    prospect_answer_event: Any = field(default=None, repr=False)
    hangup_event: Optional[str] = None
    hangup_cause: Optional[str] = None
    hangup_cause_txt: Optional[str] = None
    end_call_pending: bool = False

    # Buffered streaming transcriptions — flushed per turn / on call end
    user_tx_parts: list[str] = field(default_factory=list)
    model_tx_parts: list[str] = field(default_factory=list)

    # Estimated Gemini token usage for pricing (audio in/out + text context)
    token_usage: SessionTokenUsage = field(default_factory=SessionTokenUsage)



SYSTEM_PROMPT = (
    "You are on a live phone call. Speak like a real human: warm, polite, and professional. "
    "Use natural pacing and brief pauses. Occasional phrases like 'um' or 'let me see' are fine — sparingly. "
    "Never say the word 'filler' or label what you are about to say — just speak naturally. "
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

        self.rtp_port_base = int(os.getenv("RTP_PORT_BASE", "40000"))
        self.rtp_port_count = int(os.getenv("RTP_PORT_COUNT", "50"))
        self.max_concurrent_calls = int(os.getenv("MAX_CONCURRENT_CALLS", "5"))
        # Hostname/IP Asterisk uses in ExternalMedia (docker DNS name by default).
        self.external_media_host = os.getenv("EXTERNAL_MEDIA_HOST", "bridge")
        self._asterisk_rtp_host_ip: str = ""

        self.client = genai.Client(api_key=self.gemini_api_key)

        self.http: Optional[httpx.AsyncClient] = None
        self.ari_ws: Optional[websockets.WebSocketClientProtocol] = None

        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()
        self._calls: dict[str, CallSession] = {}
        self._port_to_channel: dict[int, str] = {}
        self._free_ports: list[int] = list(
            range(self.rtp_port_base, self.rtp_port_base + self.rtp_port_count)
        )

        self.platform_url = os.getenv("PLATFORM_URL", "").rstrip("/")
        self.platform_token = os.getenv("BRIDGE_INTERNAL_TOKEN", "")
        # Outbound originate context keyed by ARI channel id until StasisStart.
        self._pending_outbound: dict[str, dict[str, Any]] = {}
        # Live + recent outbound dial tracking for CRM polling (channel_id -> status).
        self._dial_status: dict[str, dict[str, Any]] = {}

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

    def _send_rtp_for_call(self, call: CallSession, packet: bytes, addr: tuple[str, int]) -> None:
        host, port = addr
        if not host.replace(".", "").isdigit():
            host = self._resolve_udp_host(host)
        if call.rtp_transport is None:
            raise RuntimeError(f"RTP transport missing for call {call.human_channel_id}")
        call.rtp_transport.sendto(packet, (host, port))

    def _allocate_rtp_port(self, channel_id: str) -> int:
        if not self._free_ports:
            raise RuntimeError("No free RTP ports available")
        port = self._free_ports.pop(0)
        self._port_to_channel[port] = channel_id
        return port

    def _release_rtp_port(self, port: int) -> None:
        self._port_to_channel.pop(port, None)
        if port and port not in self._free_ports:
            self._free_ports.append(port)
            self._free_ports.sort()

    async def start(self) -> None:
        self.http = httpx.AsyncClient(
            base_url=f"http://{self.ari_host}:{self.ari_port}/ari",
            auth=(self.ari_user, self.ari_pass),
            timeout=30.0,
        )

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
            f"{self.rtp_port_base}+{self.rtp_port_count}",
            self.external_media_host,
            self.rtp_port_base,
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
            if not self._calls:
                continue
            for call in list(self._calls.values()):
                state = call.state
                now = time.monotonic()

                if state.rtp_in_frames > 0 and state.rtp_in_frames == state.last_rtp_in_count:
                    if not state.rtp_stall_since:
                        state.rtp_stall_since = now
                else:
                    state.rtp_stall_since = 0.0
                    state.last_rtp_in_count = state.rtp_in_frames

                stall_sec = (
                    (now - state.rtp_stall_since) if state.rtp_stall_since else 0.0
                )
                if (
                    state.rtp_stall_since
                    and state.rtp_in_frames > 30
                    and call.state.human_channel_id
                ):
                    # Outbound ARI channels often stay "Up" after the prospect
                    # hangs up (no StasisEnd). Inbound usually gets StasisEnd.
                    # Before force-cleaning either direction, confirm the ARI
                    # channel is actually gone (404) so a brief network hiccup
                    # does not drop a live call.
                    stall_threshold = (
                        OUTBOUND_RTP_STALL_SEC
                        if state.call_direction == "outbound"
                        else 15.0
                    )
                    if stall_sec < stall_threshold:
                        pass  # not stalled long enough yet
                    elif self.http is not None:
                        # ARI liveness check: only clean up if channel is gone.
                        channel_alive = True
                        try:
                            resp = await self.http.get(
                                f"/channels/{call.state.human_channel_id}"
                            )
                            channel_alive = resp.status_code != 404
                        except Exception:
                            logger.warning(
                                "Stale call liveness check failed for %s",
                                call.state.human_channel_id,
                                exc_info=True,
                            )
                        if not channel_alive:
                            logger.warning(
                                "Cleaning up %s call %s (RTP stalled %.0fs, channel gone)",
                                state.call_direction,
                                call.state.human_channel_id,
                                stall_sec,
                            )
                            await self.cleanup_call(call)
                            continue
                        elif state.call_direction == "outbound":
                            logger.warning(
                                "Cleaning up outbound call %s (RTP stalled %.0fs)",
                                call.state.human_channel_id,
                                stall_sec,
                            )
                            await self.cleanup_call(call)
                            continue

                since_user = (
                    f"{now - state.last_user_tx_ts:.1f}s"
                    if state.last_user_tx_ts
                    else "never"
                )
                since_gem = (
                    f"{now - state.last_gemini_audio_ts:.1f}s"
                    if state.last_gemini_audio_ts
                    else "never"
                )
                # in_rms_peak is in PCM16 units (0..32767). >=2000 = clearly
                # audible speech, ~500-1500 = quiet speech, <300 = effectively
                # silence/line noise.
                rms_peak = state.in_rms_peak
                rms_mean = (
                    state.in_rms_sum // state.in_rms_count
                    if state.in_rms_count
                    else 0
                )
                state.in_rms_peak = 0
                state.in_rms_sum = 0
                state.in_rms_count = 0
                apm_rms_peak = state.apm_rms_peak
                apm_rms_mean = (
                    state.apm_rms_sum // state.apm_rms_count
                    if state.apm_rms_count
                    else 0
                )
                state.apm_rms_peak = 0
                state.apm_rms_sum = 0
                state.apm_rms_count = 0

                # Watchdog: caller audio absent for too long. Almost always
                # the softphone auto-muting on speaker output.
                if (
                    rms_peak < 100
                    and state.rtp_in_frames > 50
                    and call.call_active.is_set()
                    and state.human_channel_id
                ):
                    state.silent_windows += 1
                    if state.silent_windows == 3:
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
                    state.silent_windows = 0
                speech_prob = None
                if state.apm is not None:
                    try:
                        speech_prob = float(state.apm.speech_probability())
                    except Exception:
                        speech_prob = None
                logger.info(
                    "STATS call=%s port=%d rtp_in=%d rtp_out=%d gemini_in=%d (%dB) gemini_out=%dB "
                    "turns_complete=%d interruptions=%d last_user_tx=%s last_gem_audio=%s "
                    "q_in=%d q_out=%d in_rms=p%d/m%d apm_rms=p%d/m%d gated=%d "
                    "apm_frames=%d far_buf=%dB apm_speech_prob=%s",
                    call.human_channel_id,
                    call.rtp_port,
                    state.rtp_in_frames,
                    state.rtp_out_frames,
                    state.gemini_in_chunks,
                    state.gemini_in_bytes,
                    state.gemini_out_bytes,
                    state.gemini_turn_completes,
                    state.gemini_interruptions,
                    since_user,
                    since_gem,
                    call.audio_ingest_queue.qsize(),
                    call.rtp_out_queue.qsize(),
                    rms_peak,
                    rms_mean,
                    apm_rms_peak,
                    apm_rms_mean,
                    state.gated_in_frames,
                    state.apm_frames,
                    len(state.far_end_buf),
                    f"{speech_prob:.2f}" if speech_prob is not None else "n/a",
                )

    async def stop(self) -> None:
        self._stopping.set()

        for call in list(self._calls.values()):
            await self.cleanup_call(call)

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
                        elif etype == "ChannelDestroyed":
                            await self._handle_channel_destroyed(event)
                        elif etype == "ChannelHangupRequest":
                            await self._handle_channel_hangup_request(event)
                        elif etype == "ChannelLeftBridge":
                            await self._handle_channel_left_bridge(event)
                        elif etype == "ChannelStateChange":
                            await self._handle_channel_state_change(event)
                        elif etype == "Dial":
                            await self._handle_dial(event)
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
            for call in self._calls.values():
                if call.state.external_channel_id == channel_id:
                    return
            return

        if len(self._calls) >= self.max_concurrent_calls:
            logger.warning(
                "Max concurrent calls reached (%d); hanging up channel %s",
                self.max_concurrent_calls,
                channel_id,
            )
            try:
                assert self.http is not None
                await self.http.delete(f"/channels/{channel_id}")
            except Exception:
                pass
            return

        state = CallState()
        state.active = True
        state.human_channel_id = channel_id
        state.apm = _build_apm()
        if state.apm is not None:
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
        try:
            rtp_port = self._allocate_rtp_port(channel_id)
        except RuntimeError:
            logger.warning("No free RTP ports; hanging up channel %s", channel_id)
            try:
                assert self.http is not None
                await self.http.delete(f"/channels/{channel_id}")
            except Exception:
                pass
            return
        call = CallSession(human_channel_id=channel_id, state=state, rtp_port=rtp_port)
        self._calls[channel_id] = call

        assert self.http is not None

        try:
            loop = asyncio.get_running_loop()
            transport, _protocol = await loop.create_datagram_endpoint(
                lambda: RTPProtocol(self, call),
                local_addr=("0.0.0.0", call.rtp_port),
            )
            call.rtp_transport = transport

            ring_started = time.monotonic()
            caller = channel.get("caller") or {}
            caller_id = caller.get("number") or channel.get("name")
            agent_slug = args[0] if args else None
            dialplan = channel.get("dialplan") or {}
            dialed_extension = dialplan.get("exten")

            pending = self._pending_outbound.pop(channel_id, None)
            direction = "inbound"
            lead_id: Optional[int] = None
            dialed_endpoint: Optional[str] = None
            campaign_lead_id: Optional[int] = None
            connect_experience = "auto_greeting"
            if pending:
                agent_slug = pending.get("agent_slug") or agent_slug
                lead_id = pending.get("lead_id")
                dialed_endpoint = pending.get("endpoint")
                campaign_lead_id = pending.get("campaign_lead_id")
                direction = "outbound"
                connect_experience = str(
                    pending.get("connect_experience") or "auto_greeting"
                ).strip().lower()
            elif len(args) > 1 and args[1] == "outbound":
                direction = "outbound"
                if len(args) > 2 and str(args[2]).isdigit():
                    lead_id = int(args[2])

            call.state.call_direction = direction
            call.state.dialed_endpoint = dialed_endpoint
            call.state.channel_state = channel.get("state") or ""
            call.state.connect_experience = connect_experience
            call.state.prospect_answer_event = asyncio.Event()
            if (
                direction != "outbound"
                and call.state.channel_state == "Up"
                and connect_experience != "comfort_tone"
            ):
                call.state.prospect_answered = True
                call.state.prospect_answer_event.set()

            await self._platform_call_start(
                call,
                channel_id,
                caller_id,
                agent_slug,
                dialed_extension,
                direction=direction,
                lead_id=lead_id,
                dialed_endpoint=dialed_endpoint,
                campaign_lead_id=campaign_lead_id,
            )

            if direction == "outbound":
                await self._set_outbound_dial_phase(call, "ringing")
                asyncio.create_task(
                    self._outbound_answer_watch(call),
                    name=f"outbound-answer-watch-{channel_id}",
                )

            inbound_ringback = use_inbound_ringback(direction)

            # 1) Open Gemini while the phone is still ringing (not answered).
            call.call_active.set()
            call.gemini_task = asyncio.create_task(
                self._gemini_loop(call), name=f"gemini-loop-{channel_id}"
            )
            call.pacer_task = asyncio.create_task(
                self._rtp_pacer_loop(call), name=f"rtp-pacer-{channel_id}"
            )

            # 2) Inbound only: ringback while Gemini connects. Outbound prospects
            # already heard their phone ring — never play ringback after pickup.
            if inbound_ringback:
                try:
                    await self.http.post(f"/channels/{channel_id}/ring")
                    logger.info(
                        "Inbound ringback on channel %s (ring_min=%.1fs)",
                        channel_id,
                        RING_MIN_SEC,
                    )
                except Exception:
                    logger.warning("ARI ring failed for %s (continuing)", channel_id)
            else:
                logger.info(
                    "Outbound call %s — connect_experience=%s",
                    channel_id,
                    connect_experience,
                )
                if connect_experience == "comfort_tone":
                    try:
                        await self.http.post(f"/channels/{channel_id}/answer")
                        await self.http.post(f"/channels/{channel_id}/moh")
                        logger.info(
                            "Outbound comfort tone enabled on channel %s while Gemini connects",
                            channel_id,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to start outbound comfort tone for %s (continuing)",
                            channel_id,
                        )

            # 3) Wait for Gemini session (with timeout).
            try:
                await asyncio.wait_for(
                    call.session_ready.wait(),
                    timeout=GEMINI_READY_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "Gemini not ready within %.0fs; hanging up %s",
                    GEMINI_READY_TIMEOUT_SEC,
                    channel_id,
                )
                await self.cleanup_call(call)
                try:
                    await self.http.delete(f"/channels/{channel_id}")
                except Exception:
                    pass
                return

            # 4) Inbound only: minimum ring time so setup never feels instant/dead-air.
            elapsed = time.monotonic() - ring_started
            if inbound_ringback and elapsed < RING_MIN_SEC:
                await asyncio.sleep(RING_MIN_SEC - elapsed)

            gemini_wait = time.monotonic() - ring_started
            logger.info(
                "Gemini ready after %.1fs; answering channel %s (%s)",
                gemini_wait,
                channel_id,
                direction,
            )

            # Outbound PSTN: keep "ringing" until the prospect picks up, then wire audio.
            if direction == "outbound" and connect_experience != "comfort_tone":
                await self._set_outbound_dial_phase(call, "ringing")
                if not call.state.prospect_answered:
                    answered = await self._wait_for_prospect_answer(
                        call, timeout=OUTBOUND_ANSWER_TIMEOUT_SEC
                    )
                    if not answered:
                        logger.warning(
                            "Outbound no answer within %.0fs; hanging up %s",
                            OUTBOUND_ANSWER_TIMEOUT_SEC,
                            channel_id,
                        )
                        call.state.hangup_event = "NoAnswerTimeout"
                        call.state.hangup_cause_txt = "no answer"
                        await self.cleanup_call(call)
                        try:
                            await self.http.delete(f"/channels/{channel_id}")
                        except Exception:
                            pass
                        return

            # 5) Answer and wire audio. In comfort_tone mode we already answered.
            if not (direction == "outbound" and connect_experience == "comfort_tone"):
                await self.http.post(f"/channels/{channel_id}/answer")
            else:
                try:
                    await self.http.delete(f"/channels/{channel_id}/moh")
                except Exception:
                    logger.warning("Failed to stop MOH for %s", channel_id)

            bridge_resp = await self.http.post("/bridges", params={"type": "mixing"})
            bridge_resp.raise_for_status()
            bridge_obj = bridge_resp.json()
            call.state.bridge_id = bridge_obj["id"]

            await self.http.post(
                f"/bridges/{call.state.bridge_id}/addChannel",
                params={"channel": channel_id},
            )

            ext_resp = await self.http.post(
                "/channels/externalMedia",
                params={
                    "app": self.ari_app,
                    "external_host": f"{self.external_media_host}:{call.rtp_port}",
                    "format": "ulaw",
                    "direction": "both",
                    "data": "external_media",
                },
            )
            ext_resp.raise_for_status()
            ext_channel = ext_resp.json()
            call.state.external_channel_id = ext_channel["id"]

            await self.http.post(
                f"/bridges/{call.state.bridge_id}/addChannel",
                params={"channel": call.state.external_channel_id},
            )

            await self._bootstrap_external_rtp(call, call.state.external_channel_id)

            call.state.bridge_ready = True
            logger.info(
                "Call ready: human=%s bridge=%s external=%s port=%d (setup %.1fs)",
                call.state.human_channel_id,
                call.state.bridge_id,
                call.state.external_channel_id,
                call.rtp_port,
                time.monotonic() - ring_started,
            )

            if direction == "outbound":
                await self._sync_outbound_dial_phase(call)

        except Exception:
            logger.exception("Failed to set up call %s", channel_id)
            await self.cleanup_call(call)

    async def _bootstrap_external_rtp(self, call: CallSession, external_channel_id: str) -> None:
        """Kick-start Asterisk UnicastRTP strict-RTP with outbound silence.

        ExternalMedia often waits for the first RTP from us before it
        forwards mixed caller audio to bridge:40000. Without this,
        rtp_in can stay at 0 (especially on physical phones where the
        phone→Asterisk leg is still learning).
        """
        assert self.http is not None
        if call.rtp_transport is None:
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
            call.state.asterisk_rtp_addr = (host, port)
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
                sequence_number=call.state.tx_seq,
                timestamp=call.state.tx_timestamp,
                ssrc=call.state.tx_ssrc,
                payload_type=0,
            )
            try:
                self._send_rtp_for_call(call, packet, call.state.asterisk_rtp_addr)
            except Exception:
                logger.exception("Bootstrap RTP send failed")
                break
            call.state.tx_seq = (call.state.tx_seq + 1) & 0xFFFF
            call.state.tx_timestamp = (
                call.state.tx_timestamp + SAMPLES_PER_FRAME_8K
            ) & 0xFFFFFFFF
            call.state.last_outbound_rtp_ts = time.monotonic()
            call.state.rtp_out_frames += 1
            await asyncio.sleep(PTIME_MS / 1000.0)
        logger.info(
            "Bootstrap sent %d RTP frames to Asterisk at %s:%d",
            25,
            call.state.asterisk_rtp_addr[0],
            call.state.asterisk_rtp_addr[1],
        )

    def _find_call_for_channel(self, channel_id: str) -> Optional[CallSession]:
        call = self._calls.get(channel_id)
        if call is not None:
            return call
        for active in self._calls.values():
            if active.state.external_channel_id == channel_id:
                return active
        return None

    @staticmethod
    def _channel_remote_answered(channel: dict) -> bool:
        """True when the far end has picked up."""
        return (channel.get("state") or "").strip() == "Up"

    async def _fetch_channel_answered(self, channel_id: str) -> bool:
        if self.http is None:
            return False
        try:
            resp = await self.http.get(f"/channels/{channel_id}")
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            data = resp.json()
            if self._channel_remote_answered(data):
                return True
            for var in ("PJSIP_RESPONSE_CODE", "SIPRESPONSE", "DIALSTATUS"):
                try:
                    vresp = await self.http.get(
                        f"/channels/{channel_id}/variable",
                        params={"variable": var},
                    )
                    if vresp.status_code != 200:
                        continue
                    value = (vresp.json().get("value") or "").strip().upper()
                    if value in ("200", "ANSWER", "ANSWERED"):
                        return True
                except Exception:
                    continue
        except Exception:
            return False
        return False

    async def _handle_channel_state_change(self, event: dict) -> None:
        channel = event.get("channel") or {}
        channel_id = channel.get("id")
        if not channel_id:
            return
        state = channel.get("state") or ""
        call = self._find_call_for_channel(channel_id)
        if call is None or channel_id != call.human_channel_id:
            return
        call.state.channel_state = state
        if call.state.call_direction != "outbound":
            return
        if state in ("Ring", "Ringing"):
            if call.state.dial_phase in ("", "originating"):
                await self._set_outbound_dial_phase(call, "ringing")
        elif state == "Up" and call.state.connect_experience != "comfort_tone":
            await self._mark_prospect_answered(call)

    async def _handle_dial(self, event: dict) -> None:
        dialstatus = (event.get("dialstatus") or "").upper()
        if dialstatus != "ANSWER":
            return
        peer = event.get("peer") or {}
        channel_id = peer.get("id")
        if not channel_id:
            return
        call = self._find_call_for_channel(channel_id)
        if call is None or channel_id != call.human_channel_id:
            return
        if call.state.call_direction != "outbound":
            return
        await self._mark_prospect_answered(call)

    async def _mark_prospect_answered(self, call: CallSession) -> None:
        if call.state.prospect_answered:
            return
        call.state.prospect_answered = True
        ev = call.state.prospect_answer_event
        if ev is not None and not ev.is_set():
            ev.set()
        logger.info("Prospect answered outbound channel=%s", call.human_channel_id)
        await self._sync_outbound_dial_phase(call)

    async def _wait_for_prospect_answer(self, call: CallSession, *, timeout: float) -> bool:
        if call.state.prospect_answered:
            return True
        ev = call.state.prospect_answer_event
        if ev is None:
            return False
        deadline = time.monotonic() + timeout
        poll_interval = 0.4
        while time.monotonic() < deadline:
            if call.state.prospect_answered:
                return True
            if await self._fetch_channel_answered(call.human_channel_id):
                await self._mark_prospect_answered(call)
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(ev.wait(), timeout=min(poll_interval, remaining))
                return True
            except asyncio.TimeoutError:
                continue
        return call.state.prospect_answered

    async def _sync_outbound_dial_phase(self, call: CallSession) -> None:
        """ringing → connecting (picked up) → in_call (bridge live)."""
        if call.state.call_direction != "outbound":
            return
        if call.state.dial_phase == "ended":
            return
        bridge_ready = bool(
            call.state.bridge_ready
            and call.state.bridge_id
            and call.state.external_channel_id
        )
        if bridge_ready:
            phase = "in_call"
        elif call.state.prospect_answered:
            phase = "connecting"
        else:
            phase = "ringing"
        if phase != call.state.dial_phase:
            await self._set_outbound_dial_phase(call, phase)

    async def _outbound_answer_watch(self, call: CallSession) -> None:
        """Background poll until pickup is detected (covers missed ARI events)."""
        if call.state.call_direction != "outbound":
            return
        channel_id = call.human_channel_id
        deadline = time.monotonic() + OUTBOUND_ANSWER_TIMEOUT_SEC
        while (
            call.state.active
            and not call.state.prospect_answered
            and not call.state.bridge_ready
            and time.monotonic() < deadline
        ):
            if await self._fetch_channel_answered(channel_id):
                await self._mark_prospect_answered(call)
                return
            await asyncio.sleep(0.4)

    async def hangup_channel(self, channel_id: str) -> dict[str, Any]:
        """CRM-initiated hangup for an outbound dial."""
        call = self._find_call_for_channel(channel_id)
        if call is not None:
            call.state.hangup_event = "UserHangup"
            call.state.hangup_cause_txt = "user hangup"
            await self.cleanup_call(call)
            return {"status": "ended", "channel_id": channel_id}

        pending = self._pending_outbound.pop(channel_id, None)
        row = self._dial_status.get(channel_id)
        if pending or row:
            if self.http is not None:
                try:
                    await self.http.delete(f"/channels/{channel_id}")
                except Exception:
                    pass
            meta = pending or row or {}
            self._upsert_dial_status(
                channel_id,
                dial_phase="ended",
                outcome="failed",
                hangup_cause_txt="user hangup",
                endpoint=meta.get("endpoint"),
            )
            return {"status": "ended", "channel_id": channel_id}

        raise HTTPException(status_code=404, detail="Unknown dial channel")

    async def _handle_stasis_end(self, event: dict) -> None:
        channel_id = event["channel"]["id"]
        call = self._find_call_for_channel(channel_id)
        if call is None:
            return

        if channel_id == call.human_channel_id:
            ch = event.get("channel", {}) or {}
            call.state.hangup_event = "StasisEnd"
            call.state.hangup_cause = str(ch.get("cause")) if ch.get("cause") is not None else None
            call.state.hangup_cause_txt = ch.get("cause_txt")
            logger.info(
                "Human channel ended: %s (cause=%s %s)",
                channel_id,
                event.get("channel", {}).get("cause", "?"),
                event.get("channel", {}).get("cause_txt", ""),
            )
        else:
            logger.info(
                "External media channel ended: %s (call human=%s)",
                channel_id,
                call.human_channel_id,
            )
        await self.cleanup_call(call)

    async def _handle_channel_destroyed(self, event: dict) -> None:
        channel = event.get("channel") or {}
        channel_id = channel.get("id")
        if not channel_id:
            return
        call = self._find_call_for_channel(channel_id)
        if call is None:
            pending = self._pending_outbound.pop(channel_id, None)
            if pending:
                outcome = _hangup_outcome(
                    cause=str(channel.get("cause")) if channel.get("cause") is not None else None,
                    cause_txt=channel.get("cause_txt"),
                    dial_phase="ringing",
                    had_media=False,
                )
                self._upsert_dial_status(
                    channel_id,
                    dial_phase="ended",
                    outcome=outcome,
                    hangup_cause=str(channel.get("cause")) if channel.get("cause") is not None else None,
                    hangup_cause_txt=channel.get("cause_txt"),
                    endpoint=pending.get("endpoint"),
                    agent_slug=pending.get("agent_slug"),
                    lead_id=pending.get("lead_id"),
                )
            return
        if channel_id != call.human_channel_id:
            logger.info(
                "External media channel destroyed: %s (human=%s) — ignoring",
                channel_id,
                call.human_channel_id,
            )
            return
        logger.info(
            "ChannelDestroyed: %s (cause=%s %s) — cleaning up call",
            channel_id,
            channel.get("cause", "?"),
            channel.get("cause_txt", ""),
        )
        call.state.hangup_event = "ChannelDestroyed"
        call.state.hangup_cause = str(channel.get("cause")) if channel.get("cause") is not None else None
        call.state.hangup_cause_txt = channel.get("cause_txt")
        await self.cleanup_call(call)

    async def _handle_channel_hangup_request(self, event: dict) -> None:
        channel = event.get("channel") or {}
        channel_id = channel.get("id")
        if not channel_id:
            return
        call = self._find_call_for_channel(channel_id)
        if call is None:
            return
        if channel_id != call.human_channel_id:
            logger.info(
                "External media hangup request: %s (human=%s) — ignoring",
                channel_id,
                call.human_channel_id,
            )
            return
        logger.info(
            "ChannelHangupRequest: %s (cause=%s %s)",
            channel_id,
            channel.get("cause", "?"),
            channel.get("cause_txt", ""),
        )
        call.state.hangup_event = "ChannelHangupRequest"
        call.state.hangup_cause = str(channel.get("cause")) if channel.get("cause") is not None else None
        call.state.hangup_cause_txt = channel.get("cause_txt")
        await self.cleanup_call(call)

    async def _handle_channel_left_bridge(self, event: dict) -> None:
        channel = event.get("channel") or {}
        channel_id = channel.get("id")
        if not channel_id:
            return
        call = self._find_call_for_channel(channel_id)
        if call is None:
            return
        if channel_id == call.human_channel_id:
            logger.info(
                "Human channel left bridge: %s — cleaning up call",
                channel_id,
            )
            await self.cleanup_call(call)

    async def cleanup_call(self, call: CallSession) -> None:
        if call.state.cleaning_up:
            return
        call.state.cleaning_up = True
        call.state.active = False

        self._finalize_outbound_dial_status(call)
        await self._notify_platform_dial_status(call)

        # Flush any buffered transcript before ending the platform session.
        await self._flush_all_transcripts(call)
        # Notify platform while session metadata is still attached.
        await self._platform_call_end(call)

        # Stop the per-call Gemini session FIRST so it stops touching
        # state/queues we're about to reset. The async with inside
        # _gemini_loop will close the WebSocket cleanly on cancellation.
        call.call_active.clear()
        if call.gemini_task is not None and not call.gemini_task.done():
            call.gemini_task.cancel()
            try:
                await call.gemini_task
            except (asyncio.CancelledError, Exception):
                pass
        call.gemini_task = None
        if call.pacer_task is not None and not call.pacer_task.done():
            call.pacer_task.cancel()
            try:
                await call.pacer_task
            except (asyncio.CancelledError, Exception):
                pass
        call.pacer_task = None
        call.session_ready.clear()
        call.session = None

        if self.http is not None:
            try:
                if call.state.human_channel_id:
                    hid = call.state.human_channel_id
                    await self.http.post(f"/channels/{hid}/hangup")
                    await self.http.delete(f"/channels/{hid}")
            except Exception:
                pass

            try:
                if call.state.external_channel_id:
                    await self.http.delete(f"/channels/{call.state.external_channel_id}")
            except Exception:
                pass

            try:
                if call.state.bridge_id:
                    await self.http.delete(f"/bridges/{call.state.bridge_id}")
            except Exception:
                pass

        if call.rtp_transport is not None:
            call.rtp_transport.close()
            call.rtp_transport = None
        self._drain_queue(call.audio_ingest_queue)
        self._drain_queue(call.rtp_out_queue)
        self._release_rtp_port(call.rtp_port)
        self._calls.pop(call.human_channel_id, None)
        logger.info(
            "Call cleaned up; channel=%s port=%d active_calls=%d",
            call.human_channel_id,
            call.rtp_port,
            len(self._calls),
        )

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

    def _upsert_dial_status(self, channel_id: str, **fields: Any) -> dict[str, Any]:
        row = dict(self._dial_status.get(channel_id) or {})
        row.update({k: v for k, v in fields.items() if v is not None})
        row["channel_id"] = channel_id
        row["updated_at"] = time.time()
        phase = row.get("dial_phase") or row.get("phase") or "ringing"
        row["dial_phase"] = phase
        outcome = row.get("outcome")
        row["label"] = _dial_status_message(phase, outcome)
        row["terminal"] = phase == "ended" or bool(outcome)
        self._dial_status[channel_id] = row
        return row

    def get_dial_status(self, channel_id: str) -> Optional[dict[str, Any]]:
        row = self._dial_status.get(channel_id)
        if row:
            return dict(row)
        pending = self._pending_outbound.get(channel_id)
        if pending:
            return self._upsert_dial_status(
                channel_id,
                dial_phase="ringing",
                endpoint=pending.get("endpoint"),
                agent_slug=pending.get("agent_slug"),
                lead_id=pending.get("lead_id"),
            )
        return None

    async def _notify_platform_dial_status(self, call: CallSession) -> None:
        if not self.platform_url or not call.state.platform_session_id:
            return
        row = self.get_dial_status(call.human_channel_id) or {}
        payload = {
            "session_id": call.state.platform_session_id,
            "channel_id": call.human_channel_id,
            "dial_phase": row.get("dial_phase") or call.state.dial_phase,
            "outcome": row.get("outcome"),
            "hangup_cause": row.get("hangup_cause"),
            "hangup_cause_txt": row.get("hangup_cause_txt"),
            "message": row.get("label"),
            "prospect_answered": call.state.prospect_answered,
        }
        try:
            assert self.http is not None
            await self.http.post(
                f"{self.platform_url}/internal/calls/dial-status",
                json=payload,
                headers=self._platform_headers(),
                timeout=5.0,
            )
        except Exception:
            logger.debug("Dial status notify failed session=%s", call.state.platform_session_id)

    def _finalize_outbound_dial_status(self, call: CallSession) -> None:
        if call.state.call_direction != "outbound":
            return
        channel_id = call.human_channel_id or ""
        if not channel_id:
            return
        phase = call.state.dial_phase or "ringing"
        had_media = call.state.rtp_in_frames > 0 or call.state.prospect_answered
        if call.state.hangup_event == "NoAnswerTimeout":
            outcome = "no_answer"
        else:
            outcome = _hangup_outcome(
                cause=call.state.hangup_cause,
                cause_txt=call.state.hangup_cause_txt,
                dial_phase=phase,
                had_media=had_media,
            )
        call.state.dial_outcome = outcome
        self._upsert_dial_status(
            channel_id,
            dial_phase="ended",
            outcome=outcome,
            hangup_cause=call.state.hangup_cause,
            hangup_cause_txt=call.state.hangup_cause_txt,
            session_id=call.state.platform_session_id,
            prospect_answered=call.state.prospect_answered,
        )

    async def _set_outbound_dial_phase(self, call: CallSession, phase: str) -> None:
        if call.state.call_direction != "outbound":
            return
        call.state.dial_phase = phase
        self._upsert_dial_status(
            call.human_channel_id,
            dial_phase=phase,
            session_id=call.state.platform_session_id,
            endpoint=call.state.dialed_endpoint,
            agent_slug=(call.state.agent_config or {}).get("agent_slug"),
            prospect_answered=call.state.prospect_answered,
        )
        await self._notify_platform_dial_status(call)

    async def originate_call(
        self,
        *,
        endpoint: str,
        agent_slug: str,
        lead_id: Optional[int] = None,
        caller_id: Optional[str] = None,
        connect_experience: Optional[str] = None,
        campaign_lead_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Originate an outbound call via ARI; StasisStart loads platform config."""
        if len(self._calls) >= self.max_concurrent_calls:
            raise HTTPException(
                status_code=409,
                detail=f"Bridge busy ({self.max_concurrent_calls} active call limit reached)",
            )
        assert self.http is not None

        cid = (caller_id or os.getenv("OUTBOUND_DEFAULT_CALLER_ID", "1000")).strip()
        app_args = [agent_slug, "outbound"]
        if lead_id is not None:
            app_args.append(str(lead_id))

        payload = {
            "endpoint": endpoint,
            "app": self.ari_app,
            "appArgs": ",".join(app_args),
            "callerId": f'"Aura" <{cid}>',
        }
        resp = await self.http.post("/channels", json=payload)
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json()
            except Exception:
                pass
            raise HTTPException(status_code=502, detail=f"ARI originate failed: {detail}")
        data = resp.json()
        channel_id = data.get("id")
        if not channel_id:
            raise HTTPException(status_code=502, detail="ARI originate returned no channel id")

        self._pending_outbound[channel_id] = {
            "agent_slug": agent_slug,
            "lead_id": lead_id,
            "endpoint": endpoint,
            "direction": "outbound",
            "connect_experience": (connect_experience or "auto_greeting"),
            "campaign_lead_id": campaign_lead_id,
        }
        self._upsert_dial_status(
            channel_id,
            dial_phase="ringing",
            endpoint=endpoint,
            agent_slug=agent_slug,
            lead_id=lead_id,
        )
        logger.info(
            "Originated outbound channel=%s agent=%s endpoint=%s lead=%s",
            channel_id,
            agent_slug,
            endpoint,
            lead_id,
        )
        return {
            "channel_id": channel_id,
            "status": "ringing",
            "endpoint": endpoint,
            "dial_phase": "ringing",
            "label": _dial_status_message("ringing"),
        }

    async def _platform_call_start(
        self,
        call: CallSession,
        channel_id: str,
        caller_id: Optional[str],
        agent_slug: Optional[str] = None,
        dialed_extension: Optional[str] = None,
        *,
        direction: str = "inbound",
        lead_id: Optional[int] = None,
        dialed_endpoint: Optional[str] = None,
        campaign_lead_id: Optional[int] = None,
    ) -> None:
        """Load per-call agent config from the platform API."""
        state = call.state
        state.call_started_at = time.monotonic()
        fallback = {
            "model": self.gemini_model,
            "voice": self.gemini_voice,
            "system_instruction": SYSTEM_PROMPT,
            "tools": [],
            "agent_id": None,
        }
        if not self.platform_url:
            state.agent_config = fallback
            return
        try:
            assert self.http is not None
            payload: dict = {
                "channel_id": channel_id,
                "caller_id": caller_id,
                "direction": direction,
            }
            if agent_slug:
                payload["agent_slug"] = agent_slug
            if dialed_extension:
                payload["dialed_extension"] = dialed_extension
            if lead_id is not None:
                payload["lead_id"] = lead_id
            if dialed_endpoint:
                payload["dialed_endpoint"] = dialed_endpoint
            if campaign_lead_id is not None:
                payload["campaign_lead_id"] = campaign_lead_id
            resp = await self.http.post(
                f"{self.platform_url}/internal/calls/start",
                json=payload,
                headers=self._platform_headers(),
                timeout=10.0,
            )
            resp.raise_for_status()
            cfg = resp.json()
            state.platform_session_id = cfg.get("session_id")
            state.agent_config = cfg
            logger.info(
                "Platform call session=%s agent=%s",
                state.platform_session_id,
                cfg.get("agent_slug", "?"),
            )
        except Exception:
            logger.exception("Platform /internal/calls/start failed; using fallback config")
            state.agent_config = fallback

        active_cfg = state.agent_config or {}
        instruction = active_cfg.get("system_instruction") or SYSTEM_PROMPT
        state.token_usage.add_text_context(instruction)

    async def _platform_transcript(self, call: CallSession, role: str, text: str) -> None:
        if not self.platform_url or not call.state.platform_session_id or not text.strip():
            return
        try:
            assert self.http is not None
            await self.http.post(
                f"{self.platform_url}/internal/calls/transcript",
                json={
                    "session_id": call.state.platform_session_id,
                    "role": role,
                    "text": text,
                },
                headers=self._platform_headers(),
                timeout=5.0,
            )
        except Exception:
            logger.warning("Failed to post transcript to platform", exc_info=True)

    def _buffer_transcript(self, call: CallSession, role: str, text: str) -> None:
        if not text or not text.strip():
            return
        if role == "user":
            call.state.user_tx_parts.append(text)
        else:
            call.state.model_tx_parts.append(text)

    async def _flush_transcript_role(self, call: CallSession, role: str) -> None:
        parts = call.state.user_tx_parts if role == "user" else call.state.model_tx_parts
        merged = _join_transcript_fragments(parts)
        if role == "user":
            call.state.user_tx_parts = []
        else:
            call.state.model_tx_parts = []
        if merged:
            await self._platform_transcript(call, role, merged)

    async def _flush_all_transcripts(self, call: CallSession) -> None:
        await self._flush_transcript_role(call, "user")
        await self._flush_transcript_role(call, "model")

    async def _on_turn_complete(self, call: CallSession) -> None:
        """Flush buffered transcriptions at each turn boundary."""
        await self._flush_transcript_role(call, "user")
        await self._flush_transcript_role(call, "model")

    async def _platform_tool(
        self, call: CallSession, tool_name: str, call_id: str, params: dict
    ) -> dict:
        if not self.platform_url or not call.state.platform_session_id:
            return {"id": call_id, "name": tool_name, "response": {"error": "no platform session"}}
        try:
            assert self.http is not None
            resp = await self.http.post(
                f"{self.platform_url}/internal/calls/tool",
                json={
                    "session_id": call.state.platform_session_id,
                    "agent_id": call.state.agent_config.get("agent_id"),
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

    async def _platform_call_end(self, call: CallSession) -> None:
        if call.state.platform_end_sent:
            return
        if not self.platform_url or not call.state.platform_session_id:
            return
        duration = None
        if call.state.call_started_at:
            duration = time.monotonic() - call.state.call_started_at
        payload = {
            "session_id": call.state.platform_session_id,
            "channel_id": call.state.human_channel_id,
            "duration_sec": duration,
            "stats": {
                "rtp_in": call.state.rtp_in_frames,
                "rtp_out": call.state.rtp_out_frames,
                "gemini_turns": call.state.gemini_turn_completes,
                "interruptions": call.state.gemini_interruptions,
                "hangup_event": call.state.hangup_event,
                "hangup_cause": call.state.hangup_cause,
                "hangup_cause_txt": call.state.hangup_cause_txt,
            },
            "token_usage": call.state.token_usage.to_dict(),
        }
        for attempt in range(2):
            try:
                assert self.http is not None
                await self.http.post(
                    f"{self.platform_url}/internal/calls/end",
                    json=payload,
                    headers=self._platform_headers(),
                    timeout=10.0,
                )
                call.state.platform_end_sent = True
                return
            except Exception:
                if attempt == 0:
                    logger.warning(
                        "Platform call end failed (retrying) session=%s",
                        call.state.platform_session_id,
                        exc_info=True,
                    )
                    await asyncio.sleep(0.5)
                else:
                    logger.warning(
                        "Failed to notify platform of call end session=%s",
                        call.state.platform_session_id,
                        exc_info=True,
                    )

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

    async def _send_auto_greeting(self, call: CallSession, session) -> None:
        """Kick the model to speak first. Only marks greeting_sent after success."""
        greeting = _auto_greeting_for_direction(call.state.call_direction)
        if not greeting or call.state.greeting_sent:
            return
        call.state.token_usage.add_text_context(greeting)
        await session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=greeting)],
            ),
            turn_complete=True,
        )
        call.state.greeting_sent = True
        logger.info("AUTO_GREETING sent (%s)", call.state.call_direction)

    async def _gemini_loop(self, call: CallSession) -> None:
        cfg = call.state.agent_config or {}
        model = cfg.get("model") or self.gemini_model
        config = self._build_live_config(cfg)

        # Per-call session loop. We reconnect on transient errors (network
        # blips, 1011 keepalive timeouts) but exit cleanly when the call
        # ends, so a fresh WebSocket is opened for the next call.
        while call.call_active.is_set() and not self._stopping.is_set():
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
                    call.session = session
                    call.session_ready.set()
                    logger.info(
                        "Gemini Live connected (voice=%s)",
                        cfg.get("voice", self.gemini_voice),
                    )

                    try:
                        await self._send_auto_greeting(call, session)
                    except Exception:
                        logger.exception(
                            "AUTO_GREETING failed; will retry after reconnect"
                        )

                    send_task = asyncio.create_task(
                        self._gemini_send_loop(call, session), name="gemini-send-loop"
                    )
                    recv_task = asyncio.create_task(
                        self._gemini_recv_loop(call, session), name="gemini-recv-loop"
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
                        call.session_ready.clear()
                        call.session = None

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not call.call_active.is_set():
                    break
                logger.warning(
                    "Gemini loop error: %s; reconnecting in 2s", exc
                )
                await asyncio.sleep(2)

        logger.info("Gemini per-call session loop exited")

    async def _gemini_send_loop(self, call: CallSession, session) -> None:
        # Same shape as React: stream 256 ms PCM16 chunks continuously.
        call.state.last_user_tx_ts = time.monotonic()
        while not self._stopping.is_set():
            try:
                audio_chunk = await asyncio.wait_for(
                    call.audio_ingest_queue.get(), timeout=0.01
                )
            except asyncio.TimeoutError:
                continue
            if not audio_chunk:
                continue
            try:
                await session.send_realtime_input(
                    audio=types.Blob(
                        data=audio_chunk,
                        mime_type="audio/pcm;rate=16000",
                    ),
                )
            except Exception as exc:
                if self._is_gemini_session_closed(exc):
                    logger.warning("Gemini send loop: session closed")
                    raise
                logger.exception("Gemini send_realtime_input failed")
                raise
            chunk_len = len(audio_chunk)
            call.state.gemini_in_chunks += 1
            call.state.gemini_in_bytes += chunk_len
            call.state.token_usage.add_audio_input(chunk_len, sample_rate_hz=16000)
            call.state.last_user_tx_ts = time.monotonic()

    @staticmethod
    def _is_gemini_session_closed(exc: BaseException) -> bool:
        name = type(exc).__name__
        if "ConnectionClosed" in name:
            return True
        return "1000" in str(exc)

    async def _gemini_recv_loop(self, call: CallSession, session) -> None:
        # session.receive() yields ONE model turn then returns (it breaks on
        # turn_complete). Google's cookbook re-enters receive() in a while
        # loop for every subsequent turn — without that, turn 2+ is deaf.
        try:
            while not self._stopping.is_set():
                async for response in session.receive():
                    call.state.token_usage.merge_api_usage(
                        extract_usage_metadata(response)
                    )

                    tool_call = getattr(response, "tool_call", None)
                    if tool_call is not None:
                        await self._handle_tool_call(call, session, tool_call)

                    server_content = getattr(response, "server_content", None)
                    if server_content is None:
                        continue

                    # React reference: only handle interruption (clear playback).
                    if getattr(server_content, "interrupted", False):
                        call.state.gemini_interruptions += 1
                        logger.info(
                            "Gemini interrupted (#%d); flushing playback queue",
                            call.state.gemini_interruptions,
                        )
                        self._drain_queue(call.rtp_out_queue)
                        call.state.out_pcm8_buffer = b""
                        call.state.rx_resampler.reset()

                    in_tx = getattr(server_content, "input_transcription", None)
                    if in_tx is not None:
                        text = getattr(in_tx, "text", None)
                        if text:
                            logger.info("USER: %s", text)
                            self._buffer_transcript(call, "user", text)
                            call.state.token_usage.add_text_output(text)

                    out_tx = getattr(server_content, "output_transcription", None)
                    if out_tx is not None:
                        text = getattr(out_tx, "text", None)
                        if text:
                            logger.info("GEMINI: %s", text)
                            self._buffer_transcript(call, "model", text)
                            call.state.token_usage.add_text_output(text)

                    if getattr(server_content, "turn_complete", False):
                        call.state.gemini_turn_completes += 1
                        logger.info(
                            "Gemini turn_complete (#%d) — ready for next turn",
                            call.state.gemini_turn_completes,
                        )
                        asyncio.create_task(self._on_turn_complete(call))

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
                        call.state.gemini_out_bytes += len(ab)
                        call.state.token_usage.add_audio_output(len(ab), sample_rate_hz=24000)
                        call.state.last_gemini_audio_ts = time.monotonic()
                        self._enqueue_output_audio(call, ab)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._is_gemini_session_closed(exc):
                return
            raise

    async def _platform_transfer(
        self, call: CallSession, handoff_summary: str, reason: Optional[str] = None
    ) -> Optional[dict]:
        if not self.platform_url or not call.state.platform_session_id:
            return None
        try:
            assert self.http is not None
            resp = await self.http.post(
                f"{self.platform_url}/internal/calls/transfer",
                json={
                    "session_id": call.state.platform_session_id,
                    "channel_id": call.human_channel_id,
                    "handoff_summary": handoff_summary,
                    "reason": reason,
                },
                headers=self._platform_headers(),
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.exception("Platform call transfer failed")
            return None

    async def _restart_gemini_session(self, call: CallSession, new_cfg: dict) -> None:
        """Swap Gemini persona mid-call (e.g. sales → support transfer)."""
        logger.info(
            "Restarting Gemini for transfer channel=%s new_session=%s agent=%s",
            call.human_channel_id,
            new_cfg.get("session_id"),
            new_cfg.get("agent_slug"),
        )
        call.call_active.clear()
        if call.gemini_task is not None and not call.gemini_task.done():
            call.gemini_task.cancel()
            try:
                await call.gemini_task
            except (asyncio.CancelledError, Exception):
                pass
        call.gemini_task = None
        call.session_ready.clear()
        call.session = None

        call.state.greeting_sent = False
        call.state.end_call_pending = False
        call.state.platform_session_id = new_cfg.get("session_id")
        call.state.agent_config = new_cfg
        call.state.call_direction = "inbound"
        instruction = new_cfg.get("system_instruction") or ""
        if instruction:
            call.state.token_usage.add_text_context(instruction)

        self._drain_queue(call.rtp_out_queue)
        call.state.out_pcm8_buffer = b""

        call.call_active.set()
        call.gemini_task = asyncio.create_task(
            self._gemini_loop(call), name=f"gemini-loop-transfer-{call.human_channel_id}"
        )

    async def _execute_transfer(self, call: CallSession, params: dict) -> None:
        await self._flush_all_transcripts(call)
        new_cfg = await self._platform_transfer(
            call,
            handoff_summary=str(params.get("handoff_summary") or ""),
            reason=params.get("reason"),
        )
        if not new_cfg:
            logger.error("Transfer aborted — platform did not return new config")
            return
        await self._restart_gemini_session(call, new_cfg)

    async def _handle_tool_call(self, call: CallSession, session, tool_call) -> None:
        transfer_params: Optional[dict] = None

        async def run_one(fc):
            nonlocal transfer_params
            params = dict(fc.args) if fc.args else {}
            if fc.name == "transfer_to_support":
                transfer_params = params
            result = await self._platform_tool(call, fc.name, fc.id, params)
            return types.FunctionResponse(
                id=result.get("id", fc.id),
                name=result.get("name", fc.name),
                response=result.get("response", {}),
            )

        responses = await asyncio.gather(
            *[run_one(fc) for fc in tool_call.function_calls]
        )
        for fr in responses:
            try:
                payload = json.dumps(fr.response) if fr.response is not None else ""
            except (TypeError, ValueError):
                payload = str(fr.response)
            call.state.token_usage.add_text_context(payload)
        logger.info("Tool call batch: %s", [r.name for r in responses])
        await session.send_tool_response(function_responses=list(responses))
        if transfer_params is not None:
            asyncio.create_task(
                self._execute_transfer(call, transfer_params),
                name=f"call-transfer-{call.human_channel_id}",
            )
        elif any(r.name == "end_call" for r in responses):
            self._schedule_end_call(call)

    def _schedule_end_call(self, call: CallSession) -> None:
        if call.state.end_call_pending or call.state.cleaning_up:
            return
        call.state.end_call_pending = True
        logger.info(
            "end_call requested; waiting for playback to finish channel=%s",
            call.human_channel_id,
        )
        asyncio.create_task(
            self._end_call_after_playback(call),
            name=f"end-call-drain-{call.human_channel_id}",
        )

    async def _end_call_after_playback(self, call: CallSession) -> None:
        """Hang up only after queued farewell audio has been sent to the caller."""
        started = time.monotonic()
        await asyncio.sleep(END_CALL_MIN_WAIT_SEC)
        while time.monotonic() - started < END_CALL_MAX_WAIT_SEC:
            if not call.state.active or call.state.cleaning_up:
                return
            queue_empty = call.rtp_out_queue.empty() and not call.state.out_pcm8_buffer
            if queue_empty:
                last_out = call.state.last_outbound_rtp_ts
                if not last_out:
                    break
                if time.monotonic() - last_out >= END_CALL_PLAYBACK_GRACE_SEC:
                    break
            await asyncio.sleep(0.1)
        if call.state.active and not call.state.cleaning_up:
            logger.info(
                "end_call playback drained (%.1fs); hanging up channel=%s",
                time.monotonic() - started,
                call.human_channel_id,
            )
            await self.cleanup_call(call)

    # ----------------------------------------------------------------- RTP

    def _enqueue_output_audio(self, call: CallSession, pcm24: bytes) -> None:
        """Convert Gemini's 24 kHz PCM16 chunk into 20 ms ulaw RTP payloads
        and enqueue them for the paced sender. Pacing is done elsewhere.

        Also tees the same chunk (resampled to 16 kHz) into the APM's
        far-end buffer so the echo canceller knows what the caller will
        be hearing.
        """
        if call.state.asterisk_rtp_addr is None:
            return

        # 24 kHz -> 8 kHz for Asterisk (zero-phase polyphase sinc).
        # Stateful: filter ringing at chunk boundaries is absorbed by the
        # Resampler so the spliced audio sounds continuous.
        pcm8 = _resample_pcm16(pcm24, call.state.rx_resampler, ratio=1.0 / 3.0)
        call.state.out_pcm8_buffer += pcm8

        # 24 kHz -> 16 kHz for the APM far-end reference. Independent
        # resampler so its filter state doesn't fight with the 8 kHz one.
        if call.state.apm is not None:
            pcm16_ref = _resample_pcm16(
                pcm24, call.state.far_resampler, ratio=2.0 / 3.0
            )
            call.state.far_end_buf += pcm16_ref
            # Cap the far-end buffer at ~2 s so a slow inbound (or a
            # cleanup race) can't grow it unboundedly. AEC only needs
            # ~stream_delay_ms of history aligned with the near-end.
            max_bytes = 16000 * 2 * 2  # 2 s
            if len(call.state.far_end_buf) > max_bytes:
                call.state.far_end_buf = call.state.far_end_buf[-max_bytes:]

        while len(call.state.out_pcm8_buffer) >= FRAME_BYTES_PCM16_8K:
            frame_pcm16 = call.state.out_pcm8_buffer[:FRAME_BYTES_PCM16_8K]
            call.state.out_pcm8_buffer = call.state.out_pcm8_buffer[FRAME_BYTES_PCM16_8K:]
            ulaw_payload = audioop.lin2ulaw(frame_pcm16, 2)
            try:
                call.rtp_out_queue.put_nowait(ulaw_payload)
            except asyncio.QueueFull:
                logger.warning("RTP out queue full; dropping outbound frame")
                return

    async def _rtp_pacer_loop(self, call: CallSession) -> None:
        """Send one ulaw RTP packet every 20 ms when audio is queued.

        Asterisk's jitter buffer expects ptime-paced RTP. Without this the
        bursts of frames we get whenever Gemini delivers a chunk cause
        audible clicks/gaps even though the bytes arrive correctly.
        """
        next_send = time.monotonic()
        while not self._stopping.is_set():
            try:
                ulaw_payload = await asyncio.wait_for(
                    call.rtp_out_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                next_send = time.monotonic()
                continue

            if (
                call.rtp_transport is None
                or call.state.asterisk_rtp_addr is None
            ):
                # Lost the call; drop the frame.
                continue

            packet = build_rtp_packet(
                payload=ulaw_payload,
                sequence_number=call.state.tx_seq,
                timestamp=call.state.tx_timestamp,
                ssrc=call.state.tx_ssrc,
                payload_type=0,  # PCMU
            )

            try:
                self._send_rtp_for_call(call, packet, call.state.asterisk_rtp_addr)
            except Exception:
                logger.exception("Failed to send RTP packet")
                continue

            call.state.rtp_out_frames += 1
            # Record outbound timestamp for TTS gating. Inbound audio
            # arriving within GATE_TAIL_MS of this is treated as likely
            # acoustic echo of our own output.
            call.state.last_outbound_rtp_ts = time.monotonic()
            call.state.tx_seq = (call.state.tx_seq + 1) & 0xFFFF
            call.state.tx_timestamp = (call.state.tx_timestamp + SAMPLES_PER_FRAME_8K) & 0xFFFFFFFF

            # Wall-clock pace: sleep until next_send. If we fell behind,
            # reset the schedule so we don't burst-catch-up.
            next_send += PTIME_MS / 1000.0
            now = time.monotonic()
            delay = next_send - now
            if delay < -0.1:
                next_send = now
            elif delay > 0:
                await asyncio.sleep(delay)

    async def handle_rtp_packet(self, call: CallSession, data: bytes, addr: tuple[str, int]) -> None:
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
        if not call.state.active or call.state.external_channel_id is None:
            return

        if call.state.asterisk_rtp_addr is None:
            rip = addr[0]
            if rip in ("127.0.0.1", "::1", "localhost") and self._asterisk_rtp_host_ip:
                rip = self._asterisk_rtp_host_ip
            call.state.asterisk_rtp_addr = (rip, addr[1])
            logger.info("Learned Asterisk RTP remote address: %s", call.state.asterisk_rtp_addr)

        if call.state.rtp_in_frames == 0:
            logger.info(
                "First RTP from Asterisk: %d bytes from %s (pcmu)",
                len(payload),
                addr,
            )
        call.state.rtp_in_frames += 1

        if (
            call.state.call_direction == "outbound"
            and not call.state.prospect_answered
            and call.state.rtp_in_frames >= 15
        ):
            asyncio.create_task(self._mark_prospect_answered(call))

        # PCMU -> PCM16 8 kHz -> PCM16 16 kHz for Gemini.
        # libsamplerate (sinc_fastest) gives Gemini a clean upsampled
        # signal; audioop.ratecv loses HF detail and weakens VAD pickup
        # on telephony audio (see GoogleCloudPlatform/generative-ai
        # gemini-live-telephony-app reference).
        pcm8 = audioop.ulaw2lin(payload, 2)
        pcm16k = _resample_pcm16(pcm8, call.state.tx_resampler, ratio=2.0)
        # Small static lift so the APM's AGC has signal to work with.
        # AGC will then dynamically normalise from here. audioop.mul
        # saturates at int16 bounds, so brief peaks just clip instead
        # of wrapping.
        if INBOUND_GAIN != 1.0:
            pcm16k = audioop.mul(pcm16k, 2, INBOUND_GAIN)

        try:
            frame_rms = audioop.rms(pcm16k, 2)
            if frame_rms > call.state.in_rms_peak:
                call.state.in_rms_peak = frame_rms
            call.state.in_rms_sum += frame_rms
            call.state.in_rms_count += 1
        except audioop.error:
            frame_rms = 0

        # First-frames-after-bridge diagnostic. If these are all 0 even
        # before the AI says anything, audio isn't reaching us at all
        # (Asterisk mis-bridge or softphone muted from the start). If
        # they're nonzero but go to 0 only after the AI speaks, the
        # softphone is auto-muting on speaker output (use headphones).
        if call.state.rtp_in_frames <= 5:
            logger.info(
                "RTP early frame #%d: frame_rms=%d (raw 8k bytes=%d)",
                call.state.rtp_in_frames,
                frame_rms,
                len(payload),
            )

        if not call.session_ready.is_set():
            return

        now = time.monotonic()

        call.state.in_pcm16k_buffer += pcm16k

        # Optional APM stage (off by default). Only runs if a working
        # AudioProcessor was constructed at session start.
        if call.state.apm is not None:
            while len(call.state.in_pcm16k_buffer) >= APM_FRAME_BYTES_16K:
                near = call.state.in_pcm16k_buffer[:APM_FRAME_BYTES_16K]
                call.state.in_pcm16k_buffer = call.state.in_pcm16k_buffer[
                    APM_FRAME_BYTES_16K:
                ]
                if len(call.state.far_end_buf) >= APM_FRAME_BYTES_16K:
                    far = call.state.far_end_buf[:APM_FRAME_BYTES_16K]
                    call.state.far_end_buf = call.state.far_end_buf[
                        APM_FRAME_BYTES_16K:
                    ]
                else:
                    far = _SILENCE_10MS_16K
                try:
                    near_np = np.frombuffer(near, dtype=np.int16)
                    far_np = np.frombuffer(far, dtype=np.int16)
                    out_np = call.state.apm.process(near_np, far_np)
                    processed = out_np.tobytes()
                    call.state.apm_frames += 1
                    try:
                        rms = int(audioop.rms(processed, 2))
                        if rms > call.state.apm_rms_peak:
                            call.state.apm_rms_peak = rms
                        call.state.apm_rms_sum += rms
                        call.state.apm_rms_count += 1
                    except audioop.error:
                        pass
                except Exception:
                    processed = near
                call.state.in_pcm16k_clean_buffer += processed
        else:
            # No APM: pass the raw 16 kHz buffer through unchanged.
            call.state.in_pcm16k_clean_buffer += call.state.in_pcm16k_buffer
            call.state.in_pcm16k_buffer = b""

        # Re-frame to GEMINI_CHUNK_BYTES and enqueue for the send loop.
        while len(call.state.in_pcm16k_clean_buffer) >= GEMINI_CHUNK_BYTES:
            chunk = call.state.in_pcm16k_clean_buffer[:GEMINI_CHUNK_BYTES]
            call.state.in_pcm16k_clean_buffer = call.state.in_pcm16k_clean_buffer[
                GEMINI_CHUNK_BYTES:
            ]
            try:
                call.audio_ingest_queue.put_nowait(chunk)
            except asyncio.QueueFull:
                logger.warning("Inbound audio queue full; dropping chunk")
                break


class RTPProtocol(asyncio.DatagramProtocol):
    def __init__(self, bridge: GeminiLiveBridge, call: CallSession) -> None:
        self.bridge = bridge
        self.call = call

    def datagram_received(self, data: bytes, addr) -> None:
        asyncio.create_task(self.bridge.handle_rtp_packet(self.call, data, addr))


bridge = GeminiLiveBridge()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await bridge.start()
    try:
        yield
    finally:
        await bridge.stop()


app = FastAPI(lifespan=lifespan)


class OriginateIn(BaseModel):
    agent_slug: str
    endpoint: str
    lead_id: Optional[int] = None
    caller_id: Optional[str] = None
    connect_experience: Optional[str] = None
    campaign_lead_id: Optional[int] = None


def _verify_bridge_token(x_bridge_token: str = Header(..., alias="X-Bridge-Token")) -> None:
    expected = os.getenv("BRIDGE_INTERNAL_TOKEN", "")
    if not expected or not secrets.compare_digest(x_bridge_token, expected):
        raise HTTPException(status_code=403, detail="Invalid bridge token")


@app.post("/internal/originate")
async def internal_originate(
    body: OriginateIn,
    _: None = Depends(_verify_bridge_token),
):
    return await bridge.originate_call(
        endpoint=body.endpoint,
        agent_slug=body.agent_slug,
        lead_id=body.lead_id,
        caller_id=body.caller_id,
        connect_experience=body.connect_experience,
        campaign_lead_id=body.campaign_lead_id,
    )


@app.get("/health")
async def health():
    active_calls = list(bridge._calls.values())
    first_call = active_calls[0] if active_calls else None
    first_state = first_call.state if first_call else None
    return {
        "ok": True,
        "active_calls": len(active_calls),
        "calls": [
            {
                "channel_id": call.human_channel_id,
                "rtp_port": call.rtp_port,
                "session_ready": call.session_ready.is_set(),
            }
            for call in active_calls
        ],
        "session_ready": first_call.session_ready.is_set() if first_call else False,
        "bridge_active": bool(active_calls),
        "bridge_id": first_state.bridge_id if first_state else None,
        "human_channel_id": first_state.human_channel_id if first_state else None,
        "external_channel_id": first_state.external_channel_id if first_state else None,
        "asterisk_rtp_addr": (
            list(first_state.asterisk_rtp_addr)
            if first_state and first_state.asterisk_rtp_addr
            else None
        ),
        "model": (
            first_state.agent_config.get("model")
            if first_state and first_state.agent_config
            else bridge.gemini_model
        ),
        "voice": (
            first_state.agent_config.get("voice")
            if first_state and first_state.agent_config
            else bridge.gemini_voice
        ),
        "platform_session_id": first_state.platform_session_id if first_state else None,
        "platform_url": bridge.platform_url or None,
        "rtp_port_base": bridge.rtp_port_base,
        "rtp_port_count": bridge.rtp_port_count,
        "inbound_gain": INBOUND_GAIN,
        "tts_gating": TTS_GATING_ENABLED,
        "tts_gate_tail_ms": GATE_TAIL_MS,
        "max_concurrent_calls": bridge.max_concurrent_calls,
        "free_ports": len(bridge._free_ports),
    }


@app.get("/internal/status")
async def internal_status(_: None = Depends(_verify_bridge_token)):
    now = time.monotonic()
    call_rows = []
    for call in bridge._calls.values():
        state = call.state
        stall_sec = (
            (now - state.rtp_stall_since) if state.rtp_stall_since else 0.0
        )
        cfg = state.agent_config or {}
        call_rows.append(
            {
                "channel_id": call.human_channel_id,
                "rtp_port": call.rtp_port,
                "session_ready": call.session_ready.is_set(),
                "bridge_id": state.bridge_id,
                "external_channel_id": state.external_channel_id,
                "platform_session_id": state.platform_session_id,
                "direction": state.call_direction,
                "agent_id": cfg.get("agent_id"),
                "agent_slug": cfg.get("agent_slug"),
                "rtp_in_frames": state.rtp_in_frames,
                "rtp_stall_sec": round(stall_sec, 1),
                "dial_phase": state.dial_phase or None,
                "prospect_answered": state.prospect_answered,
                "dialed_endpoint": state.dialed_endpoint,
            }
        )
    return {
        "active_calls": len(bridge._calls),
        "max_concurrent": bridge.max_concurrent_calls,
        "free_ports": len(bridge._free_ports),
        "calls": call_rows,
        "pending_dials": [
            bridge.get_dial_status(cid)
            for cid in bridge._pending_outbound
            if bridge.get_dial_status(cid)
        ],
    }


@app.post("/internal/hangup/{channel_id}")
async def internal_hangup(
    channel_id: str,
    _: None = Depends(_verify_bridge_token),
):
    return await bridge.hangup_channel(channel_id)


@app.get("/internal/dial-status/{channel_id}")
async def internal_dial_status(
    channel_id: str,
    _: None = Depends(_verify_bridge_token),
):
    row = bridge.get_dial_status(channel_id)
    if not row:
        raise HTTPException(status_code=404, detail="Unknown dial channel")
    return row
