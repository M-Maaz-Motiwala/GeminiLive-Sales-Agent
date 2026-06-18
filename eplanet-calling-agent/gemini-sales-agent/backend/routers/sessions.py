from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Session as DBSession, Message, ToolCall, Output, OutputType, Note, SessionStatus
from backend.services import summarizer
from backend.services.post_call import process_call_end
from backend.services.session_reconcile import reconcile_stale_bridge_sessions
from backend.services.session_display import enrich_session_dict
from backend.services.session_timeline import build_timeline, merge_message_turns

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _session_out(s: DBSession) -> dict:
    return {
        "id": s.id, "agent_id": s.agent_id, "caller_id": s.caller_id,
        "channel_type": s.channel_type, "status": s.status,
        "started_at": s.started_at, "ended_at": s.ended_at, "summary": s.summary,
        "meta": s.meta or {},
    }


@router.get("")
async def list_sessions(
    status: Optional[str] = None,
    agent_id: Optional[int] = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = (
        select(DBSession)
        .options(selectinload(DBSession.agent), selectinload(DBSession.outputs))
        .order_by(DBSession.started_at.desc())
        .limit(limit)
    )
    if status:
        q = q.where(DBSession.status == status)
    if agent_id:
        q = q.where(DBSession.agent_id == agent_id)
    await reconcile_stale_bridge_sessions(db)
    result = await db.execute(q)
    rows = []
    for s in result.scalars().all():
        out = _session_out(s)
        if s.agent:
            out["agent"] = {
                "id": s.agent.id,
                "name": s.agent.name,
                "slug": s.agent.slug,
                "inbound_extension": s.agent.inbound_extension,
            }
        out["output_types"] = [o.output_type.value for o in (s.outputs or [])]
        enrich_session_dict(s, out)
        rows.append(out)
    return rows


@router.get("/{session_id}")
async def get_session(session_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(
        select(DBSession)
        .options(
            selectinload(DBSession.messages),
            selectinload(DBSession.tool_calls),
            selectinload(DBSession.outputs),
            selectinload(DBSession.agent),
        )
        .where(DBSession.id == session_id)
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")

    turns = merge_message_turns(s.messages)
    timeline = build_timeline(turns, s.tool_calls, s.outputs)

    agent_info = None
    if s.agent:
        agent_info = {
            "id": s.agent.id,
            "name": s.agent.name,
            "slug": s.agent.slug,
            "type": s.agent.type.value if s.agent.type else None,
            "inbound_extension": s.agent.inbound_extension,
        }

    return enrich_session_dict(
        s,
        {
            **_session_out(s),
            "agent": agent_info,
            "turns": turns,
            "timeline": timeline,
            "messages": [{"id": m.id, "role": m.role, "text": m.text, "timestamp": m.timestamp} for m in s.messages],
            "tool_calls": [{"id": tc.id, "tool_name": tc.tool_name, "parameters": tc.parameters, "result": tc.result, "called_at": tc.called_at, "duration_ms": tc.duration_ms} for tc in s.tool_calls],
            "outputs": [{"id": o.id, "output_type": o.output_type.value, "content": o.content, "created_at": o.created_at} for o in s.outputs],
        },
    )


@router.post("/{session_id}/summarize")
async def summarize_session(session_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(
        select(DBSession)
        .options(selectinload(DBSession.messages), selectinload(DBSession.agent))
        .where(DBSession.id == session_id)
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")

    messages = [{"role": t["role"], "text": t["text"]} for t in merge_message_turns(s.messages)]
    if not messages:
        raise HTTPException(400, "No transcript to summarize")

    gen = await summarizer.generate_summary(
        messages,
        agent_type=s.agent.type if s.agent else None,
        agent_name=s.agent.name if s.agent else None,
    )
    summary_text = gen.get("summary") or ""
    error = gen.get("error")
    if not summary_text:
        raise HTTPException(502, error or "Summary generation failed")

    s.summary = summary_text
    note = Note(entity_type="session", entity_id=session_id, content=summary_text)
    db.add(note)
    return {"summary": summary_text, "error": None}


@router.post("/{session_id}/outputs")
async def generate_output(
    session_id: int,
    output_type: str = "summary",
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(
        select(DBSession)
        .options(selectinload(DBSession.messages), selectinload(DBSession.agent))
        .where(DBSession.id == session_id)
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")

    messages = [{"role": t["role"], "text": t["text"]} for t in merge_message_turns(s.messages)]
    if not messages:
        raise HTTPException(400, "No transcript for output generation")

    content = await summarizer.generate_output(
        output_type,
        messages,
        context={"agent_name": s.agent.name if s.agent else None},
    )
    if content.get("error"):
        raise HTTPException(502, content["error"])

    try:
        otype = OutputType(output_type)
    except ValueError:
        otype = OutputType.summary

    existing = await db.execute(
        select(Output).where(Output.session_id == session_id, Output.output_type == otype)
    )
    row = existing.scalar_one_or_none()
    if row:
        row.content = content
        output_id = row.id
    else:
        output = Output(session_id=session_id, output_type=otype, content=content)
        db.add(output)
        await db.flush()
        output_id = output.id

    return {"id": output_id, "output_type": output_type, "content": content}


class PostCallIn(BaseModel):
    force: bool = False


@router.post("/{session_id}/post-call")
async def run_post_call(
    session_id: int,
    body: PostCallIn | None = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Manually trigger post-call processing (summary + outputs + note)."""
    result = await db.execute(select(DBSession).where(DBSession.id == session_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")
    if body and body.force:
        s.summary = None
    await db.commit()
    await process_call_end(session_id)
    return {"status": "ok", "message": "Post-call processing started"}
