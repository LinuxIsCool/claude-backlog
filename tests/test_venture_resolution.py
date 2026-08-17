from pathlib import Path

from claude_backlog.venture_resolution import resolve_venture


def test_legion_historical_aliases_resolve_to_one_venture():
    for raw in ("Legion", "legion-platform", "legion-infra", "legion-systems",
                "legion-internal", "infrastructure", "legion (infrastructure)",
                "Longtail Financial / Legion infrastructure", "claude-dock"):
        resolution = resolve_venture(raw)
        assert resolution.canonical == "legion"
        assert resolution.status == "resolved"


def test_unknown_venture_is_visible_but_not_claimed_as_verified():
    resolution = resolve_venture("future-venture")
    assert resolution.canonical == "future-venture"
    assert resolution.status == "unverified"


def test_project_hint_is_preserved():
    resolution = resolve_venture("legion-platform", project="claude-webui")
    assert resolution.program == "legion-platform"
    assert resolution.project == "claude-webui"
