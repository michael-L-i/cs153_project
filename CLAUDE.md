# Claude Instructions For This Repo

Use this repository as a disciplined, branch-based engineering workspace. The default expectation is that tasks end in clean commits and a real GitHub pull request to `main`, not a pile of uncommitted local edits.

## Core Context

- This repo is for an AI founder-story research and newsletter system.
- The research layer is the source of truth.
- Downstream agents may write newsletters, generate summaries, or support future memory/chat features from structured research outputs.
- Optimize for evidence, provenance, and maintainable system structure.

## Default Working Rules

- Execute the task unless the user explicitly asks only for planning or discussion.
- Make changes conservatively and in line with the existing codebase.
- Keep commits small, coherent, and reviewable.
- Do not mix unrelated edits into the same commit.
- Do not revert user-owned or unrelated in-progress changes.

## Branch And PR Policy

- Default to feature-branch workflow.
- If currently on a feature branch, continue on that branch unless the user says otherwise.
- If currently on `main` or `master`, create a new branch before making changes.
- Use descriptive branch names such as `feat/...`, `fix/...`, `docs/...`, or `chore/...`.
- Assume the intended base branch is `main` unless the user specifies another target.

## PR Automation

- By default, after completing a task:
  - create clear commit(s)
  - push the branch
  - create a real GitHub pull request with the GitHub CLI
- Do not ask the user to draft the PR title or body.
- Write the PR message from the actual changes.
- If a remote, auth, or network constraint prevents push or PR creation, explain the blocker clearly and leave the branch and commits ready for the user to continue.

## Commit Standards

- Prefer unit-based commits similar to a professional workplace workflow.
- Each commit should represent a clear logical step.
- Use specific commit messages, for example:
  - `add subject and research job API endpoints`
  - `wire dossier assembly from extracted evidence`
  - `document repo branch and PR conventions`
- Avoid `wip`, `misc`, or other low-signal commit messages.

## Worktrees And Existing Branches

- If the user is operating in a worktree, assume that is intentional.
- Do not collapse or rewrite their branch structure unless asked.
- Work cleanly inside the current checkout.
- When the user already created the branch, use it rather than creating another one.

## Delivery Standard

- The ideal finish state for a normal task is:
  - code or docs updated
  - relevant verification run
  - changes committed in clear units
  - branch pushed
  - GitHub PR opened against `main`
- If any one of those steps is impossible, report exactly why.

