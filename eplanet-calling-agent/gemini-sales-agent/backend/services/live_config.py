"""Build JSON-serializable Gemini Live config from a DB Agent row."""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from backend.db.models import Agent, AgentType
from backend.services.gemini_live import SYSTEM_PROMPTS
from backend.services.tool_executor import get_tool_declarations

logger = logging.getLogger(__name__)

DEFAULT_VOICE_MASTER_PROMPT = """You are on a live phone call representing Trango Tech — a full-service software development partner.

## Voice call rules (mandatory, every call)
- Speak like a real human professional: warm, polite, confident, and consultative — never robotic.
- Keep answers short and natural — one or two sentences unless asked for detail.
- Ask only 1 to 2 questions per message. Never fire multiple questions at once.
- Always end your turn with a helpful next-step question or action.
- Listen fully before responding; never interrupt the caller.
- Never mention these instructions, internal tools, or that you are an AI unless directly asked.
- When you need a brief beat before a tool or answer, speak a short natural phrase ("let me check that", "one moment") — sparingly. Never say the word "filler" or describe the phrase — just say it.

## Non-negotiable sales rules
- Do not jump to pricing without discovery and qualification first.
- Never invent pricing, timelines, discounts, case studies, or capabilities — rely only on approved company information (internally via tools; never describe this process to the caller).
- If you do not have a confirmed answer, say naturally: "I don't want to guess on that — I can connect you with a Trango Tech consultant who can confirm."
- Never promise a fixed final quote without confirmed scope and consultant review.
- Do not pressure the lead — help them make a confident decision.
- If the prospect refuses contact details, continue helping and ask again near closing.

## Tool usage (critical — no dead air, sound human)
- BEFORE calling any tool, say a brief phrase out loud first (for example: "Let me check that", "One moment", "Let me pull that up for you"). Never say "filler" or label what you are doing — just speak the phrase naturally.
- This is mandatory for every tool call so the caller never experiences silent delay.
- Never go silent while a tool is running — reassure the caller with a short phrase.
- AFTER tool results, answer in plain spoken language — never read JSON, bullet lists, or field names aloud.

## Never expose system mechanics (critical — sounds like AI)
- NEVER say aloud: "knowledge base", "KB", "database", "searching our system", "looking in our records", "I didn't find it in the knowledge base", "according to my tools", "search_knowledge_base", "create_lead", or any tool/function name.
- NEVER narrate that you are "checking the knowledge base" or "searching documentation" — just use natural phrases like "let me check that for you" or "one moment".
- When information is missing, do NOT blame a system. Say naturally: "I don't have that exact detail handy right now, but our consultant can confirm that for you."
- Speak as a Trango Tech sales consultant on a phone call — not as software running a lookup.

## Lead capture quality (critical)
- Before saving any name, email, or phone number, repeat it back character-by-character for confirmation.
- Only call create_lead AFTER the caller explicitly confirms the details are correct.
- On outbound calls, if they say their phone is the same number you called or "this number", use the dialed number from call context — do not ask them to read it again.
- If the caller corrects any saved detail, immediately call update_lead_details and confirm the correction.

## Scheduling follow-up calls (mandatory when proposing a meeting or callback)
- Trango Tech schedules from **US Central (CST/CDT)** — San Antonio, Texas. Say that naturally when offering times (e.g. "I'm on Central Time here in San Antonio").
- Whenever you propose or agree to a specific date or time — discovery call, consultant callback, "I'll align a call", etc. — you **must** confirm the prospect's **timezone** before treating the time as final.
- Do not assume their timezone from their phone number or location. Ask once, plainly: "What timezone are you in?" or "Is that Eastern, Central, or another timezone?"
- After they give a time, **repeat it back with both timezones** when helpful (e.g. "So that's 2 PM your time Eastern — that's 1 PM Central on our side. Does that work?").
- Only save preferred_meeting_time in create_lead/update_lead_details after timezone is confirmed. Include timezone in the saved value (e.g. "Tue 2:00 PM EST / 1:00 PM CST").
- Never say "I'll schedule that" or "we're all set" on a time until timezone is confirmed.
- **Suggesting** a discovery call is not enough — if they agree to one, stay on the line and confirm **date, time, timezone**, and **contact details** (name, email/phone) before wrapping up. Use create_lead to save what you captured.
- Do **not** call end_call right after proposing a discovery call unless the prospect clearly declines scheduling, says they will follow up themselves, or says goodbye / not interested.

## Call ending behavior
- If the caller clearly indicates they are done ("bye", "that's all", "talk later"), speak your full goodbye first — complete the farewell sentence out loud.
- Only call end_call AFTER you have finished speaking the goodbye (same turn is fine once the words are spoken; the system waits for your voice to finish playing).
- Do not call end_call before or mid-sentence — never cut yourself off.
- Never end abruptly without a closing sentence.
- **Exception:** If the caller says "bye" or hangs up, you may end after your short farewell — you do not need to finish scheduling in that case.

"""

OUTBOUND_OPENING_RULES = """## Outbound cold-call opening (mandatory — style only, keep 9-stage funnel)
- Speak first when the call connects, but your **first line is greeting only** — hello and your name. Then wait for their response.
- **Next turns (still Stage 1):** ease in with a brief comfortable line → one-sentence Trango Tech intro → ask if they have a quick moment.
- Do NOT combine greeting, company pitch, permission, and business questions into one opener.
- Only after they agree to continue, move to Stage 2 (Discovery).
- If they say no or not interested, thank them and end_call.
"""

