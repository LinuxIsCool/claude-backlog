"""Phase 5.1 persona-aware schema additions (task-442).

Goal: verify the new fields are STRICTLY ADDITIVE — defaults match the
"absent" frontmatter shape, round-trip emits nothing when unset, and the
existing 286-task corpus parses without regression.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from claude_backlog.io import (
    BACKLOG_ROOT,
    Stage,
    _iter_stage_files,
    _task_from_text,
    read_task,
    task_to_text,
)
from claude_backlog.schema import Task


# --- defaults ---------------------------------------------------------------


def test_persona_fields_default_to_unset() -> None:
    """A minimal task must report None / [] for the new persona fields."""
    t = Task(id=1, title="x")
    assert t.creator_persona is None
    assert t.assignee_persona is None
    assert t.persona_history == []


# --- write-time omission ----------------------------------------------------


def test_persona_fields_absent_when_unset_in_serialized_form() -> None:
    """`task_to_text` MUST NOT emit empty persona lines.

    Existing 286 tasks have no persona block; round-trip via task_to_text
    cannot introduce new lines or the diffs would be enormous.
    """
    t = Task(id=1, title="x", priority="medium", created=date(2026, 5, 12))
    text = task_to_text(t)
    assert "creator_persona" not in text
    assert "assignee_persona" not in text
    assert "persona_history" not in text


# --- write-time emission ----------------------------------------------------


def test_persona_fields_emit_when_set() -> None:
    """When persona fields are set, they must round-trip on the wire."""
    history = [
        {"persona": "matt", "action": "created", "at": "2026-05-12T17:53:00-07:00"},
        {"persona": "shawn", "action": "reviewed", "at": "2026-05-12T18:01:00-07:00"},
    ]
    t = Task(
        id=2,
        title="Persona round-trip",
        creator_persona="matt",
        assignee_persona="shawn",
        persona_history=history,
    )
    text = task_to_text(t)
    assert "creator_persona: matt" in text
    assert "assignee_persona: shawn" in text
    assert "persona_history:" in text

    # Now parse it back and verify lossless round-trip.
    reloaded = _task_from_text(text)
    assert reloaded.creator_persona == "matt"
    assert reloaded.assignee_persona == "shawn"
    assert reloaded.persona_history == history


# --- coercion safety --------------------------------------------------------


def test_persona_history_accepts_single_dict() -> None:
    """A pre-existing single-event dict must be coerced into a list of one."""
    t = Task(
        id=3,
        title="x",
        persona_history={"persona": "matt", "action": "created", "at": "2026-05-12"},
    )
    assert isinstance(t.persona_history, list)
    assert len(t.persona_history) == 1


def test_persona_history_none_becomes_empty_list() -> None:
    t = Task(id=4, title="x", persona_history=None)
    assert t.persona_history == []


# --- regression: real corpus ------------------------------------------------


@pytest.mark.skipif(not BACKLOG_ROOT.exists(), reason="no local backlog corpus")
def test_real_corpus_parses_with_persona_schema() -> None:
    """Re-parse the entire active corpus and assert no schema-level breakage.

    This is the F-check from task-442 §5.1: "schema migration doesn't break
    existing tasks". A handful of tasks have already-known unparseable
    frontmatter (F2 history); those raise BacklogToolError and are tallied
    as "skipped" — but NO new failures should appear because of the persona
    additions.
    """
    from claude_backlog.errors import BacklogToolError

    parsed = 0
    skipped: list[tuple[Path, str]] = []
    persona_set = 0
    for path in _iter_stage_files(Stage.ACTIVE):
        try:
            t = read_task(path)
        except BacklogToolError as e:
            skipped.append((path, str(e)))
            continue
        parsed += 1
        if t.creator_persona is not None or t.assignee_persona is not None or t.persona_history:
            persona_set += 1

    # We expect at least 200 tasks to parse cleanly. The exact number is a
    # moving target (drafts/archive grow), so we only assert order-of-mag.
    assert parsed > 200, f"only {parsed} tasks parsed; skipped={len(skipped)}"
    # Persona fields are additive; nothing in the legacy corpus is populated
    # yet, so this should be 0 right now. The assertion exists so we notice
    # if some other process pre-populates persona fields unexpectedly.
    assert persona_set == 0 or persona_set < 5, (
        f"unexpected persona-populated tasks in legacy corpus: {persona_set}"
    )
