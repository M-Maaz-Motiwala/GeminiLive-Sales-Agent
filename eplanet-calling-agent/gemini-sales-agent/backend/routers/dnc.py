"""Do-not-call list for outbound compliance."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.deps import get_current_user
from backend.config import get_settings
from backend.db.database import get_db
from backend.db.models import DoNotCall
from backend.services.phone_utils import normalize_e164

router = APIRouter(prefix="/api/dnc", tags=["dnc"])
settings = get_settings()


class DncIn(BaseModel):
    phone: str
    reason: str | None = None


@router.get("")
async def list_dnc(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(DoNotCall).order_by(DoNotCall.created_at.desc()))
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "phone_e164": r.phone_e164,
            "reason": r.reason,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("", status_code=201)
async def add_dnc(
    body: DncIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    e164 = normalize_e164(body.phone, settings.outbound_default_country_code)
    if not e164:
        raise HTTPException(400, "Invalid phone number")
    existing = await db.execute(
        select(DoNotCall).where(DoNotCall.phone_e164 == e164)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Number already on DNC list")
    row = DoNotCall(phone_e164=e164, reason=body.reason)
    db.add(row)
    await db.flush()
    return {"id": row.id, "phone_e164": e164}


@router.delete("/{dnc_id}", status_code=204)
async def remove_dnc(
    dnc_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    row = await db.get(DoNotCall, dnc_id)
    if not row:
        raise HTTPException(404, "Not found")
    await db.delete(row)
