"""One-shot bootstrap: migration, admin, agents. Idempotent.

Knowledge base / RAG seeding is intentionally NOT run here — upload and index
documents manually from the admin UI after bootstrap.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from backend.scripts.create_admin import create_admin  # noqa: E402
from backend.scripts.migrate_add_extension import migrate  # noqa: E402
from backend.scripts.migrate_outbound import migrate as migrate_outbound  # noqa: E402
from backend.scripts.migrate_phase2 import migrate as migrate_phase2  # noqa: E402
from backend.scripts.seed_agents import seed_agents  # noqa: E402


async def main() -> None:
    email = os.getenv("ADMIN_EMAIL", "admin@aura.ai")
    password = os.getenv("ADMIN_PASSWORD", "changeme123")
    full_name = os.getenv("ADMIN_NAME", "Admin")

    print("=== Bootstrap: database migration ===")
    await migrate()
    await migrate_outbound()
    await migrate_phase2()

    print("=== Bootstrap: admin user ===")
    await create_admin(email, password, full_name)

    print("=== Bootstrap: default organization ===")
    from backend.scripts.seed_organizations import seed_organizations
    await seed_organizations()

    print("=== Bootstrap: sales fleet agents (2) ===")
    await seed_agents()

    print("Knowledge base seeding skipped — upload documents manually from the admin UI.")
    print("Platform bootstrap complete.")


if __name__ == "__main__":
    asyncio.run(main())
