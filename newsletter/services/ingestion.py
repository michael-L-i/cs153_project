"""
Ingestion worker: chunk a Document and upsert into Qdrant.

Called after a Document is written to Postgres. Produces Chunk rows
in Postgres (for provenance) and upserts vectors into Qdrant (for search).

Chunking strategy:
- YouTube transcripts: ~300 tokens, 40-token overlap, split at sentence boundaries
- Everything else: ~500 tokens, 80-token overlap, recursive paragraph→sentence
"""

from __future__ import annotations

import logging
import re
from uuid import uuid4

from sqlalchemy.orm import Session

from newsletter.models import Chunk, Document, Source
from newsletter.services.vector import ensure_collection, upsert_chunks

logger = logging.getLogger(__name__)

# approximate token counts using word count (1 token ≈ 0.75 words is too aggressive;
# 1 word ≈ 1.3 tokens is a safe estimate for mixed prose/transcripts)
_WORDS_PER_TOKEN = 0.75


def _token_estimate(text: str) -> int:
    return int(len(text.split()) / _WORDS_PER_TOKEN)


def _split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation, keeping the delimiter."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _chunk_text(
    text: str,
    target_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """
    Sentence-aware chunking with token-count targets and overlap.
    Returns a list of chunk strings.
    """
    sentences = _split_sentences(text)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        s_tokens = _token_estimate(sentence)

        if current_tokens + s_tokens > target_tokens and current:
            chunks.append(" ".join(current))
            # carry forward overlap: drop sentences from the front until
            # we're within the overlap budget
            while current and current_tokens - _token_estimate(current[0]) > overlap_tokens:
                current_tokens -= _token_estimate(current[0])
                current.pop(0)

        current.append(sentence)
        current_tokens += s_tokens

    if current:
        chunks.append(" ".join(current))

    return chunks


def _chunking_params(source_type: str) -> tuple[int, int]:
    """Return (target_tokens, overlap_tokens) for a given source type."""
    if "youtube" in source_type or "transcript" in source_type:
        return 300, 40
    return 500, 80


def ingest_document(document_id: str, db: Session) -> int:
    """
    Chunk a Document and upsert its vectors into Qdrant.

    Creates Chunk rows in Postgres with the chunk text (embedding field left
    empty — Qdrant is the vector store). Returns number of chunks produced.
    """
    doc: Document | None = db.get(Document, document_id)
    if doc is None:
        raise ValueError(f"Document {document_id} not found")

    source: Source = doc.source
    target_tokens, overlap_tokens = _chunking_params(source.source_type)

    raw_chunks = _chunk_text(doc.content_text, target_tokens, overlap_tokens)
    if not raw_chunks:
        logger.warning("Document %s produced no chunks (empty content?)", document_id)
        return 0

    ensure_collection()

    # build Chunk DB rows and Qdrant payloads together
    db_chunks: list[Chunk] = []
    qdrant_payloads: list[dict] = []

    for ordinal, text in enumerate(raw_chunks):
        chunk_id = str(uuid4())
        db_chunks.append(
            Chunk(
                id=chunk_id,
                document_id=document_id,
                ordinal=ordinal,
                text=text,
                embedding=[],  # stored in Qdrant, not here
                metadata_json={
                    "source_type": source.source_type,
                    "source_url": source.url,
                },
            )
        )
        qdrant_payloads.append(
            {
                "id": chunk_id,
                "text": text,
                "subject_id": source.subject_id,
                "source_id": source.id,
                "source_type": source.source_type,
                "source_url": source.url,
                "document_id": document_id,
                "ordinal": ordinal,
            }
        )

    # write chunk records to Postgres first (provenance)
    db.add_all(db_chunks)
    db.commit()

    # then embed + upsert into Qdrant
    upserted = upsert_chunks(qdrant_payloads)
    logger.info(
        "Ingested document %s: %d chunks → Qdrant (%s, subject %s)",
        document_id,
        upserted,
        source.source_type,
        source.subject_id,
    )
    return upserted


def ingest_all_pending(db: Session) -> dict[str, int]:
    """
    Ingest all Documents that have no Chunk rows yet.
    Returns {document_id: chunk_count}.
    """
    from sqlalchemy import select, not_, exists

    stmt = select(Document).where(
        not_(exists().where(Chunk.document_id == Document.id))
    )
    pending = db.scalars(stmt).all()

    results = {}
    for doc in pending:
        try:
            count = ingest_document(doc.id, db)
            results[doc.id] = count
        except Exception:
            logger.exception("Failed to ingest document %s", doc.id)
            results[doc.id] = -1

    return results
