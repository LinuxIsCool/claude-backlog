"""claude-backlog web server — thin satellite of claude_webui.WebuiKernel.

POST-PIVOT (task-441 Phase 2, task-442 §0): every concern that does not
vary between substrate webuis (ThreadingHTTPServer, route dispatch, gzip,
hard-405 on mutations, /healthz, /api/list, /api/detail, /api/stats,
/api/feed, Range support, Server-Timing) lives in the kernel. This file
only:
  1. Wires the BacklogAccessor into the kernel.
  2. Subclasses WebuiHandler to add backlog-specific extra GET routes
     (/api/facets, /api/search) until the upstream kernel grows a public
     extra_routes hook.
  3. Points at the satellite's `static/` directory.

If this file grows past ~120 LOC, the wrong thing is being added here —
push it into the accessor (data shape) or upstream into claude-webui
(cross-cutting shell concern).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claude_webui import WebuiKernel
from claude_webui.kernel import WebuiHandler

from claude_backlog import __version__ as _BACKLOG_VERSION
from claude_backlog.web.accessor import NAMESPACE, BacklogAccessor

# Static assets shipped with this plugin. The kernel passes this as
# `static_dir` so /index.html and /static/* both resolve here.
STATIC_DIR: Path = Path(__file__).resolve().parent / "static"


class BacklogHandler(WebuiHandler):
    """WebuiHandler + backlog-specific extra GET routes.

    Override `_dispatch_get` so the kernel's standard routes work unchanged
    AND `/api/facets` + `/api/search` resolve before the kernel's
    not-found fallback. The kernel will grow a public `extra_routes` hook
    in a future minor version; until then this is the kernel-doctrine-
    aligned extension point per the WebuiHandler docstring:

        "Each kernel instance gets its own handler subclass."
    """

    def _dispatch_get(self) -> None:  # noqa: D401
        # Parse once — same shape the kernel uses.
        import mimetypes
        from urllib.parse import parse_qs, unquote, urlparse

        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/facets":
            try:
                payload = self.accessor.facets()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=500)
                return
            self._send_json(payload)
            return
        if path == "/api/search":
            params_raw = parse_qs(parsed.query, keep_blank_values=True)
            params = {k: v[0] if v else "" for k, v in params_raw.items()}
            try:
                payload = self.accessor.search(params)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": str(exc)}, status=500)
                return
            self._send_json(payload)
            return
        # /static/<path> — satellite-supplied assets (CSS, JS, vendored libs).
        # The kernel doesn't expose static dispatch beyond index.html, so we
        # walk static_dir ourselves with a path-traversal guard.
        if path.startswith("/static/"):
            if self.static_dir is None:
                self._send_json({"error": "no static_dir configured"}, status=500)
                return
            rel = path[len("/static/") :]
            if not rel:
                self._send_json({"error": "empty static path"}, status=404)
                return
            target = (self.static_dir / rel).resolve()
            try:
                target.relative_to(self.static_dir.resolve())
            except ValueError:
                self._send_json({"error": "forbidden"}, status=403)
                return
            if not target.is_file():
                self._send_json({"error": f"not found: {rel}"}, status=404)
                return
            ctype, _ = mimetypes.guess_type(str(target))
            if ctype is None:
                ctype = "application/octet-stream"
            self._send_bytes(
                target.read_bytes(),
                content_type=ctype,
                cache_control="public, max-age=300",
            )
            return
        # Fall through to the kernel's standard route table.
        super()._dispatch_get()


class BacklogKernel(WebuiKernel):
    """WebuiKernel that builds a BacklogHandler subclass.

    Identical to the upstream kernel except for the handler class used —
    keeps every other concern (server lifecycle, build_server, serve, stop,
    bind warnings) untouched.
    """

    def _make_handler_class(self) -> type[WebuiHandler]:
        accessor = self.accessor
        static_dir = self.static_dir
        event_bus = self._event_bus

        class _Handler(BacklogHandler):
            pass

        _Handler.accessor = accessor
        _Handler.static_dir = static_dir
        _Handler.event_bus = event_bus
        return _Handler


def build_kernel(
    *,
    port: int = 6420,
    bind: str = "127.0.0.1",
    root: Path | None = None,
) -> BacklogKernel:
    """Construct a configured kernel for the claude-backlog satellite.

    Returns the kernel without calling `.serve()` so tests can drive the
    underlying server directly via `kernel.build_server()`.

    Real-time push (R2/R3) is wired here: the kernel watches the backlog
    root + drafts + archive directories via inotify when available, and
    falls back to polling the accessor's `(count, max_mtime)` signature
    every 1s. The browser EventSource on /api/events receives broadcasts
    within <50ms (inotify) or <1s (polling).
    """
    from claude_backlog.io import BACKLOG_ROOT, Stage

    accessor = BacklogAccessor(root=root)
    backlog_root = root or BACKLOG_ROOT

    # Watch all three stage directories. Drafts + archive may not exist
    # yet on a fresh install; InotifyWatcher.available filters them out.
    watch_paths = [
        backlog_root,
        backlog_root / "drafts",
        backlog_root / "archive",
    ]
    watch_paths = [p for p in watch_paths if p.exists()]

    # Signature fn is the polling fallback when inotify is unavailable.
    # Use Stage.ANY so any file change in any stage drives a broadcast.
    def _signature_for_push() -> tuple:
        return accessor._signature(Stage.ANY)

    kernel = BacklogKernel(
        accessor=accessor,
        port=port,
        bind=bind,
        static_dir=STATIC_DIR,
        signature_fn=_signature_for_push,
        watch_paths=watch_paths,
        poll_interval_s=1.0,
    )
    kernel.satellite_namespace = NAMESPACE  # type: ignore[attr-defined]
    kernel.satellite_version = _BACKLOG_VERSION  # type: ignore[attr-defined]
    return kernel
