"""
Embedding and vector search via Voyage AI + Qdrant.

Responsibilities:
- Embed text using Voyage AI voyage-3 (retrieval-optimized)
- Upsert chunks into Qdrant with founder/source metadata as payload
- Search by semantic similarity, optionally filtered to one founder
- Ensure the Qdrant collection exists on first use
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    Filter,
    FieldCondition,
    MatchValue,
    PointStruct,
    VectorParams,
)

from newsletter.config import get_settings

logger = logging.getLogger(__name__)

# voyage-3 produces 1024-dimensional vectors
EMBEDDING_DIM = 1024
VOYAGE_EMBED_URL = "https://api.voyageai.com/v1/embeddings"
VOYAGE_MODEL = "voyage-3"


@dataclass
class SearchResult:
    chunk_id: str
    score: float
    text: str
    subject_id: str
    source_id: str
    source_type: str
    source_url: str
    metadata: dict[str, Any]


def _voyage_embed(texts: list[str], input_type: str) -> list[list[float]]:
    """Call Voyage AI embeddings API. input_type is 'document' or 'query'."""
    settings = get_settings()
    if not settings.voyage_api_key:
        raise RuntimeError("VOYAGE_API_KEY is not set")

    response = httpx.post(
        VOYAGE_EMBED_URL,
        headers={"Authorization": f"Bearer {settings.voyage_api_key}"},
        json={"model": VOYAGE_MODEL, "input": texts, "input_type": input_type},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    # API returns [{object, embedding, index}, ...] sorted by index
    return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]


def _qdrant_client() -> QdrantClient:
    settings = get_settings()
    if not settings.qdrant_url:
        raise RuntimeError("QDRANT_URL is not set")
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


def ensure_collection() -> None:
    """Create the Qdrant collection if it doesn't exist yet."""
    settings = get_settings()
    client = _qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection '%s'", settings.qdrant_collection)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed a batch of document chunks (asymmetric — document side)."""
    return _voyage_embed(texts, input_type="document")


def embed_query(text: str) -> list[float]:
    """Embed a search query (asymmetric — query side)."""
    return _voyage_embed([text], input_type="query")[0]


def upsert_chunks(chunks: list[dict[str, Any]]) -> int:
    """
    Embed and upsert a list of chunks into Qdrant.

    Each chunk dict must have:
        id          str   — the Chunk.id from Postgres (used as Qdrant point ID)
        text        str   — the text to embed
        subject_id  str
        source_id   str
        source_type str
        source_url  str

    Optional keys are passed through as payload metadata.
    Returns number of points upserted.
    """
    if not chunks:
        return 0

    settings = get_settings()
    texts = [c["text"] for c in chunks]

    logger.info("Embedding %d chunks via Voyage AI", len(texts))
    vectors = embed_documents(texts)

    points = []
    for chunk, vector in zip(chunks, vectors):
        payload = {
            "text": chunk["text"],
            "subject_id": chunk["subject_id"],
            "source_id": chunk["source_id"],
            "source_type": chunk["source_type"],
            "source_url": chunk["source_url"],
        }
        # pass through any extra metadata (e.g. timestamp_seconds, ordinal)
        for key in chunk:
            if key not in ("id", "text", "subject_id", "source_id", "source_type", "source_url"):
                payload[key] = chunk[key]

        points.append(PointStruct(id=chunk["id"], vector=vector, payload=payload))

    client = _qdrant_client()
    client.upsert(collection_name=settings.qdrant_collection, points=points)
    logger.info("Upserted %d points into Qdrant", len(points))
    return len(points)


def search(
    query: str,
    *,
    subject_id: str | None = None,
    source_type: str | None = None,
    limit: int = 8,
    score_threshold: float = 0.45,
) -> list[SearchResult]:
    """
    Semantic search over the founders corpus.

    Pass subject_id to scope the search to one founder.
    Pass source_type to filter by e.g. 'youtube_transcript' or 'web'.
    """
    settings = get_settings()
    vector = embed_query(query)

    conditions = []
    if subject_id:
        conditions.append(FieldCondition(key="subject_id", match=MatchValue(value=subject_id)))
    if source_type:
        conditions.append(FieldCondition(key="source_type", match=MatchValue(value=source_type)))

    query_filter = Filter(must=conditions) if conditions else None

    client = _qdrant_client()
    hits = client.search(
        collection_name=settings.qdrant_collection,
        query_vector=vector,
        query_filter=query_filter,
        limit=limit,
        score_threshold=score_threshold,
        with_payload=True,
    )

    results = []
    for hit in hits:
        p = hit.payload or {}
        results.append(
            SearchResult(
                chunk_id=str(hit.id),
                score=hit.score,
                text=p.get("text", ""),
                subject_id=p.get("subject_id", ""),
                source_id=p.get("source_id", ""),
                source_type=p.get("source_type", ""),
                source_url=p.get("source_url", ""),
                metadata={k: v for k, v in p.items() if k not in ("text", "subject_id", "source_id", "source_type", "source_url")},
            )
        )

    return results
