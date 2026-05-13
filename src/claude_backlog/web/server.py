"""claude-backlog web server — thin satellite of claude_webui.WebuiKernel.

POST-PIVOT (task-441 Phase 2, task-442 §0): every concern that does not
vary between substrate webuis (ThreadingHTTPServer, route dispatch, gzip,
hard-405 on mutations, /healthz, /api/list, /api/detail, /api/stats,
/api/feed, Range support, Server-Timing) lives in the kernel. This file
only WIRES the BacklogAccessor into the kernel and points at the
satellite's `static/` directory.

If this file grows past ~50 LOC, the wrong thing is being added here —
push it into the accessor (data shape) or into claude-webui (cross-cutting
shell concern).
"""

from __future__ import annotations

from pathlib import Path

from claude_webui import WebuiKernel

from claude_backlog import __version__ as _BACKLOG_VERSION
from claude_backlog.web.accessor import NAMESPACE, BacklogAccessor

# Static assets shipped with this plugin. The kernel passes this as
# `static_dir` so /index.html and /static/* both resolve here.
STATIC_DIR: Path = Path(__file__).resolve().parent / "static"


def build_kernel(
    *,
    port: int = 6420,
    bind: str = "127.0.0.1",
    root: Path | None = None,
) -> WebuiKernel:
    """Construct a configured WebuiKernel for the claude-backlog satellite.

    Returns the kernel without calling `.serve()` so tests can drive the
    underlying server directly via `kernel.build_server()`.
    """
    accessor = BacklogAccessor(root=root)
    kernel = WebuiKernel(
        accessor=accessor,
        port=port,
        bind=bind,
        static_dir=STATIC_DIR,
    )
    # Stamp the satellite-reported version for /api/version (if the kernel
    # ever surfaces one — purely informational for now).
    kernel.satellite_namespace = NAMESPACE  # type: ignore[attr-defined]
    kernel.satellite_version = _BACKLOG_VERSION  # type: ignore[attr-defined]
    return kernel
