"""BacklogAccessor — implements claude_webui.Accessor over the backlog corpus.

Phase 2 of task-441 (first satellite migration). Replaces the in-plugin
ThreadingHTTPServer + custom routes that the pre-pivot Phase 5.1 work
introduced. The web/ surface now consists of:

  1. This accessor (5 methods of `claude_webui.Accessor`)
  2. A ~40-LOC `server.py` that instantiates `WebuiKernel(accessor=...)`
  3. A Tailwind+vanilla-JS `static/index.html` per kernel-webui doctrine

The kernel owns ThreadingHTTPServer, routing, gzip, /healthz, Range support,
hard-405 on mutations, and Server-Timing. We supply DATA SHAPE ONLY.

The five Accessor methods map to the kernel routes:
    GET  /api/list          → BacklogAccessor.list(params)
    GET  /api/detail/<id>   → BacklogAccessor.detail(item_id)
    GET  /api/stats         → BacklogAccessor.stats()
    GET  /api/feed          → BacklogAccessor.feed(params)
    GET  /healthz           → BacklogAccessor.healthz()

Persona attribution is read-only here — if a task's frontmatter carries
`creator_persona` / `assignee_persona` / `persona_history` (managed by
claude-personas overlay, not by claude-backlog's typed schema), the
accessor surfaces them to the UI as extras. The accessor does NOT
type-validate them; claude-personas owns that contract.
"""
from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from claude_backlog import __version__ as _BACKLOG_VERSION
from claude_backlog.errors import BacklogToolError
from claude_backlog.io import (
    BACKLOG_ROOT,
    Stage,
    _iter_stage_files,
    find_task,
    list_tasks,
    read_task,
)
from claude_backlog.schema import Task

# --- Constants --------------------------------------------------------------

NAMESPACE: str = "legion.claude-backlog"

_DONE_STATUSES: frozenset[str] = frozenset({"done", "cancelled"})

# Priority ordering for sort + filter — preserves the canonical config.yml
# ranking without re-reading config on every request.
_PRIORITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

# Match `[ ]` or `[x]` (case-insensitive) at the start of a list item.
_CHECKBOX_RE: re.Pattern[str] = re.compile(r"^\s*-\s*\[( |x|X)\]\s+", re.MULTILINE)


# --- Public accessor --------------------------------------------------------


