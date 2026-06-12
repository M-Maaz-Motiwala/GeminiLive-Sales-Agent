"""Compute contact_number for session meta at call start."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Lead
from backend.services.session_display import format_caller_display, format_endpoint_display


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
        if dialed_endpoint:
            extra["dialed_endpoint"] = dialed_endpoint
            extra["contact_number"] = format_endpoint_display(dialed_endpoint)
        if lead_id is not None:
            lead = await db.get(Lead, lead_id)
            if lead and lead.phone:
                extra["lead_phone"] = lead.phone
                extra["contact_number"] = lead.phone
    else:
        if caller_id:
            extra["contact_number"] = format_caller_display(caller_id)
        elif dialed_extension:
            extra["contact_number"] = str(dialed_extension)
    return extra
