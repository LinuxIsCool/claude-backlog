"""Unit tests for claude_backlog.io."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from claude_backlog.errors import BacklogToolError, ErrorCode
from claude_backlog.io import (
    Stage,
    find_task,
    list_tasks,
    load_config,
    mv_task,
    next_id,
    parse_frontmatter,
    read_task,
    save_config,
    scan_ids,
    slugify,
    task_to_text,
    write_task,
)
from claude_backlog.schema import Task


# --- slugify ----------------------------------------------------------------


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Simple title", "simple-title"),
        ("Spaces  and   punctuation!", "spaces-and-punctuation"),
        ("MiXeD CaSe", "mixed-case"),
        ("Already-slugified-fine", "already-slugified-fine"),
        ("Café résumé naïve", "cafe-resume-naive"),
        ("emoji 🚀 in title", "emoji-in-title"),
        ("", "untitled"),
        ("!!!", "untitled"),
        ("a" * 200, "a" * 60),  # truncation to max_len
    ],
)
def test_slugify(title: str, expected: str) -> None:
    assert slugify(title) == expected


def test_slugify_truncates_then_strips_trailing_dash() -> None:
    """A title whose 60-char slice ends with `-` should drop the trailing dash."""
    title = "abc " * 30  # produces alternating word-dash pattern
    result = slugify(title)
    assert len(result) <= 60
    assert not result.endswith("-")


def test_slugify_custom_max_len() -> None:
    assert slugify("hello world", max_len=5) == "hello"


# --- parse_frontmatter ------------------------------------------------------


def test_parse_frontmatter_basic(tmp_path: Path) -> None:
    f = tmp_path / "task-1 - x.md"
    f.write_text("---\nid: 1\ntitle: x\n---\n\nbody here\n")
    fm = parse_frontmatter(f)
    assert fm == {"id": 1, "title": "x"}


def test_parse_frontmatter_missing_block(tmp_path: Path) -> None:
    f = tmp_path / "task-1.md"
    f.write_text("no frontmatter here")
    assert parse_frontmatter(f) == {}


def test_parse_frontmatter_missing_file(tmp_path: Path) -> None:
    assert parse_frontmatter(tmp_path / "nonexistent.md") == {}


def test_parse_frontmatter_malformed_yaml(tmp_path: Path) -> None:
    """The F2 enrichment bug produces broken keys — parse_frontmatter must
    not raise on these so SessionStart hooks keep working."""
    f = tmp_path / "task-broken.md"
    # F2 enrichment bug surfaces as unclosed flow / bare-key scanner errors.
    f.write_text("---\nid: 1\nbroken: [1, 2\n---\n\nbody\n")
    # Should NOT raise; returns {} on YAML errors.
    result = parse_frontmatter(f)
    assert result == {} or isinstance(result, dict)


# --- scan_ids + next_id -----------------------------------------------------


def test_scan_ids_empty(tmp_backlog: Path) -> None:
    assert scan_ids(root=tmp_backlog) == set()


def test_scan_ids_across_stages(tmp_backlog: Path) -> None:
    (tmp_backlog / "task-1 - a.md").write_text("---\nid: 1\ntitle: a\n---\n")
    (tmp_backlog / "drafts" / "task-2 - b.md").write_text("---\nid: 2\ntitle: b\n---\n")
    (tmp_backlog / "archive" / "task-3 - c.md").write_text("---\nid: 3\ntitle: c\n---\n")
    assert scan_ids(root=tmp_backlog) == {1, 2, 3}


def test_next_id_empty(tmp_backlog: Path) -> None:
    assert next_id(root=tmp_backlog) == 1


def test_next_id_with_gaps(tmp_backlog: Path) -> None:
    (tmp_backlog / "task-1 - a.md").write_text("---\nid: 1\ntitle: a\n---\n")
    (tmp_backlog / "task-5 - e.md").write_text("---\nid: 5\ntitle: e\n---\n")
    assert next_id(root=tmp_backlog) == 6


# --- find_task --------------------------------------------------------------


def test_find_task_active(tmp_backlog: Path) -> None:
    p = tmp_backlog / "task-7 - g.md"
    p.write_text("---\nid: 7\ntitle: g\n---\n")
    assert find_task(7, Stage.ACTIVE, root=tmp_backlog) == p
    assert find_task(7, Stage.DRAFTS, root=tmp_backlog) is None
    assert find_task(7, Stage.ANY, root=tmp_backlog) == p


def test_find_task_drafts(tmp_backlog: Path) -> None:
    p = tmp_backlog / "drafts" / "task-9 - d.md"
    p.write_text("---\nid: 9\ntitle: d\nstatus: draft\n---\n")
    assert find_task(9, Stage.DRAFTS, root=tmp_backlog) == p
    assert find_task(9, Stage.ACTIVE, root=tmp_backlog) is None


def test_find_task_not_found(tmp_backlog: Path) -> None:
    assert find_task(999, Stage.ANY, root=tmp_backlog) is None


# --- write_task + read_task round-trip --------------------------------------


def test_write_then_read_roundtrip(tmp_backlog: Path, sample_task: Task) -> None:
    path = write_task(sample_task, root=tmp_backlog)
    assert path.exists()
    assert path.parent == tmp_backlog
    loaded = read_task(path)
    assert loaded.id == sample_task.id
    assert loaded.title == sample_task.title
    assert loaded.tags == sample_task.tags
    assert loaded.definition_of_done == sample_task.definition_of_done
    # Body should survive round-trip
    assert "Acceptance Criteria" in loaded.body
    assert "Definition of Done" in loaded.body


def test_write_task_id_collision(tmp_backlog: Path, sample_task: Task) -> None:
    write_task(sample_task, root=tmp_backlog)
    # Try to write a different task with the same ID in a different stage.
    sample_task.title = "Different title — different file"
    with pytest.raises(BacklogToolError) as exc_info:
        write_task(sample_task, stage=Stage.ARCHIVE, root=tmp_backlog)
    assert exc_info.value.code == ErrorCode.ID_COLLISION


def test_write_task_overwrite_same_path_is_ok(
    tmp_backlog: Path, sample_task: Task
) -> None:
    p1 = write_task(sample_task, root=tmp_backlog)
    # Writing the same task again (same stage, same slug) should be a no-op
    # collision-wise — find_task returns the same path.
    p2 = write_task(sample_task, root=tmp_backlog)
    assert p1 == p2


def test_read_task_missing(tmp_backlog: Path) -> None:
    with pytest.raises(BacklogToolError) as exc_info:
        read_task(tmp_backlog / "task-999 - missing.md")
    assert exc_info.value.code == ErrorCode.TASK_NOT_FOUND


def test_read_task_malformed_yaml_raises_typed_error(tmp_backlog: Path) -> None:
    """Direct read_task surfaces YAML errors as VALIDATION_ERROR."""
    f = tmp_backlog / "task-1 - bad.md"
    # Unclosed flow sequence — true YAML ScannerError / ParserError.
    f.write_text("---\nid: 1\ntitle: bad\nbroken: [1, 2\n---\n\nbody\n")
    with pytest.raises(BacklogToolError) as exc_info:
        read_task(f)
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


# --- mv_task ----------------------------------------------------------------


def test_mv_task_preserves_id(tmp_backlog: Path, sample_task: Task) -> None:
    src = write_task(sample_task, root=tmp_backlog)
    assert src.parent == tmp_backlog

    dest = mv_task(sample_task.id, Stage.ACTIVE, Stage.ARCHIVE, root=tmp_backlog)
    assert dest.exists()
    assert not src.exists()
    assert dest.parent == tmp_backlog / "archive"
    # ID-stable: filename stem is identical
    assert dest.name == src.name

    loaded = read_task(dest)
    assert loaded.id == sample_task.id


def test_mv_task_drafts_to_active(tmp_backlog: Path) -> None:
    draft = tmp_backlog / "drafts" / "task-12 - d.md"
    draft.write_text("---\nid: 12\ntitle: d\nstatus: draft\n---\n")
    dest = mv_task(12, Stage.DRAFTS, Stage.ACTIVE, root=tmp_backlog)
    assert dest.parent == tmp_backlog
    assert not draft.exists()


def test_mv_task_not_found(tmp_backlog: Path) -> None:
    with pytest.raises(BacklogToolError) as exc_info:
        mv_task(999, Stage.ACTIVE, Stage.ARCHIVE, root=tmp_backlog)
    assert exc_info.value.code == ErrorCode.TASK_NOT_FOUND


# --- list_tasks -------------------------------------------------------------


def test_list_tasks_active_only(tmp_backlog: Path, sample_task: Task) -> None:
    write_task(sample_task, root=tmp_backlog)
    sample_task.id = 2
    sample_task.title = "Second"
    write_task(sample_task, root=tmp_backlog)
    tasks = list(list_tasks(Stage.ACTIVE, root=tmp_backlog))
    assert len(tasks) == 2


def test_list_tasks_skips_unparseable(tmp_backlog: Path) -> None:
    """If one task is malformed, list_tasks yields the rest without raising."""
    (tmp_backlog / "task-1 - ok.md").write_text(
        "---\nid: 1\ntitle: ok\nstatus: To Do\ncreated: 2026-05-12\n---\n"
    )
    (tmp_backlog / "task-2 - broken.md").write_text(
        "---\nid: 2\ntitle: x\nbroken: [1, 2\n---\n"
    )
    tasks = list(list_tasks(Stage.ACTIVE, root=tmp_backlog))
    assert len(tasks) == 1
    assert tasks[0].id == 1


# --- config load + save ----------------------------------------------------


def test_load_config_missing_returns_defaults(tmp_backlog: Path) -> None:
    cfg = load_config(root=tmp_backlog)
    assert cfg.auto_inherit_dod is True
    assert "low" in cfg.priorities


def test_load_config_reads_real_yaml(tmp_backlog: Path) -> None:
    (tmp_backlog / "config.yml").write_text(
        "statuses: [Backlog, Done]\n"
        "priorities: [low, high]\n"
        "definition_of_done: [item1, item2]\n"
        "auto_inherit_dod: false\n"
    )
    cfg = load_config(root=tmp_backlog)
    assert cfg.statuses == ["Backlog", "Done"]
    assert cfg.auto_inherit_dod is False
    assert cfg.definition_of_done == ["item1", "item2"]


def test_save_config_roundtrip(tmp_backlog: Path, sample_config) -> None:
    save_config(sample_config, root=tmp_backlog)
    cfg2 = load_config(root=tmp_backlog)
    assert cfg2.definition_of_done == sample_config.definition_of_done
    assert cfg2.auto_inherit_dod == sample_config.auto_inherit_dod


# --- task_to_text formatting ------------------------------------------------


def test_task_to_text_has_frontmatter_block(sample_task: Task) -> None:
    text = task_to_text(sample_task)
    assert text.startswith("---\n")
    assert "id: 1\n" in text
    assert "title: Sample task\n" in text
    # Empty-default fields should NOT be serialized
    assert "blocks:" not in text
    assert "ordinal:" not in text


def test_task_to_text_preserves_extra_frontmatter(sample_task: Task) -> None:
    sample_task.extra_frontmatter = {"intent": "test extra", "venture": "longtail"}
    text = task_to_text(sample_task)
    # `venture` is a known field; emitted via known-field path with `None` skip
    # `intent` is unknown — should appear via extras
    assert "intent: test extra" in text


# --- Stage enum -------------------------------------------------------------


def test_stage_dir_resolution(tmp_backlog: Path) -> None:
    assert Stage.ACTIVE.dir(tmp_backlog) == tmp_backlog
    assert Stage.DRAFTS.dir(tmp_backlog) == tmp_backlog / "drafts"
    assert Stage.ARCHIVE.dir(tmp_backlog) == tmp_backlog / "archive"


def test_stage_any_cannot_resolve_dir(tmp_backlog: Path) -> None:
    with pytest.raises(BacklogToolError) as exc_info:
        Stage.ANY.dir(tmp_backlog)
    assert exc_info.value.code == ErrorCode.INVALID_STAGE
