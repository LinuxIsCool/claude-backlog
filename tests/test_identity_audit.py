import json
import subprocess
from pathlib import Path

from claude_backlog.identity_audit import audit


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit-task-identity"


def _write(root: Path, name: str, frontmatter: str) -> None:
    (root / name).write_text(f"---\n{frontmatter}\n---\nbody\n", encoding="utf-8")


def test_audit_distinguishes_identity_failure_classes(tmp_path):
    _write(tmp_path, "task-1 - canonical.md", "id: 1\nventure: legion")
    _write(tmp_path, "2-legacy.md", "id: 9")
    _write(tmp_path, "task-3 - first.md", "id: shared")
    _write(tmp_path, "unrecognized.md", "id: shared")
    (tmp_path / "broken.md").write_text("---\ntitle: [broken\n---\n")

    report = audit(tmp_path)

    assert report["counts"] == {
        "files_scanned": 5,
        "frontmatter_parsed": 4,
        "parse_failed": 1,
        "filename_id_missing": 2,
        "frontmatter_id_missing": 1,
        "filename_frontmatter_disagreements": 2,
        "contested_filename_ids": 0,
        "files_claiming_contested_filename_ids": 0,
        "contested_frontmatter_ids": 1,
        "files_claiming_contested_frontmatter_ids": 2,
        "venture_null": 3,
    }
    assert report["contested_frontmatter_ids"] == {
        "shared": ["task-3 - first.md", "unrecognized.md"]
    }


def test_audit_script_writes_machine_readable_report(tmp_path):
    root = tmp_path / "backlog"
    root.mkdir()
    _write(root, "task-7 - example.md", "id: 7")
    output = tmp_path / "report.json"

    subprocess.run(
        [str(SCRIPT), str(root), "--output", str(output)],
        check=True,
    )

    assert json.loads(output.read_text())["counts"]["files_scanned"] == 1
