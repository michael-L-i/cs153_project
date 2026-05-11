# FIRSTHAND — Founder Research & Newsletter Platform

A growing directory of founders, each one a self-contained knowledge sandbox. The system scrapes public content, embeds it into a vector database, and serves it to LLM-powered skills that can answer questions, write newsletters, generate case studies, and eventually power a conversational "virtual founder" experience.

The research pipeline is the foundation. Everything else — newsletters, Q&A, chat — runs on top of it.

## The founder sandbox model

Every founder is a completely isolated knowledge unit keyed by `founder_id`. All their data — scraped articles, YouTube transcripts, embeddings — is scoped to that ID and never mixes with other founders.

```
founder_id
  ├── sources       every URL discovered and scraped
  ├── documents     normalized text per source
  ├── chunks        sentence-window splits, ready for retrieval
  └── vectors       chunks embedded in Qdrant, filterable by founder_id
```

Adding a founder is one command. The rest is automatic.

## How skills work

Skills are functions that take a `founder_id` and return generated output. They always follow the same pattern:

```
query / task
    ↓
embed the query (ZeroEntropy)
    ↓
retrieve top-k relevant chunks from Qdrant, filtered by founder_id
    ↓
pass chunks + prompt to LLM (Claude)
    ↓
answer / newsletter / case study
```

The LLM does all interpretation. The vector store does retrieval. No rule-based extraction in between.

Skills planned:
- `ask(founder_id, question)` — Q&A about a specific founder
- `write_newsletter(founder_id)` — long-form newsletter from their story
- `write_case_study(founder_id)` — structured PDF-ready case study
- `chat(founder_id, message)` — conversational interface (phase 2)

## Architecture

```
YouTube / Web / Articles
        ↓
   Exa neural search        URL discovery
        ↓
   Firecrawl / httpx        web scraping  (+ youtube-transcript-api for video)
        ↓
   Custom sentence chunker  300 tok / 40 overlap for transcripts
                            500 tok / 80 overlap for articles
        ↓
   ZeroEntropy zembed-1     embedding (2560-dim, asymmetric query/doc)
        ↓
   Qdrant Cloud             vector store, one collection, filtered by founder_id
        ↓
   SQLite / Postgres        provenance ledger (subjects, sources, documents, chunks)

         ↕  phase 2
       Mem0                 persistent memory for conversational chat

         ↕  phase 3
       Graphiti / Neo4j     knowledge graph for relational queries across founders
```

## Quickstart

### Add a founder

```bash
uv sync
uv run python -m newsletter.cli research "Paul Graham" "founder of Y Combinator"
```

This runs the full pipeline: discover URLs → scrape → chunk → embed → upsert to Qdrant. Takes 1–3 minutes depending on how many sources Exa finds.

### Run the API server

```bash
uv run uvicorn newsletter.main:app --reload
```

Then search semantically:

```bash
curl 'http://localhost:8000/search?q=how+did+he+find+the+first+customers&subject_id=<founder_id>'
```

### Local Postgres + MinIO (optional, for production-like local dev)

```bash
docker compose up -d
# then set DATABASE_URL=postgresql+psycopg2://newsletter:newsletter@localhost:5432/newsletter in .env
```

## Environment

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `EXA_API_KEY` | yes | Neural search for URL discovery |
| `FIRECRAWL_API_KEY` | recommended | Clean markdown scraping; falls back to httpx |
| `ZEROENTROPY_API_KEY` | yes | Embedding via ZeroEntropy `zembed-1` |
| `QDRANT_URL` | yes | Qdrant Cloud or self-hosted |
| `QDRANT_API_KEY` | yes (cloud) | Not required for local Qdrant |
| `QDRANT_COLLECTION` | no | Defaults to `founders` |
| `DATABASE_URL` | no | Defaults to `sqlite:///./newsletter.db` |
| `OBJECT_STORE_ROOT` | no | Defaults to `./var/object-store` |
| `DEFAULT_RESEARCH_JOB_MODE` | no | `background` or `inline` (default: `background`) |

## API surface

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Health check |
| `POST` | `/subjects` | Create a founder subject |
| `POST` | `/research-jobs` | Trigger a research job via the API |
| `GET` | `/research-jobs/{job_id}` | Poll job status |
| `GET` | `/subjects/{subject_id}/sources` | List all sources for a founder |
| `GET` | `/subjects/{subject_id}/dossier` | Assembled dossier (from API job path) |
| `GET` | `/search` | Semantic search (`?q=...&subject_id=...&limit=8`) |
| `POST` | `/documents/{document_id}/ingest` | Manually re-chunk and embed a document |
| `POST` | `/writer-inputs` | Build a writer packet from a founder's dossier |

## What is built vs what is next

**Built:**
- Full ingestion pipeline (CLI + API)
- Semantic search scoped by `founder_id`
- SQLite/Postgres provenance ledger
- Static editorial frontend (`web/`)

**Next:**
- LLM skill layer (`ask`, `write_newsletter`, `write_case_study`)
- Batch ingest script for multiple founders
- Production deployment (Supabase Postgres + hosted FastAPI)
