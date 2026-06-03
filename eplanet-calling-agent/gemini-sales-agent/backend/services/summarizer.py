"""Generate session summaries and typed output documents using Gemini text."""
import json
import logging
from typing import Optional

from google import genai
from google.genai import types

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)


async def generate_summary(messages: list[dict]) -> str:
    """Summarize a session transcript into a concise paragraph."""
    if not messages:
        return ""

    transcript = "\n".join(
        f"{m['role'].upper()}: {m['text']}" for m in messages
    )
    prompt = (
        "You are a professional note-taker. Summarize the following conversation "
        "into 2-3 concise sentences capturing the key points and any outcomes.\n\n"
        f"CONVERSATION:\n{transcript}\n\nSUMMARY:"
    )
    try:
        import asyncio
        client = _client()
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
        )
        return result.text.strip()
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        return ""


async def generate_output(output_type: str, messages: list[dict], context: dict = None) -> dict:
    """Generate a structured JSON output for a session based on output_type."""
    transcript = "\n".join(
        f"{m['role'].upper()}: {m['text']}" for m in messages
    )

    prompts = {
        "lead_capture": (
            "Extract lead information from this conversation as JSON with keys: "
            "name, email, phone, company, interest_level (1-10), key_needs (list). "
            "Return ONLY valid JSON."
        ),
        "action_items": (
            "List all action items and follow-ups from this conversation as JSON with key: "
            "items (array of {task, owner, due_date, priority}). Return ONLY valid JSON."
        ),
        "research_report": (
            "Compile a structured research report from this conversation as JSON with keys: "
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
            "summary (text), topics_covered (list), decisions_made (list), next_steps (list). "
            "Return ONLY valid JSON."
        ),
    }

    prompt_prefix = prompts.get(output_type, prompts["summary"])
    prompt = f"{prompt_prefix}\n\nCONVERSATION:\n{transcript}"

    try:
        import asyncio
        client = _client()
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
        )
        text = result.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        logger.error(f"Output generation failed for {output_type}: {e}")
        return {"error": str(e)}
