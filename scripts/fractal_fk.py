"""Fractal FK validator — resolves a (parent_id, parent_type) tuple against
the filesystem layout owned by claude-ventures.

Python mirror of claude-ventures/src/validation/fk.ts. Both must agree on:
- STAGE_DIRS list and order
- Composite slug grammar (^[a-z0-9][a-z0-9-]*$, max 3 segments)
- Path layout for venture/project/milestone .md files
- Error message prefixes (used by tests via substring match)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ParentType = Literal["venture", "project", "milestone"]
VALID_TYPES: set[str] = {"venture", "project", "milestone"}
STAGE_DIRS: tuple[str, ...] = (
    "active", "exploring", "seed", "sustaining", "dormant", "harvesting",
)
SLUG_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class FKResult:
    ok: bool
    error: str = ""
    resolved_path: str = ""


def _is_valid_segment(s: str) -> bool:
    return bool(SLUG_SEGMENT_RE.match(s))


def _parse_composite(slug: str) -> tuple[str, ...]:
    """Returns (venture,), (venture, project), or (venture, project, milestone).
    Raises ValueError on bad input. Mirrors parseCompositeSlug in TS."""
    if not slug:
        raise ValueError("empty composite slug")
    parts = slug.split(".")
    if len(parts) > 3:
        raise ValueError(f"too many segments in {slug!r}")
    for seg in parts:
        if not _is_valid_segment(seg):
            raise ValueError(f"invalid slug segment {seg!r} in {slug!r}")
    return tuple(parts)


class FractalFKValidator:
    """Resolves composite-slug FKs against the claude-ventures filesystem."""

    def __init__(self, ventures_root: Path) -> None:
        self.ventures_root = Path(ventures_root)

    def resolve(self, parent_id: str, parent_type: str) -> FKResult:
        if parent_type not in VALID_TYPES:
            return FKResult(ok=False, error=f"invalid parent_type {parent_type!r}")

        try:
            parts = _parse_composite(parent_id)
        except ValueError as e:
            return FKResult(ok=False, error=str(e))

        level = ("venture", "project", "milestone")[len(parts) - 1]
        if level != parent_type:
            return FKResult(
                ok=False,
                error=f"level mismatch: parent_id {parent_id!r} is {level}, but parent_type is {parent_type}",
            )

        if parent_type == "venture":
            (venture,) = parts
            for stage in STAGE_DIRS:
                p = self.ventures_root / stage / f"{venture}.md"
                if p.exists():
                    return FKResult(ok=True, resolved_path=str(p))
            return FKResult(ok=False, error=f"venture {venture!r} not found in any stage dir")

        if parent_type == "project":
            venture, project = parts
            p = self.ventures_root / venture / "projects" / project / "project.md"
            if p.exists():
                return FKResult(ok=True, resolved_path=str(p))
            return FKResult(ok=False, error=f"project {venture}.{project} not found")

        # milestone
        venture, project, milestone = parts
        p = (
            self.ventures_root / venture / "projects" / project
            / "milestones" / f"{milestone}.md"
        )
        if p.exists():
            return FKResult(ok=True, resolved_path=str(p))
        return FKResult(ok=False, error=f"milestone {venture}.{project}.{milestone} not found")
