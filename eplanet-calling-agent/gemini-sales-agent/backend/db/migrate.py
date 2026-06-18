"""Lightweight idempotent schema patches (create_all does not alter existing tables)."""
from __future__ import annotations

from sqlalchemy import text

from backend.db.database import engine


_PATCHES = (
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS inbound_prompt_template TEXT",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS outbound_prompt_template TEXT",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS master_prompt_override TEXT",
    """CREATE TABLE IF NOT EXISTS platform_settings (
        key VARCHAR(255) PRIMARY KEY,
        value TEXT,
        updated_at TIMESTAMPTZ DEFAULT now()
    )""",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_profile JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS last_error TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS did VARCHAR(32)",
    "ALTER TYPE agenttype ADD VALUE IF NOT EXISTS 'support'",
    "CREATE INDEX IF NOT EXISTS ix_agents_did ON agents (did)",
)


async def apply_migrations() -> None:
    async with engine.begin() as conn:
        for stmt in _PATCHES:
            await conn.execute(text(stmt))
