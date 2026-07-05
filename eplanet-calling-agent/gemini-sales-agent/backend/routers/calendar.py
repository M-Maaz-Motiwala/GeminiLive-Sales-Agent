"""Google Calendar OAuth endpoints — per-user calendar connection management."""
from datetime import datetime
from urllib.parse import urlencode

import aiohttp
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.deps import get_current_user
from backend.auth.service import create_state_token, decode_token
from backend.config import get_settings
from backend.db.database import get_db
from backend.db.models import User, UserRole
from backend.services import google_calendar

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Calendar scope — read/write events
CALENDAR_SCOPES = "https://www.googleapis.com/auth/calendar"

# Distinct type claim so a login access JWT cannot be replayed as calendar state.
CALENDAR_STATE_TYPE = "calendar_oauth_state"


@router.get("/auth")
async def calendar_auth(user: User = Depends(get_current_user)):
    """Return the Google Calendar OAuth consent URL with a signed `state`.

    The frontend fetches this endpoint with the bearer Authorization header
    (which a top-level browser navigation cannot do), then navigates the user
    to the returned URL. The signed state binds the consent flow to the
    authenticated user without leaking the JWT into the URL/history.
    """
    settings = get_settings()
    if not settings.google_client_id:
        raise HTTPException(501, "Google OAuth is not configured")

    state = create_state_token(user.email, token_type=CALENDAR_STATE_TYPE, expires_minutes=5)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.calendar_redirect_uri,
        "response_type": "code",
        "scope": CALENDAR_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return {"authorize_url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}"}


@router.get("/callback")
async def calendar_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google Calendar OAuth callback — store encrypted tokens.

    `state` is a short-lived signed JWT issued by `/auth`. We verify its
    signature, type, and expiry to re-derive the authenticated user instead
    of trusting a raw user_id in the query string.
    """
    settings = get_settings()

    payload = decode_token(state)
    if (
        not payload
        or payload.get("type") != CALENDAR_STATE_TYPE
        or payload.get("sub") is None
    ):
        raise HTTPException(400, "Invalid or expired OAuth state")

    email = payload["sub"]
    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(400, "User not found for OAuth state")
    user_id = user.id

    # Exchange code for tokens
    async with aiohttp.ClientSession() as session:
        token_resp = await session.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.calendar_redirect_uri,
            "grant_type": "authorization_code",
        })
        if token_resp.status != 200:
            raise HTTPException(400, "Failed to exchange Google Calendar code")
        token_data = await token_resp.json()

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token", "")

    # Parse expiry
    expires_in = token_data.get("expires_in")
    token_expiry = None
    if expires_in:
        from datetime import timedelta, timezone
        token_expiry = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))

    # Get the user's primary calendar email
    calendar_id = "primary"
    try:
        async with aiohttp.ClientSession() as session:
            cal_resp = await session.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if cal_resp.status == 200:
                cal_data = await cal_resp.json()
                calendar_id = cal_data.get("id", "primary")
    except Exception:
        pass

    await google_calendar.store_tokens(
        user_id=user_id,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expiry=token_expiry,
        calendar_id=calendar_id,
        db=db,
    )
    await db.commit()

    # Redirect back to frontend calendar settings page
    frontend_url = settings.vite_api_url.rstrip("/")
    return RedirectResponse(f"{frontend_url}/admin/settings?calendar=connected")


@router.get("/status")
async def calendar_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if the current user has a connected Google Calendar."""
    try:
        creds = await google_calendar.get_credentials(user.id, db)
        return {
            "connected": True,
            "calendar_id": creds["calendar_id"],
        }
    except ValueError:
        return {"connected": False, "calendar_id": None}


@router.get("/slots")
async def get_available_slots(
    after: str | None = None,
    days: int = 7,
    timezone: str = "UTC",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List next available 30-minute meeting slots."""
    from datetime import timedelta, timezone as tz_mod

    after_dt = datetime.fromisoformat(after) if after else datetime.now(tz_mod.utc)

    slots = []
    result = await google_calendar.find_next_available_slot(
        user_id=user.id,
        duration_mins=30,
        after_dt=after_dt,
        timezone_str=timezone,
        db=db,
        window_days=days,
    )
    if result:
        slots.append(result)
    return {"slots": slots}


@router.delete("/disconnect")
async def disconnect_calendar(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke and remove stored Google Calendar tokens."""
    result = await google_calendar.disconnect(user.id, db)
    await db.commit()
    return result
