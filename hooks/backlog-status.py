#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""
Session-start hook: report backlog status.
Outputs JSON with systemMessage (visible banner) and additionalContext (Claude sees).
"""

import json
import re
import sys
from pathlib import Path

import yaml

BACKLOG_ROOT = Path.home() / ".claude" / "local" / "backlog"


def output(msg: str):
    """Output as JSON with both systemMessage and additionalContext."""
    print(json.dumps({
        "systemMessage": msg,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": msg,
        },
    }))


def parse_frontmatter(path: Path) -> dict:
    content = path.read_text()
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    return yaml.safe_load(content[3:end]) or {}


def main():
    # Consume stdin (Claude Code may pipe hook input)
    try:
        json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        pass

    if not BACKLOG_ROOT.exists():
        return

    # Find all active task files (not in archive/)
    task_files = sorted(BACKLOG_ROOT.glob("task-*.md"))
    if not task_files:
        output("[backlog] empty · /task to create first")
        return

    # Parse frontmatter and count by status/priority
    status_counts = {"To Do": 0, "In Progress": 0, "Blocked": 0, "Done": 0}
    priority_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    nearest_due = None
    nearest_due_title = None

    for f in task_files:
        fm = parse_frontmatter(f)
        status = fm.get("status", "To Do")
        priority = fm.get("priority", "medium")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status != "Done":
            priority_counts[priority] = priority_counts.get(priority, 0) + 1

        # Check due dates
        due = fm.get("due")
        if due and status != "Done":
            if nearest_due is None or str(due) < str(nearest_due):
                nearest_due = str(due)
                nearest_due_title = fm.get("title", f.stem)

    active = status_counts.get("To Do", 0) + status_counts.get("In Progress", 0) + status_counts.get("Blocked", 0)
    if active == 0:
        output(f"[backlog] all done · {status_counts.get('Done', 0)} completed")
        return

    parts = [f"[backlog] {active} active"]
    if priority_counts.get("critical", 0) > 0:
        parts.append(f"{priority_counts['critical']} critical")
    if priority_counts.get("high", 0) > 0:
        parts.append(f"{priority_counts['high']} high")

    if nearest_due:
        from datetime import date
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
