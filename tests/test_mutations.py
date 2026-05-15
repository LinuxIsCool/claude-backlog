"""Tests for claude_backlog.web.mutations — Pattern C write handlers (task-446 B3).

12 tests covering: handler registration, set_status (happy / invalid /
not-found / noop), set_priority (cycle / reject), set_tag (add / remove /
idempotent), MCP-tool parity invariant, end-to-end POST /api/mutate.
"""
from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import pytest

from claude_webui.dispatcher import MutationCatalog, MutationError

from claude_backlog.io import find_task, read_task, write_task
from claude_backlog.schema import Task
from claude_backlog.web.mutations import (
    CANONICAL_PRIORITIES,
    CANONICAL_STATUSES,
    register_handlers,
    set_priority,
    set_status,
    set_tag,
)


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture()
def populated_backlog(tmp_backlog: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seed three tasks at IDs 100, 200, 300 in distinct stages.

    The IO module reads BACKLOG_ROOT once at import; monkeypatch the
    module attribute so find_task / write_task / read_task all resolve
    against tmp_backlog for the test.
    """
    from claude_backlog import io as io_mod

    monkeypatch.setattr(io_mod, "BACKLOG_ROOT", tmp_backlog)

    seeded = [
        Task(id=100, title="kanban tester", status="To Do", priority="medium",
             created=date(2026, 5, 1), tags=["wip"]),
        Task(id=200, title="priority tester", status="In Progress",
             priority="medium", created=date(2026, 5, 1), tags=[]),
        Task(id=300, title="tag tester", status="Blocked", priority="low",
             created=date(2026, 5, 1), tags=["alpha", "beta"]),
    ]
    from claude_backlog.io import Stage
    for t in seeded:
        write_task(t, Stage.ACTIVE, tmp_backlog)
    return tmp_backlog


@pytest.fixture()
def catalog(tmp_path: Path) -> MutationCatalog:
    audit = tmp_path / "audit"
    audit.mkdir()
    cat = MutationCatalog(audit_dir=audit, timeout_s=3.0, paradigm="crud")
    register_handlers(cat)
    return cat


# ── 1. set_status ────────────────────────────────────────────────────────


def test_set_status_writes_file_and_returns_previous(populated_backlog: Path) -> None:
    result = set_status({"id": 100, "status": "In Progress"})
    assert result["id"] == 100
    assert result["status"] == "In Progress"
    assert result["previous_status"] == "To Do"
    assert result.get("noop") is not True
    # Verify the file actually changed on disk.
    path = find_task(100)
    assert path is not None
    assert read_task(path).status == "In Progress"


def test_set_status_rejects_non_canonical_status(populated_backlog: Path) -> None:
    with pytest.raises(MutationError) as exc_info:
        set_status({"id": 100, "status": "in-progress"})  # wrong casing
    assert exc_info.value.code == "INVALID_STATUS"
    assert "received" in exc_info.value.details
    # The file must NOT have been mutated.
    path = find_task(100)
    assert path is not None
    assert read_task(path).status == "To Do"


def test_set_status_unknown_id_raises_not_found(populated_backlog: Path) -> None:
    with pytest.raises(MutationError) as exc_info:
        set_status({"id": 99999, "status": "Done"})
    assert exc_info.value.code == MutationError.NOT_FOUND


def test_set_status_noop_when_current_matches_target(populated_backlog: Path) -> None:
    result = set_status({"id": 100, "status": "To Do"})
    assert result == {"id": 100, "status": "To Do", "noop": True}


# ── 2. set_priority ──────────────────────────────────────────────────────


def test_set_priority_cycles_through_canonical_values(populated_backlog: Path) -> None:
    """Verify each of the 4 canonical priorities round-trips. The browser
    cycles client-side; the handler just validates."""
    # Task-200 starts at medium.
    for target in ["critical", "high", "low", "medium"]:
        result = set_priority({"id": 200, "priority": target})
        assert result["priority"] == target


def test_set_priority_rejects_unknown(populated_backlog: Path) -> None:
    with pytest.raises(MutationError) as exc_info:
        set_priority({"id": 200, "priority": "urgent"})
    assert exc_info.value.code == "INVALID_PRIORITY"


# ── 3. set_tag ────────────────────────────────────────────────────────────


def test_set_tag_add_adds_tag(populated_backlog: Path) -> None:
    result = set_tag({"id": 300, "tag": "gamma", "op": "add"})
    assert result["tag"] == "gamma"
    assert result["op"] == "add"
    assert "gamma" in result["tags"]
    # File on disk reflects.
    path = find_task(300)
    assert path is not None
    assert "gamma" in read_task(path).tags


def test_set_tag_add_is_idempotent(populated_backlog: Path) -> None:
    result = set_tag({"id": 300, "tag": "alpha", "op": "add"})
    assert result.get("noop") is True


def test_set_tag_remove_removes_tag(populated_backlog: Path) -> None:
    result = set_tag({"id": 300, "tag": "alpha", "op": "remove"})
    assert "alpha" not in result["tags"]
    assert "beta" in result["tags"]


def test_set_tag_remove_idempotent_when_absent(populated_backlog: Path) -> None:
    result = set_tag({"id": 300, "tag": "nonexistent", "op": "remove"})
    assert result.get("noop") is True


# ── 4. catalog registration ─────────────────────────────────────────────


def test_register_handlers_registers_all_three(catalog: MutationCatalog) -> None:
    names = [t["name"] for t in catalog.list_tools()]
    assert set(names) == {"set_status", "set_priority", "set_tag"}


def test_register_handlers_args_schema_present(catalog: MutationCatalog) -> None:
    """Tier-C parity (§"Mutation-parity gate" #9): args_schema must match
    the MCP tool's input schema. This test pins the SHAPE so a careless
    edit can't silently relax validation."""
    by_name = {t["name"]: t for t in catalog.list_tools()}
    # set_status enumerates the canonical statuses + Draft
    status_enum = by_name["set_status"]["args_schema"]["status"]["enum"]
    assert set(status_enum) == CANONICAL_STATUSES
    # set_priority enumerates the canonical priorities (ordered list)
    pri_enum = by_name["set_priority"]["args_schema"]["priority"]["enum"]
    assert list(pri_enum) == list(CANONICAL_PRIORITIES)
    # set_tag accepts op = add | remove
    tag_op_enum = by_name["set_tag"]["args_schema"]["op"]["enum"]
    assert set(tag_op_enum) == {"add", "remove"}


# ── 5. end-to-end via POST /api/mutate ──────────────────────────────────


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def live_kernel(populated_backlog: Path) -> Iterator[str]:
    """Spin a BacklogKernel against the populated_backlog fixture.

    Yields `host:port`. monkeypatch ensures the kernel's IO routes
    against tmp_backlog (already patched by populated_backlog fixture).
    """
    from claude_backlog.web.server import build_kernel

    port = _free_port()
    kernel = build_kernel(port=port, root=populated_backlog)
    server = kernel.build_server()
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    for _ in range(20):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    yield f"127.0.0.1:{port}"
    kernel.stop()
    t.join(timeout=2)


def _post_mutate(
    host: str,
    body: dict[str, Any],
    *,
    persona: str | None = None,
) -> tuple[int, dict[str, Any] | None]:
    conn = http.client.HTTPConnection(host, timeout=5)
    raw = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Content-Length": str(len(raw))}
    if persona:
        headers["X-Persona-Slug"] = persona
    conn.request("POST", "/api/mutate", body=raw, headers=headers)
    r = conn.getresponse()
    body_bytes = r.read()
    parsed: dict[str, Any] | None = None
    if body_bytes:
        try:
            parsed = json.loads(body_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            parsed = None
    return r.status, parsed


def test_live_set_status_round_trip(live_kernel: str, populated_backlog: Path) -> None:
    """Browser-style: POST /api/mutate {set_status, id=100, status='Done'}.
    Expect 200, result, and the file mutated on disk."""
    status_code, body = _post_mutate(
        live_kernel,
        {"tool": "set_status", "args": {"id": 100, "status": "Done"}},
        persona="shawn",
    )
    assert status_code == 200
    assert body is not None
    assert body["tool"] == "set_status"
    assert body["result"]["status"] == "Done"
    # Verify the file.
    path = find_task(100)
    assert path is not None
    assert read_task(path).status == "Done"
    # Audit row exists at backlog_root/mutations/YYYY-MM-DD.ndjson.
    audit_dir = populated_backlog / "mutations"
    files = list(audit_dir.glob("*.ndjson"))
    assert files, "audit log must exist after a successful dispatch"
    rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    started = next(r for r in rows if r["status"] == "started")
    assert started["persona"] == "shawn"
    assert started["tool"] == "set_status"
