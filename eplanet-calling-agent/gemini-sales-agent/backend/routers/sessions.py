from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import datetime, timezone

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Session as DBSession, Message, ToolCall, Output, SessionStatus
from backend.services import summarizer
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
    q = select(DBSession).order_by(DBSession.started_at.desc()).limit(limit)
    if status:
        q = q.where(DBSession.status == status)
    if agent_id:
        q = q.where(DBSession.agent_id == agent_id)
    result = await db.execute(q)
    return [_session_out(s) for s in result.scalars().all()]


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
            "inbound_extension": s.agent.inbound_extension,
        }

    return {
        **_session_out(s),
        "agent": agent_info,
        "turns": turns,
        "timeline": timeline,
        "messages": [{"id": m.id, "role": m.role, "text": m.text, "timestamp": m.timestamp} for m in s.messages],
        "tool_calls": [{"id": tc.id, "tool_name": tc.tool_name, "parameters": tc.parameters, "result": tc.result, "called_at": tc.called_at, "duration_ms": tc.duration_ms} for tc in s.tool_calls],
        "outputs": [{"id": o.id, "output_type": o.output_type, "content": o.content, "created_at": o.created_at} for o in s.outputs],
    }


@router.post("/{session_id}/summarize")
async def summarize_session(session_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(DBSession).options(selectinload(DBSession.messages)).where(DBSession.id == session_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")

    messages = [{"role": t["role"], "text": t["text"]} for t in merge_message_turns(s.messages)]
    summary_text = await summarizer.generate_summary(messages)
    s.summary = summary_text
    await db.flush()
    return {"summary": summary_text}


@router.post("/{session_id}/outputs")
async def generate_output(session_id: int, output_type: str = "summary", db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(DBSession).options(selectinload(DBSession.messages)).where(DBSession.id == session_id))
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Session not found")

    messages = [{"role": t["role"], "text": t["text"]} for t in merge_message_turns(s.messages)]
    content = await summarizer.generate_output(output_type, messages)

    from backend.db.models import OutputType
    try:
        otype = OutputType(output_type)
    except ValueError:
        otype = OutputType.summary

    output = Output(session_id=session_id, output_type=otype, content=content)
    db.add(output)
    await db.flush()
    return {"id": output.id, "output_type": output_type, "content": content}
