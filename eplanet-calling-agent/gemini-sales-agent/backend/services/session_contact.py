"""Compute contact_number for session meta at call start."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db.models import Lead
from backend.services.phone_utils import digits_only, normalize_e164
from backend.services.session_display import format_caller_display, format_endpoint_display

settings = get_settings()


def resolve_prospect_phone(
    *,
    dialed_endpoint: Optional[str],
    lead_phone: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Return (display_phone, e164) for outbound dial target."""
    if lead_phone and str(lead_phone).strip():
        e164 = normalize_e164(str(lead_phone), settings.outbound_default_country_code)
        display = e164 or str(lead_phone).strip()
        return display, e164

    if not dialed_endpoint:
        return None, None

    display = format_endpoint_display(dialed_endpoint)
    if not display:
        return None, None

    e164 = normalize_e164(display, settings.outbound_default_country_code)
    if not e164:
        digits = digits_only(display)
        if digits:
            e164 = normalize_e164(f"+{digits}", settings.outbound_default_country_code)
    return display, e164


async def build_call_contact_meta(
    db: AsyncSession,
    *,
    direction: str,
    caller_id: Optional[str],
    dialed_endpoint: Optional[str],
    lead_id: Optional[int],
    dialed_extension: Optional[str],
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if direction == "outbound":
        lead_phone: Optional[str] = None
        if lead_id is not None:
            lead = await db.get(Lead, lead_id)
            if lead and lead.phone:
                lead_phone = lead.phone
                extra["lead_phone"] = lead.phone
                if lead.phone_e164:
                    extra["prospect_phone_e164"] = lead.phone_e164

        if dialed_endpoint:
            extra["dialed_endpoint"] = dialed_endpoint

        display, e164 = resolve_prospect_phone(
            dialed_endpoint=dialed_endpoint,
            lead_phone=lead_phone,
        )
        if e164:
            extra["prospect_phone_e164"] = e164
            extra["prospect_phone"] = e164
            extra["contact_number"] = e164
        elif display:
            extra["prospect_phone"] = display
            extra["contact_number"] = display
    else:
        if caller_id:
            extra["contact_number"] = format_caller_display(caller_id)
        elif dialed_extension:
            extra["contact_number"] = str(dialed_extension)
    return extra
