# Working instructions for this repo

## No subagents by default

Do not use the Agent tool (Explore, general-purpose, fork, or any other
subagent type) in this repo unless explicitly told otherwise for a given
task. Do research inline with direct tools instead.

When the user does authorize agents for a task, use the tiered
codebase-memory agents for code research — `codebase-memory-scout` (fast
provisional lookup), `codebase-memory` (default verification), or
`codebase-memory-auditor` (bounded exhaustive audit). Subagents don't
inherit conversation context: pass each one the graph project id below, the
tier, a bounded scope, and any qualified names / coverage results already
gathered in the parent.

## MCP tools available here

- **codebase-memory-mcp** (`mcp__codebase-memory-mcp__*`) — indexed
  knowledge graph of this repo (replaces the retired graphify server).
  Project id: `C-Users-mcclu-Desktop-inventory_app_git` (watched;
  auto-refreshes after commits). Invoke the `codebase-memory` skill before
  structural exploration — it carries the full decision matrix. Quick map:
  - `search_graph` — find symbols (BM25 `query`, regex `name_pattern`, or
    `semantic_query` array); returns the exact qualified_name other tools
    need. Check `has_more` and paginate.
  - `trace_path` — callers/callees/data-flow from an exact function name
  - `get_code_snippet` — read a symbol's source by qualified_name
  - `detect_changes` — blast radius of the current git diff vs main
  - `query_graph` — Cypher for multi-hop/aggregate questions
  - `get_architecture` — orientation, hotspots, Leiden clusters
  - `search_code` — graph-ranked grep when you need literal text
  - `check_index_coverage` — after discovery, batch-check every cited path;
    include scopes before any negative or exhaustive claim
  Gotchas: FastAPI route handlers show 0 callers (framework-invoked), so an
  empty result means "look closer", not "unused". Known parse-partial files
  (grep these instead of trusting the graph): backend/Dockerfile,
  backend/scripts/import_local_data.ps1, backend/static/shell-head.html,
  backend/static/shell-tail.html.
- **obsidian** (`mcp__obsidian__*`) — reads/writes the user's Obsidian vault
  directly for docs that mirror there. For doc/design/plan context, search the
  vault mirror first — `John_Vault/4. Notes/Repository-Docs/inventory-app-git/`
  under `C:\Users\mcclu\Desktop\Obsidian` — via `mcp__obsidian__search_files`
  (pass `excludePatterns` to skip noise) or direct Reads of that path; don't
  sweep the repo for `*.md`. The `docs/` -> vault mirror is generated
  automatically at turn end (`scripts/sync-obsidian.ps1` via Stop hook), so the
  vault is current — and never sync it by hand. Agents without obsidian MCP
  tools (e.g. the codebase-memory tiers) should Read the vault path directly.

Standard tools (Read/Grep/Glob/Bash/Edit) remain the default for anything
the graph doesn't cover: reading full files, editing, running the app, git.

## Documentation conventions (token cost)

Living docs in `docs/` are current-truth only: state what is true now.
Delete history, superseded designs, and how-we-got-here narrative on
sight — git and `docs/superpowers/` own the past. A settled choice gets
at most one line of rationale, only where a future session would
otherwise re-litigate it. Form: tables for enumerable facts, clipped
bullets elsewhere, no paragraph over ~3 sentences, never restate what
code or another doc owns. Soft word budgets (also stated in each doc's
header): `current-state.md` 16,500 · `endpoint-map.md` 11,000 ·
`open-work.md` 12,000. Budgets bound form, not content — compress
phrasing first, delete only what is stale, and exceed a budget rather
than drop a load-bearing fact. An update that breaches a budget should
delete something stale in the same edit when one exists.

## Response protocols (token cost)

Chat: outcome first; default reply under ~200 words; no per-step
narration; no recap tables or headers for simple answers; detail on
request. Completion reports: one sentence plus verification evidence.
Plan-then-implement and options-first workflows remain mandatory, but
present options as a tight table with one-line trade-offs and a
recommendation, not essays. Authored artifacts carry soft budgets under
the same content-over-form rule: specs ≤ 1,800 words; plans ≤ 3,500
using a compact per-task template (goal / files / steps / test) that
never restates spec content; session handoffs ≤ 500.
