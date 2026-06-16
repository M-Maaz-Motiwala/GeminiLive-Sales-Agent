"""Tool executor — dispatches Gemini function calls to their handlers."""
import logging
import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from google.genai import types

from backend.services.tools import crm_tools, rag_tools

logger = logging.getLogger(__name__)


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


def _extract_lead_profile(params: dict, existing: dict | None = None) -> dict:
    profile = dict(existing or {})
    scalar_fields = (
        "industry",
        "service_required",
        "budget",
        "timeline",
        "preferred_meeting_time",
        "requirement",
        "recommended_service_package",
        "decision_maker_status",
        "lead_temperature",
        "recommended_next_step",
    )
    for field in scalar_fields:
        if field in params and params.get(field) is not None:
            s = _norm_str(params.get(field))
            if s:
                profile[field] = s
    if "key_features" in params and params.get("key_features") is not None:
        profile["key_features"] = _merge_unique(profile.get("key_features"), params.get("key_features"))
    if "objections_concerns" in params and params.get("objections_concerns") is not None:
        profile["objections_concerns"] = _merge_unique(profile.get("objections_concerns"), params.get("objections_concerns"))
    return profile


async def _attach_lead_to_session(
    db: AsyncSession,
    session_id: int,
    lead_id: int,
    params: dict,
) -> None:
    """Link captured lead details to the live call session for inbound callback lookup."""
    try:
        from backend.db.models import Session as DBSession
        from backend.services.session_metrics import merge_session_meta

        sess = await db.get(DBSession, session_id)
        if not sess:
            return
        patch: dict = {
            "lead_id": lead_id,
            "captured_contact": {
                "name": params.get("name"),
                "email": params.get("email"),
                "phone": params.get("phone"),
                "company": params.get("company"),
            },
            "lead_capture": {
                "name": params.get("name"),
                "email": params.get("email"),
                "phone": params.get("phone"),
                "company": params.get("company"),
            },
        }
        existing_lc = (sess.meta or {}).get("lead_capture")
        if isinstance(existing_lc, dict):
            patch["lead_capture"] = {
                **existing_lc,
                **{k: v for k, v in patch["lead_capture"].items() if v},
            }
        profile = _extract_lead_profile(
            params,
            (patch["lead_capture"].get("lead_profile") if isinstance(patch.get("lead_capture"), dict) else None),
        )
        if profile:
            patch["lead_capture"]["lead_profile"] = profile
        phone = params.get("phone")
        if phone:
            patch["lead_phone"] = phone
            patch["contact_number"] = phone
        sess.meta = merge_session_meta(sess.meta, patch)
        await db.flush()
    except Exception as exc:
        logger.warning("Failed to attach lead to session %s: %s", session_id, exc)


