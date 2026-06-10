"""Estimate Gemini Live session token usage for pricing.

Google bills Live API by modality (audio vs text). The Live API does not always
return usageMetadata on every chunk, so we estimate audio from PCM duration and
text from character heuristics. Rates are configurable for your pricing sheet.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


# Google docs: ~25 TPS for Live audio (varies by model); override via env.
AUDIO_INPUT_TPS = _env_float("GEMINI_AUDIO_INPUT_TPS", 25.0)
AUDIO_OUTPUT_TPS = _env_float("GEMINI_AUDIO_OUTPUT_TPS", 25.0)
TEXT_CHARS_PER_TOKEN = _env_float("GEMINI_TEXT_CHARS_PER_TOKEN", 4.0)

# USD per 1M tokens — defaults for Gemini Live-style pricing (override in .env).
PRICE_AUDIO_INPUT_PER_1M = _env_float("GEMINI_PRICE_AUDIO_INPUT_PER_1M", 3.0)
PRICE_AUDIO_OUTPUT_PER_1M = _env_float("GEMINI_PRICE_AUDIO_OUTPUT_PER_1M", 12.0)
PRICE_TEXT_INPUT_PER_1M = _env_float("GEMINI_PRICE_TEXT_INPUT_PER_1M", 0.5)
PRICE_TEXT_OUTPUT_PER_1M = _env_float("GEMINI_PRICE_TEXT_OUTPUT_PER_1M", 2.0)


def pcm16_duration_sec(byte_count: int, sample_rate_hz: int) -> float:
    """PCM16 mono: 2 bytes per sample."""
    if byte_count <= 0 or sample_rate_hz <= 0:
        return 0.0
    return byte_count / (sample_rate_hz * 2)


def estimate_audio_tokens(byte_count: int, sample_rate_hz: int, *, tps: float) -> int:
    seconds = pcm16_duration_sec(byte_count, sample_rate_hz)
    return max(0, int(round(seconds * tps)))


def estimate_text_tokens(text: str) -> int:
    if not text or not text.strip():
        return 0
    return max(1, int(round(len(text) / TEXT_CHARS_PER_TOKEN)))


@dataclass
class SessionTokenUsage:
    """Per-call token buckets for Gemini Live pricing."""

    audio_input_tokens: int = 0
    text_input_context_tokens: int = 0
    audio_output_tokens: int = 0
    text_output_tokens: int = 0

    audio_input_bytes: int = 0
    audio_output_bytes: int = 0
    audio_input_sec: float = 0.0
    audio_output_sec: float = 0.0

    api_prompt_tokens: int = 0
    api_response_tokens: int = 0
    api_total_tokens: int = 0

    _audio_in_tps: float = field(default=AUDIO_INPUT_TPS, repr=False)
    _audio_out_tps: float = field(default=AUDIO_OUTPUT_TPS, repr=False)

    def add_audio_input(self, pcm_bytes: int, sample_rate_hz: int = 16000) -> None:
        self.audio_input_bytes += pcm_bytes
        sec = pcm16_duration_sec(pcm_bytes, sample_rate_hz)
        self.audio_input_sec += sec
        self.audio_input_tokens += estimate_audio_tokens(
            pcm_bytes, sample_rate_hz, tps=self._audio_in_tps
        )

    def add_audio_output(self, pcm_bytes: int, sample_rate_hz: int = 24000) -> None:
        self.audio_output_bytes += pcm_bytes
        sec = pcm16_duration_sec(pcm_bytes, sample_rate_hz)
        self.audio_output_sec += sec
        self.audio_output_tokens += estimate_audio_tokens(
            pcm_bytes, sample_rate_hz, tps=self._audio_out_tps
        )

    def add_text_context(self, text: str) -> None:
        self.text_input_context_tokens += estimate_text_tokens(text)

    def add_text_output(self, text: str) -> None:
        self.text_output_tokens += estimate_text_tokens(text)

    def merge_api_usage(self, usage: Any) -> None:
        """Accumulate usage_metadata from a Gemini response when present."""
        if usage is None:
            return
        prompt = getattr(usage, "prompt_token_count", None)
        candidates = getattr(usage, "candidates_token_count", None)
        total = getattr(usage, "total_token_count", None)
        if isinstance(usage, dict):
            prompt = usage.get("prompt_token_count", prompt)
            candidates = usage.get("candidates_token_count", candidates)
            total = usage.get("total_token_count", total)
        if prompt is not None:
            self.api_prompt_tokens += int(prompt)
        if candidates is not None:
            self.api_response_tokens += int(candidates)
        if total is not None:
            self.api_total_tokens += int(total)

    @property
    def estimated_input_tokens(self) -> int:
        return self.audio_input_tokens + self.text_input_context_tokens

    @property
    def estimated_output_tokens(self) -> int:
        return self.audio_output_tokens + self.text_output_tokens

    @property
    def estimated_total_tokens(self) -> int:
        return self.estimated_input_tokens + self.estimated_output_tokens

    def pricing_estimate_usd(self) -> dict[str, float]:
        ai = self.audio_input_tokens / 1_000_000 * PRICE_AUDIO_INPUT_PER_1M
        ao = self.audio_output_tokens / 1_000_000 * PRICE_AUDIO_OUTPUT_PER_1M
        ti = self.text_input_context_tokens / 1_000_000 * PRICE_TEXT_INPUT_PER_1M
        to = self.text_output_tokens / 1_000_000 * PRICE_TEXT_OUTPUT_PER_1M
        total = ai + ao + ti + to
        return {
            "audio_input_usd": round(ai, 6),
            "audio_output_usd": round(ao, 6),
            "text_context_usd": round(ti, 6),
            "text_output_usd": round(to, 6),
            "total_usd": round(total, 6),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "audio_input_tokens": self.audio_input_tokens,
            "text_input_context_tokens": self.text_input_context_tokens,
            "audio_output_tokens": self.audio_output_tokens,
            "text_output_tokens": self.text_output_tokens,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
            "estimated_total_tokens": self.estimated_total_tokens,
            "audio_input_bytes": self.audio_input_bytes,
            "audio_output_bytes": self.audio_output_bytes,
            "audio_input_sec": round(self.audio_input_sec, 2),
            "audio_output_sec": round(self.audio_output_sec, 2),
            "api_reported": {
                "prompt_tokens": self.api_prompt_tokens,
                "response_tokens": self.api_response_tokens,
                "total_tokens": self.api_total_tokens,
            }
            if (self.api_prompt_tokens or self.api_response_tokens or self.api_total_tokens)
            else None,
            "rates": {
                "audio_input_tps": self._audio_in_tps,
                "audio_output_tps": self._audio_out_tps,
                "text_chars_per_token": TEXT_CHARS_PER_TOKEN,
            },
            "pricing_estimate_usd": self.pricing_estimate_usd(),
        }


def extract_usage_metadata(response: Any) -> Optional[Any]:
    return getattr(response, "usage_metadata", None) or getattr(response, "usageMetadata", None)
