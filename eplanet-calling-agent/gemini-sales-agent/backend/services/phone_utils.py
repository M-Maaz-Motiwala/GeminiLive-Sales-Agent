"""Phone normalization and ARI endpoint building (lab + trunk-ready)."""
from __future__ import annotations

import re
from typing import Optional

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
_DIGITS_RE = re.compile(r"\D+")


def digits_only(phone: str) -> str:
    return _DIGITS_RE.sub("", phone or "")


def normalize_e164(phone: str, default_country_code: str = "1") -> Optional[str]:
    """Best-effort E.164. Returns None if too few digits."""
    raw = (phone or "").strip()
    if not raw:
        return None
    if raw.upper().startswith("PJSIP/"):
        return None
    if raw.startswith("+"):
        cleaned = "+" + digits_only(raw)
        return cleaned if _E164_RE.match(cleaned) else None
    d = digits_only(raw)
    if not d:
        return None
    cc = digits_only(default_country_code) or "1"
    if len(d) >= 10 and not raw.startswith("+"):
        # US/CA 10-digit or longer with country implied
        if len(d) == 10 and cc == "1":
            return f"+1{d}"
        if len(d) > 10:
            return f"+{d}"
    if len(d) >= 7:
        return f"+{cc}{d}" if not d.startswith(cc) else f"+{d}"
    return None


def is_lab_extension(phone: str) -> bool:
    """True for 3–4 digit lab SIP extensions (1001, 1002)."""
    d = digits_only(phone)
    return 3 <= len(d) <= 4 and d.isdigit()


def lab_pjsip_endpoint(phone: str) -> Optional[str]:
    d = digits_only(phone)
    if is_lab_extension(phone):
        return f"PJSIP/{d}"
    if (phone or "").upper().startswith("PJSIP/"):
        return phone.strip()
    return None


def trunk_pjsip_endpoint(e164: str, trunk_name: str) -> str:
    """ARI dial string for SIP trunk (digits only in URI — no '+')."""
    num = digits_only(e164)
    trunk = (trunk_name or "").strip()
    if not num or not trunk:
        raise ValueError(f"Invalid trunk dial: e164={e164!r} trunk={trunk_name!r}")
    return f"PJSIP/{num}@{trunk}"
