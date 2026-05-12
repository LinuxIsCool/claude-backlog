---
description: "Create a new backlog task"
argument-hint: "<title> [--milestone <id>] [--priority <level>] [--no-dod-defaults] [--dod <item>]..."
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash, Skill]
---

Invoke the @task-writer subskill to create a new backlog task.

Parse the argument:
- **title** (required) — the task title. If not provided, ask the user for one.
- **--milestone <id>** (optional) — associate with a milestone.
- **--priority <level>** (optional, default: `medium`) — one of: critical, high, medium, low.
- **--no-dod-defaults** (optional) — skip Definition of Done inheritance from `config.yml`.
- **--dod <item>** (optional, repeatable) — supply explicit DoD items instead of inheriting defaults.

Workflow:
1. Glob `~/.claude/local/backlog/task-*.md` to find existing tasks.
2. Determine the next sequential task ID.
3. Read `~/.claude/local/backlog/config.yml` → `definition_of_done` + `auto_inherit_dod`.
4. Resolve DoD items: explicit `--dod` flags → else config defaults if `auto_inherit_dod: true` and not `--no-dod-defaults` → else empty.
5. Create the task file at `~/.claude/local/backlog/task-<id> - <slug>.md` using the task-writer format.
6. Report the created task: ID, title, priority, milestone, DoD item count, file path.

Data location: `~/.claude/local/backlog/`
DoD doctrine: AC = scope/correctness. DoD = completion hygiene. Distinct sections, distinct lists.
