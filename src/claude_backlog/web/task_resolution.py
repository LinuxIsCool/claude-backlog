"""Read-only bridge from Backlog routes to claude-addr's parallel v2 index."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path


DEFAULT_INDEX = Path.home() / ".local" / "state" / "legion" / "addr" / "index" / "nodes-v2.db"


@dataclass(frozen=True)
class TaskResolution:
    reference: str
    status: str
    canonical_id: str | None = None
    path: Path | None = None
    resolution: str | None = None
    contested: bool = False
    targets: tuple[str, ...] = ()


class TaskReferenceResolver:
    def __init__(self, backlog_root: Path, index_path: Path | None = None) -> None:
        self.backlog_root = backlog_root.resolve()
        configured = os.environ.get("CLAUDE_ADDR_V2_INDEX")
        self.index_path = index_path or (Path(configured).expanduser() if configured else DEFAULT_INDEX)

    def resolve(self, reference: str) -> TaskResolution:
        reference = reference.strip()
        if not reference or not self.index_path.is_file():
            return TaskResolution(reference=reference, status="unavailable")
        try:
            conn = sqlite3.connect(f"file:{self.index_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id,file_path FROM nodes WHERE id=? AND kind='task'", (reference,)
            ).fetchone()
            resolution = "canonical"
            if row is None:
                ambiguity = conn.execute(
                    "SELECT target_ids FROM alias_collisions WHERE alias=?", (reference,)
                ).fetchone()
                if ambiguity is not None:
                    import json

                    return TaskResolution(
                        reference=reference,
                        status="ambiguous",
                        targets=tuple(json.loads(ambiguity[0])),
                    )
                row = conn.execute(
                    "SELECT n.id,n.file_path FROM aliases a JOIN nodes n ON n.id=a.id "
                    "WHERE a.alias=? AND n.kind='task'",
                    (reference,),
                ).fetchone()
                resolution = "alias"
            if row is None:
                return TaskResolution(reference=reference, status="not_found")
            path = Path(row["file_path"]).resolve() if row["file_path"] else None
            if path is None or not path.is_relative_to(self.backlog_root) or not path.is_file():
                return TaskResolution(reference=reference, status="stale")
            contested = conn.execute(
                "SELECT 1 FROM collisions WHERE claimed_id=? LIMIT 1", (row["id"],)
            ).fetchone() is not None
            return TaskResolution(
                reference=reference,
                status="resolved",
                canonical_id=row["id"],
                path=path,
                resolution=resolution,
                contested=contested,
            )
        except sqlite3.DatabaseError:
            return TaskResolution(reference=reference, status="unavailable")
        finally:
            if "conn" in locals():
                conn.close()

