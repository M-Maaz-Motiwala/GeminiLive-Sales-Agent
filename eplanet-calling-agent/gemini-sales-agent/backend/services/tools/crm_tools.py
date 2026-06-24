"""CRM tools — create/search/update leads, notes, and statuses."""
import logging
from datetime import datetime, timezone

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.db.models import Lead, Contact, Note, LeadStatus, Session as DBSession, Agent
from backend.services.phone_utils import normalize_e164

logger = logging.getLogger(__name__)
settings = get_settings()


LEAD_PROFILE_FIELDS = (
    "industry",
    "service_required",
    "budget",
    "timeline",
    "preferred_meeting_time",
    "requirement",
    "recommended_service_package",
    "key_features",
    "decision_maker_status",
    "objections_concerns",
    "lead_temperature",
    "recommended_next_step",
)


def _norm_str(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _merge_unique(existing, incoming) -> list[str]:
    out: list[str] = []
    for item in (existing or []):
        s = _norm_str(item)
        if s and s not in out:
            out.append(s)
    if isinstance(incoming, str):
        incoming = [incoming]
    for item in (incoming or []):
        s = _norm_str(item)
        if s and s not in out:
            out.append(s)
    return out


def _extract_profile(params: dict, existing: dict | None = None) -> dict:
    profile = dict(existing or {})
    for field in LEAD_PROFILE_FIELDS:
        if field not in params or params.get(field) is None:
            continue
        if field in {"key_features", "objections_concerns"}:
            profile[field] = _merge_unique(profile.get(field), params.get(field))
        else:
            val = _norm_str(params.get(field))
            if val:
                profile[field] = val
    return profile


async def _org_id_for_session(db: AsyncSession, session_id: int | None) -> int | None:
    if not session_id:
        return None
    sess = await db.get(DBSession, session_id)
    if not sess:
        return None
    meta = sess.meta or {}
    oid = meta.get("organization_id")
    if oid is not None:
        try:
            return int(oid)
        except (TypeError, ValueError):
            pass
    if sess.agent_id:
        agent = await db.get(Agent, sess.agent_id)
        if agent and agent.organization_id:
            return agent.organization_id
    return None


async def upsert_contact_from_lead(db: AsyncSession, lead: Lead) -> Contact | None:
    """Mirror captured leads into the contacts directory for the CRM UI."""
    name = (lead.name or "").strip()
    if not name:
        return None
    phone = (lead.phone or "").strip() or None
    email = (lead.email or "").strip() or None
    existing: Contact | None = None
    if phone:
        result = await db.execute(
            select(Contact).where(Contact.phone == phone).order_by(Contact.id.desc()).limit(1)
        )
        existing = result.scalar_one_or_none()
    if existing is None and email:
        result = await db.execute(
            select(Contact).where(Contact.email == email).order_by(Contact.id.desc()).limit(1)
        )
        existing = result.scalar_one_or_none()
    if existing:
        existing.name = name
        if phone:
            existing.phone = phone
        if email:
            existing.email = email
        if lead.company:
            existing.company = lead.company
        if lead.notes:
            existing.notes = lead.notes
        if lead.organization_id:
            existing.organization_id = lead.organization_id
        await db.flush()
        return existing
    contact = Contact(
        name=name,
        email=email,
        phone=phone,
        company=lead.company,
        notes=lead.notes,
        tags=lead.tags or [],
        organization_id=lead.organization_id,
    )
    db.add(contact)
    await db.flush()
    return contact


async def create_lead(db: AsyncSession, params: dict) -> dict:
    session_id = params.get("source_session_id")
    organization_id = await _org_id_for_session(db, session_id)
    lead_profile = _extract_profile(params)
    phone = params.get("phone")
    phone_e164 = None
    if phone:
        phone_e164 = normalize_e164(str(phone), settings.outbound_default_country_code)
    lead = Lead(
        name=params.get("name", "Unknown"),
        email=params.get("email"),
        phone=phone,
        phone_e164=phone_e164,
        company=params.get("company"),
        notes=params.get("notes"),
        lead_profile=lead_profile,
        status=LeadStatus.new,
        tags=params.get("tags", []),
        source_session_id=session_id,
        organization_id=organization_id,
    )
    db.add(lead)
    await db.flush()
    contact = await upsert_contact_from_lead(db, lead)
    out: dict = {"status": "created", "lead_id": lead.id, "name": lead.name}
    if contact:
        out["contact_id"] = contact.id
    return out


async def search_contacts(db: AsyncSession, params: dict) -> dict:
    query_str = params.get("query", "")
    result = await db.execute(
        select(Contact).where(
            or_(
                Contact.name.ilike(f"%{query_str}%"),
                Contact.email.ilike(f"%{query_str}%"),
                Contact.company.ilike(f"%{query_str}%"),
                Contact.phone.ilike(f"%{query_str}%"),
            )
        ).limit(5)
    )
    contacts = result.scalars().all()
    return {
        "contacts": [
            {"id": c.id, "name": c.name, "email": c.email, "phone": c.phone, "company": c.company}
            for c in contacts
        ],
        "results": [
            {"id": c.id, "name": c.name, "email": c.email, "phone": c.phone, "company": c.company}
            for c in contacts
        ],
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


async def update_lead_details(db: AsyncSession, params: dict) -> dict:
    """Update captured lead fields, usually after caller corrections."""
    lead_id = params.get("lead_id")
    source_session_id = params.get("source_session_id")

    lead = None
    if lead_id is not None:
        result = await db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
    elif source_session_id is not None:
        result = await db.execute(
            select(Lead)
            .where(Lead.source_session_id == source_session_id)
            .order_by(Lead.id.desc())
            .limit(1)
        )
        lead = result.scalar_one_or_none()

    if not lead:
        return {"error": "Lead not found for update", "lead_id": lead_id}

    changed: dict[str, str] = {}
    for field in ("name", "email", "phone", "company", "notes"):
        if field in params and params.get(field) is not None:
            new_val = str(params.get(field)).strip()
            old_val = getattr(lead, field)
            if new_val != (old_val or ""):
                setattr(lead, field, new_val)
                changed[field] = new_val
    if "phone" in changed:
        lead.phone_e164 = normalize_e164(changed["phone"], settings.outbound_default_country_code)

    existing_profile = lead.lead_profile if isinstance(lead.lead_profile, dict) else {}
    updated_profile = _extract_profile(params, existing_profile)
    if updated_profile != existing_profile:
        lead.lead_profile = updated_profile
        changed["lead_profile"] = "updated"

        await db.flush()
    contact = await upsert_contact_from_lead(db, lead)
    result = {
        "status": "updated",
        "lead_id": lead.id,
        "changed_fields": changed,
    }
    if contact:
        result["contact_id"] = contact.id
    return result
