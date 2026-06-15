"""Lightweight idempotent schema patches (create_all does not alter existing tables)."""
from __future__ import annotations

from sqlalchemy import text

from backend.db.database import engine


_PATCHES = (
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS inbound_prompt_template TEXT",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS outbound_prompt_template TEXT",
)


async def apply_migrations() -> None:
    async with engine.begin() as conn:
        for stmt in _PATCHES:
            await conn.execute(text(stmt))
