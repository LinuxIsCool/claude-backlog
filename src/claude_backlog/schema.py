"""Pydantic models for claude-backlog Task / Draft / Config.

Mirrors the frontmatter contract documented in plugin CLAUDE.md
"Frontmatter Contract" + skill SKILL.md "Task Frontmatter Schema".

All Phase 1 additive fields (modified_files, ordinal, parent_task,
documentation, on_status_change, definition_of_done) are `Optional[...]`
so existing 286+ tasks parse cleanly.

Unknown frontmatter keys (e.g., `_pipeline` enrichment block) are preserved
in `extra_frontmatter` so write_task round-trips without data loss.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Priority = Literal["critical", "high", "medium", "low"]

_STR_ID_RE = re.compile(r"^(?:task[-_]?)?(\d+)", re.IGNORECASE)


class Task(BaseModel):
    """Canonical task frontmatter + body.

    All required fields match the existing 286+ tasks. Optional fields are
    `None` by default. Pre-existing extra fields (e.g., `intent`,
    `expected_impact`, `_pipeline`) round-trip via `extra_frontmatter`.
    """

    model_config = ConfigDict(extra="ignore")

    # --- Required ---
    id: int
    title: str
    status: str = "To Do"
    priority: Priority = "medium"
    created: date = Field(default_factory=date.today)

    @field_validator("priority", mode="before")
    @classmethod
    def _coerce_priority(cls, v: Any) -> Any:
        """Default invalid/missing priority to 'medium' (matches hook behavior)."""
        valid = {"critical", "high", "medium", "low"}
        if v is None:
            return "medium"
        if isinstance(v, str) and v.lower() in valid:
            return v.lower()
        return v  # let Pydantic raise on truly bad input

    @field_validator("created", "due", mode="before")
    @classmethod
    def _coerce_date(cls, v: Any) -> Any:
        """Accept date, datetime (PyYAML converts `YYYY-MM-DD HH:MM:SS`), ISO string, or None."""
        if v is None or v == "":
            return None
        if isinstance(v, datetime):
            return v.date()
        return v

    @field_validator("created", mode="after")
    @classmethod
    def _fill_created(cls, v: date | None) -> date:
        """`created` must end as a real date — fall back to today."""
        return v or date.today()

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, v: Any) -> Any:
        """Default missing status to 'To Do'."""
        if v is None or v == "":
            return "To Do"
        return v

    @field_validator(
        "tags",
        "depends_on",
        "blocks",
        "modified_files",
        "documentation",
        "definition_of_done",
        mode="before",
    )
    @classmethod
    def _coerce_list(cls, v: Any) -> Any:
        """Accept single value, list, or None for list-typed fields.

        Real-world data has `depends_on: 'task-010'` (string) in 1 task.
        Treat as a single-element list.
        """
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("depends_on", "blocks", mode="before")
    @classmethod
    def _coerce_task_id_list(cls, v: Any) -> Any:
        """Coerce list of mixed int / 'task-NNN' string IDs to list[int]."""
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            return v
        out: list[int] = []
        for item in v:
            if isinstance(item, int):
                out.append(item)
            elif isinstance(item, str):
                m = _STR_ID_RE.match(item)
                if m:
                    out.append(int(m.group(1)))
                else:
                    # silently drop unparseable refs rather than fail the whole task
                    continue
        return out

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v: Any) -> Any:
        """Accept int OR legacy string IDs of form 'task-NNN' / 'task-NN-suffix'.

        Real-world data audit (286 active tasks, 2026-05-12):
        - 153 tasks: int IDs
        - 117 tasks: string 'task-NNN'
        - 14 tasks: id missing entirely (caller must supply via filename)
        - 1 task:  string with suffix like 'task-401-v1-archive'
        """
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            m = _STR_ID_RE.match(v)
            if m:
                return int(m.group(1))
        return v  # let Pydantic surface the error if still wrong

    # --- Canonical optional ---
    milestone: str | int | None = None
    tags: list[str] = Field(default_factory=list)
    estimated_hours: float | None = None
    depends_on: list[int] = Field(default_factory=list)
    blocks: list[int] = Field(default_factory=list)
    effort: str | None = None
    due: date | None = None
    venture: str | None = None

    # --- Phase 1 additive ---
    modified_files: list[str] = Field(default_factory=list)
    ordinal: int | None = None
    parent_task: int | None = None
    documentation: list[str] = Field(default_factory=list)
    on_status_change: str | None = None
    definition_of_done: list[str] = Field(default_factory=list)

    # --- Round-trip safety: everything else from frontmatter ---
    extra_frontmatter: dict[str, Any] = Field(default_factory=dict)

    # --- Body (markdown after second `---`) ---
    body: str = ""

    @property
    def is_done(self) -> bool:
        return self.status.lower() in {"done", "cancelled"}


class Draft(Task):
    """A task in `drafts/` stage. Status is conventionally `draft`."""

    status: str = "draft"


class Config(BaseModel):
    """Project config from `~/.claude/local/backlog/config.yml`."""

    model_config = ConfigDict(extra="allow")

    statuses: list[str] = Field(default_factory=lambda: ["To Do", "In Progress", "Blocked", "Done"])
    priorities: list[str] = Field(default_factory=lambda: ["low", "medium", "high", "critical"])
    definition_of_done: list[str] = Field(default_factory=list)
    auto_inherit_dod: bool = True
    default_assignee: str | None = None
    next_id: int | None = None
    ventures_path: str | None = None
    journal_path: str | None = None
    auto_archive_done: bool = False
    archive_after_days: int | None = None
    default_view: str = "priority"
    tasks_per_page: int = 20
