# Newsletter Repo Instructions

This repository is built around agent-driven execution. Treat the repo as a professional engineering workspace with explicit branch hygiene, clear commits, and GitHub pull requests as the default delivery mechanism.

## Product Context

- The system is an AI research and newsletter platform focused on founder stories.
- The research pipeline is the core system of record.
- Writing, synthesis, and future chat or memory experiences are downstream consumers of structured research outputs.
- Favor evidence-backed ingestion, clean provenance, and durable intermediate representations over one-shot generated output.

## Default Execution Style

- Unless the user explicitly says otherwise, execute tasks instead of only proposing them.
- Prefer small, clean, professional commits over one large mixed commit.
- Keep commits unit-scoped, workplace-quality, and easy to review.
- Avoid unrelated refactors unless they are required to complete the task safely.
- Preserve user changes and work with existing in-progress edits rather than reverting them.

## Git Workflow

- The default workflow is branch -> commit(s) -> push -> GitHub PR to `main`.
- If the current checkout is already on a feature branch, keep using that branch unless the user says otherwise.
- If the current checkout is on `main` or `master`, create a new feature branch before making changes.
- If the user is working in a worktree, treat that checkout as intentional and work within it.
- Never commit directly to `main` unless the user explicitly requests it.
- Never leave completed code changes uncommitted unless the user explicitly requests that.

## Pull Request Expectations

- When the user asks for a task, assume they want a real GitHub pull request created with the GitHub CLI unless they explicitly opt out.
- Do not ask the user to write the PR title or body.
- Draft the PR title and body directly from the implemented changes.
- Target `main` by default.
- Push the branch and open the PR as part of finishing the task when the repository has a configured remote and credentials allow it.
- If a PR cannot be created because the repo has no remote, no GitHub auth, or network restrictions block it, say that clearly and still leave the branch and commits in a clean state.

## Commit Style

- Commit in clear units.
- Use precise, professional commit messages.
- Favor messages like:
  - `add research job API scaffold`
  - `persist dossier and source provenance models`
  - `document default branch and PR workflow`
- Avoid vague commit messages like `updates`, `fix stuff`, or `wip`.
- If a task naturally breaks into multiple steps, create multiple commits instead of squashing everything into one.

## Repository Management Preferences

- Branch names should be short and descriptive, usually prefixed by the work type, for example:
  - `feat/...`
  - `fix/...`
  - `docs/...`
  - `chore/...`
- Keep diffs reviewable.
- Prefer pull requests that are easy to merge cleanly into `main`.
- If there are unrelated local changes, do not revert them. Stage and commit only the files relevant to the current task unless the user asks for broader cleanup.

## Agent Behavior

- Read repo instructions before editing.
- Treat `AGENTS.md` and `CLAUDE.md` as operational guidance for future tasks in this repo.
- Be explicit about blockers.
- When possible, finish the full loop: code changes, tests, commits, push, and PR.
- If any part of that loop cannot be completed, report the exact blocker and leave the repo in the best possible intermediate state.

