"""Outbound dial policy: DNC list and call windows."""
from __future__ import annotations

from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db.models import DoNotCall
from backend.services.phone_utils import digits_only, normalize_e164

settings = get_settings()


async def is_on_dnc_list(db: AsyncSession, phone: str) -> bool:
    e164 = normalize_e164(phone, settings.outbound_default_country_code)
    d = digits_only(phone)
    if not e164 and not d:
        return False
    q = select(DoNotCall)
    result = await db.execute(q)
    for row in result.scalars().all():
        if e164 and row.phone_e164 == e164:
            return True
        if d and digits_only(row.phone_e164) == d:
            return True
    return False


def within_call_window(now: Optional[datetime] = None) -> tuple[bool, str]:
    """Return (allowed, reason)."""
    if not settings.outbound_call_window_enabled:
        return True, "window_disabled"

    tz_name = settings.outbound_call_timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    start = time(settings.outbound_call_hour_start, 0)
    end = time(settings.outbound_call_hour_end, 0)
    t = now.time()

    if start <= end:
        allowed = start <= t < end
    else:
        # overnight window e.g. 22:00–06:00
        allowed = t >= start or t < end

    if allowed:
        return True, "ok"
    return False, f"outside_call_window ({start.isoformat()}–{end.isoformat()} {tz_name})"


async def assert_may_dial(
    db: AsyncSession,
    *,
    phone: Optional[str] = None,
) -> None:
    allowed, reason = within_call_window()
    if not allowed:
        raise PermissionError(reason)
    if phone and await is_on_dnc_list(db, phone):
        raise PermissionError("number_on_dnc_list")
