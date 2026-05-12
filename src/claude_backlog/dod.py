"""Definition of Done — inheritance, AC/DoD check/uncheck logic.

DoD = completion hygiene (project-wide, with per-task overrides).
AC  = scope/correctness (task-specific). Different lists, different roles.

The AC/DoD body sections in markdown bodies use GitHub-style checklists:

    ## Acceptance Criteria

    - [ ] Item one
    - [x] Item two

Index semantics:
- 1-based (mirrors MrLesk/Backlog.md). Index 1 → first item.
- Out-of-range → AC_INVALID / DOD_INVALID.
"""

from __future__ import annotations

import re
from typing import Literal

from claude_backlog.errors import BacklogToolError, ErrorCode
from claude_backlog.schema import Config, Task

ChecklistKind = Literal["ac", "dod"]

_HEADERS: dict[ChecklistKind, list[str]] = {
    "ac": ["## Acceptance Criteria", "## Acceptance criteria", "## acceptance criteria"],
    "dod": ["## Definition of Done", "## Definition of done", "## definition of done"],
}


def inherit_defaults(config: Config) -> list[str]:
    """Return project DoD defaults if `auto_inherit_dod` is set, else []."""
    if not config.auto_inherit_dod:
        return []
    return list(config.definition_of_done)


# --- Body-level checklist parsing -------------------------------------------

_CHECKBOX_RE = re.compile(r"^(\s*-\s*\[)([ xX])(\]\s*)(.*)$")


def _section_bounds(body: str, kind: ChecklistKind) -> tuple[int, int] | None:
    """Find the [start_line_idx, end_line_idx) of the section body.

    Returns None if no header matches. The start index points to the line
    AFTER the header. The end index is the line index of the next `## ` or
    end of file.
    """
    lines = body.splitlines()
    headers = _HEADERS[kind]
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        for h in headers:
            if stripped.startswith(h):
                start = i + 1
                break
        if start is not None:
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return start, end


def _toggle_checkbox(body: str, kind: ChecklistKind, index: int, *, checked: bool) -> str:
    """Toggle the Nth (1-based) checkbox in the given section."""
    bounds = _section_bounds(body, kind)
    if bounds is None:
        raise BacklogToolError(
            ErrorCode.AC_INVALID if kind == "ac" else ErrorCode.DOD_INVALID,
            f"No '{kind.upper()}' section found in task body.",
            context={"kind": kind},
        )
    start, end = bounds
    lines = body.splitlines(keepends=False)
    seen = 0
    for i in range(start, end):
        m = _CHECKBOX_RE.match(lines[i])
        if not m:
            continue
        seen += 1
        if seen == index:
            new_char = "x" if checked else " "
            lines[i] = f"{m.group(1)}{new_char}{m.group(3)}{m.group(4)}"
            # splitlines drops a trailing newline; preserve if original had one.
            result = "\n".join(lines)
            if body.endswith("\n"):
                result += "\n"
            return result
    raise BacklogToolError(
        ErrorCode.AC_INVALID if kind == "ac" else ErrorCode.DOD_INVALID,
        f"Index {index} out of range — only {seen} {kind.upper()} item(s) found.",
        context={"kind": kind, "index": index, "max": seen},
    )


def check_dod_item(task: Task, index: int) -> Task:
    """Return a new Task with DoD item N (1-based) marked `[x]`."""
    new_body = _toggle_checkbox(task.body, "dod", index, checked=True)
    return task.model_copy(update={"body": new_body})


def uncheck_dod_item(task: Task, index: int) -> Task:
    """Return a new Task with DoD item N (1-based) marked `[ ]`."""
    new_body = _toggle_checkbox(task.body, "dod", index, checked=False)
    return task.model_copy(update={"body": new_body})


def check_ac_item(task: Task, index: int) -> Task:
    """Return a new Task with AC item N (1-based) marked `[x]`."""
    new_body = _toggle_checkbox(task.body, "ac", index, checked=True)
    return task.model_copy(update={"body": new_body})


def uncheck_ac_item(task: Task, index: int) -> Task:
    """Return a new Task with AC item N (1-based) marked `[ ]`."""
    new_body = _toggle_checkbox(task.body, "ac", index, checked=False)
    return task.model_copy(update={"body": new_body})


def count_items(task: Task, kind: ChecklistKind) -> int:
    """Count checklist items in the named section (0 if section absent)."""
    bounds = _section_bounds(task.body, kind)
    if bounds is None:
        return 0
    start, end = bounds
    lines = task.body.splitlines()
    return sum(1 for i in range(start, end) if _CHECKBOX_RE.match(lines[i]))


def items_status(task: Task, kind: ChecklistKind) -> list[tuple[str, bool]]:
    """Return a list of `(text, checked)` tuples for the section.

    Empty list if section is absent.
    """
    bounds = _section_bounds(task.body, kind)
    if bounds is None:
        return []
    start, end = bounds
    lines = task.body.splitlines()
    out: list[tuple[str, bool]] = []
    for i in range(start, end):
        m = _CHECKBOX_RE.match(lines[i])
        if m:
            out.append((m.group(4).strip(), m.group(2).lower() == "x"))
    return out
