#!/usr/bin/env python3
"""Migrate reviewed Legion venture aliases without reserializing task bodies."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from claude_backlog.venture_resolution import resolve_venture

VENTURE_LINE = re.compile(r"^(venture:\s*)(.*)$", re.MULTILINE)


def _scalar(value: str) -> str:
    return yaml.safe_dump(value, default_flow_style=True).strip().removesuffix("...").strip()


def migrate(path: Path, *, apply: bool) -> dict | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    try:
        metadata = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None  # corpus audit owns malformed YAML; this migration is narrow
    raw = metadata.get("venture")
    resolution = resolve_venture(raw, project=metadata.get("project"))
    if resolution.canonical != "legion" or resolution.rule == "canonical":
        return None
    match = VENTURE_LINE.search(parts[1])
    if not match:
        return None
    frontmatter = VENTURE_LINE.sub(r"\1legion", parts[1], count=1)
    additions = []
    if "venture_previous" not in metadata:
        additions.append(f"venture_previous: {_scalar(str(raw))}")
    if "venture_resolution_rule" not in metadata:
        additions.append(f"venture_resolution_rule: {resolution.rule}")
    if resolution.program and "program" not in metadata:
        additions.append(f"program: {resolution.program}")
    if resolution.project and "project" not in metadata:
        additions.append(f"project: {resolution.project}")
    if additions:
        frontmatter = frontmatter.rstrip() + "\n" + "\n".join(additions) + "\n"
    updated = f"---{frontmatter}---{parts[2]}"
    if apply:
        path.write_text(updated, encoding="utf-8")
    return {
        "path": str(path), "previous": raw, "venture": "legion",
        "program": resolution.program, "project": resolution.project,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.home() / ".claude/local/backlog")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    changes = [change for path in sorted(args.root.glob("*.md"))
               if (change := migrate(path, apply=args.apply))]
    for change in changes:
        print(f"{change['previous']} -> legion\t{change['path']}")
    print(f"mode={'apply' if args.apply else 'dry-run'} changed={len(changes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
