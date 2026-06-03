from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Note

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteIn(BaseModel):
    entity_type: str
    entity_id: int
    content: str


@router.get("")
async def list_notes(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(Note).order_by(Note.created_at.desc())
    if entity_type:
        q = q.where(Note.entity_type == entity_type)
    if entity_id:
        q = q.where(Note.entity_id == entity_id)
    result = await db.execute(q)
    return [{"id": n.id, "entity_type": n.entity_type, "entity_id": n.entity_id, "content": n.content, "created_at": n.created_at} for n in result.scalars().all()]


@router.post("")
async def create_note(body: NoteIn, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    n = Note(**body.model_dump())
    db.add(n)
    await db.flush()
    return {"id": n.id, "content": n.content}


@router.delete("/{note_id}", status_code=204)
async def delete_note(note_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    n = result.scalar_one_or_none()
    if not n:
        raise HTTPException(404, "Note not found")
    await db.delete(n)
