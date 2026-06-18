from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Contact
from backend.services.org_scope import org_names_map

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


class ContactIn(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    tags: list = []


def _out(c: Contact, org_name: Optional[str] = None) -> dict:
    return {"id": c.id, "name": c.name, "email": c.email, "phone": c.phone,
            "company": c.company, "notes": c.notes, "tags": c.tags,
            "organization_id": c.organization_id,
            "organization_name": org_name,
            "created_at": c.created_at, "updated_at": c.updated_at}


@router.get("")
async def list_contacts(
    search: Optional[str] = None,
    organization_id: Optional[int] = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(Contact).order_by(Contact.created_at.desc()).limit(limit)
    if organization_id:
        q = q.where(Contact.organization_id == organization_id)
    if search:
        q = q.where(or_(
            Contact.name.ilike(f"%{search}%"),
            Contact.email.ilike(f"%{search}%"),
            Contact.phone.ilike(f"%{search}%"),
            Contact.company.ilike(f"%{search}%"),
        ))
    result = await db.execute(q)
    contacts = result.scalars().all()
    org_ids = {c.organization_id for c in contacts if c.organization_id}
    names = await org_names_map(db, org_ids)
    return [_out(c, names.get(c.organization_id or -1)) for c in contacts]


@router.post("")
async def create_contact(body: ContactIn, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    c = Contact(**body.model_dump())
    db.add(c)
    await db.flush()
    return _out(c)


@router.get("/{contact_id}")
async def get_contact(contact_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Contact not found")
    return _out(c)


@router.put("/{contact_id}")
async def update_contact(contact_id: int, body: ContactIn, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Contact not found")
    for field, value in body.model_dump().items():
        setattr(c, field, value)
    return _out(c)


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(contact_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Contact not found")
    await db.delete(c)
