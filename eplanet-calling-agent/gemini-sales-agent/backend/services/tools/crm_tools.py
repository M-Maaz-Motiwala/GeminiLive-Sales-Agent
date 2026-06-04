"""CRM tools — create_lead, search_contacts, create_note, update_lead_status."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Lead, Contact, Note, LeadStatus

logger = logging.getLogger(__name__)


async def create_lead(db: AsyncSession, params: dict) -> dict:
    session_id = params.get("source_session_id")
    lead = Lead(
        name=params.get("name", "Unknown"),
        email=params.get("email"),
        phone=params.get("phone"),
        company=params.get("company"),
        notes=params.get("notes"),
        status=LeadStatus.new,
        tags=params.get("tags", []),
        source_session_id=session_id,
    )
    db.add(lead)
    await db.flush()
    return {"status": "created", "lead_id": lead.id, "name": lead.name}


async def search_contacts(db: AsyncSession, params: dict) -> dict:
    query_str = params.get("query", "")
    result = await db.execute(
        select(Contact).where(
            or_(
                Contact.name.ilike(f"%{query_str}%"),
                Contact.email.ilike(f"%{query_str}%"),
                Contact.company.ilike(f"%{query_str}%"),
            )
        ).limit(5)
    )
    contacts = result.scalars().all()
    return {
        "results": [
            {"id": c.id, "name": c.name, "email": c.email, "phone": c.phone, "company": c.company}
            for c in contacts
        ]
    }


async def create_note(db: AsyncSession, params: dict, session_id: int = None) -> dict:
    entity_type = params.get("entity_type", "session")
    entity_id = params.get("entity_id") or session_id or 0
    note = Note(
        entity_type=entity_type,
        entity_id=entity_id,
        content=params.get("content", ""),
    )
    db.add(note)
    await db.flush()
    return {"status": "created", "note_id": note.id}


async def update_lead_status(db: AsyncSession, params: dict) -> dict:
    lead_id = params.get("lead_id")
    new_status = params.get("status", "contacted")
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        return {"error": f"Lead {lead_id} not found"}
    try:
        lead.status = LeadStatus(new_status)
    except ValueError:
        return {"error": f"Invalid status: {new_status}"}
    await db.flush()
    return {"status": "updated", "lead_id": lead.id, "new_status": lead.status}
