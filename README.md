# FIRSTHAND — Founder Research & Newsletter Platform

An editorial system for researching, storing, and publishing long-form founder case studies. The end goal is a directory of founders that people can read about — and eventually converse with as a "virtual founder" persona trained on their public record.

The research layer is the source of truth. Downstream agents write newsletters, generate case studies, and eventually power the chat experience from structured research outputs.

## Vision and architecture

```
YouTube / Web / Articles
        ↓
   Exa neural search  (URL discovery)
        ↓
   Firecrawl / httpx  (scraping) + youtube-transcript-api  (transcripts)
        ↓
   Custom sentence chunker  (300 or 500 token windows)
        ↓
  ZeroEntropy zembed-1  (embedding API — retrieval-optimized)
        ↓
    Qdrant Cloud  (vector storage + filtered search)
        ↓
   SQLite / Postgres via SQLAlchemy  (founder directory, sources, metadata)

         ↕  phase 2 — chat
           Mem0  (persistent memory layer — fact extraction, long-term recall)

         ↕  phase 3 — relational depth
       Graphiti / Neo4j  (knowledge graph — people, companies, events, investors)
```

### Why each layer

| Layer | Tool | Reason |
|---|---|---|
| URL discovery | Exa | Neural search finds founder interviews, podcasts, and articles without manual curation |
| Web scraping | Firecrawl (+ httpx fallback) | Returns clean markdown from behind JS-heavy pages; httpx covers simple HTML |
| Transcript extraction | youtube-transcript-api | Fetches real auto-generated transcripts without YouTube Data API quota |
| Chunking | Custom sentence-aware splitter | Tuned per source type (transcripts vs. articles); sentence boundaries prevent broken context |
| Embedding | ZeroEntropy `zembed-1` | Retrieval-optimized, asymmetric query/doc mode, 2560-dim vectors |
| Vector search | Qdrant Cloud | Best filtered search (e.g. search within a single founder's corpus), open source |
| Structured data | SQLAlchemy (SQLite local / Postgres in prod) | Founder directory, source URLs, metadata, tags — relational data belongs here |
| Memory (chat) | Mem0 | Extracts discrete facts from conversations, handles long-term recall across sessions |
| Knowledge graph | Graphiti | Temporal knowledge graphs for AI agents; encodes founder → company → investor relationships |

### Chunking strategy

Retrieval quality depends as much on chunking as on embedding model choice.

- **YouTube transcripts**: sentence-boundary chunks, 300 tokens, 40-token overlap
- **Web articles / long-form**: sentence-boundary chunks, 500 tokens, 80-token overlap
- **All chunks store**: `founder_id`, `source_url`, `source_type`, `ordinal`

The `subject_id` metadata field is what enables Qdrant filtered search — queries scoped to one person's corpus rather than the full index.

### Phased build plan

**Phase 1 — Ingestion + retrieval (current focus)**
Exa discovers source URLs → Firecrawl scrapes web pages or `youtube-transcript-api` pulls transcripts → custom chunker splits → ZeroEntropy embeds → Qdrant stores with metadata → SQLite/Postgres holds the directory. Query: "find everything in the knowledge base about how Mira talked about her first hire."

**Phase 2 — Chat / virtual founder**
Drop Mem0 on top of the existing stack. Conversations extract persistent facts per founder. The system accumulates memory across sessions without ballooning token costs.

**Phase 3 — Relational depth**
Add Graphiti. Build the graph: `Mira → worked at → Company X → knows → Investor Y`. Enables multi-hop reasoning: "find founders in the directory who share background patterns with Mira."

---

## Current implementation (phase 1, research layer)

The current implementation is intentionally research-first:

- ingest one founder/company target at a time
- discover and normalize source material via Exa + Firecrawl
- chunk, embed, and upsert into Qdrant
- persist provenance in Postgres/SQLite (subjects, sources, artifacts, documents, chunks)
- expose a REST API and a CLI for triggering the pipeline

## Current shape

- **FastAPI** app with a local-first setup
- **CLI** (`python -m newsletter.cli`) for one-command pipeline runs
- **SQLAlchemy** data model for subjects, sources, artifacts, documents, chunks, claims, events, quotes, dossiers, and jobs
- **Exa** adapter for neural URL discovery
- **Firecrawl** adapter (+ httpx fallback) for web scraping
- **YouTube** adapter using `youtube-transcript-api` for real transcripts
- **Custom sentence-aware chunker** in `newsletter/services/ingestion.py`
- **ZeroEntropy `zembed-1`** for embedding; **Qdrant** for vector storage and filtered search
- **Filesystem object store** for raw artifacts (`./var/object-store`)
- Dossier and writer-packet assembly for downstream newsletter agents
- Static web frontend in `web/` (editorial landing page)

## Quickstart

### API server

```bash
uv sync
uv run uvicorn newsletter.main:app --reload
```

The app creates the configured database tables on startup. Default local config uses SQLite and a filesystem object store under `./var/object-store`.

### CLI pipeline

```bash
uv run python -m newsletter.cli research "Peter Steinberger" "founder of OpenClaw"
uv run python -m newsletter.cli research "Paul Graham"
```

This runs the full pipeline: Exa discovery → fetch → normalize → chunk → embed → Qdrant. Prints progress and a `curl` example for semantic search when done.

### Local Postgres + MinIO (optional)

```bash
docker compose up -d
```

Then set `DATABASE_URL=postgresql+psycopg2://newsletter:newsletter@localhost:5432/newsletter` in `.env`.

## Environment

Copy `.env.example` to `.env` and adjust as needed.

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | no | Defaults to `sqlite:///./newsletter.db` |
| `OBJECT_STORE_ROOT` | no | Defaults to `./var/object-store` |
| `DEFAULT_RESEARCH_JOB_MODE` | no | `background` or `inline` (default: `background`) |
| `EXA_API_KEY` | yes | Exa neural search — URL discovery |
| `FIRECRAWL_API_KEY` | recommended | Clean markdown scraping; falls back to httpx without it |
| `ZEROENTROPY_API_KEY` | yes | Embedding via ZeroEntropy `zembed-1` |
| `QDRANT_URL` | yes | Qdrant Cloud or self-hosted instance URL |
| `QDRANT_API_KEY` | yes (cloud) | Not required for local Qdrant |
| `QDRANT_COLLECTION` | no | Defaults to `founders` |
| `YOUTUBE_API_KEY` | no | Not required; transcripts use `youtube-transcript-api` directly |
| `X_BEARER_TOKEN` | no | X/Twitter adapter (scaffolded, not yet wired) |

## API surface

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Health check |
| `POST` | `/subjects` | Create a founder subject |
| `POST` | `/research-jobs` | Trigger a research job for a subject |
| `GET` | `/research-jobs/{job_id}` | Poll research job status |
| `GET` | `/subjects/{subject_id}/sources` | List all sources for a subject |
| `GET` | `/subjects/{subject_id}/timeline` | Ordered event timeline |
| `GET` | `/subjects/{subject_id}/dossier` | Latest assembled dossier |
| `POST` | `/documents/{document_id}/ingest` | Manually trigger chunk + embed for a document |
| `GET` | `/search` | Semantic search (`?q=...&subject_id=...&limit=8`) |
| `POST` | `/writer-inputs` | Build a writer packet from a subject's dossier |

## Notes

- v1 optimizes for evidence-backed research records over perfect extraction quality.
- The writer is treated as a separate consumer of the dossier contract.
- Retrieval is modeled around canonical chunks with `subject_id` payload indexes in Qdrant, enabling per-founder scoped search.
