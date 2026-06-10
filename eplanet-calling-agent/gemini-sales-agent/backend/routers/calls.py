from fastapi import APIRouter, Depends, HTTPException

from backend.auth.deps import get_current_user
from backend.services import session_manager

router = APIRouter(prefix="/api/calls", tags=["calls"])


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
