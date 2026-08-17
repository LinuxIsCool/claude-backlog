"""The reserve-id script is the only ID source /vision is allowed to use."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reserve-id"


def _run(root, *args):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.split()


def test_single_reservation_is_monotonic(tmp_path):
    (tmp_path / "task-40 - seed.md").write_text("---\nid: 40\n---\n")
    first = _run(tmp_path)
    second = _run(tmp_path)
    assert first == ["41"]
    assert second == ["42"]


def test_count_reserves_a_consecutive_block(tmp_path):
    (tmp_path / "task-40 - seed.md").write_text("---\nid: 40\n---\n")
    assert _run(tmp_path, "--count", "3") == ["41", "42", "43"]
    assert _run(tmp_path) == ["44"]


def test_two_concurrent_batches_never_overlap(tmp_path):
    (tmp_path / "task-40 - seed.md").write_text("---\nid: 40\n---\n")
    procs = [
        subprocess.Popen(
            [sys.executable, str(SCRIPT), str(tmp_path), "--count", "8"],
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(8)
    ]
    ids = [int(x) for p in procs for x in p.communicate()[0].split()]
    assert len(ids) == 64
    assert len(set(ids)) == 64, "concurrent reservations collided"
