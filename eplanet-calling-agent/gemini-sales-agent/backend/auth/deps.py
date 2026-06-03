from fastapi import Depends, HTTPException, status, WebSocket
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.auth.service import decode_token
from backend.db.database import get_db
from backend.db.models import User

bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    email = payload.get("sub")
    result = await db.execute(select(User).where(User.email == email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_ws_user(token: str, db: AsyncSession) -> User:
    """Extract user from a raw token string (used in WebSocket handshake)."""
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    email = payload.get("sub")
    result = await db.execute(select(User).where(User.email == email, User.is_active == True))
    return result.scalar_one_or_none()
