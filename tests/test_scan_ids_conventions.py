"""scan_ids must see every filename convention present in the live corpus.

Measured 2026-08-04: 460 files use `task-N`, 150 use a bare `N-`, and 104
have no ID. A scan blind to the bare-numbered band lets reserve_id hand out
an ID that already exists on disk.
"""
from pathlib import Path

from claude_backlog.io import reserve_id, scan_ids


def _write(root: Path, name: str) -> None:
    (root / name).write_text("---\nid: 0\ntitle: x\n---\n")


def test_scan_ids_sees_all_conventions(tmp_path: Path) -> None:
    _write(tmp_path, "task-10 - spaced-dash.md")
    _write(tmp_path, "task-11-tight-dash.md")
    _write(tmp_path, "12-bare-number.md")
    _write(tmp_path, "no-id-at-all.md")
    _write(tmp_path, "2026-04-27-date-prefixed.md")

    assert scan_ids(tmp_path) == {10, 11, 12}


def test_reserve_id_respects_bare_numbered_maximum(tmp_path: Path) -> None:
    _write(tmp_path, "task-5 - low.md")
    _write(tmp_path, "900-high-bare-number.md")

    assert reserve_id(tmp_path) == 901