# Tool declarations sent to Gemini during session config
TOOL_DECLARATIONS = [
    {
        "name": "end_call",
        "description": "End the current phone call after confirming the caller is done.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why the call is ending (e.g. caller_said_bye, completed).",
                }
            },
            "required": [],
        },
    },
    {
        "name": "create_lead",
        "description": "Save a new sales lead captured during the conversation.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Full name of the lead"},
                "email": {"type": "string", "description": "Email address"},
                "phone": {"type": "string", "description": "Phone number"},
                "company": {"type": "string", "description": "Company name"},
                "notes": {"type": "string", "description": "Any additional notes about the lead"},
                "industry": {"type": "string", "description": "Prospect industry"},
                "service_required": {"type": "string", "description": "Service required by prospect"},
                "budget": {"type": "string", "description": "Budget shared by prospect"},
                "timeline": {"type": "string", "description": "Timeline shared by prospect"},
                "preferred_meeting_time": {"type": "string", "description": "Preferred time for follow-up meeting"},
                "requirement": {"type": "string", "description": "Requirement summary"},
                "recommended_service_package": {"type": "string", "description": "Recommended service/package"},
                "key_features": {"type": "array", "items": {"type": "string"}, "description": "Key requested features"},
                "decision_maker_status": {"type": "string", "description": "Decision-maker status"},
                "objections_concerns": {"type": "array", "items": {"type": "string"}, "description": "Objections or concerns"},
                "lead_temperature": {"type": "string", "description": "Hot | Warm | Cold | Unqualified"},
                "recommended_next_step": {"type": "string", "description": "Recommended next step"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "search_contacts",
        "description": "Search the contact database by name, email, or company.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "update_lead_details",
        "description": "Update an existing lead when caller corrects name/email/phone/company.",
        "parameters": {
            "type": "object",
            "properties": {
                "lead_id": {
                    "type": "integer",
                    "description": "Lead ID to update. Optional when source_session_id is available.",
                },
                "name": {"type": "string", "description": "Corrected full name"},
                "email": {"type": "string", "description": "Corrected email address"},
                "phone": {"type": "string", "description": "Corrected phone number"},
                "company": {"type": "string", "description": "Corrected company name"},
                "notes": {"type": "string", "description": "Additional corrected notes"},
                "industry": {"type": "string", "description": "Prospect industry"},
                "service_required": {"type": "string", "description": "Service required by prospect"},
                "budget": {"type": "string", "description": "Budget shared by prospect"},
                "timeline": {"type": "string", "description": "Timeline shared by prospect"},
                "preferred_meeting_time": {"type": "string", "description": "Preferred time for follow-up meeting"},
                "requirement": {"type": "string", "description": "Requirement summary"},
                "recommended_service_package": {"type": "string", "description": "Recommended service/package"},
                "key_features": {"type": "array", "items": {"type": "string"}, "description": "Key requested features"},
                "decision_maker_status": {"type": "string", "description": "Decision-maker status"},
                "objections_concerns": {"type": "array", "items": {"type": "string"}, "description": "Objections or concerns"},
                "lead_temperature": {"type": "string", "description": "Hot | Warm | Cold | Unqualified"},
                "recommended_next_step": {"type": "string", "description": "Recommended next step"},
            },
            "required": [],
        },
    },
    {
        "name": "create_note",
        "description": "Save a note during the conversation (action items, follow-ups, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Note content"},
                "entity_type": {"type": "string", "description": "session | lead | contact", "default": "session"},
                "entity_id": {"type": "integer", "description": "ID of the entity to attach the note to"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "update_lead_status",
        "description": "Update the status of an existing lead.",
        "parameters": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "integer", "description": "Lead ID to update"},
                "status": {
                    "type": "string",
                    "description": "New status: new | qualified | contacted | closed | lost",
                },
            },
            "required": ["lead_id", "status"],
        },
    },
    {
        "name": "search_knowledge_base",
        "description": "Search the agent's knowledge base for relevant information.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
            },
            "required": ["query"],
        },
    },
]


def get_tool_declarations(enabled_tools: list[str]) -> list[dict]:
    """Filter tool declarations to only those enabled for the agent."""
    if not enabled_tools:
        return [t for t in TOOL_DECLARATIONS if t["name"] == "end_call"]
    names = set(enabled_tools)
    names.add("end_call")
    # If agent can capture leads, also allow updating corrected details.
    if "create_lead" in names:
        names.add("update_lead_details")
    return [t for t in TOOL_DECLARATIONS if t["name"] in names]


async def dispatch(
    tool_name: str,
    call_id: str,
    params: dict,
    db: AsyncSession,
    session_id: Optional[int] = None,
    agent_id: Optional[int] = None,
) -> types.FunctionResponse:
    """Dispatch a tool call and return a FunctionResponse for Gemini."""
    start = time.monotonic()
    result = {}

    try:
        if tool_name == "create_lead":
            if session_id:
                params["source_session_id"] = session_id
            result = await crm_tools.create_lead(db, params)
            if session_id and db and result.get("lead_id"):
                await _attach_lead_to_session(db, session_id, result["lead_id"], params)

        elif tool_name == "end_call":
            result = {
                "status": "ending_call",
                "reason": params.get("reason") or "caller_done",
            }

        elif tool_name == "search_contacts":
            result = await crm_tools.search_contacts(db, params)

        elif tool_name == "create_note":
            result = await crm_tools.create_note(db, params, session_id=session_id)

        elif tool_name == "update_lead_details":
            if session_id:
                params["source_session_id"] = session_id
            result = await crm_tools.update_lead_details(db, params)
            if session_id and db and result.get("lead_id"):
                await _attach_lead_to_session(db, session_id, result["lead_id"], params)

        elif tool_name == "update_lead_status":
            result = await crm_tools.update_lead_status(db, params)

        elif tool_name == "search_knowledge_base":
            result = await rag_tools.search_knowledge_base(params, agent_id=agent_id)

        else:
            result = {"error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.error(f"Tool {tool_name} raised an exception: {e}")
        result = {"error": str(e)}

    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(f"Tool {tool_name} completed in {duration_ms}ms: {result}")

    # Persist tool call log
    if session_id and db:
        try:
            from backend.db.models import ToolCall
            tc = ToolCall(
                session_id=session_id,
                tool_name=tool_name,
                parameters=params,
                result=result,
                duration_ms=duration_ms,
            )
            db.add(tc)
            await db.flush()
        except Exception as e:
            logger.warning(f"Failed to persist tool call log: {e}")

    return types.FunctionResponse(id=call_id, name=tool_name, response=result)
