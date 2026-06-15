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
from backend.services.bridge_client import bridge_status
from backend.services.outbound_dialer import dial_one
from backend.services.outbound_policy import within_call_window
from backend.services.session_reconcile import reconcile_stale_bridge_sessions

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/outbound", tags=["outbound"])


class OutboundDialIn(BaseModel):
    agent_id: int
    lead_id: Optional[int] = None
    endpoint: Optional[str] = Field(
        None,
        description="ARI endpoint e.g. PJSIP/1001 — defaults via endpoint resolver",
    )
    caller_id: Optional[str] = None


class BatchDialIn(BaseModel):
    agent_id: int
    endpoints: list[str] = Field(
        default_factory=list,
        description="Lab demo: ['PJSIP/1001', 'PJSIP/1002']",
    )
    lead_ids: list[int] = Field(default_factory=list)


@router.get("/status")
async def outbound_status(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Bridge capacity + outbound mode (for CRM dashboard)."""
    await reconcile_stale_bridge_sessions(db)
    try:
        bridge = await bridge_status()
    except Exception as exc:
        bridge = {"error": str(exc)}
    allowed, window_reason = within_call_window()
    return {
        "outbound_mode": settings.outbound_mode,
        "call_window_allowed": allowed,
        "call_window_reason": window_reason,
        "max_concurrent": settings.max_concurrent_outbound,
        "bridge": bridge,
    }


@router.get("/agents")
async def list_outbound_agents(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(
        select(Agent)
        .where(
            Agent.is_active.is_(True),
            Agent.type.in_((AgentType.sales, AgentType.outbound_sales)),
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
    result = await db.execute(
        select(Agent).where(Agent.id == body.agent_id, Agent.is_active.is_(True))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    lead: Lead | None = None
    if body.lead_id is not None:
        lead = await db.get(Lead, body.lead_id)
        if lead is None:
            raise HTTPException(404, "Lead not found")

    try:
        return await dial_one(
            db,
            agent=agent,
            lead=lead,
            lead_id=body.lead_id,
            endpoint=body.endpoint,
            caller_id=body.caller_id,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        logger.exception("Outbound dial failed")
        raise HTTPException(502, str(exc)) from exc


@router.post("/dial/batch")
async def dial_batch(
    body: BatchDialIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Dial multiple targets at once (lab: two softphones). Respects bridge capacity."""
    result = await db.execute(
        select(Agent).where(Agent.id == body.agent_id, Agent.is_active.is_(True))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    targets: list[tuple[Optional[Lead], Optional[int], Optional[str]]] = []
    for lid in body.lead_ids:
        lead = await db.get(Lead, lid)
        targets.append((lead, lid, None))
    for ep in body.endpoints:
        targets.append((None, None, ep.strip()))

    if not targets:
        raise HTTPException(400, "Provide endpoints and/or lead_ids")

    results = []
    for lead, lead_id, endpoint in targets:
        try:
            resp = await dial_one(
                db,
                agent=agent,
                lead=lead,
                lead_id=lead_id,
                endpoint=endpoint,
            )
            results.append({"ok": True, **resp})
        except Exception as exc:
            results.append({
                "ok": False,
                "lead_id": lead_id,
                "endpoint": endpoint,
                "error": str(exc),
            })

    ok_count = sum(1 for r in results if r.get("ok"))
    return {
        "status": "completed",
        "dialed": ok_count,
        "failed": len(results) - ok_count,
        "results": results,
    }
