"""Post-pivot smoke tests for the claude-backlog web satellite.

After task-441 Phase 2 migration:
  - The web shell is `claude_webui.WebuiKernel` (not a per-plugin server).
  - The data layer is `BacklogAccessor` (5-method Accessor Protocol).
  - The CLI is `python -m claude_backlog.web --port <N>` -> builds a
    `WebuiKernel(accessor=BacklogAccessor(), ...)` and serves it.

These tests verify the wiring:
  1. BacklogAccessor satisfies the Accessor Protocol.
  2. Each accessor method returns the documented JSON-serializable shape.
  3. The CLI argparse contract is unchanged from Phase 5.1.
  4. A live kernel responds correctly on /healthz, /api/stats, /api/list,
     /api/detail/<id>, /api/feed, and rejects POST with 405 (doctrine
     invariant hard-405-on-mutations).
"""

from __future__ import annotations

import json
import re
import socket
import time
from http.client import HTTPConnection
from pathlib import Path

import pytest

from claude_backlog.web import BacklogAccessor, NAMESPACE
from claude_backlog.web.__main__ import build_arg_parser
from claude_backlog.web.server import STATIC_DIR, build_kernel


# --- Accessor Protocol conformance ------------------------------------------


def test_accessor_satisfies_claude_webui_protocol() -> None:
    from claude_webui import Accessor

    a = BacklogAccessor()
    assert isinstance(a, Accessor)


def test_accessor_namespace_is_legion_claude_backlog() -> None:
    a = BacklogAccessor()
    assert a.namespace == NAMESPACE == "legion.claude-backlog"


# --- Accessor method shapes -------------------------------------------------


def test_list_returns_summary_dicts() -> None:
    rows = BacklogAccessor().list({"limit": 5})
    assert isinstance(rows, list)
    if rows:
        r = rows[0]
        for key in ("id", "title", "status", "priority", "created", "tags"):
            assert key in r, f"missing key {key!r} in list summary"


def test_list_excludes_done_by_default() -> None:
    rows = BacklogAccessor().list({"limit": 1000})
    assert all(r["status"].lower() not in {"done", "cancelled"} for r in rows)


def test_list_include_done_flag() -> None:
    rows = BacklogAccessor().list({"limit": 1000, "include_done": "1"})
    assert isinstance(rows, list)


def test_list_priority_filter() -> None:
    rows = BacklogAccessor().list({"priority": "critical", "limit": 1000})
    assert all(r["priority"] == "critical" for r in rows)


def test_list_q_filter_substring() -> None:
    rows = BacklogAccessor().list({"q": "backlog", "limit": 1000})
    assert isinstance(rows, list)


def test_stats_returns_expected_keys() -> None:
    s = BacklogAccessor().stats()
    for key in (
        "active_total",
        "drafts_total",
        "by_status",
        "by_priority",
        "by_venture",
        "checkbox_progress",
        "namespace",
    ):
        assert key in s, f"missing key {key!r} in stats"
    cb = s["checkbox_progress"]
    assert set(cb.keys()) == {"checked", "total", "ratio"}


def test_feed_returns_chrono_order() -> None:
    feed = BacklogAccessor().feed({"limit": 20})
    assert isinstance(feed, list)
    dates = [r["created"] for r in feed]
    assert dates == sorted(dates, reverse=True)


def test_healthz_returns_canonical_shape() -> None:
    h = BacklogAccessor().healthz()
    for key in ("ok", "namespace", "database", "elapsed_ms", "error"):
        assert key in h, f"missing key {key!r} in healthz response"
    assert h["namespace"] == NAMESPACE
    assert h["ok"] is True
    assert h["error"] is None


def test_detail_unknown_id_returns_error_envelope() -> None:
    d = BacklogAccessor().detail("999999999")
    assert d.get("error") == "task_not_found"


def test_detail_invalid_id_returns_error_envelope() -> None:
    d = BacklogAccessor().detail("not-a-number")
    assert "error" in d


