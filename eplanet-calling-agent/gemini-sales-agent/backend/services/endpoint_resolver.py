"""Resolve CRM phone / lead → Asterisk ARI endpoint (lab or trunk)."""
from __future__ import annotations

from typing import Optional

from backend.config import get_settings
from backend.db.models import Lead
from backend.services.phone_utils import (
    lab_pjsip_endpoint,
    normalize_e164,
    trunk_pjsip_endpoint,
)

settings = get_settings()


def _resolve_explicit_endpoint(ep: str, mode: str) -> tuple[str, str]:
    """Turn UI/campaign input into a valid ARI endpoint string."""
    raw = ep.strip()
    if raw.upper().startswith("PJSIP/"):
        return raw, "explicit"

    lab = lab_pjsip_endpoint(raw)
    if lab and mode == "lab":
        return lab, "explicit_lab"

    e164 = normalize_e164(raw, settings.outbound_default_country_code)
    if mode == "trunk" and e164:
        trunk = settings.outbound_trunk_name.strip()
        if not trunk:
            raise ValueError("OUTBOUND_TRUNK_NAME not configured for trunk mode")
        return trunk_pjsip_endpoint(e164, trunk), "explicit_trunk"

    if lab:
        return lab, "explicit_lab"

    if e164 and mode == "trunk":
        trunk = settings.outbound_trunk_name.strip()
        if not trunk:
            raise ValueError("OUTBOUND_TRUNK_NAME not configured for trunk mode")
        return trunk_pjsip_endpoint(e164, trunk), "explicit_trunk"

    return raw, "explicit"


def resolve_endpoint(
    *,
    lead: Optional[Lead] = None,
    phone: Optional[str] = None,
    explicit_endpoint: Optional[str] = None,
) -> tuple[str, dict]:
    """
    Return (ari_endpoint, meta).
    lab mode: PJSIP/1001 or lead extension
    trunk mode: PJSIP/E164@trunk_name
    """
    mode = (settings.outbound_mode or "lab").strip().lower()
    meta: dict = {"mode": mode}

    if explicit_endpoint and explicit_endpoint.strip():
        ep, source = _resolve_explicit_endpoint(explicit_endpoint, mode)
        meta["source"] = source
        if source.startswith("explicit_trunk"):
            meta["e164"] = normalize_e164(explicit_endpoint, settings.outbound_default_country_code)
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
            return trunk_pjsip_endpoint(e164, trunk), meta

        if lab:
            meta["source"] = "lead_lab_extension"
            return lab, meta

    if mode == "lab":
        fallback = settings.outbound_lab_endpoint.strip()
        if fallback:
            meta["source"] = "lab_default"
            return fallback, meta

    raise ValueError("No dial endpoint — set phone, endpoint, or OUTBOUND_LAB_ENDPOINT")


def resolve_caller_id(
    override: Optional[str] = None,
    *,
    agent_did: Optional[str] = None,
) -> str:
    mode = (settings.outbound_mode or "lab").strip().lower()
    if override and override.strip():
        return override.strip()
    if agent_did and agent_did.strip():
        did = agent_did.strip()
        if mode == "trunk":
            return did if did.startswith("+") else f"+{did.lstrip('+')}"
        return did
    if mode == "trunk" and settings.outbound_trunk_caller_id.strip():
        return settings.outbound_trunk_caller_id.strip()
    return settings.outbound_default_caller_id or "1000"
