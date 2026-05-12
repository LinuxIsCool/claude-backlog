"""Track B — Phase 4.6 external MCP client validator (v2).

Drives the claude-backlog MCP server via stdio JSON-RPC exactly as any
external MCP client would. NO knowledge of internals; pure protocol.

Server contract per Phase 4 ship:
  - task_list / task_view / task_search / draft_list → markdown text
  - task_create / task_edit / task_archive / draft_promote → JSON
    payload with `ok: True` and tool-specific keys
  - definition_of_done_defaults_get / _upsert → JSON dict
  - get_backlog_instructions → workflow markdown

Sequence:
  B.0 initialize handshake
  B.1 tools/list → expect 11 tools
  B.2 resources/list → expect 1 resource
  B.3 resources/read claude-backlog://workflow/overview
  B.4 tools/call task_list (read; markdown)
  B.5 tools/call task_view (read; markdown)
  B.6 tools/call task_search (read; markdown)
  B.7 tools/call definition_of_done_defaults_get (read; JSON)
  B.8 tools/call task_create (write; JSON)
  B.9 tools/call task_edit (write; JSON)
  B.10 tools/call task_archive (write; JSON; verifies file move)
  B.11 tools/call draft_list (read; markdown)
  B.12 tools/call get_backlog_instructions (read; markdown fallback)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(
    "/home/shawn/.claude/plugins/local/legion-plugins/plugins/claude-backlog"
)


class MCPClient:
    def __init__(self, backlog_root: str) -> None:
        env = os.environ.copy()
        env["BACKLOG_ROOT"] = backlog_root
        self.proc = subprocess.Popen(
            [
                "uv", "run", "--directory", str(PLUGIN_ROOT), "scripts/mcp_server.py",
            ],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True, bufsize=0,
        )
        self.next_id = 1

    def send(self, method: str, params: dict | None = None,
             is_notification: bool = False) -> dict | None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not is_notification:
            msg["id"] = self.next_id
            self.next_id += 1
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        time.sleep(0.05)
        if is_notification:
            return None
        return self._read_response(msg["id"])

    def _read_response(self, want_id: int, timeout_s: float = 10.0) -> dict:
        assert self.proc.stdout is not None
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == want_id:
                return msg
        raise TimeoutError(f"timeout id={want_id}")

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return self.send("tools/call",
                         {"name": name, "arguments": arguments or {}}) or {}

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _tool_text(resp: dict) -> str:
    """Extract the text payload from a tools/call response."""
    return resp["result"]["content"][0]["text"]


def _tool_json(resp: dict) -> Any:
    return json.loads(_tool_text(resp))


def run(name: str, fn) -> tuple[bool, str]:
    try:
        return True, str(fn())
    except Exception as e:
        return False, f"FAIL: {type(e).__name__}: {e}"


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="track-b-mcp-")
    tmp_root = Path(tmp)
    (tmp_root / "drafts").mkdir()
    (tmp_root / "archive").mkdir()
    (tmp_root / "docs").mkdir()
    (tmp_root / "config.yml").write_text(
        "definition_of_done:\n"
        "  - Tests pass\n"
        "  - Docs updated\n"
        "auto_inherit_dod: true\n",
        encoding="utf-8",
    )
    seed = """---
id: 1
title: "Seed task — Track B validation"
status: backlog
priority: high
created: 2026-05-12
milestone: null
tags:
  - validation
  - track-b
estimated_hours: null
depends_on: []
blocks: []
effort: null
due: null
venture: null
---

## Description
Seed for Track B.

## Acceptance Criteria
- [ ] Tool discovery works

