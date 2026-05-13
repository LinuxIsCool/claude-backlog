"""CLI entry point: `python -m claude_backlog.web`.

Launches the Phase 5 web UI on a configurable port. Default is 6420, chosen to
match the Backlog.md upstream so muscle memory carries over.

The CLI is intentionally thin — argparse → start server → (optionally) open the
default browser → block on SIGINT. All routing logic lives in `server.py` so
tests can drive the handler directly without spinning up a subprocess.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
import webbrowser
from urllib.request import urlopen

from claude_backlog.web.server import _check_port, build_arg_parser, serve


def _wait_until_healthy(host: str, port: int, timeout_s: float = 5.0) -> bool:
    """Poll /healthz until it returns 200 or `timeout_s` elapses."""
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

    _check_port(args.host, args.port)
    server = serve(
        host=args.host,
        port=args.port,
        static_root=args.static_root,
        debug=args.debug,
    )

    url = f"http://{args.host}:{args.port}/"
    print(f"claude-backlog web UI → {url}")
    print("Ctrl-C to stop.")

    healthy = _wait_until_healthy(args.host, args.port)
    if not healthy:
        print("WARN: server did not come up cleanly within 5s", file=sys.stderr)

    if not args.no_open and healthy:
        # webbrowser.open is best-effort — failures are silent by design (no
        # display, headless run, etc.). The URL is already printed above.
        try:
            webbrowser.open_new_tab(url)
        except Exception:  # noqa: BLE001 (best-effort)
            pass

    # Block until Ctrl-C. SIGTERM handled the same way for systemd parity.
    stop = False

    def _handle_signal(_sig: int, _frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not stop:
        time.sleep(0.25)

    print("\nshutting down…")
    server.shutdown()
    server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
