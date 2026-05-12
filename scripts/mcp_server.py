# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "mcp>=1.0",
#     "pyyaml>=6.0",
#     "pydantic>=2.0",
# ]
# ///
"""claude-backlog MCP server — 11 tools + 1 workflow resource.

Phase 4.3 of task-435 (Backlog.md cross-pollination). Wraps the shared
`claude_backlog` library; never re-implements file ops.

Run standalone:
    uv run --directory <plugin-root> scripts/mcp_server.py

Registered via `.mcp.json`:
    {"mcpServers": {"claude-backlog": {"command": "uv", "args": [...]}}}

Resource:
    claude-backlog://workflow/overview  (text/markdown)

Environment:
    BACKLOG_ROOT     — override the backlog data root
                       (default ~/.claude/local/backlog)
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

# Make claude_backlog importable when invoked directly via `uv run` against
# this script (no editable install needed for the runtime path).
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp.server.fastmcp import FastMCP

from claude_backlog import (
    BACKLOG_ROOT,
    BacklogToolError,
    Config,
    ErrorCode,
    Stage,
    Task,
    find_task,
    list_tasks,
    mv_task,
    next_id,
    write_task,
)
from claude_backlog.dod import (
    check_ac_item,
    check_dod_item,
    inherit_defaults,
    uncheck_ac_item,
    uncheck_dod_item,
)
from claude_backlog.io import load_config, read_task, save_config, task_to_text
from claude_backlog.workflow import load_workflow

server = FastMCP("claude-backlog")


# --- helpers ----------------------------------------------------------------


def _error_payload(exc: BacklogToolError) -> str:
    """Serialize a BacklogToolError as a JSON payload for tool callers."""
    return json.dumps({"error": exc.to_dict()}, indent=2)


def _task_summary_line(t: Task) -> str:
    """One-line task summary for list views."""
    tag_str = f" [{', '.join(t.tags)}]" if t.tags else ""
    due_str = f" due:{t.due.isoformat()}" if t.due else ""
    return f"  - #{t.id} ({t.priority}) [{t.status}] {t.title}{tag_str}{due_str}"


def _full_view(t: Task) -> str:
    """Markdown rendering of a task — frontmatter table + body."""
    lines = [
        f"# Task {t.id}: {t.title}",
        "",
        f"- **Status**: {t.status}",
        f"- **Priority**: {t.priority}",
        f"- **Created**: {t.created.isoformat()}",
    ]
    if t.due:
        lines.append(f"- **Due**: {t.due.isoformat()}")
    if t.venture:
        lines.append(f"- **Venture**: {t.venture}")
    if t.milestone:
        lines.append(f"- **Milestone**: {t.milestone}")
    if t.tags:
        lines.append(f"- **Tags**: {', '.join(t.tags)}")
    if t.estimated_hours is not None:
        lines.append(f"- **Estimated hours**: {t.estimated_hours}")
    if t.depends_on:
        lines.append(f"- **Depends on**: {t.depends_on}")
    if t.blocks:
        lines.append(f"- **Blocks**: {t.blocks}")
    if t.modified_files:
        lines.append(f"- **Modified files**: {t.modified_files}")
    if t.parent_task:
        lines.append(f"- **Parent task**: #{t.parent_task}")
    if t.definition_of_done:
        lines.append(f"- **DoD items**: {len(t.definition_of_done)}")
    lines.append("")
    lines.append(t.body or "_(no body)_")
    return "\n".join(lines)


def _matches(t: Task, *, status: str | None, priority: str | None,
             tag: str | None, venture: str | None, milestone: str | None) -> bool:
    if status and t.status.lower() != status.lower():
        return False
    if priority and t.priority != priority:
        return False
    if tag and tag not in t.tags:
        return False
    if venture and t.venture != venture:
        return False
    if milestone is not None and str(t.milestone) != str(milestone):
        return False
    return True


# --- resource ---------------------------------------------------------------


@server.resource(
    "claude-backlog://workflow/overview",
    mime_type="text/markdown",
)
async def workflow_overview() -> str:
    """Canonical agent-onboarding doc for the claude-backlog plugin."""
    return load_workflow("overview")


# --- tools ------------------------------------------------------------------


@server.tool()
async def get_backlog_instructions() -> str:
    """Return the workflow/overview document as markdown.

    Fallback for MCP clients that do not support resources. The content
    is identical to the `claude-backlog://workflow/overview` resource.
    """
    return load_workflow("overview")


@server.tool()
async def task_list(
    status: str | None = None,
    priority: str | None = None,
    tag: str | None = None,
    venture: str | None = None,
    milestone: str | None = None,
    include_drafts: bool = False,
    include_archive: bool = False,
    limit: int = 50,
) -> str:
    """List tasks, filtered by status / priority / tag / venture / milestone.

    Args:
        status: Exact match against task `status` (case-insensitive for
            done/cancelled, exact otherwise).
        priority: One of `critical`, `high`, `medium`, `low`.
        tag: Match if the tag is in the task's `tags` list.
        venture: Match against the venture slug.
        milestone: Match against the milestone ref (string equality).
        include_drafts: If true, also list tasks in `drafts/`.
        include_archive: If true, also list tasks in `archive/`.
        limit: Maximum tasks to return (default 50).

    Returns markdown summary.
    """
    rows: list[Task] = []
    for t in list_tasks(Stage.ACTIVE):
        if _matches(t, status=status, priority=priority, tag=tag,
                    venture=venture, milestone=milestone):
            rows.append(t)
    if include_drafts:
        for t in list_tasks(Stage.DRAFTS):
            if _matches(t, status=status, priority=priority, tag=tag,
                        venture=venture, milestone=milestone):
                rows.append(t)
    if include_archive:
        for t in list_tasks(Stage.ARCHIVE):
            if _matches(t, status=status, priority=priority, tag=tag,
                        venture=venture, milestone=milestone):
                rows.append(t)

    if not rows:
        return "_No tasks matched._"

    rows.sort(
        key=lambda t: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(t.priority, 9),
            -t.id,
        )
    )
    truncated = rows[:limit]
    header = f"**{len(truncated)}** task(s)"
    if len(rows) > limit:
        header += f" (showing first {limit} of {len(rows)})"
    lines = [header, ""]
    lines.extend(_task_summary_line(t) for t in truncated)
    return "\n".join(lines)


@server.tool()
async def task_view(task_id: int, include_drafts: bool = True,
                    include_archive: bool = True) -> str:
    """Return the full frontmatter + body of a task by ID."""
    stages: list[Stage] = [Stage.ACTIVE]
    if include_drafts:
        stages.append(Stage.DRAFTS)
    if include_archive:
        stages.append(Stage.ARCHIVE)
    path = None
    for s in stages:
        path = find_task(task_id, s)
        if path is not None:
            break
    if path is None:
        return _error_payload(BacklogToolError(
            ErrorCode.TASK_NOT_FOUND,
            f"No task with id={task_id}",
            context={"task_id": task_id},
        ))
    try:
        task = read_task(path)
    except BacklogToolError as exc:
        return _error_payload(exc)
    return _full_view(task)


@server.tool()
async def task_search(
    query: str,
    search_modified_files: bool = False,
    search_tags: bool = False,
    limit: int = 50,
) -> str:
    """Substring search across active tasks.

    Args:
        query: Substring to look for. Case-insensitive.
        search_modified_files: Also match against `modified_files`.
        search_tags: Also match against `tags`.
        limit: Max results.

    Searches title + body always. Optional fields toggle via flags.
    """
    needle = query.lower()
    if not needle.strip():
        return "_Empty query._"

    hits: list[tuple[Task, str]] = []
    for t in list_tasks(Stage.ACTIVE):
        where: list[str] = []
        if needle in t.title.lower():
            where.append("title")
        if needle in t.body.lower():
            where.append("body")
        if search_tags and any(needle in tag.lower() for tag in t.tags):
            where.append("tags")
        if search_modified_files and any(needle in mf.lower() for mf in t.modified_files):
            where.append("modified_files")
        if where:
            hits.append((t, "+".join(where)))

    if not hits:
        return f"_No tasks matched '{query}'._"

    hits.sort(key=lambda pair: (-len(pair[1].split("+")), -pair[0].id))
    truncated = hits[:limit]
    lines = [f"**{len(truncated)}** hit(s) for '{query}'", ""]
    for t, where in truncated:
        lines.append(f"  - #{t.id} ({t.priority}) [{t.status}] {t.title}  _(match: {where})_")
    return "\n".join(lines)


@server.tool()
async def task_create(
    title: str,
    priority: str = "medium",
    status: str = "To Do",
    tags: list[str] | None = None,
    venture: str | None = None,
    milestone: str | None = None,
    estimated_hours: float | None = None,
    depends_on: list[int] | None = None,
    blocks: list[int] | None = None,
    parent_task: int | None = None,
    documentation: list[str] | None = None,
    modified_files: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    disable_dod_defaults: bool = False,
    extra_definition_of_done: list[str] | None = None,
    body: str | None = None,
) -> str:
    """Create a new task. Inherits DoD from config.yml by default.

    Args:
        title: Required. Becomes the slug.
        priority: One of critical/high/medium/low. Default 'medium'.
        status: Default 'To Do'.
        tags: List of tags.
        venture: Optional venture slug.
        milestone: Optional milestone ref.
        estimated_hours: Optional float.
        depends_on, blocks: Lists of task IDs.
        parent_task: Optional parent task ID.
        documentation: List of doc IDs / URLs.
        modified_files: List of repo-relative paths to be edited.
        acceptance_criteria: AC bullets. If supplied, rendered as
            `## Acceptance Criteria` in body.
        disable_dod_defaults: If true, do NOT copy config DoD into the task.
        extra_definition_of_done: Additional DoD items appended after defaults.
        body: Optional raw markdown body. If omitted, an AC + DoD scaffold
            is generated.

    Returns the created task ID and path.
    """
    try:
        cfg = load_config()
    except BacklogToolError as exc:
        return _error_payload(exc)

    dod: list[str] = [] if disable_dod_defaults else inherit_defaults(cfg)
    if extra_definition_of_done:
        dod.extend(extra_definition_of_done)

    new_id = next_id()

    # Build body if not supplied
    if body is None:
        sections: list[str] = ["\n"]
        if acceptance_criteria:
            sections.append("## Acceptance Criteria\n")
            for ac in acceptance_criteria:
                sections.append(f"- [ ] {ac}")
            sections.append("")
        else:
            sections.append("## Acceptance Criteria\n\n- [ ] _TBD_\n")
        if dod:
            sections.append("## Definition of Done\n")
            for item in dod:
                sections.append(f"- [ ] {item}")
            sections.append("")
        body = "\n".join(sections)

    try:
        task = Task(
            id=new_id,
            title=title,
            status=status,
            priority=priority,
            created=date.today(),
            tags=tags or [],
            venture=venture,
            milestone=milestone,
            estimated_hours=estimated_hours,
            depends_on=depends_on or [],
            blocks=blocks or [],
            parent_task=parent_task,
            documentation=documentation or [],
            modified_files=modified_files or [],
            definition_of_done=dod,
            body=body,
        )
    except Exception as exc:  # pydantic ValidationError or similar
        return _error_payload(BacklogToolError(
            ErrorCode.VALIDATION_ERROR,
            f"Task validation failed: {exc}",
        ))

    try:
        path = write_task(task)
    except BacklogToolError as exc:
        return _error_payload(exc)

    return json.dumps({
        "ok": True,
        "task_id": task.id,
        "path": str(path),
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "dod_inherited": len(dod),
    }, indent=2)


@server.tool()
async def task_edit(
    task_id: int,
    title: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    tags: list[str] | None = None,
    venture: str | None = None,
    milestone: str | None = None,
    estimated_hours: float | None = None,
    depends_on: list[int] | None = None,
    blocks: list[int] | None = None,
    modified_files: list[str] | None = None,
    check_ac: list[int] | None = None,
    uncheck_ac: list[int] | None = None,
    check_dod: list[int] | None = None,
    uncheck_dod: list[int] | None = None,
    append_body: str | None = None,
) -> str:
    """Edit an existing task.

    All field args are optional. Provide only the fields you want to change.

    AC / DoD list args are **1-based**. E.g. `check_dod=[1, 3]` marks the
    first and third DoD items complete. Out-of-range raises
    AC_INVALID / DOD_INVALID.

    `append_body` adds the text to the end of the body, separated by a
    blank line. Useful for progress notes.
    """
    path = find_task(task_id, Stage.ANY)
    if path is None:
        return _error_payload(BacklogToolError(
            ErrorCode.TASK_NOT_FOUND,
            f"No task with id={task_id}",
            context={"task_id": task_id},
        ))
    try:
        task = read_task(path)
    except BacklogToolError as exc:
        return _error_payload(exc)

    updates: dict = {}
    if title is not None:
        updates["title"] = title
    if status is not None:
        updates["status"] = status
    if priority is not None:
        updates["priority"] = priority
    if tags is not None:
        updates["tags"] = tags
    if venture is not None:
        updates["venture"] = venture
    if milestone is not None:
        updates["milestone"] = milestone
    if estimated_hours is not None:
        updates["estimated_hours"] = estimated_hours
    if depends_on is not None:
        updates["depends_on"] = depends_on
    if blocks is not None:
        updates["blocks"] = blocks
    if modified_files is not None:
        updates["modified_files"] = modified_files

    if updates:
        try:
            task = task.model_copy(update=updates)
            # Re-validate by round-tripping through model_validate
            task = Task.model_validate(task.model_dump())
        except Exception as exc:
            return _error_payload(BacklogToolError(
                ErrorCode.VALIDATION_ERROR,
                f"Task validation failed after edit: {exc}",
            ))

    try:
        for idx in (check_ac or []):
            task = check_ac_item(task, idx)
        for idx in (uncheck_ac or []):
            task = uncheck_ac_item(task, idx)
        for idx in (check_dod or []):
            task = check_dod_item(task, idx)
        for idx in (uncheck_dod or []):
            task = uncheck_dod_item(task, idx)
    except BacklogToolError as exc:
        return _error_payload(exc)

    if append_body:
        sep = "" if task.body.endswith("\n") else "\n"
        task = task.model_copy(update={"body": task.body + sep + "\n" + append_body + "\n"})

    # Stage may have changed if title changed → new filename. write_task
    # handles ID-collision; we ensure the existing file is updated in place.
    path.write_text(task_to_text(task))

    return json.dumps({
        "ok": True,
        "task_id": task.id,
        "path": str(path),
        "status": task.status,
    }, indent=2)


@server.tool()
async def task_archive(task_id: int) -> str:
    """Move a task from active to archive/. Idempotent if already archived."""
    archived = find_task(task_id, Stage.ARCHIVE)
    if archived is not None:
        return json.dumps({
            "ok": True,
            "task_id": task_id,
            "path": str(archived),
            "already_archived": True,
        }, indent=2)
    active = find_task(task_id, Stage.ACTIVE)
    if active is None:
        return _error_payload(BacklogToolError(
            ErrorCode.TASK_NOT_FOUND,
            f"No active task with id={task_id}",
            context={"task_id": task_id},
        ))
    try:
        dest = mv_task(task_id, Stage.ACTIVE, Stage.ARCHIVE)
    except BacklogToolError as exc:
        return _error_payload(exc)
    return json.dumps({
        "ok": True,
        "task_id": task_id,
        "path": str(dest),
    }, indent=2)


@server.tool()
async def draft_list(limit: int = 50) -> str:
    """List tasks in drafts/."""
    drafts = list(list_tasks(Stage.DRAFTS))
    if not drafts:
        return "_No drafts._"
    drafts.sort(key=lambda t: -t.id)
    truncated = drafts[:limit]
    lines = [f"**{len(truncated)}** draft(s)"]
    if len(drafts) > limit:
        lines[0] += f" (showing first {limit} of {len(drafts)})"
    lines.append("")
    lines.extend(_task_summary_line(t) for t in truncated)
    return "\n".join(lines)


@server.tool()
async def draft_promote(task_id: int) -> str:
    """Move a draft to active. Inherits DoD; adds AC stub if absent."""
    path = find_task(task_id, Stage.DRAFTS)
    if path is None:
        return _error_payload(BacklogToolError(
            ErrorCode.DRAFT_NOT_FOUND,
            f"No draft with id={task_id}",
            context={"task_id": task_id},
        ))
    try:
        task = read_task(path)
    except BacklogToolError as exc:
        return _error_payload(exc)

    try:
        cfg = load_config()
    except BacklogToolError as exc:
        return _error_payload(exc)

    inherit_now = inherit_defaults(cfg) if not task.definition_of_done else []
    if inherit_now:
        task = task.model_copy(update={"definition_of_done": inherit_now})

    if task.status.lower() == "draft":
        task = task.model_copy(update={"status": "To Do"})

    # Add `## Acceptance Criteria` if missing
    if "## Acceptance Criteria" not in task.body and "## Acceptance criteria" not in task.body:
        stub = "\n## Acceptance Criteria\n\n- [ ] _TBD on promotion — please fill in_\n"
        task = task.model_copy(update={"body": task.body + stub})

    # Add `## Definition of Done` body if DoD is now populated and body lacks it
    if task.definition_of_done and "## Definition of Done" not in task.body:
        sections = ["", "## Definition of Done", ""]
        for item in task.definition_of_done:
            sections.append(f"- [ ] {item}")
        sections.append("")
        task = task.model_copy(update={"body": task.body + "\n".join(sections)})

    # Persist the updated content in drafts/, then move.
    path.write_text(task_to_text(task))
    try:
        dest = mv_task(task_id, Stage.DRAFTS, Stage.ACTIVE)
    except BacklogToolError as exc:
        return _error_payload(exc)

    return json.dumps({
        "ok": True,
        "task_id": task.id,
        "path": str(dest),
        "status": task.status,
        "dod_inherited": len(inherit_now),
    }, indent=2)


@server.tool()
async def definition_of_done_defaults_get() -> str:
    """Return the current project DoD defaults from config.yml."""
    try:
        cfg = load_config()
    except BacklogToolError as exc:
        return _error_payload(exc)
    return json.dumps({
        "auto_inherit_dod": cfg.auto_inherit_dod,
        "definition_of_done": cfg.definition_of_done,
    }, indent=2)


@server.tool()
async def definition_of_done_defaults_upsert(
    items: list[str],
    auto_inherit_dod: bool | None = None,
) -> str:
    """Replace project DoD defaults in config.yml.

    Args:
        items: Full replacement list of DoD items. The old list is discarded.
        auto_inherit_dod: If supplied, also updates the inherit toggle.

    Affects FUTURE tasks only. Existing tasks keep their per-task DoD.
    """
    try:
        cfg = load_config()
    except BacklogToolError as exc:
        return _error_payload(exc)
    updates: dict = {"definition_of_done": items}
    if auto_inherit_dod is not None:
        updates["auto_inherit_dod"] = auto_inherit_dod
    new_cfg = cfg.model_copy(update=updates)
    try:
        save_config(new_cfg)
    except BacklogToolError as exc:
        return _error_payload(exc)
    return json.dumps({
        "ok": True,
        "definition_of_done": items,
        "auto_inherit_dod": new_cfg.auto_inherit_dod,
    }, indent=2)


# --- entry point ------------------------------------------------------------


def _diag() -> None:
    """Print a one-line diagnostic when invoked with --diag (smoke check)."""
    tools = [name for name in dir(server) if not name.startswith("_")]
    print(json.dumps({
        "ok": True,
        "backlog_root": str(BACKLOG_ROOT),
        "backlog_root_exists": BACKLOG_ROOT.exists(),
        "server_name": "claude-backlog",
    }))


if __name__ == "__main__":
    if "--diag" in sys.argv:
        _diag()
    else:
        server.run()
