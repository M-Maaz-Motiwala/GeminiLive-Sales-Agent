"""Internal HTTP API for the SIP bridge (not for public clients)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db.database import get_db
from backend.db.models import (
    Agent,
    Campaign,
    CampaignLead,
    ChannelType,
    Lead,
    Message,
    Session as DBSession,
    SessionStatus,
)
from backend.services.session_contact import build_call_contact_meta
from backend.services import tool_executor
from backend.services.live_config import (
    agent_to_live_config,
    format_lead_context,
    preload_agent_context,
)
from backend.services.post_call import process_call_end
from backend.services.session_metrics import finalize_session_metrics
from backend.services.token_meter import estimate_text_tokens

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/internal", tags=["internal-bridge"])


def _verify_bridge_token(x_bridge_token: str = Header(..., alias="X-Bridge-Token")) -> None:
    expected = settings.bridge_internal_token
    if not expected or x_bridge_token != expected:
        raise HTTPException(status_code=403, detail="Invalid bridge token")


class CallStartIn(BaseModel):
    channel_id: str
    caller_id: Optional[str] = None
    agent_slug: Optional[str] = None
    dialed_extension: Optional[str] = None
    direction: Literal["inbound", "outbound"] = "inbound"
    lead_id: Optional[int] = None
    dialed_endpoint: Optional[str] = None
    campaign_lead_id: Optional[int] = None


class TranscriptIn(BaseModel):
    session_id: int
    role: Literal["user", "model"]
    text: str


class ToolCallIn(BaseModel):
    session_id: int
    agent_id: Optional[int] = None
    call_id: str
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)


class CallEndIn(BaseModel):
    session_id: int
    channel_id: Optional[str] = None
    duration_sec: Optional[float] = None
    stats: dict[str, Any] = Field(default_factory=dict)
    token_usage: dict[str, Any] = Field(default_factory=dict)


async def _resolve_agent(db: AsyncSession, body: CallStartIn) -> Agent:
    """Lookup agent by Stasis slug, dialed extension, or fallback to first active."""
    if body.agent_slug:
        result = await db.execute(
            select(Agent).where(
                Agent.slug == body.agent_slug,
                Agent.is_active.is_(True),
            )
        )
        agent = result.scalar_one_or_none()
        if agent:
            return agent
        logger.warning("No active agent for slug=%s; falling back", body.agent_slug)

    if body.dialed_extension and body.dialed_extension not in ("700", "s"):
        result = await db.execute(
            select(Agent).where(
                Agent.inbound_extension == body.dialed_extension,
                Agent.is_active.is_(True),
            )
        )
        agent = result.scalar_one_or_none()
        if agent:
            return agent
        logger.warning(
            "No active agent for extension=%s; falling back",
            body.dialed_extension,
        )

    result = await db.execute(
        select(Agent).where(Agent.is_active.is_(True)).order_by(Agent.id).limit(1)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=503, detail="No active agent configured")
    return agent


@router.post("/calls/start")
async def call_start(
    body: CallStartIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_bridge_token),
) -> dict[str, Any]:
    agent = await _resolve_agent(db, body)
    direction = body.direction or "inbound"
    meta: dict[str, Any] = {"channel_id": body.channel_id, "direction": direction}
    if body.dialed_extension:
        meta["dialed_extension"] = body.dialed_extension
    if body.agent_slug:
        meta["agent_slug"] = body.agent_slug
    if body.dialed_endpoint:
        meta["dialed_endpoint"] = body.dialed_endpoint
    if body.lead_id is not None:
        meta["lead_id"] = body.lead_id
    if body.campaign_lead_id is not None:
        meta["campaign_lead_id"] = body.campaign_lead_id

    contact_meta = await build_call_contact_meta(
        db,
        direction=direction,
        caller_id=body.caller_id,
        dialed_endpoint=body.dialed_endpoint,
        lead_id=body.lead_id,
        dialed_extension=body.dialed_extension,
    )
    meta.update(contact_meta)

    if body.campaign_lead_id is not None:
        cl = await db.get(CampaignLead, body.campaign_lead_id)
        if cl:
            camp = await db.get(Campaign, cl.campaign_id)
            if camp:
                meta["campaign_id"] = camp.id
                meta["campaign_name"] = camp.name

    lead_context = ""
    if body.lead_id is not None:
        lead_row = await db.get(Lead, body.lead_id)
        if lead_row:
            lead_context = format_lead_context(
                {
                    "name": lead_row.name,
                    "email": lead_row.email,
                    "phone": lead_row.phone,
                    "company": lead_row.company,
                    "status": lead_row.status.value if lead_row.status else None,
                    "notes": lead_row.notes,
                    "tags": lead_row.tags or [],
                }
            )

    channel_type = ChannelType.outbound if direction == "outbound" else ChannelType.sip

    db_session = DBSession(
        agent_id=agent.id,
        caller_id=body.caller_id,
        channel_type=channel_type,
        status=SessionStatus.active,
        meta=meta,
    )
    db.add(db_session)
    await db.flush()

    kb_block, kb_meta = await preload_agent_context(agent)
    meta["preloaded_kb"] = kb_meta

    config = agent_to_live_config(
        agent,
        kb_context=kb_block,
        lead_context=lead_context,
        direction=direction,
    )
    config["session_id"] = db_session.id

    context_tokens = estimate_text_tokens(config.get("system_instruction", ""))
    for tool_entry in config.get("tools") or []:
        for fd in tool_entry.get("function_declarations") or []:
            context_tokens += estimate_text_tokens(
                (fd.get("name") or "") + (fd.get("description") or "")
            )
    meta["token_usage_baseline"] = {
        "text_input_context_tokens": context_tokens,
        "note": "System prompt + tool declarations at call start (included in session total)",
    }
    db_session.meta = meta
    await db.flush()

    if body.campaign_lead_id is not None:
        cl = await db.get(CampaignLead, body.campaign_lead_id)
        if cl:
            cl.session_id = db_session.id

    logger.info(
        "Call started session=%d agent=%s direction=%s ext=%s channel=%s caller=%s lead=%s campaign_lead=%s contact=%s",
        db_session.id,
        agent.slug,
        direction,
        body.dialed_extension,
        body.channel_id,
        body.caller_id,
        body.lead_id,
        body.campaign_lead_id,
        meta.get("contact_number"),
    )
    return config


@router.post("/calls/transcript")
async def call_transcript(
    body: TranscriptIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_bridge_token),
) -> dict[str, str]:
    if not body.text.strip():
        return {"status": "skipped"}

    msg = Message(session_id=body.session_id, role=body.role, text=body.text.strip())
    db.add(msg)
    return {"status": "ok"}


@router.post("/calls/tool")
async def call_tool(
    body: ToolCallIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_bridge_token),
) -> dict[str, Any]:
    fr = await tool_executor.dispatch(
        tool_name=body.tool_name,
        call_id=body.call_id,
        params=body.params,
        db=db,
        session_id=body.session_id,
        agent_id=body.agent_id,
    )
    return {
        "id": fr.id,
        "name": fr.name,
        "response": fr.response,
    }


@router.post("/calls/end")
async def call_end(
    body: CallEndIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_bridge_token),
) -> dict[str, str]:
    result = await db.execute(select(DBSession).where(DBSession.id == body.session_id))
    db_session = result.scalar_one_or_none()
    if db_session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    db_session.status = SessionStatus.ended
    db_session.ended_at = datetime.now(timezone.utc)
    meta = dict(db_session.meta or {})
    if body.duration_sec is not None:
        meta["duration_sec"] = body.duration_sec
    if body.stats:
        meta["bridge_stats"] = body.stats
    if body.channel_id:
        meta["channel_id"] = body.channel_id
    db_session.meta = meta

    usage = dict(body.token_usage) if body.token_usage else None
    await finalize_session_metrics(db, body.session_id, token_usage=usage)
    # Commit metrics before post-call runs — otherwise process_call_end loads stale
    # meta and overwrites token_usage / rag_metrics when it finishes (~30s later).
    await db.commit()

    logger.info(
        "SIP call ended session=%d duration=%.1fs tokens=%s",
        body.session_id,
        body.duration_sec or 0,
        usage.get("estimated_total_tokens") if usage else "n/a",
    )

    session_id = body.session_id
    asyncio.create_task(process_call_end(session_id))

    return {"status": "ok"}
