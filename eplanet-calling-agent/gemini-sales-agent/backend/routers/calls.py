from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.services import session_manager

router = APIRouter(prefix="/api/calls", tags=["calls"])


class OutboundCallRequest(BaseModel):
    endpoint: str          # e.g. "PJSIP/6001"
    agent_id: int = 1
    caller_id: Optional[str] = None


@router.post("/outbound")
async def outbound_call(body: OutboundCallRequest, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    try:
        from backend.services.asterisk_ari import ari_client
        call_id = await ari_client.originate(body.endpoint, body.agent_id)
        return {"status": "dialing", "call_id": call_id}
    except Exception as e:
        raise HTTPException(500, f"Outbound call failed: {e}")


@router.get("")
async def list_calls(_=Depends(get_current_user)):
    sessions = session_manager.all_sessions()
    return {
        "active_calls": len(sessions),
        "sessions": [{"session_id": sid} for sid in sessions.keys()],
    }


@router.delete("/{session_id}")
async def hangup(session_id: int, _=Depends(get_current_user)):
    session = session_manager.get(session_id)
    if not session:
        raise HTTPException(404, "Active session not found")
    await session.close()
    return {"status": "closed"}
