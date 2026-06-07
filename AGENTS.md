# Inventory App Codex Agent Instructions

## Scope

These instructions apply to all work in this repository:

`C:\Users\mcclu\Desktop\inventory_app_git`

This file is the repo-level operating contract for Codex. It supplements the root vault agent spec at:

`C:\Users\mcclu\Desktop\Obsidian\John_Vault\0. Agents\agent.md`

If these instructions conflict with generic Codex defaults, follow this file for this repository.

## Required Workflow

For every implementation, refactor, review, planning, or architecture task:

1. Receive and restate the task when useful.
2. Review relevant Obsidian context before making code edits.
3. Summarize the relevant retrieved context briefly before proceeding.
4. Inspect the codebase and make the requested code edits.
5. Run appropriate focused checks or tests when feasible.
6. After code edits, orchestrate a documentation/project-memory update through a sub-agent when sub-agent delegation is available and authorized by the current session.
7. Ensure Obsidian repo docs reflect the actual code changes made, not the original plan.
8. Final response must include:
   - code changes made
   - verification performed
   - Obsidian notes created or updated, or any documentation gaps

## Obsidian Retrieval

Obsidian is the canonical project memory for this repo. Use targeted retrieval before code edits with this priority:

1. `obsidian_context`
2. `obsidian_search`
3. `obsidian_read` on the most relevant notes

Prefer repository-specific docs under:

`4. Notes\Repository-Docs\inventory-app-git`

Do not claim Obsidian was searched unless it was. Do not scan the full vault unless explicitly requested.

## Obsidian Update After Code Edits

After code edits, update project memory based on the final diff and verification results.

Preferred mechanism:

1. Delegate the Obsidian update to a sub-agent when the current session permits sub-agents.
2. Give the sub-agent a bounded, self-contained handoff that includes the changed files, final diff summary, tests/checks run, and the Obsidian note paths or repo-doc area that likely need updating.
3. The sub-agent should run as-is within its available tools. If it has Obsidian MCP access, it may update the relevant Obsidian repo docs directly. If it does not have Obsidian MCP access, it should return a concise project-memory update brief for Codex to apply.
4. Codex remains responsible for the actual Obsidian write being completed before the final response. If the sub-agent cannot write to Obsidian, Codex must use the Obsidian MCP tools directly and base the update on the sub-agent's brief plus the final code diff.
5. Codex should include the sub-agent result and the actual Obsidian notes updated in the final response.

If sub-agent delegation is unavailable, times out, or returns without Obsidian access, Codex must perform the Obsidian update directly with the Obsidian MCP tools.

Use `obsidian_update_repo_docs` for session-level updates when appropriate. For durable decisions, specs, or architecture changes, update or create the relevant note and ensure change logging follows the vault agent spec.

## Source-of-Truth Precedence

When context conflicts, use this order:

1. Stable specs
2. Decision records
3. Architecture notes and context packs
4. Plans and roadmaps
5. Working notes
6. Logs and session summaries

Surface meaningful conflicts in the response rather than silently choosing one.

## Git and Local Edits

The worktree may contain user edits. Never revert changes that were not made by Codex unless the user explicitly asks.

Before editing, check current status. Keep changes scoped to the task and ignore unrelated modified files.

## Final Response Expectations

Keep final responses concise and concrete. Mention:

- files changed
- tests or checks run
- Obsidian context consulted
- Obsidian notes updated
- any blockers or follow-up documentation gaps
