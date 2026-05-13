"""Dedupe colliding task IDs in the claude-backlog corpus — task-447 A2.

Symptom: prior next_id() raced under concurrent multi-agent activity,
producing 37 distinct task IDs each with TWO files on disk (different
slugs, same numeric ID). MiniSearch in the satellite UI errored with
"duplicate ID 217" and any cross-ref that referenced an ambiguous ID
resolved to whichever file find_task() iterated first.

Strategy:
  - Older mtime KEEPS the colliding ID. Older = earlier creator wins.
  - Newer file gets a freshly reserved ID via reserve_id() (atomic).
  - File renamed: `task-{NEW_ID} - {original_slug}.md` (slug preserved).
  - YAML frontmatter `id:` field updated to NEW_ID.
  - Body text is left intact (no auto-rewrite of `task-OLDID` mentions
    inside prose — those are surfaced in the report for manual review).
  - Cross-refs (`depends_on`, `blocks`, `parent_task`) in OTHER tasks
    are NOT rewritten because today they ALL resolve to the older file
    (the one keeping the ID). Dedupe makes the ambiguity vanish without
    making any existing reference worse.

Modes:
  --dry-run  (default)  print planned actions; no filesystem changes
  --apply               execute the migration; archive a JSON log

Usage (from plugin root):
  uv run python scripts/dedupe_collisions.py
  uv run python scripts/dedupe_collisions.py --apply
  uv run python scripts/dedupe_collisions.py --root /tmp/test-corpus

Note: the script is idempotent — running --apply on a clean corpus is
a no-op and prints `COLLISIONS: 0`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Walking up two dirs to find the src/ tree; allow running both as a
# module (`python -m claude_backlog.scripts...`) and as a script.
_SCRIPT_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = _SCRIPT_DIR.parent
_SRC = _PLUGIN_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from claude_backlog.io import (  # noqa: E402  — after sys.path injection
    BACKLOG_ROOT,
    Stage,
    reserve_id,
)

_FILENAME_RE = re.compile(r"^task-(\d+)(?:\s*-\s*(.*))?\.md$")


def _stage_dirs(root: Path) -> list[Path]:
    """Active, drafts, archive — in scan order."""
    return [
        Stage.ACTIVE.dir(root),
        Stage.DRAFTS.dir(root),
        Stage.ARCHIVE.dir(root),
    ]


def find_collisions(root: Path) -> dict[int, list[Path]]:
    """Group all task files by numeric ID. Returns groups with >= 2 members."""
    by_id: dict[int, list[Path]] = defaultdict(list)
    for d in _stage_dirs(root):
        if not d.exists():
            continue
        for p in d.glob("task-*.md"):
            if not p.is_file():
                continue
            m = _FILENAME_RE.match(p.name)
            if m is not None:
                by_id[int(m.group(1))].append(p)
    return {tid: paths for tid, paths in by_id.items() if len(paths) >= 2}


def _slug_from_filename(name: str) -> str:
    """Extract the slug portion from `task-NNN - slug.md`."""
    m = _FILENAME_RE.match(name)
    if m is None:
        return "untitled"
    slug = m.group(2) or "untitled"
    return slug.strip()


def _rewrite_id_in_frontmatter(text: str, new_id: int) -> str:
    """Replace the FIRST `id:` line inside the leading `---` frontmatter
    block with the new integer value. Leaves the body untouched.

    Handles BOTH legacy forms seen in the corpus (audited 2026-05-12):
      - `id: 30`        (153 tasks — pure integer)
      - `id: task-030`  (117 tasks — string with `task-` prefix)
      - `id: 'task-30'` (quoted variant)

    The schema's @field_validator on `id` coerces the string form to int
    at parse time, so leaving the prefix here would mask collisions after
    a dedupe rename. Rewrite always emits pure-integer form.

    Idempotent: if the file lacks frontmatter or lacks an `id:` field,
    returns the text unchanged.
    """
    if not text.startswith("---"):
        return text
    end = text.find("---", 3)
    if end == -1:
        return text
    fm = text[3:end]
    body = text[end:]
    # Match `id:` at start of a line. Value may be:
    #   - bare digits: `id: 30`
    #   - `task-` prefix: `id: task-030`
    #   - quoted: `id: 'task-30'` or `id: "30"`
    # Capture indent prefix (group 1) and trailing whitespace (group 2).
    # Match all legacy id forms observed in the corpus:
    #   `id: 30`, `id: task-030`, `id: 'task-30'`, `id: "30"`,
    #   `id: 401-v1-archive` (one archived task uses this).
    # Any non-bare-int form is rewritten to bare int to keep the schema
    # validator's coercer from masking future collisions.
    pattern = re.compile(
        r"(?m)^(\s*id\s*:\s*)"
        r"(?:'[^']*'|\"[^\"]*\"|task-[\w-]+|\d+(?:-[\w-]+)?)"
        r"(\s*)$"
    )
    new_fm, n = pattern.subn(
        lambda m: f"{m.group(1)}{new_id}{m.group(2)}",
        fm,
        count=1,
    )
    if n == 0:
        return text  # frontmatter present but no recognizable id line
    return f"---{new_fm}{body}"


def _body_mentions_old_id(text: str, old_id: int) -> int:
    """Count occurrences of `task-OLDID` patterns in the file content
    (helps operator review whether prose still references the old ID).

    Matches: `task-217`, `task-0217`, but NOT `task-2170` etc."""
    pattern = re.compile(rf"\btask-0*{old_id}\b")
    return len(pattern.findall(text))


def plan_dedupe(collisions: dict[int, list[Path]]) -> list[dict[str, Any]]:
    """Compute the per-collision action plan WITHOUT touching disk.

    Each plan entry describes one rename: a single newer-file gets
    reassigned. If 3+ files share an ID (rare), every file beyond the
    oldest is queued; new IDs assigned in mtime order (oldest-of-the-
    duplicates first to keep the migration deterministic).
    """
    plans: list[dict[str, Any]] = []
    for old_id, paths in sorted(collisions.items()):
        # Sort by mtime ASCENDING — first entry keeps the ID.
        ordered = sorted(paths, key=lambda p: p.stat().st_mtime)
        keeper = ordered[0]
        for victim in ordered[1:]:
            plans.append(
                {
                    "old_id": old_id,
                    "keeper": str(keeper),
                    "keeper_mtime": keeper.stat().st_mtime,
                    "victim": str(victim),
                    "victim_mtime": victim.stat().st_mtime,
                    "victim_slug": _slug_from_filename(victim.name),
                    # new_id filled in during --apply; for dry-run we
                    # report a synthetic preview.
                    "new_id": None,
                }
            )
    return plans


def execute_plan(
    plans: list[dict[str, Any]],
    root: Path,
) -> list[dict[str, Any]]:
    """Apply the plan, mutating disk. Returns the plan with new_id +
    new_path filled in plus a `body_mentions_old_id` count for operator
    review.

    Idempotency: each victim's `id:` frontmatter is rewritten to the new
    reserved ID and the file is renamed under its stage directory.
    """
    results: list[dict[str, Any]] = []
    for plan in plans:
        victim = Path(plan["victim"])
        old_id = plan["old_id"]
        slug = plan["victim_slug"]

        # Atomically reserve a fresh ID — counter file persists across
        # the migration even if interrupted partway through.
        new_id = reserve_id(root=root)

        text = victim.read_text()
        body_mentions = _body_mentions_old_id(text, old_id)
        new_text = _rewrite_id_in_frontmatter(text, new_id)

        new_name = f"task-{new_id} - {slug}.md"
        new_path = victim.parent / new_name

        # Write new content, then rename (two-step keeps changes visible
        # if a crash interrupts between write and rename — the file
        # under the OLD name will have NEW id frontmatter, scan_ids
        # still finds it via filename, mtime ordering for any future
        # collision pass is preserved).
        victim.write_text(new_text)
        os.rename(victim, new_path)

        results.append(
            {
                **plan,
                "new_id": new_id,
                "new_path": str(new_path),
                "body_mentions_old_id": body_mentions,
            }
        )
    return results


def write_migration_log(
    root: Path,
    results: list[dict[str, Any]],
    started_at: str,
    finished_at: str,
) -> Path:
    """Archive the migration log under <root>/archive/migrations/."""
    log_dir = root / "archive" / "migrations"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"dedupe_collisions_{started_at.replace(':', '-')}.json"
    payload = {
        "tool": "claude_backlog.scripts.dedupe_collisions",
        "started_at": started_at,
        "finished_at": finished_at,
        "actions_taken": results,
        "summary": {
            "total_renames": len(results),
            "ids_freed_for_reassignment": [r["old_id"] for r in results],
            "new_ids_assigned": [r["new_id"] for r in results],
            "tasks_with_body_mentions": sum(
                1 for r in results if r["body_mentions_old_id"] > 0
            ),
        },
    }
    log_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return log_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dedupe colliding task IDs in claude-backlog corpus."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the migration. Default is --dry-run.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=BACKLOG_ROOT,
        help=f"Backlog root (default: {BACKLOG_ROOT})",
    )
    args = parser.parse_args(argv)

    root: Path = args.root
    collisions = find_collisions(root)

    print(f"=== claude-backlog dedupe_collisions ===")
    print(f"Backlog root: {root}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Total colliding IDs: {len(collisions)}")
    total_dupes = sum(len(p) - 1 for p in collisions.values())
    print(f"Total files to reassign: {total_dupes}")
    print()

    if not collisions:
        print("COLLISIONS: 0 — corpus is clean.")
        return 0

    plans = plan_dedupe(collisions)

    if not args.apply:
        # Dry-run output — also surface cross-ref body mentions per plan so
        # the operator can audit risk before committing.
        for plan in plans:
            keeper_t = datetime.fromtimestamp(
                plan["keeper_mtime"], tz=timezone.utc
            ).isoformat(timespec="seconds")
            victim_t = datetime.fromtimestamp(
                plan["victim_mtime"], tz=timezone.utc
            ).isoformat(timespec="seconds")
            keeper_name = Path(plan["keeper"]).name
            victim_name = Path(plan["victim"]).name
            # Count any `task-OLDID` mentions in BOTH the victim AND in any
            # other task's body. Surface to operator so they can review.
            old_id = plan["old_id"]
            victim_text = Path(plan["victim"]).read_text()
            victim_mentions = _body_mentions_old_id(victim_text, old_id)
            external_mentions = 0
            for d in _stage_dirs(root):
                if not d.exists():
                    continue
                for other in d.glob("task-*.md"):
                    if not other.is_file() or other == Path(plan["victim"]):
                        continue
                    try:
                        external_mentions += _body_mentions_old_id(
                            other.read_text(), old_id
                        )
                    except OSError:
                        pass
            print(f"task-{old_id}:")
            print(f"  KEEP   [{keeper_t}] {keeper_name}")
            print(f"  RENAME [{victim_t}] {victim_name}")
            print(f"         → task-<NEW_ID> - {plan['victim_slug']}.md")
            if victim_mentions or external_mentions:
                print(
                    f"         (body mentions: {victim_mentions} in victim, "
                    f"{external_mentions} elsewhere — review post-apply)"
                )
        print()
        print("Re-run with --apply to execute.")
        return 0

    started = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    results = execute_plan(plans, root)
    finished = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    log_path = write_migration_log(root, results, started, finished)

    print()
    print(f"Migration log archived: {log_path}")
    print()
    print("Per-rename summary:")
    for r in results:
        old_path = Path(r["victim"]).name
        new_path = Path(r["new_path"]).name
        mentions = r["body_mentions_old_id"]
        suffix = (
            f"  (warning: body has {mentions} mentions of `task-{r['old_id']}` — review)"
            if mentions
            else ""
        )
        print(f"  task-{r['old_id']} → task-{r['new_id']}: {old_path} → {new_path}{suffix}")

    print()
    print(f"Done. {len(results)} files renamed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
