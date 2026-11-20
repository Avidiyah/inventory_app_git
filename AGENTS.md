# Inventory App Codex Agent Instructions

Repo-level operating contract for Codex. Where it conflicts with generic
Codex defaults, follow this file.

## Workflow

For every implementation, refactor, review, planning, or architecture task:

1. Read the relevant living docs in `docs/` before editing code
   (`current-state.md`, `endpoint-map.md`, `open-work.md`). `docs/` is the
   only project memory; `docs/superpowers/` is history — open a file there
   by name, never sweep it.
2. Inspect the codebase and make the requested edits.
3. Run focused checks or tests when feasible.
4. Update the living docs to match the code as changed, not the original
   plan. Follow the documentation conventions and word budgets in
   `CLAUDE.md`.

## Source-of-Truth Precedence

When context conflicts, use this order and surface meaningful conflicts
rather than silently choosing:

1. Code
2. Living docs in `docs/`
3. Specs, then plans, in `docs/superpowers/`
4. Session handoffs

## Git and Local Edits

The worktree may contain user edits. Check status before editing, keep
changes scoped to the task, and never revert changes Codex did not make
unless the user explicitly asks.

## Final Response

Concise and concrete: files changed, checks run, docs updated, and any
blockers or documentation gaps.
