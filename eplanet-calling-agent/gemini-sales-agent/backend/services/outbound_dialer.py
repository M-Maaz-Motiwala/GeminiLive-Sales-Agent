"""Shared outbound dial logic for single, batch, and campaign flows."""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db.models import Agent, AgentType, Lead, Organization
from backend.services.bridge_client import bridge_status, originate_outbound
from backend.services.endpoint_resolver import resolve_caller_id, resolve_endpoint
from backend.services.outbound_policy import assert_may_dial
from backend.services.phone_utils import normalize_e164

logger = logging.getLogger(__name__)
settings = get_settings()


async def _resolve_agent_did(db: AsyncSession, agent: Agent) -> Optional[str]:
    """Organization DID is the source of truth for outbound caller ID."""
    if agent.organization_id:
        org = await db.get(Organization, agent.organization_id)
        if org and org.did:
            if agent.did != org.did:
                agent.did = org.did
            return org.did
    return agent.did


async def dial_one(
    db: AsyncSession,
    *,
    agent: Agent,
    lead: Optional[Lead] = None,
    lead_id: Optional[int] = None,
    endpoint: Optional[str] = None,
    caller_id: Optional[str] = None,
    campaign_lead_id: Optional[int] = None,
    connect_experience: Optional[str] = None,
) -> dict[str, Any]:
    if agent.type not in (AgentType.sales, AgentType.outbound_sales):
        raise ValueError("Agent is not a sales agent")

    phone = lead.phone if lead else None
    await assert_may_dial(db, phone=phone)

    ep, ep_meta = resolve_endpoint(lead=lead, explicit_endpoint=endpoint)
    agent_did = await _resolve_agent_did(db, agent)
    cid = resolve_caller_id(caller_id, agent_did=agent_did)
    logger.info(
        "Outbound dial agent=%s org=%s caller_id=%s endpoint=%s",
        agent.slug,
        agent.organization_id,
        cid,
        ep,
    )

    status = await bridge_status()
    active = int(status.get("active_calls") or 0)
    max_c = int(status.get("max_concurrent") or settings.max_concurrent_outbound)
    if active >= max_c:
        raise RuntimeError(f"Bridge at capacity ({active}/{max_c} active calls)")

    bridge_resp = await originate_outbound(
        agent_slug=agent.slug,
        endpoint=ep,
        lead_id=lead_id or (lead.id if lead else None),
        caller_id=cid,
        campaign_lead_id=campaign_lead_id,
        connect_experience=connect_experience,
    )

    if lead and lead.phone:
        e164 = normalize_e164(lead.phone, settings.outbound_default_country_code)
        if e164 and not lead.phone_e164:
            lead.phone_e164 = e164

    return {
        "status": "dialing",
        "agent_id": agent.id,
        "agent_slug": agent.slug,
        "endpoint": ep,
        "endpoint_meta": ep_meta,
        "lead_id": lead_id or (lead.id if lead else None),
        "caller_id": cid,
        "connect_experience": connect_experience or "auto_greeting",
        "bridge": bridge_resp,
    }
