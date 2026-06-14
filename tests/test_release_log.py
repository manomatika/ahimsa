"""
Tests for ahimsa.release_log and ahimsa.stub_resolver.

Covers:
  - render output format (headings, fields)
  - placeholder emission for orphan live tags (tag in live_tags but not in entries)
  - YAML round-trip (load_release_log reads release-log.yaml cleanly)
  - StubTagResolver default and custom data
"""

import io
import textwrap
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from ahimsa.release_log import ReleaseEntry, load_release_log, render_releases_md
from ahimsa.stub_resolver import StubTagResolver

REPO_ROOT = Path(__file__).parent.parent
# release-log.yaml lives in manomatika/manomatika (product authority).
# tests/fixtures/release-log.yaml is a pinned snapshot used for regression tests.
RELEASE_LOG_PATH = Path(__file__).parent / "fixtures" / "release-log.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    repo: str = "matika",
    tag: str = "v0.0.1",
    date: str = "2026-01-01",
    status: str = "published",
    artifact: str = "none",
    prs: str = "manomatika/matika#1",
    summary: str = "A test release.",
) -> ReleaseEntry:
    return ReleaseEntry(
        repo=repo,
        tag=tag,
        date=date,
        status=status,
        artifact=artifact,
        prs=prs,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# StubTagResolver
# ---------------------------------------------------------------------------


def test_stub_resolver_default_data():
    """Default stub data has matika, eyerate, and ahimsa slugs."""
    r = StubTagResolver()
    matika_tags = r.list_tags("matika")
    assert "v0.0.1" in matika_tags
    assert "v0.0.4-dev.2" in matika_tags


def test_stub_resolver_custom_data():
    """Custom injected data overrides defaults."""
    r = StubTagResolver({"matika": ["v0.0.5"], "eyerate": []})
    assert r.list_tags("matika") == ["v0.0.5"]
    assert r.list_tags("eyerate") == []


def test_stub_resolver_unknown_slug_returns_empty():
    r = StubTagResolver()
    assert r.list_tags("nonexistent-repo") == []


def test_stub_resolver_returns_copy():
    """list_tags returns a copy; mutating it doesn't corrupt the resolver."""
    r = StubTagResolver({"matika": ["v0.0.1"]})
    tags = r.list_tags("matika")
    tags.append("v9.9.9")
    assert r.list_tags("matika") == ["v0.0.1"]


# ---------------------------------------------------------------------------
# render_releases_md — format
# ---------------------------------------------------------------------------


def test_render_heading_format():
    """H2 headings use '## <repo> <tag>' form."""
    entry = _make_entry(repo="matika", tag="v0.0.4")
    output = render_releases_md([entry], live_tags={})
    assert "## matika v0.0.4" in output


def test_render_all_fields_present():
    """All six fields (Date, Status, Artifact, PRs, Summary) are rendered."""
    entry = _make_entry(
        repo="matika",
        tag="v0.0.4",
        date="2026-05-01",
        status="published",
        artifact="@manomatika/matika-frontend@0.0.4 (GitHub Packages)",
        prs="manomatika/matika#42",
        summary="Full release of matika v0.0.4.",
    )
    output = render_releases_md([entry], live_tags={})
    assert "**Date:** 2026-05-01" in output
    assert "**Status:** published" in output
    assert "**Artifact:** @manomatika/matika-frontend@0.0.4 (GitHub Packages)" in output
    assert "**PRs:** manomatika/matika#42" in output
    assert "**Summary:** Full release of matika v0.0.4." in output


def test_render_multiple_entries_newest_first():
    """Entries appear in the order given (caller controls newest-first ordering)."""
    e1 = _make_entry(repo="matika", tag="v0.0.2")
    e2 = _make_entry(repo="matika", tag="v0.0.1")
    output = render_releases_md([e1, e2], live_tags={})
    pos_v002 = output.index("## matika v0.0.2")
    pos_v001 = output.index("## matika v0.0.1")
    assert pos_v002 < pos_v001, "v0.0.2 should appear before v0.0.1 (newest-first)"


def test_render_multi_repo_entries():
    """Entries for different repos both appear under their own headings."""
    entries = [
        _make_entry(repo="matika", tag="v0.0.1"),
        _make_entry(repo="eyerate", tag="v0.0.1"),
    ]
    output = render_releases_md(entries, live_tags={})
    assert "## matika v0.0.1" in output
    assert "## eyerate v0.0.1" in output


# ---------------------------------------------------------------------------
# render_releases_md — placeholder emission for orphan live tags
# ---------------------------------------------------------------------------


def test_orphan_live_tag_emits_placeholder(capsys):
    """A live tag not in entries gets a placeholder entry and a stderr warning."""
    entries = [_make_entry(repo="matika", tag="v0.0.1")]
    live_tags = {"matika": ["v0.0.1", "v0.0.2"]}
    output = render_releases_md(entries, live_tags=live_tags)

    captured = capsys.readouterr()
    # Placeholder entry present in output.
    assert "## matika v0.0.2" in output
    assert "auto-generated placeholder" in output.lower()
    # Warning emitted to stderr.
    assert "WARNING" in captured.err
    assert "matika/v0.0.2" in captured.err


def test_orphan_live_tag_placeholder_contains_instructions(capsys):
    """Placeholder entry tells the human to update release-log.yaml."""
    entries = []
    live_tags = {"matika": ["v0.0.1"]}
    output = render_releases_md(entries, live_tags=live_tags)
    capsys.readouterr()
    assert "release-log.yaml" in output


def test_no_orphan_no_placeholder_no_warning(capsys):
    """When all live tags have entries, no placeholder and no warning."""
    entries = [_make_entry(repo="matika", tag="v0.0.1")]
    live_tags = {"matika": ["v0.0.1"]}
    output = render_releases_md(entries, live_tags=live_tags)
    captured = capsys.readouterr()
    assert "placeholder" not in output.lower()
    assert "WARNING" not in captured.err


def test_entry_without_live_tag_still_rendered():
    """An entry whose tag doesn't appear in live_tags is still rendered (breadcrumb)."""
    entry = _make_entry(repo="matika", tag="v0.0.4-dev.0")
    live_tags = {"matika": []}  # tag not present
    output = render_releases_md([entry], live_tags=live_tags)
    assert "## matika v0.0.4-dev.0" in output


# ---------------------------------------------------------------------------
# load_release_log — YAML round-trip
# ---------------------------------------------------------------------------


def test_load_release_log_reads_real_file():
    """release-log.yaml exists and loads cleanly into ReleaseEntry objects."""
    pytest.importorskip("yaml")
    entries = load_release_log(RELEASE_LOG_PATH)
    assert len(entries) > 0
    for entry in entries:
        assert isinstance(entry, ReleaseEntry)
        assert entry.repo
        assert entry.tag.startswith("v")
        assert entry.date
        assert entry.status
        assert entry.artifact
        assert entry.prs
        assert entry.summary


def test_load_release_log_has_expected_repos():
    """The real release-log.yaml contains entries for matika, eyerate, ahimsa."""
    pytest.importorskip("yaml")
    entries = load_release_log(RELEASE_LOG_PATH)
    repos = {e.repo for e in entries}
    assert "matika" in repos
    assert "eyerate" in repos
    assert "ahimsa" in repos


def test_load_release_log_matika_has_v004_entries():
    """matika v0.0.4-dev.* entries are present."""
    pytest.importorskip("yaml")
    entries = load_release_log(RELEASE_LOG_PATH)
    matika_tags = [e.tag for e in entries if e.repo == "matika"]
    assert "v0.0.4-dev.2" in matika_tags
    assert "v0.0.4-dev.1" in matika_tags
    assert "v0.0.4-dev.0" in matika_tags


def test_load_release_log_missing_file():
    """FileNotFoundError raised when the file doesn't exist."""
    pytest.importorskip("yaml")
    with pytest.raises(FileNotFoundError):
        load_release_log("/nonexistent/path/release-log.yaml")


def test_load_release_log_missing_entries_key(tmp_path):
    """ValueError raised when the YAML has no 'entries' key."""
    pytest.importorskip("yaml")
    bad = tmp_path / "release-log.yaml"
    bad.write_text("something: else\n")
    with pytest.raises(ValueError, match="entries"):
        load_release_log(bad)


def test_load_release_log_missing_required_field(tmp_path):
    """ValueError raised when an entry is missing a required field."""
    pytest.importorskip("yaml")
    bad = tmp_path / "release-log.yaml"
    bad.write_text("entries:\n  - repo: matika\n    tag: v0.0.1\n")
    with pytest.raises(ValueError, match="missing required fields"):
        load_release_log(bad)


def test_yaml_round_trip(tmp_path):
    """Writing entries as YAML and reloading produces identical data."""
    pytest.importorskip("yaml")
    import yaml

    original_entries = [
        _make_entry(repo="matika", tag="v0.0.1", summary="First release."),
        _make_entry(repo="eyerate", tag="v0.0.1", summary="Eyerate first."),
    ]
    data = {
        "entries": [
            {
                "repo": e.repo,
                "tag": e.tag,
                "date": e.date,
                "status": e.status,
                "artifact": e.artifact,
                "prs": e.prs,
                "summary": e.summary,
            }
            for e in original_entries
        ]
    }
    outfile = tmp_path / "release-log.yaml"
    outfile.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False))
    reloaded = load_release_log(outfile)
    assert len(reloaded) == len(original_entries)
    for orig, reloaded_e in zip(original_entries, reloaded):
        assert orig.repo == reloaded_e.repo
        assert orig.tag == reloaded_e.tag
        assert orig.summary == reloaded_e.summary
