"""Close SIP/outbound sessions that ended on the bridge but stayed active in the DB."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import ChannelType, Session as DBSession, SessionStatus
from backend.services.bridge_client import bridge_status
from backend.services.post_call import process_call_end

logger = logging.getLogger(__name__)

# Ignore brand-new sessions while the bridge is still setting up the call.
_STALE_GRACE_SEC = 15


async def reconcile_stale_bridge_sessions(db: AsyncSession) -> int:
    """Mark telephony sessions ended when they are no longer active on the bridge."""
    try:
        status = await bridge_status()
    except Exception as exc:
        logger.debug("Session reconcile skipped (bridge unreachable): %s", exc)
        return 0

    if status.get("error"):
        return 0

    calls = status.get("calls")
    if calls is None:
        return 0

    live_ids: set[int] = set()
    for call in calls:
        sid = call.get("platform_session_id")
        if sid is None:
            continue
        stall = float(call.get("rtp_stall_sec") or 0)
        direction = call.get("direction") or "inbound"
        # Outbound channels can linger in Asterisk after hangup; bridge marks stall.
        if direction == "outbound" and stall >= 15.0:
            continue
        live_ids.add(int(sid))

    active_count = int(status.get("active_calls") or 0)
    if active_count > 0 and not live_ids:
        # e.g. /health fallback — don't close sessions we can't correlate.
        logger.debug("Session reconcile skipped (active bridge calls without session ids)")
        return 0

    result = await db.execute(
        select(DBSession).where(
            DBSession.status == SessionStatus.active,
            DBSession.channel_type.in_((ChannelType.sip, ChannelType.outbound)),
        )
    )
    now = datetime.now(timezone.utc)
    closed = 0
    reconciled_ids: list[int] = []
    for row in result.scalars().all():
        if row.id in live_ids:
            continue
        started = row.started_at
        if started is not None:
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            age = (now - started).total_seconds()
            if age < _STALE_GRACE_SEC:
                continue
        meta = dict(row.meta or {})
        meta["reconciled"] = True
        meta["reconcile_reason"] = "not_active_on_bridge"
        row.status = SessionStatus.ended
        row.ended_at = now
        row.meta = meta
        closed += 1
        reconciled_ids.append(row.id)
        logger.info("Reconciled stale session %d (channel_type=%s)", row.id, row.channel_type)

    if closed:
        await db.commit()
        for session_id in reconciled_ids:
            asyncio.create_task(process_call_end(session_id))
    return closed