class BacklogAccessor:
    """Read-only accessor over the backlog corpus.

    Satisfies `claude_webui.Accessor` Protocol via structural typing.
    Mutations live in the MCP server (task_create / task_edit / task_archive
    / draft_promote / definition_of_done_defaults_upsert) per the kernel
    doctrine invariant `hard-405-on-mutations`.
    """

    namespace = NAMESPACE
    version = _BACKLOG_VERSION

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or BACKLOG_ROOT

    # ----- 5-method Accessor Protocol surface ---------------------------

    def list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Return task summaries matching the query parameters.

        Recognized params (all optional):
          stage    - "active" (default) | "drafts" | "archive" | "any"
          status   - exact match on `status`, case-insensitive
          priority - one of critical|high|medium|low
          tag      - tag substring (case-insensitive)
          venture  - substring on the `venture` field
          q        - free-text substring across title + body
          creator_persona, assignee_persona - persona slug match
          include_done - "1" to include Done/Cancelled (default exclude)
          limit    - cap rows (default 1000 — corpus is ~286 today)
          offset   - pagination offset (default 0)
        """
        stage = _stage_from_param(params.get("stage", "active"))
        tasks: list[Task] = list(list_tasks(stage, self.root))

        # Filter
        status = _strip(params.get("status"))
        priority = _strip(params.get("priority"))
        tag = _strip(params.get("tag"))
        venture = _strip(params.get("venture"))
        q = _strip(params.get("q"))
        creator = _strip(params.get("creator_persona"))
        assignee = _strip(params.get("assignee_persona"))
        include_done = str(params.get("include_done", "")).lower() in {"1", "true", "yes"}

        def keep(t: Task) -> bool:
            if not include_done and t.status.lower() in _DONE_STATUSES:
                return False
            if status and t.status.lower() != status.lower():
                return False
            if priority and t.priority != priority.lower():
                return False
            if tag and not any(tag.lower() in tg.lower() for tg in t.tags):
                return False
            if venture and (not t.venture or venture.lower() not in t.venture.lower()):
                return False
            if q:
                hay = f"{t.title}\n{t.body}".lower()
                if q.lower() not in hay:
                    return False
            if creator:
                fm_creator = t.extra_frontmatter.get("creator_persona")
                if fm_creator != creator:
                    return False
            if assignee:
                fm_assignee = t.extra_frontmatter.get("assignee_persona")
                if fm_assignee != assignee:
                    return False
            return True

        kept = [t for t in tasks if keep(t)]

        # Sort: priority asc (critical first), then created desc (newest first)
        kept.sort(
            key=lambda t: (
                _PRIORITY_RANK.get(t.priority, 99),
                -_date_ord(t.created),
            )
        )

        # Paginate
        offset = int(params.get("offset", 0) or 0)
        limit = int(params.get("limit", 1000) or 1000)
        page = kept[offset : offset + limit]

        return [_summary(t) for t in page]

    def detail(self, item_id: str) -> dict[str, Any]:
        """Return full record for a single task ID."""
        try:
            task_id = _coerce_task_id(item_id)
        except ValueError as exc:
            return {"error": str(exc), "item_id": item_id}
        path = find_task(task_id, Stage.ANY, self.root)
        if path is None:
            return {"error": "task_not_found", "item_id": item_id}
        try:
            t = read_task(path)
        except BacklogToolError as exc:
            return {
                "error": "task_unparseable",
                "item_id": item_id,
                "path": str(path),
                "detail": str(exc),
            }
        return _detail(t, path)

    def stats(self) -> dict[str, Any]:
        """Aggregate counts across the active corpus."""
        active = list(list_tasks(Stage.ACTIVE, self.root))
        drafts = list(list_tasks(Stage.DRAFTS, self.root))
        by_status: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        by_venture: dict[str, int] = {}
        by_creator: dict[str, int] = {}
        by_assignee: dict[str, int] = {}
        checkbox_checked = 0
        checkbox_total = 0
        for t in active:
            by_status[t.status] = by_status.get(t.status, 0) + 1
            by_priority[t.priority] = by_priority.get(t.priority, 0) + 1
            if t.venture:
                by_venture[t.venture] = by_venture.get(t.venture, 0) + 1
            ck, ct = _count_checkboxes(t.body)
            checkbox_checked += ck
            checkbox_total += ct
            ck_p = t.extra_frontmatter.get("creator_persona")
            if isinstance(ck_p, str):
                by_creator[ck_p] = by_creator.get(ck_p, 0) + 1
            ak_p = t.extra_frontmatter.get("assignee_persona")
            if isinstance(ak_p, str):
                by_assignee[ak_p] = by_assignee.get(ak_p, 0) + 1
        return {
            "active_total": len(active),
            "drafts_total": len(drafts),
            "by_status": by_status,
            "by_priority": by_priority,
            "by_venture": by_venture,
            "by_creator_persona": by_creator,
            "by_assignee_persona": by_assignee,
            "checkbox_progress": {
                "checked": checkbox_checked,
                "total": checkbox_total,
                "ratio": (checkbox_checked / checkbox_total) if checkbox_total else 0.0,
            },
            "namespace": NAMESPACE,
        }

    def feed(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Return tasks ordered by `created` desc — feeds claude-feed / portal.

        Recognized params:
          limit - cap rows (default 50)
          since - unix epoch (seconds); include only tasks with `created` > since
        """
        limit = int(params.get("limit", 50) or 50)
        since = float(params.get("since", 0) or 0)
        cutoff = date.fromtimestamp(since) if since else None
        rows = []
        for t in list_tasks(Stage.ACTIVE, self.root):
            if cutoff and t.created <= cutoff:
                continue
            rows.append(_feed_item(t))
        rows.sort(key=lambda r: r["created"], reverse=True)
        return rows[:limit]

    def healthz(self) -> dict[str, Any]:
        """Smoke check: count files + parse one of them; report elapsed."""
        from claude_webui.healthz import healthz_response

        start = time.perf_counter()
        try:
            files = list(_iter_stage_files(Stage.ACTIVE, self.root))
            count = len(files)
            sample_ok = True
            if files:
                read_task(files[0])
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - start) * 1000
            return healthz_response(
                namespace=NAMESPACE,
                database=str(self.root),
                elapsed_ms=elapsed,
                ok=False,
                error=str(exc),
            )
        elapsed = (time.perf_counter() - start) * 1000
        body = healthz_response(
            namespace=NAMESPACE,
            database=str(self.root),
            elapsed_ms=elapsed,
            ok=True,
        )
        body["active_count"] = count
        body["sample_parses"] = sample_ok
        return body


