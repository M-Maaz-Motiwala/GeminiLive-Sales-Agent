"""Seed RAG documents from backend/seed_data/ for each fleet sales agent."""
import asyncio
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from sqlalchemy import select

from backend.config import get_settings
from backend.db.database import AsyncSessionLocal, init_db
from backend.db.models import Agent, Document, DocumentStatus

FLEET_SLUGS = (
    "sales-alex",
    "sales-jordan",
    "sales-morgan",
    "sales-casey",
    "sales-riley",
)

SHARED_KB_FILES = (
    "trangotech-services.txt",
    "cold-outbound-script.txt",
)

SEED_DIR = Path(__file__).resolve().parent.parent / "seed_data"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/app/uploads"))
SEED_NAME_PREFIX = "seed:"


async def seed_rag() -> None:
    settings = get_settings()
    if not settings.pinecone_api_key:
        print("PINECONE_API_KEY not set — skipping RAG seed (upload docs manually).")
        return

    await init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from backend.services.rag_service import ensure_pinecone_index_async

        index_name = await ensure_pinecone_index_async()
        print(f"Pinecone index ready: {index_name}")
    except Exception as exc:
        print(f"Pinecone index setup failed: {exc}")
        return

    async with AsyncSessionLocal() as db:
        for slug in FLEET_SLUGS:
            result = await db.execute(select(Agent).where(Agent.slug == slug))
            agent = result.scalar_one_or_none()
            if not agent:
                print(f"Agent {slug} not found; run seed_agents first")
                continue

            for filename in SHARED_KB_FILES:
                src = SEED_DIR / filename
                if not src.exists():
                    print(f"Seed file missing: {src}")
                    continue

                seed_name = f"{SEED_NAME_PREFIX}{filename}"
                existing = await db.execute(
                    select(Document).where(
                        Document.agent_id == agent.id,
                        Document.name == seed_name,
                    )
                )
                doc = existing.scalar_one_or_none()

                if doc is not None:
                    if doc.status == DocumentStatus.indexed and (doc.chunk_count or 0) > 0:
                        print(f"RAG doc already indexed: {filename} for {slug}")
                        continue
                    if doc.status == DocumentStatus.indexing:
                        print(f"RAG doc already indexing: {filename} for {slug}")
                        continue
                    if doc.status == DocumentStatus.pending:
                        from backend.services.document_indexer import index_document

                        index_document.delay(doc.id, doc.file_path, agent.id)
                        continue

                dest_name = f"seed_{agent.id}_{filename}"
                dest = UPLOAD_DIR / dest_name
                shutil.copy2(src, dest)

                if doc is not None and doc.status == DocumentStatus.failed:
                    doc.file_path = str(dest)
                    doc.file_size = dest.stat().st_size
                    doc.status = DocumentStatus.pending
                    doc.chunk_count = 0
                    await db.flush()
                    from backend.services.document_indexer import index_document

                    index_document.delay(doc.id, str(dest), agent.id)
                    print(f"Re-queued failed RAG doc: {filename} → {slug}")
                    continue

                doc = Document(
                    agent_id=agent.id,
                    name=seed_name,
                    original_filename=filename,
                    file_path=str(dest),
                    file_size=dest.stat().st_size,
                    status=DocumentStatus.pending,
                )
                db.add(doc)
                await db.flush()

                from backend.services.document_indexer import index_document

                index_document.delay(doc.id, str(dest), agent.id)
                print(f"Queued RAG indexing: {filename} → {slug}")

        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed_rag())
