"""Read-only audit of task identity integrity in a Backlog corpus."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


_CANONICAL_RE = re.compile(r"^task-(\d+)(?:\s*-\s*(.*))?\.md$")
_LEGACY_RE = re.compile(r"^(\d{1,})\s*-\s*(?!\d{2}-\d{2})(.*)\.md$")


@dataclass(frozen=True)
class IdentityRecord:
    path: str
    filename_id: str | None
    frontmatter_id: str | None
    filename_shape: str
    parse_status: str
    parse_error: str | None
    venture: str | None


def _filename_identity(name: str) -> tuple[str | None, str]:
    if match := _CANONICAL_RE.match(name):
        return match.group(1), "canonical"
    if match := _LEGACY_RE.match(name):
        return match.group(1), "legacy"
    return None, "unrecognized"


def _frontmatter(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if not text.startswith("---"):
        return {}, "missing YAML frontmatter"
    end = text.find("\n---", 3)
    if end == -1:
        return {}, "unterminated YAML frontmatter"
    try:
        parsed = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(parsed, dict):
        return {}, "YAML frontmatter is not a mapping"
    return parsed, None


def audit(root: Path) -> dict[str, Any]:
    """Return a deterministic, JSON-serializable identity audit for ``root``."""
    records: list[IdentityRecord] = []
    filename_claimants: dict[str, list[str]] = defaultdict(list)
    frontmatter_claimants: dict[str, list[str]] = defaultdict(list)

    for path in sorted(root.glob("*.md"), key=lambda item: item.name):
        filename_id, filename_shape = _filename_identity(path.name)
        frontmatter, error = _frontmatter(path)
        raw_id = frontmatter.get("id") if not error else None
        frontmatter_id = str(raw_id) if raw_id not in (None, "") else None
        venture_raw = frontmatter.get("venture") if not error else None
        venture = str(venture_raw) if venture_raw not in (None, "") else None
        record = IdentityRecord(
            path=path.name,
            filename_id=filename_id,
            frontmatter_id=frontmatter_id,
            filename_shape=filename_shape,
            parse_status="failed" if error else "parsed",
            parse_error=error,
            venture=venture,
        )
        records.append(record)
        if filename_id is not None:
            filename_claimants[filename_id].append(path.name)
        if frontmatter_id is not None:
            frontmatter_claimants[frontmatter_id].append(path.name)

    contested_filenames = {
        task_id: paths
        for task_id, paths in sorted(filename_claimants.items())
        if len(paths) > 1
    }
    contested_frontmatter = {
        task_id: paths
        for task_id, paths in sorted(frontmatter_claimants.items())
        if len(paths) > 1
    }
    disagreements = [
        record
        for record in records
        if record.filename_id is not None
        and record.frontmatter_id is not None
        and record.filename_id != record.frontmatter_id
    ]
    parse_failures = [record for record in records if record.parse_status == "failed"]
    unaddressable = [record for record in records if record.frontmatter_id is None]
    no_filename_id = [record for record in records if record.filename_id is None]
    venture_null = [
        record
        for record in records
        if record.parse_status == "parsed" and record.venture is None
    ]

    return {
        "schema_version": 1,
        "root": str(root.resolve()),
        "counts": {
            "files_scanned": len(records),
            "frontmatter_parsed": len(records) - len(parse_failures),
            "parse_failed": len(parse_failures),
            "filename_id_missing": len(no_filename_id),
            "frontmatter_id_missing": len(unaddressable),
            "filename_frontmatter_disagreements": len(disagreements),
            "contested_filename_ids": len(contested_filenames),
            "files_claiming_contested_filename_ids": sum(
                len(paths) for paths in contested_filenames.values()
            ),
            "contested_frontmatter_ids": len(contested_frontmatter),
            "files_claiming_contested_frontmatter_ids": sum(
                len(paths) for paths in contested_frontmatter.values()
            ),
            "venture_null": len(venture_null),
        },
        "filename_shapes": dict(sorted(Counter(r.filename_shape for r in records).items())),
        "parse_failures": [asdict(record) for record in parse_failures],
        "missing_filename_ids": [asdict(record) for record in no_filename_id],
        "missing_frontmatter_ids": [asdict(record) for record in unaddressable],
        "identity_disagreements": [asdict(record) for record in disagreements],
        "contested_filename_ids": contested_filenames,
        "contested_frontmatter_ids": contested_frontmatter,
    }
