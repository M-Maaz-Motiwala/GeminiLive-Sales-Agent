"""Load prior outbound call context for inbound return callers."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.models import Lead, Output, OutputType, Session as DBSession, SessionStatus, ToolCall
from backend.services.phone_match import caller_keys, keys_overlap, session_meta_matches_caller

logger = logging.getLogger(__name__)

_CALLBACK_LOOKBACK_DAYS = 14


async def find_prior_outbound_session(
    db: AsyncSession,
    caller_id: Optional[str],
    *,
    exclude_session_id: Optional[int] = None,
) -> Optional[DBSession]:
    """Most recent ended outbound session for this caller (phone / lead match)."""
    keys = caller_keys(caller_id)
    if not keys:
        return None

    since = datetime.now(timezone.utc) - timedelta(days=_CALLBACK_LOOKBACK_DAYS)
    result = await db.execute(
        select(DBSession)
        .where(
            DBSession.started_at >= since,
            DBSession.status == SessionStatus.ended,
        )
        .order_by(DBSession.started_at.desc())
        .limit(300)
    )
    for sess in result.scalars():
        if exclude_session_id and sess.id == exclude_session_id:
            continue
        meta = sess.meta or {}
        if meta.get("direction") != "outbound":
            continue
        if session_meta_matches_caller(meta, keys):
            return sess

    lead_q = await db.execute(
        select(Lead)
        .where(Lead.phone.isnot(None))
        .order_by(Lead.id.desc())
        .limit(500)
    )
    for lead in lead_q.scalars():
        if not keys_overlap(caller_keys(lead.phone), keys):
            continue
        if not lead.source_session_id:
            continue
        sess = await db.get(DBSession, lead.source_session_id)
        if not sess or sess.status != SessionStatus.ended:
            continue
        meta = sess.meta or {}
        if meta.get("direction") != "outbound":
            continue
        if sess.started_at and sess.started_at < since:
            continue
        return sess

    return None


async def _lead_for_session(db: AsyncSession, sess: DBSession) -> Optional[Lead]:
    meta = sess.meta or {}
    lead_id = meta.get("lead_id")
    if lead_id:
        lead = await db.get(Lead, lead_id)
        if lead:
            return lead

    result = await db.execute(
        select(Lead)
        .where(Lead.source_session_id == sess.id)
        .order_by(Lead.id.desc())
        .limit(1)
    )
    lead = result.scalar_one_or_none()
    if lead:
        return lead

    tc_result = await db.execute(
        select(ToolCall)
        .where(ToolCall.session_id == sess.id, ToolCall.tool_name == "create_lead")
        .order_by(ToolCall.called_at.desc())
        .limit(1)
    )
    tc = tc_result.scalar_one_or_none()
    if not tc or not isinstance(tc.result, dict):
        return None
    lid = tc.result.get("lead_id")
    if lid:
        return await db.get(Lead, lid)
    return None


def _lead_dict(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "name": lead.name,
        "email": lead.email,
        "phone": lead.phone,
        "company": lead.company,
        "status": lead.status.value if lead.status else None,
        "notes": lead.notes,
        "tags": lead.tags or [],
    }


async def load_inbound_callback_context(
    db: AsyncSession,
    caller_id: Optional[str],
) -> dict[str, Any]:
    """Gather prior outbound session summary, lead, and action items for a return caller."""
    prior = await find_prior_outbound_session(db, caller_id)
    if not prior:
        return {}

    result = await db.execute(
        select(DBSession)
        .options(selectinload(DBSession.outputs))
        .where(DBSession.id == prior.id)
    )
    prior = result.scalar_one_or_none()
    if prior is None:
        return {}

    lead = await _lead_for_session(db, prior)
    meta = prior.meta or {}
    captured = meta.get("captured_contact") if isinstance(meta.get("captured_contact"), dict) else {}

    action_items: Optional[dict] = None
    call_disposition: Optional[dict] = None
    lead_capture: Optional[dict] = None
    for output in prior.outputs or []:
        otype = output.output_type.value if hasattr(output.output_type, "value") else str(output.output_type)
        if otype == OutputType.action_items.value:
            action_items = output.content
        elif otype == OutputType.call_disposition.value:
            call_disposition = output.content
        elif otype == OutputType.lead_capture.value:
            lead_capture = output.content

    ctx: dict[str, Any] = {
        "prior_session_id": prior.id,
        "prior_started_at": prior.started_at.isoformat() if prior.started_at else None,
        "summary": prior.summary,
        "lead_id": lead.id if lead else meta.get("lead_id"),
        "lead": _lead_dict(lead) if lead else None,
        "captured_contact": captured or None,
        "action_items": action_items,
        "call_disposition": call_disposition,
        "lead_capture": lead_capture,
        "is_return_call": True,
    }

    if not ctx["lead"] and captured:
        ctx["lead"] = {
            "name": captured.get("name"),
            "email": captured.get("email"),
            "phone": captured.get("phone"),
            "company": captured.get("company"),
        }

    logger.info(
        "Inbound callback context session=%d lead=%s caller=%s",
        prior.id,
        ctx.get("lead_id"),
        caller_id,
    )
    return ctx


def format_prior_call_context(ctx: dict[str, Any]) -> str:
    """Build system-prompt block for an inbound return call."""
    if not ctx.get("prior_session_id"):
        return ""

    lines = [
        "## Return call — prior outbound conversation",
        "The caller is likely returning a call your team placed recently.",
        "Briefly verify they are calling back, then continue naturally using the context below.",
        "Do not read field labels or JSON aloud.",
        "",
    ]

    if ctx.get("summary"):
        lines.append("### Prior call summary")
        lines.append(str(ctx["summary"]).strip())
        lines.append("")

    lead = ctx.get("lead") or {}
    if any(lead.get(k) for k in ("name", "email", "phone", "company")):
        lines.append("### Contact details captured on the prior call")
        for key, label in (
            ("name", "Name"),
            ("email", "Email"),
            ("phone", "Phone"),
            ("company", "Company"),
        ):
            val = lead.get(key)
            if val:
                lines.append(f"- {label}: {val}")
        notes = lead.get("notes")
        if notes:
            lines.append(f"- Notes: {notes}")
        lines.append("")

    disposition = ctx.get("call_disposition")
    if isinstance(disposition, dict) and disposition:
        lines.append("### Outbound call outcome")
        for key in ("disposition", "interest_level", "callback_requested", "lead_captured", "notes"):
            val = disposition.get(key)
            if val is not None and val != "":
                lines.append(f"- {key.replace('_', ' ').title()}: {val}")
        objections = disposition.get("objections") or []
        if objections:
            lines.append(f"- Objections: {', '.join(str(o) for o in objections)}")
        lines.append("")

    items = None
    action = ctx.get("action_items")
    if isinstance(action, dict):
        items = action.get("items")
    if items:
        lines.append("### Follow-ups and action items from the prior call")
        for item in items:
            if not isinstance(item, dict):
                continue
            task = item.get("task") or item.get("action") or str(item)
            owner = item.get("owner")
            priority = item.get("priority")
            due = item.get("due_date")
            extra = ", ".join(x for x in (owner, priority, due) if x)
            lines.append(f"- {task}" + (f" ({extra})" if extra else ""))
        lines.append("")

    lc = ctx.get("lead_capture")
    if isinstance(lc, dict) and lc and not lead:
        lines.append("### Lead capture (from prior call analysis)")
        for key in ("name", "email", "phone", "company", "notes"):
            val = lc.get(key)
            if val:
                lines.append(f"- {key.title()}: {val}")
        needs = lc.get("key_needs") or []
        if needs:
            lines.append(f"- Key needs: {', '.join(str(n) for n in needs)}")
        lines.append("")

    lines.append(
        "Continue the relationship from the prior call — reference what was discussed, "
        "confirm any open action items, and help them with their next step."
    )
    return "\n".join(lines)
