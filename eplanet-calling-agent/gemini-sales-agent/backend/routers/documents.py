import os
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Agent, Document, DocumentStatus, Organization, User, UserRole
from backend.config import get_settings
from backend.services.data_scope import get_scope_filters, can_access_record

router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()
UPLOAD_DIR = "uploads"


def _out(d: Document, org_name: Optional[str] = None) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "original_filename": d.original_filename,
        "file_size": d.file_size,
        "status": d.status,
        "chunk_count": d.chunk_count,
        "retry_count": d.retry_count,
        "last_error": d.last_error,
        "last_attempt_at": d.last_attempt_at,
        "agent_id": d.agent_id,
        "organization_id": d.organization_id,
        "organization_name": org_name,
        "created_at": d.created_at,
        "indexed_at": d.indexed_at,
    }


async def _org_names(db: AsyncSession, org_ids: set[int]) -> dict[int, str]:
    if not org_ids:
        return {}
    result = await db.execute(select(Organization).where(Organization.id.in_(org_ids)))
    return {o.id: o.name for o in result.scalars()}


def _enforce_doc_org(user: User, org_id: Optional[int]) -> None:
    """Non-admins may only target their own organization."""
    if user.role == UserRole.admin:
        return
    if org_id is None or org_id != user.organization_id:
        raise HTTPException(403, "You can only manage documents in your own organization")


async def _enforce_agent_org(db: AsyncSession, user: User, agent_id: int) -> Agent:
    """Verify the agent belongs to the user's org (non-admins only)."""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if user.role != UserRole.admin and (
        agent.organization_id is None or agent.organization_id != user.organization_id
    ):
        raise HTTPException(403, "Agent does not belong to your organization")
    return agent


@router.get("")
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Document).order_by(Document.created_at.desc())
    for f in get_scope_filters(user, Document):
        q = q.where(f)
    result = await db.execute(q)
    docs = result.scalars().all()
    org_ids = {d.organization_id for d in docs if d.organization_id}
    names = await _org_names(db, org_ids)
    return [_out(d, names.get(d.organization_id or -1)) for d in docs]


@router.get("/summary")
async def documents_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = select(Document)
    for f in get_scope_filters(user, Document):
        q = q.where(f)
    result = await db.execute(q)
    docs = list(result.scalars().all())
    counts = {"total": len(docs), "indexed": 0, "indexing": 0, "pending": 0, "failed": 0}
    for d in docs:
        st = str(d.status.value if hasattr(d.status, "value") else d.status)
        if st in counts:
            counts[st] += 1
    counts["remaining"] = counts["pending"] + counts["failed"]
    return counts


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    agent_id: Optional[int] = Form(None),
    organization_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if agent_id is not None and agent_id <= 0:
        agent_id = None
    if organization_id is not None and organization_id <= 0:
        organization_id = None

    if agent_id is None and organization_id is None:
        raise HTTPException(400, "Select an organization or agent for this document")

    org = None
    if organization_id is not None:
        _enforce_doc_org(user, organization_id)
        org = await db.get(Organization, organization_id)
        if not org:
            raise HTTPException(400, "Organization not found")

    # If an agent is selected, verify it belongs to the user's org and derive
    # the document's organization from the agent.
    if agent_id is not None:
        agent = await _enforce_agent_org(db, user, agent_id)
        if organization_id is None:
            organization_id = agent.organization_id
            org = await db.get(Organization, organization_id) if organization_id else None

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
        organization_id=organization_id if agent_id is None else None,
        status=DocumentStatus.pending,
    )
    db.add(doc)
    await db.flush()

    try:
        from backend.services.document_indexer import index_document
        index_document.delay(doc.id, file_path, agent_id, organization_id=doc.organization_id)
    except Exception:
        doc.status = DocumentStatus.failed

    org_name = None
    if doc.organization_id:
        org = await db.get(Organization, doc.organization_id)
        org_name = org.name if org else None
    return _out(doc, org_name)


async def _queue_index(doc: Document):
    from backend.services.document_indexer import index_document
    index_document.delay(doc.id, doc.file_path, doc.agent_id, organization_id=doc.organization_id)


@router.post("/{doc_id}/retry")
async def retry_document(doc_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "Document not found")
    if not can_access_record(user, d):
        raise HTTPException(403, "Access denied")
    if d.status == DocumentStatus.indexing:
        return {"status": "already_indexing", "doc_id": d.id}
    d.status = DocumentStatus.pending
    await db.flush()
    await _queue_index(d)
    return {"status": "queued", "doc_id": d.id}


@router.post("/retry-remaining")
async def retry_remaining_documents(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(Document).where(Document.status.in_([DocumentStatus.pending, DocumentStatus.failed]))
    for f in get_scope_filters(user, Document):
        q = q.where(f)
    result = await db.execute(q)
    docs = list(result.scalars().all())
    queued = 0
    for d in docs:
        d.status = DocumentStatus.pending
        await _queue_index(d)
        queued += 1
    return {"status": "queued", "count": queued}


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Document).where(Document.id == doc_id))
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "Document not found")
    if not can_access_record(user, d):
        raise HTTPException(403, "Access denied")
    try:
        from backend.services import rag_service
        await rag_service.delete_document_vectors(
            d.id, d.agent_id, organization_id=d.organization_id
        )
    except Exception:
        pass
    if os.path.exists(d.file_path):
        os.remove(d.file_path)
    await db.delete(d)


@router.get("/tools")
async def list_available_tools(_=Depends(get_current_user)):
    from backend.services.tool_executor import TOOL_DECLARATIONS
    return [{"name": t["name"], "description": t["description"]} for t in TOOL_DECLARATIONS]