from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Lead, LeadStatus, User
from backend.services.org_scope import org_names_map
from backend.services.data_scope import get_scope_filters, can_access_record, clamp_org_param

router = APIRouter(prefix="/api/leads", tags=["leads"])


class LeadIn(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    status: LeadStatus = LeadStatus.new
    notes: Optional[str] = None
    tags: list = []
    lead_profile: Optional[dict] = None


def _out(l: Lead, org_name: Optional[str] = None) -> dict:
    return {"id": l.id, "name": l.name, "email": l.email, "phone": l.phone,
            "company": l.company, "status": l.status, "notes": l.notes,
            "tags": l.tags, "source_session_id": l.source_session_id,
            "organization_id": l.organization_id,
            "organization_name": org_name,
            "lead_profile": l.lead_profile or {},
            "created_at": l.created_at, "updated_at": l.updated_at}


@router.get("")
async def list_leads(
    status: Optional[str] = None,
    search: Optional[str] = None,
    organization_id: Optional[int] = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Lead).order_by(Lead.created_at.desc()).limit(limit)
    for f in get_scope_filters(user, Lead):
        q = q.where(f)
    organization_id = clamp_org_param(user, organization_id)
    if status:
        q = q.where(Lead.status == status)
    if organization_id:
        q = q.where(Lead.organization_id == organization_id)
    if search:
        q = q.where(or_(Lead.name.ilike(f"%{search}%"), Lead.email.ilike(f"%{search}%"), Lead.company.ilike(f"%{search}%")))
    result = await db.execute(q)
    leads = result.scalars().all()
    org_ids = {l.organization_id for l in leads if l.organization_id}
    names = await org_names_map(db, org_ids)
    return [_out(l, names.get(l.organization_id or -1)) for l in leads]


@router.post("")
async def create_lead(body: LeadIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    lead = Lead(**body.model_dump(), owner_id=user.id)
    db.add(lead)
    await db.flush()
    return _out(lead)


@router.get("/{lead_id}")
async def get_lead(lead_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    l = result.scalar_one_or_none()
    if not l:
        raise HTTPException(404, "Lead not found")
    if not can_access_record(user, l):
        raise HTTPException(403, "Access denied")
    return _out(l)


class LeadPatch(BaseModel):
    status: Optional[LeadStatus] = None
    notes: Optional[str] = None
    tags: Optional[list] = None
    lead_profile: Optional[dict] = None


@router.patch("/{lead_id}")
async def patch_lead(lead_id: int, body: LeadPatch, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    l = result.scalar_one_or_none()
    if not l:
        raise HTTPException(404, "Lead not found")
    if not can_access_record(user, l):
        raise HTTPException(403, "Access denied")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(l, field, value)
    return _out(l)


@router.put("/{lead_id}")
async def update_lead(lead_id: int, body: LeadIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    l = result.scalar_one_or_none()
    if not l:
        raise HTTPException(404, "Lead not found")
    if not can_access_record(user, l):
        raise HTTPException(403, "Access denied")
    for field, value in body.model_dump().items():
        setattr(l, field, value)
    return _out(l)


@router.delete("/{lead_id}", status_code=204)
async def delete_lead(lead_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    l = result.scalar_one_or_none()
    if not l:
        raise HTTPException(404, "Lead not found")
    if not can_access_record(user, l):
        raise HTTPException(403, "Access denied")
    await db.delete(l)