# --- Internal helpers -------------------------------------------------------


def _strip(v: Any) -> str:
    """Coerce a query value to a stripped string, '' if absent."""
    if v is None:
        return ""
    return str(v).strip()


def _stage_from_param(v: Any) -> Stage:
    """Map a query string to a Stage enum; defaults to ACTIVE."""
    s = _strip(v).lower()
    if s in {"draft", "drafts"}:
        return Stage.DRAFTS
    if s == "archive":
        return Stage.ARCHIVE
    if s == "any":
        return Stage.ANY
    return Stage.ACTIVE


def _coerce_task_id(item_id: str) -> int:
    """Accept '123', 'task-123', 'task-0123' — return int."""
    s = item_id.strip()
    if s.startswith("task-") or s.startswith("task_"):
        s = s[5:]
    try:
        return int(s)
    except ValueError as exc:
        raise ValueError(f"invalid task id: {item_id!r}") from exc


def _date_ord(d: date) -> int:
    """Date as int (proleptic-Gregorian ordinal) for sort comparisons."""
    return d.toordinal()


def _count_checkboxes(body: str) -> tuple[int, int]:
    """Return (checked, total) checkbox count across a task body."""
    matches = _CHECKBOX_RE.findall(body or "")
    total = len(matches)
    checked = sum(1 for m in matches if m.lower() == "x")
    return checked, total


def _summary(t: Task) -> dict[str, Any]:
    """Compact JSON shape for list view."""
    checked, total = _count_checkboxes(t.body)
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "created": t.created.isoformat(),
        "tags": list(t.tags),
        "venture": t.venture,
        "milestone": t.milestone,
        "parent_task": t.parent_task,
        "depends_on": list(t.depends_on),
        "blocks": list(t.blocks),
        "due": t.due.isoformat() if t.due else None,
        "checkbox_checked": checked,
        "checkbox_total": total,
        "checkbox_ratio": (checked / total) if total else None,
        # Persona overlay (from extra_frontmatter; claude-personas-owned).
        "creator_persona": t.extra_frontmatter.get("creator_persona"),
        "assignee_persona": t.extra_frontmatter.get("assignee_persona"),
    }


def _detail(t: Task, path: Path) -> dict[str, Any]:
    """Full JSON shape for detail view."""
    base = _summary(t)
    base["body"] = t.body
    base["path"] = str(path)
    base["effort"] = t.effort
    base["estimated_hours"] = t.estimated_hours
    base["modified_files"] = list(t.modified_files)
    base["documentation"] = list(t.documentation)
    base["definition_of_done"] = list(t.definition_of_done)
    base["ordinal"] = t.ordinal
    base["on_status_change"] = t.on_status_change
    base["extra"] = dict(t.extra_frontmatter)
    return base


def _feed_item(t: Task) -> dict[str, Any]:
    """Chrono-ordered shape for the feed endpoint."""
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "priority": t.priority,
        "created": t.created.isoformat(),
        "venture": t.venture,
        "url": f"/task/{t.id}",
    }
