import json
import socket
import sqlite3
import threading
import time
from http.client import HTTPConnection

import pytest

from claude_backlog.web.accessor import BacklogAccessor
from claude_backlog.web.server import build_kernel


def _index(path, task_path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE nodes (id TEXT PRIMARY KEY, kind TEXT, file_path TEXT);
        CREATE TABLE aliases (alias TEXT PRIMARY KEY, id TEXT);
        CREATE TABLE collisions (file_path TEXT, claimed_id TEXT, winner_id TEXT, reason TEXT);
        CREATE TABLE alias_collisions (alias TEXT PRIMARY KEY, target_ids TEXT, source_paths TEXT, reason TEXT);
    """)
    conn.execute("INSERT INTO nodes VALUES ('stable-id','task',?)", (str(task_path),))
    conn.execute("INSERT INTO aliases VALUES ('77','stable-id')")
    conn.execute(
        "INSERT INTO alias_collisions VALUES ('ambiguous', ?, '[]', 'ambiguous-alias')",
        (json.dumps(["one", "two"]),),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def corpus(tmp_path):
    task = tmp_path / "77-legacy.md"
    task.write_text(
        "---\nid: stable-id\ntitle: Stable task\nstatus: backlog\npriority: high\n---\nBody\n"
    )
    index = tmp_path / "nodes-v2.db"
    _index(index, task)
    return tmp_path, index


def test_accessor_resolves_alias_to_string_id_detail(corpus):
    root, index = corpus
    detail = BacklogAccessor(root=root, addr_index=index).detail("77")
    assert detail["id"] == "stable-id"
    assert detail["resolution"] == "alias"
    assert detail["canonical_url"] == "/backlog/tasks/stable-id"


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def server(corpus):
    root, index = corpus
    port = _port()
    kernel = build_kernel(port=port, root=root, addr_index=index)
    httpd = kernel.build_server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.01)
    yield port
    kernel.stop()


def _get(port, path):
    conn = HTTPConnection("127.0.0.1", port, timeout=3)
    conn.request("GET", path)
    response = conn.getresponse()
    body = response.read()
    headers = dict(response.getheaders())
    conn.close()
    return response.status, headers, body


def test_alias_route_redirects_to_canonical_url(server):
    status, headers, _ = _get(server, "/backlog/tasks/77")
    assert status == 301
    assert headers["Location"] == "/backlog/tasks/stable-id?from=77"


def test_legacy_query_route_redirects_with_provenance(server):
    status, headers, _ = _get(server, "/?task=77")
    assert status == 301
    assert headers["Location"] == "/backlog/tasks/stable-id?from=77"


def test_canonical_route_serves_spa_in_standalone_and_mounted_shapes(server):
    for path in ("/backlog/tasks/stable-id", "/tasks/stable-id"):
        status, _, body = _get(server, path)
        assert status == 200
        assert b"claude-backlog" in body


def test_ambiguous_route_returns_409_with_targets(server):
    status, _, body = _get(server, "/backlog/tasks/ambiguous")
    assert status == 409
    assert json.loads(body)["targets"] == ["one", "two"]
