import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Agent, Persona, AgentType, User, Document, Organization, VoiceGender
from backend.services.agent_provisioning import (
    agent_type_needs_extension,
    allocate_inbound_extension,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])


class PersonaIn(BaseModel):
    name: str
    description: Optional[str] = None
    traits: dict = {}
    example_phrases: list = []
    is_active: bool = False


class AgentIn(BaseModel):
    name: str
    organization_id: int
    type: AgentType = AgentType.sales
    inbound_prompt_template: Optional[str] = None
    outbound_prompt_template: Optional[str] = None
    voice: str = "Zephyr"
    voice_gender: str = "female"
    model: str = "gemini-3.1-flash-live-preview"
    enabled_tools: list = []
    is_active: bool = True


def _agent_out(a: Agent, doc_count: int = 0, org_name: Optional[str] = None) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "slug": a.slug,
        "type": a.type,
        "organization_id": a.organization_id,
        "organization_name": org_name,
        "did": a.did,
        "inbound_prompt_template": a.inbound_prompt_template,
        "outbound_prompt_template": a.outbound_prompt_template,
        "voice": a.voice,
        "voice_gender": a.voice_gender,
        "model": a.model,
        "enabled_tools": a.enabled_tools or [],
        "inbound_extension": a.inbound_extension,
        "is_active": a.is_active,
        "document_count": doc_count,
        "created_at": a.created_at,
    }


async def _doc_counts(db: AsyncSession) -> dict[int, int]:
    result = await db.execute(
        select(Document.agent_id, func.count(Document.id))
        .where(Document.agent_id.isnot(None))
        .group_by(Document.agent_id)
    )
    return {row[0]: row[1] for row in result.all()}


async def _load_org(db: AsyncSession, organization_id: int) -> Organization:
    org = await db.get(Organization, organization_id)
    if not org or not org.is_active:
        raise HTTPException(400, "Organization not found or inactive")
    return org


def _resolve_system_prompt(body: AgentIn) -> str:
    inbound = (body.inbound_prompt_template or "").strip()
    outbound = (body.outbound_prompt_template or "").strip()
    if inbound:
        return inbound
    if outbound:
        return outbound
    return f"You are {body.name}, a sales phone agent."


def _unique_slug(base: str, existing: set[str]) -> str:
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}-{n}"
        n += 1
    return slug


@router.get("")
async def list_agents(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Agent).order_by(Agent.created_at.desc()))
    agents = result.scalars().all()
    counts = await _doc_counts(db)
    org_ids = {a.organization_id for a in agents if a.organization_id}
    org_names: dict[int, str] = {}
    if org_ids:
        org_result = await db.execute(
            select(Organization).where(Organization.id.in_(org_ids))
        )
        org_names = {o.id: o.name for o in org_result.scalars()}
    return [
        _agent_out(a, counts.get(a.id, 0), org_names.get(a.organization_id or -1))
        for a in agents
    ]


@router.post("")
async def create_agent(
    body: AgentIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    org = await _load_org(db, body.organization_id)
    slug_base = re.sub(r"[^a-z0-9-]", "-", body.name.lower().strip()).strip("-") or "agent"
    taken = {row[0] for row in (await db.execute(select(Agent.slug))).all()}
    slug = _unique_slug(slug_base, taken)

    inbound_extension = None
    if agent_type_needs_extension(body.type):
        inbound_extension = await allocate_inbound_extension(db)

    agent = Agent(
        name=body.name,
        slug=slug,
        type=body.type,
        organization_id=org.id,
        did=org.did,
        system_prompt_template=_resolve_system_prompt(body),
        inbound_prompt_template=body.inbound_prompt_template,
        outbound_prompt_template=body.outbound_prompt_template,
        voice=body.voice,
        voice_gender=body.voice_gender,
        model=body.model,
        enabled_tools=body.enabled_tools,
        inbound_extension=inbound_extension,
        is_active=body.is_active,
        created_by_id=user.id,
    )
    db.add(agent)
    await db.flush()
    return _agent_out(agent, 0, org.name)


@router.get("/{agent_id}")
async def get_agent(agent_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(404, "Agent not found")
    counts = await _doc_counts(db)
    org_name = None
    if a.organization_id:
        org = await db.get(Organization, a.organization_id)
        org_name = org.name if org else None
    return _agent_out(a, counts.get(a.id, 0), org_name)


@router.get("/{agent_id}/stats")
async def agent_stats(agent_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(404, "Agent not found")
    doc_result = await db.execute(
        select(func.count(Document.id)).where(Document.agent_id == agent_id)
    )
    doc_count = doc_result.scalar() or 0
    return {
        "agent_id": agent_id,
        "document_count": doc_count,
        "inbound_extension": a.inbound_extension,
        "organization_id": a.organization_id,
        "did": a.did,
        "has_knowledge_tool": "search_knowledge_base" in (a.enabled_tools or []),
    }


@router.put("/{agent_id}")
async def update_agent(
    agent_id: int,
    body: AgentIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(404, "Agent not found")

    org = await _load_org(db, body.organization_id)
    a.name = body.name
    a.type = body.type
    a.organization_id = org.id
    a.did = org.did
    a.inbound_prompt_template = body.inbound_prompt_template
    a.outbound_prompt_template = body.outbound_prompt_template
    a.system_prompt_template = _resolve_system_prompt(body)
    a.voice = body.voice
    a.voice_gender = body.voice_gender
    a.model = body.model
    a.enabled_tools = body.enabled_tools
    a.is_active = body.is_active

    if agent_type_needs_extension(body.type) and not a.inbound_extension:
        a.inbound_extension = await allocate_inbound_extension(db)

    counts = await _doc_counts(db)
    return _agent_out(a, counts.get(a.id, 0), org.name)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(404, "Agent not found")
    await db.delete(a)


@router.get("/{agent_id}/personas")
async def list_personas(agent_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Persona).where(Persona.agent_id == agent_id))
    personas = result.scalars().all()
    return [{"id": p.id, "name": p.name, "description": p.description, "traits": p.traits, "example_phrases": p.example_phrases, "is_active": p.is_active} for p in personas]


@router.post("/{agent_id}/personas")
async def create_persona(agent_id: int, body: PersonaIn, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    p = Persona(agent_id=agent_id, **body.model_dump())
    db.add(p)
    await db.flush()
    return {"id": p.id, "name": p.name, "is_active": p.is_active}


@router.delete("/{agent_id}/personas/{persona_id}", status_code=204)
async def delete_persona(agent_id: int, persona_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Persona).where(Persona.id == persona_id, Persona.agent_id == agent_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Persona not found")
    await db.delete(p)
