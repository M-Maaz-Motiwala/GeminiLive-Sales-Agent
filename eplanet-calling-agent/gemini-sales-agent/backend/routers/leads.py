from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Lead, LeadStatus

router = APIRouter(prefix="/api/leads", tags=["leads"])


class LeadIn(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    status: LeadStatus = LeadStatus.new
    notes: Optional[str] = None
    tags: list = []


def _out(l: Lead) -> dict:
    return {"id": l.id, "name": l.name, "email": l.email, "phone": l.phone,
            "company": l.company, "status": l.status, "notes": l.notes,
            "tags": l.tags, "source_session_id": l.source_session_id,
            "created_at": l.created_at, "updated_at": l.updated_at}


@router.get("")
async def list_leads(
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(Lead).order_by(Lead.created_at.desc()).limit(limit)
    if status:
        q = q.where(Lead.status == status)
    if search:
        q = q.where(or_(Lead.name.ilike(f"%{search}%"), Lead.email.ilike(f"%{search}%"), Lead.company.ilike(f"%{search}%")))
    result = await db.execute(q)
    return [_out(l) for l in result.scalars().all()]


@router.post("")
async def create_lead(body: LeadIn, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    lead = Lead(**body.model_dump())
    db.add(lead)
    await db.flush()
    return _out(lead)


@router.get("/{lead_id}")
async def get_lead(lead_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    l = result.scalar_one_or_none()
    if not l:
        raise HTTPException(404, "Lead not found")
    return _out(l)


@router.put("/{lead_id}")
async def update_lead(lead_id: int, body: LeadIn, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    l = result.scalar_one_or_none()
    if not l:
        raise HTTPException(404, "Lead not found")
    for field, value in body.model_dump().items():
        setattr(l, field, value)
    return _out(l)


@router.delete("/{lead_id}", status_code=204)
async def delete_lead(lead_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    l = result.scalar_one_or_none()
    if not l:
        raise HTTPException(404, "Lead not found")
    await db.delete(l)
