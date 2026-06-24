"""Route inbound calls to DID-scoped sales agent pools (callback-aware)."""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Agent, AgentType, Session as DBSession, SessionStatus
from backend.services.callback_context import find_prior_outbound_session
from backend.services.phone_normalize import dids_match, normalize_did

logger = logging.getLogger(__name__)

_SALES_TYPES = (AgentType.sales, AgentType.outbound_sales)
_FLEET_EXTENSIONS = frozenset({"700", "701", "702", "703", "704"})
_DEFAULT_ORG_DID = os.getenv("DEFAULT_ORG_DID", "12107297915")


async def busy_agent_ids(db: AsyncSession) -> set[int]:
    """Agents currently on an active platform session."""
    result = await db.execute(
        select(DBSession.agent_id).where(
            DBSession.status == SessionStatus.active,
            DBSession.agent_id.isnot(None),
        )
    )
    return {row[0] for row in result.all() if row[0] is not None}


def _effective_did(
    dialed_did: Optional[str],
    dialed_extension: Optional[str],
) -> Optional[str]:
    if dialed_did:
        return normalize_did(dialed_did)
    if dialed_extension in _FLEET_EXTENSIONS:
        return normalize_did(_DEFAULT_ORG_DID)
    return None


async def _sales_agents_for_did(
    db: AsyncSession, org_did: str
) -> list[Agent]:
    result = await db.execute(
        select(Agent)
        .where(Agent.is_active.is_(True), Agent.type.in_(_SALES_TYPES))
        .order_by(Agent.id)
    )
    return [a for a in result.scalars() if dids_match(a.did, org_did)]


async def find_callback_owner(
    db: AsyncSession,
    caller_id: Optional[str],
    *,
    org_did: Optional[str] = None,
) -> Optional[Agent]:
    prior = await find_prior_outbound_session(db, caller_id)
    if prior and prior.agent_id:
        agent = await db.get(Agent, prior.agent_id)
        if agent and agent.is_active and agent.type in _SALES_TYPES:
            if org_did and not dids_match(agent.did, org_did):
                logger.info(
                    "Callback owner agent=%s DID mismatch (want %s, agent %s)",
                    agent.slug,
                    org_did,
                    agent.did,
                )
                return None
            logger.info(
                "Callback match session=%d agent=%s caller=%s",
                prior.id,
                agent.slug,
                caller_id,
            )
            return agent
    return None


async def resolve_inbound_agent(
    db: AsyncSession,
    *,
    caller_id: Optional[str] = None,
    agent_slug: Optional[str] = None,
    dialed_extension: Optional[str] = None,
    dialed_did: Optional[str] = None,
) -> Agent:
    """Pick sales agent for an inbound call (DID pool + callback-aware)."""
    if agent_slug:
        result = await db.execute(
            select(Agent).where(Agent.slug == agent_slug, Agent.is_active.is_(True))
        )
        agent = result.scalar_one_or_none()
        if agent:
            return agent
        logger.warning("No active agent for slug=%s; continuing routing", agent_slug)

    if dialed_extension and dialed_extension not in _FLEET_EXTENSIONS:
        result = await db.execute(
            select(Agent).where(
                Agent.inbound_extension == dialed_extension,
                Agent.is_active.is_(True),
            )
        )
        agent = result.scalar_one_or_none()
        if agent:
            return agent

    org_did = _effective_did(dialed_did, dialed_extension)
    if not org_did:
        raise RuntimeError("No DID on inbound call — cannot route")

    pool = await _sales_agents_for_did(db, org_did)
    if not pool:
        raise RuntimeError(f"No active agents for DID {org_did}")

    busy = await busy_agent_ids(db)
    owner = await find_callback_owner(db, caller_id, org_did=org_did)
    if owner and owner.id not in busy and owner in pool:
        return owner

    candidates = [a for a in pool if a.id not in busy]
    if owner and owner in pool and owner in candidates:
        return owner
    if candidates:
        return candidates[0]
    if owner and owner in pool:
        return owner

    return pool[0]
