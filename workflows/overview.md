# claude-backlog — Agent Workflow Overview

This document is the canonical agent-onboarding resource for the
`claude-backlog` plugin. It is served as an MCP resource at:

    claude-backlog://workflow/overview

and is also available via the `get_backlog_instructions` MCP tool for
clients that do not support resources.

If you are an external agent (Codex, Cursor, a Legion persona, or any
MCP-aware tool), read this file **before** issuing any other
`claude-backlog` MCP call.

> Companion documents (cross-referenced throughout):
> - `AGENTS.md` — public-surface boundary contract (what is and is not
>   stable). Required reading.
> - `CLAUDE.md` — plugin overview, quick-start commands, file layout.
> - `skills/backlog-master/SKILL.md` — the in-context skill (when you are
>   running inside Claude Code with the plugin loaded).

---

## 1. When to create a task

A `claude-backlog` task represents **tactical, time-bounded work** with
acceptance criteria and a definition of done. Use the decision tree
below before reaching for `task_create`.

```
Is the idea concrete + actionable in the next 1-4 weeks?
│
├─ NO  → /scratchpad it (or capture in journal). Not yet a task.
│
└─ YES
   │
   ├─ Could it have acceptance criteria today?
   │  │
   │  ├─ NO  → Create a DRAFT (`draft_create`). It will live in drafts/
   │  │         until ACs are scoped. Promote later via `draft_promote`.
   │  │
   │  └─ YES
   │     │
   │     ├─ Is it strategic, multi-quarter, with milestones?
   │     │  ├─ YES → It's a VENTURE concern. Surface to /venture, not /task.
   │     │  └─ NO  → Create a task: `task_create`.
   │     │
   │     └─ Is it a status-update / progress-note on existing work?
   │        ├─ YES → Edit the existing task (`task_edit`). Do NOT duplicate.
   │        └─ NO  → Create the task.
```

### When **not** to create a task

- Pure capture / brainstorm → scratchpad.
- Reflection / decision rationale → journal.
- Cross-cutting initiative spanning multiple months → venture.
- Recurring rhythm or schedule item → rhythms / schedule plugins.
- Communication to a person → comms or outbox plugins.
- Pure knowledge artefact → research / knowledge plugins.

---

## 2. Task creation conventions

### Always-required fields

| Field | Why |
|---|---|
| `title` | Human-readable. Becomes the slug in the filename. |
| `priority` | One of `critical`, `high`, `medium`, `low`. Default `medium`. |
| `status` | Default `To Do`. Other values: `In Progress`, `Blocked`, `Done`. |

The plugin assigns the next free integer `id` automatically.

### Strongly-encouraged fields

| Field | When to use |
|---|---|
| `tags` | Always include at least one. Tags drive triage filters. |
| `estimated_hours` | When the work is large enough to bother planning. |
| `venture` | If the task belongs to a known venture (e.g., `longtail-financial`). |
| `milestone` | If the task closes a specific venture milestone. |
| `depends_on` | Other task IDs blocking this one. |
| `due` | If there is a real external deadline. Do NOT inflate. |
| `modified_files` | When the task involves editing specific code paths. Lets `grep` find owning tasks. |

### Acceptance Criteria vs Definition of Done

This distinction is **non-negotiable**. The plugin enforces it at the
data layer and the doctrine is restated in `AGENTS.md`.

| | Acceptance Criteria | Definition of Done |
|---|---|---|
| **Scope** | Task-specific | Project-wide (with overrides) |
| **Question** | *What does this task deliver?* | *What is always required before status=Done?* |
| **Examples** | "Implement OAuth login flow", "Migrate 50 records", "Plot renders within 2s" | "Tests written", "Documentation updated", "Lint passes" |
| **Lives in** | `## Acceptance Criteria` body section | `## Definition of Done` body + `definition_of_done` frontmatter list |
| **MCP tools** | `task_edit` with `check_ac` / `uncheck_ac` indices | `task_edit` with `check_dod` / `uncheck_dod` indices |

Never collapse them. AC describes the work. DoD describes the
discipline.

### Inheriting Definition of Done

By default, `task_create` copies the project's `definition_of_done`
from `~/.claude/local/backlog/config.yml` into the new task's
`definition_of_done` list **and** appends a `## Definition of Done`
section to the body. To suppress this (for trivial one-line meta-tasks),
pass `disable_dod_defaults=true`.

Read the current project defaults with
`definition_of_done_defaults_get`. Update them with
`definition_of_done_defaults_upsert` — note that updates apply
**only to future tasks**, not to existing ones.

---

## 3. Lifecycle and status transitions

```
              draft_create               draft_promote
   (idea) ─────────────────▶  drafts/  ─────────────────▶  active (To Do)
                                ▲                            │
                                │ draft_demote               │
                                │ (only from To Do)          │ task_edit status
                                │                            ▼
                                └──── status transitions ──▶ In Progress
                                                              │
                                                              ├─▶ Blocked
                                                              │
                                                              └─▶ Done
                                                                   │
                                                                   │ task_archive
                                                                   ▼
                                                                archive/
```

### Canonical status values

| Status | Stage | Meaning |
|---|---|---|
| `draft` | drafts/ | Not yet scoped; AC may be empty. |
| `To Do` | active | Ready to work. |
| `In Progress` | active | Someone is actively working it. |
| `Blocked` | active | Waiting on a dependency (note it in body). |
| `Done` | active or archive/ | All AC + DoD checked. |
| `Cancelled` | active or archive/ | Will never be done. Captures the why. |

Case-insensitive matching applies to `done` and `cancelled` only (see
`AGENTS.md` "Status values"). All other statuses are exact-match.

### Transitions must use the documented tools

