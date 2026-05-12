# claude-backlog

Milestone-linked task management. Tasks connect to milestones, milestones live in ventures.

**Agents**: read `AGENTS.md` first. It declares the public surface contract and the conventions agents should follow when creating, modifying, or moving tasks. The "AC vs DoD" distinction in particular is non-negotiable.

## Quick Start
- `/task <title>` — create a new task
- `/backlog` — show active tasks by priority
- `/backlog plan` — planning session: what to work on next
- `/backlog triage` — review and prioritize open tasks
- `/draft create <title>` — capture an unscoped idea (Phase 2 of task-435)
- `/draft list | promote <id> | demote <id>` — manage drafts/

## Data Location
Tasks: `~/.claude/local/backlog/task-NNN - title.md`
Config: `~/.claude/local/backlog/config.yml`

## The Five Ws
- **What** → venture (strategic container)
- **How** → task (tactical steps, acceptance criteria)
- **Why** → journal (reflections, decisions, meaning)
- **When** → milestone deadlines, task due dates, temporal grounding
- **Where** → inventory (machine, drive, venue, network)
- **Who** → co-venturers (venture), assignees (task)

## Milestone Linking
Tasks link to milestones via `milestone:` frontmatter field.
Milestones live in venture files. The milestone is the joint
between strategic intent (ventures) and tactical execution (tasks).

## Data Schema

No SQLite. File-based only.

### File Layout

```
~/.claude/local/backlog/
├── config.yml
├── docs/
│   └── template.md
├── drafts/                     # Phase 2 of task-435 — unscoped ideas
│   ├── README.md
│   └── task-NNN - slug.md      # status: draft
├── archive/
│   └── task-NNN - slug.md      # terminal state
└── task-NNN - slug.md          # active work (default)
```

**Lifecycle**: `drafts/` → active → `archive/`. ID-stable across all transitions. Promoting a draft moves the file but never changes the ID. See `~/.claude/local/backlog/drafts/README.md`.

### Frontmatter Contract

```yaml
---
id: 185                              # required, integer
title: "Legion Web Stack"            # required
status: backlog                      # required, any string. Done/done/Cancelled/cancelled = closed
priority: high                       # required (critical|high|medium|low)
created: 2026-04-14                  # required, date
milestone: null                      # optional, links to venture milestone
tags: [web, architecture]            # optional
estimated_hours: 30                  # optional
depends_on: []                       # optional, task IDs
blocks: []                           # optional, task IDs
effort: null                         # optional
due: null                            # optional, date
venture: null                        # optional, venture slug

# --- Additive optional fields (Phase 1 — Backlog.md cross-pollination, task-435) ---
modified_files: []                   # optional, repo-relative paths an agent edited
ordinal: null                        # optional, int — custom sort within column
parent_task: null                    # optional, int — task ID this is a subtask of
documentation: []                    # optional, doc IDs or URLs informing this task
on_status_change: null               # optional, str — shell command on status transition (DOCUMENTED, NOT YET ENFORCED)
definition_of_done: []               # optional, DoD checklist items (inherits config.yml defaults)
---
```

### Definition of Done

DoD is distinct from Acceptance Criteria:
- **AC** = scope/correctness — what the task *delivers*.
- **DoD** = completion hygiene — what is *always required* before status=Done.

Project-level DoD defaults live in `~/.claude/local/backlog/config.yml` under `definition_of_done:`. When `auto_inherit_dod: true` (default), `/task create` copies them into the new task's `definition_of_done` frontmatter list and `## Definition of Done` body section. Override with `--no-dod-defaults` or per-task `--dod` flags.

### Canonical Count

The SessionStart hook (`backlog-status.py`) counts:

```python
DONE_STATUSES = {"Done", "done", "Cancelled", "cancelled"}
task_files = sorted(BACKLOG_ROOT.glob("task-*.md"))
# active = total - sum(status in DONE_STATUSES)
```
