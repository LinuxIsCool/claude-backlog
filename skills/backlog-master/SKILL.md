---
name: backlog-master
description: >
  Milestone-linked task management — create, track, and prioritize backlog tasks that connect to venture milestones.
  Use when the user wants to create tasks, check what to work on, plan sprints, triage the backlog, browse tasks,
  manage dependencies, or decompose milestones into actionable work.
  Also triggers on: "to-do", "todo", "blocked", "what should I do", "next task", "backlog", "sprint", "triage".
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Backlog Master

Milestone-linked task management for Claude Code. Tasks are flat markdown files with rich frontmatter. The **milestone** is the joint between strategic ventures and tactical tasks.

## Philosophy

**Flat-first**: One directory, status lives in frontmatter not in folder structure. No nesting, no subdirectories for states. Archive is the only exception (completed tasks move there).

**Milestone-linked**: Tasks reference milestones, milestones live inside ventures. `task → milestone → venture`. Loose coupling — resolution happens at read time by scanning venture files.

**Five Ws integration**: What=ventures, How=tasks, Why=journal, When=temporal, Where=inventory, Who=assignees. Each system owns its domain, cross-references via namespace syntax.

## Directory Structure

```
~/.claude/local/backlog/
├── config.yml
├── docs/
│   └── template.md
├── archive/
│   └── task-NNN - title.md
└── task-NNN - title.md
```

## Task Frontmatter Schema

```yaml
---
id: 42
title: "Curate 50 kelp forest reference images"
milestone: ms-dataset
status: To Do          # To Do | In Progress | Blocked | Done
priority: high         # low | medium | high | critical
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
summary: "Find and curate 50 high-quality kelp forest images for Autolume training dataset."
final_summary: null
---
```

## ID Generation

Scan `~/.claude/local/backlog/task-*.md`, extract numeric IDs with regex (`task-(\d+)`), take `max + 1`. Start at 1 if no tasks exist.

## Milestone Resolution

When a task has `milestone: ms-dataset`, scan `~/.claude/local/ventures/` for any venture file containing a milestone with that ID. That venture becomes the task's parent context. This is loose coupling — no hardcoded venture references needed.

## Namespace Syntax

`task:N`, `milestone:ms-slug`, `venture:slug`, `journal:YYYY-MM-DD`, `person:name`

## Subskills

### @task-writer
**Trigger**: Creating new backlog tasks, adding to-dos, capturing action items.
Creates tasks with proper ID, frontmatter, slugified filename. Auto-detects milestones from context.

### @task-planner
**Trigger**: "What should I work on?", sprint planning, priority review, "next task", "plan my day/week".
Scores tasks by: milestone deadline proximity (40%) + priority (30%) + unblocks others (20%) + age (10%).

### @task-browser
**Trigger**: Browsing, searching, navigating tasks. Filter by status, priority, milestone, venture. Statistics.
Query patterns: `browse all`, `browse milestone:X`, `browse venture:X`, `browse blocked`, `search keyword`, `stats`.

### @task-linker
**Trigger**: Linking tasks to milestones, ventures, journal entries. Dependency graph. Finding orphan tasks.
Cross-system references using namespace syntax.

### @task-triage
**Trigger**: "triage", bulk review, stale task cleanup, archival, reconciliation.
Reviews tasks with no updates in 30+ days, archives completed tasks, finds invalid milestone references.

## Routing

When invoked without specific context:
1. Check open tasks → show summary (count by status, top priorities)
2. If the user's message implies a specific subskill → route there
3. If unclear → ask what they'd like to do

## Config

`~/.claude/local/backlog/config.yml`:
```yaml
backlog_root: ~/.claude/local/backlog
ventures_root: ~/.claude/local/ventures
default_assignee: "@legion"
default_priority: medium
stale_threshold_days: 30
archive_on_done: false
```
