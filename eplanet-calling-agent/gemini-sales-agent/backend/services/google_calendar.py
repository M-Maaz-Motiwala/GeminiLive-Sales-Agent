"""Google Calendar Service — per-user OAuth, event CRUD, slot finding."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.config import get_settings
from backend.db.models import GoogleCalendarToken

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    key = get_settings().calendar_encryption_key
    if not key:
        raise RuntimeError("calendar_encryption_key is not configured")
    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


async def store_tokens(
    user_id: int,
    access_token: str,
    refresh_token: str,
    token_expiry: Optional[datetime],
    calendar_id: str,
    db: AsyncSession,
) -> GoogleCalendarToken:
    """Encrypt and persist OAuth tokens for a user."""
    result = await db.execute(
        select(GoogleCalendarToken).where(GoogleCalendarToken.user_id == user_id)
    )
    existing = result.scalar_one_or_none()

    enc_access = _encrypt(access_token)
    enc_refresh = _encrypt(refresh_token)

    if existing:
        existing.access_token = enc_access
        existing.refresh_token = enc_refresh
        existing.token_expiry = token_expiry
        existing.calendar_id = calendar_id
        return existing

    token = GoogleCalendarToken(
        user_id=user_id,
        access_token=enc_access,
        refresh_token=enc_refresh,
        token_expiry=token_expiry,
        calendar_id=calendar_id,
    )
    db.add(token)
    await db.flush()
    return token


async def get_credentials(user_id: int, db: AsyncSession) -> dict:
    """Load + decrypt credentials. Returns dict with access_token, refresh_token, expiry."""
    result = await db.execute(
        select(GoogleCalendarToken).where(GoogleCalendarToken.user_id == user_id)
    )
    token = result.scalar_one_or_none()
    if not token:
        raise ValueError("Google Calendar not connected for this user")

    return {
        "access_token": _decrypt(token.access_token),
        "refresh_token": _decrypt(token.refresh_token),
        "token_expiry": token.token_expiry,
        "calendar_id": token.calendar_id or "primary",
    }


async def _build_service(user_id: int, db: AsyncSession):
    """Build a Google Calendar API service client with the user's credentials."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds_data = await get_credentials(user_id, db)
    settings = get_settings()

    creds = Credentials(
        token=creds_data["access_token"],
        refresh_token=creds_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
    )

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        import google.auth.transport.requests
        creds.refresh(google.auth.transport.requests.Request())
        # Persist refreshed token
        await store_tokens(
            user_id=user_id,
            access_token=creds.token,
            refresh_token=creds.refresh_token,
            token_expiry=creds.expiry,
            calendar_id=creds_data["calendar_id"],
            db=db,
        )

    return build("calendar", "v3", credentials=creds), creds_data["calendar_id"]


async def list_events(
    user_id: int,
    start: datetime,
    end: datetime,
    db: AsyncSession,
) -> list[dict]:
    """List calendar events in a time range."""
    service, calendar_id = await _build_service(user_id, db)

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = []
    for ev in events_result.get("items", []):
        start_dt = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
        end_dt = ev.get("end", {}).get("dateTime", ev.get("end", {}).get("date", ""))
        events.append({
            "id": ev.get("id"),
            "summary": ev.get("summary", ""),
            "start": start_dt,
            "end": end_dt,
            "status": ev.get("status", ""),
        })
    return events


async def check_availability(
    user_id: int,
    start: datetime,
    end: datetime,
    db: AsyncSession,
) -> bool:
    """Check if a time slot is free (no overlapping events)."""
    events = await list_events(user_id, start, end, db)
    return len(events) == 0


