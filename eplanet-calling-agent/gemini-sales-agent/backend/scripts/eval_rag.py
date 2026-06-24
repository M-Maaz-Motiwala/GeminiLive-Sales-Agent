"""Run RAG retrieval evaluation against labeled questions (offline).

Usage:
  python -m backend.scripts.eval_rag [--agent-id 1] [--top-k 5]

Expects PINECONE_API_KEY and GEMINI_API_KEY in environment.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from backend.services import rag_service
from backend.services.rag_metrics import compute_query_metrics

# Minimal golden set — extend per agent/knowledge base.
GOLDEN_QUERIES = [
    {"query": "What services does Trangotech offer?", "min_top_score": 0.5},
    {"query": "lead qualification budget timeline", "min_top_score": 0.45},
    {"query": "support FAQ refund policy", "min_top_score": 0.45},
]


async def run_eval(agent_id: int | None, top_k: int) -> dict:
    entries = []
    passed = 0
    for item in GOLDEN_QUERIES:
        query = item["query"]
        results, latency_ms = await rag_service.query_with_timing(query, agent_id, top_k=top_k)
        metrics = compute_query_metrics(query, results, latency_ms=latency_ms, top_k=top_k, source="eval")
        ok = metrics["top_score"] >= item.get("min_top_score", 0.4)
        if ok:
            passed += 1
        metrics["pass"] = ok
        metrics["min_top_score"] = item.get("min_top_score", 0.4)
        entries.append(metrics)

    total = len(entries) or 1
    return {
        "agent_id": agent_id,
        "top_k": top_k,
        "queries": len(entries),
        "pass_rate": round(passed / total, 3),
        "passed": passed,
        "failed": len(entries) - passed,
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate RAG retrieval quality")
    parser.add_argument("--agent-id", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    report = asyncio.run(run_eval(args.agent_id, args.top_k))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
