"""RBAC data scoping — returns SQLAlchemy WHERE clauses based on user role.

admin    → no filter (sees everything)
org_head → filter by organization_id (sees all data within their org)
user     → filter by owner_id (sees only their own data)
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Agent,
    Contact,
    Document,
    Lead,
    Note,
    Output,
    Session as DBSession,
    User,
    UserRole,
)
from backend.services.org_scope import (
    note_org_clause,
    session_org_clause,
)


def get_scope_filters(user: User, model) -> list:
    """Return a list of SQLAlchemy filter expressions for the given user + model.

    The caller appends these to their query's .where() clause.  For admin users
    the list is empty (no restriction).

    Use this for models that have a direct organization_id and/or owner_id
    column: Session, Contact, Lead, Campaign, Document, Agent.
    """
    if user.role == UserRole.admin:
        return []

    model_name = model.__name__ if hasattr(model, "__name__") else model.__class__.__name__

    if user.role == UserRole.org_head:
        # Session has no organization_id column — derive org via the agent
        # or session meta.organization_id. Falls back to owner_id for
        # sessions the org_head themselves initiated.
        if model_name == "Session":
            clauses = [session_org_clause(user.organization_id)]
            if hasattr(model, "owner_id"):
                clauses.append(model.owner_id == user.id)
            return [or_(*clauses)]
        if hasattr(model, "organization_id"):
            return [model.organization_id == user.organization_id]
        # Fallback: if model doesn't have organization_id, scope by owner
        if hasattr(model, "owner_id"):
            return [model.owner_id == user.id]
        return []

    # Regular user — restrict to own records only.
    # For org-scoped knowledge records (Document, Agent) with no owner_id,
    # fall back to the user's organization so they see org-shared knowledge.
    if hasattr(model, "owner_id"):
        return [model.owner_id == user.id]
    if model_name in ("Document", "Agent") and hasattr(model, "organization_id"):
        return [model.organization_id == user.organization_id]
    return []


async def get_scope_filters_async(user: User, model, db: AsyncSession) -> list:
    """Async variant for models whose org scoping requires a DB lookup.

    Currently used for:
    - Note: org derived via note_org_clause (joins Session/Lead/Contact).
    - Output: org derived via the Output.session_id -> Session relationship.

    Regular users are scoped by ownership (Note.created_by_id, or
    Session.owner_id for Outputs).
    """
    if user.role == UserRole.admin:
        return []

    model_name = model.__name__ if hasattr(model, "__name__") else model.__class__.__name__

    if user.role == UserRole.org_head:
        if model_name == "Note":
            return [await note_org_clause(db, user.organization_id)]
        if model_name == "Output":
            # Outputs are org-scoped via the session they belong to.
            org_session_ids = select(DBSession.id).where(
                session_org_clause(user.organization_id)
            )
            return [model.session_id.in_(org_session_ids)]
        return []

    # Regular user
    if model_name == "Note" and hasattr(model, "created_by_id"):
        return [model.created_by_id == user.id]
    if model_name == "Output":
        own_session_ids = select(DBSession.id).where(DBSession.owner_id == user.id)
        return [model.session_id.in_(own_session_ids)]
    if hasattr(model, "owner_id"):
        return [model.owner_id == user.id]
    return []


def can_access_record(user: User, record) -> bool:
    """Check if a user can access a specific record (for detail endpoints)."""
    if user.role == UserRole.admin:
        return True
    if user.role == UserRole.org_head:
        if hasattr(record, "organization_id") and record.organization_id is not None:
            return record.organization_id == user.organization_id
        # Session: derive org via the session's agent / meta.
        if record.__class__.__name__ == "Session":
            meta = getattr(record, "meta", None) or {}
            oid = meta.get("organization_id")
            if oid is not None:
                try:
                    return int(oid) == user.organization_id
                except (TypeError, ValueError):
                    pass
            if hasattr(record, "owner_id"):
                return record.owner_id == user.id
        if hasattr(record, "owner_id"):
            return record.owner_id == user.id
        return True  # records without ownership are visible to org_heads
    # Regular user
    if hasattr(record, "owner_id"):
        return record.owner_id == user.id
    return False


# ── Query-param clamping & agent-org validation ──────────────────────────────


def clamp_org_param(user: User, organization_id: Optional[int]) -> Optional[int]:
    """Force the ?organization_id= query param to the user's own org for non-admins.

    Non-admins can never request another org's id. If they pass a foreign org id
    it is silently replaced with their own; if they pass None it stays None (no
    extra filter, but the role scope filters in get_scope_filters still apply).
    """
    if user.role == UserRole.admin:
        return organization_id
    return user.organization_id


async def assert_agent_in_user_org(
    db: AsyncSession, user: User, agent_id: int
) -> Agent:
    """Load an agent and verify it belongs to the requesting user's org.

    Admins can access any agent. Non-admins get 403 if the agent belongs to a
    different org (or has no org). Returns the loaded Agent.
    """
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if user.role == UserRole.admin:
        return agent
    if agent.organization_id is None or agent.organization_id != user.organization_id:
        raise HTTPException(403, "Agent does not belong to your organization")
    return agent


# ── Helpers for query-param clamping & cross-org validation ──────────────────


def clamp_org_param(user: User, organization_id: Optional[int]) -> Optional[int]:
    """Force a user-supplied ?organization_id= query param to the user's own org
    for non-admins. Admins can pass any org id (or none). Returns the clamped
    value (or None if the caller is an admin and passed nothing).
    """
    if user.role == UserRole.admin:
        return organization_id
    return user.organization_id


async def assert_org_owned_by_user(
    db: AsyncSession, organization_id: int, user: User
) -> None:
    """For non-admins, verify the given organization_id matches the user's own
    org. Admins pass through. Used to validate create/update payloads that
    carry an organization_id field.
    """
    if user.role == UserRole.admin:
        return
    if organization_id != user.organization_id:
        raise HTTPException(403, "You can only operate within your own organization")