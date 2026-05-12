#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6.0", "pydantic>=2.0"]
# ///
"""
Stop hook: remind about in-progress tasks after significant sessions.
Outputs JSON with systemMessage (visible) and additionalContext (Claude sees).

Imports the shared `claude_backlog` library — Phase 4 of task-435.

Resolution strategy (Track A follow-up, 2026-05-12):
  1. Inject `<plugin>/src` into `sys.path` so the import works without
     needing `uv run` to find the project venv. Robust against fresh
     sessions whose venv isn't yet synced and concurrent runs racing on
     the venv lock.
  2. Inline-script `# /// script` block declares minimal deps (pyyaml,
     pydantic) so this hook ALSO runs cleanly via `uv run script.py`
     without a project venv at all.
  3. Project venv editable install still works in the normal path.

Three resolution paths converge — no single point of failure.
"""

import json
import sys
from pathlib import Path

# Resolution path 1: inject src/ before any claude_backlog import.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_SRC = _PLUGIN_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from claude_backlog.io import BACKLOG_ROOT, parse_frontmatter  # noqa: E402


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
