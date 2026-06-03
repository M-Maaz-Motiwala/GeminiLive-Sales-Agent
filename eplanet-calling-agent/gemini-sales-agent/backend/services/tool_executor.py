"""Tool executor — dispatches Gemini function calls to their handlers."""
import logging
import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from google.genai import types

from backend.services.tools import crm_tools, rag_tools

logger = logging.getLogger(__name__)

# Tool declarations sent to Gemini during session config
TOOL_DECLARATIONS = [
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
        return []
    return [t for t in TOOL_DECLARATIONS if t["name"] in enabled_tools]


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
                from backend.db.models import Lead
                params["source_session_id"] = session_id
            result = await crm_tools.create_lead(db, params)

        elif tool_name == "search_contacts":
            result = await crm_tools.search_contacts(db, params)

        elif tool_name == "create_note":
            result = await crm_tools.create_note(db, params, session_id=session_id)

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
