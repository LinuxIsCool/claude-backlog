---
description: "Manage backlog drafts — create, list, promote, demote"
argument-hint: "<create <title> | list | promote <id> | demote <id>>"
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash, Skill]
---

Invoke the @task-draft subskill to manage backlog drafts.

Drafts are unscoped ideas living in `~/.claude/local/backlog/drafts/`. Same ID space as active tasks. ID-stable across promotion / demotion.

Parse the argument:
- **create <title>** — create a new draft. Lightweight: no AC, no DoD inheritance.
- **list** — show all drafts with ID, title, priority, age.
- **promote <id>** — move draft to active. Inherits DoD from config. Adds AC stub if absent.
- **demote <id>** — move active back to draft. Rare. Refuses if status is In Progress / Done / Blocked.

Workflow:
1. Parse op + args.
2. If op = `create`:
   - Scan `~/.claude/local/backlog/task-*.md`, `~/.claude/local/backlog/drafts/task-*.md`, `~/.claude/local/backlog/archive/task-*.md` for highest ID → `max + 1`.
   - Slugify title.
   - Write `~/.claude/local/backlog/drafts/task-<id> - <slug>.md` with `status: draft` and lightweight body (Description + Notes only).
   - Report: `Drafted task-<id> - <title> (drafts/<filename>)`.
3. If op = `list`:
   - Glob `~/.claude/local/backlog/drafts/task-*.md`.
   - Display ID, title, priority, age (created date diff).
   - Sort newest first.
4. If op = `promote <id>`:
   - Locate `~/.claude/local/backlog/drafts/task-<id> - *.md`.
   - Update `status: draft` → first non-draft status from config (`statuses[0]`, typically `To Do`).
   - Inherit DoD from config (`definition_of_done` + `auto_inherit_dod`).
   - Add `## Definition of Done` body section after `## Acceptance Criteria` (or stub if AC absent).
   - Move file → `~/.claude/local/backlog/task-<id> - <slug>.md` (drop `drafts/` prefix).
   - Report: `Promoted task-<id>. DoD: <n> items. AC: <present|stub>`.
5. If op = `demote <id>`:
   - Locate `~/.claude/local/backlog/task-<id> - *.md`.
   - Refuse if status is `In Progress`, `Done`, `Blocked`. Prompt user to confirm.
   - Update `status: <current>` → `status: draft`.
   - Move file → `~/.claude/local/backlog/drafts/task-<id> - <slug>.md`.
   - Keep DoD + AC sections (user may re-promote).
   - Report: `Demoted task-<id> to drafts/`.

ID-stability invariant: task ID never changes across stage transitions. Only the directory prefix changes.

Data location: `~/.claude/local/backlog/drafts/`
See: `~/.claude/local/backlog/drafts/README.md` for lifecycle details.
