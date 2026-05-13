"""File operations for claude-backlog tasks.

Stable interface for hooks, MCP server, and any future Python entry point.
Everything here mirrors the filesystem contract documented in plugin
CLAUDE.md "File Layout" + AGENTS.md "Public surface".

Functions intentionally avoid I/O side effects beyond the targeted file ops:
no logging, no env writes, no daemon state. Pure file ↔ Task transformations.
"""

from __future__ import annotations

import fcntl
import os
import re
import unicodedata
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

import yaml

from claude_backlog.errors import BacklogToolError, ErrorCode
from claude_backlog.schema import Config, Draft, Task

# --- Backlog root resolution -------------------------------------------------

_DEFAULT_ROOT = Path.home() / ".claude" / "local" / "backlog"


def _resolve_root() -> Path:
    """Resolve BACKLOG_ROOT from env or default."""
    env = os.environ.get("BACKLOG_ROOT")
    if env:
        return Path(env).expanduser()
    return _DEFAULT_ROOT


BACKLOG_ROOT: Path = _resolve_root()


# --- Stage taxonomy ----------------------------------------------------------


class Stage(str, Enum):
    """Lifecycle stage: drafts → active → archive."""

    DRAFTS = "drafts"
    ACTIVE = "active"
    ARCHIVE = "archive"
    ANY = "any"

    def dir(self, root: Path | None = None) -> Path:
        """Return the filesystem directory for this stage."""
        r = root or BACKLOG_ROOT
        if self is Stage.ACTIVE:
            return r
        if self is Stage.DRAFTS:
            return r / "drafts"
        if self is Stage.ARCHIVE:
            return r / "archive"
        raise BacklogToolError(
            ErrorCode.INVALID_STAGE,
            f"Cannot resolve directory for stage {self.value!r}",
        )


# --- Filename + slug helpers -------------------------------------------------

_TASK_RE = re.compile(r"^task-(\d+)(?:\s*-\s*(.*))?\.md$")

_SLUG_MAX = 60


