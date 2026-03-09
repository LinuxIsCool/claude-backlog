#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""
Stop hook: remind about in-progress tasks after significant sessions.
Outputs JSON with systemMessage (visible) and additionalContext (Claude sees).
"""

import json
import sys
from pathlib import Path

import yaml

BACKLOG_ROOT = Path.home() / ".claude" / "local" / "backlog"


def parse_frontmatter(path: Path) -> dict:
    content = path.read_text()
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    return yaml.safe_load(content[3:end]) or {}


def main():
    # Read hook input from stdin
    hook_input = {}
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        pass

    transcript_turns = hook_input.get("transcript_turns", 0)

    # If very few turns, not worth checking
    if transcript_turns < 5:
        return

    if not BACKLOG_ROOT.exists():
        return

    # Find in-progress tasks
    task_files = sorted(BACKLOG_ROOT.glob("task-*.md"))
    in_progress = []
    for f in task_files:
        fm = parse_frontmatter(f)
        if fm.get("status") == "In Progress":
            in_progress.append(fm.get("title", f.stem))

    if not in_progress:
        return

    count = len(in_progress)
    titles = ", ".join(in_progress[:3])
    if count > 3:
        titles += f" (+{count - 3} more)"

    msg = f"[backlog] {count} in-progress: {titles}. Consider /backlog to update status."
    print(json.dumps({
        "systemMessage": msg,
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": msg,
        },
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
