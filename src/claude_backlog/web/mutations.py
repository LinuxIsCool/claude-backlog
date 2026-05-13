"""Mutation handlers for the claude-backlog satellite (task-446 Phase B3).

Pattern C of task-446 §4.3: each handler is a thin wrapper around the
same in-process library function the MCP server's `task_edit` tool calls.
Symmetric AI-and-human contract — an MCP client and the browser hit the
same code, just via different transports.

Handlers receive a validated args dict. Validation lives here (not on
the kernel side) because it's domain-specific. Errors are raised as
MutationError with structured codes the browser maps to toast messages.

Three handlers shipped in this phase:

  - set_status   — move a task across kanban columns
  - set_priority — cycle the priority badge
  - set_tag      — add or remove a tag

Each is registered with `register_handlers(catalog)` which is idempotent
and called from `web/server.py` during `build_kernel()`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_webui.dispatcher import MutationCatalog, MutationError

from claude_backlog.io import Stage, find_task, read_task, write_task
from claude_backlog.schema import Task


# ── canonical vocabularies ──────────────────────────────────────────────

# The five canonical kanban statuses + Draft (lifecycle-only — drafts
# live in their own stage but the satellite still surfaces the value).
# Mirror of the claude-backlog vocabulary; kept here so the dispatcher
# rejects ill-typed input BEFORE Pydantic coerces it.
CANONICAL_STATUSES: set[str] = {"To Do", "In Progress", "Blocked", "Done", "Draft"}

CANONICAL_PRIORITIES: tuple[str, ...] = ("critical", "high", "medium", "low")


# ── helpers ─────────────────────────────────────────────────────────────


def _coerce_task_id(value: Any) -> int:
    """Accept int OR legacy 'task-NNN' string forms.

    Raises MutationError(INVALID_ARGS) on unparseable input. Mirrors the
    schema's id-coercer so the dispatcher and MCP tool accept the same
    inputs.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        import re

        m = re.match(r"^(?:task[-_]?)?(\d+)", value, re.IGNORECASE)
        if m:
            return int(m.group(1))
    raise MutationError(
        MutationError.INVALID_ARGS,
        "args.id must be an integer (or legacy 'task-NNN' string)",
        details={"received": repr(value), "type": type(value).__name__},
    )


def _load_task(args: dict[str, Any]) -> tuple[Task, Path, Stage]:
    """Locate + parse the target task. Returns (task, path, stage).

    The stage is inferred from the path so write_task() preserves it
    (set_status on a task in archive/ keeps it there; the column move
    happens by status, not by directory).
    """
    task_id = _coerce_task_id(args.get("id"))
    path = find_task(task_id, Stage.ANY)
    if path is None:
        raise MutationError(
            MutationError.NOT_FOUND,
            f"no task with id={task_id}",
            details={"id": task_id},
            rollback_hint="refresh — task may have been archived",
        )
    # Infer stage from path. Parent-of-parent matches the Stage dir layout
    # (ACTIVE is BACKLOG_ROOT itself; DRAFTS is BACKLOG_ROOT/drafts; etc).
    parent_name = path.parent.name
    if parent_name == "drafts":
        stage = Stage.DRAFTS
    elif parent_name == "archive":
        stage = Stage.ARCHIVE
    else:
        stage = Stage.ACTIVE
    return read_task(path), path, stage


# ── handlers ────────────────────────────────────────────────────────────


def set_status(args: dict[str, Any]) -> dict[str, Any]:
    """Mutate the status field of one task.

    args: `{id: int, status: str (canonical 5)}`

    Returns `{id, status, previous_status, path}` on change.
    Returns `{id, status, noop: true}` when current == target.
    Raises MutationError(INVALID_STATUS) on unknown status.
    """
    task, _path, stage = _load_task(args)
    new_status = args.get("status")
    if not isinstance(new_status, str) or new_status not in CANONICAL_STATUSES:
        raise MutationError(
            "INVALID_STATUS",
            f"status must be one of {sorted(CANONICAL_STATUSES)}",
            details={"received": new_status},
            rollback_hint="snap card back; status unchanged",
        )

    previous_status = task.status
    if previous_status == new_status:
        return {
            "id": task.id,
            "status": new_status,
            "noop": True,
        }

    updated = task.model_copy(update={"status": new_status})
    new_path = write_task(updated, stage)
    return {
        "id": task.id,
        "status": new_status,
        "previous_status": previous_status,
        "path": str(new_path),
    }


