"""Build handoff context when transferring a live call to support."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Message


async def load_recent_transcript(
    db: AsyncSession, session_id: int, *, limit: int = 12
) -> list[dict[str, str]]:
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.timestamp.desc())
        .limit(limit)
    )
    rows = list(reversed(result.scalars().all()))
    return [{"role": m.role, "text": m.text} for m in rows if m.text]


def format_transfer_handoff(
    *,
    from_agent_name: str,
    handoff_summary: str,
    transcript: list[dict[str, str]],
    caller_id: Optional[str] = None,
) -> str:
    lines = [
        "## Call transfer handoff (internal — do not read section headers aloud)",
        f"You are taking over this live call from {from_agent_name}.",
        "Introduce yourself as a Trango Tech support specialist and acknowledge the transfer naturally.",
        "The caller should feel like a new knowledgeable person joined — not a system handoff.",
    ]
    if caller_id:
        lines.append(f"- Caller ID on record: {caller_id}")
    if handoff_summary.strip():
        lines.append(f"- Reason for transfer: {handoff_summary.strip()}")
    if transcript:
        lines.append("\n## Recent conversation (for context only)")
        for turn in transcript[-10:]:
            role = "Caller" if turn.get("role") == "user" else "Previous agent"
            text = (turn.get("text") or "").strip()
            if text:
                lines.append(f"- {role}: {text}")
    lines.append(
        "\nStart with a brief warm greeting, confirm you understand their issue, "
        "then help using search_knowledge_base for approved answers."
    )
    return "\n".join(lines) + "\n"
