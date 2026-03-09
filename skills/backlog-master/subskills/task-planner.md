# Task Planner — Sprint Planning & Priority Review

Answers: "What should I work on next?"

## Planning Algorithm

1. **Gather**: Read all `~/.claude/local/backlog/task-*.md` with status "To Do" or "In Progress"
2. **Parse**: Extract YAML frontmatter (id, title, priority, milestone, dependencies, blocked_by, created, estimate)
3. **Resolve milestones**: For each task with `milestone:`, scan `~/.claude/local/ventures/` for the venture containing that milestone. Inherit the venture's deadline.
4. **Score each task** (0-100):

| Factor | Weight | Scoring |
|--------|--------|---------|
| Milestone deadline proximity | 40% | Cliff curve: <7d=100, <14d=80, <30d=60, <60d=40, >60d=20, none=10 |
| Task priority | 30% | critical=100, high=75, medium=50, low=25 |
| Unblocks others | 20% | Count tasks listing this ID in `dependencies` or `blocked_by`. 3+=100, 2=75, 1=50, 0=0 |
| Age (days since created) | 10% | `min(days_since_created, 30) / 30 * 100` |

5. **Present** top 5-10 tasks with score breakdown

## Sprint Planning Mode

### "Plan my day"
- Select 3-5 tasks, total estimated effort ~6 hours
- Include at least one quick win (<30min) for momentum
- Front-load the highest-priority item

### "Plan my week"
- Select 8-15 tasks across different milestones
- Mix high-priority with quick wins for sustainable pace
- Group by milestone for context switching efficiency
- Leave ~20% buffer for emergent work

## Dependency Analysis

- **Blocked tasks**: Show what blocks them and current status of blockers
- **High leverage**: Highlight tasks that unblock the most downstream work
- **Critical path**: If dependencies form a chain, visualize it:
  ```
  task-12 → task-15 → task-18 → task-22 (chain length: 4)
  ```
- Flag circular dependencies as errors

## Milestone Progress

For each active milestone:
- Completion: X/Y tasks done (Z%)
- Remaining effort estimate (sum of task estimates)
- Flag milestones behind schedule: deadline approaching + low completion

## Venture Awareness

Check venture deadlines from `~/.claude/local/ventures/`. Surface alerts like:
> "Salish Sea Dreaming deadline in 37 days — ms-dataset 0/3 tasks complete"

Flag any venture with: `(days_remaining / total_days) < (tasks_remaining / total_tasks)`

## Output Format

```
## Recommended Next Tasks

| # | Task | Priority | Milestone | Score | Why |
|---|------|----------|-----------|-------|-----|
| 1 | task-42: Curate kelp images | high | ms-dataset | 87 | Deadline in 37d, unblocks 2 |
| 2 | task-38: Fix export pipeline | critical | ms-pipeline | 82 | Critical priority, unblocks 3 |
| 3 | task-51: Write test harness | medium | ms-testing | 64 | Quick win (30min), ages well |

## Milestone Status
- ms-dataset: 0/3 (0%) — deadline: April 15 (37d) ⚠️
- ms-pipeline: 2/5 (40%) — deadline: April 30 (52d)
- ms-testing: 1/4 (25%) — no deadline

## Blocked Tasks
- task-44: Blocked by task-42 (status: To Do)
- task-47: Blocked by task-38, task-39 (1/2 resolved)
```

## Invocation

```
/backlog plan          # top 5 recommendations
/backlog plan day      # day sprint plan (~6h)
/backlog plan week     # week sprint plan
/backlog milestones    # milestone progress overview
/backlog blocked       # dependency analysis
```
