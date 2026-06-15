"""Generate session summaries and typed output documents using Gemini text."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from google import genai
from google.genai import types

from backend.config import get_settings
from backend.db.models import AgentType

logger = logging.getLogger(__name__)
settings = get_settings()

_SUMMARY_PROMPTS: dict[str, str] = {
    AgentType.lead_qualification.value: (
        "You are summarizing a lead qualification call for a sales team. "
        "Write 3-4 concise sentences covering: caller identity, their need/project, "
        "budget or timeline if mentioned, qualification level, and recommended next step."
    ),
    AgentType.sales.value: (
        "You are summarizing a sales discovery call. "
        "Write 3-4 concise sentences covering: prospect context, pain points, "
        "services discussed, objections or concerns, and suggested follow-up."
    ),
    AgentType.document_qa.value: (
        "You are summarizing a support/FAQ call. "
        "Write 3-4 concise sentences covering: the issue or question, what was explained, "
        "whether it was resolved, and any escalation or follow-up needed."
    ),
    AgentType.outbound_sales.value: (
        "You are summarizing an outbound cold call. "
        "Write 3-4 concise sentences covering: prospect reaction, interest level, "
        "whether a callback was booked or lead captured, and recommended follow-up."
    ),
    "default": (
        "You are a professional note-taker. Summarize the conversation into "
        "2-4 concise sentences capturing key points and outcomes."
    ),
}

_AGENT_OUTPUT_TYPES: dict[str, list[str]] = {
    AgentType.lead_qualification.value: ["lead_capture", "action_items"],
    AgentType.sales.value: ["action_items"],
    AgentType.document_qa.value: ["action_items"],
    AgentType.outbound_sales.value: ["call_disposition", "lead_capture", "action_items"],
}


def _text_model() -> str:
    return settings.gemini_text_model or "gemini-2.5-flash"


async def _retry_on_quota(coro_factory, *, attempts: int = 3, base_delay: float = 35.0):
    """Retry Gemini text calls when free-tier rate limits (429) are hit."""
    last_result: Any = None
    for attempt in range(attempts):
        last_result = await coro_factory()
        if isinstance(last_result, dict):
            err = str(last_result.get("error") or "")
            if ("429" in err or "RESOURCE_EXHAUSTED" in err) and attempt + 1 < attempts:
                await asyncio.sleep(base_delay * (attempt + 1))
                continue
        return last_result
    return last_result or {"error": "rate limited"}


def _client() -> genai.Client:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    return genai.Client(api_key=settings.gemini_api_key)


def _agent_type_key(agent_type: Any) -> str:
    if agent_type is None:
        return "default"
    if hasattr(agent_type, "value"):
        return str(agent_type.value)
    return str(agent_type)


def output_types_for_agent(agent_type: Any, *, direction: str | None = None) -> list[str]:
    key = _agent_type_key(agent_type)
    types_list = list(_AGENT_OUTPUT_TYPES.get(key, []))
    if direction == "outbound" and key == AgentType.sales.value:
        for extra in ("call_disposition", "lead_capture"):
            if extra not in types_list:
                types_list.append(extra)
    if "summary" not in types_list:
        types_list.insert(0, "summary")
    return types_list


async def generate_summary(
    messages: list[dict],
    *,
    agent_type: Any = None,
    agent_name: Optional[str] = None,
) -> dict[str, Any]:
    """Summarize a session transcript. Returns {summary, error}."""
    if not messages:
        return {"summary": "", "error": "No transcript messages"}

    transcript = "\n".join(f"{m['role'].upper()}: {m['text']}" for m in messages)
    type_key = _agent_type_key(agent_type)
    instruction = _SUMMARY_PROMPTS.get(type_key, _SUMMARY_PROMPTS["default"])
    if agent_name:
        instruction = f"Agent on the call: {agent_name}. {instruction}"

    prompt = f"{instruction}\n\nCONVERSATION:\n{transcript}\n\nSUMMARY:"

    async def _call():
        try:
            client = _client()
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=_text_model(),
                    contents=prompt,
                ),
            )
            text = (result.text or "").strip()
            if not text:
                return {"summary": "", "error": "Model returned empty summary"}
            return {"summary": text, "error": None}
        except Exception as e:
            logger.error("Summary generation failed: %s", e)
            return {"summary": "", "error": str(e)}

    return await _retry_on_quota(_call)


async def generate_output(
    output_type: str,
    messages: list[dict],
    context: dict | None = None,
) -> dict:
    """Generate a structured JSON output for a session based on output_type."""
    transcript = "\n".join(f"{m['role'].upper()}: {m['text']}" for m in messages)

    prompts = {
        "lead_capture": (
            "Extract lead information from this conversation as JSON with keys: "
            "name, email, phone, company, interest_level (1-10), key_needs (array of strings), "
            "notes (short string). Return ONLY valid JSON."
        ),
        "action_items": (
            "List follow-ups from this conversation as JSON with key: "
            "items (array of {task, owner, priority, due_date}). Return ONLY valid JSON."
        ),
        "call_disposition": (
            "Classify this outbound call as JSON with keys: "
            "disposition (interested|callback_booked|not_interested|no_answer|wrong_number|do_not_call|voicemail), "
            "interest_level (1-10), callback_requested (boolean), lead_captured (boolean), "
            "objections (array of strings), notes (short string). Return ONLY valid JSON."
        ),
        "research_report": (
            "Compile a structured research report as JSON with keys: "
            "topic, key_findings (list), sources_mentioned (list), recommendations (list). "
            "Return ONLY valid JSON."
        ),
        "code_analysis": (
            "Summarize code analysis findings as JSON with keys: "
            "files_reviewed (list), issues_found (list), improvements_suggested (list), "
            "overall_quality (1-10). Return ONLY valid JSON."
        ),
        "summary": (
            "Provide a structured session summary as JSON with keys: "
            "headline (one line), summary (paragraph), topics_covered (list), "
            "decisions_made (list), next_steps (list), sentiment (positive/neutral/negative). "
            "Return ONLY valid JSON."
        ),
    }

    prompt_prefix = prompts.get(output_type, prompts["summary"])
    agent_hint = ""
    if context and context.get("agent_name"):
        agent_hint = f"Agent: {context['agent_name']}. "
    prompt = f"{agent_hint}{prompt_prefix}\n\nCONVERSATION:\n{transcript}"

    async def _call():
        try:
            client = _client()
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=_text_model(),
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                ),
            )
            text = (result.text or "").strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            logger.error("Output generation failed for %s: %s", output_type, e)
            return {"error": str(e)}

    out = await _retry_on_quota(_call)
    return out if isinstance(out, dict) else {"error": "Unexpected response"}