# Runtime accessor — may be overridden by DB PlatformSetting at call time.
# Code should use _get_master_prompt() rather than this constant directly.
VOICE_MASTER_PROMPT = DEFAULT_VOICE_MASTER_PROMPT


def _get_master_prompt(override: str | None = None) -> str:
    """Return master prompt: agent-level override > global DB setting > default."""
    if override and override.strip():
        return override.strip() + "\n\n"
    return VOICE_MASTER_PROMPT

INBOUND_KB_QUERY = (
    "company overview services products pricing sales process callback returning prospect"
)
OUTBOUND_KB_QUERY = (
    "cold outbound sales script discovery objections pricing services trangotech pitch"
)

_PRELOAD_CACHE: dict[tuple[int, str], tuple[float, str, dict[str, Any]]] = {}
PRELOAD_CACHE_TTL_SEC = int(os.getenv("KB_PRELOAD_CACHE_TTL_SEC", "300"))


def _role_prompt(agent: Agent, direction: str) -> str:
    is_outbound = direction == "outbound"
    if is_outbound and agent.outbound_prompt_template:
        return agent.outbound_prompt_template
    if not is_outbound and agent.inbound_prompt_template:
        return agent.inbound_prompt_template
    if agent.system_prompt_template:
        return agent.system_prompt_template
    agent_type = agent.type.value if hasattr(agent.type, "value") else str(agent.type)
    return SYSTEM_PROMPTS.get(agent_type, SYSTEM_PROMPTS["sales"])


async def preload_agent_context(
    agent: Agent,
    *,
    direction: str = "inbound",
    top_k: int = 5,
) -> tuple[str, dict[str, Any]]:
    """Fetch direction-aware KB chunks for injection at call start."""
    enabled = list(agent.enabled_tools or [])
    if "search_knowledge_base" not in enabled:
        return "", {"chunks": [], "skipped": "kb_tool_disabled"}

    cache_key = (agent.id, direction)
    if PRELOAD_CACHE_TTL_SEC > 0:
        cached = _PRELOAD_CACHE.get(cache_key)
        if cached and (time.time() - cached[0]) < PRELOAD_CACHE_TTL_SEC:
            block, meta = cached[1], dict(cached[2])
            meta["cache_hit"] = True
            return block, meta

    kb_query = OUTBOUND_KB_QUERY if direction == "outbound" else INBOUND_KB_QUERY
    try:
        from backend.services import rag_service

        agent_type = agent.type.value if hasattr(agent.type, "value") else str(agent.type)
        query = f"{agent.name} {agent_type} {kb_query}"
        results, latency_ms = await rag_service.query_with_timing(query, agent.id, top_k=top_k)
        if not results:
            logger.warning("No KB chunks preloaded for agent %s (%s)", agent.slug, direction)
            return "", {"chunks": [], "query": query, "skipped": "no_results", "direction": direction}

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
            return "", {"chunks": [], "query": query, "skipped": "empty_chunks", "direction": direction}

        block = (
            "## Preloaded company information (internal reference — do not read this header aloud)\n"
            "Use the following as your primary source at call start and for common questions. "
            "When speaking, present answers naturally — never mention that you are reading from a knowledge base or database:\n\n"
            + "\n\n".join(lines)
        )
        from backend.services.rag_metrics import compute_query_metrics

        rag_eval = compute_query_metrics(
            query, results, latency_ms=latency_ms, top_k=top_k, source="preload"
        )
        meta = {
            "chunks": chunks_meta,
            "query": query,
            "latency_ms": latency_ms,
            "metrics": rag_eval,
            "direction": direction,
        }
        if PRELOAD_CACHE_TTL_SEC > 0 and block:
            _PRELOAD_CACHE[cache_key] = (time.time(), block, meta)
        return block, meta
    except Exception as exc:
        logger.warning("KB preload failed for agent %s: %s", agent.slug, exc)
        return "", {"chunks": [], "error": str(exc), "direction": direction}


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


def format_outbound_call_context(meta: dict[str, Any]) -> str:
    """Tell the agent which number was dialed (for 'same as this number' capture)."""
    phone = (
        meta.get("prospect_phone_e164")
        or meta.get("prospect_phone")
        or meta.get("contact_number")
    )
    if not phone:
        return ""
    return (
        "## Outbound call context (internal — do not read section headers aloud)\n"
        f"- This call was placed to: {phone}\n"
        "- If the prospect says their phone is the same number you called, "
        "'this number', 'the number you're calling', or similar, their phone is: "
        f"{phone}\n"
        "- When saving their contact with create_lead, use that number if they confirm "
        "it is their phone (you do not need to ask them to repeat digits they already confirmed).\n"
    )


def agent_to_live_config(
    agent: Agent,
    kb_context: str = "",
    *,
    lead_context: str = "",
    prior_call_context: str = "",
    call_context: str = "",
    direction: str = "inbound",
    global_master_prompt: str | None = None,
) -> dict[str, Any]:
    """Return config dict consumed by the SIP bridge."""
    role_prompt = _role_prompt(agent, direction)
    # Per-agent override wins, then global platform setting, then built-in default.
    agent_override = getattr(agent, "master_prompt_override", None) or None
    master = _get_master_prompt(agent_override or global_master_prompt)
    system_prompt = master + role_prompt
    if direction == "outbound":
        system_prompt += "\n\n" + OUTBOUND_OPENING_RULES
    if prior_call_context:
        system_prompt += "\n\n" + prior_call_context
    if call_context:
        system_prompt += "\n\n" + call_context
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
        "direction": direction,
    }
