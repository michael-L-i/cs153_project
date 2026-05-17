"""
Hybrid search: dense (ZeroEntropy zembed-1) + sparse (BM25 via fastembed).

Dense vectors capture semantic meaning. Sparse BM25 vectors catch exact
keyword matches — names, dates, company names, terminology. Both are stored
in Qdrant under named vector slots ("dense" / "sparse") and fused at query
time using Reciprocal Rank Fusion (RRF).

RRF only uses ranking order, so the incompatible score scales between
cosine similarity (dense) and BM25 (sparse) don't matter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from zeroentropy import ZeroEntropy

from newsletter.config import get_settings

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 2560
EMBED_MODEL = "zembed-1"
DENSE = "dense"
SPARSE = "sparse"


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


@lru_cache(maxsize=1)
def _bm25_model() -> SparseTextEmbedding:
    return SparseTextEmbedding(model_name="Qdrant/bm25")


def _ze_client() -> ZeroEntropy:
    settings = get_settings()
    if not settings.zeroentropy_api_key:
        raise RuntimeError("ZEROENTROPY_API_KEY is not set")
    return ZeroEntropy(api_key=settings.zeroentropy_api_key)


def _qdrant_client() -> QdrantClient:
    settings = get_settings()
    if not settings.qdrant_url:
        raise RuntimeError("QDRANT_URL is not set")
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


def _dense_embed(texts: list[str], input_type: str) -> list[list[float]]:
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


def _sparse_embed(texts: list[str]) -> list[SparseVector]:
    model = _bm25_model()
    results = []
    for embedding in model.embed(texts):
        results.append(SparseVector(
            indices=embedding.indices.tolist(),
            values=embedding.values.tolist(),
        ))
    return results


def embed_documents(texts: list[str]) -> list[list[float]]:
    return _dense_embed(texts, input_type="document")


def embed_query(text: str) -> list[float]:
    return _dense_embed([text], input_type="query")[0]


def ensure_collection() -> None:
    """Create the Qdrant collection with dense + sparse vector slots if needed."""
    settings = get_settings()
    client = _qdrant_client()
    existing = {c.name for c in client.get_collections().collections}

    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config={
                DENSE: VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                SPARSE: SparseVectorParams(index=SparseIndexParams()),
            },
        )
        logger.info("Created Qdrant collection '%s' (dense + sparse)", settings.qdrant_collection)

    for field in ("subject_id", "source_type", "source_id"):
        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )


def upsert_chunks(chunks: list[dict[str, Any]]) -> int:
    """
    Embed and upsert chunks into Qdrant with both dense and sparse vectors.

    Each chunk dict must have: id, text, subject_id, source_id, source_type, source_url.
    """
    if not chunks:
        return 0

    settings = get_settings()
    texts = [c["text"] for c in chunks]

    logger.info("Embedding %d chunks (dense + sparse)", len(texts))
    dense_vectors = embed_documents(texts)
    sparse_vectors = _sparse_embed(texts)

    points = []
    for chunk, dense, sparse in zip(chunks, dense_vectors, sparse_vectors):
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

        points.append(PointStruct(
            id=chunk["id"],
            vector={DENSE: dense, SPARSE: sparse},
            payload=payload,
        ))

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
) -> list[SearchResult]:
    """
    Hybrid semantic + keyword search over the founders corpus.

    Retrieves top candidates via both dense and sparse vectors independently,
    then fuses the ranked lists with RRF. Pass subject_id to scope to one founder.
    """
    dense_vector = embed_query(query)
    sparse_vector = _sparse_embed([query])[0]

    conditions = []
    if subject_id:
        conditions.append(FieldCondition(key="subject_id", match=MatchValue(value=subject_id)))
    if source_type:
        conditions.append(FieldCondition(key="source_type", match=MatchValue(value=source_type)))

    query_filter = Filter(must=conditions) if conditions else None

    settings = get_settings()
    client = _qdrant_client()

    hits = client.query_points(
        collection_name=settings.qdrant_collection,
        prefetch=[
            Prefetch(query=dense_vector, using=DENSE, limit=20, filter=query_filter),
            Prefetch(query=sparse_vector, using=SPARSE, limit=20, filter=query_filter),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=limit,
        with_payload=True,
    ).points

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
