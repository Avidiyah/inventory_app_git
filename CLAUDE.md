# Working instructions for this repo

## No subagents by default

Do not use the Agent tool (Explore, general-purpose, fork, or any other
subagent type) in this repo unless explicitly told otherwise for a given
task. Do research inline with direct tools instead.

## MCP tools available here

- **graphify** (`mcp__graphify__*`) — indexed code graph for this repo.
  Call `list_repositories` once to get the repository_id, then use
  `graphify_find` for symbol/label search, `graphify_callers` /
  `graphify_callees` / `graphify_trace` for call relationships,
  `graphify_impact` / `impact_and_risk` for blast-radius before a change,
  `graphify_imports_exports` / `graphify_file_neighbors` for file
  dependencies, and `query_graph` for prose questions. Prefer this over a
  grep sweep or a subagent for "where is X" / "what calls Y" questions.
- **obsidian** (`mcp__obsidian__*`) — reads/writes the user's Obsidian vault
  directly for docs that mirror there.

Standard tools (Read/Grep/Glob/Bash/Edit) remain the default for anything
graphify doesn't cover: reading full files, editing, running the app, git.
