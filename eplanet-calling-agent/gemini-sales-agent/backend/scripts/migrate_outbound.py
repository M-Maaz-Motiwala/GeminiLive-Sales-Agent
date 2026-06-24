"""Idempotent migration: PostgreSQL enum values for outbound Phase 1."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from sqlalchemy import text

from backend.db.database import engine

_ENUM_ADDITIONS = (
    ("agenttype", "outbound_sales"),
    ("channeltype", "outbound"),
    ("outputtype", "call_disposition"),
)


async def migrate() -> None:
    async with engine.begin() as conn:
        for type_name, value in _ENUM_ADDITIONS:
            await conn.execute(
                text(
                    f"""
                    DO $body$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_enum e
                            JOIN pg_type t ON e.enumtypid = t.oid
                            WHERE t.typname = '{type_name}' AND e.enumlabel = '{value}'
                        ) THEN
                            ALTER TYPE {type_name} ADD VALUE '{value}';
                        END IF;
                    END
                    $body$;
                    """
                )
            )
    print("Migration complete: outbound enum values")


if __name__ == "__main__":
    asyncio.run(migrate())
