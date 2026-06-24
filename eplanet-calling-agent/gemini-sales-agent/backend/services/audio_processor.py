"""G.711 ulaw codec + PCM resampling for Asterisk ↔ Gemini Live audio bridge."""
try:
    import audioop  # Python <= 3.12
except ImportError:  # Python >= 3.13
    import audioop_lts as audioop
import struct


ULAW_RATE = 8000       # Asterisk G.711 ulaw
GEMINI_IN_RATE = 16000 # Gemini Live input
GEMINI_OUT_RATE = 24000 # Gemini Live output


def ulaw_to_pcm16(ulaw_bytes: bytes) -> bytes:
    """Convert G.711 ulaw bytes to 16-bit PCM bytes."""
    return audioop.ulaw2lin(ulaw_bytes, 2)


def pcm16_to_ulaw(pcm_bytes: bytes) -> bytes:
    """Convert 16-bit PCM bytes to G.711 ulaw bytes."""
    return audioop.lin2ulaw(pcm_bytes, 2)


def resample(pcm_bytes: bytes, from_rate: int, to_rate: int, state=None):
    """Resample 16-bit PCM from from_rate to to_rate using audioop."""
    if from_rate == to_rate:
        return pcm_bytes, state
    result, new_state = audioop.ratecv(pcm_bytes, 2, 1, from_rate, to_rate, state)
    return result, new_state


def ulaw_to_gemini_pcm(ulaw_bytes: bytes) -> bytes:
    """Convert Asterisk G.711 ulaw (8kHz) → 16-bit PCM (16kHz) for Gemini."""
    pcm8k = ulaw_to_pcm16(ulaw_bytes)
    pcm16k, _ = resample(pcm8k, ULAW_RATE, GEMINI_IN_RATE)
    return pcm16k


def gemini_pcm_to_ulaw(pcm24k_bytes: bytes) -> bytes:
    """Convert Gemini 16-bit PCM (24kHz) → G.711 ulaw (8kHz) for Asterisk."""
    pcm8k, _ = resample(pcm24k_bytes, GEMINI_OUT_RATE, ULAW_RATE)
    return pcm16_to_ulaw(pcm8k)


def float32_to_int16(float_bytes: bytes) -> bytes:
    """Convert 32-bit float PCM to 16-bit int PCM."""
    n = len(float_bytes) // 4
    floats = struct.unpack(f"{n}f", float_bytes)
    ints = []
    for f in floats:
        f = max(-1.0, min(1.0, f))
        ints.append(int(f * 32767))
    return struct.pack(f"{n}h", *ints)


def int16_to_float32(int16_bytes: bytes) -> bytes:
    """Convert 16-bit int PCM to 32-bit float PCM."""
    n = len(int16_bytes) // 2
    ints = struct.unpack(f"{n}h", int16_bytes)
    floats = [i / 32768.0 for i in ints]
    return struct.pack(f"{n}f", *floats)
