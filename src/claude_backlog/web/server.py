"""ThreadingHTTPServer + request handler for the claude-backlog web UI.

Phase 5.1 surface (this release):
  GET /                 → index.html (Alpine.js SPA)
  GET /list             → index.html (client-side route)
  GET /task/<id>        → index.html
  GET /stats            → index.html
  GET /graph            → index.html
  GET /embed            → index.html
  GET /heatmap          → index.html
  GET /fdg              → index.html
  GET /fdg-hm           → index.html
  GET /compass          → index.html
  GET /static/<path>    → bundled static asset (CSS / JS)
  GET /healthz          → "ok\n"
  GET /api/version      → {name, version, phase}  (smoke-test endpoint)

Phase 5.2-5.6 add /api/tasks, /api/stats, /api/events (SSE), /api/embed/* and the
write APIs (POST/PATCH/DELETE). They are intentionally NOT registered here so
the 5.1 surface stays small and easy to test.

The handler is wired through `make_handler(static_root, debug)` so tests can
substitute a temp directory and inject debug logging without monkey-patching.
"""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import socket
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Type

LOG = logging.getLogger("claude_backlog.web")

# --- Versioning --------------------------------------------------------------

# Bumped manually when the web-UI public surface changes (routes / response
# shapes). The "phase" reflects which Phase 5 sub-phase has shipped; new code
# in this directory should bump it as the corresponding sub-phase lands.
WEB_VERSION = "0.1.0"
WEB_PHASE = "5.1"

# --- Static asset routing ----------------------------------------------------

# Resolve the bundled static dir at import time. Tests can override by passing
# a custom `static_root` into `make_handler()`.
_DEFAULT_STATIC_ROOT: Path = Path(__file__).resolve().parent / "static"


# Client-side route names. Every entry here is served by `index.html` so the
# Alpine.js router can hydrate the matching view. The set is small enough to
# enumerate inline; expanding it in later sub-phases is intentional.
_SPA_ROUTES: frozenset[str] = frozenset(
    {
        "/",
        "/list",
        "/stats",
        "/graph",
        "/embed",
        "/heatmap",
        "/fdg",
        "/fdg-hm",
        "/compass",
    }
)


def _is_spa_route(path: str) -> bool:
    """Return True if `path` should be hydrated by the Alpine.js router."""
    if path in _SPA_ROUTES:
        return True
    # /task/<id> — opaque trailing segment; hydrated by the detail view.
    if path.startswith("/task/") and path.count("/") == 2:
        return True
    return False


# --- Handler factory ---------------------------------------------------------


