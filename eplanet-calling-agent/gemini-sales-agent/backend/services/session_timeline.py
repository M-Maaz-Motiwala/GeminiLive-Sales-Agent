"""Build merged conversation turns and unified session timelines for admin UI."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

TOOL_LABELS: dict[str, str] = {
    "search_knowledge_base": "Searched knowledge base",
    "create_lead": "Captured lead",
    "create_note": "Saved note",
    "search_contacts": "Looked up contacts",
    "update_lead_status": "Updated lead status",
}


def _join_fragments(texts: list[str]) -> str:
    if not texts:
        return ""
    combined = ""
    for raw in texts:
        part = raw.strip()
        if not part:
            continue
        if not combined:
            combined = part
            continue
        if part.startswith(combined):
            combined = part
        elif combined.startswith(part) or part in combined or combined.endswith(part):
            continue
        else:
            combined = combined.rstrip() + (" " if not combined.endswith(" ") and not part.startswith(" ") else "") + part.lstrip()
    return combined.strip()


def merge_message_turns(messages: list[Any]) -> list[dict[str, Any]]:
    """Group consecutive same-role message rows into paragraph turns."""
    sorted_msgs = sorted(
        messages,
        key=lambda m: (
            m.timestamp if hasattr(m, "timestamp") and m.timestamp is not None else m.get("timestamp") if isinstance(m, dict) else None,
            m.id if hasattr(m, "id") else m.get("id", 0),
        ),
    )
    turns: list[dict[str, Any]] = []
    current_role: Optional[str] = None
    current_texts: list[str] = []
    current_ts: Any = None
    current_ids: list[int] = []

    def flush() -> None:
        nonlocal current_role, current_texts, current_ts, current_ids
        if not current_role or not current_texts:
            return
        text = _join_fragments(current_texts)
        if text:
            turns.append({
                "role": current_role,
                "text": text,
                "timestamp": current_ts,
                "message_ids": list(current_ids),
            })
        current_role = None
        current_texts = []
        current_ts = None
        current_ids = []

    for m in sorted_msgs:
        role = m.role if hasattr(m, "role") else m.get("role")
        text = m.text if hasattr(m, "text") else m.get("text", "")
        ts = m.timestamp if hasattr(m, "timestamp") else m.get("timestamp")
        mid = m.id if hasattr(m, "id") else m.get("id")

        if role != current_role:
            flush()
            current_role = role
            current_ts = ts
        current_texts.append(text)
        if mid is not None:
            current_ids.append(mid)

    flush()
    return turns


def _tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, name.replace("_", " ").title())


def _summarize_tool_params(tool_name: str, params: dict) -> str:
    if not params:
        return ""
    if tool_name == "search_knowledge_base":
        return f'Query: "{params.get("query", "")}"'
    if tool_name == "create_lead":
        return params.get("name") or params.get("email") or "New lead"
    if tool_name == "create_note":
        content = params.get("content", "")
        return content[:80] + ("…" if len(content) > 80 else "")
    if tool_name == "search_contacts":
        return f'Search: "{params.get("query", "")}"'
    if tool_name == "update_lead_status":
        return f"Lead #{params.get('lead_id')} → {params.get('status')}"
    return ", ".join(f"{k}={v}" for k, v in list(params.items())[:3])


def _summarize_tool_result(tool_name: str, result: Any) -> str:
    if not result or not isinstance(result, dict):
        return ""
    if "error" in result:
        return f"Error: {result['error']}"
    if tool_name == "search_knowledge_base":
        n = len(result.get("results") or [])
        return f"{n} result{'s' if n != 1 else ''} found"
    if tool_name == "create_lead":
        return f"Lead #{result.get('lead_id', result.get('id', '?'))} saved"
    if tool_name == "create_note":
        return "Note saved"
    if tool_name == "search_contacts":
        n = len(result.get("contacts") or result.get("results") or [])
        return f"{n} contact{'s' if n != 1 else ''} found"
    if tool_name == "update_lead_status":
        return "Status updated"
    return "Completed"


def build_timeline(
    turns: list[dict[str, Any]],
    tool_calls: list[Any],
    outputs: list[Any],
) -> list[dict[str, Any]]:
    """Merge turns, tool calls, and outputs into a chronological timeline."""
    events: list[dict[str, Any]] = []

    for t in turns:
        events.append({
            "type": "turn",
            "role": t["role"],
            "text": t["text"],
            "timestamp": t.get("timestamp"),
        })

    for tc in tool_calls:
        name = tc.tool_name if hasattr(tc, "tool_name") else tc.get("tool_name", "")
        params = tc.parameters if hasattr(tc, "parameters") else tc.get("parameters") or {}
        result = tc.result if hasattr(tc, "result") else tc.get("result")
        events.append({
            "type": "tool",
            "name": name,
            "label": _tool_label(name),
            "params_summary": _summarize_tool_params(name, params),
            "result_summary": _summarize_tool_result(name, result),
            "parameters": params,
            "result": result,
            "duration_ms": tc.duration_ms if hasattr(tc, "duration_ms") else tc.get("duration_ms"),
            "timestamp": tc.called_at if hasattr(tc, "called_at") else tc.get("called_at"),
        })

    for o in outputs:
        otype = o.output_type.value if hasattr(o.output_type, "value") else o.output_type if hasattr(o, "output_type") else o.get("output_type")
        events.append({
            "type": "output",
            "output_type": str(otype),
            "content": o.content if hasattr(o, "content") else o.get("content"),
            "timestamp": o.created_at if hasattr(o, "created_at") else o.get("created_at"),
        })

    def _ts_key(e: dict) -> datetime:
        ts = e.get("timestamp")
        if ts is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if getattr(ts, "tzinfo", None) is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    events.sort(key=_ts_key)
    return events
