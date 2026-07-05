import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from backend.auth.deps import get_current_user, require_admin
from backend.db.database import get_db
from backend.db.models import Agent, Organization, User, UserRole
from backend.services.asterisk_registry import sync_organizations_to_asterisk
from backend.services.phone_normalize import normalize_did

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


class OrganizationIn(BaseModel):
    name: str
    did: str
    is_active: bool = True

    @field_validator("did")
    @classmethod
    def validate_did(cls, v: str) -> str:
        normalized = normalize_did(v)
        if not normalized:
            raise ValueError("DID must be a valid phone number (10+ digits)")
        return normalized

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Organization name is required")
        return v


def _org_out(org: Organization, agent_count: int = 0) -> dict:
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "did": org.did,
        "is_active": org.is_active,
        "agent_count": agent_count,
        "created_at": org.created_at,
    }


def _unique_slug(base: str, existing: set[str]) -> str:
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}-{n}"
        n += 1
    return slug


async def _agent_counts(db: AsyncSession) -> dict[int, int]:
    result = await db.execute(
        select(Agent.organization_id, func.count(Agent.id))
        .where(Agent.organization_id.isnot(None), Agent.is_active.is_(True))
        .group_by(Agent.organization_id)
    )
    return {row[0]: row[1] for row in result.all()}


@router.get("")
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Non-admins only see their own organization.
    if user.role != UserRole.admin:
        if not user.organization_id:
            return []
        org = await db.get(Organization, user.organization_id)
        if not org:
            return []
        counts = await _agent_counts(db)
        return [_org_out(org, counts.get(org.id, 0))]
    result = await db.execute(
        select(Organization).order_by(Organization.created_at.desc())
    )
    orgs = result.scalars().all()
    counts = await _agent_counts(db)
    return [_org_out(o, counts.get(o.id, 0)) for o in orgs]


@router.get("/available")
async def list_available_organizations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return all active organizations for the access-request dropdown.

    Any authenticated user (including unapproved ones with no organization yet)
    can list active orgs so they can pick one to request access to.
    """
    result = await db.execute(
        select(Organization)
        .where(Organization.is_active.is_(True))
        .order_by(Organization.name.asc())
    )
    orgs = result.scalars().all()
    return [{"id": o.id, "name": o.name} for o in orgs]


@router.get("/{org_id}")
async def get_organization(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    if user.role != UserRole.admin and org.id != user.organization_id:
        raise HTTPException(403, "Access denied")
    counts = await _agent_counts(db)
    return _org_out(org, counts.get(org.id, 0))


@router.post("")
async def create_organization(
    body: OrganizationIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    existing = await db.execute(
        select(Organization).where(Organization.did == body.did)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"DID {body.did} is already registered")

    slug_base = re.sub(r"[^a-z0-9-]", "-", body.name.lower().strip()).strip("-") or "org"
    taken = {row[0] for row in (await db.execute(select(Organization.slug))).all()}
    slug = _unique_slug(slug_base, taken)

    org = Organization(
        name=body.name,
        slug=slug,
        did=body.did,
        is_active=body.is_active,
    )
    db.add(org)
    await db.flush()

    telephony = await sync_organizations_to_asterisk(db)
    return {**_org_out(org, 0), "telephony": telephony}


@router.put("/{org_id}")
async def update_organization(
    org_id: int,
    body: OrganizationIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")

    if body.did != org.did:
        clash = await db.execute(
            select(Organization).where(
                Organization.did == body.did,
                Organization.id != org_id,
            )
        )
        if clash.scalar_one_or_none():
            raise HTTPException(400, f"DID {body.did} is already registered")

    org.name = body.name
    org.did = body.did
    org.is_active = body.is_active

    agents = await db.execute(select(Agent).where(Agent.organization_id == org_id))
    for agent in agents.scalars():
        agent.did = body.did

    await db.flush()
    telephony = await sync_organizations_to_asterisk(db)
    counts = await _agent_counts(db)
    return {**_org_out(org, counts.get(org.id, 0)), "telephony": telephony}


@router.delete("/{org_id}", status_code=204)
async def delete_organization(
    org_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")

    agents = await db.execute(
        select(func.count(Agent.id)).where(
            Agent.organization_id == org_id,
            Agent.is_active.is_(True),
        )
    )
    if (agents.scalar() or 0) > 0:
        raise HTTPException(
            400,
            "Cannot delete organization with active agents — deactivate or reassign agents first",
        )

    await db.delete(org)
    await db.flush()
    await sync_organizations_to_asterisk(db)
