"""Route inbound callbacks to sales agents; resolve available support agents for transfers."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Agent, AgentType, Session as DBSession, SessionStatus
from backend.services.callback_context import find_prior_outbound_session

logger = logging.getLogger(__name__)

_SALES_TYPES = (AgentType.sales, AgentType.outbound_sales)
_SUPPORT_TYPES = (AgentType.support, AgentType.document_qa)


async def busy_agent_ids(db: AsyncSession) -> set[int]:
    """Agents currently on an active platform session."""
    result = await db.execute(
        select(DBSession.agent_id).where(
            DBSession.status == SessionStatus.active,
            DBSession.agent_id.isnot(None),
        )
    )
    return {row[0] for row in result.all() if row[0] is not None}


async def find_callback_owner(
    db: AsyncSession, caller_id: Optional[str]
) -> Optional[Agent]:
    prior = await find_prior_outbound_session(db, caller_id)
    if prior and prior.agent_id:
        agent = await db.get(Agent, prior.agent_id)
        if agent and agent.is_active and agent.type in _SALES_TYPES:
            logger.info(
                "Callback match session=%d agent=%s caller=%s",
                prior.id,
                agent.slug,
                caller_id,
            )
            return agent
    return None


async def resolve_support_agent(
    db: AsyncSession,
    *,
    exclude_agent_id: Optional[int] = None,
) -> Agent:
    """Pick an available FAQ/support agent for a live transfer."""
    busy = await busy_agent_ids(db)
    if exclude_agent_id is not None:
        busy.add(exclude_agent_id)

    result = await db.execute(
        select(Agent)
        .where(Agent.is_active.is_(True), Agent.type.in_(_SUPPORT_TYPES))
        .order_by(Agent.id)
    )
    candidates = [a for a in result.scalars() if a.id not in busy]
    if candidates:
        return candidates[0]

    result = await db.execute(
        select(Agent)
        .where(Agent.is_active.is_(True), Agent.type.in_(_SUPPORT_TYPES))
        .order_by(Agent.id)
        .limit(1)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise RuntimeError("No active support agent configured")
    return agent


async def resolve_inbound_agent(
    db: AsyncSession,
    *,
    caller_id: Optional[str] = None,
    agent_slug: Optional[str] = None,
    dialed_extension: Optional[str] = None,
) -> Agent:
    """Pick agent for an inbound call (sales callback router or direct extension)."""
    if agent_slug:
        result = await db.execute(
            select(Agent).where(Agent.slug == agent_slug, Agent.is_active.is_(True))
        )
        agent = result.scalar_one_or_none()
        if agent:
            return agent
        logger.warning("No active agent for slug=%s; continuing routing", agent_slug)

    if dialed_extension and dialed_extension not in ("700", "s"):
        result = await db.execute(
            select(Agent).where(
                Agent.inbound_extension == dialed_extension,
                Agent.is_active.is_(True),
            )
        )
        agent = result.scalar_one_or_none()
        if agent:
            return agent

    # Shared DID / ext 700 — sales callback fleet only (never auto-pick support).
    busy = await busy_agent_ids(db)
    owner = await find_callback_owner(db, caller_id)
    if owner and owner.id not in busy:
        return owner

    result = await db.execute(
        select(Agent)
        .where(Agent.is_active.is_(True), Agent.type.in_(_SALES_TYPES))
        .order_by(Agent.id)
    )
    candidates = [a for a in result.scalars() if a.id not in busy]
    if owner and owner in candidates:
        return owner
    if candidates:
        return candidates[0]
    if owner:
        return owner

    result = await db.execute(
        select(Agent)
        .where(Agent.is_active.is_(True), Agent.type.in_(_SALES_TYPES))
        .order_by(Agent.id)
        .limit(1)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise RuntimeError("No active sales agent configured")
    return agent
