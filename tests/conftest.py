"""Shared pytest fixtures for claude-backlog tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from claude_backlog.schema import Config, Task


@pytest.fixture()
def tmp_backlog(tmp_path: Path) -> Path:
    """Empty backlog root with active/, drafts/, archive/ scaffolding."""
    (tmp_path / "drafts").mkdir()
    (tmp_path / "archive").mkdir()
    return tmp_path


@pytest.fixture()
def sample_task() -> Task:
    """A canonical Task model for round-trip tests."""
    return Task(
        id=1,
        title="Sample task",
        status="To Do",
        priority="high",
        created=date(2026, 5, 12),
        tags=["sample", "phase-4"],
        definition_of_done=[
            "Acceptance criteria met",
            "Tests written or updated",
        ],
        body="\n## Acceptance Criteria\n\n- [ ] First criterion\n- [ ] Second criterion\n\n## Definition of Done\n\n- [ ] Acceptance criteria met\n- [ ] Tests written or updated\n",
    )


@pytest.fixture()
def sample_config() -> Config:
    """A canonical Config model matching ~/.claude/local/backlog/config.yml."""
    return Config(
        statuses=["To Do", "In Progress", "Blocked", "Done"],
        priorities=["low", "medium", "high", "critical"],
        definition_of_done=[
            "Acceptance criteria met",
            "Tests written or updated (if code path touched)",
            "Documentation updated if needed",
        ],
        auto_inherit_dod=True,
    )
