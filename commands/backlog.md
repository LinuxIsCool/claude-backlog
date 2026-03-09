---
description: "View and manage the task backlog"
argument-hint: "[plan | triage | browse <query> | stats]"
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash, Skill]
model: sonnet
---

Parse the user's argument and route accordingly:

**No arguments** → Show active tasks by priority.
Read all `~/.claude/local/backlog/task-*.md` files, parse YAML frontmatter, display tasks where status != `done` sorted by priority (critical > high > medium > low). Show: ID, title, status, priority, milestone, assignee. Use the @task-browser subskill approach.

**`plan`** → Invoke the @task-planner subskill.
Run the planning algorithm to recommend what to work on next based on priority, dependencies, and readiness.

**`triage`** → Invoke the @task-triage subskill.
Interactive review of stale tasks (no update in 7+ days), ready-to-close tasks, and orphan tasks (no milestone).

**`browse <query>`** → Invoke the @task-browser subskill with the query.
Supported filters: `all`, `milestone:<id>`, `venture:<id>`, `priority:<level>`, `blocked`, `done`, `assignee:<name>`.

**`stats`** → Show task statistics.
Read all task files, parse frontmatter, report counts by: status, priority, milestone. Include orphan count (tasks with no milestone) and total count.

**`search <keyword>`** → Search across all task files.
Grep `~/.claude/local/backlog/task-*.md` for the keyword. Show matching filenames with context lines.

Data location: `~/.claude/local/backlog/`
