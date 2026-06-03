"""Idempotent migration: add agents.inbound_extension column."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from sqlalchemy import text

from backend.db.database import engine


async def migrate() -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "ALTER TABLE agents ADD COLUMN IF NOT EXISTS "
                "inbound_extension VARCHAR(10)"
            )
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_agents_inbound_extension "
                "ON agents (inbound_extension) WHERE inbound_extension IS NOT NULL"
            )
        )
    print("Migration complete: agents.inbound_extension")


if __name__ == "__main__":
    asyncio.run(migrate())
