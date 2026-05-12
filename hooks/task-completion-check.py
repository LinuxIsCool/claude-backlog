#!/usr/bin/env python3
"""
Stop hook: remind about in-progress tasks after significant sessions.
Outputs JSON with systemMessage (visible) and additionalContext (Claude sees).

Imports the shared `claude_backlog` library — Phase 4 of task-435.
"""

import json
import sys

from claude_backlog.io import BACKLOG_ROOT, parse_frontmatter


def main() -> None:
    hook_input: dict = {}
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        pass

    transcript_turns = hook_input.get("transcript_turns", 0)

    if transcript_turns < 5:
        return

    if not BACKLOG_ROOT.exists():
        return

    task_files = sorted(BACKLOG_ROOT.glob("task-*.md"))
    in_progress: list[str] = []
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
    print(json.dumps({"systemMessage": msg}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
