"""
Embedding and vector search via ZeroEntropy (zembed-1) + Qdrant.

Responsibilities:
- Embed text using ZeroEntropy zembed-1 (retrieval-optimized, asymmetric)
- Upsert chunks into Qdrant with founder/source metadata as payload
- Search by semantic similarity, optionally filtered to one founder
- Ensure the Qdrant collection exists on first use
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from zeroentropy import ZeroEntropy
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

# zembed-1 default dimension
EMBEDDING_DIM = 2560
EMBED_MODEL = "zembed-1"


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


def _ze_client() -> ZeroEntropy:
    settings = get_settings()
    if not settings.zeroentropy_api_key:
        raise RuntimeError("ZEROENTROPY_API_KEY is not set")
    return ZeroEntropy(api_key=settings.zeroentropy_api_key)


def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    """Embed a batch of texts. input_type is 'document' or 'query'."""
    client = _ze_client()
    vectors = []
    for text in texts:
        response = client.models.embed(
            model=EMBED_MODEL,
            input_type=input_type,
            input=text,
            dimensions=EMBEDDING_DIM,
            encoding_format="float",
        )
        vectors.append(response.results[0].embedding)
    return vectors


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
    """Embed document chunks (asymmetric — document side)."""
    return _embed(texts, input_type="document")


def embed_query(text: str) -> list[float]:
    """Embed a search query (asymmetric — query side)."""
    return _embed([text], input_type="query")[0]


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

    logger.info("Embedding %d chunks via ZeroEntropy", len(texts))
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
    vector = embed_query(query)

    conditions = []
    if subject_id:
        conditions.append(FieldCondition(key="subject_id", match=MatchValue(value=subject_id)))
    if source_type:
        conditions.append(FieldCondition(key="source_type", match=MatchValue(value=source_type)))

    query_filter = Filter(must=conditions) if conditions else None

    settings = get_settings()
    client = _qdrant_client()
    hits = client.search(
        collection_name=settings.qdrant_collection,
        query_vector=vector,
        query_filter=query_filter,
        limit=limit,
        score_threshold=score_threshold,
        with_payload=True,
    )

    return [
        SearchResult(
            chunk_id=str(hit.id),
            score=hit.score,
            text=(hit.payload or {}).get("text", ""),
            subject_id=(hit.payload or {}).get("subject_id", ""),
            source_id=(hit.payload or {}).get("source_id", ""),
            source_type=(hit.payload or {}).get("source_type", ""),
            source_url=(hit.payload or {}).get("source_url", ""),
            metadata={
                k: v for k, v in (hit.payload or {}).items()
                if k not in ("text", "subject_id", "source_id", "source_type", "source_url")
            },
        )
        for hit in hits
    ]