def set_priority(args: dict[str, Any]) -> dict[str, Any]:
    """Mutate the priority field of one task.

    args: `{id: int, priority: 'critical' | 'high' | 'medium' | 'low'}`

    Click-to-cycle UX is browser-side — the handler just validates the
    target value.
    """
    task, _path, stage = _load_task(args)
    new_priority = args.get("priority")
    if not isinstance(new_priority, str) or new_priority.lower() not in CANONICAL_PRIORITIES:
        raise MutationError(
            "INVALID_PRIORITY",
            f"priority must be one of {list(CANONICAL_PRIORITIES)}",
            details={"received": new_priority},
            rollback_hint="snap badge back; priority unchanged",
        )
    new_priority = new_priority.lower()
    previous_priority = task.priority
    if previous_priority == new_priority:
        return {
            "id": task.id,
            "priority": new_priority,
            "noop": True,
        }
    updated = task.model_copy(update={"priority": new_priority})
    new_path = write_task(updated, stage)
    return {
        "id": task.id,
        "priority": new_priority,
        "previous_priority": previous_priority,
        "path": str(new_path),
    }


def set_tag(args: dict[str, Any]) -> dict[str, Any]:
    """Add or remove a tag on one task.

    args: `{id: int, tag: str, op: 'add' | 'remove'}`

    Idempotent on both ops: adding an already-present tag returns
    `noop: true`; removing an already-absent tag does the same. This
    matches Pattern C anti-pattern §"args_schema divergent from MCP"
    — the MCP `task_edit` tool is also idempotent on tag ops.
    """
    task, _path, stage = _load_task(args)
    tag = args.get("tag")
    op = args.get("op")
    if not isinstance(tag, str) or not tag.strip():
        raise MutationError(
            MutationError.INVALID_ARGS,
            "tag must be a non-empty string",
            details={"received": tag},
        )
    if op not in {"add", "remove"}:
        raise MutationError(
            MutationError.INVALID_ARGS,
            "op must be 'add' or 'remove'",
            details={"received": op},
        )
    tag = tag.strip()
    current = list(task.tags)

    if op == "add":
        if tag in current:
            return {"id": task.id, "tag": tag, "op": "add", "noop": True}
        new_tags = current + [tag]
    else:  # remove
        if tag not in current:
            return {"id": task.id, "tag": tag, "op": "remove", "noop": True}
        new_tags = [t for t in current if t != tag]

    updated = task.model_copy(update={"tags": new_tags})
    new_path = write_task(updated, stage)
    return {
        "id": task.id,
        "tag": tag,
        "op": op,
        "tags": new_tags,
        "path": str(new_path),
    }


# ── registration ────────────────────────────────────────────────────────


def register_handlers(catalog: MutationCatalog) -> None:
    """Register all claude-backlog mutation handlers on a catalog.

    Idempotent — re-calling replaces handlers (useful for tests that
    construct fresh catalogs).
    """
    catalog.register(
        "set_status",
        set_status,
        args_schema={
            "id": {"type": "integer", "required": True},
            "status": {
                "type": "string",
                "required": True,
                "enum": sorted(CANONICAL_STATUSES),
            },
        },
    )
    catalog.register(
        "set_priority",
        set_priority,
        args_schema={
            "id": {"type": "integer", "required": True},
            "priority": {
                "type": "string",
                "required": True,
                "enum": list(CANONICAL_PRIORITIES),
            },
        },
    )
    catalog.register(
        "set_tag",
        set_tag,
        args_schema={
            "id": {"type": "integer", "required": True},
            "tag": {"type": "string", "required": True},
            "op": {"type": "string", "required": True, "enum": ["add", "remove"]},
        },
    )
