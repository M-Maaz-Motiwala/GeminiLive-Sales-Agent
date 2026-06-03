import os
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Document, DocumentStatus
from backend.config import get_settings

router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()
UPLOAD_DIR = "uploads"


def _out(d: Document) -> dict:
    return {"id": d.id, "name": d.name, "original_filename": d.original_filename,
            "file_size": d.file_size, "status": d.status, "chunk_count": d.chunk_count,
            "agent_id": d.agent_id, "created_at": d.created_at, "indexed_at": d.indexed_at}


@router.get("")
async def list_documents(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    return [_out(d) for d in result.scalars().all()]


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    agent_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = os.path.basename(file.filename)
    file_path = os.path.join(UPLOAD_DIR, f"{id(file)}_{safe_name}")

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = os.path.getsize(file_path)
    doc = Document(
        name=name or safe_name,
        original_filename=safe_name,
        file_path=file_path,
        file_size=file_size,
        agent_id=agent_id,
        status=DocumentStatus.pending,
    )
    db.add(doc)
    await db.flush()

    # Trigger async indexing via Celery
    try:
        from backend.services.document_indexer import index_document
        index_document.delay(doc.id, file_path, agent_id)
    except Exception as e:
        doc.status = DocumentStatus.failed

    return _out(doc)


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "Document not found")
    # Delete vectors from Pinecone
    try:
        from backend.services import rag_service
        await rag_service.delete_document_vectors(d.id, d.agent_id)
    except Exception:
        pass
    if os.path.exists(d.file_path):
        os.remove(d.file_path)
    await db.delete(d)


@router.get("/tools")
async def list_available_tools(_=Depends(get_current_user)):
    from backend.services.tool_executor import TOOL_DECLARATIONS
    return [{"name": t["name"], "description": t["description"]} for t in TOOL_DECLARATIONS]
