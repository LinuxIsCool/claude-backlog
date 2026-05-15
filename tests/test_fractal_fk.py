"""Tests for FractalFKValidator — validates parent_id + parent_type against
the claude-ventures filesystem layout.

Mirror of claude-ventures/tests/validation/fk.test.ts (TS).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fractal_fk import FractalFKValidator  # noqa: E402  # pyright: ignore[reportMissingImports]


@pytest.fixture
def ventures_root(tmp_path: Path) -> Path:
    return tmp_path / "ventures"


def _seed_venture(root: Path, slug: str) -> None:
    stage_dir = root / "active"
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / f"{slug}.md").write_text(f"---\nslug: {slug}\n---\n")


def _seed_project(root: Path, venture: str, slug: str) -> None:
    pdir = root / venture / "projects" / slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.md").write_text(f"---\nslug: {slug}\nventure: {venture}\n---\n")


def _seed_milestone(root: Path, venture: str, project: str, slug: str) -> None:
    mdir = root / venture / "projects" / project / "milestones"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / f"{slug}.md").write_text(
        f"---\nslug: {slug}\nproject: {project}\nventure: {venture}\n---\n"
    )


def test_resolves_venture(ventures_root: Path) -> None:
    _seed_venture(ventures_root, "bcrg")
    v = FractalFKValidator(ventures_root)
    r = v.resolve("bcrg", "venture")
    assert r.ok is True


def test_resolves_project(ventures_root: Path) -> None:
    _seed_venture(ventures_root, "bcrg")
    _seed_project(ventures_root, "bcrg", "tbff")
    v = FractalFKValidator(ventures_root)
    r = v.resolve("bcrg.tbff", "project")
    assert r.ok is True


def test_resolves_milestone(ventures_root: Path) -> None:
    _seed_venture(ventures_root, "bcrg")
    _seed_project(ventures_root, "bcrg", "tbff")
    _seed_milestone(ventures_root, "bcrg", "tbff", "m1-spec")
    v = FractalFKValidator(ventures_root)
    r = v.resolve("bcrg.tbff.m1-spec", "milestone")
    assert r.ok is True


def test_rejects_missing_venture(ventures_root: Path) -> None:
    v = FractalFKValidator(ventures_root)
    r = v.resolve("missing", "venture")
    assert r.ok is False
    assert "not found" in r.error


def test_rejects_level_mismatch(ventures_root: Path) -> None:
    _seed_venture(ventures_root, "bcrg")
    v = FractalFKValidator(ventures_root)
    r = v.resolve("bcrg", "milestone")
    assert r.ok is False
    assert "level mismatch" in r.error


def test_rejects_invalid_parent_type(ventures_root: Path) -> None:
    v = FractalFKValidator(ventures_root)
    r = v.resolve("bcrg", "task")
    assert r.ok is False
    assert "invalid parent_type" in r.error


def test_rejects_invalid_slug_segment(ventures_root: Path) -> None:
    v = FractalFKValidator(ventures_root)
    r = v.resolve("BCRG.UPPER", "project")
    assert r.ok is False
