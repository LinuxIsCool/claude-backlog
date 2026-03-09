# Task Writer — Creating Backlog Tasks

## ID Generation

1. Glob `~/.claude/local/backlog/task-*.md`
2. Extract numeric ID from each filename: `task-(\d+)`
3. New ID = max(all extracted IDs) + 1. If no tasks exist, start at 1.

## Filename Convention

`task-NNN - slugified-title.md`

- Zero-pad ID to 3 digits
- Slugify title: lowercase, replace spaces with hyphens, strip special characters, max 60 chars
- Example: `task-042 - curate-kelp-forest-images.md`

## Frontmatter Template

```yaml
---
id: {next_id}
title: "{title}"
milestone: {milestone_id or null}
status: To Do
priority: {priority or medium}
assignee: "@legion"
labels: []
tags: []
created: {today YYYY-MM-DD}
updated: {today YYYY-MM-DD}
due: null
dependencies: []
blocked_by: []
references: []
outgoing_links: []
modified_at: "{ISO timestamp}"
modified_count: 0
summary: "{1-2 sentence summary}"
final_summary: null
---
```

## Body Template

```markdown
## Description

{description}

## Acceptance Criteria

- [ ] {criterion 1}
- [ ] {criterion 2}

## Notes

## Final Summary

_Filled on completion._
```

## Milestone Auto-Detection

If conversation context includes venture info (user invoked /ventures, or is discussing a specific venture):

1. Scan that venture's milestones directory
2. List matching milestones as numbered options
3. Suggest the most relevant one based on task description
4. Let user confirm or pick a different milestone

If no venture context, set milestone to `null` and move on.

## outgoing_links Extraction

Scan the description text for namespace references and auto-populate `outgoing_links`:

- `venture:X` — link to venture X
- `task:N` — link to task N
- `journal:YYYY-MM-DD` — link to journal entry

Extract all matches and add them to the array. Don't prompt — just populate silently.

## Workflow

1. **Determine next ID** — glob, extract, increment
2. **Title** — extract from user message, or ask if ambiguous
3. **Milestone** — suggest if venture context available, otherwise null
4. **Priority** — use stated priority, default to `medium`
5. **Create file** — write frontmatter + body to `~/.claude/local/backlog/task-NNN - slug.md`
6. **Report** — `Created task-{id} - {title} (priority: {priority}, milestone: {milestone})`

Keep creation fast. Don't over-prompt. Extract what you can from context, ask only for what's missing.
