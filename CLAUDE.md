# Claude Instructions For This Repo

## Project Landscape

**FIRSTHAND** is an AI-powered founder research and newsletter platform. The product is a growing directory of founders — each one a self-contained knowledge sandbox — that powers semantic search, long-form newsletters, case studies, and eventually a "virtual founder" chat experience.

### The core idea: the founder sandbox

Every founder in the system is a completely isolated unit of knowledge, keyed by a single `founder_id`. All data for that person — scraped content, vector embeddings, structured metadata — is scoped to that ID. No cross-founder contamination.

```
founder_id
  ├── sources       URLs scraped (articles, YouTube transcripts, interviews)
  ├── documents     normalized text per source
  ├── chunks        sentence-window splits of each document
  └── vectors       chunks embedded and stored in Qdrant, filtered by founder_id
```

Adding a founder is a single CLI command:
```bash
python -m newsletter.cli research "Founder Name" "optional context"
```

That command runs the full pipeline and populates everything.

### The data pipeline

```
Exa neural search   →  discover relevant URLs for the founder
       ↓
Firecrawl / httpx   →  scrape web articles (Firecrawl preferred, httpx fallback)
youtube-transcript-api  →  fetch YouTube transcripts
       ↓
Custom chunker      →  sentence-aware splits (300 tok / 40 overlap for transcripts,
                        500 tok / 80 overlap for articles)
       ↓
ZeroEntropy zembed-1  →  embed each chunk (2560-dim, asymmetric query/doc)
       ↓
Qdrant Cloud        →  upsert vectors with founder_id + source metadata as payload
       ↓
SQLite / Postgres   →  persist subject, sources, documents, chunks (provenance ledger)
```

### How skills work

Skills are functions that take a `founder_id` (and optionally a question or task) and return generated output. They always follow the same pattern:

```
1. Embed the query / task description
2. Retrieve top-k relevant chunks from Qdrant filtered by founder_id
3. Pass retrieved context + prompt to an LLM (Claude)
4. Return the generated answer / newsletter / case study
```

The LLM does all interpretation. The vector store does retrieval. There is no rule-based extraction layer in between.

Skills planned:
- `ask(founder_id, question)` — Q&A about a specific founder
- `write_newsletter(founder_id)` — long-form newsletter from their story
- `write_case_study(founder_id)` — structured PDF-ready case study
- `chat(founder_id, message)` — conversational interface (phase 2, with Mem0)

### Source types

| Type | Notes |
|---|---|
| `website` | Articles, interviews, blog posts scraped via Firecrawl |
| `youtube_transcript` | Auto-generated transcripts pulled via `youtube-transcript-api` |
| `x_post` | X/Twitter posts (adapter scaffolded, not yet wired) |

Source type is stored in every Qdrant chunk payload so skills can filter by it (e.g. "only search YouTube interviews").

### What is built vs what is next

**Built:**
- Full ingestion pipeline (discover → fetch → normalize → chunk → embed → Qdrant)
- FastAPI server with semantic search endpoint (`GET /search?q=...&subject_id=...`)
- SQLite/Postgres provenance ledger (subjects, sources, documents, chunks)
- CLI for adding founders

**Not yet built:**
- LLM skill layer (`ask`, `write_newsletter`, `write_case_study`)
- Batch ingest script for multiple founders
- Production deployment (Supabase Postgres, hosted FastAPI)
- Phase 2: Mem0 memory layer for conversational chat
- Phase 3: Graphiti knowledge graph for relational queries

### Key design decisions

- **No rule-based extraction.** There are no separate claims/events/quotes tables actively used. The LLM interprets raw chunks at query time — it does a far better job than pattern matching.
- **One Qdrant collection for all founders.** Physical isolation per founder is unnecessary and wasteful. `founder_id` filter IS the sandbox.
- **SQLite for local dev, Postgres (Supabase) for prod.** Swap by changing `DATABASE_URL` in `.env`.
- **Idempotent pipeline.** Re-running the CLI for an existing founder skips already-processed sources.

---

## Working Rules

Use this repository as a disciplined, branch-based engineering workspace. The default expectation is that tasks end in clean commits and a real GitHub pull request to `main`, not a pile of uncommitted local edits.

### Default Behavior

- Execute the task unless the user explicitly asks only for planning or discussion.
- Make changes conservatively and in line with the existing codebase.
- Keep commits small, coherent, and reviewable.
- Do not mix unrelated edits into the same commit.
- Do not revert user-owned or unrelated in-progress changes.

### Branch And PR Policy

- Default to feature-branch workflow.
- If currently on a feature branch, continue on that branch unless the user says otherwise.
- If currently on `main` or `master`, create a new branch before making changes.
- Use descriptive branch names such as `feat/...`, `fix/...`, `docs/...`, or `chore/...`.
- Assume the intended base branch is `main` unless the user specifies another target.

### PR Automation

- By default, after completing a task:
  - create clear commit(s)
  - push the branch
  - create a real GitHub pull request with the GitHub CLI
- Do not ask the user to draft the PR title or body.
- Write the PR message from the actual changes.
- If a remote, auth, or network constraint prevents push or PR creation, explain the blocker clearly and leave the branch and commits ready for the user to continue.

### Commit Standards

- Prefer unit-based commits similar to a professional workplace workflow.
- Each commit should represent a clear logical step.
- Use specific commit messages, for example:
  - `add semantic search endpoint`
  - `wire ZeroEntropy embedding into ingestion pipeline`
  - `document founder sandbox architecture`
- Avoid `wip`, `misc`, or other low-signal commit messages.

### Worktrees And Existing Branches

- If the user is operating in a worktree, assume that is intentional.
- Do not collapse or rewrite their branch structure unless asked.
- Work cleanly inside the current checkout.
- When the user already created the branch, use it rather than creating another one.

### Delivery Standard

- The ideal finish state for a normal task is:
  - code or docs updated
  - relevant verification run
  - changes committed in clear units
  - branch pushed
  - GitHub PR opened against `main`
- If any one of those steps is impossible, report exactly why.
