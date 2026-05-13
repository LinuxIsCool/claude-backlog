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
    find_collisions,
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

# Canonical status families (5). The live corpus has 24 distinct status
# strings; this map normalizes them so the kanban can render reliably.
# Keys are status strings lowercased + stripped; values are the canonical
# family name. Unmapped strings fall back to "To Do" (see _normalize_status).
#
# Doctrine: this lives ON THE SERVER so every adapter (web UI / MCP / hooks)
# sees the same normalization. The raw status string remains accessible on
# every Task summary so audits / migrations / corpus hygiene work isn't lost.
_STATUS_FAMILY: dict[str, str] = {
    # ── To Do family ────────────────────────────────────────────────
    "to do":            "To Do",
    "todo":             "To Do",
    "backlog":          "To Do",
    "pending":          "To Do",
    "open":             "To Do",
    "ready":            "To Do",
    "active":           "To Do",
    "planned":          "To Do",
    "proposed":         "To Do",
    "discussion":       "To Do",
    # ── In Progress family ──────────────────────────────────────────
    "in progress":      "In Progress",
    "in-progress":      "In Progress",
    "inprogress":       "In Progress",
    "wip":              "In Progress",
    # ── Blocked family ──────────────────────────────────────────────
    "blocked":          "Blocked",
    "waiting":          "Blocked",
    "stalled":          "Blocked",
    # ── Done family ────────────────────────────────────────────────
    "done":             "Done",
    "complete":         "Done",
    "completed":        "Done",
    "shipped":          "Done",
    "phase-0-shipped":  "Done",
    "phase-1-shipped":  "Done",
    "phase-2-shipped":  "Done",
    "tier-1-shipped":   "Done",
    "tier-2-shipped":   "Done",
    "cancelled":        "Done",
    "superseded":       "Done",
    # ── Draft family ───────────────────────────────────────────────
    "draft":            "Draft",
}

# The 5 canonical families the kanban renders. Order = column order L→R.
CANONICAL_STATUSES: tuple[str, ...] = ("To Do", "In Progress", "Blocked", "Done", "Draft")


def _normalize_status(raw: str | None) -> str:
    """Map any status string to one of CANONICAL_STATUSES.

    Pure function — used by `list`, `stats`, `facets`, and `search`. Keeps
    the kanban deterministic regardless of corpus drift.
    """
    if not raw:
        return "To Do"
    key = str(raw).strip().lower()
    return _STATUS_FAMILY.get(key, "To Do")


# --- Public accessor --------------------------------------------------------


