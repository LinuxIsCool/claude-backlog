"""Canonical venture resolution for historical Backlog vocabulary.

Backlog owns the raw task record and exposes this non-destructive resolution
overlay. Ventures consumes the canonical reference; migrations may later
rewrite proven aliases while preserving ``venture_previous`` provenance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class VentureResolution:
    raw: str | None
    canonical: str | None
    status: str
    program: str | None = None
    project: str | None = None
    rule: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


_LEGION_ALIASES: dict[str, tuple[str | None, str | None]] = {
    "legion": (None, None),
    "legion-platform": ("legion-platform", None),
    "legion-infra": ("runtime-infrastructure", None),
    "legion-systems": ("operating-rhythms", "claude-rhythms"),
    "legion-internal": ("governance-doctrine", None),
    "infrastructure": ("runtime-infrastructure", None),
    "legion (infrastructure)": ("runtime-infrastructure", None),
    "longtail financial / legion infrastructure": ("legion-platform", None),
    "claude-dock": ("legion-platform", "claude-dock"),
}


def resolve_venture(raw: str | None, *, project: str | None = None) -> VentureResolution:
    value = str(raw or "").strip()
    if not value:
        return VentureResolution(raw=None, canonical=None, status="missing")
    key = value.casefold()
    mapped = _LEGION_ALIASES.get(key)
    if mapped is not None:
        program, default_project = mapped
        return VentureResolution(
            raw=value, canonical="legion", status="resolved",
            program=program, project=project or default_project,
            rule="legion-historical-alias-v1" if value != "legion" else "canonical",
        )
    return VentureResolution(
        raw=value, canonical=value, status="unverified", project=project,
        rule="identity-fallback",
    )

