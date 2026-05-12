"""Phase 4.5 smoke test — spawn the MCP server as a subprocess,
exchange JSON-RPC over stdio, and round-trip all 11 MVP tools + the
workflow resource against an isolated BACKLOG_ROOT.

If this test passes, Phase 4 acceptance criterion 5 is green:
    "Smoke test (round-trip create → list → view → edit DoD → archive) passes."
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SERVER_SCRIPT = PLUGIN_ROOT / "scripts" / "mcp_server.py"


def _seed_config(root: Path) -> None:
    """Write a minimal config.yml so the server has a real project DoD."""
    (root / "config.yml").write_text(
        "statuses: [To Do, In Progress, Blocked, Done]\n"
        "priorities: [low, medium, high, critical]\n"
        "definition_of_done:\n"
        "  - Acceptance criteria met\n"
        "  - Tests written or updated\n"
        "auto_inherit_dod: true\n"
    )
    (root / "drafts").mkdir(exist_ok=True)
    (root / "archive").mkdir(exist_ok=True)


def _rpc(messages: list[dict], backlog_root: Path) -> list[dict]:
    """Send a batch of JSON-RPC messages, return parsed responses.

    Uses Popen so we can write all messages and then close stdin
    explicitly — subprocess.run with `input=` races with the server's
    stdio reader on Python 3.13 and drops trailing requests.
    """
    env = os.environ.copy()
    env["BACKLOG_ROOT"] = str(backlog_root)

    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "--directory",
            str(PLUGIN_ROOT),
            str(SERVER_SCRIPT),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    assert proc.stdin is not None
    # FastMCP's stdio loop drops trailing requests if stdin closes mid-process.
    # Send messages with a small inter-message gap and a drain delay before
    # closing stdin — this is a workaround for an upstream race in the
    # mcp Python SDK 1.27.1 stdio handler.
    for m in messages:
        proc.stdin.write(json.dumps(m) + "\n")
        proc.stdin.flush()
        time.sleep(0.05)
    time.sleep(0.5)
    proc.stdin.close()

    try:
        stdout, _stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _stderr = proc.communicate()
        raise

    responses: list[dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            responses.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return responses


def _result_of(responses: list[dict], req_id: int) -> dict:
    for r in responses:
        if r.get("id") == req_id:
            return r["result"]
    raise AssertionError(f"No response for id={req_id}; got: {responses}")


def _tool_call(tool: str, args: dict, req_id: int) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }


def _tool_text(result: dict) -> str:
    """Extract the text payload from a tools/call result."""
    return result["content"][0]["text"]


# --- main smoke test --------------------------------------------------------


def test_full_roundtrip(tmp_path: Path) -> None:
    _seed_config(tmp_path)

    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "0.1"},
        },
    }
    initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}

    # Step 1: initialize + list tools + list resources
    resp1 = _rpc(
        [
            init,
            initialized,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "resources/read",
                "params": {"uri": "claude-backlog://workflow/overview"},
            },
        ],
        tmp_path,
    )

    init_result = _result_of(resp1, 1)
    assert init_result["serverInfo"]["name"] == "claude-backlog"

    tools_result = _result_of(resp1, 2)
    tool_names = {t["name"] for t in tools_result["tools"]}
    expected = {
        "get_backlog_instructions",
        "task_list",
        "task_view",
        "task_search",
        "task_create",
        "task_edit",
        "task_archive",
        "draft_list",
        "draft_promote",
        "definition_of_done_defaults_get",
        "definition_of_done_defaults_upsert",
    }
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"

    resources_result = _result_of(resp1, 3)
    resource_uris = {r["uri"] for r in resources_result["resources"]}
    assert "claude-backlog://workflow/overview" in resource_uris

    workflow_content = _result_of(resp1, 4)["contents"][0]["text"]
    assert "claude-backlog — Agent Workflow Overview" in workflow_content
    assert len(workflow_content) > 5000  # non-trivial doc

    # Step 2: get_backlog_instructions (resource fallback path)
    resp2 = _rpc(
        [
            init,
            initialized,
            _tool_call("get_backlog_instructions", {}, 10),
        ],
        tmp_path,
    )
    text = _tool_text(_result_of(resp2, 10))
    assert "Agent Workflow Overview" in text

    # Step 3: task_create
    resp3 = _rpc(
        [
            init,
            initialized,
            _tool_call(
                "task_create",
                {
                    "title": "Smoke test task",
                    "priority": "high",
                    "tags": ["smoke", "phase-4-5"],
                    "acceptance_criteria": [
                        "First criterion",
                        "Second criterion",
                    ],
                },
                20,
            ),
        ],
        tmp_path,
    )
    create_text = _tool_text(_result_of(resp3, 20))
    create_payload = json.loads(create_text)
    assert create_payload["ok"] is True
    task_id = create_payload["task_id"]
    assert isinstance(task_id, int)
    assert create_payload["title"] == "Smoke test task"
    assert create_payload["priority"] == "high"
    assert create_payload["dod_inherited"] == 2  # from seeded config

    # Step 4: task_list (smoke task should appear)
    resp4 = _rpc(
        [
            init,
            initialized,
            _tool_call("task_list", {"priority": "high"}, 30),
        ],
        tmp_path,
    )
    list_text = _tool_text(_result_of(resp4, 30))
    assert f"#{task_id}" in list_text
    assert "Smoke test task" in list_text

    # Step 5: task_view
    resp5 = _rpc(
        [
            init,
            initialized,
            _tool_call("task_view", {"task_id": task_id}, 40),
        ],
        tmp_path,
    )
    view_text = _tool_text(_result_of(resp5, 40))
    assert f"Task {task_id}: Smoke test task" in view_text
    assert "## Acceptance Criteria" in view_text
    assert "First criterion" in view_text
    assert "## Definition of Done" in view_text

    # Step 6: task_edit — check DoD index 1
    resp6 = _rpc(
        [
            init,
            initialized,
            _tool_call(
                "task_edit",
                {"task_id": task_id, "check_dod": [1]},
                50,
            ),
        ],
        tmp_path,
    )
    edit_payload = json.loads(_tool_text(_result_of(resp6, 50)))
    assert edit_payload["ok"] is True

    # Verify file content reflects the change
    task_files = list(tmp_path.glob(f"task-{task_id} - *.md"))
    assert len(task_files) == 1
    content = task_files[0].read_text()
    # The first DoD item should now be [x]
    dod_idx = content.index("## Definition of Done")
    dod_section = content[dod_idx:]
    assert "- [x] Acceptance criteria met" in dod_section

    # Step 7: definition_of_done_defaults_get
    resp7 = _rpc(
        [
            init,
            initialized,
            _tool_call("definition_of_done_defaults_get", {}, 60),
        ],
        tmp_path,
    )
    dod_payload = json.loads(_tool_text(_result_of(resp7, 60)))
    assert dod_payload["auto_inherit_dod"] is True
    assert dod_payload["definition_of_done"] == [
        "Acceptance criteria met",
        "Tests written or updated",
    ]

    # Step 8: task_archive
    resp8 = _rpc(
        [
            init,
            initialized,
            _tool_call("task_archive", {"task_id": task_id}, 70),
        ],
        tmp_path,
    )
    archive_payload = json.loads(_tool_text(_result_of(resp8, 70)))
    assert archive_payload["ok"] is True
    assert "archive" in archive_payload["path"]
    assert not list(tmp_path.glob(f"task-{task_id} - *.md"))  # moved out of active
    assert list((tmp_path / "archive").glob(f"task-{task_id} - *.md"))  # in archive

    # Step 9: task_archive idempotency — second call returns already_archived
    resp9 = _rpc(
        [
            init,
            initialized,
            _tool_call("task_archive", {"task_id": task_id}, 80),
        ],
        tmp_path,
    )
    idemp_payload = json.loads(_tool_text(_result_of(resp9, 80)))
    assert idemp_payload["ok"] is True
    assert idemp_payload.get("already_archived") is True


def test_error_path_task_not_found(tmp_path: Path) -> None:
    """task_view on a non-existent ID returns a typed error payload."""
    _seed_config(tmp_path)

    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "0.1"},
        },
    }
    initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}

    resp = _rpc(
        [
            init,
            initialized,
            _tool_call("task_view", {"task_id": 99999}, 100),
        ],
        tmp_path,
    )
    text = _tool_text(_result_of(resp, 100))
    payload = json.loads(text)
    assert "error" in payload
    assert payload["error"]["code"] == "TASK_NOT_FOUND"


def test_task_edit_renames_file_on_title_change(tmp_path: Path) -> None:
    """task_edit re-slugifies the filename when title changes."""
    _seed_config(tmp_path)

    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "0.1"},
        },
    }
    initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}

    # Create then rename via edit
    resp = _rpc(
        [
            init,
            initialized,
            _tool_call(
                "task_create",
                {"title": "Original title", "priority": "low"},
                10,
            ),
        ],
        tmp_path,
    )
    create_payload = json.loads(_tool_text(_result_of(resp, 10)))
    task_id = create_payload["task_id"]

    # Verify initial slug
    assert list(tmp_path.glob(f"task-{task_id} - original-title.md"))

    # Edit title
    resp2 = _rpc(
        [
            init,
            initialized,
            _tool_call(
                "task_edit",
                {"task_id": task_id, "title": "Renamed and improved"},
                20,
            ),
        ],
        tmp_path,
    )
    edit_payload = json.loads(_tool_text(_result_of(resp2, 20)))
    assert edit_payload["ok"] is True

    # Old filename gone, new filename present
    assert not list(tmp_path.glob(f"task-{task_id} - original-title.md"))
    assert list(tmp_path.glob(f"task-{task_id} - renamed-and-improved.md"))


def test_dod_defaults_upsert(tmp_path: Path) -> None:
    """definition_of_done_defaults_upsert replaces config DoD."""
    _seed_config(tmp_path)

    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "0.1"},
        },
    }
    initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}

    new_items = ["Lint passes", "Tests green", "Docs updated"]
    resp = _rpc(
        [
            init,
            initialized,
            _tool_call(
                "definition_of_done_defaults_upsert",
                {"items": new_items, "auto_inherit_dod": True},
                200,
            ),
            _tool_call("definition_of_done_defaults_get", {}, 201),
        ],
        tmp_path,
    )
    upsert_payload = json.loads(_tool_text(_result_of(resp, 200)))
    assert upsert_payload["ok"] is True
    assert upsert_payload["definition_of_done"] == new_items

    get_payload = json.loads(_tool_text(_result_of(resp, 201)))
    assert get_payload["definition_of_done"] == new_items
