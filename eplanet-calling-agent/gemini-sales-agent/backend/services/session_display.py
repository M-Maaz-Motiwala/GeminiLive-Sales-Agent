"""Display helpers for session list/detail (contact number, campaign tags)."""
from __future__ import annotations

import re
from typing import Any, Optional

from backend.db.models import ChannelType, Session as DBSession

_CALLER_IN_ANGLE = re.compile(r"<([^>]+)>")


def format_endpoint_display(endpoint: str) -> str:
    ep = (endpoint or "").strip()
    if not ep:
        return ""
    if ep.upper().startswith("PJSIP/"):
        return ep.split("/", 1)[-1]
    return ep


def format_caller_display(caller_id: Optional[str]) -> str:
    raw = (caller_id or "").strip()
    if not raw:
        return ""
    m = _CALLER_IN_ANGLE.search(raw)
    if m:
        raw = m.group(1).strip()
    if raw.upper().startswith("PJSIP/"):
        return raw.split("/", 1)[-1]
    return raw


def resolve_contact_number(session: DBSession) -> Optional[str]:
    """Human-readable number/extension for list UI."""
    meta = session.meta or {}
    if meta.get("contact_number"):
        return str(meta["contact_number"])

    direction = meta.get("direction")
    channel = session.channel_type
    is_outbound = direction == "outbound" or (
        channel == ChannelType.outbound
        if hasattr(channel, "value")
        else str(channel) == "outbound"
    )

    if is_outbound:
        if meta.get("lead_phone"):
            return str(meta["lead_phone"])
        ep = meta.get("dialed_endpoint")
        if ep:
            return format_endpoint_display(str(ep))

    if session.caller_id:
        return format_caller_display(session.caller_id)
    if meta.get("dialed_extension"):
        return str(meta["dialed_extension"])
    return None


def resolve_contact_label(session: DBSession) -> str:
    """Short prefix for UI: 'Called' vs 'From'."""
    meta = session.meta or {}
    direction = meta.get("direction")
    channel = session.channel_type
    is_outbound = direction == "outbound" or (
        channel == ChannelType.outbound
        if hasattr(channel, "value")
        else str(channel) == "outbound"
    )
    return "Called" if is_outbound else "From"


def enrich_session_dict(session: DBSession, out: dict[str, Any]) -> dict[str, Any]:
    meta = session.meta or {}
    contact = resolve_contact_number(session)
    out["contact_number"] = contact
    out["contact_label"] = resolve_contact_label(session)
    out["campaign_id"] = meta.get("campaign_id")
    out["campaign_name"] = meta.get("campaign_name")
    return out
