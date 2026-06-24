"""Organization scoping for CRM list endpoints."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Agent, Contact, Lead, Note, Output, Session as DBSession


def session_org_clause(organization_id: int):
    agent_ids = select(Agent.id).where(Agent.organization_id == organization_id)
    return or_(
        DBSession.agent_id.in_(agent_ids),
        DBSession.meta["organization_id"].as_string() == str(organization_id),
    )


async def lead_ids_for_org(db: AsyncSession, organization_id: int) -> list[int]:
    result = await db.execute(
        select(Lead.id).where(Lead.organization_id == organization_id)
    )
    return [row[0] for row in result.all()]


async def session_ids_for_org(db: AsyncSession, organization_id: int) -> list[int]:
    result = await db.execute(
        select(DBSession.id).where(session_org_clause(organization_id))
    )
    return [row[0] for row in result.all()]


async def contact_ids_for_org(db: AsyncSession, organization_id: int) -> list[int]:
    result = await db.execute(
        select(Contact.id).where(Contact.organization_id == organization_id)
    )
    return [row[0] for row in result.all()]


async def note_org_clause(db: AsyncSession, organization_id: int):
    session_ids = await session_ids_for_org(db, organization_id)
    lead_ids = await lead_ids_for_org(db, organization_id)
    contact_ids = await contact_ids_for_org(db, organization_id)
    clauses = []
    if session_ids:
        clauses.append((Note.entity_type == "session") & Note.entity_id.in_(session_ids))
    if lead_ids:
        clauses.append((Note.entity_type == "lead") & Note.entity_id.in_(lead_ids))
    if contact_ids:
        clauses.append((Note.entity_type == "contact") & Note.entity_id.in_(contact_ids))
    if not clauses:
        return Note.id == -1
    return or_(*clauses)


async def org_names_map(db: AsyncSession, org_ids: set[int]) -> dict[int, str]:
    if not org_ids:
        return {}
    from backend.db.models import Organization

    result = await db.execute(
        select(Organization).where(Organization.id.in_(org_ids))
    )
    return {o.id: o.name for o in result.scalars()}


async def resolve_session_org(
    db: AsyncSession, session: DBSession
) -> tuple[Optional[int], Optional[str]]:
    meta = session.meta or {}
    oid = meta.get("organization_id")
    if oid is not None:
        try:
            oid = int(oid)
        except (TypeError, ValueError):
            oid = None
    if session.agent_id:
        agent = await db.get(Agent, session.agent_id)
        if agent and agent.organization_id:
            oid = agent.organization_id
    if not oid:
        return None, None
    from backend.db.models import Organization

    org = await db.get(Organization, oid)
    return oid, org.name if org else None
