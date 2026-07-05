"""Thin helpers for reading/writing PlatformSetting key-value pairs."""
import time
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import PlatformSetting

logger = logging.getLogger(__name__)

# Simple TTL cache (key → (value, timestamp))
_cache: dict[str, tuple[str | None, float]] = {}
_CACHE_TTL = 10  # seconds


async def get_platform_setting(
    key: str,
    db: AsyncSession,
    default: Optional[str] = None,
) -> Optional[str]:
    """Read a platform setting, with a 10-second TTL in-memory cache."""
    now = time.monotonic()
    if key in _cache:
        val, ts = _cache[key]
        if now - ts < _CACHE_TTL:
            return val if val is not None else default

    result = await db.execute(
        select(PlatformSetting.value).where(PlatformSetting.key == key)
    )
    row = result.scalar_one_or_none()
    _cache[key] = (row, now)
    return row if row is not None else default


async def set_platform_setting(
    key: str,
    value: str,
    db: AsyncSession,
) -> None:
    """Create or update a platform setting. Invalidates cache."""
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == key)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.value = value
    else:
        db.add(PlatformSetting(key=key, value=value))
    await db.flush()
    # Invalidate cache
    _cache.pop(key, None)
