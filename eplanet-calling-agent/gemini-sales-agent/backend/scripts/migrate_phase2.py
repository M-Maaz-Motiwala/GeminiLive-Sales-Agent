"""Idempotent migration: Phase 2 outbound tables + leads.phone_e164."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from sqlalchemy import text

from backend.db.database import engine

_STATEMENTS = [
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS phone_e164 VARCHAR(20)",
    "CREATE INDEX IF NOT EXISTS ix_leads_phone_e164 ON leads (phone_e164)",
    """
    CREATE TABLE IF NOT EXISTS dnc_list (
        id SERIAL PRIMARY KEY,
        phone_e164 VARCHAR(20) NOT NULL UNIQUE,
        reason VARCHAR(255),
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    DO $body$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'campaignstatus') THEN
            CREATE TYPE campaignstatus AS ENUM ('draft', 'running', 'paused', 'completed');
        END IF;
    END
    $body$
    """,
    """
    DO $body$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'campaignleadstatus') THEN
            CREATE TYPE campaignleadstatus AS ENUM (
                'pending', 'dialing', 'completed', 'failed', 'skipped'
            );
        END IF;
    END
    $body$
    """,
    """
    CREATE TABLE IF NOT EXISTS campaigns (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        agent_id INTEGER NOT NULL REFERENCES agents(id),
        status campaignstatus NOT NULL DEFAULT 'draft',
        description TEXT,
        meta JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS campaign_leads (
        id SERIAL PRIMARY KEY,
        campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
        endpoint VARCHAR(255),
        status campaignleadstatus NOT NULL DEFAULT 'pending',
        session_id INTEGER REFERENCES sessions(id),
        last_error TEXT,
        dialed_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
]


async def migrate() -> None:
    async with engine.begin() as conn:
        for stmt in _STATEMENTS:
            await conn.execute(text(stmt))
    print("Migration complete: Phase 2 outbound CRM tables")


if __name__ == "__main__":
    asyncio.run(migrate())
