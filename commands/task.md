---
description: "Create a new backlog task"
argument-hint: "<title> [--milestone <id>] [--priority <level>]"
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash, Skill]
model: sonnet
---

Invoke the @task-writer subskill to create a new backlog task.

Parse the argument:
- **title** (required) — the task title. If not provided, ask the user for one.
- **--milestone <id>** (optional) — associate with a milestone.
- **--priority <level>** (optional, default: `medium`) — one of: critical, high, medium, low.

Workflow:
1. Glob `~/.claude/local/backlog/task-*.md` to find existing tasks.
2. Determine the next sequential task ID.
3. Create the task file at `~/.claude/local/backlog/task-<id>.md` using the task-writer format.
4. Report the created task: ID, title, priority, milestone, file path.

Data location: `~/.claude/local/backlog/`
