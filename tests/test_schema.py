"""Unit tests for claude_backlog.schema.

Field-validator coverage focuses on the real-world failure modes audited
on 2026-05-12 across 286 active tasks.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from claude_backlog.schema import Config, Task


# --- id coercion ------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_id, expected",
    [
        (3, 3),
        ("task-003", 3),
        ("task_003", 3),
        ("task-401-v1-archive", 401),
        ("401-v1-archive", 401),
    ],
)
def test_id_coercion(raw_id, expected) -> None:
    t = Task(id=raw_id, title="x")
    assert t.id == expected


def test_id_unparseable_raises() -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Task(id="not-a-task", title="x")


# --- priority coercion ------------------------------------------------------


def test_priority_default() -> None:
    t = Task(id=1, title="x")
    assert t.priority == "medium"


def test_priority_uppercase_lowered() -> None:
    t = Task(id=1, title="x", priority="HIGH")
    assert t.priority == "high"


def test_priority_invalid_raises() -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Task(id=1, title="x", priority="urgent")


# --- date coercion ----------------------------------------------------------


def test_created_default_today() -> None:
    t = Task(id=1, title="x")
    assert t.created == date.today()


def test_created_from_datetime() -> None:
    """PyYAML parses `created: 2026-03-09 22:30:00` as a datetime."""
    t = Task(id=1, title="x", created=datetime(2026, 3, 9, 22, 30))
    assert t.created == date(2026, 3, 9)


def test_due_from_datetime() -> None:
    t = Task(id=1, title="x", due=datetime(2026, 6, 1, 9, 0))
    assert t.due == date(2026, 6, 1)


def test_due_empty_string_becomes_none() -> None:
    t = Task(id=1, title="x", due="")
    assert t.due is None


# --- status coercion --------------------------------------------------------


def test_status_default() -> None:
    t = Task(id=1, title="x")
    assert t.status == "To Do"


def test_status_explicit() -> None:
    t = Task(id=1, title="x", status="In Progress")
    assert t.status == "In Progress"


def test_status_none_falls_back() -> None:
    t = Task(id=1, title="x", status=None)
    assert t.status == "To Do"


# --- list coercion ----------------------------------------------------------


def test_depends_on_single_string_becomes_list() -> None:
    """task-022 has `depends_on: 'task-010'` in the wild — coerce to [10]."""
    t = Task(id=22, title="x", depends_on="task-010")
    assert t.depends_on == [10]


def test_depends_on_mixed_int_string_list() -> None:
    t = Task(id=1, title="x", depends_on=[5, "task-7", "task-009"])
    assert t.depends_on == [5, 7, 9]


def test_depends_on_drops_unparseable() -> None:
    t = Task(id=1, title="x", depends_on=[5, "garbage"])
    assert t.depends_on == [5]


def test_tags_single_string_becomes_list() -> None:
    t = Task(id=1, title="x", tags="single")
    assert t.tags == ["single"]


def test_definition_of_done_default_empty() -> None:
    t = Task(id=1, title="x")
    assert t.definition_of_done == []


# --- extra_frontmatter round-trip ------------------------------------------


def test_extra_frontmatter_default() -> None:
    t = Task(id=1, title="x")
    assert t.extra_frontmatter == {}


def test_extra_frontmatter_preserves_unknown_keys() -> None:
    t = Task(
        id=1,
        title="x",
        extra_frontmatter={"intent": "do the thing", "_pipeline": {"foo": "bar"}},
    )
    assert t.extra_frontmatter["intent"] == "do the thing"
    assert t.extra_frontmatter["_pipeline"] == {"foo": "bar"}


# --- is_done helper ---------------------------------------------------------


@pytest.mark.parametrize(
    "status, expected",
    [
        ("To Do", False),
        ("In Progress", False),
        ("Done", True),
        ("done", True),
        ("Cancelled", True),
        ("cancelled", True),
        ("Blocked", False),
    ],
)
def test_is_done(status: str, expected: bool) -> None:
    t = Task(id=1, title="x", status=status)
    assert t.is_done is expected


# --- Config -----------------------------------------------------------------


def test_config_defaults() -> None:
    cfg = Config()
    assert cfg.auto_inherit_dod is True
    assert "low" in cfg.priorities
    assert "high" in cfg.priorities
    assert "To Do" in cfg.statuses
    assert "Done" in cfg.statuses


def test_config_extra_allowed() -> None:
    """Config has extra='allow' — unknown keys should round-trip."""
    cfg = Config.model_validate({"definition_of_done": ["a"], "custom_field": "hello"})
    assert cfg.definition_of_done == ["a"]
    # custom_field should be accessible since extra=allow
    assert getattr(cfg, "custom_field", None) == "hello"


# --- real-world snapshot coverage ------------------------------------------


def test_legacy_string_id_realworld() -> None:
    """One of the 117 tasks in the real backlog uses string `task-022`."""
    t = Task(id="task-022", title="x")
    assert t.id == 22


def test_completely_minimal_task() -> None:
    """A task with only id + title must validate (real-world: 14 tasks lack
    most fields). All other fields use defaults."""
    t = Task(id=999, title="bare")
    assert t.id == 999
    assert t.status == "To Do"
    assert t.priority == "medium"
    assert t.created == date.today()
    assert t.definition_of_done == []
