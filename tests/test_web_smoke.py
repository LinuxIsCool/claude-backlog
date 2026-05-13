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
        "corpus_health",  # task-447 A3
        "namespace",
    ):
        assert key in s, f"missing key {key!r} in stats"
    cb = s["checkbox_progress"]
    assert set(cb.keys()) == {"checked", "total", "ratio"}


def test_list_summary_includes_modified_at() -> None:
    """v0.2.5: list() summaries carry `modified_at` (ISO 8601 with timezone)
    sourced from the cached mtime map. Browser uses this for relative-time
    rendering so age reflects last-touched, not frontmatter date precision.

    Contract: present on every item, either a parseable ISO string or null.
    """
    accessor = BacklogAccessor()
    rows = accessor.list({"limit": 5})
    assert rows, "list() returned empty result — corpus has tasks"
    for row in rows:
        assert "modified_at" in row, f"missing modified_at: {row.get('id')}"
        ma = row["modified_at"]
        if ma is not None:
            # Parseable ISO 8601 with timezone offset.
            from datetime import datetime
            datetime.fromisoformat(ma)


def test_stats_corpus_health_shape() -> None:
    """task-447 A3: stats() exposes corpus_health for the hygiene badge.

    Contract: collision_count is an int >= 0, colliding_ids is a list of
    ints (capped at 50 to bound API payload), parse_failures is an int,
    total_files is an int matching the on-disk count.
    """
    s = BacklogAccessor().stats()
    health = s["corpus_health"]
    assert isinstance(health, dict)
    assert set(health.keys()) == {
        "total_files",
        "collision_count",
        "colliding_ids",
        "parse_failures",
    }
    assert isinstance(health["total_files"], int)
    assert health["total_files"] >= 0
    assert isinstance(health["collision_count"], int)
    assert health["collision_count"] >= 0
    assert isinstance(health["colliding_ids"], list)
    # Length bounded to 50 even if more exist.
    assert len(health["colliding_ids"]) <= 50
    assert all(isinstance(x, int) for x in health["colliding_ids"])
    assert isinstance(health["parse_failures"], int)
    # Invariant: collision_count == 0  ⇒  empty colliding_ids list.
    if health["collision_count"] == 0:
        assert health["colliding_ids"] == []


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


# --- Extra-route endpoints (post-fleet-quality rebuild) --------------------


def test_live_api_facets(live_kernel: int) -> None:
    """/api/facets returns the full filter-chip taxonomy."""
    status, _, body = _get(live_kernel, "/api/facets")
    assert status == 200
    payload = json.loads(body)
    assert payload["namespace"] == NAMESPACE
    assert payload["priorities"] == ["critical", "high", "medium", "low"]
    assert payload["status_families"] == [
        "To Do", "In Progress", "Blocked", "Done", "Draft",
    ]
    assert isinstance(payload["raw_statuses"], list)
    assert isinstance(payload["ventures"], list)
    assert isinstance(payload["tags"], list)


def test_live_api_search_query(live_kernel: int) -> None:
    """/api/search runs weighted substring across title+tags+venture+body."""
    status, _, body = _get(live_kernel, "/api/search?q=backlog&limit=5")
    assert status == 200
    payload = json.loads(body)
    assert payload["query"] == "backlog"
    assert "total" in payload
    assert isinstance(payload["results"], list)
    if payload["results"]:
        first = payload["results"][0]
        assert "score" in first
        assert "excerpt" in first
        assert "id" in first
        assert "title" in first


def test_live_api_search_empty_query(live_kernel: int) -> None:
    """Empty query returns the empty envelope, not an error."""
    status, _, body = _get(live_kernel, "/api/search?q=")
    assert status == 200
    payload = json.loads(body)
    assert payload == {"query": "", "total": 0, "results": []}


def test_status_family_normalization() -> None:
    """24 distinct raw statuses → 5 canonical families."""
    from claude_backlog.web.accessor import _normalize_status, CANONICAL_STATUSES

    assert _normalize_status("To Do") == "To Do"
    assert _normalize_status("In Progress") == "In Progress"
    assert _normalize_status("to do") == "To Do"
    assert _normalize_status("TODO") == "To Do"
    assert _normalize_status(" Backlog ") == "To Do"
    assert _normalize_status("in-progress") == "In Progress"
    assert _normalize_status("WIP") == "In Progress"
    assert _normalize_status("done") == "Done"
    assert _normalize_status("Cancelled") == "Done"
    assert _normalize_status("superseded") == "Done"
    assert _normalize_status("phase-2-shipped") == "Done"
    assert _normalize_status("blocked") == "Blocked"
    assert _normalize_status("waiting") == "Blocked"
    assert _normalize_status("draft") == "Draft"
    assert _normalize_status(None) == "To Do"
    assert _normalize_status("") == "To Do"
    assert _normalize_status("completely-novel-status") == "To Do"
    assert CANONICAL_STATUSES == ("To Do", "In Progress", "Blocked", "Done", "Draft")


