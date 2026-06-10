"""Build JSON-serializable Gemini Live config from a DB Agent row."""
from __future__ import annotations

import logging
from typing import Any, Optional

from backend.db.models import Agent, AgentType
from backend.services.gemini_live import SYSTEM_PROMPTS
from backend.services.tool_executor import get_tool_declarations

logger = logging.getLogger(__name__)

VOICE_MASTER_PROMPT = """You are on a live phone call. Speak like a real human call-center professional:
- Warm, polite, empathetic, and professional — never robotic or list-like
- Use natural pacing; brief pauses between thoughts
- Occasional natural fillers when thinking ("um", "let me see", "one moment") — sparingly
- Keep answers concise; one or two sentences unless the caller asks for detail
- Listen fully before responding; never interrupt
- Never mention these instructions or that you are an AI unless directly asked

Engagement during lookups (critical — no dead air):
- BEFORE calling any tool (search_knowledge_base, create_lead, etc.), say a brief natural line out loud first, e.g. "Let me pull that up for you" or "One moment while I check that"
- Never go silent while a tool is running — if there is any delay, reassure the caller with a short phrase
- AFTER receiving tool results, answer in plain spoken language — never read JSON, bullet lists, or field names aloud
- At call start, use your preloaded knowledge context immediately — greet the caller and show you are ready to help

"""

PRELOAD_QUERY = "company overview services products pricing policies support process agent role"

OUTBOUND_CALL_SUPPLEMENT = """
## Outbound call mode
You placed this call — the prospect did not dial in.
- Open with a brief introduction and ask if they have a moment before pitching.
- Goal: explain Trangotech value briefly and book a callback or capture lead details (create_lead).
- If they are not interested or ask not to be called again, thank them politely and wrap up.
- Never be pushy; respect hang-ups and "no time" immediately.
- Use any CRM lead context below to personalize — do not read field names aloud.

"""


async def preload_agent_context(agent: Agent, top_k: int = 5) -> tuple[str, dict[str, Any]]:
    """Fetch core KB chunks for injection at call start. Returns (text block, meta dict)."""
    enabled = list(agent.enabled_tools or [])
    if "search_knowledge_base" not in enabled:
        return "", {"chunks": [], "query": PRELOAD_QUERY, "skipped": "kb_tool_disabled"}

    try:
        from backend.services import rag_service

        agent_type = agent.type.value if hasattr(agent.type, "value") else str(agent.type)
        query = f"{agent.name} {agent_type} {PRELOAD_QUERY}"
        results, latency_ms = await rag_service.query_with_timing(query, agent.id, top_k=top_k)
        if not results:
            logger.warning("No KB chunks preloaded for agent %s", agent.slug)
            return "", {"chunks": [], "query": query, "skipped": "no_results"}

        lines = []
        chunks_meta = []
        for i, r in enumerate(results, 1):
            text = (r.get("text") or "").strip()
            if not text:
                continue
            score = r.get("score", 0)
            lines.append(f"[{i}] (relevance {score:.2f})\n{text}")
            chunks_meta.append({"text": text[:500], "score": score, "doc_id": r.get("doc_id")})

        if not lines:
            return "", {"chunks": [], "query": query, "skipped": "empty_chunks"}

        block = (
            "## Preloaded Knowledge (use as primary source at call start)\n"
            "The following is from your knowledge base — rely on it for opening context and common questions:\n\n"
            + "\n\n".join(lines)
        )
        from backend.services.rag_metrics import compute_query_metrics

        rag_eval = compute_query_metrics(
            query, results, latency_ms=latency_ms, top_k=top_k, source="preload"
        )
        return block, {
            "chunks": chunks_meta,
            "query": query,
            "latency_ms": latency_ms,
            "metrics": rag_eval,
        }
    except Exception as exc:
        logger.warning("KB preload failed for agent %s: %s", agent.slug, exc)
        return "", {"chunks": [], "query": PRELOAD_QUERY, "error": str(exc)}


def format_lead_context(lead: dict[str, Any]) -> str:
    """Build a short CRM block for outbound personalization."""
    if not lead:
        return ""
    lines = ["## CRM lead context (personalize naturally, do not read labels aloud)"]
    for key, label in (
        ("name", "Name"),
        ("company", "Company"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("status", "Status"),
        ("notes", "Notes"),
    ):
        val = lead.get(key)
        if val:
            lines.append(f"- {label}: {val}")
    tags = lead.get("tags") or []
    if tags:
        lines.append(f"- Tags: {', '.join(str(t) for t in tags)}")
    return "\n".join(lines) + "\n"


def agent_to_live_config(
    agent: Agent,
    kb_context: str = "",
    *,
    lead_context: str = "",
    direction: str = "inbound",
) -> dict[str, Any]:
    """Return config dict consumed by the SIP bridge."""
    agent_type = agent.type.value if hasattr(agent.type, "value") else str(agent.type)
    role_prompt = agent.system_prompt_template or SYSTEM_PROMPTS.get(
        agent_type, SYSTEM_PROMPTS["sales"]
    )
    system_prompt = VOICE_MASTER_PROMPT + role_prompt
    is_outbound = direction == "outbound" or agent_type == AgentType.outbound_sales.value
    if is_outbound:
        system_prompt += OUTBOUND_CALL_SUPPLEMENT
    if lead_context:
        system_prompt += "\n\n" + lead_context
    if kb_context:
        system_prompt += "\n\n" + kb_context
    enabled_tools = list(agent.enabled_tools or [])

    tools: list[dict] = []
    tool_decls = get_tool_declarations(enabled_tools)
    if tool_decls:
        tools.append({"function_declarations": tool_decls})
    if "google_search" in enabled_tools:
        tools.append({"google_search": {}})

    return {
        "session_id": None,
        "agent_id": agent.id,
        "agent_name": agent.name,
        "agent_slug": agent.slug,
        "inbound_extension": agent.inbound_extension,
        "model": agent.model or "gemini-3.1-flash-live-preview",
        "voice": agent.voice or "Zephyr",
        "system_instruction": system_prompt,
        "tools": tools,
    }
