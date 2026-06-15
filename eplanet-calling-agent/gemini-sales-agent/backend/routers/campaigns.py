"""Outbound campaigns — create, import, run with rolling parallel dials."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import (
    Agent,
    AgentType,
    Campaign,
    CampaignLead,
    CampaignLeadStatus,
    CampaignStatus,
    Lead,
)
from backend.services.campaign_csv import parse_campaign_csv
from backend.services.campaign_leads import add_csv_rows, add_endpoints, add_lead_ids
from backend.services.campaign_runner import (
    campaign_agent_ids,
    campaign_inter_call_delay,
    campaign_progress,
    is_runner_active,
    start_runner,
    stop_runner,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignIn(BaseModel):
    name: str
    agent_ids: list[int] = Field(default_factory=list)
    agent_id: Optional[int] = None  # legacy single-agent
    description: Optional[str] = None
    inter_call_delay_sec: int = Field(30, ge=0, le=600)
    lead_ids: list[int] = Field(default_factory=list)
    endpoints: list[str] = Field(default_factory=list)


class CampaignUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_ids: Optional[list[int]] = None
    agent_id: Optional[int] = None
    inter_call_delay_sec: Optional[int] = Field(None, ge=0, le=600)


class CampaignLeadsIn(BaseModel):
    endpoints: list[str] = Field(default_factory=list)
    lead_ids: list[int] = Field(default_factory=list)


class CampaignStartIn(BaseModel):
    max_parallel: int = Field(2, ge=1, le=10)
    inter_call_delay_sec: Optional[int] = Field(None, ge=0, le=600)
    start_at: Optional[datetime] = Field(
        None,
        description="Schedule start (ISO datetime). Omit or null = start immediately.",
    )


def _lead_row(cl: CampaignLead, lead: Optional[Lead]) -> dict[str, Any]:
    return {
        "id": cl.id,
        "lead_id": cl.lead_id,
        "endpoint": cl.endpoint,
        "status": cl.status.value if hasattr(cl.status, "value") else cl.status,
        "session_id": cl.session_id,
        "last_error": cl.last_error,
        "dialed_at": cl.dialed_at,
        "lead_name": lead.name if lead else None,
        "lead_phone": lead.phone if lead else None,
        "lead_company": lead.company if lead else None,
    }


def _campaign_out(c: Campaign, *, include_progress: bool = True) -> dict[str, Any]:
    data = {
        "id": c.id,
        "name": c.name,
        "agent_id": c.agent_id,
        "agent_ids": campaign_agent_ids(c),
        "inter_call_delay_sec": campaign_inter_call_delay(c),
        "status": c.status.value if hasattr(c.status, "value") else c.status,
        "description": c.description,
        "meta": c.meta or {},
        "lead_count": len(c.campaign_leads or []),
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }
    if include_progress:
        data["progress"] = campaign_progress(c)
    return data


async def _load_campaign(db: AsyncSession, campaign_id: int) -> Campaign:
    result = await db.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(selectinload(Campaign.campaign_leads))
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Campaign not found")
    return c


def _resolve_agent_ids(body: CampaignIn | CampaignUpdateIn) -> list[int]:
    ids = list(getattr(body, "agent_ids", None) or [])
    legacy = getattr(body, "agent_id", None)
    if legacy and legacy not in ids:
        ids.insert(0, legacy)
    return ids


async def _validate_agents(db: AsyncSession, agent_ids: list[int]) -> list[Agent]:
    if not agent_ids:
        raise HTTPException(400, "Select at least one sales agent")
    agents: list[Agent] = []
    for aid in agent_ids:
        agent = await db.get(Agent, aid)
        if not agent or not agent.is_active:
            raise HTTPException(404, f"Agent {aid} not found")
        if agent.type not in (AgentType.sales, AgentType.outbound_sales):
            raise HTTPException(400, f"Agent {agent.name} must be a sales agent")
        agents.append(agent)
    return agents


def _campaign_meta_agents(
    meta: dict[str, Any], agent_ids: list[int], inter_call_delay_sec: int
) -> dict[str, Any]:
    out = dict(meta or {})
    out["agent_ids"] = agent_ids
    out["inter_call_delay_sec"] = inter_call_delay_sec
    return out


@router.get("")
async def list_campaigns(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(Campaign).order_by(Campaign.created_at.desc()))
    campaigns = result.scalars().all()
    out = []
    for c in campaigns:
        await db.refresh(c, ["campaign_leads"])
        out.append(_campaign_out(c))
    return out


@router.post("")
async def create_campaign(
    body: CampaignIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    agent_ids = _resolve_agent_ids(body)
    await _validate_agents(db, agent_ids)

    campaign = Campaign(
        name=body.name.strip(),
        agent_id=agent_ids[0],
        description=(body.description or "").strip() or None,
        status=CampaignStatus.draft,
        meta=_campaign_meta_agents({}, agent_ids, body.inter_call_delay_sec),
    )
    db.add(campaign)
    await db.flush()

    if body.lead_ids:
        await add_lead_ids(db, campaign, body.lead_ids)
    elif body.endpoints:
        await add_endpoints(db, campaign, body.endpoints)

    await db.refresh(campaign, ["campaign_leads"])
    return _campaign_out(campaign)


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    c = await _load_campaign(db, campaign_id)
    lead_ids = [cl.lead_id for cl in c.campaign_leads if cl.lead_id]
    leads_map: dict[int, Lead] = {}
    if lead_ids:
        result = await db.execute(select(Lead).where(Lead.id.in_(lead_ids)))
        leads_map = {l.id: l for l in result.scalars().all()}

    rows = [
        _lead_row(cl, leads_map.get(cl.lead_id) if cl.lead_id else None)
        for cl in sorted(c.campaign_leads, key=lambda x: x.id)
    ]
    data = _campaign_out(c)
    data["campaign_leads"] = rows
    return data


@router.patch("/{campaign_id}")
async def update_campaign(
    campaign_id: int,
    body: CampaignUpdateIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    c = await _load_campaign(db, campaign_id)
    if c.status == CampaignStatus.running and is_runner_active(c.id):
        raise HTTPException(400, "Pause or stop the campaign before editing")

    if body.name is not None:
        c.name = body.name.strip()
    if body.description is not None:
        c.description = body.description.strip() or None
    agent_ids = _resolve_agent_ids(body) if (
        body.agent_ids is not None or body.agent_id is not None
    ) else None
    if agent_ids is not None:
        await _validate_agents(db, agent_ids)
        c.agent_id = agent_ids[0]
        delay = (
            body.inter_call_delay_sec
            if body.inter_call_delay_sec is not None
            else campaign_inter_call_delay(c)
        )
        c.meta = _campaign_meta_agents(c.meta, agent_ids, int(delay))
    elif body.inter_call_delay_sec is not None:
        c.meta = _campaign_meta_agents(
            c.meta, campaign_agent_ids(c), body.inter_call_delay_sec
        )

    await db.flush()
    return _campaign_out(c)


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    c = await _load_campaign(db, campaign_id)
    if c.status == CampaignStatus.running and is_runner_active(c.id):
        raise HTTPException(400, "Stop the campaign before deleting")
    await stop_runner(campaign_id)
    await db.delete(c)
    return {"ok": True, "id": campaign_id}


@router.post("/{campaign_id}/leads")
async def add_campaign_leads(
    campaign_id: int,
    body: CampaignLeadsIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    c = await _load_campaign(db, campaign_id)
    if c.status == CampaignStatus.running:
        raise HTTPException(400, "Pause the campaign before adding targets")

    added = 0
    if body.endpoints:
        added += await add_endpoints(db, c, body.endpoints)
    if body.lead_ids:
        added += await add_lead_ids(db, c, body.lead_ids)
    if not added:
        raise HTTPException(400, "Provide endpoints or lead_ids")

    await db.refresh(c, ["campaign_leads"])
    return {"campaign_id": campaign_id, "added": added, "lead_count": len(c.campaign_leads)}


@router.post("/{campaign_id}/import-csv")
async def import_campaign_csv(
    campaign_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    c = await _load_campaign(db, campaign_id)
    if c.status == CampaignStatus.running:
        raise HTTPException(400, "Pause the campaign before importing")

    raw = await file.read()
    try:
        rows = parse_campaign_csv(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    added = await add_csv_rows(db, c, rows)
    await db.refresh(c, ["campaign_leads"])
    return {
        "campaign_id": campaign_id,
        "imported": added,
        "lead_count": len(c.campaign_leads),
    }


@router.post("/{campaign_id}/start")
async def start_campaign(
    campaign_id: int,
    body: CampaignStartIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Start or schedule campaign. Uses rolling parallel slots — as each call ends, the next pending target dials."""
    c = await _load_campaign(db, campaign_id)
    if is_runner_active(c.id):
        raise HTTPException(409, "Campaign runner is already active")

    pending = [cl for cl in c.campaign_leads if cl.status == CampaignLeadStatus.pending]
    if not pending:
        raise HTTPException(400, "No pending targets to dial")

    meta = dict(c.meta or {})
    if body.inter_call_delay_sec is not None:
        meta["inter_call_delay_sec"] = body.inter_call_delay_sec
    runner = dict(meta.get("runner") or {})
    runner["max_parallel"] = body.max_parallel
    runner["inter_call_delay_sec"] = campaign_inter_call_delay(c)
    runner["agent_ids"] = campaign_agent_ids(c)
    if body.start_at:
        sched = body.start_at
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)
        runner["scheduled_at"] = sched.isoformat()
    else:
        runner.pop("scheduled_at", None)
    runner["active_dials"] = {}
    meta["runner"] = runner
    c.meta = meta
    c.status = CampaignStatus.running

    await db.flush()

    scheduled = body.start_at
    if scheduled and scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)

    await start_runner(
        c.id,
        max_parallel=body.max_parallel,
        scheduled_at=scheduled,
    )
    return {
        "campaign_id": campaign_id,
        "status": "running",
        "max_parallel": body.max_parallel,
        "inter_call_delay_sec": campaign_inter_call_delay(c),
        "agent_ids": campaign_agent_ids(c),
        "scheduled_at": runner.get("scheduled_at"),
        "pending": len(pending),
    }


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    c = await _load_campaign(db, campaign_id)
    c.status = CampaignStatus.paused
    await stop_runner(campaign_id)
    return {"campaign_id": campaign_id, "status": "paused"}


