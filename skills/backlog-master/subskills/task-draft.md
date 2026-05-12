# Task Draft — Create, Promote, Demote, List

Drafts are unscoped ideas living in `~/.claude/local/backlog/drafts/`.
Same ID space as active tasks. ID-stable across promotion / demotion.

Phase 2 of task-435 (Backlog.md cross-pollination, 2026-05-12).

## When to invoke

- User says "draft", "capture an idea", "unscoped idea", "rough thought".
- User invokes `/draft create | list | promote | demote`.
- User asks to triage drafts or promote from drafts.

## Subskill operations

### draft create

1. **Determine next ID** — scan all of:
   - `~/.claude/local/backlog/task-*.md` (active)
   - `~/.claude/local/backlog/drafts/task-*.md`
   - `~/.claude/local/backlog/archive/task-*.md`
   Extract numeric IDs via `task-(\d+)` regex. New ID = `max + 1`.
2. **Slugify title** — lowercase, hyphens for spaces, strip special chars, max 60 chars.
3. **Write file** to `~/.claude/local/backlog/drafts/task-<id> - <slug>.md`.
4. **Frontmatter** — lightweight. Same schema as task-writer, but:
   - `status: draft`
   - DoD inheritance is **SKIPPED** for drafts. DoD applies on promotion.
   - Optional fields may be absent / empty.
5. **Body** — Description + Notes section. Acceptance Criteria + Definition of Done sections are OMITTED for drafts (they kick in on promotion).
6. **Report** — `Drafted task-{id} - {title} (drafts/{filename})`.

### draft list

1. Glob `~/.claude/local/backlog/drafts/task-*.md`.
2. For each, read frontmatter — extract `id`, `title`, `priority`, `created`, `tags`.
3. Display sorted by `created` descending (newest first).
4. Show count, oldest age, summary distribution.

### draft promote `<id>`

1. **Locate draft** — `~/.claude/local/backlog/drafts/task-<id> - *.md`. Error if missing.
2. **Load frontmatter + body**.
3. **Update frontmatter** — change `status: draft` → `status: To Do` (or whatever the project's default-active status is, from `~/.claude/local/backlog/config.yml` `statuses[0]`). Set `updated: today`. Set `modified_at: now`.
4. **Inherit DoD** — read `definition_of_done` + `auto_inherit_dod` from `config.yml`. If `auto_inherit_dod: true`:
   - Copy items into `definition_of_done:` frontmatter list.
   - Append `## Definition of Done` body section after `## Acceptance Criteria` (or at end of body if AC section absent — but a promoted task SHOULD have AC).
5. **Ensure body sections** — if `## Acceptance Criteria` is missing, append a stub:
   ```
   ## Acceptance Criteria

   - [ ] (criterion to be defined)
   ```
   Surface to user: "Promoted task-{id} needs Acceptance Criteria — please scope before progressing to In Progress."
6. **Move file** — `git mv` (or filesystem `mv`) from `drafts/task-NNN - slug.md` → `task-NNN - slug.md`. **ID stays. Filename stays except for the drafts/ prefix.**
7. **Report** — `Promoted task-{id} from drafts/ to active. DoD: {n} items. AC: {present|stub}.`

### draft demote `<id>`

Rare. Only when an active task turns out to be unscoped after starting it.

1. **Locate active task** — `~/.claude/local/backlog/task-<id> - *.md`. Error if missing.
2. **Sanity check** — refuse if `status: In Progress` or `Done` or `Blocked`. Drafts should not contain real work history. If user insists, prompt for confirmation.
3. **Update frontmatter** — change `status: To Do` (or current) → `status: draft`. Set `updated: today`.
4. **Move file** — `task-NNN - slug.md` → `drafts/task-NNN - slug.md`.
5. **Keep DoD + AC sections** — do NOT strip them. The user may re-promote later.
6. **Report** — `Demoted task-{id} from active to drafts/. (DoD + AC sections preserved.)`

## ID-stability invariant

```
task-NNN keeps its ID across:
  drafts/ → active     (promote)
  active → drafts/     (demote)
  active → archive/    (archive)
  archive/ → active    (un-archive, manual)
```

Only the directory prefix changes. Filename stem (`task-NNN - slug.md`)
stays identical unless user explicitly renames slug.

## Sanity checks on ID collision

If a draft ID collides with an active ID (shouldn't happen if ID generation
scans all dirs, but defensive):
- Refuse to promote. Report both file paths. Ask user to resolve manually.

## Integration with /task

`/task create --draft "Title"` is equivalent to `/draft create "Title"`.
Both invoke this subskill. Aliased for ergonomic flexibility.

## Triage workflow

During `/backlog triage`, drafts are surfaced with the question:
"Promote, edit, or delete?" Drafts older than 30 days surface
automatically with a recommendation to delete or promote.

## Workflow summary

| Op | File before | File after | ID | Status |
|---|---|---|---|---|
| draft create | (none) | drafts/task-N - slug.md | N | draft |
| draft promote N | drafts/task-N - slug.md | task-N - slug.md | N | To Do |
| draft demote N | task-N - slug.md | drafts/task-N - slug.md | N | draft |

Keep operations fast and idempotent. Always preserve task content across
moves. Never lose history.
