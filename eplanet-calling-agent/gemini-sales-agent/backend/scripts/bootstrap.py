"""One-shot bootstrap: migration, admin, agents, Pinecone index, RAG seed. Idempotent."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from backend.config import get_settings
from backend.scripts.create_admin import create_admin  # noqa: E402
from backend.scripts.migrate_add_extension import migrate  # noqa: E402
from backend.scripts.migrate_outbound import migrate as migrate_outbound  # noqa: E402
from backend.scripts.migrate_phase2 import migrate as migrate_phase2  # noqa: E402
from backend.scripts.seed_agents import seed_agents  # noqa: E402
from backend.scripts.seed_rag import seed_rag  # noqa: E402
from backend.services.rag_service import ensure_pinecone_index_async


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

    print("=== Bootstrap: agents (701-704) ===")
    await seed_agents()

    settings = get_settings()
    if settings.pinecone_api_key:
        print("=== Bootstrap: Pinecone index ===")
        try:
            name = await ensure_pinecone_index_async()
            print(f"Pinecone index ready: {name}")
        except Exception as exc:
            print(f"WARNING: Pinecone index setup failed: {exc}")
        print("=== Bootstrap: RAG seed documents ===")
        await seed_rag()
    else:
        print("PINECONE_API_KEY not set — skipping index + RAG seed.")

    print("Platform bootstrap complete.")


if __name__ == "__main__":
    asyncio.run(main())
