# claude-backlog — Agent Public Surface

This file declares what is and is not a stable, agent-facing public surface
of the claude-backlog plugin. Adapted from MrLesk/Backlog.md `AGENTS.md`
"Agent POV" doctrine. Phase 3 of task-435.

If you are an AI agent operating in this repository or installing this
plugin into a different project, read this file first.

---

## Public surface

Agents MAY rely on the stability of:

1. **Slash commands** registered by this plugin:
   - `/task <title> [--milestone <id>] [--priority <level>] [--no-dod-defaults] [--dod <item>]`
   - `/backlog`, `/backlog plan`, `/backlog triage`, `/backlog browse`
   - `/draft create | list | promote | demote` (Phase 2 of task-435)
   Behavior is documented in `commands/*.md`.

2. **The `backlog-master` skill** (`skills/backlog-master/SKILL.md`) and
   its registered subskills:
   - `@task-writer`, `@task-planner`, `@task-browser`, `@task-linker`,
     `@task-triage`, `@task-draft`.
   The skill description and subskill routing are part of the public surface.
   Subskill prompts may evolve; the routing contract should not.

3. **MCP tools** (Phase 4 of task-435 — `scripts/mcp_server.py`):
   - `get_backlog_instructions` — returns the workflow doc
   - `task_list`, `task_view`, `task_search`
   - `task_create`, `task_edit`, `task_archive`
   - `draft_list`, `draft_promote`
   - `definition_of_done_defaults_get`, `definition_of_done_defaults_upsert`
   Tool names + signatures are stable; argument names may grow additively
   (new optional fields only) without a major-version bump.

4. **MCP resource**:
   - `claude-backlog://workflow/overview` (mime: `text/markdown`) —
     canonical agent-onboarding doc. Mirrors `get_backlog_instructions`.

5. **The data contract**:
   - File layout: `~/.claude/local/backlog/{config.yml,task-NNN - slug.md,drafts/,archive/,docs/}`
   - Filename convention: `task-NNN - slug.md` (drafts/archive: same)
   - Frontmatter schema as documented in `CLAUDE.md` "Frontmatter Contract"
     and `skills/backlog-master/SKILL.md` "Task Frontmatter Schema".
   - DoD doctrine: `definition_of_done` + `auto_inherit_dod` from `config.yml`.
   - Lifecycle: drafts/ → active → archive/, ID-stable across transitions.

6. **Documented agent instructions**:
   - This file (`AGENTS.md`)
   - Plugin `CLAUDE.md`
   - Skill descriptions
   - `workflows/overview.md` (served as the MCP resource above)

7. **The `/dock`-generated SKILL.md description** when this plugin is
   docked as a reference by other tooling.

8. **The web UI** (Phase 5.1 of task-435, parent task-442) — launched via
   `/browser` or `python -m claude_backlog.web --port 6420`. As of Phase 5.1,
   the public web surface is:
   - `GET /healthz` → `ok\n`
   - `GET /api/version` → `{name, version, phase}` JSON
   - `GET /` and 9 SPA routes (`/list`, `/task/<id>`, `/stats`, `/graph`,
     `/embed`, `/heatmap`, `/fdg`, `/fdg-hm`, `/compass`) all serve the
     Alpine.js client (`web/static/index.html`).
   - `GET /static/<path>` serves bundled CSS / JS assets.
   - Unknown `/api/*` paths return a structured 501 `{error,phase,next_phase}`
     placeholder so callers can detect "not yet shipped" cleanly.
   - All write APIs (POST/PATCH/DELETE) currently return 501 — they unlock
     in Phase 5.4.

9. **Persona-aware frontmatter fields** (Phase 5.1, additive):
   - `creator_persona: str | None` — persona slug that created the task.
   - `assignee_persona: str | None` — persona slug currently owning it.
   - `persona_history: list[dict] | None` — chronological handoffs, each
     entry shape `{persona, action, at}`.
   All three default to None/empty; tasks without them parse unchanged.

## NOT a public surface

Agents MUST NOT reference, depend on, or import:

1. **Internal hook scripts** under `hooks/` — their interfaces and existence
   may change without warning. Use the SessionStart-provided context, not
   the hook source.

2. **Internal agent definitions** under `agents/*.md` — these are
   implementation details. The user-facing surface is the slash commands
   and skills they expose.