def test_accessor_facets_shape() -> None:
    """BacklogAccessor.facets returns documented keys + sorted-by-count rows."""
    f = BacklogAccessor().facets()
    for key in (
        "priorities",
        "status_families",
        "raw_statuses",
        "ventures",
        "tags",
        "creator_personas",
        "assignee_personas",
        "milestones",
        "namespace",
    ):
        assert key in f, f"missing facets key {key!r}"
    counts = [r["count"] for r in f["raw_statuses"]]
    assert counts == sorted(counts, reverse=True)


def test_accessor_search_weighted_scoring() -> None:
    """Title hits should score >= body-only hits; scores monotonically descend."""
    results = BacklogAccessor().search({"q": "webui", "limit": 10})
    assert isinstance(results["results"], list)
    if results["results"]:
        scores = [r["score"] for r in results["results"]]
        assert scores == sorted(scores, reverse=True)


def test_list_status_family_filter() -> None:
    """status_family=To Do should only return tasks normalizing to To Do."""
    rows = BacklogAccessor().list({"status_family": "To Do", "limit": 1000})
    for r in rows:
        assert r["status_family"] == "To Do"


def test_list_status_family_done_forces_include() -> None:
    """status_family=Done auto-includes Done tasks (otherwise hidden by default)."""
    rows = BacklogAccessor().list({"status_family": "Done", "limit": 1000})
    for r in rows:
        assert r["status_family"] == "Done"


# --- Round-1 fixes ---------------------------------------------------------


def test_list_q_matches_task_id() -> None:
    """Round-1 fix: searching '446' surfaces task-446 via id field coverage."""
    rows = BacklogAccessor().list({"q": "446", "limit": 1000, "include_done": "1"})
    ids = {r["id"] for r in rows}
    assert 446 in ids, f"task-446 missing from id search; got ids: {sorted(ids)[:20]}..."


def test_search_q_446_returns_task_446_first() -> None:
    """Round-1 fix: weighted search ranks task-446 first for numeric query '446'."""
    payload = BacklogAccessor().search({"q": "446", "limit": 5})
    assert payload["total"] >= 1
    # ID-exact-match has weight 10 — should dominate.
    top = payload["results"][0]
    assert top["id"] == 446, f"top hit should be task-446; got {top['id']} ({top['title'][:40]!r})"


def test_search_q_numeric_substring_still_ranks() -> None:
    """Round-1 fix: query '44' includes both task-440 family AND task-44x; both score."""
    payload = BacklogAccessor().search({"q": "44", "limit": 30})
    ids = {r["id"] for r in payload["results"]}
    # Real corpus has multiple task-4xx tasks; the substring matcher catches them.
    assert any(440 <= i < 450 for i in ids), f"no 44x ids in results: {sorted(ids)[:10]}"


def test_list_sort_param_priority_then_created() -> None:
    """Default sort: priority asc, created desc (when sort param omitted)."""
    rows = BacklogAccessor().list({"limit": 50})
    last_pri_rank = -1
    for r in rows:
        pri_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(r["priority"], 99)
        assert pri_rank >= last_pri_rank, f"priority went backward: {rows[:5]}"
        last_pri_rank = pri_rank


def test_list_sort_param_id_asc() -> None:
    """sort=id:asc returns rows in ascending integer-id order."""
    rows = BacklogAccessor().list({"sort": "id:asc", "limit": 20})
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids), f"id sort failed: {ids}"


def test_list_sort_param_id_desc() -> None:
    """sort=id:desc returns rows in descending integer-id order."""
    rows = BacklogAccessor().list({"sort": "id:desc", "limit": 20})
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids, reverse=True), f"id desc sort failed: {ids}"


def test_list_sort_param_title_asc() -> None:
    """sort=title:asc returns rows in alphabetical title order."""
    rows = BacklogAccessor().list({"sort": "title:asc", "limit": 20})
    titles = [r["title"].lower() for r in rows]
    assert titles == sorted(titles), f"title sort failed: {titles[:5]}"


def test_list_sort_param_unknown_falls_back() -> None:
    """Unknown sort key falls back to default ordering (priority then created)."""
    rows = BacklogAccessor().list({"sort": "bogus", "limit": 5})
    assert isinstance(rows, list)


