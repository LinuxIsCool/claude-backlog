# Task Linker — Cross-System Linking & Dependencies

## Link Management

- **Set milestone**: update task's `milestone:` field (e.g., `milestone: ms-dataset`)
- **Add outgoing links**: append to `outgoing_links:` array — `task:N`, `venture:slug`, `journal:YYYY-MM-DD`
- **Add references**: append URLs to `references:` array
- **Add dependencies**: update `dependencies:` on this task AND `blocked_by:` on the target (bidirectional)

## Namespace Syntax

| Prefix | Example | Resolves to |
|--------|---------|-------------|
| `task:` | `task:42` | A backlog task |
| `milestone:` | `milestone:ms-dataset` | A milestone (lives in a venture file) |
| `venture:` | `venture:salish-sea-dreaming` | A venture |
| `journal:` | `journal:2026-03-09` | A journal day |
| `journal:` | `journal:2026-03-09/12-11-roadmap` | A specific journal entry |
| `person:` | `person:carol-anne-hilton` | A co-venturer/contact |

## Resolution Rules

| From → To | How |
|-----------|-----|
| task → milestone | Read task's `milestone:` field |
| task → venture | Resolve milestone → scan venture files for that milestone ID |
| milestone → tasks | Grep all task files for `milestone: ms-X` |
| venture → tasks | Get venture's milestone IDs → grep tasks for each |
| task → journal | Direct reference in `outgoing_links` |
| journal → task | Direct reference in journal's `related:` field |

## Dependency Graph

When asked to show dependencies, build an ASCII tree:

```
task-40: Set up data pipeline
├── task-41: Download kelp images (depends on 40)
│   └── task-42: Curate kelp images (depends on 41)
└── task-45: Set up training env (depends on 40)
```

Walk `dependencies:` / `blocked_by:` fields recursively. Detect cycles and warn.

## Orphan Detection

- Find tasks with `milestone: null` — these need milestone assignment
- Suggest milestones based on tag overlap with existing milestone-linked tasks
- Surface orphans during `/backlog triage` and session-start

## Link Suggestions

When creating or viewing a task, suggest links based on:
- Tag overlap with other tasks/ventures/journal entries
- Shared milestone membership
- Recently mentioned venture context
- Temporal proximity (journal entries near task creation date)

## Bidirectional Sync

When adding `dependencies: [41]` to task-42:
1. Also add `blocked_by: [42]` to task-41
2. If task-41 doesn't exist, warn but still save the forward link
3. If `blocked_by: [42]` already present on task-41, skip (idempotent)

When removing a dependency, remove both directions.

## Operations

| Intent | Action |
|--------|--------|
| "link task 42 to venture salish-sea-dreaming" | Append `venture:salish-sea-dreaming` to task-42's `outgoing_links` |
| "task 42 depends on 41" | Add 41 to task-42 `dependencies`, add 42 to task-41 `blocked_by` |
| "show dependency tree for task 40" | Walk graph, render ASCII tree |
| "find orphan tasks" | Grep tasks where `milestone: null` |
| "assign task 42 to milestone ms-dataset" | Set `milestone: ms-dataset` on task-42 |
