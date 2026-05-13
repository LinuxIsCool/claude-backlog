---
description: "Launch the claude-backlog web UI at http://localhost:6420/"
argument-hint: "[--port <N>] [--no-open] [--debug] [--stop]"
allowed-tools: [Bash, Read]
---

The `/browser` command starts the Phase 5 claude-backlog web UI in a
background process so the kanban / list / detail / stats / network /
embedding views are reachable from any browser on this machine.

## Parse `$ARGUMENTS`

Read `$ARGUMENTS` and route:

| Tokens | Action |
|---|---|
| (empty) | Start on default port 6420, open the default browser |
| `--port <N>` | Override the listen port |
| `--no-open` | Start but do not auto-open the browser |
| `--debug` | Enable per-request access logging |
| `--stop` | Kill any running `claude_backlog.web` process and exit |

## Implementation

1. **Stop mode** (`--stop`):
   ```bash
   pkill -f "python -m claude_backlog.web" || true
   ```
   Then report which PIDs were killed (or `none running`).

2. **Start mode** (everything else):
   - Resolve plugin root: `~/.claude/plugins/local/legion-plugins/plugins/claude-backlog`.
   - If a server is already listening on the chosen port, just print the URL
     and exit — never spawn a duplicate.
   - Otherwise, launch the server detached in the background:
     ```bash
     uv run --directory <plugin-root> python -m claude_backlog.web \
       --port <port> [--no-open] [--debug] \
       > ~/.claude/local/backlog/.cache/web.log 2>&1 &
     ```
   - Poll `http://127.0.0.1:<port>/healthz` up to 5s; report:
     - `claude-backlog web UI → http://localhost:<port>/`
     - the PID
     - the log path
   - If `--no-open` was NOT passed and the user is on a desktop session, the
     server itself opens a tab via `webbrowser.open_new_tab` — do NOT also
     `xdg-open` here, that would spawn a duplicate tab.

## Output contract

Always print:
- The URL (or `(stopped)` for `--stop`).
- The PID running the server (or `none` if stopped).
- The log path.
- A reminder: `/browser --stop` kills the server.

Do NOT block on the server — it runs detached. The command returns after the
health probe succeeds.

## Data location

- Source: `~/.claude/plugins/local/legion-plugins/plugins/claude-backlog/src/claude_backlog/web/`
- Log:    `~/.claude/local/backlog/.cache/web.log`
- Parent task: `~/.claude/local/backlog/task-442 - …phase-5… .md`
