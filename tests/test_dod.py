"""Unit tests for claude_backlog.dod."""

from __future__ import annotations

import pytest

from claude_backlog.dod import (
    check_ac_item,
    check_dod_item,
    count_items,
    inherit_defaults,
    items_status,
    uncheck_ac_item,
    uncheck_dod_item,
)
from claude_backlog.errors import BacklogToolError, ErrorCode
from claude_backlog.schema import Config


# --- inherit_defaults -------------------------------------------------------


def test_inherit_defaults_enabled() -> None:
    cfg = Config(
        definition_of_done=["item one", "item two"],
        auto_inherit_dod=True,
    )
    assert inherit_defaults(cfg) == ["item one", "item two"]


def test_inherit_defaults_disabled() -> None:
    cfg = Config(
        definition_of_done=["item one"],
        auto_inherit_dod=False,
    )
    assert inherit_defaults(cfg) == []


def test_inherit_defaults_returns_copy() -> None:
    """Mutating the returned list must not affect the config."""
    cfg = Config(definition_of_done=["x"], auto_inherit_dod=True)
    out = inherit_defaults(cfg)
    out.append("y")
    assert cfg.definition_of_done == ["x"]


# --- AC / DoD checkbox manipulation ----------------------------------------

_BODY_WITH_BOTH = (
    "\n## Acceptance Criteria\n\n"
    "- [ ] First criterion\n"
    "- [ ] Second criterion\n"
    "- [ ] Third criterion\n"
    "\n## Definition of Done\n\n"
    "- [ ] Acceptance criteria met\n"
    "- [ ] Tests written\n"
    "- [ ] Documentation updated\n"
)


def test_check_dod_item_index_1(sample_task) -> None:
    sample_task.body = _BODY_WITH_BOTH
    updated = check_dod_item(sample_task, 1)
    items = items_status(updated, "dod")
    assert items[0] == ("Acceptance criteria met", True)
    assert items[1] == ("Tests written", False)


def test_check_dod_item_index_last(sample_task) -> None:
    sample_task.body = _BODY_WITH_BOTH
    updated = check_dod_item(sample_task, 3)
    items = items_status(updated, "dod")
    assert items[2] == ("Documentation updated", True)


def test_check_then_uncheck_roundtrip(sample_task) -> None:
    sample_task.body = _BODY_WITH_BOTH
    checked = check_dod_item(sample_task, 2)
    unchecked = uncheck_dod_item(checked, 2)
    # Round-trip: body content should match original
    assert items_status(unchecked, "dod")[1] == ("Tests written", False)


def test_check_ac_item_independent_of_dod(sample_task) -> None:
    sample_task.body = _BODY_WITH_BOTH
    updated = check_ac_item(sample_task, 2)
    ac_items = items_status(updated, "ac")
    dod_items = items_status(updated, "dod")
    assert ac_items[1] == ("Second criterion", True)
    # DoD must NOT have been touched
    assert all(not checked for _, checked in dod_items)


def test_check_dod_out_of_range_raises(sample_task) -> None:
    sample_task.body = _BODY_WITH_BOTH
    with pytest.raises(BacklogToolError) as exc_info:
        check_dod_item(sample_task, 99)
    assert exc_info.value.code == ErrorCode.DOD_INVALID


def test_check_ac_out_of_range_raises(sample_task) -> None:
    sample_task.body = _BODY_WITH_BOTH
    with pytest.raises(BacklogToolError) as exc_info:
        check_ac_item(sample_task, 0)  # 1-based — index 0 invalid
    assert exc_info.value.code == ErrorCode.AC_INVALID


def test_check_dod_no_section_raises(sample_task) -> None:
    sample_task.body = "\n## Acceptance Criteria\n\n- [ ] One\n"
    with pytest.raises(BacklogToolError) as exc_info:
        check_dod_item(sample_task, 1)
    assert exc_info.value.code == ErrorCode.DOD_INVALID


def test_check_ac_no_section_raises(sample_task) -> None:
    sample_task.body = "\n## Definition of Done\n\n- [ ] One\n"
    with pytest.raises(BacklogToolError) as exc_info:
        check_ac_item(sample_task, 1)
    assert exc_info.value.code == ErrorCode.AC_INVALID


# --- count_items + items_status --------------------------------------------


def test_count_items(sample_task) -> None:
    sample_task.body = _BODY_WITH_BOTH
    assert count_items(sample_task, "ac") == 3
    assert count_items(sample_task, "dod") == 3


def test_count_items_no_section(sample_task) -> None:
    sample_task.body = "no checklists here"
    assert count_items(sample_task, "ac") == 0
    assert count_items(sample_task, "dod") == 0


def test_items_status_mixed(sample_task) -> None:
    sample_task.body = (
        "\n## Acceptance Criteria\n\n"
        "- [x] Done one\n"
        "- [ ] Not done\n"
        "- [X] Done two (upper-case x)\n"
    )
    items = items_status(sample_task, "ac")
    assert items == [
        ("Done one", True),
        ("Not done", False),
        ("Done two (upper-case x)", True),
    ]


def test_items_status_alt_header_case(sample_task) -> None:
    """Lower-case header variant should still match."""
    sample_task.body = (
        "\n## acceptance criteria\n\n"
        "- [ ] only item\n"
    )
    items = items_status(sample_task, "ac")
    assert items == [("only item", False)]


def test_checkboxes_outside_section_are_ignored(sample_task) -> None:
    """Checkboxes in prose / other sections must not count toward the section."""
    sample_task.body = (
        "\n## Acceptance Criteria\n\n"
        "- [ ] inside\n"
        "\n## Notes\n\n"
        "- [ ] not-counted-1\n"
        "- [ ] not-counted-2\n"
    )
    assert count_items(sample_task, "ac") == 1
