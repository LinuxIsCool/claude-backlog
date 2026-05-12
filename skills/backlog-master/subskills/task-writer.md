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

# Optional additive fields (Phase 1 — Backlog.md cross-pollination, task-435).
# Emit only when the writer has a value for them. Leave absent (don't emit) when empty
# for `modified_files`, `documentation`, `parent_task`, `ordinal`, `on_status_change`.
# ALWAYS emit `definition_of_done` (inherits config defaults — see DoD Inheritance below).
modified_files: []
ordinal: null
parent_task: null
documentation: []
on_status_change: null
definition_of_done: {dod_items_inherited_from_config_or_empty}
---
```

## Body Template

```markdown
## Description

{description}

## Acceptance Criteria

- [ ] {criterion 1}
- [ ] {criterion 2}

## Definition of Done

{dod_section_inherited_from_config_or_user_provided}

## Notes

## Final Summary

_Filled on completion._
```

## Definition of Done Inheritance

DoD is completion hygiene, distinct from Acceptance Criteria (scope/correctness).

1. Read `~/.claude/local/backlog/config.yml`.
2. If `auto_inherit_dod: true` (default), copy the `definition_of_done` list into:
   - the new task's `definition_of_done` frontmatter field (as a flat list of strings)
   - the new task's `## Definition of Done` body section (as `- [ ] item` checklist)
3. If the user passes `--no-dod-defaults`, leave both empty (task body section is omitted).
4. If the user passes explicit DoD items via flag (`--dod "Custom item"`), use those instead of config defaults.

Example config:

```yaml
definition_of_done:
  - Acceptance criteria met
  - Tests written or updated (if code path touched)
  - Documentation updated if needed
  - Type-check / lint passes (if code path touched)
  - Backlog status moved to Done
  - No known issues remaining
auto_inherit_dod: true
```

## modified_files

Repo-relative paths an agent (human or AI) edited as part of this task. Surfaces tasks when grepping by file path:

```bash
grep -l "src/foo.ts" ~/.claude/local/backlog/task-*.md
```

Leave empty at creation. Agents populate as they work.

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
5. **DoD** — load `definition_of_done` from `~/.claude/local/backlog/config.yml`. If `auto_inherit_dod: true` and user did not pass `--no-dod-defaults`, copy into the new task's `definition_of_done` frontmatter list + `## Definition of Done` body section. If user passed `--dod "Item"` flags, use those instead.
6. **Create file** — write frontmatter + body to `~/.claude/local/backlog/task-NNN - slug.md`
7. **Report** — `Created task-{id} - {title} (priority: {priority}, milestone: {milestone}, DoD: {n} items)`

Keep creation fast. Don't over-prompt. Extract what you can from context, ask only for what's missing.