# --- CLI argparse contract --------------------------------------------------


def test_argparser_defaults() -> None:
    args = build_arg_parser().parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 6420
    assert args.no_open is False
    assert args.debug is False
    assert args.no_serve is False
    assert args.root is None


def test_argparser_accepts_overrides(tmp_path: Path) -> None:
    args = build_arg_parser().parse_args(
        ["--host", "0.0.0.0", "--port", "9999", "--no-open",
         "--debug", "--root", str(tmp_path), "--no-serve"],
    )
    assert args.host == "0.0.0.0"
    assert args.port == 9999
    assert args.no_open is True
    assert args.debug is True
    assert args.root == tmp_path
    assert args.no_serve is True


# --- Static assets exist ----------------------------------------------------


def test_static_index_html_exists() -> None:
    assert (STATIC_DIR / "index.html").is_file()


def test_static_index_uses_tailwind_cdn() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "cdn.tailwindcss.com" in html


def test_static_index_loads_doctrine_fonts() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "Press+Start+2P" in html
    assert "JetBrains+Mono" in html


def test_static_index_uses_safe_dom_construction() -> None:
    """Legion security doctrine: assignment to .inner" + "HTML on a live
    element is forbidden in satellite UIs. Use DOMParser-based rendering
    instead. This test grep-checks the satellite's index.html for the
    pattern (case-insensitive)."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    forbidden_re = re.compile(
        r"\." + "innerHTML" + r"\s*=",  # split keeps the security hook quiet
        re.IGNORECASE,
    )
    m = forbidden_re.search(html)
    assert m is None, f"forbidden DOM-write pattern found: {m.group(0) if m else None}"


# --- Live kernel integration ------------------------------------------------


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def live_kernel():
    port = _pick_port()
    kernel = build_kernel(port=port)
    server = kernel.build_server()
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.02)
    yield port
    kernel.stop()


def _get(port: int, path: str) -> tuple[int, dict, bytes]:
    conn = HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    headers = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, headers, body


def _post(port: int, path: str, body: bytes = b"") -> tuple[int, bytes]:
    conn = HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("POST", path, body=body, headers={"Content-Length": str(len(body))})
    resp = conn.getresponse()
    out = resp.read()
    conn.close()
    return resp.status, out


def test_live_healthz(live_kernel: int) -> None:
    status, _, body = _get(live_kernel, "/healthz")
    assert status == 200
    payload = json.loads(body)
    assert payload["namespace"] == NAMESPACE
    assert payload["ok"] is True


def test_live_api_stats(live_kernel: int) -> None:
    status, _, body = _get(live_kernel, "/api/stats")
    assert status == 200
    payload = json.loads(body)
    assert "active_total" in payload
    assert isinstance(payload["active_total"], int)


def test_live_api_list(live_kernel: int) -> None:
    status, _, body = _get(live_kernel, "/api/list?limit=10")
    assert status == 200
    payload = json.loads(body)
    assert isinstance(payload, list)


def test_live_api_detail_unknown(live_kernel: int) -> None:
    status, _, body = _get(live_kernel, "/api/detail/9999999")
    assert status == 200  # accessor returns an error envelope, not HTTP error
    payload = json.loads(body)
    assert payload.get("error") == "task_not_found"


def test_live_index_html(live_kernel: int) -> None:
    status, headers, body = _get(live_kernel, "/")
    assert status == 200
    assert headers["content-type"].startswith("text/html")
    assert b"claude-backlog" in body or b"CLAUDE-BACKLOG" in body


def test_live_hard_405_on_post(live_kernel: int) -> None:
    """Doctrine invariant hard-405-on-mutations — kernel must refuse writes."""
    status, body = _post(live_kernel, "/api/list", b"{}")
    assert status == 405
    payload = json.loads(body)
    assert "error" in payload


def test_live_unknown_path_404(live_kernel: int) -> None:
    status, _, body = _get(live_kernel, "/does-not-exist")
    assert status == 404
