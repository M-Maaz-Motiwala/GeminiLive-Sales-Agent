from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Output

router = APIRouter(prefix="/api/outputs", tags=["outputs"])


@router.get("")
async def list_outputs(
    output_type: Optional[str] = None,
    session_id: Optional[int] = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    q = select(Output).order_by(Output.created_at.desc()).limit(limit)
    if output_type:
        q = q.where(Output.output_type == output_type)
    if session_id:
        q = q.where(Output.session_id == session_id)
    result = await db.execute(q)
    return [
        {"id": o.id, "session_id": o.session_id, "output_type": o.output_type,
         "content": o.content, "created_at": o.created_at}
        for o in result.scalars().all()
    ]


@router.get("/tools")
async def list_available_tools(_=Depends(get_current_user)):
    from backend.services.tool_executor import TOOL_DECLARATIONS
    return [{"name": t["name"], "description": t["description"]} for t in TOOL_DECLARATIONS]
