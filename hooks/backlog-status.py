#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6.0", "pydantic>=2.0"]
# ///
"""
Session-start hook: report backlog status.
Outputs JSON with systemMessage (visible banner) and additionalContext (Claude sees).

Imports the shared `claude_backlog` library so frontmatter parsing matches
the MCP server + skill implementations exactly. Runs via:

    uv run --directory ${CLAUDE_PLUGIN_ROOT} hooks/backlog-status.py

Phase 4 of task-435 (Backlog.md cross-pollination): replaces inline
`parse_frontmatter` with `claude_backlog.io.parse_frontmatter`.

Resolution strategy (Track A follow-up, 2026-05-12): inject
`<plugin>/src` into sys.path so the import works without needing
`uv run` to find the project venv. Robust against fresh sessions
whose venv isn't yet synced and concurrent runs racing on the venv
lock. The `# /// script` block above provides a third resolution
path via uv inline-script mode (zero project venv required).
"""

import json
import sys
from datetime import date
from pathlib import Path

# Resolution path 1: inject src/ before any claude_backlog import.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_SRC = _PLUGIN_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from claude_backlog.io import BACKLOG_ROOT, parse_frontmatter  # noqa: E402


def output(msg: str) -> None:
    """Output as JSON with both systemMessage and additionalContext."""
    print(json.dumps({
        "systemMessage": msg,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": msg,
        },
    }))


def main() -> None:
    # Consume stdin (Claude Code may pipe hook input)
    try:
        json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        pass

    if not BACKLOG_ROOT.exists():
        return

    task_files = sorted(BACKLOG_ROOT.glob("task-*.md"))
    if not task_files:
        output("[backlog] empty · /task to create first")
        return

    status_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    nearest_due: str | None = None
    nearest_due_title: str | None = None

    DONE_STATUSES = {"Done", "done", "Cancelled", "cancelled"}

    for f in task_files:
        fm = parse_frontmatter(f)
        status = fm.get("status", "To Do")
        priority = fm.get("priority", "medium")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status not in DONE_STATUSES:
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

        due = fm.get("due")
        if due and status != "Done":
            if nearest_due is None or str(due) < str(nearest_due):
                nearest_due = str(due)
                nearest_due_title = fm.get("title", f.stem)

    done_count = sum(status_counts.get(s, 0) for s in DONE_STATUSES)
    active = sum(status_counts.values()) - done_count
    if active == 0:
        output(f"[backlog] all done · {done_count} completed")
        return

    parts = [f"[backlog] {active} active"]
    if priority_counts.get("critical", 0) > 0:
        parts.append(f"{priority_counts['critical']} critical")
    if priority_counts.get("high", 0) > 0:
        parts.append(f"{priority_counts['high']} high")

    if nearest_due:
        try:
            due_date = date.fromisoformat(nearest_due)
            days_left = (due_date - date.today()).days
            parts.append(f"next due: \"{nearest_due_title}\" ({days_left}d)")
        except (ValueError, TypeError):
            pass

    output(" · ".join(parts))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
