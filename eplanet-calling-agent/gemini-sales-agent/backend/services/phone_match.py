"""Normalize and match phone numbers across SIP caller IDs, leads, and lab extensions."""
from __future__ import annotations

from typing import Optional

from backend.services.phone_utils import digits_only, lab_pjsip_endpoint, normalize_e164


def caller_keys(caller_id: Optional[str]) -> set[str]:
    keys: set[str] = set()
    if not caller_id:
        return keys
    raw = caller_id.strip()
    if raw:
        keys.add(raw.lower())
    d = digits_only(raw)
    if d:
        keys.add(d)
    e164 = normalize_e164(raw)
    if e164:
        keys.add(e164)
        keys.add(digits_only(e164))
    lab = lab_pjsip_endpoint(raw)
    if lab:
        keys.add(lab.lower())
        ext = digits_only(lab)
        if ext:
            keys.add(ext)
    return keys


def keys_overlap(a: set[str], b: set[str]) -> bool:
    return bool(a and b and (a & b))


def session_meta_matches_caller(meta: dict, keys: set[str]) -> bool:
    if not keys:
        return False
    for field in ("contact_number", "lead_phone", "dialed_endpoint", "caller_id"):
        val = meta.get(field)
        if not val:
            continue
        s = str(val).strip().lower()
        if s in keys or digits_only(s) in keys:
            return True
        lab = lab_pjsip_endpoint(s)
        if lab and lab.lower() in keys:
            return True
    captured = meta.get("captured_contact") or {}
    if isinstance(captured, dict):
        phone = captured.get("phone")
        if phone and keys_overlap(caller_keys(phone), keys):
            return True
    return False
