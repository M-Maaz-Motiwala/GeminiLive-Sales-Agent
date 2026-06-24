"""RAG retrieval evaluation metrics (runtime, per query and per session)."""
from __future__ import annotations

import statistics
from typing import Any, Optional

# Cosine similarity bands for Pinecone (normalized vectors → score in ~[0, 1]).
SCORE_HIGH = 0.75
SCORE_MEDIUM = 0.55


def relevance_band(score: float) -> str:
    if score >= SCORE_HIGH:
        return "high"
    if score >= SCORE_MEDIUM:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def compute_query_metrics(
    query: str,
    results: list[dict],
    *,
    latency_ms: int,
    top_k: int,
    source: str = "search",
) -> dict[str, Any]:
    """Build evaluation metrics for a single RAG retrieval."""
    scores = [float(r.get("score", 0)) for r in results if r.get("score") is not None]
    hit_count = len(results)

    metrics: dict[str, Any] = {
        "source": source,
        "query": query[:500],
        "top_k": top_k,
        "hit_count": hit_count,
        "latency_ms": latency_ms,
        "has_results": hit_count > 0,
    }

    if not scores:
        metrics.update({
            "top_score": 0.0,
            "min_score": 0.0,
            "avg_score": 0.0,
            "median_score": 0.0,
            "relevance_band": "none",
            "high_relevance_hits": 0,
            "medium_relevance_hits": 0,
            "low_relevance_hits": 0,
            "scores": [],
        })
        return metrics

    metrics.update({
        "top_score": round(max(scores), 4),
        "min_score": round(min(scores), 4),
        "avg_score": round(statistics.mean(scores), 4),
        "median_score": round(statistics.median(scores), 4),
        "relevance_band": relevance_band(max(scores)),
        "high_relevance_hits": sum(1 for s in scores if s >= SCORE_HIGH),
        "medium_relevance_hits": sum(1 for s in scores if SCORE_MEDIUM <= s < SCORE_HIGH),
        "low_relevance_hits": sum(1 for s in scores if 0 < s < SCORE_MEDIUM),
        "scores": [round(s, 4) for s in scores],
    })
    return metrics


def aggregate_session_rag_metrics(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize all RAG queries in a session (tool calls + preload)."""
    if not entries:
        return {
            "query_count": 0,
            "total_hits": 0,
            "avg_top_score": 0.0,
            "avg_latency_ms": 0.0,
            "high_relevance_queries": 0,
            "no_result_queries": 0,
        }

    top_scores = [e.get("top_score", 0) for e in entries]
    latencies = [e.get("latency_ms", 0) for e in entries]
    return {
        "query_count": len(entries),
        "total_hits": sum(e.get("hit_count", 0) for e in entries),
        "avg_top_score": round(statistics.mean(top_scores), 4) if top_scores else 0.0,
        "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
        "high_relevance_queries": sum(
            1 for e in entries if e.get("relevance_band") == "high"
        ),
        "no_result_queries": sum(1 for e in entries if not e.get("has_results")),
        "entries": entries,
    }


def metrics_from_preloaded_kb(preloaded_kb: Optional[dict]) -> Optional[dict[str, Any]]:
    """Derive RAG metrics from call-start KB preload metadata."""
    if not preloaded_kb or preloaded_kb.get("skipped"):
        return None
    chunks = preloaded_kb.get("chunks") or []
    if not chunks:
        return None
    scores = [float(c.get("score", 0)) for c in chunks]
    query = preloaded_kb.get("query", "")
    results = [{"score": s, "text": ""} for s in scores]
    return compute_query_metrics(
        query,
        results,
        latency_ms=int(preloaded_kb.get("latency_ms", 0)),
        top_k=len(chunks),
        source="preload",
    )