class BacklogAccessor:
    """Read-only accessor over the backlog corpus.

    Satisfies `claude_webui.Accessor` Protocol via structural typing.
    Mutations live in the MCP server (task_create / task_edit / task_archive
    / draft_promote / definition_of_done_defaults_upsert) per the kernel
    doctrine invariant `hard-405-on-mutations`.

    In-memory cache keyed by (stage, root_mtime_signature):
      • First call parses every task file in the stage.
      • Subsequent calls return the cached list IF the directory's mtime
        signature is unchanged.
      • If any task file's mtime > cache.signature, the cache invalidates
        and the next call re-reads. Cheaper than per-request fs scan when
        the corpus is in the "lots of reads, occasional writes" regime
        (which describes ~all usage today).
    """

    namespace = NAMESPACE
    version = _BACKLOG_VERSION

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or BACKLOG_ROOT
        # Per-stage cache. Keys: Stage enum. Values: (signature_tuple, tasks).
        self._cache: dict[Any, tuple[tuple, list[Task]]] = {}

    # ----- caching layer ----------------------------------------------------

    def _signature(self, stage: Stage) -> tuple:
        """Return a (count, max_mtime) signature for fast cache invalidation."""
        max_mtime = 0.0
        count = 0
        for p in _iter_stage_files(stage, self.root):
            try:
                m = p.stat().st_mtime
            except FileNotFoundError:
                continue
            if m > max_mtime:
                max_mtime = m
            count += 1
        return (count, max_mtime)

    def _cached_tasks(self, stage: Stage) -> list[Task]:
        """Return cached parsed Task[] for a stage, refreshing on mtime drift."""
        sig = self._signature(stage)
        cached = self._cache.get(stage)
        if cached is not None and cached[0] == sig:
            return cached[1]
        tasks = list(list_tasks(stage, self.root))
        self._cache[stage] = (sig, tasks)
        return tasks

    def invalidate_cache(self) -> None:
        """Manual invalidation (test seam; not used in steady state)."""
        self._cache.clear()

    # ----- 5-method Accessor Protocol surface ---------------------------

    def list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Return task summaries matching the query parameters.

        Recognized params (all optional):
          stage          - "active" (default) | "drafts" | "archive" | "any"
          status         - exact match on raw `status` string, case-insensitive
          status_family  - one of CANONICAL_STATUSES (To Do / In Progress /
                           Blocked / Done / Draft) — preferred filter for UI
          priority       - one of critical|high|medium|low
          tag            - tag substring (case-insensitive)
          venture        - substring on the `venture` field
          q              - free-text substring across title + body
          creator_persona, assignee_persona - persona slug match
          include_done   - "1" to include Done/Cancelled (default exclude
                           — except when status_family='Done' which forces include)
          limit          - cap rows (default 1000 — corpus is ~293 today)
          offset         - pagination offset (default 0)
        """
        stage = _stage_from_param(params.get("stage", "active"))
        tasks: list[Task] = list(self._cached_tasks(stage))

        # Filter
        status = _strip(params.get("status"))
        status_family = _strip(params.get("status_family"))
        priority = _strip(params.get("priority"))
        tag = _strip(params.get("tag"))
        venture = _strip(params.get("venture"))
        q = _strip(params.get("q"))
        creator = _strip(params.get("creator_persona"))
        assignee = _strip(params.get("assignee_persona"))
        include_done = (
            str(params.get("include_done", "")).lower() in {"1", "true", "yes"}
            or status_family == "Done"
        )

        def keep(t: Task) -> bool:
            if not include_done and t.status.lower() in _DONE_STATUSES:
                return False
            if status and t.status.lower() != status.lower():
                return False
            if status_family and _normalize_status(t.status) != status_family:
                return False
            if priority and t.priority != priority.lower():
                return False
            if tag and not any(tag.lower() in tg.lower() for tg in t.tags):
                return False
            if venture and (not t.venture or venture.lower() not in t.venture.lower()):
                return False
            if q:
                # Match against id + title + body + tags + venture + milestone.
                # ID is first-class so `446` surfaces task-446 even when the
                # digits don't appear elsewhere on the card.
                q_lc = q.lower()
                hay = (
                    f"{t.id}\n{t.title}\n{t.body}\n"
                    f"{' '.join(t.tags)}\n{t.venture or ''}\n{t.milestone or ''}"
                ).lower()
                if q_lc not in hay:
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

        # Sort — honors optional `sort` param, falls back to priority+created.
        # Accepted: priority|created|due|id|title|status_family|venture|checkbox
        # Optional direction suffix: ":asc" / ":desc"
        sort_param = _strip(params.get("sort"))
        kept = _sort_tasks(kept, sort_param)

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
        """Aggregate counts across the active + drafts corpus."""
        active = self._cached_tasks(Stage.ACTIVE)
        drafts = self._cached_tasks(Stage.DRAFTS)
        by_status: dict[str, int] = {}        # raw status strings (24+ today)
        by_status_family: dict[str, int] = {}  # canonical 5 families
        by_priority: dict[str, int] = {}
        by_venture: dict[str, int] = {}
        by_creator: dict[str, int] = {}
        by_assignee: dict[str, int] = {}
        checkbox_checked = 0
        checkbox_total = 0
        for t in active:
            by_status[t.status] = by_status.get(t.status, 0) + 1
            family = _normalize_status(t.status)
            by_status_family[family] = by_status_family.get(family, 0) + 1
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
        # Drafts always fold into the Draft family for the kanban; mirror that
        # in by_status_family so the column shows non-zero when drafts exist.
        if drafts:
            by_status_family["Draft"] = by_status_family.get("Draft", 0) + len(drafts)

        # Corpus-health hygiene (task-447 A3): surface ID collision count and
        # parse-failure count. After the flock fix + dedupe migration this
        # should hold steady at collision_count=0 — a non-zero value is a
        # regression signal worth investigating.
        collisions = find_collisions(self.root)
        colliding_ids = sorted(collisions.keys())
        # Cap colliding_ids payload at 50 to keep response size bounded.
        colliding_ids_truncated = colliding_ids[:50]
        # Audit unparseable files (separate from collisions — corpus hygiene
        # not all caused by races). One bad-YAML file is the only known
        # failure mode today.
        parse_failures = 0
        total_files = 0
        for p in _iter_stage_files(Stage.ANY, self.root):
            total_files += 1
            try:
                read_task(p)
            except BacklogToolError:
                parse_failures += 1
            except Exception:  # pragma: no cover  — defensive
                parse_failures += 1

        return {
            "active_total": len(active),
            "drafts_total": len(drafts),
            "by_status": by_status,
            "by_status_family": by_status_family,
            "by_priority": by_priority,
            "by_venture": by_venture,
            "by_creator_persona": by_creator,
            "by_assignee_persona": by_assignee,
            "checkbox_progress": {
                "checked": checkbox_checked,
                "total": checkbox_total,
                "ratio": (checkbox_checked / checkbox_total) if checkbox_total else 0.0,
            },
            "corpus_health": {
                "total_files": total_files,
                "collision_count": len(collisions),
                "colliding_ids": colliding_ids_truncated,
                "parse_failures": parse_failures,
            },
            "namespace": NAMESPACE,
        }

    # ----- Extra-route methods (registered via extra_routes in server.py) -----

    def facets(self) -> dict[str, Any]:
        """Return all filter-chip values for the UI's filter bar.

        Shape:
          {
            "priorities":     ["critical","high","medium","low"],   # canonical
            "status_families": ["To Do","In Progress","Blocked","Done","Draft"],
            "raw_statuses":   [{"value": str, "count": int}, ...]  # all 24-ish
            "ventures":       [{"value": str, "count": int}, ...]
            "tags":           [{"value": str, "count": int}, ...]
            "creator_personas":  [{"value": str, "count": int}, ...]
            "assignee_personas": [{"value": str, "count": int}, ...]
            "milestones":     [{"value": str, "count": int}, ...]
          }
        Values sorted by descending count; ties by name.
        """
        tasks = list(self._cached_tasks(Stage.ACTIVE)) + list(
            self._cached_tasks(Stage.DRAFTS)
        )
        raw_status: dict[str, int] = {}
        ventures: dict[str, int] = {}
        tags: dict[str, int] = {}
        creators: dict[str, int] = {}
        assignees: dict[str, int] = {}
        milestones: dict[str, int] = {}
        for t in tasks:
            raw_status[t.status] = raw_status.get(t.status, 0) + 1
            if t.venture:
                ventures[t.venture] = ventures.get(t.venture, 0) + 1
            for tg in t.tags:
                tags[tg] = tags.get(tg, 0) + 1
            ck_p = t.extra_frontmatter.get("creator_persona")
            if isinstance(ck_p, str):
                creators[ck_p] = creators.get(ck_p, 0) + 1
            ak_p = t.extra_frontmatter.get("assignee_persona")
            if isinstance(ak_p, str):
                assignees[ak_p] = assignees.get(ak_p, 0) + 1
            if t.milestone is not None:
                m = str(t.milestone)
                milestones[m] = milestones.get(m, 0) + 1

        def _sorted_counts(d: dict[str, int]) -> list[dict[str, Any]]:
            return [
                {"value": k, "count": v}
                for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))
            ]

        return {
            "priorities": ["critical", "high", "medium", "low"],
            "status_families": list(CANONICAL_STATUSES),
            "raw_statuses": _sorted_counts(raw_status),
            "ventures": _sorted_counts(ventures),
            "tags": _sorted_counts(tags),
            "creator_personas": _sorted_counts(creators),
            "assignee_personas": _sorted_counts(assignees),
            "milestones": _sorted_counts(milestones),
            "namespace": NAMESPACE,
        }

    def search(self, params: dict[str, Any]) -> dict[str, Any]:
        """Free-text search across id + title + body + tags + venture + milestone.

        Returns `{query, total, results: [{...summary, excerpt, score}, ...]}`.
        Sorted by score (descending) where score = sum(weighted matches).

        Server-side search runs over the corpus directly; the UI vendors
        MiniSearch for the LIVE-typing case but falls back to this endpoint
        on cold load + bulk filter.

        ID matching: pure-numeric queries match the task id exactly with the
        highest weight (10x). Numeric substrings inside larger queries match
        with a smaller weight (2x). Both ensure `446` surfaces task-446 even
        though the digits don't appear in title/body in any natural way.
        """
        q = _strip(params.get("q"))
        limit = int(params.get("limit", 50) or 50)
        if not q:
            return {"query": "", "total": 0, "results": []}
        q_lower = q.lower()
        terms = [t for t in re.split(r"\s+", q_lower) if t]
        # Field weights — title hits weighed heaviest, body matches lightest.
        # ID hits dominate when the query is purely numeric (e.g., "446"),
        # so a single-token numeric query routes directly to that task.
        FIELD_WEIGHTS = {
            "id_exact": 10, "id_substring": 2,
            "title": 5, "tags": 3, "venture": 2, "milestone": 2, "body": 1,
        }
        # Pre-extract numeric tokens once — used for id matching.
        numeric_tokens: list[str] = [t for t in terms if t.isdigit()]
        scored: list[tuple[float, Task]] = []
        for t in self._cached_tasks(Stage.ACTIVE):
            score = 0.0
            id_str = str(t.id)
            # ID matches — only fire when the user is asking for IDs.
            for nt in numeric_tokens:
                if id_str == nt:
                    score += FIELD_WEIGHTS["id_exact"]
                elif nt in id_str:
                    score += FIELD_WEIGHTS["id_substring"]
            for term in terms:
                if term in t.title.lower():
                    score += FIELD_WEIGHTS["title"]
                if any(term in tg.lower() for tg in t.tags):
                    score += FIELD_WEIGHTS["tags"]
                if t.venture and term in t.venture.lower():
                    score += FIELD_WEIGHTS["venture"]
                if t.milestone and term in str(t.milestone).lower():
                    score += FIELD_WEIGHTS["milestone"]
                if term in t.body.lower():
                    score += FIELD_WEIGHTS["body"]
            if score > 0:
                scored.append((score, t))
        scored.sort(key=lambda pair: -pair[0])
        results = []
        for score, t in scored[:limit]:
            summary = _summary(t)
            summary["score"] = score
            summary["excerpt"] = _make_excerpt(t.body, terms)
            results.append(summary)
        return {"query": q, "total": len(scored), "results": results}

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
        for t in self._cached_tasks(Stage.ACTIVE):
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


# Sort key extractors per column. Each returns a tuple suitable for `sorted`.
# Default direction is "what makes sense for the column":
#   - priority: low rank first (critical → low) for ASC; reversed for DESC
#   - created/due: newest first for DESC
#   - title/status_family/venture: alphabetical for ASC
#   - id: smallest first for ASC
#   - checkbox: highest progress first for DESC
_SORT_EXTRACTORS: dict[str, Any] = {
    "priority":      lambda t: _PRIORITY_RANK.get(t.priority, 99),
    "created":       lambda t: _date_ord(t.created),
    "due":           lambda t: _date_ord(t.due) if t.due else 10**9,
    "id":            lambda t: t.id,
    "title":         lambda t: (t.title or "").lower(),
    "status_family": lambda t: _normalize_status(t.status),
    "status":        lambda t: (t.status or "").lower(),
    "venture":       lambda t: (t.venture or "").lower(),
    "milestone":     lambda t: str(t.milestone or "").lower(),
    "checkbox":      lambda t: (
        (lambda c: (c[0] / c[1]) if c[1] else -1)(_count_checkboxes(t.body))
    ),
}

# Default direction per column — what humans expect at first click.
_SORT_DEFAULT_DIR: dict[str, str] = {
    "priority":      "asc",   # critical first
    "created":       "desc",  # newest first
    "due":           "asc",   # soonest first
    "id":            "asc",
    "title":         "asc",
    "status_family": "asc",
    "status":        "asc",
    "venture":       "asc",
    "milestone":     "asc",
    "checkbox":      "desc",  # most progress first
}


def _sort_tasks(tasks: list[Task], sort_param: str) -> list[Task]:
    """Apply a `column[:direction][,column[:direction]...]` sort spec.

    Empty / unknown spec falls back to (priority asc, created desc).
    Multi-key sorts are supported via comma. Direction is per-key.
    """
    if not sort_param:
        # Default ordering preserved from pre-sort behavior.
        return sorted(
            tasks,
            key=lambda t: (
                _PRIORITY_RANK.get(t.priority, 99),
                -_date_ord(t.created),
            ),
        )
    keys: list[tuple[str, str]] = []
    for token in sort_param.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            col, direction = token.split(":", 1)
            col = col.strip().lower()
            direction = direction.strip().lower()
        else:
            col = token.lower()
            direction = _SORT_DEFAULT_DIR.get(col, "asc")
        if col not in _SORT_EXTRACTORS:
            continue
        keys.append((col, direction))
    if not keys:
        return _sort_tasks(tasks, "")  # fallback

    def composite(t: Task) -> tuple:
        out = []
        for col, direction in keys:
            v = _SORT_EXTRACTORS[col](t)
            if direction == "desc":
                # Negate numeric / wrap string for reverse ordering.
                if isinstance(v, (int, float)):
                    v = -v
                else:
                    v = _ReverseStr(v)
            out.append(v)
        return tuple(out)

    return sorted(tasks, key=composite)


class _ReverseStr:
    """Wrapper that reverses string ordering for desc sort keys.

    sorted() can't accept reverse-on-a-per-key basis natively; this helper
    inverts comparison so a single sorted() call handles mixed directions.
    """

    __slots__ = ("s",)

    def __init__(self, s: str) -> None:
        self.s = s

    def __lt__(self, other: "_ReverseStr") -> bool:
        return self.s > other.s

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ReverseStr) and self.s == other.s

    def __repr__(self) -> str:
        return f"_ReverseStr({self.s!r})"


def _count_checkboxes(body: str) -> tuple[int, int]:
    """Return (checked, total) checkbox count across a task body."""
    matches = _CHECKBOX_RE.findall(body or "")
    total = len(matches)
    checked = sum(1 for m in matches if m.lower() == "x")
    return checked, total


def _make_excerpt(body: str, terms: list[str], *, radius: int = 60) -> str:
    """Return a ~120-char excerpt centered on the first matched term.

    Falls back to the first `radius * 2` chars when no term matches (e.g.
    a phrase that survives across non-matching chunks of the body). UI
    renders matched terms via its own buildExcerpt() pattern; the excerpt
    here only chooses WHICH slice of the body to render.
    """
    if not body:
        return ""
    body_lower = body.lower()
    earliest = -1
    for term in terms:
        idx = body_lower.find(term)
        if idx != -1 and (earliest == -1 or idx < earliest):
            earliest = idx
    if earliest == -1:
        return body[: radius * 2].strip()
    start = max(0, earliest - radius)
    end = min(len(body), earliest + radius * 2)
    excerpt = body[start:end].strip()
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(body):
        excerpt = excerpt + "…"
    return excerpt


def _summary(t: Task) -> dict[str, Any]:
    """Compact JSON shape for list view."""
    checked, total = _count_checkboxes(t.body)
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "status_family": _normalize_status(t.status),
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