| From | To | Tool |
|---|---|---|
| (new) | drafts/ | `draft_create` (not exposed at Phase 4 MVP) |
| (new) | active | `task_create` |
| drafts/ | active | `draft_promote` |
| active | drafts/ | (skill / CLI only — Phase 4 MVP does not expose this in MCP) |
| active | archive/ | `task_archive` |

**Never write task files directly.** The plugin enforces ID-stability,
DoD inheritance, and filename conventions through the documented tools.
Bypassing them silently breaks downstream rhythms and persona briefs.

---

## 4. MCP tool quick reference

The Phase 4 MVP exposes 11 tools. Each one validates its inputs through
Pydantic models before touching the filesystem. Errors surface as
`BacklogToolError` with a typed `code`.

| Tool | Read-only | What it does |
|---|---|---|
| `get_backlog_instructions` | yes | Returns this document. Fallback for clients without resource support. |
| `task_list` | yes | List active tasks. Optional filters: status, priority, tag, venture, milestone. Optional `include_drafts`, `include_archive`. |
| `task_view` | yes | Full frontmatter + body for a given ID. |
| `task_search` | yes | Substring + tag + modified_files search. |
| `task_create` | no | Create new task. Inherits DoD unless `disable_dod_defaults=true`. |
| `task_edit` | no | Edit fields, check/uncheck AC + DoD by 1-based index, append notes. |
| `task_archive` | no | Move task to archive/. Idempotent if already archived. |
| `draft_list` | yes | List drafts in drafts/. |
| `draft_promote` | no | Move `drafts/task-N - slug.md` → active. Inherits DoD; adds AC stub if absent. |
| `definition_of_done_defaults_get` | yes | Returns the current project DoD defaults. |
| `definition_of_done_defaults_upsert` | no | Replace project DoD defaults. Affects future tasks only. |

### Indexing semantics

AC and DoD check/uncheck operations use **1-based** indices. The first
item is index 1, not 0. Out-of-range raises `AC_INVALID` or
`DOD_INVALID`. This mirrors the upstream MrLesk/Backlog.md convention.

### Error codes

The full list lives in `claude_backlog.errors.ErrorCode`:

- `TASK_NOT_FOUND`, `DRAFT_NOT_FOUND`
- `ID_COLLISION`
- `VALIDATION_ERROR`, `CONFIG_ERROR`
- `DOD_INVALID`, `AC_INVALID`
- `INVALID_STAGE`, `INVALID_STATUS_TRANSITION`
- `FILE_IO_ERROR`

Branch on `error.code` rather than parsing prose messages.

---

## 5. Drafts vs active tasks

Drafts capture "good ideas that aren't yet projects." The drafts plane
exists so the active backlog stays uncluttered while preserving capture.

### Use a draft when

- The idea is real but acceptance criteria are not yet writable.
- You want to defer scoping to a planning session.
- The work depends on a decision that has not been made.

### Promote when

- ACs become concrete.
- The work is the next reasonable thing to do.
- A milestone or venture pulls it.

### Demote (skill-only at Phase 4 MVP)

A `To Do` task may be demoted back to a draft. `In Progress`, `Blocked`,
and `Done` tasks cannot be demoted — they live where they live.

---

## 6. Cross-plugin etiquette

Tasks rarely live alone. When you create or edit one, consider the
neighbours:

- **journal** — Decision rationale + reflection on why a task exists.
  Link via the journal entry's title; do not copy prose into the task.
- **venture** — Strategic container. Reference via `venture:` and
  `milestone:` frontmatter.
- **scratchpad** — Capture sibling. Items often graduate from
  scratchpad → draft → task.
- **knowledge / koi** — Research that informs a task lives in research
  bundles. Link with the `documentation:` frontmatter field.
- **outbox** — Communication with a human. Do not stuff drafts of
  messages into task bodies; the outbox owns drafts.
- **rhythms** — Cadenced check-ins. The rhythm investigators read tasks
  to build briefs. Keep `status` honest so briefs are honest.

---

## 7. Required reading

Before issuing `task_create`, `task_edit`, or `task_archive`:

1. Skim **`AGENTS.md`** (this plugin) — declares the public surface,
   conventions, and boundary doctrine. The AC vs DoD distinction is
   non-negotiable.
2. Skim **`CLAUDE.md`** (this plugin) — file layout, frontmatter
   contract, lifecycle diagram.
3. Read **this document** (`workflow/overview`).

When in doubt, ask the user — do not invent new conventions.

---

## 8. Quick examples

### Creating a task with explicit DoD override

```python
task_create(
    title="Wire up Plaza View hero image",
    priority="high",
    tags=["ecoscene", "plaza-v1"],
    venture="ecoscene-oasis",
    estimated_hours=1.5,
    modified_files=["src/components/plaza/Hero.tsx"],
    disable_dod_defaults=False,  # inherit project DoD
)
```

### Marking the first DoD item complete

```python
task_edit(
    id=438,
    check_dod=[1],  # 1-based — first DoD checkbox toggles to [x]
)
```

### Promoting a draft

```python
draft_promote(id=99)
# Moves drafts/task-99 - slug.md → task-99 - slug.md
# Inherits DoD from config.yml definition_of_done
# Adds `## Acceptance Criteria` stub if body lacks one
```

### Archiving a completed task

```python
task_edit(id=438, status="Done")
task_archive(id=438)
# Idempotent if already archived
```

---

## Provenance

- Phase 4.2 of task-435 (Backlog.md cross-pollination).
- Derived from MrLesk/Backlog.md `workflows/` resource pattern.
- Plugin AGENTS.md is the boundary-contract companion; this file is
  the workflow companion.
- Last updated: 2026-05-12.
