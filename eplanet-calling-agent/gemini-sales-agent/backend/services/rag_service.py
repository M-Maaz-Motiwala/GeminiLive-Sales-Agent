"""Pinecone RAG service — embed, upsert, query knowledge base."""
import asyncio
import logging
import time
from typing import Optional

from google import genai
from google.genai import types
from pinecone import Pinecone, ServerlessSpec

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_pinecone_client: Optional[Pinecone] = None
_genai_client: Optional[genai.Client] = None
_index_ready: Optional[str] = None  # cache: index name we verified ready

EMBED_DIMENSION = 768
EMBED_MODEL = "gemini-embedding-001"


def _get_pinecone() -> Pinecone:
    global _pinecone_client
    if not settings.pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY is not configured")
    if _pinecone_client is None:
        _pinecone_client = Pinecone(api_key=settings.pinecone_api_key)
    return _pinecone_client


def _get_genai() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=settings.gemini_api_key)
    return _genai_client


def _index_names(pc: Pinecone) -> list[str]:
    return [i.name for i in pc.list_indexes()]


def _wait_index_ready(pc: Pinecone, name: str, timeout_sec: int = 120) -> None:
    """Poll until Pinecone reports the index is ready."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            desc = pc.describe_index(name)
            status = getattr(desc, "status", None)
            ready = getattr(status, "ready", None) if status else None
            if ready is True:
                return
            if isinstance(status, dict) and status.get("ready"):
                return
        except Exception as exc:
            logger.debug("Waiting for index %s: %s", name, exc)
        time.sleep(2)
    raise TimeoutError(f"Pinecone index {name} not ready after {timeout_sec}s")


def ensure_pinecone_index() -> str:
    """Create the configured index if missing; wait until ready. Idempotent."""
    global _index_ready
    name = settings.pinecone_index_name
    if _index_ready == name:
        return name

    pc = _get_pinecone()
    if name not in _index_names(pc):
        region = settings.pinecone_environment or "us-east-1"
        logger.info("Creating Pinecone index %s (region=%s)", name, region)
        pc.create_index(
            name=name,
            dimension=EMBED_DIMENSION,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region=region),
        )
        logger.info("Pinecone index %s created; waiting for ready", name)
        _wait_index_ready(pc, name)
    else:
        _wait_index_ready(pc, name)

    _index_ready = name
    return name


def _ensure_index():
    return _get_pinecone().Index(ensure_pinecone_index())


async def ensure_pinecone_index_async() -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, ensure_pinecone_index)


async def embed_text(text: str) -> list[float]:
    """Generate embedding using Gemini gemini-embedding-001 (768 dims)."""
    client = _get_genai()
    loop = asyncio.get_event_loop()

    def _embed() -> list[float]:
        result = client.models.embed_content(
            model=EMBED_MODEL,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=EMBED_DIMENSION),
        )
        vec = list(result.embeddings[0].values)
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    return await loop.run_in_executor(None, _embed)


async def upsert_chunks(doc_id: int, agent_id: Optional[int], chunks: list[str]) -> int:
    """Embed and upsert text chunks to Pinecone. Returns number of vectors upserted."""
    namespace = f"agent-{agent_id}" if agent_id else "global"
    index = await asyncio.get_event_loop().run_in_executor(None, _ensure_index)

    vectors = []
    for i, chunk in enumerate(chunks):
        try:
            embedding = await embed_text(chunk)
            vectors.append(
                {
                    "id": f"doc-{doc_id}-chunk-{i}",
                    "values": embedding,
                    "metadata": {
                        "doc_id": doc_id,
                        "chunk_index": i,
                        "text": chunk[:1000],
                    },
                }
            )
        except Exception as e:
            logger.error("Failed to embed chunk %d of doc %d: %s", i, doc_id, e)

    if vectors:
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: index.upsert(vectors=vectors, namespace=namespace)
        )

    return len(vectors)


async def query(text: str, agent_id: Optional[int], top_k: int = 5) -> list[dict]:
    """Query Pinecone for relevant chunks. Searches agent namespace + global."""
    if not settings.pinecone_api_key:
        return []

    embedding = await embed_text(text)
    index = await asyncio.get_event_loop().run_in_executor(None, _ensure_index)

    namespaces = ["global"]
    if agent_id:
        namespaces.insert(0, f"agent-{agent_id}")

    all_results = []
    for ns in namespaces:
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda ns=ns: index.query(
                    vector=embedding,
                    top_k=top_k,
                    namespace=ns,
                    include_metadata=True,
                ),
            )
            for match in result.matches:
                all_results.append(
                    {
                        "score": match.score,
                        "text": match.metadata.get("text", ""),
                        "doc_id": match.metadata.get("doc_id"),
                        "chunk_index": match.metadata.get("chunk_index"),
                        "namespace": ns,
                    }
                )
        except Exception as e:
            logger.warning("RAG query failed for namespace %s: %s", ns, e)

    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:top_k]


async def delete_document_vectors(doc_id: int, agent_id: Optional[int]) -> None:
    """Delete all vectors for a document from Pinecone."""
    if not settings.pinecone_api_key:
        return
    namespace = f"agent-{agent_id}" if agent_id else "global"
    index = await asyncio.get_event_loop().run_in_executor(None, _ensure_index)
    try:
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: index.delete(filter={"doc_id": {"$eq": doc_id}}, namespace=namespace),
        )
    except Exception as e:
        logger.error("Failed to delete vectors for doc %d: %s", doc_id, e)