3. **Source-level utilities** (Python, scripts under `hooks/`, etc.) —
   not a stable API for external callers.

4. **The `_pipeline:` block** in task frontmatter — this is enrichment
   metadata written by `backlog-enrich` processor. Treat it as opaque.
   Read but do not rely on its schema. (Phase 1 follow-up F2 notes a known
   YAML serialization bug in this block.)

5. **Specific subskill internal step numbering or wording** — the routing
   contract is stable; the per-step prompts may be rewritten.

6. **The exact text of inherited DoD defaults** — agents should treat the
   list as configurable. Override via `--no-dod-defaults` or `--dod` flags.

## Conventions for agents working with claude-backlog

### Task creation

- **Always include a title.** Slugified filename is derived from it.
- **Inherit DoD by default.** Pass `--no-dod-defaults` only for trivial
  meta-tasks (e.g., one-line fix).
- **Set `priority` deliberately.** Default `medium` is fine when uncertain.
- **Populate `modified_files`** when you edit repo files as part of the
  task. Lets `grep -l "src/foo.ts" task-*.md` find the owning task.

### Acceptance Criteria vs Definition of Done

These are **distinct**:

- **Acceptance Criteria** = scope / correctness. "What does this task
  *deliver*?" Task-specific.
- **Definition of Done** = completion hygiene. "What is *always required*
  before status=Done?" Project-wide (with per-task overrides).

Never collapse them into one list. AC describes the work; DoD describes
the discipline.

### Status values

Canonical statuses (from `config.yml` `statuses:`):

- `To Do` — active, ready to work
- `In Progress` — actively being worked
- `Blocked` — waiting on dependency
- `Done` — work complete, AC + DoD all checked

Additionally:

- `draft` — file lives in `drafts/`, not yet active work
- `archived` — file lives in `archive/`, terminal state

`status` string matching is **case-insensitive** for `done`, `cancelled`
(per `CLAUDE.md` "Canonical Count" hook). Other status names: exact match.

### Lifecycle transitions

Use the documented commands. Never `mv` task files directly outside the
`/draft promote | demote` and `/backlog archive` operations.

| From | To | Command |
|---|---|---|
| (new) | drafts/ | `/draft create` |
| (new) | active | `/task create` |
| drafts/ | active | `/draft promote <id>` |
| active | drafts/ | `/draft demote <id>` (refuses In-Progress/Done/Blocked) |
| active | archive/ | `/backlog archive <id>` |

### When in doubt

1. Read `~/.claude/plugins/local/legion-plugins/plugins/claude-backlog/CLAUDE.md`.
2. Read `~/.claude/plugins/local/legion-plugins/plugins/claude-backlog/skills/backlog-master/SKILL.md`.
3. Read this file.
4. Ask the user — do not invent new conventions.

## Boundary doctrine for cross-plugin agents

If an agent from another Legion plugin (e.g., `claude-ventures`,
`claude-journal`, `claude-rhythms`) interacts with claude-backlog:

- **Read tasks via filesystem** — `~/.claude/local/backlog/task-*.md`
  is a stable interface.
- **Create tasks via `/task` slash command** — do not write files directly.
- **Update tasks via `/backlog edit` or skill-driven flows** — do not
  patch frontmatter directly without going through the skill.
- **Subscribe to changes via inotify or rhythm investigators** — there
  is no event bus today, but file mtime is a reliable signal.

## When the public surface changes

If a documented surface needs to change (e.g., new required frontmatter
field, command rename, lifecycle stage added):

1. The change is announced in this file with a version bump and
   migration notes.
2. Backward compatibility is maintained for at least one minor version
   when feasible.
3. Existing tasks are NOT migrated forcibly — additive doctrine
   (Phase 1 of task-435).
4. Cross-plugin agents are notified through an outbox draft to Shawn
   for fleet-wide adoption planning.

---

## Provenance

- Doctrine: derived from MrLesk/Backlog.md `AGENTS.md` "Agent POV" section.
- Vision: task-435 (~/.claude/local/backlog/task-435 - ...md).
- Pattern reference: `~/.claude/local/dock/generated/MrLesk/Backlog.md/references/patterns-for-legion.md` §6.
- Adoption phase: Phase 3 of task-435.
- This file last updated: 2026-05-12 (Phase 5.1 surface additions: web UI + persona fields, task-442).
