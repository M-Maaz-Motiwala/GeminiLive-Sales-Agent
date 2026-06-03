"""RAG tool — search the agent's Pinecone knowledge base."""
import logging
from typing import Optional

from backend.services import rag_service

logger = logging.getLogger(__name__)


async def search_knowledge_base(params: dict, agent_id: Optional[int] = None) -> dict:
    query = params.get("query", "")
    top_k = int(params.get("top_k", 5))
    if not query:
        return {"error": "query is required"}

    results = await rag_service.query(query, agent_id, top_k=top_k)
    if not results:
        return {"results": [], "message": "No relevant knowledge found."}

    return {
        "results": [
            {"text": r["text"], "score": round(r["score"], 3), "doc_id": r["doc_id"]}
            for r in results
        ]
    }