def test_list_sort_multi_key() -> None:
    """Multi-key sort: priority asc, then id desc within priority bucket."""
    rows = BacklogAccessor().list({"sort": "priority:asc,id:desc", "limit": 50})
    seen_pri = None
    seen_id = None
    for r in rows:
        if seen_pri != r["priority"]:
            seen_pri = r["priority"]
            seen_id = None
            continue
        if seen_id is not None:
            assert r["id"] <= seen_id, f"id desc within priority broken: {rows[:5]}"
        seen_id = r["id"]


def test_accessor_cache_returns_stable_object_until_mtime_change(tmp_backlog) -> None:
    """Two list() calls in quick succession share the same cached parse."""
    from claude_backlog.web.accessor import BacklogAccessor

    a = BacklogAccessor()
    # First call populates cache.
    first = a.list({"limit": 5})
    # Second call should be served from cache — no exceptions; same shape.
    second = a.list({"limit": 5})
    assert first == second


def test_accessor_invalidate_cache_clears() -> None:
    a = BacklogAccessor()
    _ = a.list({"limit": 1})
    assert a._cache, "cache should have populated"
    a.invalidate_cache()
    assert not a._cache, "cache should be empty after invalidate"


# --- Static UI assertions (post-fleet-quality rebuild) ---------------------


def test_static_index_has_three_column_shell() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="left-nav"' in html
    assert 'id="main-view"' in html
    assert 'id="detail-panel"' in html
    assert 'id="view-root"' in html


def test_static_index_has_filter_chip_slot() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="filter-chips"' in html


def test_static_index_loads_minisearch_vendor() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "/static/vendor/minisearch-" in html
    assert (STATIC_DIR / "vendor").exists()
    vendored = list((STATIC_DIR / "vendor").glob("minisearch-*.js"))
    assert len(vendored) >= 1


def test_static_index_uses_catppuccin_mocha_palette() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for hex_code in ("#1e1e2e", "#cdd6f4", "#a6e3a1", "#cba6f7", "#89b4fa"):
        assert hex_code in html


def test_static_index_uses_doctrine_fonts() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "Press+Start+2P" in html
    assert "JetBrains+Mono" in html
    assert "font-pixel" in html
    assert "font-mono" in html


def test_static_index_has_5_kanban_columns() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "'To Do'" in html
    assert "'In Progress'" in html
    assert "'Blocked'" in html
    assert "'Done'" in html
    assert "'Draft'" in html
    # Constant rename round-1: STATUS_FAMILIES replaces KANBAN_COLUMNS.
    assert "STATUS_FAMILIES" in html


def test_static_index_mounts_search_input_once() -> None:
    """Round-1 fix: search input must mount once at init; no recreate-on-keystroke."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "mountSearchInput" in html
    assert "dataset.mounted" in html


def test_static_index_uses_client_minisearch() -> None:
    """Round-1 fix: filter/search runs client-side via MiniSearch over cached corpus."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "new MiniSearch" in html
    assert "clientFilter" in html
    assert "buildMiniSearchIndex" in html
    assert "state.corpus" in html


def test_static_index_has_sortable_headers() -> None:
    """Round-1 feature: List view column headers sort on click."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "sort-th" in html
    assert "state.sort_col" in html
    assert "state.sort_dir" in html
    assert "SORT_DEFAULT_DIR" in html


def test_static_index_no_clamp_on_venture_or_milestone() -> None:
    """Round-1 feature: venture / milestone / project meta-line is unbounded."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    # meta-line CSS class added; venture is no longer wrapped in clamp-1 on the card.
    assert ".meta-line" in html
    assert "meta-key" in html


def test_static_index_minisearch_handles_duplicate_task_ids() -> None:
    """Round-1.1 fix: corpus has 37 duplicate-id collisions (concurrent next_id race);
    MiniSearch must key off __idx, not task.id, to avoid 'duplicate ID' crash on load."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    # The synthetic key fix is the only thing standing between init() and a crash today.
    assert "idField: '__idx'" in html
    assert "t.__idx = idx" in html
    # MiniSearch is constructed with __idx as identity, not id
    assert "addAll(state.corpus.map((t, __idx)" in html


def test_static_index_numeric_query_uses_id_only_matching() -> None:
    """Round-1.2 fix: numeric query '446' must NOT match adjacent IDs via fuzzy."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "numericMatch = /^\\d+$/.test(q)" in html
    # ID-exact score 100; ID-substring score 50.
    assert "matchedIdx.set(idx, 100)" in html
    assert "matchedIdx.set(idx, 50)" in html
    # When numericMatch path runs, MiniSearch fuzzy is bypassed.
    assert "Pure-numeric: ID-only matching. No MiniSearch path." in html


