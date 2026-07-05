from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Note, User, UserRole, Lead, Contact, Session as DBSession
from backend.services.org_scope import note_org_clause, session_org_clause
from backend.services.data_scope import get_scope_filters_async, clamp_org_param

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteIn(BaseModel):
    entity_type: str
    entity_id: int
    content: str


async def _entity_in_user_org(
    db: AsyncSession, user: User, entity_type: str, entity_id: int
) -> bool:
    """Verify the referenced entity belongs to the user's org (non-admins only)."""
    if user.role == UserRole.admin:
        return True
    if entity_type == "session":
        s = await db.get(DBSession, entity_id)
        if not s:
            return False
        meta = (s.meta or {}).get("organization_id")
        if meta is not None:
            try:
                return int(meta) == user.organization_id
            except (TypeError, ValueError):
                pass
        if s.owner_id == user.id:
            return True
        if s.agent_id:
            from backend.db.models import Agent
            a = await db.get(Agent, s.agent_id)
            return bool(a and a.organization_id == user.organization_id)
        return False
    if entity_type == "lead":
        l = await db.get(Lead, entity_id)
        return bool(l and l.organization_id == user.organization_id)
    if entity_type == "contact":
        c = await db.get(Contact, entity_id)
        return bool(c and c.organization_id == user.organization_id)
    # Unknown entity type — be conservative for non-admins.
    return False


@router.get("")
async def list_notes(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    organization_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Note).order_by(Note.created_at.desc())
    for f in await get_scope_filters_async(user, Note, db):
        q = q.where(f)
    if entity_type:
        q = q.where(Note.entity_type == entity_type)
    if entity_id:
        q = q.where(Note.entity_id == entity_id)
    organization_id = clamp_org_param(user, organization_id)
    if organization_id:
        q = q.where(await note_org_clause(db, organization_id))
    result = await db.execute(q)
    return [{"id": n.id, "entity_type": n.entity_type, "entity_id": n.entity_id, "content": n.content, "created_by_id": n.created_by_id, "created_at": n.created_at} for n in result.scalars().all()]


@router.post("")
async def create_note(body: NoteIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not await _entity_in_user_org(db, user, body.entity_type, body.entity_id):
        raise HTTPException(403, "You cannot attach a note to a record outside your organization")
    n = Note(**body.model_dump(), created_by_id=user.id)
    db.add(n)
    await db.flush()
    return {"id": n.id, "content": n.content}


@router.delete("/{note_id}", status_code=204)
async def delete_note(note_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    n = result.scalar_one_or_none()
    if not n:
        raise HTTPException(404, "Note not found")
    # Regular users can only delete their own notes.
    if user.role == UserRole.user and n.created_by_id != user.id:
        raise HTTPException(403, "Access denied")
    # Org heads can only delete notes attached to records within their org.
    if user.role == UserRole.org_head:
        if not await _entity_in_user_org(db, user, n.entity_type, n.entity_id):
            raise HTTPException(403, "Access denied")
    await db.delete(n)