def slugify(title: str, max_len: int = _SLUG_MAX) -> str:
    """Generate filename slug from a title.

    Rules (match existing 286+ task filenames):
    - NFKD-normalize, strip non-ascii.
    - Lowercase.
    - Replace runs of non-alphanumeric with `-`.
    - Strip leading/trailing `-`.
    - Truncate to max_len, again strip trailing `-`.
    - Empty result → "untitled".
    """
    normalized = unicodedata.normalize("NFKD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "untitled"


def filename_for(task_id: int, title: str) -> str:
    """Canonical filename for a task: `task-<id> - <slug>.md`."""
    return f"task-{task_id} - {slugify(title)}.md"


# Backward-compat alias (kept in case any internal caller used the old name).
_filename_for = filename_for


def _parse_task_filename(name: str) -> tuple[int, str | None] | None:
    """Return (id, slug) from a task filename, or None if it doesn't match."""
    m = _TASK_RE.match(name)
    if not m:
        return None
    return int(m.group(1)), m.group(2)


# --- Frontmatter parsing ----------------------------------------------------


def parse_frontmatter(path: Path) -> dict:
    """Extract YAML frontmatter dict from a markdown file.

    Forgiving by design: returns `{}` if the file is missing, lacks a
    `---` block, or has malformed YAML (the F2 enrichment bug surfaces
    on a small number of tasks). Stricter callers should use
    `read_task(path)` which surfaces a typed `BacklogToolError`.
    """
    try:
        content = path.read_text()
    except FileNotFoundError:
        return {}
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    try:
        parsed = yaml.safe_load(content[3:end])
    except yaml.YAMLError:
        return {}
    return parsed or {}


def _split_frontmatter_body(text: str) -> tuple[dict, str]:
    """Split a markdown file into (frontmatter_dict, body_string)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    fm = yaml.safe_load(text[3:end]) or {}
    body = text[end + 3 :]
    if body.startswith("\n"):
        body = body[1:]
    return fm, body


# --- Task <-> file conversion ------------------------------------------------

_KNOWN_FIELDS = {
    "id", "title", "status", "priority", "created", "milestone", "tags",
    "estimated_hours", "depends_on", "blocks", "effort", "due", "venture",
    "modified_files", "ordinal", "parent_task", "documentation",
    "on_status_change", "definition_of_done",
}
# NOTE: persona attribution (creator/assignee/history) is a cross-cutting
# concern owned by claude-personas overlay; it is NOT in the Task schema.
# If those keys appear in a task's frontmatter, they round-trip via
# extra_frontmatter (additive doctrine). See task-441 pivot decision.


def _task_from_text(
    text: str,
    *,
    path: Path | None = None,
    allow_draft: bool = False,
) -> Task:
    """Parse a full markdown file content into a Task.

    If `path` is supplied, missing/invalid `id` or `title` are filled from
    the filename. Tolerates the 14 legacy tasks (audited 2026-05-12) that
    have no `id:` line in frontmatter.
    """
    fm, body = _split_frontmatter_body(text)
    if not fm:
        raise BacklogToolError(
            ErrorCode.VALIDATION_ERROR,
            "File has no YAML frontmatter — cannot construct Task.",
            context={"path": str(path) if path else None},
        )
    known: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for k, v in fm.items():
        if k in _KNOWN_FIELDS:
            known[k] = v
        else:
            extra[k] = v

    # Filename-derived fallback for legacy tasks (14 of 286 lack `id:` line).
    if path is not None:
        parsed = _parse_task_filename(path.name)
        if parsed is not None:
            file_id, file_slug = parsed
            if "id" not in known or known.get("id") in (None, ""):
                known["id"] = file_id
            if "title" not in known or not known.get("title"):
                known["title"] = (file_slug or path.stem).replace("-", " ").strip()

    known["extra_frontmatter"] = extra
    known["body"] = body
    if allow_draft:
        return Draft.model_validate(known)
    return Task.model_validate(known)


def read_task(path: Path) -> Task:
    """Load a task file from disk into a Task model.

    Raises BacklogToolError on missing file (TASK_NOT_FOUND) or malformed
    YAML (VALIDATION_ERROR — known upstream cause: enrichment F2 bug
    serializing comma-bearing rationale strings as broken keys).
    """
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        raise BacklogToolError(
            ErrorCode.TASK_NOT_FOUND,
            f"No file at {path}",
        ) from exc
    try:
        return _task_from_text(text, path=path)
    except yaml.YAMLError as exc:
        raise BacklogToolError(
            ErrorCode.VALIDATION_ERROR,
            f"YAML parse failed for {path.name}: {exc}",
            context={"path": str(path)},
        ) from exc


def _serialize_frontmatter(task: Task) -> dict:
    """Build the ordered frontmatter dict to write to disk."""
    out: dict[str, Any] = {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "created": task.created.isoformat() if isinstance(task.created, date) else task.created,
    }
    # Canonical optionals — only emit if non-default to keep diffs small.
    if task.milestone is not None:
        out["milestone"] = task.milestone
    if task.tags:
        out["tags"] = task.tags
    if task.estimated_hours is not None:
        out["estimated_hours"] = task.estimated_hours
    if task.depends_on:
        out["depends_on"] = task.depends_on
    if task.blocks:
        out["blocks"] = task.blocks
    if task.effort is not None:
        out["effort"] = task.effort
    if task.due is not None:
        out["due"] = task.due.isoformat() if isinstance(task.due, date) else task.due
    if task.venture is not None:
        out["venture"] = task.venture
    # Phase 1 additive
    if task.modified_files:
        out["modified_files"] = task.modified_files
    if task.ordinal is not None:
        out["ordinal"] = task.ordinal
    if task.parent_task is not None:
        out["parent_task"] = task.parent_task
    if task.documentation:
        out["documentation"] = task.documentation
    if task.on_status_change is not None:
        out["on_status_change"] = task.on_status_change
    if task.definition_of_done:
        out["definition_of_done"] = task.definition_of_done
    # Round-trip extras last (preserves enrichment _pipeline block etc., and
    # cross-cutting overlays like persona attribution managed by claude-personas).
    for k, v in task.extra_frontmatter.items():
        out[k] = v
    return out


def task_to_text(task: Task) -> str:
    """Serialize a Task to its on-disk markdown form."""
    fm = _serialize_frontmatter(task)
    yaml_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=120)
    body = task.body
    if not body.startswith("\n") and body:
        body = "\n" + body
    return f"---\n{yaml_text}---{body}"


# --- Stage scans -------------------------------------------------------------


def _iter_stage_files(stage: Stage, root: Path | None = None) -> Iterator[Path]:
    """Yield task-*.md files for the given stage."""
    r = root or BACKLOG_ROOT
    if stage is Stage.ANY:
        for sub in (Stage.ACTIVE, Stage.DRAFTS, Stage.ARCHIVE):
            yield from _iter_stage_files(sub, r)
        return
    d = stage.dir(r)
    if not d.exists():
        return
    for p in sorted(d.glob("task-*.md")):
        # Skip nested dirs accidentally matched (e.g., a directory named "task-*.md")
        if p.is_file():
            yield p


def scan_ids(root: Path | None = None) -> set[int]:
    """Return the set of integer IDs across active + drafts + archive."""
    out: set[int] = set()
    for p in _iter_stage_files(Stage.ANY, root):
        parsed = _parse_task_filename(p.name)
        if parsed is not None:
            out.add(parsed[0])
    return out


_COUNTER_FILE = ".next_id_counter"
_LOCK_FILE = ".next_id.lock"


def _counter_path(root: Path) -> Path:
    return root / _COUNTER_FILE


def _lock_path(root: Path) -> Path:
    return root / _LOCK_FILE


def _read_counter(root: Path) -> int:
    """Read the persisted counter. Returns 0 if missing or unparseable."""
    p = _counter_path(root)
    try:
        return int(p.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return 0


def _write_counter(root: Path, value: int) -> None:
    """Atomic counter write via tmp file + rename. Survives crashes."""
    p = _counter_path(root)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(str(value))
    os.replace(tmp, p)


def peek_next_id(root: Path | None = None) -> int:
    """Read-only preview of what the next reserved ID would be.

    Useful for dry-runs / informational displays. Does NOT reserve.
    Two callers racing on peek_next_id() WILL see the same value —
    use reserve_id() (or next_id()) for actual allocation.
    """
    r = root or BACKLOG_ROOT
    if not r.exists():
        return 1
    counter = _read_counter(r)
    scan = scan_ids(r)
    scan_max = max(scan) if scan else 0
    return max(counter, scan_max) + 1


def reserve_id(root: Path | None = None) -> int:
    """Atomically reserve a fresh task ID under fcntl.flock(LOCK_EX).

    Concurrent-safe: no two callers (across threads OR processes) can
    return the same ID. The reserved value is the larger of the persisted
    counter and `max(scan_ids()) + 1`, so manually-added task files are
    reconciled on every call.

    Lock + counter files live at `<root>/.next_id.lock` and
    `<root>/.next_id_counter`. The lock file is created on first use.

    Fixes the race condition documented in task-447: prior versions did
    `max(scan_ids()) + 1` without a lock, producing 37 ID collisions in
    the live corpus from concurrent multi-agent activity.
    """
    r = root or BACKLOG_ROOT
    r.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_path(r)
    # Open lock file in append mode (creates if missing). The open file
    # description carries the flock; threads opening separately each get
    # their own description and serialize correctly via the kernel.
    with open(lock_path, "a+") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            counter = _read_counter(r)
            scan = scan_ids(r)
            scan_max = max(scan) if scan else 0
            reserved = max(counter, scan_max) + 1
            _write_counter(r, reserved)
            return reserved
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def next_id(root: Path | None = None) -> int:
    """Atomically reserve the next integer task ID. Concurrent-safe.

    Behavior change (task-447, 2026-05-12): this function now reserves
    under fcntl.flock and persists a counter file. Previous versions did
    `max(scan_ids()) + 1` without a lock, allowing two concurrent agents
    to return the same ID. All call sites that invoke next_id() to claim
    an ID for a new task become safe automatically.

    For read-only "what would be next" inspection without reserving, use
    peek_next_id().
    """
    return reserve_id(root)


def find_task(
    task_id: int,
    stage: Stage = Stage.ANY,
    root: Path | None = None,
) -> Path | None:
    """Locate a task file by integer ID. Returns None if not found."""
    for p in _iter_stage_files(stage, root):
        parsed = _parse_task_filename(p.name)
        if parsed is not None and parsed[0] == task_id:
            return p
    return None


def find_collisions(root: Path | None = None) -> dict[int, list[Path]]:
    """Return ID groups with >= 2 files on disk across all stages.

    Used by:
      - /api/stats hygiene badge in the satellite UI (task-447 A3)
      - scripts/dedupe_collisions.py migration tool (task-447 A2)

    Post-flock-fix this should always return {} for a healthy corpus.
    A non-empty result is a regression signal that either (a) the lock
    fell off, (b) a foreign tool wrote tasks without going through
    reserve_id(), or (c) someone manually edited files into a clash.
    """
    from collections import defaultdict

    by_id: dict[int, list[Path]] = defaultdict(list)
    for p in _iter_stage_files(Stage.ANY, root):
        parsed = _parse_task_filename(p.name)
        if parsed is not None:
            by_id[parsed[0]].append(p)
    return {tid: paths for tid, paths in by_id.items() if len(paths) >= 2}


def list_tasks(
    stage: Stage = Stage.ACTIVE,
    root: Path | None = None,
) -> Iterator[Task]:
    """Yield Task models from the given stage's directory.

    Skips files that fail to parse (logs the failure via BacklogToolError
    context but does not raise — one malformed task should not block listing).
    """
    for p in _iter_stage_files(stage, root):
        try:
            yield read_task(p)
        except BacklogToolError:
            continue


# --- Writes ------------------------------------------------------------------


def write_task(
    task: Task,
    stage: Stage = Stage.ACTIVE,
    root: Path | None = None,
) -> Path:
    """Write a Task to disk under the given stage's directory.

    Returns the path written. Creates the stage dir if missing.
    Raises ID_COLLISION if a different task already owns this ID anywhere.
    """
    r = root or BACKLOG_ROOT
    d = stage.dir(r)
    d.mkdir(parents=True, exist_ok=True)
    existing = find_task(task.id, Stage.ANY, r)
    target = d / filename_for(task.id, task.title)
    if existing is not None and existing != target:
        raise BacklogToolError(
            ErrorCode.ID_COLLISION,
            f"Task ID {task.id} already exists at {existing}",
            context={"task_id": task.id, "existing": str(existing)},
        )
    target.write_text(task_to_text(task))
    return target


def mv_task(
    task_id: int,
    from_stage: Stage,
    to_stage: Stage,
    root: Path | None = None,
) -> Path:
    """Move a task file from one stage to another. ID-stable.

    The full filename (`task-N - slug.md`) is preserved verbatim across
    the move — the integer ID never changes and the slug does not re-
    derive from the current title. If the title has been edited and you
    want the filename to reflect that, call `write_task` (which
    re-slugifies) after moving — but be aware this leaves the original
    file in place; the cleanest pattern is a `read_task` → `write_task`
    pair, not a `mv_task`.
    """
    src = find_task(task_id, from_stage, root)
    if src is None:
        raise BacklogToolError(
            ErrorCode.TASK_NOT_FOUND,
            f"Task {task_id} not found in stage {from_stage.value!r}",
            context={"task_id": task_id, "stage": from_stage.value},
        )
    r = root or BACKLOG_ROOT
    dest_dir = to_stage.dir(r)
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Preserve existing filename to maximize stability.
    dest = dest_dir / src.name
    if dest.exists() and dest != src:
        # Filename collision in target dir — rare but possible if two stages had drift.
        raise BacklogToolError(
            ErrorCode.ID_COLLISION,
            f"Destination already exists: {dest}",
            context={"task_id": task_id, "dest": str(dest)},
        )
    src.rename(dest)
    return dest


def load_config(root: Path | None = None) -> Config:
    """Load and validate config.yml from the backlog root."""
    r = root or BACKLOG_ROOT
    path = r / "config.yml"
    if not path.exists():
        return Config()
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise BacklogToolError(
            ErrorCode.CONFIG_ERROR,
            f"Failed to parse {path}: {exc}",
        ) from exc
    return Config.model_validate(data)


def save_config(config: Config, root: Path | None = None) -> Path:
    """Write the config back to config.yml. Round-trips extras."""
    r = root or BACKLOG_ROOT
    path = r / "config.yml"
    data = config.model_dump(exclude_none=False)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120))
    return path
