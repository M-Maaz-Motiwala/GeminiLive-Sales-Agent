"""Auto-assign SIP lab extensions when agents are created via CRM."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Agent, AgentType

RESERVED_EXTENSIONS = frozenset(
    {
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
)

_EXTENSION_RANGE = range(705, 800)

_TYPES_WITH_EXTENSION = frozenset(
    {
        AgentType.sales,
        AgentType.outbound_sales,
        AgentType.support,
        AgentType.lead_qualification,
    }
)


def agent_type_needs_extension(agent_type: AgentType) -> bool:
    return agent_type in _TYPES_WITH_EXTENSION


async def allocate_inbound_extension(db: AsyncSession) -> str:
    """Return the lowest free extension in 705–799."""
    result = await db.execute(
        select(Agent.inbound_extension).where(Agent.inbound_extension.isnot(None))
    )
    used = {row[0] for row in result.all() if row[0]}
    for ext in _EXTENSION_RANGE:
        candidate = str(ext)
        if candidate not in used and candidate not in RESERVED_EXTENSIONS:
            return candidate
    raise RuntimeError("No inbound extensions available in range 705–799")
