"""Workflow resource loader.

The MCP server exposes `claude-backlog://workflow/overview` as a markdown
resource. Content lives in `workflows/overview.md` (versioned with plugin).
This loader resolves the path, reads the file, and caches in-memory.
"""

from __future__ import annotations

from pathlib import Path

# The plugin root is two levels up from this file:
# src/claude_backlog/workflow.py → .../claude-backlog/
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKFLOWS_DIR = _PLUGIN_ROOT / "workflows"

# Resource URI → filename mapping (extensible for Phase 4.5 split).
_RESOURCES: dict[str, str] = {
    "overview": "overview.md",
}


def workflow_path(name: str = "overview") -> Path:
    """Return the path for a named workflow resource."""
    if name not in _RESOURCES:
        raise KeyError(f"No workflow resource named {name!r}")
    return _WORKFLOWS_DIR / _RESOURCES[name]


def load_workflow(name: str = "overview") -> str:
    """Read and return the markdown content of a workflow resource.

    Raises FileNotFoundError if the workflow file is missing (signals
    that Phase 4.2 deliverable is incomplete).
    """
    return workflow_path(name).read_text()


def available_workflows() -> list[str]:
    """Return the list of registered workflow names."""
    return list(_RESOURCES.keys())
