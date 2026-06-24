"""One-time: copy existing leads into the contacts directory."""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from backend.db.database import AsyncSessionLocal
from backend.db.models import Lead
from backend.services.tools.crm_tools import upsert_contact_from_lead


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Lead).order_by(Lead.id))
        leads = result.scalars().all()
        count = 0
        for lead in leads:
            contact = await upsert_contact_from_lead(db, lead)
            if contact:
                count += 1
        await db.commit()
        print(f"Synced {count} contact(s) from {len(leads)} lead(s).")


if __name__ == "__main__":
    asyncio.run(main())
