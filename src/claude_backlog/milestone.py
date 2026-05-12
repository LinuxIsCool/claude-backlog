"""Milestone resolution — placeholder for Phase 4.5+.

claude-backlog tasks may carry a `milestone:` frontmatter field that
references a milestone defined in a venture file under
`~/.claude/local/ventures/`. Phase 4 MVP exposes the data field but
defers full resolution (parsing venture YAML, joining milestone IDs)
to a follow-up.

This module provides the API stub so callers can already depend on it.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_VENTURES = Path.home() / ".claude" / "local" / "ventures"


def ventures_root() -> Path:
    """Return the venture root path, honoring VENTURES_ROOT env override."""
    env = os.environ.get("VENTURES_ROOT")
    if env:
        return Path(env).expanduser()
    return _DEFAULT_VENTURES


def resolve(milestone_ref: str | int | None) -> dict | None:
    """Resolve a milestone reference to a metadata dict.

    Phase 4 MVP returns `{"ref": milestone_ref}` without joining venture
    data. The MCP server can call this to surface the raw ref in task
    payloads; full join lives in a later phase.
    """
    if milestone_ref is None:
        return None
    return {"ref": milestone_ref, "resolved": False}
