"""Tests for scripts/dedupe_collisions.py — task-447 A2.

Covers:
  - find_collisions detects only ID groups with >= 2 files
  - plan_dedupe places older-mtime file as keeper, newer(s) as victims
  - _rewrite_id_in_frontmatter touches ONLY the first `id:` line
  - _body_mentions_old_id detects `task-NNN` mentions, ignores `task-NNN0`
  - execute_plan renames file + rewrites id + persists counter
  - End-to-end: synthesize collisions, run --apply, verify clean state
  - Idempotency: running on clean corpus is a no-op
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

# Load the script as a module (it's not under src/).
_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "dedupe_collisions.py"
)
_SPEC = importlib.util.spec_from_file_location("dedupe_collisions", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
dedupe = importlib.util.module_from_spec(_SPEC)
sys.modules["dedupe_collisions"] = dedupe
_SPEC.loader.exec_module(dedupe)


def _seed(path: Path, task_id: int, slug: str, body: str = "body") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {task_id}\ntitle: {slug}\nstatus: backlog\n"
        f"priority: medium\ncreated: 2026-05-12\n---\n\n{body}\n"
    )
    return path


# --- find_collisions --------------------------------------------------------


def test_find_collisions_empty(tmp_backlog: Path) -> None:
    assert dedupe.find_collisions(tmp_backlog) == {}


def test_find_collisions_no_dupes(tmp_backlog: Path) -> None:
    _seed(tmp_backlog / "task-1 - a.md", 1, "a")
    _seed(tmp_backlog / "task-2 - b.md", 2, "b")
    assert dedupe.find_collisions(tmp_backlog) == {}


def test_find_collisions_detects_pair(tmp_backlog: Path) -> None:
    p1 = _seed(tmp_backlog / "task-7 - one.md", 7, "one")
    p2 = _seed(tmp_backlog / "task-7 - two.md", 7, "two")
    result = dedupe.find_collisions(tmp_backlog)
    assert 7 in result
    assert set(result[7]) == {p1, p2}


def test_find_collisions_across_stages(tmp_backlog: Path) -> None:
    """A collision can span active + drafts + archive (all real cases on disk)."""
    p1 = _seed(tmp_backlog / "task-9 - active.md", 9, "active")
    p2 = _seed(tmp_backlog / "drafts" / "task-9 - draft.md", 9, "draft")
    p3 = _seed(tmp_backlog / "archive" / "task-9 - old.md", 9, "old")
    result = dedupe.find_collisions(tmp_backlog)
    assert set(result[9]) == {p1, p2, p3}


# --- plan_dedupe ------------------------------------------------------------


def test_plan_dedupe_older_wins(tmp_backlog: Path) -> None:
    """Plan must place the older-mtime file as keeper."""
    p_old = _seed(tmp_backlog / "task-5 - old.md", 5, "old")
    time.sleep(0.02)  # ensure mtime separation across filesystems
    p_new = _seed(tmp_backlog / "task-5 - new.md", 5, "new")
    collisions = dedupe.find_collisions(tmp_backlog)
    plans = dedupe.plan_dedupe(collisions)
    assert len(plans) == 1
    assert plans[0]["old_id"] == 5
    assert Path(plans[0]["keeper"]) == p_old
    assert Path(plans[0]["victim"]) == p_new
    assert plans[0]["victim_slug"] == "new"
    assert plans[0]["new_id"] is None  # not yet reserved


def test_plan_dedupe_three_way_collision(tmp_backlog: Path) -> None:
    """If three files share an ID, two get reassigned (in mtime order)."""
    p1 = _seed(tmp_backlog / "task-3 - first.md", 3, "first")
    time.sleep(0.02)
    p2 = _seed(tmp_backlog / "task-3 - second.md", 3, "second")
    time.sleep(0.02)
    p3 = _seed(tmp_backlog / "task-3 - third.md", 3, "third")
    plans = dedupe.plan_dedupe(dedupe.find_collisions(tmp_backlog))
    assert len(plans) == 2
    keeper_paths = {Path(plan["keeper"]) for plan in plans}
    victim_paths = {Path(plan["victim"]) for plan in plans}
    assert keeper_paths == {p1}  # the same keeper across both plans
    assert victim_paths == {p2, p3}


# --- _rewrite_id_in_frontmatter --------------------------------------------


def test_rewrite_id_replaces_first_id_line() -> None:
    src = "---\nid: 217\ntitle: foo\npriority: medium\n---\n\nbody with id: 999\n"
    out = dedupe._rewrite_id_in_frontmatter(src, 448)
    assert out.startswith("---\nid: 448\n")
    # Body must remain untouched.
    assert "body with id: 999" in out


def test_rewrite_id_idempotent_when_no_frontmatter() -> None:
    src = "no frontmatter here\nid: 1\n"
    assert dedupe._rewrite_id_in_frontmatter(src, 999) == src


def test_rewrite_id_handles_padded_value() -> None:
    """Some legacy tasks use `id: 030` (zero-padded). Regex must still match."""
    src = "---\nid: 030\ntitle: x\n---\n\nbody\n"
    out = dedupe._rewrite_id_in_frontmatter(src, 500)
    assert "id: 500" in out
    assert "id: 030" not in out


def test_rewrite_id_handles_legacy_task_prefix_form() -> None:
    """117 of 286 corpus tasks use `id: task-030` form (string with prefix).
    Schema validator coerces these to int — but if dedupe leaves the prefix
    intact, both files still resolve to the same int ID and the API
    surfaces a duplicate. Must rewrite to pure integer."""
    src = "---\nid: task-030\ntitle: foo\n---\n\nbody\n"
    out = dedupe._rewrite_id_in_frontmatter(src, 448)
    assert "id: 448" in out
    assert "task-030" not in out


def test_rewrite_id_handles_quoted_task_prefix() -> None:
    """`id: 'task-30'` quoted form (rare but observed in legacy YAML)."""
    src = "---\nid: 'task-30'\ntitle: foo\n---\n\nbody\n"
    out = dedupe._rewrite_id_in_frontmatter(src, 449)
    assert "id: 449" in out
    assert "task-30" not in out


def test_rewrite_id_handles_quoted_int() -> None:
    src = '---\nid: "30"\ntitle: foo\n---\n\nbody\n'
    out = dedupe._rewrite_id_in_frontmatter(src, 450)
    assert "id: 450" in out


# --- _body_mentions_old_id --------------------------------------------------


def test_body_mentions_counts_task_id_refs() -> None:
    text = (
        "This task supersedes task-217 and also task-217 again.\n"
        "But task-2170 is different (longer ID).\n"
    )
    assert dedupe._body_mentions_old_id(text, 217) == 2


def test_body_mentions_handles_zero_padded() -> None:
    text = "See task-030 and task-0030 for context.\n"
    # \btask-0*30\b matches both forms.
    assert dedupe._body_mentions_old_id(text, 30) == 2


# --- execute_plan + end-to-end ---------------------------------------------


def test_execute_plan_renames_and_reassigns(tmp_backlog: Path) -> None:
    """Full migration cycle on a synthetic 3-collision corpus."""
    # Build a small corpus with one healthy + two colliding pairs.
    _seed(tmp_backlog / "task-1 - keep.md", 1, "keep")
    _seed(tmp_backlog / "task-10 - first.md", 10, "first")
    time.sleep(0.02)
    _seed(tmp_backlog / "task-10 - second.md", 10, "second")
    _seed(tmp_backlog / "task-20 - alpha.md", 20, "alpha")
    time.sleep(0.02)
    _seed(tmp_backlog / "task-20 - beta.md", 20, "beta")

    plans = dedupe.plan_dedupe(dedupe.find_collisions(tmp_backlog))
    assert len(plans) == 2

    results = dedupe.execute_plan(plans, tmp_backlog)
    assert len(results) == 2

    # Each victim got a unique new_id, both > max(scan_ids) at time of plan.
    new_ids = [r["new_id"] for r in results]
    assert len(set(new_ids)) == 2
    assert min(new_ids) >= 21  # past max original ID

    # Verify post-state: no collisions remain.
    assert dedupe.find_collisions(tmp_backlog) == {}

    # Verify the keepers still hold the original IDs (10 and 20).
    keeper_10 = tmp_backlog / "task-10 - first.md"
    keeper_20 = tmp_backlog / "task-20 - alpha.md"
    assert keeper_10.exists()
    assert keeper_20.exists()
    assert "id: 10" in keeper_10.read_text()
    assert "id: 20" in keeper_20.read_text()

    # Counter file was bumped by reserve_id() during execution.
    counter_file = tmp_backlog / ".next_id_counter"
    assert counter_file.exists()
    assert int(counter_file.read_text().strip()) == max(new_ids)


def test_migration_log_written(tmp_backlog: Path) -> None:
    _seed(tmp_backlog / "task-5 - old.md", 5, "old")
    time.sleep(0.02)
    _seed(tmp_backlog / "task-5 - new.md", 5, "new")
    plans = dedupe.plan_dedupe(dedupe.find_collisions(tmp_backlog))
    results = dedupe.execute_plan(plans, tmp_backlog)
    log_path = dedupe.write_migration_log(
        tmp_backlog, results, "2026-05-12T20:00:00+00:00", "2026-05-12T20:00:01+00:00"
    )
    assert log_path.exists()
    payload = json.loads(log_path.read_text())
    assert payload["tool"] == "claude_backlog.scripts.dedupe_collisions"
    assert payload["summary"]["total_renames"] == 1
    assert payload["summary"]["ids_freed_for_reassignment"] == [5]


def test_idempotency_on_clean_corpus(tmp_backlog: Path) -> None:
    """Running --apply with no collisions must be a no-op."""
    _seed(tmp_backlog / "task-1 - clean.md", 1, "clean")
    rc = dedupe.main(["--apply", "--root", str(tmp_backlog)])
    assert rc == 0
    # File untouched.
    assert (tmp_backlog / "task-1 - clean.md").exists()
    # No counter bumping happened because plan was empty.
    counter_file = tmp_backlog / ".next_id_counter"
    assert not counter_file.exists()


def test_main_dry_run_exits_zero_and_reports(tmp_backlog: Path, capsys) -> None:
    _seed(tmp_backlog / "task-5 - old.md", 5, "old")
    time.sleep(0.02)
    _seed(tmp_backlog / "task-5 - new.md", 5, "new")
    rc = dedupe.main(["--root", str(tmp_backlog)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Mode: DRY-RUN" in out
    assert "task-5:" in out
    assert "Re-run with --apply" in out
    # File still on disk untouched.
    assert (tmp_backlog / "task-5 - new.md").exists()
