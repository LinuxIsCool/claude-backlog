# claude-backlog

Milestone-linked task management. Tasks connect to milestones, milestones live in ventures.

## Quick Start
- `/task <title>` — create a new task
- `/backlog` — show active tasks by priority
- `/backlog plan` — planning session: what to work on next
- `/backlog triage` — review and prioritize open tasks

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
├── task-NNN - title.md     # e.g. "task-185 - Legion Web Stack.md"
└── config.yml
```

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
---
```

### Canonical Count

The SessionStart hook (`backlog-status.py`) counts:

```python
DONE_STATUSES = {"Done", "done", "Cancelled", "cancelled"}
task_files = sorted(BACKLOG_ROOT.glob("task-*.md"))
# active = total - sum(status in DONE_STATUSES)
```
