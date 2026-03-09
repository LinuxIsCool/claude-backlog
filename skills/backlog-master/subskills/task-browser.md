# Task Browser — Search & Navigate Tasks

## Browse Modes

All modes read from `~/.claude/local/backlog/task-*.md`.

- `browse` or `browse all` — active tasks (status != Done), grouped by status, sorted by priority within group
- `browse milestone:ms-dataset` — tasks for a specific milestone
- `browse venture:salish-sea-dreaming` — resolve venture's milestones from `~/.claude/local/ventures/`, then find all tasks linked to those milestones
- `browse priority:critical` (or high, medium, low) — filter by priority
- `browse blocked` — blocked tasks with their blockers
- `browse done` — completed tasks from last 30 days
- `browse assignee:@legion` — filter by assignee

## Search

`search <keyword>` — Grep across all task files (title, description, tags, notes). Show matching tasks with surrounding context.

## Stats

`stats` — aggregate overview:

- Total tasks by status (To Do: X, In Progress: Y, Blocked: Z, Done: W)
- Total by priority
- Total by milestone (with completion %)
- Orphan tasks (no milestone)
- Average task age (days since created)
- Recently completed (last 7 days)

## Display Format

### Browse Results

```
## Active Tasks (12)

### In Progress (2)
| ID | Title | Priority | Milestone | Due | Age |
|----|-------|----------|-----------|-----|-----|
| 43 | Train autolume model | high | ms-autolume | — | 3d |

### To Do (8)
| ID | Title | Priority | Milestone | Due | Age |
|----|-------|----------|-----------|-----|-----|
| 42 | Curate kelp images | high | ms-dataset | — | 5d |

### Blocked (2)
| ID | Title | Blocked By | Milestone |
|----|-------|------------|-----------|
| 44 | Test projection | task:43 | ms-touchdesigner |
```

### Stats Results

```
## Backlog Stats

| Status | Count |
|--------|-------|
| To Do | 8 |
| In Progress | 2 |
| Blocked | 2 |
| Done | 15 |

| Priority | Count |
|----------|-------|
| critical | 1 |
| high | 5 |
| medium | 12 |
| low | 9 |

| Milestone | Total | Done | % |
|-----------|-------|------|---|
| ms-dataset | 6 | 2 | 33% |
| ms-autolume | 4 | 0 | 0% |
| (none) | 3 | — | — |

Avg task age: 8d | Completed (7d): 3
```

## Implementation

1. **Glob** `~/.claude/local/backlog/task-*.md` to collect all task files
2. **Read** each file, parse YAML frontmatter — extract id, title, status, priority, milestone, assignee, created, due, blocked_by, dependencies
3. **Filter** based on browse mode parameters
4. **Sort** — within each status group, order by priority: critical > high > medium > low
5. **Age** — compute days between `created` date and today
6. **Render** — format as markdown tables per the display format above

For **search**: use Grep with the keyword pattern across `~/.claude/local/backlog/task-*.md`, then Read matched files to build the result table.

For **venture browse**: Glob `~/.claude/local/ventures/{venture}/milestones/ms-*.md`, extract milestone IDs, then filter tasks by those milestones.

No external dependencies. Glob + Read + Grep only.
