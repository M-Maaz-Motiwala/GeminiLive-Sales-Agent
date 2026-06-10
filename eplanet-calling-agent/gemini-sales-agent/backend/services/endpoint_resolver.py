"""Resolve CRM phone / lead → Asterisk ARI endpoint (lab or trunk)."""
from __future__ import annotations

from typing import Optional

from backend.config import get_settings
from backend.db.models import Lead
from backend.services.phone_utils import lab_pjsip_endpoint, normalize_e164

settings = get_settings()


def resolve_endpoint(
    *,
    lead: Optional[Lead] = None,
    phone: Optional[str] = None,
    explicit_endpoint: Optional[str] = None,
) -> tuple[str, dict]:
    """
    Return (ari_endpoint, meta).
    lab mode: PJSIP/1001 or lead extension
    trunk mode: PJSIP/+E164@trunk_name (stub until trunk configured)
    """
    mode = (settings.outbound_mode or "lab").strip().lower()
    meta: dict = {"mode": mode}

    if explicit_endpoint and explicit_endpoint.strip():
        ep = explicit_endpoint.strip()
        meta["source"] = "explicit"
        return ep, meta

    raw_phone = (phone or (lead.phone if lead else None) or "").strip()
    if raw_phone:
        lab = lab_pjsip_endpoint(raw_phone)
        if lab and mode == "lab":
            meta["source"] = "lead_lab_extension"
            return lab, meta

        e164 = normalize_e164(raw_phone, settings.outbound_default_country_code)
        meta["e164"] = e164
        if mode == "trunk":
            if not e164:
                raise ValueError(f"Invalid phone for trunk dial: {raw_phone!r}")
            trunk = settings.outbound_trunk_name.strip()
            if not trunk:
                raise ValueError("OUTBOUND_TRUNK_NAME not configured for trunk mode")
            meta["source"] = "trunk"
            return f"PJSIP/{e164}@{trunk}", meta

        # lab mode: try lab extension from lead phone
        if lab:
            meta["source"] = "lead_lab_extension"
            return lab, meta

    if mode == "lab":
        fallback = settings.outbound_lab_endpoint.strip()
        if fallback:
            meta["source"] = "lab_default"
            return fallback, meta

    raise ValueError("No dial endpoint — set phone, endpoint, or OUTBOUND_LAB_ENDPOINT")


def resolve_caller_id(override: Optional[str] = None) -> str:
    mode = (settings.outbound_mode or "lab").strip().lower()
    if override and override.strip():
        return override.strip()
    if mode == "trunk" and settings.outbound_trunk_caller_id.strip():
        return settings.outbound_trunk_caller_id.strip()
    return settings.outbound_default_caller_id or "1000"
