"""Background post-call processing: summary, structured outputs, notes, leads."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.db.database import AsyncSessionLocal
from backend.db.models import (
    AgentType,
    Lead,
    LeadStatus,
    Note,
    Output,
    OutputType,
    Session as DBSession,
)
from backend.services import summarizer
from backend.services.session_metrics import merge_session_meta
from backend.services.session_timeline import merge_message_turns

logger = logging.getLogger(__name__)


def _norm_str(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _merge_unique(existing, incoming) -> list[str]:
    out: list[str] = []
    for item in (existing or []):
        s = _norm_str(item)
        if s and s not in out:
            out.append(s)
    if isinstance(incoming, str):
        incoming = [incoming]
    for item in (incoming or []):
        s = _norm_str(item)
        if s and s not in out:
            out.append(s)
    return out


def _extract_lead_profile(lead_data: dict, existing: dict | None = None) -> dict:
    profile = dict(existing or {})
    scalar_fields = (
        "industry",
        "service_required",
        "budget",
        "timeline",
        "preferred_meeting_time",
        "requirement",
        "recommended_service_package",
        "decision_maker_status",
        "lead_temperature",
        "recommended_next_step",
    )
    for field in scalar_fields:
        if field in lead_data and lead_data.get(field) is not None:
            s = _norm_str(lead_data.get(field))
            if s:
                profile[field] = s
    profile["key_features"] = _merge_unique(profile.get("key_features"), lead_data.get("key_features"))
    profile["objections_concerns"] = _merge_unique(profile.get("objections_concerns"), lead_data.get("objections_concerns"))
    return profile


def _output_enum(name: str) -> OutputType:
    try:
        return OutputType(name)
    except ValueError:
        return OutputType.summary


async def _upsert_output(
    db,
    session_id: int,
    output_type: str,
    content: dict,
) -> bool:
    if not content or content.get("error"):
        return False
    otype = _output_enum(output_type)
    existing = await db.execute(
        select(Output).where(
            Output.session_id == session_id,
            Output.output_type == otype,
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        row.content = content
    else:
        db.add(Output(session_id=session_id, output_type=otype, content=content))
    return True


async def _save_session_note(db, session_id: int, content: str) -> None:
    if not content.strip():
        return
    existing = await db.execute(
        select(Note).where(
            Note.entity_type == "session",
            Note.entity_id == session_id,
            Note.content == content,
        )
    )
    if existing.scalar_one_or_none():
        return
    db.add(Note(entity_type="session", entity_id=session_id, content=content))


async def _maybe_create_lead(db, session_id: int, lead_data: dict) -> int | None:
    if not lead_data or lead_data.get("error"):
        return None
    existing = await db.execute(
        select(Lead).where(Lead.source_session_id == session_id)
    )
    existing_lead = existing.scalar_one_or_none()

    interest = lead_data.get("interest_level")
    try:
        interest_num = int(interest) if interest is not None else 0
    except (TypeError, ValueError):
        interest_num = 0

    key_needs = lead_data.get("key_needs")
    notes_parts = []
    if lead_data.get("notes"):
        notes_parts.append(str(lead_data["notes"]))
    if isinstance(key_needs, list) and key_needs:
        notes_parts.append("Needs: " + "; ".join(str(x) for x in key_needs))

    lead_profile = _extract_lead_profile(lead_data, existing_lead.lead_profile if existing_lead else None)

    if existing_lead:
        if lead_data.get("name"):
            existing_lead.name = lead_data.get("name") or existing_lead.name
        if lead_data.get("email"):
            existing_lead.email = lead_data.get("email")
        if lead_data.get("phone"):
            existing_lead.phone = lead_data.get("phone")
        if lead_data.get("company"):
            existing_lead.company = lead_data.get("company")
        if notes_parts:
            merged_notes = _merge_unique(
                (existing_lead.notes or "").split("\n") if existing_lead.notes else [],
                notes_parts,
            )
            existing_lead.notes = "\n".join(merged_notes) if merged_notes else existing_lead.notes
        existing_lead.lead_profile = lead_profile
        if interest_num >= 7:
            existing_lead.status = LeadStatus.qualified
        existing_lead.tags = _merge_unique(existing_lead.tags or [], ["auto-capture"])
        await db.flush()
        return existing_lead.id

    lead = Lead(
        name=lead_data.get("name") or "Unknown",
        email=lead_data.get("email"),
        phone=lead_data.get("phone"),
        company=lead_data.get("company"),
        notes="\n".join(notes_parts) or None,
        lead_profile=lead_profile,
        source_session_id=session_id,
        status=LeadStatus.qualified if interest_num >= 7 else LeadStatus.new,
        tags=["auto-capture"],
    )
    db.add(lead)
    await db.flush()
    return lead.id


async def process_call_end(session_id: int) -> None:
    """Generate summary, outputs, session note, and optional lead after call ends."""
    post_meta: dict = {"status": "running", "outputs_created": [], "errors": []}

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DBSession)
            .options(selectinload(DBSession.messages), selectinload(DBSession.agent))
            .where(DBSession.id == session_id)
        )
        db_session = result.scalar_one_or_none()
        if db_session is None:
            return

        turns = merge_message_turns(db_session.messages)
        messages = [{"role": t["role"], "text": t["text"]} for t in turns]
        if not messages:
            logger.info("Session %d has no messages; skipping post-call processing", session_id)
            await db.refresh(db_session)
            db_session.meta = merge_session_meta(
                db_session.meta,
                {"post_call": {"status": "skipped", "reason": "no_messages"}},
            )
            await db.commit()
            return

        agent = db_session.agent
        agent_type = agent.type if agent else None
        agent_name = agent.name if agent else None

        if not db_session.summary:
            result_summary = await summarizer.generate_summary(
                messages, agent_type=agent_type, agent_name=agent_name
            )
            summary_text = result_summary.get("summary") or ""
            if summary_text:
                db_session.summary = summary_text
                await _save_session_note(db, session_id, summary_text)
                logger.info("Auto-summary generated for session %d", session_id)
            elif result_summary.get("error"):
                post_meta["errors"].append(result_summary["error"])

        direction = (db_session.meta or {}).get("direction")
        output_types = summarizer.output_types_for_agent(agent_type, direction=direction)
        for i, otype in enumerate(output_types):
            if i > 0:
                await asyncio.sleep(13)
            content = await summarizer.generate_output(
                otype,
                messages,
                context={"agent_name": agent_name},
            )
            if await _upsert_output(db, session_id, otype, content):
                post_meta["outputs_created"].append(otype)
                logger.info("Output %s saved for session %d", otype, session_id)
            elif content.get("error"):
                post_meta["errors"].append(f"{otype}: {content['error']}")

            if otype == "lead_capture":
                lead_id = await _maybe_create_lead(db, session_id, content)
                if lead_id:
                    post_meta["lead_id"] = lead_id
                    db_session.meta = merge_session_meta(
                        db_session.meta,
                        {
                            "lead_id": lead_id,
                            "captured_contact": {
                                "name": content.get("name"),
                                "email": content.get("email"),
                                "phone": content.get("phone"),
                                "company": content.get("company"),
                            },
                            "lead_capture": {
                                "name": content.get("name"),
                                "email": content.get("email"),
                                "phone": content.get("phone"),
                                "company": content.get("company"),
                                "lead_profile": _extract_lead_profile(content),
                            },
                        },
                    )

        post_meta["status"] = "completed" if not post_meta["errors"] else "partial"
        # Reload meta so we do not overwrite token_usage / rag_metrics written at call end.
        await db.refresh(db_session)
        db_session.meta = merge_session_meta(db_session.meta, {"post_call": post_meta})
        await db.commit()
