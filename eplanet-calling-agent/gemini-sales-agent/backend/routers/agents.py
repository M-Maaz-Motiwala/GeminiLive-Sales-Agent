import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from backend.auth.deps import get_current_user
from backend.db.database import get_db
from backend.db.models import Agent, Persona, AgentType, User, Document

router = APIRouter(prefix="/api/agents", tags=["agents"])

RESERVED_EXTENSIONS = {
    "600",
    "700",
    "701",
    "702",
    "703",
    "704",
    "1000",
    "1001",
    "1002",
    "1003",
    "1004",
    "1005",
    "1006",
    "1007",
    "1008",
    "1009",
    "1010",
}


class PersonaIn(BaseModel):
    name: str
    description: Optional[str] = None
    traits: dict = {}
    example_phrases: list = []
    is_active: bool = False


class AgentIn(BaseModel):
    name: str
    type: AgentType = AgentType.sales
    system_prompt_template: str
    inbound_prompt_template: Optional[str] = None
    outbound_prompt_template: Optional[str] = None
    voice: str = "Zephyr"
    model: str = "gemini-3.1-flash-live-preview"
    enabled_tools: list = []
    inbound_extension: Optional[str] = None
    is_active: bool = True

    @field_validator("inbound_extension")
    @classmethod
    def validate_extension(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip()
        if not re.fullmatch(r"\d{3,4}", v):
            raise ValueError("Extension must be 3–4 digits")
        if v in RESERVED_EXTENSIONS:
            raise ValueError(f"Extension {v} is reserved for system use")
        return v


def _agent_out(a: Agent, doc_count: int = 0) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "slug": a.slug,
        "type": a.type,
        "system_prompt_template": a.system_prompt_template,
        "inbound_prompt_template": a.inbound_prompt_template,
        "outbound_prompt_template": a.outbound_prompt_template,
        "voice": a.voice,
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


async def _check_extension_unique(
    db: AsyncSession, ext: Optional[str], exclude_id: Optional[int] = None
) -> None:
    if not ext:
        return
    q = select(Agent).where(Agent.inbound_extension == ext)
    if exclude_id:
        q = q.where(Agent.id != exclude_id)
    result = await db.execute(q)
    if result.scalar_one_or_none():
        raise HTTPException(400, f"Extension {ext} is already assigned to another agent")


@router.get("")
async def list_agents(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Agent).order_by(Agent.created_at.desc()))
    agents = result.scalars().all()
    counts = await _doc_counts(db)
    return [_agent_out(a, counts.get(a.id, 0)) for a in agents]


@router.post("")
async def create_agent(body: AgentIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await _check_extension_unique(db, body.inbound_extension)
    slug = re.sub(r"[^a-z0-9-]", "-", body.name.lower().strip())
    agent = Agent(
        name=body.name,
        slug=slug,
        type=body.type,
        system_prompt_template=body.system_prompt_template,
        inbound_prompt_template=body.inbound_prompt_template,
        outbound_prompt_template=body.outbound_prompt_template,
        voice=body.voice,
        model=body.model,
        enabled_tools=body.enabled_tools,
        inbound_extension=body.inbound_extension,
        is_active=body.is_active,
        created_by_id=user.id,
    )
    db.add(agent)
    await db.flush()
    return _agent_out(agent, 0)


@router.get("/{agent_id}")
async def get_agent(agent_id: int, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(404, "Agent not found")
    counts = await _doc_counts(db)
    return _agent_out(a, counts.get(a.id, 0))


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
        "has_knowledge_tool": "search_knowledge_base" in (a.enabled_tools or []),
    }


@router.put("/{agent_id}")
async def update_agent(agent_id: int, body: AgentIn, db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(404, "Agent not found")
    await _check_extension_unique(db, body.inbound_extension, exclude_id=agent_id)
    for field, value in body.model_dump().items():
        setattr(a, field, value)
    counts = await _doc_counts(db)
    return _agent_out(a, counts.get(a.id, 0))


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