@router.post("/{campaign_id}/stop")
async def stop_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Stop runner; in-flight calls continue on bridge but no new dials."""
    c = await _load_campaign(db, campaign_id)
    await stop_runner(campaign_id)
    for cl in c.campaign_leads:
        if cl.status == CampaignLeadStatus.dialing:
            cl.status = CampaignLeadStatus.pending
            cl.dialed_at = None
    meta = dict(c.meta or {})
    runner = dict(meta.get("runner") or {})
    runner["active_dials"] = {}
    meta["runner"] = runner
    c.meta = meta
    c.status = CampaignStatus.draft
    return {"campaign_id": campaign_id, "status": "draft"}


@router.post("/{campaign_id}/reset")
async def reset_campaign_leads(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Reset failed/completed targets back to pending (for re-run after a bad attempt)."""
    c = await _load_campaign(db, campaign_id)
    if c.status == CampaignStatus.running and is_runner_active(c.id):
        raise HTTPException(400, "Stop the campaign before resetting targets")
    n = 0
    for cl in c.campaign_leads:
        if cl.status != CampaignLeadStatus.pending:
            cl.status = CampaignLeadStatus.pending
            cl.last_error = None
            cl.dialed_at = None
            cl.session_id = None
            n += 1
    c.status = CampaignStatus.draft
    return {"campaign_id": campaign_id, "reset": n}


@router.post("/{campaign_id}/dial")
async def dial_campaign_legacy(
    campaign_id: int,
    body: CampaignStartIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Legacy alias — use POST /start instead."""
    return await start_campaign(campaign_id, body, db, user)
