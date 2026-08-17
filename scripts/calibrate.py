#!/usr/bin/env python3
"""Close the calibration loop: record outcomes against predictions, and report bias.

The corpus has been generating prediction data for months and discarding the
outcomes. Measured 2026-08-11:

    impact_count_predicted present : 226
    tasks reaching terminal state  : 127
    any outcome recorded           :   8

Every prediction without an outcome is training data that cannot be
reconstructed later — nobody remembers in six months how long something took.
This script is the missing half.

Field names follow the design proposed in `246-impact-legibility-infrastructure.md`
(`impact_ratio`, `duration_ratio`), which specified this loop and was never built.

Subcommands
-----------
    calibrate.py pending            # closed tasks with predictions but no outcome
    calibrate.py record 4258 --hours 0.3 --impact 1
    calibrate.py report             # bias + spread per quantity, log space

Design notes
------------
* **Surgical frontmatter edit, never re-serialize.** Round-tripping YAML through
  safe_load/dump reorders keys and reflows the `_pipeline` enrichment blocks,
  which would produce enormous diffs across 752 files. We insert a block before
  the closing `---` and touch nothing else.
* **Log space, median and MAD.** Estimation error is multiplicative — "twice as
  long" is the natural unit, not "six hours more". Median/MAD rather than
  mean/sigma so one 40x outlier cannot move the correction.
* **Refuses to invent.** A quantity with no prediction is not scored. Below
  MIN_PAIRS the report says "insufficient data" rather than printing a number.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

BACKLOG = Path.home() / ".claude" / "local" / "backlog"
LEDGER = BACKLOG / "calibration-ledger.jsonl"

TERMINAL = {"done", "complete", "completed", "closed"}
# Below this, a bias estimate is noise dressed as a correction.
MIN_PAIRS = 20

QUANTITIES = ("hours", "impact_count")

# Who DID the work, not who estimated it. Agent-executed work is
# systematically over-estimated: a model estimating effort draws on a training
# distribution of human effort. Human-executed work estimates fine. Sharing one
# bias correction across both would cancel the signal.
EXECUTORS = ("agent", "human")


# ---------------------------------------------------------------- parsing


def split_frontmatter(text: str) -> tuple[str, str, str]:
    """-> (before, frontmatter_yaml, after). Raises if not a frontmatter file."""
    if not text.startswith("---"):
        raise ValueError("no frontmatter")
    end = text.index("\n---", 3)
    return text[:4], text[4:end + 1], text[end + 4:]


def load(path: Path) -> dict | None:
    try:
        _, fm, _ = split_frontmatter(path.read_text())
        d = yaml.safe_load(fm)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def predicted(d: dict) -> dict[str, float]:
    """Predictions already on disk, in the fields the corpus actually uses."""
    out: dict[str, float] = {}
    h = d.get("estimated_hours")
    if isinstance(h, (int, float)):
        out["hours"] = float(h)
    ei = d.get("expected_impact")
    if isinstance(ei, dict):
        ic = ei.get("impact_count_predicted")
        if isinstance(ic, (int, float)):
            out["impact_count"] = float(ic)
    return out


def observed(d: dict) -> dict[str, float]:
    o = d.get("outcomes")
    if not isinstance(o, dict):
        return {}
    return {k: float(v) for k, v in o.items()
            if k in QUANTITIES and isinstance(v, (int, float))}


def is_terminal(d: dict) -> bool:
    return str(d.get("status", "")).strip().lower() in TERMINAL


def tasks():
    for p in sorted(BACKLOG.glob("*.md")):
        d = load(p)
        if d and d.get("id") is not None:
            yield p, d


# ---------------------------------------------------------------- commands


def cmd_pending(args) -> int:
    """Closed tasks that made a prediction and never recorded the outcome."""
    rows = []
    for p, d in tasks():
        if not is_terminal(d):
            continue
        pred, obs = predicted(d), observed(d)
        missing = [q for q in pred if q not in obs]
        if missing:
            rows.append((d["id"], ",".join(missing), str(d.get("title", ""))[:58]))
    rows.sort()
    for tid, miss, title in rows:
        print(f"{tid:>6}  missing:{miss:<22} {title}")
    print(f"\n{len(rows)} closed task(s) with unscored predictions.")
    if rows:
        print("Score one with:  calibrate.py record <id> --hours N --impact N")
    return 0


def cmd_record(args) -> int:
    match = [(p, d) for p, d in tasks() if str(d["id"]) == str(args.task_id)]
    if not match:
        print(f"error: no task with id {args.task_id}", file=sys.stderr)
        return 1
    path, d = match[0]

    obs: dict[str, float] = {}
    if args.hours is not None:
        obs["hours"] = float(args.hours)
    if args.impact is not None:
        obs["impact_count"] = float(args.impact)
    if not obs:
        print("error: give at least one of --hours / --impact", file=sys.stderr)
        return 1

    pred = predicted(d)
    # Ratios only where a prediction exists. No prediction => not scored,
    # rather than scored against an invented baseline.
    calib = {}
    if "impact_count" in obs and pred.get("impact_count"):
        calib["impact_ratio"] = round(obs["impact_count"] / pred["impact_count"], 3)
    if "hours" in obs and pred.get("hours"):
        calib["duration_ratio"] = round(obs["hours"] / pred["hours"], 3)

    text = path.read_text()
    if re.search(r"^outcomes:", text[:text.index("\n---", 3)], re.M):
        print(f"error: task {args.task_id} already has outcomes; edit by hand",
              file=sys.stderr)
        return 1

    block = ["outcomes:"]
    for k, v in obs.items():
        block.append(f"  {k}: {v:g}")
    if calib:
        block.append("calibration:")
        for k, v in calib.items():
            block.append(f"  {k}: {v:g}")
    block.append(f"outcome_recorded_at: \"{now()}\"")
    if args.note:
        block.append(f"outcome_note: {json.dumps(args.note)}")

    end = text.index("\n---", 3)
    # The trailing newline is load-bearing: without it the closing `---` is
    # glued onto the last inserted line and the frontmatter stops parsing.
    path.write_text(text[:end + 1] + "\n".join(block) + "\n" + text[end + 1:])

    append_ledger({
        "ts": now(), "kind": "outcome.recorded",
        "subject": f"legion://backlog/{d['id']}",
        "payload": {"predicted": pred, "observed": obs, "calibration": calib},
        "actor": {"kind": "human", "id": "shawn"},
    })

    print(f"recorded on task-{d['id']}: {obs}")
    if calib:
        print(f"  calibration: {calib}")
    else:
        print("  (no matching prediction on file — outcome stored, not scored)")
    return 0


def cmd_report(args) -> int:
    pairs: dict[str, list[float]] = {q: [] for q in QUANTITIES}
    scored = 0
    for _, d in tasks():
        pred, obs = predicted(d), observed(d)
        hit = False
        for q in QUANTITIES:
            if q in pred and q in obs and pred[q] > 0 and obs[q] > 0:
                pairs[q].append(math.log(obs[q] / pred[q]))
                hit = True
        scored += hit

    total_pred = sum(1 for _, d in tasks() if predicted(d))
    print(f"scored tasks: {scored}   tasks carrying a prediction: {total_pred}\n")

    for q in QUANTITIES:
        xs = sorted(pairs[q])
        n = len(xs)
        if n < MIN_PAIRS:
            print(f"{q:<14} insufficient data ({n}/{MIN_PAIRS} pairs) — "
                  f"no correction offered")
            continue
        bias = median(xs)
        mad = median(sorted(abs(x - bias) for x in xs))
        lo, hi = math.exp(bias - mad), math.exp(bias + mad)
        print(f"{q:<14} n={n:<4} bias x{math.exp(bias):.2f}  "
              f"typical range x{lo:.2f}–x{hi:.2f}")
        print(f"{'':<14} → multiply your next {q} estimate by "
              f"{math.exp(bias):.2f}")
    return 0


# ---------------------------------------------------------------- helpers


def median(xs: list[float]) -> float:
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append_ledger(event: dict) -> None:
    with LEDGER.open("a") as f:
        f.write(json.dumps(event) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("pending", help="closed tasks with unscored predictions")

    r = sub.add_parser("record", help="record the outcome for a task")
    r.add_argument("task_id")
    r.add_argument("--hours", type=float)
    r.add_argument("--impact", type=float)
    r.add_argument("--note")

    sub.add_parser("report", help="bias and spread per quantity")

    args = ap.parse_args(argv)
    return {"pending": cmd_pending, "record": cmd_record,
            "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
