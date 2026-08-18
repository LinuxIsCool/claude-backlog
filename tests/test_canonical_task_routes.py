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


def _base_of(body):
    import re
    m = re.search(rb'<base href="([^"]*)"', body)
    return m.group(1).decode() if m else None


@pytest.mark.parametrize(
    "path,app_root",
    [
        ("/tasks/stable-id", "/"),
        ("/tasks/stable-id/", "/"),
        ("/backlog/tasks/stable-id", "/backlog/"),
        ("/backlog/tasks/stable-id/", "/backlog/"),
    ],
)
def test_spa_at_a_canonical_task_route_resolves_relative_urls_to_the_app_root(
    server, path, app_root
):
    """The shell is served one level deep, so `api/list` and `static/...` would
    resolve into /tasks/<id>/ and 404. A <base> has to lift them back up.

    The hub strips the mount prefix before the handler sees the path, so the
    base cannot name /backlog itself; it has to be relative for the browser to
    resolve against whatever prefix it is actually on.
    """
    from urllib.parse import urljoin

    status, _, body = _get(server, path)
    assert status == 200
    base = _base_of(body)
    assert base is not None, f"{path} serves no <base>; relative URLs resolve one level too deep"

    document = urljoin("http://h", path)
    resolved = urljoin(urljoin(document, base), "api/list")
    assert resolved == f"http://h{app_root}api/list"


def test_the_api_url_the_shell_would_request_actually_answers(server):
    """Resolve the page's own relative URL and fetch it, rather than trusting
    that a 200 on the shell means the page works."""
    from urllib.parse import urljoin, urlparse

    path = "/tasks/stable-id"
    _, _, body = _get(server, path)
    base = _base_of(body)
    assert base is not None
    target = urlparse(urljoin(urljoin(urljoin("http://h", path), base), "api/list")).path
    status, _, _ = _get(server, target)
    assert status == 200, f"the shell would request {target}, which answers {status}"
