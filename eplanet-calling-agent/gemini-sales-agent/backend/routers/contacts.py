from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Contact

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


class ContactIn(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None
    tags: list = []


def _out(c: Contact) -> dict:
    return {"id": c.id, "name": c.name, "email": c.email, "phone": c.phone,
            "company": c.company, "notes": c.notes, "tags": c.tags,
            "created_at": c.created_at, "updated_at": c.updated_at}


@router.get("")
async def list_contacts(
    search: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(Contact).order_by(Contact.created_at.desc()).limit(limit)
    if search:
        q = q.where(or_(Contact.name.ilike(f"%{search}%"), Contact.email.ilike(f"%{search}%")))
    result = await db.execute(q)
    return [_out(c) for c in result.scalars().all()]


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
