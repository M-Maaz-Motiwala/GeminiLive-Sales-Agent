"""Normalize phone numbers / DIDs for routing comparisons."""
from __future__ import annotations

import re

_DIGITS_ONLY = re.compile(r"\D+")


def normalize_did(value: str | None) -> str | None:
    """Return E.164-style digits only (e.g. 12107297915), or None if invalid."""
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    digits = _DIGITS_ONLY.sub("", raw)
    if len(digits) < 10:
        return None
    if len(digits) == 10:
        digits = "1" + digits
    return digits


def dids_match(a: str | None, b: str | None) -> bool:
    na, nb = normalize_did(a), normalize_did(b)
    if not na or not nb:
        return False
    return na == nb


def is_did_exten(exten: str | None) -> bool:
    """True when Asterisk EXTEN is a PSTN number, not a short lab extension."""
    if not exten:
        return False
    s = exten.strip()
    if s.startswith("+"):
        return True
    digits = _DIGITS_ONLY.sub("", s)
    return len(digits) >= 10
