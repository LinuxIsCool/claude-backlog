"""CLI entry: `python -m claude_backlog.web --port 6420`.

Wraps `build_kernel(...)` from `server.py` and either:
  - serves blocking on Ctrl-C / SIGTERM (default), or
  - prints the configured kernel and exits when `--no-serve` is passed
    (useful for smoke-testing the wiring without binding a socket).

Per the kernel-webui doctrine, this CLI deliberately does NOT do
substrate-specific work — every concern beyond argparse + browser-open +
serve is owned by `claude_webui.WebuiKernel`.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen

from claude_backlog.web.server import build_kernel


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude_backlog.web",
        description=(
            "Launch the claude-backlog web UI as a claude-webui satellite "
            "(task-441 Phase 2). Reads from ~/.claude/local/backlog/."
        ),
    )
    p.add_argument("--host", default="127.0.0.1", help="bind interface (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=6420, help="bind port (default 6420)")
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="override BACKLOG_ROOT (defaults to ~/.claude/local/backlog/)",
    )
    p.add_argument("--no-open", action="store_true", help="do not auto-open the browser")
    p.add_argument("--debug", action="store_true", help="verbose per-request logging")
    p.add_argument(
        "--no-serve",
        action="store_true",
        help="construct the kernel + print readiness, then exit (smoke check)",
    )
    return p


def _wait_until_healthy(host: str, port: int, timeout_s: float = 5.0) -> bool:
    url = f"http://{host}:{port}/healthz"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=0.5) as resp:  # noqa: S310 (localhost)
                if resp.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.05)
    return False


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.debug else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    kernel = build_kernel(port=args.port, bind=args.host, root=args.root)

    if args.no_serve:
        print(f"kernel constructed on http://{args.host}:{args.port}/ (no-serve)")
        kernel.stop()
        return 0

    url = f"http://{args.host}:{args.port}/"
    print(f"claude-backlog satellite (via claude-webui kernel) → {url}")
    print("Ctrl-C to stop.")

    # Run serve_forever in the kernel; the kernel's own SIGINT handling
    # exits cleanly when Ctrl-C arrives.
    stop = False

    def _handle(_sig: int, _frame) -> None:
        nonlocal stop
        stop = True
        try:
            kernel.stop()
        except Exception:  # noqa: BLE001
            pass

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    # Open browser after a brief delay so the user lands on a ready page.
    if not args.no_open:
        import threading

        def _open_when_ready() -> None:
            if _wait_until_healthy(args.host, args.port):
                try:
                    webbrowser.open_new_tab(url)
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=_open_when_ready, name="open-browser", daemon=True).start()

    try:
        kernel.serve()  # blocks until shutdown
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
