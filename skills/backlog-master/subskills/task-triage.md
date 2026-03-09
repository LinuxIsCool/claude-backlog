# Task Triage — Bulk Review & Housekeeping

## Stale Task Review

1. Glob `~/.claude/local/backlog/task-*.md`
2. Parse `updated:` and `status:` from frontmatter
3. Find tasks where `updated:` is more than 30 days ago AND status != `Done`
4. Present as table:

| ID | Title | Status | Last Updated | Days Stale |
|----|-------|--------|--------------|------------|

5. For each stale task, offer:
   - **Update** — change status or priority, set `updated:` to today
   - **Close** — mark `status: Done`, populate `final_summary`
   - **Archive** — move to `~/.claude/local/backlog/archive/`
   - **Delete** — remove the file (confirm first)

## Bulk Close

1. Scan all non-Done tasks for acceptance criteria
2. If every checkbox is checked (`- [x]`), the task is ready to close
3. Suggest marking each as `status: Done`
4. Auto-populate `final_summary` from description + acceptance criteria text
5. Set `updated:` to today

## Archive

- Move completed tasks to `~/.claude/local/backlog/archive/`
- Only archive tasks with `status: Done`
- If `auto_archive_done: true` in `~/.claude/local/backlog/config.yaml`:
  - Suggest archiving Done tasks older than `archive_after_days` since their `updated:` date
- Archive is non-destructive — files are moved, not deleted
- Create `archive/` directory if it doesn't exist

## Reconciliation

Scan for broken references and report each category:

**Invalid milestone references**:
- Find tasks with `milestone:` values that don't match any milestone in any venture file under `~/.claude/local/ventures/`
- Report: task ID, title, invalid milestone value

**Orphan milestones**:
- Find milestones in venture files that have zero tasks referencing them
- Report: venture name, milestone ID, milestone title

**Broken dependencies**:
- Find tasks with `dependencies:` or `blocked_by:` referencing non-existent task IDs
- Report: task ID, title, broken reference ID

## Priority Rebalancing

1. Count tasks per priority level (exclude Done)
2. If >50% are `critical` or `high`, suggest rebalancing
3. Show distribution: `"4 critical, 8 high, 2 medium, 1 low — consider downgrading some"`
4. Let user select tasks to reprioritize

## Triage Workflow

Run steps interactively:

1. **Stale tasks** — show table, user decides per task
2. **Ready to close** — show candidates, user confirms batch
3. **Reconciliation** — show broken refs, user fixes or ignores
4. **Priority balance** — show distribution, user rebalances if needed
5. **Summary** — `"Triaged X tasks: Y closed, Z archived, W updated"`

Invoke with `/backlog triage` or as part of session startup when stale count > 0.
