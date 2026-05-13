"""Phase 5.1 web-server smoke (task-442).

Verifies the routing contract documented in `web/server.py`:
  • /healthz returns 200 "ok\\n"
  • /api/version returns the right JSON shape
  • /static/style.css and /static/app.js are served
  • SPA routes (/, /list, /task/42, /stats, …) all serve index.html
  • /api/<unknown> returns the structured 501 placeholder
  • POST anything returns the structured 501 placeholder
  • CLI argparse accepts --port / --no-open / --debug / --static-root

This test does NOT bind a real socket — it instantiates the handler class
directly via Python's `http.server.BaseHTTPRequestHandler` test idiom by
driving it through `serve()` on an ephemeral port. That keeps the smoke fast
(<1s) without monkey-patching socket internals.
"""

from __future__ import annotations

import json
import socket
import time
from http.client import HTTPConnection
from pathlib import Path

import pytest

from claude_backlog.web.server import (
    WEB_PHASE,
    WEB_VERSION,
    _is_spa_route,
    build_arg_parser,
    serve,
)


# --- ephemeral-port helper --------------------------------------------------


def _pick_port() -> int:
    """Ask the OS for an unused localhost port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def live_server():
    """Start a real server on a random localhost port; teardown on exit."""
    port = _pick_port()
    server = serve(host="127.0.0.1", port=port)
    # tiny wait for the daemon thread to enter serve_forever
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.02)
    yield port
    server.shutdown()
    server.server_close()


def _get(port: int, path: str) -> tuple[int, dict, bytes]:
    conn = HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    headers = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, headers, body


def _post(port: int, path: str, body: bytes = b"") -> tuple[int, bytes]:
    conn = HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request("POST", path, body=body)
    resp = conn.getresponse()
    out = resp.read()
    conn.close()
    return resp.status, out


# --- SPA route table --------------------------------------------------------


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/", True),
        ("/list", True),
        ("/stats", True),
        ("/graph", True),
        ("/embed", True),
        ("/heatmap", True),
        ("/fdg", True),
        ("/fdg-hm", True),
        ("/compass", True),
        ("/task/123", True),
        ("/task/abc-zzz", True),
        ("/static/style.css", False),
        ("/api/tasks", False),
        ("/api/version", False),
        ("/healthz", False),
        ("/bogus", False),
    ],
)
def test_spa_route_classifier(path: str, expected: bool) -> None:
    assert _is_spa_route(path) is expected


# --- live server probes -----------------------------------------------------


def test_healthz_returns_200(live_server: int) -> None:
    status, _, body = _get(live_server, "/healthz")
    assert status == 200
    assert body == b"ok\n"


def test_version_endpoint(live_server: int) -> None:
    status, headers, body = _get(live_server, "/api/version")
    assert status == 200
    assert headers["content-type"].startswith("application/json")
    payload = json.loads(body)
    assert payload["name"] == "claude-backlog"
    assert payload["version"] == WEB_VERSION
    assert payload["phase"] == WEB_PHASE


def test_root_serves_index(live_server: int) -> None:
    status, headers, body = _get(live_server, "/")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert b"claude-backlog" in body
    assert b'x-data="backlogApp()"' in body


def test_spa_routes_all_serve_index(live_server: int) -> None:
    for path in (
        "/list",
        "/stats",
        "/graph",
        "/embed",
        "/heatmap",
        "/fdg",
        "/fdg-hm",
        "/compass",
        "/task/42",
    ):
        status, _, body = _get(live_server, path)
        assert status == 200, f"{path} returned {status}"
        # Same HTML body as `/`
        assert b'x-data="backlogApp()"' in body


def test_static_assets_served(live_server: int) -> None:
    for path in ("/static/style.css", "/static/app.js"):
        status, headers, body = _get(live_server, path)
        assert status == 200, f"{path} returned {status}"
        assert len(body) > 0
        # rough MIME sanity
        if path.endswith(".css"):
            assert "css" in headers["content-type"]
        if path.endswith(".js"):
            assert "javascript" in headers["content-type"] or "ecmascript" in headers["content-type"]


def test_static_path_traversal_blocked(live_server: int) -> None:
    status, _, _ = _get(live_server, "/static/../server.py")
    assert status in (403, 404)


def test_unknown_api_returns_structured_501(live_server: int) -> None:
    status, headers, body = _get(live_server, "/api/does-not-exist")
    assert status == 501
    assert headers["content-type"].startswith("application/json")
    payload = json.loads(body)
    assert payload["error"] == "endpoint_not_yet_shipped"
    assert payload["phase"] == WEB_PHASE


def test_post_returns_structured_501(live_server: int) -> None:
    status, body = _post(live_server, "/api/tasks", b"{}")
    assert status == 501
    payload = json.loads(body)
    assert payload["error"] == "writes_not_yet_shipped"


def test_unknown_path_returns_404(live_server: int) -> None:
    status, _, _ = _get(live_server, "/no-such-route")
    assert status == 404


# --- CLI argparse contract --------------------------------------------------


def test_argparser_defaults() -> None:
    args = build_arg_parser().parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 6420
    assert args.no_open is False
    assert args.debug is False
    assert args.static_root is None


def test_argparser_accepts_overrides(tmp_path: Path) -> None:
    args = build_arg_parser().parse_args(
        [
            "--host",
            "0.0.0.0",
            "--port",
            "9999",
            "--no-open",
            "--debug",
            "--static-root",
            str(tmp_path),
        ]
    )
    assert args.host == "0.0.0.0"
    assert args.port == 9999
    assert args.no_open is True
    assert args.debug is True
    assert args.static_root == tmp_path
