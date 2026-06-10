"""Outbound cold-call API — lab softphone first, PSTN trunk later."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.deps import get_current_user
from backend.config import get_settings
from backend.db.database import get_db
from backend.db.models import Agent, AgentType, Lead
from backend.services.bridge_client import originate_outbound

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/outbound", tags=["outbound"])


class OutboundDialIn(BaseModel):
    agent_id: int
    lead_id: Optional[int] = None
    endpoint: Optional[str] = Field(
        None,
        description="ARI endpoint e.g. PJSIP/1001 — defaults to OUTBOUND_LAB_ENDPOINT",
    )
    caller_id: Optional[str] = Field(
        None,
        description="Caller ID presented to callee — defaults to OUTBOUND_DEFAULT_CALLER_ID",
    )


def _lead_endpoint(lead: Lead) -> Optional[str]:
    phone = (lead.phone or "").strip()
    if not phone:
        return None
    if phone.upper().startswith("PJSIP/"):
        return phone
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        return None
    return f"PJSIP/{digits}"


@router.get("/agents")
async def list_outbound_agents(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Active outbound_sales agents available for dialing."""
    result = await db.execute(
        select(Agent)
        .where(
            Agent.is_active.is_(True),
            Agent.type == AgentType.outbound_sales,
        )
        .order_by(Agent.name)
    )
    agents = result.scalars().all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "slug": a.slug,
            "voice": a.voice,
            "inbound_extension": a.inbound_extension,
        }
        for a in agents
    ]


@router.post("/dial")
async def dial_outbound(
    body: OutboundDialIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Originate an outbound call through gemini_bridge → Asterisk → softphone."""
    result = await db.execute(
        select(Agent).where(Agent.id == body.agent_id, Agent.is_active.is_(True))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent.type != AgentType.outbound_sales:
        raise HTTPException(400, "Agent is not an outbound_sales agent")

    endpoint = (body.endpoint or "").strip()
    lead: Lead | None = None
    if body.lead_id is not None:
        lead = await db.get(Lead, body.lead_id)
        if lead is None:
            raise HTTPException(404, "Lead not found")
        if not endpoint:
            endpoint = _lead_endpoint(lead) or ""

    if not endpoint:
        endpoint = settings.outbound_lab_endpoint.strip()

    if not endpoint:
        raise HTTPException(
            400,
            "No dial endpoint — set endpoint, lead phone, or OUTBOUND_LAB_ENDPOINT",
        )

    caller_id = (body.caller_id or settings.outbound_default_caller_id or "1000").strip()

    try:
        bridge_resp = await originate_outbound(
            agent_slug=agent.slug,
            endpoint=endpoint,
            lead_id=body.lead_id,
            caller_id=caller_id,
        )
    except RuntimeError as exc:
        logger.exception("Outbound dial failed agent=%s endpoint=%s", agent.slug, endpoint)
        raise HTTPException(502, str(exc)) from exc

    return {
        "status": "dialing",
        "agent_id": agent.id,
        "agent_slug": agent.slug,
        "endpoint": endpoint,
        "lead_id": body.lead_id,
        "caller_id": caller_id,
        "bridge": bridge_resp,
    }