async def create_event(
    user_id: int,
    title: str,
    start: datetime,
    end: datetime,
    timezone_str: str,
    db: AsyncSession,
    attendee_email: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """Create a calendar event."""
    service, calendar_id = await _build_service(user_id, db)

    event_body = {
        "summary": title,
        "start": {"dateTime": start.isoformat(), "timeZone": timezone_str},
        "end": {"dateTime": end.isoformat(), "timeZone": timezone_str},
    }
    if description:
        event_body["description"] = description
    if attendee_email:
        event_body["attendees"] = [{"email": attendee_email}]

    created = service.events().insert(calendarId=calendar_id, body=event_body).execute()
    return {
        "event_id": created["id"],
        "html_link": created.get("htmlLink", ""),
        "summary": created.get("summary", ""),
        "start": created["start"].get("dateTime", ""),
        "end": created["end"].get("dateTime", ""),
    }


async def update_event(
    user_id: int,
    event_id: str,
    db: AsyncSession,
    **kwargs,
) -> dict:
    """Update an existing calendar event."""
    service, calendar_id = await _build_service(user_id, db)

    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    if "title" in kwargs:
        event["summary"] = kwargs["title"]
    if "start" in kwargs and "timezone" in kwargs:
        event["start"] = {"dateTime": kwargs["start"].isoformat(), "timeZone": kwargs["timezone"]}
    if "end" in kwargs and "timezone" in kwargs:
        event["end"] = {"dateTime": kwargs["end"].isoformat(), "timeZone": kwargs["timezone"]}

    updated = service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
    return {"event_id": updated["id"], "status": "updated"}


async def delete_event(
    user_id: int,
    event_id: str,
    db: AsyncSession,
) -> dict:
    """Delete a calendar event."""
    service, calendar_id = await _build_service(user_id, db)
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    return {"event_id": event_id, "status": "deleted"}


def _round_up_30min(dt: datetime) -> datetime:
    """Round a datetime up to the next 30-minute boundary."""
    dt = dt.replace(second=0, microsecond=0)
    if dt.minute % 30 == 0:
        return dt
    if dt.minute < 30:
        return dt.replace(minute=30)
    return dt.replace(minute=0) + timedelta(hours=1)


def _day_window(day_date, tz, bh_start: int, bh_end: int) -> tuple[datetime, datetime]:
    """Return the [start, end) business-hours window for a given date in tz."""
    return (
        datetime(day_date.year, day_date.month, day_date.day, bh_start, 0, tzinfo=tz),
        datetime(day_date.year, day_date.month, day_date.day, bh_end, 0, tzinfo=tz),
    )


def _parse_busy(events: list[dict]) -> list[tuple[datetime, datetime]]:
    """Parse event dicts into sorted busy intervals."""
    busy = []
    for ev in events:
        try:
            ev_start = datetime.fromisoformat(ev["start"])
            ev_end = datetime.fromisoformat(ev["end"])
            if ev_start.tzinfo is None:
                continue
            busy.append((ev_start, ev_end))
        except (ValueError, KeyError):
            continue
    busy.sort(key=lambda x: x[0])
    return busy


def _find_slots_in_day(
    day_start: datetime,
    day_end: datetime,
    slot_duration: timedelta,
    busy: list[tuple[datetime, datetime]],
    earliest_start: datetime | None = None,
    max_slots: int = 0,
) -> list[dict]:
    """Find free slots within a single day window."""
    slots: list[dict] = []
    tz = day_start.tzinfo

    lower = day_start
    if earliest_start is not None:
        lower = max(day_start, earliest_start)
    candidate = _round_up_30min(lower)

    while candidate + slot_duration <= day_end:
        slot_end = candidate + slot_duration
        conflict = False
        for b_start, b_end in busy:
            if candidate < b_end and slot_end > b_start:
                conflict = True
                candidate = _round_up_30min(b_end)
                break
        if not conflict:
            slots.append({
                "start": candidate.isoformat(),
                "end": slot_end.isoformat(),
                "timezone": str(tz),
            })
            if max_slots and len(slots) >= max_slots:
                return slots
            candidate = _round_up_30min(slot_end)
    return slots


async def find_next_available_slot(
    user_id: int,
    duration_mins: int,
    after_dt: datetime,
    timezone_str: str,
    db: AsyncSession,
    window_days: int = 7,
    business_hour_start: int = 9,
    business_hour_end: int = 18,
    target_date=None,
) -> Optional[dict]:
    """Find the next available slot of `duration_mins` minutes.

    If `target_date` (a `date` object or ISO "YYYY-MM-DD" string) is provided,
    the search is restricted to that single day. Otherwise it scans
    `window_days` days from `after_dt`. Business hours are configurable.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone_str)
    search_start = after_dt.astimezone(tz)

    if target_date is not None:
        if isinstance(target_date, str):
            target = datetime.fromisoformat(target_date).date()
        else:
            target = target_date
        days_to_scan = [target]
        window_start = datetime(target.year, target.month, target.day, 0, 0, tzinfo=tz)
        window_end = window_start + timedelta(days=1)
    else:
        window_start = search_start
        window_end = search_start + timedelta(days=window_days)
        days_to_scan = []
        d = search_start.date()
        end_d = window_end.date()
        while d <= end_d:
            days_to_scan.append(d)
            d += timedelta(days=1)

    events = await list_events(user_id, window_start, window_end, db)
    busy = _parse_busy(events)
    slot_duration = timedelta(minutes=duration_mins)

    for day_date in days_to_scan:
        day_start, day_end = _day_window(day_date, tz, business_hour_start, business_hour_end)
        earliest = search_start if (target_date is None and day_date == search_start.date()) else None
        slots = _find_slots_in_day(
            day_start, day_end, slot_duration, busy,
            earliest_start=earliest, max_slots=1,
        )
        if slots:
            slots[0]["duration_mins"] = duration_mins
            return slots[0]
    return None


async def list_available_slots(
    user_id: int,
    duration_mins: int,
    timezone_str: str,
    db: AsyncSession,
    target_date=None,
    days_ahead: int = 7,
    business_hour_start: int = 9,
    business_hour_end: int = 18,
    max_slots_per_day: int = 12,
) -> list[dict]:
    """List ALL available slots of `duration_mins` minutes.

    If `target_date` (ISO date or `date` object) is provided, only that day is
    scanned. Otherwise the next `days_ahead` days from now are scanned.
    Returns one entry per day with a list of free slots in business hours.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone_str)
    now = datetime.now(tz)

    if target_date is not None:
        if isinstance(target_date, str):
            target = datetime.fromisoformat(target_date).date()
        else:
            target = target_date
        days_to_scan = [target]
        window_start = datetime(target.year, target.month, target.day, 0, 0, tzinfo=tz)
        window_end = window_start + timedelta(days=1)
    else:
        days_to_scan = []
        d = now.date()
        for _ in range(days_ahead):
            days_to_scan.append(d)
            d += timedelta(days=1)
        window_start = now
        window_end = now + timedelta(days=days_ahead)

    events = await list_events(user_id, window_start, window_end, db)
    busy = _parse_busy(events)
    slot_duration = timedelta(minutes=duration_mins)

    all_days: list[dict] = []
    for day_date in days_to_scan:
        day_start, day_end = _day_window(day_date, tz, business_hour_start, business_hour_end)
        earliest = now if day_date == now.date() else None
        day_slots = _find_slots_in_day(
            day_start, day_end, slot_duration, busy,
            earliest_start=earliest, max_slots=max_slots_per_day,
        )
        all_days.append({"date": day_date.isoformat(), "slots": day_slots})
    return all_days


async def disconnect(user_id: int, db: AsyncSession) -> dict:
    """Revoke and delete stored calendar tokens."""
    result = await db.execute(
        select(GoogleCalendarToken).where(GoogleCalendarToken.user_id == user_id)
    )
    token = result.scalar_one_or_none()
    if not token:
        return {"status": "not_connected"}

    # Try to revoke the token
    try:
        import aiohttp
        access_token = _decrypt(token.access_token)
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"https://oauth2.googleapis.com/revoke?token={access_token}"
            )
    except Exception as e:
        logger.warning("Failed to revoke Google Calendar token: %s", e)

    await db.delete(token)
    await db.flush()
    return {"status": "disconnected"}
