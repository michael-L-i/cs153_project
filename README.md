# FIRSTHAND — Founder Research & Newsletter Platform

An editorial system for researching, storing, and publishing long-form founder case studies. The end goal is a directory of founders that people can read about — and eventually converse with as a "virtual founder" persona trained on their public record.

The research layer is the source of truth. Downstream agents write newsletters, generate case studies, and eventually power the chat experience from structured research outputs.

## Vision and architecture

```
YouTube / Web / PDFs / Transcripts
        ↓
   LlamaIndex  (parsing, chunking, ingestion)
        ↓
  Voyage AI voyage-3-large  (embedding API — retrieval-optimized)
        ↓
    Qdrant Cloud  (vector storage + filtered search)
        ↓
   Supabase / Postgres  (founder directory, sources, metadata)

         ↕  phase 2 — chat
           Mem0  (persistent memory layer — fact extraction, long-term recall)

         ↕  phase 3 — relational depth
       Graphiti / Neo4j  (knowledge graph — people, companies, events, investors)
```

### Why each layer

| Layer | Tool | Reason |
|---|---|---|
| Parsing & ingestion | LlamaIndex | Handles PDFs, YouTube transcripts, HTML natively. Most mature RAG-first framework. |
| Embedding | Voyage AI `voyage-3-large` | Retrieval-optimized, leads MTEB retrieval benchmarks, asymmetric query/doc mode |
| Vector search | Qdrant Cloud | Best filtered search (e.g. search within a single founder's corpus), open source |
| Structured data | Supabase (Postgres) | Founder directory, source URLs, metadata, tags — relational data belongs here |
| Memory (chat) | Mem0 | Extracts discrete facts from conversations, handles long-term recall across sessions |
| Knowledge graph | Graphiti | Temporal knowledge graphs for AI agents; encodes founder → company → investor relationships |

### Chunking strategy

Retrieval quality depends as much on chunking as on embedding model choice.

- **YouTube transcripts**: sentence-boundary chunks, 250–350 tokens, 40-token overlap
- **PDFs / long-form articles**: recursive paragraph → sentence, 400–600 tokens, 80-token overlap
- **All chunks store**: `founder_id`, `source_url`, `source_type`, `scraped_at`, `timestamp_in_video`

The `founder_id` metadata field is what enables Qdrant filtered search — queries scoped to one person's corpus rather than the full index.

### Phased build plan

**Phase 1 — Ingestion + retrieval (current focus)**
LlamaIndex parses scraped content → Voyage AI embeds → Qdrant stores with metadata → Supabase holds the directory. Query: "find everything in the knowledge base about how Mira talked about her first hire."

**Phase 2 — Chat / virtual founder**
Drop Mem0 on top of the existing stack. Conversations extract persistent facts per founder. The system accumulates memory across sessions without ballooning token costs.

**Phase 3 — Relational depth**
Add Graphiti. Build the graph: `Mira → worked at → Company X → knows → Investor Y`. Enables multi-hop reasoning: "find founders in the directory who share background patterns with Mira."

---

## Current implementation (phase 1, research layer)

The current implementation is intentionally research-first:

- ingest one founder/company target at a time
- discover and normalize source material
- extract claims, events, and quotes with provenance
- assemble a structured dossier
- expose a separate writer-input contract for downstream newsletter agents

## Current shape

- `FastAPI` app with a local-first setup
- `SQLAlchemy` data model for subjects, sources, artifacts, documents, chunks, claims, events, quotes, dossiers, and jobs
- in-process research job runner with explicit stages
- source adapter interface plus initial web/YouTube/X adapters
- filesystem object storage for raw artifacts
- dossier and writer-packet assembly

The external source integrations are scaffolded to prefer official APIs where configured, while still supporting local development without them.

## Quickstart

```bash
uv sync
uv run uvicorn newsletter.main:app --reload
```

The app will create the configured database tables on startup.

Default local configuration uses SQLite and a filesystem object store under `./var/object-store`.

## Environment

Copy `.env.example` to `.env` and adjust as needed.

Important variables:

- `DATABASE_URL`
- `OBJECT_STORE_ROOT`
- `DEFAULT_RESEARCH_JOB_MODE` (`background` or `inline`)
- `FIRECRAWL_API_KEY`
- `YOUTUBE_API_KEY`
- `X_BEARER_TOKEN`

## API surface

- `POST /subjects`
- `POST /research-jobs`
- `GET /research-jobs/{job_id}`
- `GET /subjects/{subject_id}/sources`
- `GET /subjects/{subject_id}/timeline`
- `GET /subjects/{subject_id}/dossier`
- `POST /writer-inputs`

## Notes

- v1 optimizes for evidence-backed research records over perfect extraction quality.
- The writer is treated as a separate consumer of the dossier contract.
- Retrieval is modeled around canonical chunks, claims, events, and quotes rather than a single monolithic blob.

