# Founder Newsletter Research Platform

This repo contains the initial research system for an AI founder-story newsletter.

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

