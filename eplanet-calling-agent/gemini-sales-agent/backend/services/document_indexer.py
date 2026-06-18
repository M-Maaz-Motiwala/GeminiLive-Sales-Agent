"""Celery task: extract text from documents, chunk, embed, and upsert to Pinecone."""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from backend.celery_app import celery_app
from backend.config import get_settings
from backend.services import rag_service

logger = logging.getLogger(__name__)
settings = get_settings()

CHUNK_SIZE = 500       # tokens ≈ characters / 4
CHUNK_OVERLAP = 50


def _extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        try:
            import PyPDF2
            text = []
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text.append(page.extract_text() or "")
            return "\n".join(text)
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return ""
    elif ext in (".docx", ".doc"):
        try:
            import docx
            doc = docx.Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            logger.error(f"DOCX extraction failed: {e}")
            return ""
    else:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Text extraction failed: {e}")
            return ""


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


@celery_app.task(bind=True, max_retries=3)
def index_document(
    self,
    doc_id: int,
    file_path: str,
    agent_id: Optional[int],
    organization_id: Optional[int] = None,
):
    """Extract, chunk, embed, and upsert a document to Pinecone."""

    async def _run():
        from sqlalchemy import select

        from backend.db.database import AsyncSessionLocal, engine
        from backend.db.models import Document, DocumentStatus

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Document).where(Document.id == doc_id))
                doc = result.scalar_one_or_none()
                if not doc:
                    logger.error("Document %d not found", doc_id)
                    return

                if doc.status == DocumentStatus.indexed and doc.chunk_count > 0:
                    logger.info(
                        "Document %d already indexed (%d chunks); skipping",
                        doc_id,
                        doc.chunk_count,
                    )
                    return

                doc.status = DocumentStatus.indexing
                doc.last_attempt_at = datetime.now(timezone.utc)
                doc.last_error = None
                await db.commit()

                try:
                    text = _extract_text(file_path)
                    if not text.strip():
                        raise ValueError("No text extracted from document")

                    chunks = _chunk_text(text)
                    logger.info("Document %d: %d chunks extracted", doc_id, len(chunks))

                    count = await rag_service.upsert_chunks(
                        doc_id,
                        agent_id,
                        chunks,
                        organization_id=doc.organization_id or organization_id,
                    )
                    if count == 0:
                        raise ValueError("No vectors upserted to Pinecone")

                    doc.status = DocumentStatus.indexed
                    doc.chunk_count = count
                    doc.indexed_at = datetime.now(timezone.utc)
                    doc.last_error = None
                    await db.commit()
                    logger.info("Document %d indexed: %d vectors", doc_id, count)

                except Exception as e:
                    logger.error("Document %d indexing failed: %s", doc_id, e)
                    doc.status = DocumentStatus.failed
                    doc.retry_count = int(doc.retry_count or 0) + 1
                    doc.last_error = str(e)
                    await db.commit()
                    raise self.retry(exc=e, countdown=60) from e
        finally:
            # Celery prefork workers run many tasks per process; asyncpg
            # connections must not be reused across closed event loops.
            await engine.dispose()

    asyncio.run(_run())
