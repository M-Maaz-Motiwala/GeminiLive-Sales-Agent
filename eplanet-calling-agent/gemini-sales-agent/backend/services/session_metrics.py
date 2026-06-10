"""Aggregate per-session RAG and token metrics at call end."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Session as DBSession, ToolCall
from backend.services.rag_metrics import (
    aggregate_session_rag_metrics,
    metrics_from_preloaded_kb,
)


def collect_rag_entries_from_session(
    meta: dict[str, Any],
    tool_calls: list[ToolCall],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    preload_metrics = metrics_from_preloaded_kb(meta.get("preloaded_kb"))
    if preload_metrics:
        entries.append(preload_metrics)

    for tc in tool_calls:
        if tc.tool_name != "search_knowledge_base":
            continue
        result = tc.result or {}
        if isinstance(result, dict) and result.get("metrics"):
            entries.append(result["metrics"])
            continue
        # Backfill metrics for older sessions without stored metrics
        results = result.get("results") or []
        scores = [r.get("score", 0) for r in results if isinstance(r, dict)]
        if scores or tc.parameters:
            from backend.services.rag_metrics import compute_query_metrics

            entries.append(
                compute_query_metrics(
                    (tc.parameters or {}).get("query", ""),
                    results if isinstance(results, list) else [],
                    latency_ms=tc.duration_ms or 0,
                    top_k=len(results) if isinstance(results, list) else 5,
                    source="tool",
                )
            )

    return entries


def merge_session_meta(existing: Optional[dict[str, Any]], patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge patch into existing session meta without dropping other keys."""
    meta = dict(existing or {})
    meta.update(patch)
    return meta


async def finalize_session_metrics(
    db: AsyncSession,
    session_id: int,
    token_usage: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Merge token usage and RAG aggregates into session meta. Returns meta patch."""
    result = await db.execute(
        select(DBSession).where(DBSession.id == session_id)
    )
    db_session = result.scalar_one_or_none()
    if db_session is None:
        return {}

    tc_result = await db.execute(
        select(ToolCall).where(ToolCall.session_id == session_id)
    )
    tool_calls = list(tc_result.scalars().all())

    meta = dict(db_session.meta or {})
    rag_entries = collect_rag_entries_from_session(meta, tool_calls)
    patch: dict[str, Any] = {
        "rag_metrics": aggregate_session_rag_metrics(rag_entries),
    }
    if token_usage:
        patch["token_usage"] = token_usage

    db_session.meta = merge_session_meta(meta, patch)
    return db_session.meta
