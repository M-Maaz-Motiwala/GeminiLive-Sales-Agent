from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import aiohttp
from urllib.parse import urlencode

from backend.auth.service import verify_password, create_access_token, create_refresh_token, decode_token
from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import User, UserRole
from backend.config import get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user or not user.hashed_password or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(
        access_token=create_access_token(user.email),
        refresh_token=create_refresh_token(user.email),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    email = payload.get("sub")
    result = await db.execute(select(User).where(User.email == email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return TokenResponse(
        access_token=create_access_token(user.email),
        refresh_token=create_refresh_token(user.email),
    )


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_approved": user.is_approved,
        "auth_provider": user.auth_provider,
        "google_picture": user.google_picture,
        "organization_id": user.organization_id,
        "designation": user.designation,
    }


# ── Google OAuth ────────────────────────────────────────────────────────────


@router.get("/google")
async def google_login():
    """Redirect user to Google OAuth consent screen."""
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth is not configured")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/google/callback")
async def google_callback(code: str, db: AsyncSession = Depends(get_db)):
    """Handle Google OAuth callback: exchange code, upsert user, return JWT.

    After token exchange, redirects to the frontend with JWT params in the URL
    so the SPA can capture them and store in localStorage.
    """
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=501, detail="Google OAuth is not configured")

    # Exchange code for tokens
    async with aiohttp.ClientSession() as session:
        token_resp = await session.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        })
        if token_resp.status != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange Google code")
        token_data = await token_resp.json()

        # Fetch user info
        userinfo_resp = await session.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        if userinfo_resp.status != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Google user info")
        userinfo = await userinfo_resp.json()

    google_id = userinfo["id"]
    email = userinfo.get("email", "")
    full_name = userinfo.get("name", "")
    picture = userinfo.get("picture", "")

    # Upsert user
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        # Check if a local user with same email exists
        result2 = await db.execute(select(User).where(User.email == email))
        user = result2.scalar_one_or_none()
        if user:
            # Link Google to existing local account
            user.google_id = google_id
            user.google_picture = picture
            if not user.full_name:
                user.full_name = full_name
        else:
            # Brand-new Google user — not approved until admin/org_head acts
            user = User(
                email=email,
                full_name=full_name,
                google_id=google_id,
                google_picture=picture,
                auth_provider="google",
                role=UserRole.user,
                is_approved=False,
                is_active=True,
            )
            db.add(user)
    else:
        # Update picture / name on subsequent logins
        user.google_picture = picture
        if full_name and not user.full_name:
            user.full_name = full_name

    await db.flush()
    await db.commit()

    access_token = create_access_token(user.email)
    refresh_token = create_refresh_token(user.email)

    # Redirect to frontend with tokens as query params (SPA captures them)
    frontend_url = settings.vite_api_url.rstrip("/")
    redirect_url = (
        f"{frontend_url}/auth/google/callback"
        f"?access_token={access_token}"
        f"&refresh_token={refresh_token}"
    )
    return RedirectResponse(redirect_url)
