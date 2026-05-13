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
    peek_next_id,
    read_task,
    reserve_id,
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


# --- task-447: atomic reserve_id + counter file -----------------------------


def test_next_id_is_atomic_alias_for_reserve_id(tmp_backlog: Path) -> None:
    """next_id() and reserve_id() are functionally identical post-task-447.

    Both atomically allocate a fresh ID under flock. Each call must
    return a strictly larger value than the previous one.
    """
    a = next_id(root=tmp_backlog)
    b = reserve_id(root=tmp_backlog)
    c = next_id(root=tmp_backlog)
    assert a == 1
    assert b == 2
    assert c == 3


def test_reserve_id_persists_counter_file(tmp_backlog: Path) -> None:
    """After reservation, .next_id_counter holds the reserved value.

    Survives across process boundaries — a subsequent reserve_id() in a
    fresh process would read this counter and increment from there.
    """
    reserve_id(root=tmp_backlog)
    reserve_id(root=tmp_backlog)
    reserved = reserve_id(root=tmp_backlog)
    counter_file = tmp_backlog / ".next_id_counter"
    assert counter_file.exists()
    assert counter_file.read_text().strip() == str(reserved)


def test_reserve_id_reconciles_manual_additions(tmp_backlog: Path) -> None:
    """If someone adds task-NNN.md without going through reserve_id,
    the next reservation jumps past their highest manual ID.

    Reconciliation against scan_ids() is checked on EVERY call so manual
    additions can never produce a collision with the counter.
    """
    (tmp_backlog / "task-1 - a.md").write_text("---\nid: 1\ntitle: a\n---\n")
    (tmp_backlog / "task-500 - manual.md").write_text(
        "---\nid: 500\ntitle: manual\n---\n",
    )
    # Counter file does NOT exist yet → only scan_ids contributes.
    assert reserve_id(root=tmp_backlog) == 501
    # Now counter is 501. Add another manual file at 600 — reconciliation kicks in.
    (tmp_backlog / "task-600 - manual2.md").write_text(
        "---\nid: 600\ntitle: manual2\n---\n",
    )
    assert reserve_id(root=tmp_backlog) == 601


def test_peek_next_id_does_not_reserve(tmp_backlog: Path) -> None:
    """peek_next_id is read-only — two peeks return the same value,
    and the persisted counter is unchanged."""
    (tmp_backlog / "task-10 - x.md").write_text("---\nid: 10\ntitle: x\n---\n")
    a = peek_next_id(root=tmp_backlog)
    b = peek_next_id(root=tmp_backlog)
    assert a == b == 11
    # Counter file should not have been created by peek calls.
    counter_file = tmp_backlog / ".next_id_counter"
    assert not counter_file.exists()


def test_reserve_id_no_collisions_under_thread_concurrency(
    tmp_backlog: Path,
) -> None:
    """100 threads × 10 reservations each → 1000 distinct IDs.

    Validates fcntl.flock(LOCK_EX) on per-call file descriptors serializes
    concurrent reservations correctly. This is the core regression test
    for the 37-collision live-corpus bug (task-447).
    """
    import concurrent.futures

    NUM_THREADS = 100
    PER_THREAD = 10

    def worker() -> list[int]:
        return [reserve_id(root=tmp_backlog) for _ in range(PER_THREAD)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS) as ex:
        results = list(ex.map(lambda _: worker(), range(NUM_THREADS)))

    all_ids: list[int] = []
    for r in results:
        all_ids.extend(r)

    expected_total = NUM_THREADS * PER_THREAD
    assert len(all_ids) == expected_total
    assert len(set(all_ids)) == expected_total, (
        f"COLLISION: {expected_total - len(set(all_ids))} duplicate IDs "
        f"under {NUM_THREADS}-thread × {PER_THREAD}-reservation stress."
    )
    # IDs should be the contiguous range 1..expected_total.
    assert min(all_ids) == 1
    assert max(all_ids) == expected_total


def test_reserve_id_no_collisions_under_process_concurrency(
    tmp_backlog: Path,
) -> None:
    """Multi-process belt-and-suspenders. fork() 10 children × 10 reservations.

    flock semantics differ subtly between threads (per-FD locks within one
    process) and processes (kernel-level inter-process locks). This test
    verifies process-level correctness directly — the real production
    scenario (multiple Claude agents) is multi-process.
    """
    import multiprocessing

    NUM_PROCS = 10
    PER_PROC = 10

    def worker(root_str: str, q: multiprocessing.Queue) -> None:
        from pathlib import Path as P

        from claude_backlog.io import reserve_id as ri

        ids = [ri(root=P(root_str)) for _ in range(PER_PROC)]
        q.put(ids)

    ctx = multiprocessing.get_context("fork")
    q: multiprocessing.Queue = ctx.Queue()
    procs = [
        ctx.Process(target=worker, args=(str(tmp_backlog), q))
        for _ in range(NUM_PROCS)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0, f"worker exited {p.exitcode}"

    all_ids: list[int] = []
    while not q.empty():
        all_ids.extend(q.get())

    expected_total = NUM_PROCS * PER_PROC
    assert len(all_ids) == expected_total
    assert len(set(all_ids)) == expected_total, (
        f"PROCESS COLLISION: {expected_total - len(set(all_ids))} duplicates "
        f"across {NUM_PROCS} fork()ed workers."
    )


def test_counter_file_drift_below_scan_ids_self_heals(tmp_backlog: Path) -> None:
    """If the counter file drifts BELOW max(scan_ids), the next reserve_id
    call reconciles upward. Protects against manual counter editing or
    corrupted state — scan_ids is always authoritative when higher."""
    counter_file = tmp_backlog / ".next_id_counter"
    counter_file.write_text("3")  # artificially low
    (tmp_backlog / "task-100 - h.md").write_text("---\nid: 100\ntitle: h\n---\n")
    # Counter says 3, but scan says 100. Next reservation must beat both.
    assert reserve_id(root=tmp_backlog) == 101
    assert counter_file.read_text().strip() == "101"


def test_counter_file_corrupt_payload_treated_as_zero(tmp_backlog: Path) -> None:
    """Garbled counter file (e.g., partial write from crash) → treated as 0;
    scan_ids reconciliation prevents data loss."""
    counter_file = tmp_backlog / ".next_id_counter"
    counter_file.write_text("not-a-number\n\x00")
    (tmp_backlog / "task-50 - k.md").write_text("---\nid: 50\ntitle: k\n---\n")
    assert reserve_id(root=tmp_backlog) == 51


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
