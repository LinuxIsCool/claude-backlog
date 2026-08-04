"""The reserve-id script is the only ID source /vision is allowed to use."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reserve-id"


def _run(root: Path, *args: str) -> list[str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env={"BACKLOG_ROOT": str(root), "PATH": "/usr/bin:/bin"},
        check=True,
    )
    return proc.stdout.split()


def test_single_reservation_is_monotonic(tmp_path: Path) -> None:
    (tmp_path / "task-40 - seed.md").write_text("---\nid: 40\n---\n")

    first = _run(tmp_path)
    second = _run(tmp_path)

    assert first == ["41"]
    assert second == ["42"]


def test_count_reserves_a_consecutive_block(tmp_path: Path) -> None:
    (tmp_path / "task-40 - seed.md").write_text("---\nid: 40\n---\n")

    assert _run(tmp_path, "--count", "3") == ["41", "42", "43"]


def test_two_concurrent_batches_never_overlap(tmp_path: Path) -> None:
    (tmp_path / "task-40 - seed.md").write_text("---\nid: 40\n---\n")

    procs = [
        subprocess.Popen(
            [sys.executable, str(SCRIPT), "--count", "8"],
            stdout=subprocess.PIPE,
            text=True,
            env={"BACKLOG_ROOT": str(tmp_path), "PATH": "/usr/bin:/bin"},
        )
        for _ in range(4)
    ]
    ids = [int(x) for p in procs for x in p.communicate()[0].split()]

    assert len(ids) == 32
    assert len(set(ids)) == 32, "concurrent reservations collided"
