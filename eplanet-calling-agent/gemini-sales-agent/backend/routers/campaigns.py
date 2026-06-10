"""Outbound campaigns — batch dial leads (lab or trunk-ready)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
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
from backend.services.outbound_dialer import dial_one

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignIn(BaseModel):
    name: str
    agent_id: int
    description: Optional[str] = None
    lead_ids: list[int] = Field(default_factory=list)
    endpoints: list[str] = Field(
        default_factory=list,
        description="Lab demo: ['PJSIP/1001','PJSIP/1002'] when no leads",
    )


class CampaignDialIn(BaseModel):
    max_parallel: int = Field(2, ge=1, le=10)
    campaign_lead_ids: Optional[list[int]] = None


def _campaign_out(c: Campaign) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "agent_id": c.agent_id,
        "status": c.status.value if hasattr(c.status, "value") else c.status,
        "description": c.description,
        "meta": c.meta or {},
        "lead_count": len(c.campaign_leads or []),
        "created_at": c.created_at,
    }


@router.get("")
async def list_campaigns(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(
        select(Campaign).order_by(Campaign.created_at.desc())
    )
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
    agent = await db.get(Agent, body.agent_id)
    if not agent or not agent.is_active:
        raise HTTPException(404, "Agent not found")
    if agent.type != AgentType.outbound_sales:
        raise HTTPException(400, "Campaign agent must be outbound_sales")

    campaign = Campaign(
        name=body.name,
        agent_id=body.agent_id,
        description=body.description,
        status=CampaignStatus.draft,
        meta={"endpoints": body.endpoints} if body.endpoints else {},
    )
    db.add(campaign)
    await db.flush()

    if body.lead_ids:
        for lid in body.lead_ids:
            lead = await db.get(Lead, lid)
            if lead:
                db.add(CampaignLead(campaign_id=campaign.id, lead_id=lid))
    elif body.endpoints:
        for ep in body.endpoints:
            db.add(CampaignLead(campaign_id=campaign.id, endpoint=ep.strip()))

    await db.flush()
    await db.refresh(campaign, ["campaign_leads"])
    return _campaign_out(campaign)


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(selectinload(Campaign.campaign_leads))
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Campaign not found")
    rows = []
    for cl in c.campaign_leads:
        rows.append({
            "id": cl.id,
            "lead_id": cl.lead_id,
            "endpoint": cl.endpoint,
            "status": cl.status.value if hasattr(cl.status, "value") else cl.status,
            "session_id": cl.session_id,
            "last_error": cl.last_error,
            "dialed_at": cl.dialed_at,
        })
    data = _campaign_out(c)
    data["campaign_leads"] = rows
    return data


@router.post("/{campaign_id}/dial")
async def dial_campaign(
    campaign_id: int,
    body: CampaignDialIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Dial pending campaign leads (up to max_parallel at once)."""
    result = await db.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(selectinload(Campaign.campaign_leads))
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    agent = await db.get(Agent, campaign.agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    pending = [
        cl
        for cl in campaign.campaign_leads
        if cl.status == CampaignLeadStatus.pending
    ]
    if body.campaign_lead_ids:
        ids = set(body.campaign_lead_ids)
        pending = [cl for cl in pending if cl.id in ids]

    to_dial = pending[: body.max_parallel]
    if not to_dial:
        raise HTTPException(400, "No pending campaign leads to dial")

    campaign.status = CampaignStatus.running
    results = []
    for cl in to_dial:
        lead = await db.get(Lead, cl.lead_id) if cl.lead_id else None
        cl.status = CampaignLeadStatus.dialing
        cl.dialed_at = datetime.now(timezone.utc)
        try:
            resp = await dial_one(
                db,
                agent=agent,
                lead=lead,
                lead_id=cl.lead_id,
                endpoint=cl.endpoint,
            )
            cl.status = CampaignLeadStatus.completed
            results.append({"campaign_lead_id": cl.id, "ok": True, **resp})
        except Exception as exc:
            cl.status = CampaignLeadStatus.failed
            cl.last_error = str(exc)
            results.append({
                "campaign_lead_id": cl.id,
                "ok": False,
                "error": str(exc),
            })

    await db.flush()
    return {
        "campaign_id": campaign_id,
        "dialed": len(results),
        "results": results,
    }
