"""Shared outbound dial logic for single, batch, and campaign flows."""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db.models import Agent, AgentType, Lead
from backend.services.bridge_client import bridge_status, originate_outbound
from backend.services.endpoint_resolver import resolve_caller_id, resolve_endpoint
from backend.services.outbound_policy import assert_may_dial
from backend.services.phone_utils import normalize_e164

logger = logging.getLogger(__name__)
settings = get_settings()


async def dial_one(
    db: AsyncSession,
    *,
    agent: Agent,
    lead: Optional[Lead] = None,
    lead_id: Optional[int] = None,
    endpoint: Optional[str] = None,
    caller_id: Optional[str] = None,
    campaign_lead_id: Optional[int] = None,
) -> dict[str, Any]:
    if agent.type != AgentType.outbound_sales:
        raise ValueError("Agent is not outbound_sales")

    phone = lead.phone if lead else None
    await assert_may_dial(db, phone=phone)

    ep, ep_meta = resolve_endpoint(lead=lead, explicit_endpoint=endpoint)
    cid = resolve_caller_id(caller_id)

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
        "bridge": bridge_resp,
    }
