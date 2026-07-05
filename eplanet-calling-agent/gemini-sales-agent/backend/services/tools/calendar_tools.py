"""Calendar tool wrappers — called by tool_executor during live calls."""
import logging
from datetime import datetime, timedelta, date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from backend.services import google_calendar

logger = logging.getLogger(__name__)


def _parse_target_date(raw: Optional[str]) -> Optional[date]:
    """Parse a target_date param ("YYYY-MM-DD" or ISO datetime) into a date."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


async def find_next_available_slot(
    db: AsyncSession,
    user_id: int,
    params: dict,
) -> dict:
    """Find the next available meeting slot.

    Supports `target_date` ("YYYY-MM-DD") so the agent can ask for "tomorrow"
    or a specific day instead of always searching from now.
    """
    timezone_str = params.get("timezone", "UTC")
    preferred_after = params.get("preferred_after")
    duration_mins = int(params.get("duration_mins", 30))
    window_days = int(params.get("window_days", 7))
    business_hour_start = int(params.get("business_hour_start", 9))
    business_hour_end = int(params.get("business_hour_end", 18))
    target_date = _parse_target_date(params.get("target_date"))

    if preferred_after:
        after_dt = datetime.fromisoformat(preferred_after)
    else:
        after_dt = datetime.now()

    try:
        result = await google_calendar.find_next_available_slot(
            user_id=user_id,
            duration_mins=duration_mins,
            after_dt=after_dt,
            timezone_str=timezone_str,
            db=db,
            window_days=window_days,
            business_hour_start=business_hour_start,
            business_hour_end=business_hour_end,
            target_date=target_date,
        )
        if result:
            scope = f"on {target_date.isoformat()}" if target_date else "in the next window"
            return {
                "status": "found",
                "slot": result,
                "message": (
                    f"Found a {duration_mins}-minute slot from {result['start']} to "
                    f"{result['end']} ({timezone_str}) {scope}"
                ),
            }
        not_found_scope = f"on {target_date.isoformat()}" if target_date else f"in the next {window_days} days"
        return {
            "status": "not_found",
            "message": f"No available {duration_mins}-minute slot found {not_found_scope}",
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error("Calendar slot lookup failed: %s", e)
        return {"status": "error", "message": f"Calendar error: {e}"}


async def list_available_slots(
    db: AsyncSession,
    user_id: int,
    params: dict,
) -> dict:
    """List all available meeting slots for a day (or next N days)."""
    timezone_str = params.get("timezone", "UTC")
    duration_mins = int(params.get("duration_mins", 30))
    days_ahead = int(params.get("days_ahead", 7))
    business_hour_start = int(params.get("business_hour_start", 9))
    business_hour_end = int(params.get("business_hour_end", 18))
    target_date = _parse_target_date(params.get("target_date"))

    try:
        days = await google_calendar.list_available_slots(
            user_id=user_id,
            duration_mins=duration_mins,
            timezone_str=timezone_str,
            db=db,
            target_date=target_date,
            days_ahead=days_ahead,
            business_hour_start=business_hour_start,
            business_hour_end=business_hour_end,
        )
        # Flatten for easy consumption by the agent
        flat: list[dict] = []
        total = 0
        for day in days:
            for s in day["slots"]:
                flat.append({"date": day["date"], **s})
                total += 1
        scope = f"on {target_date.isoformat()}" if target_date else f"for the next {days_ahead} days"
        return {
            "status": "ok",
            "days": days,
            "slots": flat,
            "count": total,
            "message": f"Found {total} available {duration_mins}-min slot(s) {scope} ({timezone_str})",
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error("Calendar list slots failed: %s", e)
        return {"status": "error", "message": f"Calendar error: {e}"}


async def schedule_meeting(
    db: AsyncSession,
    user_id: int,
    params: dict,
) -> dict:
    """Book a meeting on the user's Google Calendar."""
    title = params.get("title", "Meeting")
    start_iso = params.get("start_iso")
    end_iso = params.get("end_iso")
    timezone_str = params.get("timezone", "UTC")
    attendee_email = params.get("attendee_email")

    if not start_iso or not end_iso:
        return {"status": "error", "message": "start_iso and end_iso are required"}

    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)

        result = await google_calendar.create_event(
            user_id=user_id,
            title=title,
            start=start,
            end=end,
            timezone_str=timezone_str,
            db=db,
            attendee_email=attendee_email,
        )
        return {
            "status": "scheduled",
            "event": result,
            "message": f"Meeting '{title}' scheduled from {start_iso} to {end_iso}",
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        logger.error("Calendar scheduling failed: %s", e)
        return {"status": "error", "message": f"Calendar error: {e}"}


async def cancel_meeting(
    db: AsyncSession,
    user_id: int,
    params: dict,
) -> dict:
    """Cancel a previously booked meeting."""
    event_id = params.get("event_id")
    if not event_id:
        return {"status": "error", "message": "event_id is required"}

    try:
        result = await google_calendar.delete_event(
            user_id=user_id,
            event_id=event_id,
            db=db,
        )
        return {"status": "cancelled", "message": f"Meeting {event_id} cancelled"}
    except Exception as e:
        logger.error("Calendar cancellation failed: %s", e)
        return {"status": "error", "message": f"Calendar error: {e}"}