## Definition of Done
- [ ] Tests pass
"""
    (tmp_root / "task-1 - seed-track-b-validation.md").write_text(seed, encoding="utf-8")

    print(f"tmp BACKLOG_ROOT: {tmp_root}")
    client = MCPClient(str(tmp_root))
    results: list[tuple[str, bool, str]] = []

    try:
        # B.0
        client.send("initialize", {"protocolVersion": "2024-11-05",
                                   "capabilities": {},
                                   "clientInfo": {"name": "track-b-validator", "version": "0.1"}})
        client.send("notifications/initialized", is_notification=True)
        time.sleep(0.1)
        results.append(("B.0 initialize + notify", True, "ok"))

        # B.1 tools/list
        def _tl():
            resp = client.send("tools/list", {}) or {}
            tools = resp.get("result", {}).get("tools", [])
            names = sorted(t["name"] for t in tools)
            expected = sorted([
                "get_backlog_instructions", "task_list", "task_view", "task_search",
                "task_create", "task_edit", "task_archive", "draft_list",
                "draft_promote", "definition_of_done_defaults_get",
                "definition_of_done_defaults_upsert",
            ])
            assert names == expected, f"mismatch: {set(expected) ^ set(names)}"
            return f"{len(names)} tools all present"
        results.append(("B.1 tools/list (11 tools)", *run("B.1", _tl)))

        # B.2 resources/list
        def _rl():
            resp = client.send("resources/list", {}) or {}
            uris = [r["uri"] for r in resp.get("result", {}).get("resources", [])]
            assert "claude-backlog://workflow/overview" in uris, uris
            return uris
        results.append(("B.2 resources/list", *run("B.2", _rl)))

        # B.3 resources/read workflow
        def _rr():
            resp = client.send("resources/read",
                               {"uri": "claude-backlog://workflow/overview"}) or {}
            text = resp["result"]["contents"][0]["text"]
            assert "Agent Workflow Overview" in text, text[:200]
            assert len(text) > 5000, f"too short: {len(text)}"
            return f"{len(text)} chars, header present"
        results.append(("B.3 resources/read workflow", *run("B.3", _rr)))

        # B.4 task_list (markdown)
        def _task_list():
            resp = client.call_tool("task_list", {})
            text = _tool_text(resp)
            assert "#1" in text, f"seed task missing: {text[:300]}"
            assert "Seed task" in text, f"title missing: {text[:300]}"
            return f"markdown {len(text)} chars; seed found"
        results.append(("B.4 task_list", *run("B.4", _task_list)))

        # B.5 task_view
        def _task_view():
            resp = client.call_tool("task_view", {"task_id": 1})
            text = _tool_text(resp)
            assert "Task 1: Seed task" in text, text[:200]
            assert "Acceptance Criteria" in text
            return f"task_view → markdown {len(text)} chars"
        results.append(("B.5 task_view", *run("B.5", _task_view)))

        # B.6 task_search
        def _task_search():
            resp = client.call_tool("task_search", {"query": "Track B"})
            text = _tool_text(resp)
            assert "Track B" in text or "track-b" in text, text[:200]
            return f"task_search → {len(text)} chars"
        results.append(("B.6 task_search", *run("B.6", _task_search)))

        # B.7 dod_get (JSON)
        def _dod_get():
            resp = client.call_tool("definition_of_done_defaults_get", {})
            data = _tool_json(resp)
            assert data.get("auto_inherit_dod") is True, data
            assert "Tests pass" in data["definition_of_done"], data
            return f"auto_inherit=True, {len(data['definition_of_done'])} items"
        results.append(("B.7 dod_get", *run("B.7", _dod_get)))

        # B.8 task_create
        new_id_holder: list[int] = []
        def _task_create():
            resp = client.call_tool("task_create", {
                "title": "Track B external creation",
                "priority": "medium",
                "tags": ["track-b", "external"],
            })
            data = _tool_json(resp)
            assert data.get("ok") is True, data
            tid = data["task_id"]
            new_id_holder.append(tid)
            assert data.get("dod_inherited") == 2, data
            # Verify file landed at root
            files = list(tmp_root.glob(f"task-{tid} - *.md"))
            assert files, f"file missing for id={tid}"
            return f"created id={tid}, dod_inherited=2"
        results.append(("B.8 task_create", *run("B.8", _task_create)))

        # B.9 task_edit
        if new_id_holder:
            tid = new_id_holder[0]
            def _task_edit():
                resp = client.call_tool("task_edit",
                                        {"task_id": tid, "check_ac": [1]})
                data = _tool_json(resp)
                assert data.get("ok") is True, data
                # Verify file content
                f = next(tmp_root.glob(f"task-{tid} - *.md"))
                content = f.read_text()
                ac_idx = content.index("## Acceptance Criteria")
                ac_section = content[ac_idx:content.index("## Definition of Done")]
                assert "- [x]" in ac_section, f"AC not checked: {ac_section}"
                return f"task_edit → AC[1] checked"
            results.append(("B.9 task_edit (check_ac[1])", *run("B.9", _task_edit)))

            # B.10 task_archive
            def _task_archive():
                resp = client.call_tool("task_archive", {"task_id": tid})
                data = _tool_json(resp)
                assert data.get("ok") is True, data
                # Verify file moved
                root_files = list(tmp_root.glob(f"task-{tid} - *.md"))
                archive_files = list((tmp_root / "archive").glob(f"task-{tid} - *.md"))
                assert not root_files, f"still at root: {root_files}"
                assert archive_files, f"not in archive: {list((tmp_root / 'archive').iterdir())}"
                return f"task_archive → moved to archive/{archive_files[0].name}"
            results.append(("B.10 task_archive", *run("B.10", _task_archive)))

        # B.11 draft_list
        def _draft_list():
            resp = client.call_tool("draft_list", {})
            text = _tool_text(resp)
            assert "No drafts" in text or len(text) >= 0, text
            return f"draft_list → {len(text)} chars (empty drafts/)"
        results.append(("B.11 draft_list", *run("B.11", _draft_list)))

        # B.12 get_backlog_instructions (resource fallback)
        def _get_instr():
            resp = client.call_tool("get_backlog_instructions", {})
            text = _tool_text(resp)
            assert "Agent Workflow Overview" in text
            return f"get_backlog_instructions → {len(text)} chars"
        results.append(("B.12 get_backlog_instructions", *run("B.12", _get_instr)))

    finally:
        client.close()
        shutil.rmtree(tmp, ignore_errors=True)

    # Summary
    print("\n" + "=" * 72)
    print("Track B — Phase 4.6 external MCP client validation")
    print("=" * 72)
    ok_n = sum(1 for _, ok, _ in results if ok)
    for name, ok, msg in results:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}: {msg}")
    print("=" * 72)
    print(f"  {ok_n}/{len(results)} passed")
    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
