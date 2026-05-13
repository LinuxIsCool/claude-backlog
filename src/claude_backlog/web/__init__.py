"""claude-backlog web UI — first satellite of claude-webui (task-441 Phase 2).

POST-PIVOT (2026-05-12, task-442 §0): the web shell, route dispatch, gzip,
healthz, hard-405, Range support, and per-instance Handler subclassing all
live in `claude_webui` (Surfacing cluster shell). claude-backlog supplies
only the `BacklogAccessor` (5-method Accessor Protocol implementation) and
the satellite-specific `index.html` + `static/*` assets.

Public API kept small — just the accessor + the CLI entry point so other
plugins (e.g. claude-rhythms investigators) can introspect the namespace
without spawning a server.
"""

from claude_backlog.web.accessor import NAMESPACE, BacklogAccessor

__all__ = ["BacklogAccessor", "NAMESPACE"]
