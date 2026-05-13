"""Persona attribution as a CROSS-CUTTING concern (post-pivot, 2026-05-12).

After the architecture pivot (claude-webui cluster-shell adoption), persona
attribution is owned by claude-personas overlay, NOT by the Task schema.

This test suite is the contract that:
  1. Persona keys in a task's frontmatter MUST round-trip cleanly (via
     `extra_frontmatter`) — they are not lost, not validated, not typed
     by claude-backlog. claude-personas reads/writes them externally.
  2. Tasks WITHOUT persona keys continue to round-trip with zero churn.
  3. The 286-task corpus parses without regression.

If any of these tests fail, the cross-cutting overlay contract is broken —
investigate before merging.
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


# --- baseline: persona keys are NOT typed on Task ---------------------------


def test_persona_keys_not_typed_on_task() -> None:
    """Task model MUST NOT declare creator_persona / assignee_persona /
    persona_history as typed fields. They live in the overlay layer."""
    fields = Task.model_fields
    assert "creator_persona" not in fields
    assert "assignee_persona" not in fields
    assert "persona_history" not in fields


# --- overlay round-trip: persona keys flow via extra_frontmatter ------------


def test_persona_keys_round_trip_via_extra_frontmatter() -> None:
    """A task whose frontmatter carries persona keys MUST round-trip them
    unchanged. claude-personas owns the semantics; claude-backlog only
    guarantees the bytes survive."""
    fm_text = (
        "---\n"
        "id: 9001\n"
        "title: Persona overlay round-trip\n"
        "status: To Do\n"
        "priority: high\n"
        "created: 2026-05-12\n"
        "creator_persona: matt\n"
        "assignee_persona: shawn\n"
        "persona_history:\n"
        "  - persona: matt\n"
        "    action: created\n"
        "    at: '2026-05-12T17:53:00-07:00'\n"
        "  - persona: shawn\n"
        "    action: reviewed\n"
        "    at: '2026-05-12T18:01:00-07:00'\n"
        "---\n"
        "Body.\n"
    )
    t = _task_from_text(fm_text)
    # Persona keys land in extra_frontmatter — round-trip safe.
    assert t.extra_frontmatter.get("creator_persona") == "matt"
    assert t.extra_frontmatter.get("assignee_persona") == "shawn"
    history = t.extra_frontmatter.get("persona_history")
    assert isinstance(history, list)
    assert len(history) == 2
    assert history[0]["persona"] == "matt"
    assert history[0]["action"] == "created"

    # Re-serialize and assert the persona block is still present.
    out = task_to_text(t)
    assert "creator_persona: matt" in out
    assert "assignee_persona: shawn" in out
    assert "persona_history:" in out
    assert "action: created" in out
    assert "action: reviewed" in out


# --- absence guarantee: tasks without persona keys emit nothing extra -------


def test_minimal_task_emits_no_persona_block() -> None:
    """A bare Task without persona keys must round-trip without introducing
    any persona-related lines. The 286-task corpus relies on this for
    diff-clean read-modify-write cycles."""
    t = Task(id=1, title="x", priority="medium", created=date(2026, 5, 12))
    out = task_to_text(t)
    assert "creator_persona" not in out
    assert "assignee_persona" not in out
    assert "persona_history" not in out


# --- regression: real corpus ------------------------------------------------


@pytest.mark.skipif(not BACKLOG_ROOT.exists(), reason="no local backlog corpus")
def test_real_corpus_parses_after_pivot() -> None:
    """Re-parse the entire active corpus and assert no schema-level breakage
    introduced by removing the persona fields. (They were additive in 5.1,
    and 0 of 286 tasks ever had them populated, so reverting is also free.)"""
    from claude_backlog.errors import BacklogToolError

    parsed = 0
    skipped: list[tuple[Path, str]] = []
    persona_in_extras = 0
    for path in _iter_stage_files(Stage.ACTIVE):
        try:
            t = read_task(path)
        except BacklogToolError as e:
            skipped.append((path, str(e)))
            continue
        parsed += 1
        if (
            "creator_persona" in t.extra_frontmatter
            or "assignee_persona" in t.extra_frontmatter
            or "persona_history" in t.extra_frontmatter
        ):
            persona_in_extras += 1

    assert parsed > 200, f"only {parsed} tasks parsed; skipped={len(skipped)}"
    # No legacy tasks had persona keys populated. Nothing leaks into extras.
    assert persona_in_extras == 0, (
        f"unexpected persona overlay data in corpus: {persona_in_extras}"
    )