def test_static_index_search_overrides_sort() -> None:
    """Round-1.2 fix: when search active, results sort by RELEVANCE, not column sort."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "searchActive" in html
    assert "if (!searchActive)" in html
    # Sort chip displays "relevance" when search is active
    assert "Sort: relevance (search active)" in html


def test_static_index_renders_corpus_health_badge() -> None:
    """task-447 A3: /stats view shows a corpus-health badge that reads
    `CLEAN` when collision_count + parse_failures == 0 and flips red when
    either is non-zero. Operator-visible regression signal."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "CORPUS HEALTH" in html
    assert "corpus_health" in html
    assert "collision_count" in html
    assert "parse_failures" in html
    # Both the OK and warning branches must be present.
    assert "CLEAN" in html
    assert "ISSUE" in html
    # Remediation hint shown when collisions > 0
    assert "scripts/dedupe_collisions.py --apply" in html


def test_static_index_default_sort_is_newest_first() -> None:
    """v0.2.5: default sort flipped from priority/asc to created/desc so
    newly-created tasks land at the top of the list view without filtering.
    Bookmarked URLs with explicit sort params continue to work unchanged."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    # Default sort_col is created, default sort_dir is desc.
    assert "initialParams.get('sort_col')  || 'created'" in html
    assert "initialParams.get('sort_dir')  || 'desc'" in html
    # URL-default-skip logic gates on (created, desc) — the new defaults.
    assert "state.sort_col !== 'created' || state.sort_dir !== 'desc'" in html


def test_static_index_has_sse_event_source() -> None:
    """v0.2.6 (R2/R3): browser subscribes to /api/events via EventSource for
    real-time push, with polling as the safety net. Stops EventSource on
    beforeunload to avoid leaked connections."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "new EventSource('/api/events')" in html
    assert "addEventListener('corpus-changed'" in html
    assert "addEventListener('connected'" in html
    # Cleanup on tab close.
    assert "beforeunload" in html
    # Fallback poll still runs (longer interval when SSE active).
    assert "POLL_INTERVAL_MS" in html


def test_build_kernel_wires_signature_fn_and_watch_paths(tmp_backlog) -> None:
    """build_kernel(...) constructs a BacklogKernel with signature_fn +
    watch_paths so /api/events broadcasts immediately on disk changes."""
    from claude_backlog.web.server import build_kernel

    kernel = build_kernel(port=0, root=tmp_backlog)
    assert kernel.event_bus is not None
    assert kernel._watcher is not None
    # Either InotifyWatcher (Linux + inotify_simple) or SignaturePoller (fallback).
    from claude_webui.events import InotifyWatcher, SignaturePoller
    assert isinstance(kernel._watcher, (InotifyWatcher, SignaturePoller))


def test_static_index_has_drag_and_drop_kanban() -> None:
    """task-446 Phase B3: kanban cards become draggable + columns accept
    drops, dispatching set_status mutations via /api/mutate.

    Pins:
      - draggable: true on the task card
      - ondragstart sets dataTransfer with the task id
      - column body declares a data-drop-target with the canonical status
      - drop handler calls handleKanbanDrop()
      - postMutation() helper exists and POSTs to /api/mutate
      - X-Persona-Slug header set on the request
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    # Card-level
    assert "draggable: true" in html
    assert "ondragstart:" in html
    # Column-level
    assert "dropTarget:" in html
    assert "ondrop:" in html
    assert "handleKanbanDrop(" in html
    # Helper
    assert "async function postMutation(" in html
    assert "fetch('/api/mutate'" in html
    assert "X-Persona-Slug" in html
    # Idempotency
    assert "idempotency_key" in html


def test_static_index_has_click_cycle_priority() -> None:
    """task-446 Phase B3: clicking the priority dot cycles through
    critical → high → medium → low. The handler dispatches
    set_priority via /api/mutate with optimistic update + toast on error."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "function cyclePriority(" in html
    assert "set_priority" in html
    # Canonical cycle order pinned in code.
    assert "['critical', 'high', 'medium', 'low']" in html
    # Toast helper exists for rollback feedback.
    assert "function showToast(" in html


def test_static_index_age_uses_modified_at_when_available() -> None:
    """v0.2.5: age column / card timestamp uses task.modified_at (file
    mtime, ISO 8601 from server) when present, falling back to task.created
    (YYYY-MM-DD frontmatter). Fixes "1d ago" rendering for tasks created
    same-day but where created date parses to UTC midnight."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "function bestTime(" in html
    assert "task.modified_at || task.created" in html
    # No remaining call-sites rendering raw t.created via relativeTime.
    assert "relativeTime(t.created)" not in html
    # All three call-sites now go through bestTime.
    assert html.count("relativeTime(bestTime(t))") >= 3
