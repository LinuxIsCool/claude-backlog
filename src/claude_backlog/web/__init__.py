"""claude-backlog web UI — Phase 5 of task-435 (parent: task-442).

Vanilla stdlib ThreadingHTTPServer + Alpine.js client. No build step, no Node
toolchain at runtime. Matches the established Legion fleet web-UI pattern
(claude-recordings/youtube/voice/inventory/browser-history).

The server is a *second adapter* on top of `claude_backlog/` — the same library
the MCP server already wraps. Zero logic duplication; new features land in the
library and every adapter inherits them.

Sub-phases (see `~/.claude/local/backlog/task-442 - …phase-5… .md`):
  5.1 server foundation + persona schema  ← THIS RELEASE
  5.2 read APIs + 4 basic views
  5.3 search + drafts + SSE
  5.4 write APIs + inline edit + DnD
  5.5 embedding pipeline + 5 advanced views
  5.6 polish + smoke + docs + ship
"""

from claude_backlog.web.server import BacklogHTTPServer, make_handler, serve

__all__ = ["BacklogHTTPServer", "make_handler", "serve"]
