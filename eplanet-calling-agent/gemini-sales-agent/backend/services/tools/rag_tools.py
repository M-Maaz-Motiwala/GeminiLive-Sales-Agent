"""RAG tool — search the agent's Pinecone knowledge base."""
import logging
from typing import Optional

from backend.services import rag_service
from backend.services.rag_metrics import compute_query_metrics

logger = logging.getLogger(__name__)


async def search_knowledge_base(params: dict, agent_id: Optional[int] = None) -> dict:
    query = params.get("query", "")
    top_k = int(params.get("top_k", 5))
    if not query:
        return {"error": "query is required"}

    results, latency_ms = await rag_service.query_with_timing(query, agent_id, top_k=top_k)
    metrics = compute_query_metrics(
        query, results, latency_ms=latency_ms, top_k=top_k, source="tool"
    )

    if not results:
        return {
            "results": [],
            "message": "No relevant knowledge found.",
            "metrics": metrics,
        }

    return {
        "results": [
            {"text": r["text"], "score": round(r["score"], 3), "doc_id": r["doc_id"]}
            for r in results
        ],
        "metrics": metrics,
    }
