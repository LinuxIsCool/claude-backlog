"""claude-backlog — shared file-ops library.

Phase 4 of task-435 (Backlog.md cross-pollination). Wraps the filesystem
contract documented in plugin CLAUDE.md + AGENTS.md so hooks, MCP server,
and any future Python entry point share a single implementation.
"""

__version__ = "0.2.1"

from claude_backlog.errors import BacklogToolError, ErrorCode
from claude_backlog.io import (
    BACKLOG_ROOT,
    Stage,
    find_task,
    list_tasks,
    mv_task,
    next_id,
    parse_frontmatter,
    peek_next_id,
    reserve_id,
    scan_ids,
    slugify,
    write_task,
)
from claude_backlog.schema import Config, Draft, Task

__all__ = [
    "BACKLOG_ROOT",
    "BacklogToolError",
    "Config",
    "Draft",
    "ErrorCode",
    "Stage",
    "Task",
    "find_task",
    "list_tasks",
    "mv_task",
    "next_id",
    "parse_frontmatter",
    "peek_next_id",
    "reserve_id",
    "scan_ids",
    "slugify",
    "write_task",
]
