"""Ensure default Trango Tech organization exists and backfill org links."""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from sqlalchemy import select

from backend.db.database import AsyncSessionLocal, init_db
from backend.db.models import Agent, Document, Organization
from backend.services.asterisk_registry import sync_organizations_to_asterisk
from backend.services.phone_normalize import normalize_did

DEFAULT_ORG_NAME = os.getenv("DEFAULT_ORG_NAME", "Trango Tech")
DEFAULT_ORG_DID = normalize_did(os.getenv("DEFAULT_ORG_DID", "12107297915")) or "12107297915"


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", name.lower().strip()).strip("-") or "org"


async def _backfill_org_links(db, default_org: Organization) -> None:
    """Link legacy agents and global KB docs to organizations."""
    agents = (await db.execute(select(Agent).where(Agent.organization_id.is_(None)))).scalars().all()
    for agent in agents:
        did = normalize_did(agent.did or "") if agent.did else None
        if not did:
            agent.organization_id = default_org.id
            agent.did = default_org.did
            continue
        org = (await db.execute(select(Organization).where(Organization.did == did))).scalar_one_or_none()
        if not org:
            slug_base = _slugify(f"org-{did}")
            taken = {row[0] for row in (await db.execute(select(Organization.slug))).all()}
            slug = slug_base
            n = 2
            while slug in taken:
                slug = f"{slug_base}-{n}"
                n += 1
            org = Organization(
                name=f"Org {did}",
                slug=slug,
                did=did,
                is_active=True,
            )
            db.add(org)
            await db.flush()
            print(f"Created organization from agent DID: {did}")
        agent.organization_id = org.id
        agent.did = org.did
        print(f"Linked agent {agent.slug or agent.id} → {org.name}")

    docs = (
        await db.execute(
            select(Document).where(
                Document.organization_id.is_(None),
                Document.agent_id.is_(None),
            )
        )
    ).scalars().all()
    for doc in docs:
        doc.organization_id = default_org.id
        print(f"Assigned legacy global doc {doc.id} → {default_org.name}")


async def seed_organizations() -> Organization:
    await init_db()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Organization).where(Organization.did == DEFAULT_ORG_DID))
        org = result.scalar_one_or_none()
        if org:
            org.name = DEFAULT_ORG_NAME
            org.is_active = True
            print(f"Updated organization {org.name} ({org.did})")
        else:
            org = Organization(
                name=DEFAULT_ORG_NAME,
                slug="trango-tech",
                did=DEFAULT_ORG_DID,
                is_active=True,
            )
            db.add(org)
            await db.flush()
            print(f"Created organization {org.name} ({org.did})")

        await _backfill_org_links(db, org)
        await sync_organizations_to_asterisk(db)
        await db.commit()
        return org


if __name__ == "__main__":
    asyncio.run(seed_organizations())
