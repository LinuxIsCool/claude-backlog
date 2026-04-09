# Claude Code Backlog Plugin

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Milestone-linked task management for Claude Code. Create, prioritize, and track tasks that connect to venture milestones — all stored as flat markdown files on your disk.

Every project generates action items. Most of them live in your head, a sticky note, or a chat message you'll never find again. This plugin gives you a backlog that lives alongside your code, links tasks to larger goals, and helps you decide what to work on next.

---

## Features

- **Flat markdown tasks** — one file per task, rich YAML frontmatter, no database.
- **Milestone linking** — tasks reference milestones, milestones live in ventures. `task → milestone → venture`. Loose coupling resolved at read time.
- **Five Ws integration** — What (ventures), How (tasks), Why (journal), When (temporal), Where (inventory), Who (assignees). Each system owns its domain.
- **Priority + dependency tracking** — four priority levels (critical/high/medium/low), explicit dependency chains, blocked-by detection.
- **Five specialist subskills** — writer, planner, triage, browser, linker. Each handles one workflow.
- **Taskmaster agent** — a planning agent for multi-turn decomposition sessions: break milestones into tasks, identify critical paths, manage dependencies.
- **Session hooks** — start-of-session backlog status banner; end-of-session reminder about in-progress tasks.
- **Archive workflow** — completed tasks move to `archive/`, keeping the active directory clean.

---

## Install

```
/plugin marketplace add linuxiscool/claude-backlog
/plugin install claude-backlog
```

Or clone and install locally:

```bash
git clone https://github.com/LinuxIsCool/claude-backlog ~/.claude/plugins/claude-backlog
```

Restart your Claude Code session. The `/backlog` and `/task` commands will be available.

---

## Quick Start

### Creating tasks

```
/task Fix the 404 on the embedding endpoint
/task Deploy staging environment --priority critical --milestone ms-demo
/task Write integration tests --priority high
```

### Managing the backlog

```
/backlog                          # show active tasks by priority
/backlog plan                     # what should I work on next?
/backlog triage                   # review stale, orphan, and ready-to-close tasks
/backlog browse all               # list every task
/backlog browse milestone:ms-demo # filter by milestone
/backlog browse priority:critical # filter by priority
/backlog browse blocked           # show blocked tasks
/backlog browse done              # show completed tasks
/backlog stats                    # counts by status, priority, milestone
/backlog search <keyword>         # grep across all task files
```

---

## How It's Organized

```
~/.claude/local/backlog/
├── config.yml
├── docs/
│   └── template.md
├── archive/
│   └── task-NNN - title.md      # completed tasks
└── task-NNN - title.md          # active tasks
```

Tasks are flat — no subdirectories for status. Status lives in frontmatter. The only structural distinction is active vs. archived.

### Task frontmatter

```yaml
---
id: 42
title: "Curate 50 kelp forest reference images"
milestone: ms-dataset
status: To Do              # To Do | In Progress | Blocked | Done
priority: high             # low | medium | high | critical
assignee: "@legion"
labels: [dataset, research]
tags: [images, kelp, marine-ecology]
created: 2026-03-09
updated: 2026-03-09
due: null
dependencies: [41]
blocked_by: []
references: []
outgoing_links: [task:41, venture:salish-sea-dreaming]
modified_at: "2026-03-09T13:30:00"
modified_count: 1
summary: "Find and curate 50 high-quality kelp forest images for training dataset."
final_summary: null
---
```

### ID generation

Task IDs are auto-incremented. The plugin scans existing `task-*.md` files, extracts the highest numeric ID, and assigns `max + 1`. IDs start at 1.

### Milestone resolution

When a task has `milestone: ms-dataset`, the plugin scans `~/.claude/local/ventures/` for any venture file containing a milestone with that ID. That venture becomes the task's parent context. No hardcoded venture references needed — loose coupling by convention.

### Namespace syntax

Cross-references use namespace prefixes: `task:42`, `milestone:ms-slug`, `venture:slug`, `journal:2026-04-08`, `person:name`.

---

## The Subskills

The `/backlog` command dispatches to specialist subskills:

### `@task-writer`
Creates new backlog tasks. Handles ID generation, slug filenames, frontmatter defaults, and milestone auto-detection from context.

### `@task-planner`
Answers "what should I work on next?" Considers priority, dependencies, blocked status, and deadline proximity. Useful for sprint planning, daily standups, and focus selection.

### `@task-triage`
Reviews the backlog for hygiene. Identifies stale tasks (no update in 7+ days), orphan tasks (no milestone), ready-to-close tasks, and priority mismatches. Recommends cleanup actions.

### `@task-browser`
Search and navigation. Filter by status, priority, milestone, venture, assignee, or keyword. Stats mode gives counts and distributions.

### `@task-linker`
Manages cross-references between tasks, milestones, ventures, and journal entries. Ensures bidirectional links stay consistent.

### `@taskmaster` (agent)
A dedicated planning agent for multi-turn sessions. Give it a milestone and it will decompose it into 3–10 concrete tasks with acceptance criteria, dependency ordering, and critical path identification. Best used when starting a new project phase.

---

## Session Hooks

Two hooks are registered by default:

- **`SessionStart`** — shows a banner with active task counts by priority, plus any overdue or blocked tasks.
- **`Stop`** — reminds you about in-progress tasks so nothing slips between sessions.

Both are non-blocking and output structured JSON. Disable them by editing `plugin.json` if you prefer quiet sessions.

---

## The Five Ws

This plugin is part of a larger system where each plugin owns one dimension:

| Question | Plugin | Domain |
|----------|--------|--------|
| **What** | claude-ventures | Strategic containers — what are we trying to achieve? |
| **How** | **claude-backlog** | Tactical steps — what do we do next? |
| **Why** | claude-journal | Reflections and decisions — why did we choose this? |
| **When** | Temporal grounding | Milestone deadlines, task due dates |
| **Where** | claude-inventory | Machine, drive, venue, network |
| **Who** | Assignees + co-venturers | Who is responsible? |

The **milestone** is the joint between strategic intent (ventures) and tactical execution (tasks). It's the most important link in the system.

---

## Philosophy

**Flat-first.** One directory, status in frontmatter, not in folder structure. No nesting, no Kanban columns as directories. Archive is the only structural transition.

**Milestone-linked.** Tasks without milestones are orphans. They're allowed (quick captures, one-offs), but the system nudges you to link them. Milestones provide context, deadlines, and venture-level visibility.

**Progressive disclosure.** `/backlog` shows you the essentials. `/backlog plan` adds analysis. The taskmaster agent goes deep. Each layer adds detail without forcing it on quick interactions.

**Plain files.** Every task is a markdown file. Grep it, back it up, read it in any editor. No database, no cloud, no lock-in.

---

## Configuration

`~/.claude/local/backlog/config.yml`:

```yaml
default_assignee: "@legion"
archive_on_done: true
```

If the config doesn't exist, sensible defaults are used.

---

## Data Location

All backlog data lives under `~/.claude/local/backlog/`. It's yours — never uploaded, never shared.

---

## Companion Plugins

- **[claude-journal](https://github.com/LinuxIsCool/claude-journal)** — atomic journaling, the "Why" layer. Tasks cross-reference journal entries for decision context.
- **[claude-logging](https://github.com/LinuxIsCool/claude-logging)** — session capture and search. When you need the raw transcript that produced a task.

---

## Contributing

Issues and pull requests welcome. This is a personal tool first, but the patterns are general and contributions that keep it simple and file-based are appreciated.

---

## License

MIT — see [LICENSE](LICENSE).