def make_handler(
    static_root: Path | None = None,
    *,
    debug: bool = False,
) -> Type[BaseHTTPRequestHandler]:
    """Build a request-handler class bound to a specific static root.

    The factory pattern lets tests swap in a temp dir without touching module
    state. `debug=True` swaps the silent access log for a default logger.
    """
    root = (static_root or _DEFAULT_STATIC_ROOT).resolve()

    class Handler(BaseHTTPRequestHandler):
        # Stay quiet by default — Python's BaseHTTPRequestHandler logs every
        # request to stderr otherwise, which floods the parent process.
        def log_message(self, format: str, *args) -> None:  # noqa: A002, D401
            if debug:
                LOG.info("%s - - " + format, self.address_string(), *args)

        # ----- helpers --------------------------------------------------

        def _send_text(
            self,
            status: int,
            body: str,
            *,
            content_type: str = "text/plain; charset=utf-8",
        ) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Backlog-Phase", WEB_PHASE)
            self.end_headers()
            try:
                self.wfile.write(payload)
            except BrokenPipeError:
                pass

        def _send_json(self, status: int, obj: object) -> None:
            self._send_text(
                status,
                json.dumps(obj, ensure_ascii=False, sort_keys=False, default=str),
                content_type="application/json; charset=utf-8",
            )

        def _send_file(self, path: Path) -> None:
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                self._send_text(HTTPStatus.NOT_FOUND, "404 not found\n")
                return
            ctype, _ = mimetypes.guess_type(str(path))
            if ctype is None:
                ctype = "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Backlog-Phase", WEB_PHASE)
            self.end_headers()
            try:
                self.wfile.write(data)
            except BrokenPipeError:
                pass

        def _serve_index(self) -> None:
            self._send_file(root / "index.html")

        # ----- routing --------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
            path = self.path.split("?", 1)[0].rstrip("/") or "/"

            # Health probe — used by the launch CLI to confirm port is up.
            if path == "/healthz":
                self._send_text(HTTPStatus.OK, "ok\n")
                return

            # Version probe — used by the smoke test to verify the right
            # build is talking back. JSON keeps it cheap to extend.
            if path == "/api/version":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "name": "claude-backlog",
                        "version": WEB_VERSION,
                        "phase": WEB_PHASE,
                    },
                )
                return

            # Static asset — `/static/foo.css` → <root>/foo.css. Reject any
            # path-traversal attempt; this server is localhost-only but we
            # still treat the public surface as if it were exposed.
            if path.startswith("/static/"):
                rel = path[len("/static/") :]
                target = (root / rel).resolve()
                try:
                    target.relative_to(root)
                except ValueError:
                    self._send_text(HTTPStatus.FORBIDDEN, "403 forbidden\n")
                    return
                if not target.is_file():
                    self._send_text(HTTPStatus.NOT_FOUND, "404 not found\n")
                    return
                self._send_file(target)
                return

            # SPA route — hand off to index.html and let Alpine.js hydrate.
            if _is_spa_route(path):
                self._serve_index()
                return

            # Phase 5.2+ will register /api/tasks etc. here. For 5.1, any
            # unknown /api/ path returns a structured 501 so callers can
            # detect "not yet shipped" cleanly.
            if path.startswith("/api/"):
                self._send_json(
                    HTTPStatus.NOT_IMPLEMENTED,
                    {
                        "error": "endpoint_not_yet_shipped",
                        "phase": WEB_PHASE,
                        "path": path,
                        "next_phase": "5.2",
                    },
                )
                return

            self._send_text(HTTPStatus.NOT_FOUND, "404 not found\n")

        def do_POST(self) -> None:  # noqa: N802
            # Phase 5.4 unlocks writes. Until then, refuse politely.
            self._send_json(
                HTTPStatus.NOT_IMPLEMENTED,
                {
                    "error": "writes_not_yet_shipped",
                    "phase": WEB_PHASE,
                    "next_phase": "5.4",
                },
            )

        # PATCH / DELETE arrive via the default verb-name dispatcher in
        # BaseHTTPRequestHandler (looks for `do_PATCH` / `do_DELETE`). Add
        # them when 5.4 lands.

    return Handler


# --- Server bootstrap --------------------------------------------------------


class BacklogHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with a stable name + a `shutdown_event` flag.

    The subclass exists so tests can `isinstance`-check the server cleanly and
    so future sub-phases can attach SSE bookkeeping without touching call
    sites.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.shutdown_event = threading.Event()


def _port_is_free(host: str, port: int) -> bool:
    """Return True if (host, port) can be bound right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def serve(
    host: str = "127.0.0.1",
    port: int = 6420,
    *,
    static_root: Path | None = None,
    debug: bool = False,
) -> BacklogHTTPServer:
    """Start the server in a daemon thread. Returns the server instance.

    Caller is responsible for `.shutdown()` + `.server_close()`. The CLI
    (`__main__.py`) wires that into a SIGINT handler so Ctrl-C is clean.
    """
    handler_cls = make_handler(static_root=static_root, debug=debug)
    server = BacklogHTTPServer((host, port), handler_cls)
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"backlog-web-{port}",
        daemon=True,
    )
    thread.start()
    server._serve_thread = thread  # type: ignore[attr-defined]
    LOG.info("serving claude-backlog web UI on http://%s:%d/", host, port)
    return server


# --- CLI helpers (used by `python -m claude_backlog.web`) --------------------


def build_arg_parser() -> argparse.ArgumentParser:
    """Argparse for the CLI entry point. Pulled out so tests can introspect."""
    parser = argparse.ArgumentParser(
        prog="claude_backlog.web",
        description="Launch the claude-backlog web UI (Phase 5.1, task-442).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=6420, help="bind port (default 6420)")
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="do not auto-open the system browser",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable per-request access logging",
    )
    parser.add_argument(
        "--static-root",
        type=Path,
        default=None,
        help="override the bundled static directory (for development only)",
    )
    return parser


def _check_port(host: str, port: int) -> None:
    """Hard-fail with a helpful message if the port is occupied."""
    if _port_is_free(host, port):
        return
    print(
        f"port {host}:{port} is already in use — pick another with --port <N>",
        file=sys.stderr,
    )
    raise SystemExit(2)
