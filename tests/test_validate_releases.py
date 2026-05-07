"""
Tests for ahimsa.validate_releases.

All tests run offline. Network-dependent behavior is intercepted by
injecting BaseResolver subclasses via the `resolvers={"github.com": mock}`
parameter, mirroring tests/test_validate_recipe.py.
"""

import json
from pathlib import Path

import pytest

from ahimsa.validate_recipe import (
    AppLugManifest,
    BaseResolver,
    Error,
    validate,
)
from ahimsa.validate_releases import parse_entries, validate_releases


REPO = "github.com/manomatika/Matika"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "releases_md"


# ---------------------------------------------------------------------------
# Mock resolvers
# ---------------------------------------------------------------------------


class _ReleasesMock(BaseResolver):
    """Single-repo mock returning canned RELEASES.md text and tag list."""

    def __init__(
        self,
        *,
        releases_md: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        super().__init__(host="github.com")
        self._text = releases_md
        self._tags = list(tags) if tags is not None else []

    def _canonicalize_repo(self, owner: str, repo: str) -> tuple[str, str]:
        return (owner, repo)

    def _raw_url(self, canonical: tuple[str, str], tag: str, path: str) -> str:
        return ""

    def fetch_text(self, repo: str, ref: str, path: str) -> str | None:
        return self._text

    def list_tags(self, repo: str) -> list[str]:
        return list(self._tags)


class _MultiRepoMock(BaseResolver):
    """Repo-aware mock for transitive-integration tests.

    responses: {repo_spec: {"releases_md": str | None, "tags": list[str],
                             "manifest": AppLugManifest | None}}
    """

    def __init__(self, responses: dict[str, dict]) -> None:
        super().__init__(host="github.com")
        self._responses = responses

    def _canonicalize_repo(self, owner: str, repo: str) -> tuple[str, str]:
        return (owner, repo)

    def _raw_url(self, canonical: tuple[str, str], tag: str, path: str) -> str:
        return ""

    def resolve(self, name: str, repo: str, tag: str) -> AppLugManifest:
        manifest = self._responses.get(repo, {}).get("manifest")
        if manifest is None:
            raise FileNotFoundError(f"no manifest configured for {repo}")
        return manifest

    def fetch_text(self, repo: str, ref: str, path: str) -> str | None:
        return self._responses.get(repo, {}).get("releases_md")

    def list_tags(self, repo: str) -> list[str]:
        return list(self._responses.get(repo, {}).get("tags", []))


# ---------------------------------------------------------------------------
# parse_entries — direct unit tests
# ---------------------------------------------------------------------------


def test_parse_entries_extracts_h2_tag_headings():
    text = "## v0.0.4-dev.1\n\nbody\n\n## v0.0.4-dev.0\n"
    assert parse_entries(text) == ["v0.0.4-dev.1", "v0.0.4-dev.0"]


def test_parse_entries_ignores_preamble_and_non_tag_h2():
    text = (
        "# Releases\n"
        "Some prose.\n"
        "## Releases\n"
        "## Some Other Heading\n"
        "## v0.0.4\n"
    )
    assert parse_entries(text) == ["v0.0.4"]


def test_parse_entries_rejects_trailing_junk_in_heading():
    text = "## v0.0.4-dev.1 (notes)\n## v0.0.4-dev.0\n"
    # Only the clean heading is captured; the junk-decorated one is silently dropped.
    assert parse_entries(text) == ["v0.0.4-dev.0"]


def test_parse_entries_preserves_duplicates_in_order():
    text = "## v0.0.4\n## v0.0.4\n## v0.0.5\n"
    assert parse_entries(text) == ["v0.0.4", "v0.0.4", "v0.0.5"]


def test_parse_entries_empty_text_returns_empty():
    assert parse_entries("") == []


# ---------------------------------------------------------------------------
# validate_releases — happy path and drift cases
# ---------------------------------------------------------------------------


def test_happy_path_zero_errors():
    """Tags and entries align perfectly → no errors."""
    text = "## v0.0.4-dev.1\n\n## v0.0.4-dev.0\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.1", "v0.0.4-dev.0"],
    )
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    assert errors == []


def test_missing_entry_for_existing_tag():
    """Tag exists but no matching entry."""
    text = "## v0.0.4-dev.0\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.0", "v0.0.4-dev.1"],
    )
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.tag["v0.0.4-dev.1"]'
    assert "tag exists but no entry" in errors[0].message


def test_orphan_entry_with_no_matching_tag():
    """Entry exists but no matching tag."""
    text = "## v0.0.4-dev.1\n## v0.0.4-dev.99\n"
    mock = _ReleasesMock(releases_md=text, tags=["v0.0.4-dev.1"])
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.entry["v0.0.4-dev.99"]'
    assert "tag does not exist" in errors[0].message


def test_combined_drift_reports_both_directions():
    """A repo with both missing-entry and orphan-entry drift reports both."""
    text = "## v0.0.4-dev.0\n## v0.0.4-dev.99\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.0", "v0.0.4-dev.1"],
    )
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    pointers = sorted(e.pointer for e in errors)
    assert pointers == [
        'releases.entry["v0.0.4-dev.99"]',
        'releases.tag["v0.0.4-dev.1"]',
    ]


# ---------------------------------------------------------------------------
# validate_releases — file presence and emptiness
# ---------------------------------------------------------------------------


def test_no_releases_md_is_a_noop():
    """Resolver returning None for fetch_text → zero errors regardless of tags."""
    mock = _ReleasesMock(
        releases_md=None,
        tags=["v0.0.4", "v0.0.4-dev.1"],
    )
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    assert errors == []


def test_empty_releases_md_with_tags_is_all_missing():
    """RELEASES.md present but parseable-empty: every tag is a missing-entry error."""
    mock = _ReleasesMock(releases_md="", tags=["v0.0.4-dev.0", "v0.0.4-dev.1"])
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    pointers = sorted(e.pointer for e in errors)
    assert pointers == [
        'releases.tag["v0.0.4-dev.0"]',
        'releases.tag["v0.0.4-dev.1"]',
    ]


def test_empty_releases_md_with_no_tags_is_clean():
    """Empty file + zero tags → trivially consistent, no errors."""
    mock = _ReleasesMock(releases_md="", tags=[])
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    assert errors == []


# ---------------------------------------------------------------------------
# validate_releases — duplicates, ignored tags, status irrelevance
# ---------------------------------------------------------------------------


def test_duplicate_entry_emits_error():
    """Same tag heading appearing twice in RELEASES.md → duplicate-entry error."""
    text = "## v0.0.4\n## v0.0.4\n"
    mock = _ReleasesMock(releases_md=text, tags=["v0.0.4"])
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    pointers = [e.pointer for e in errors]
    assert 'releases.entry["v0.0.4"]' in pointers
    assert any("duplicate entry" in e.message for e in errors)


def test_non_conforming_tags_are_ignored():
    """Tags like 'legacy-rev' that don't match the version regex are out of scope."""
    text = "## v0.0.4-dev.1\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.1", "legacy-rev", "release-1", "v0.0"],
    )
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    assert errors == []


def test_status_field_does_not_affect_validation():
    """Entry with `Status: superseded` or `Status: failed` still counts as an entry."""
    text = (
        "## v0.0.4-dev.1\n"
        "- **Status:** published\n\n"
        "## v0.0.4-dev.0\n"
        "- **Status:** superseded (by v0.0.4-dev.1)\n"
    )
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.0", "v0.0.4-dev.1"],
    )
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    assert errors == []


def test_trailing_junk_in_heading_is_treated_as_missing():
    """`## v0.0.4 (notes)` does not parse as an entry; tag becomes missing."""
    text = "## v0.0.4-dev.1 (notes)\n"
    mock = _ReleasesMock(releases_md=text, tags=["v0.0.4-dev.1"])
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.tag["v0.0.4-dev.1"]'


# ---------------------------------------------------------------------------
# validate_releases — real-world snapshot fixture
# ---------------------------------------------------------------------------


def test_real_matika_snapshot_round_trips_cleanly():
    """The frozen snapshot of matika's RELEASES.md round-trips with its tag list.

    This is a sanity check against the actual artifact, NOT a check on matika's
    current state. The fixture is deliberately frozen — see the file header.
    """
    text = (FIXTURE_DIR / "matika.md").read_text()
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.0", "v0.0.4-dev.1"],
    )
    errors = validate_releases(REPO, resolvers={"github.com": mock})
    assert errors == []


# ---------------------------------------------------------------------------
# validate_releases — host dispatch
# ---------------------------------------------------------------------------


def test_unknown_host_in_resolvers_dict_emits_error():
    """If `resolvers` is provided but doesn't include the repo's host."""
    mock = _ReleasesMock(releases_md=None, tags=[])
    errors = validate_releases(
        "example.com/foo/bar",
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == "releases.repo"
    assert 'no resolver for host "example.com"' in errors[0].message


def test_disallowed_host_via_allowed_hosts_emits_error():
    """If `allowed_hosts` excludes the repo's host."""
    errors = validate_releases(
        "example.com/foo/bar",
        allowed_hosts=["github.com"],
    )
    assert len(errors) == 1
    assert errors[0].pointer == "releases.repo"
    assert 'host "example.com" not in allowed_hosts' in errors[0].message


# ---------------------------------------------------------------------------
# Transitive integration with validate_recipe.validate()
# ---------------------------------------------------------------------------


def _write_recipe(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "recipe.json"
    p.write_text(json.dumps(data))
    return p


_VALID_RECIPE = {
    "application": {
        "name": "Test App",
        "version": "1.0.0",
        "bundle_id": "com.example.test",
        "icon": "assets/icon.icns",
    },
    "matika": {
        "version": "0.0.4",
        "repo": "github.com/manomatika/Matika",
        "tag": "v0.0.4",
    },
    "applugs": [
        {
            "name": "eyerate",
            "repo": "github.com/manomatika/EyeRate",
            "version": "0.0.4",
            "matika_version": "0.0.4",
            "tag": "v0.0.4",
        }
    ],
}


def test_transitive_drift_in_matika_surfaces_with_matika_pointer(tmp_path):
    """Drift in matika.repo's release log surfaces under the `matika.releases.*` pointer."""
    recipe_path = _write_recipe(tmp_path, _VALID_RECIPE)

    mock = _MultiRepoMock({
        "github.com/manomatika/Matika": {
            # Tag v0.0.4 exists but RELEASES.md has no matching entry.
            "releases_md": "## v0.0.3\n",
            "tags": ["v0.0.3", "v0.0.4"],
            "manifest": AppLugManifest(id="matika", version="0.0.4", matika_version="0.0.4"),
        },
        "github.com/manomatika/EyeRate": {
            # No RELEASES.md → no-op for this repo.
            "releases_md": None,
            "tags": [],
            "manifest": AppLugManifest(id="eyerate", version="0.0.4", matika_version="0.0.4"),
        },
    })

    errors = validate(recipe_path, resolvers={"github.com": mock})
    matika_release_errors = [e for e in errors if e.pointer.startswith("matika.releases")]
    assert len(matika_release_errors) == 1
    assert matika_release_errors[0].pointer == 'matika.releases.tag["v0.0.4"]'
    assert "tag exists but no entry" in matika_release_errors[0].message


def test_transitive_drift_in_applug_surfaces_with_applugs_pointer(tmp_path):
    """Drift in an applug's release log surfaces under `applugs[i].releases.*`."""
    recipe_path = _write_recipe(tmp_path, _VALID_RECIPE)

    mock = _MultiRepoMock({
        "github.com/manomatika/Matika": {
            "releases_md": None,
            "tags": [],
            "manifest": AppLugManifest(id="matika", version="0.0.4", matika_version="0.0.4"),
        },
        "github.com/manomatika/EyeRate": {
            # Orphan entry — RELEASES.md mentions a tag that doesn't exist.
            "releases_md": "## v0.0.5\n",
            "tags": [],
            "manifest": AppLugManifest(id="eyerate", version="0.0.4", matika_version="0.0.4"),
        },
    })

    errors = validate(recipe_path, resolvers={"github.com": mock})
    applug_release_errors = [
        e for e in errors if e.pointer.startswith("applugs[0].releases")
    ]
    assert len(applug_release_errors) == 1
    assert applug_release_errors[0].pointer == 'applugs[0].releases.entry["v0.0.5"]'


def test_transitive_clean_when_all_repos_have_no_releases_md(tmp_path):
    """All repos opting out (no RELEASES.md) → recipe validates with no release errors."""
    recipe_path = _write_recipe(tmp_path, _VALID_RECIPE)

    mock = _MultiRepoMock({
        "github.com/manomatika/Matika": {
            "releases_md": None,
            "tags": [],
            "manifest": AppLugManifest(id="matika", version="0.0.4", matika_version="0.0.4"),
        },
        "github.com/manomatika/EyeRate": {
            "releases_md": None,
            "tags": [],
            "manifest": AppLugManifest(id="eyerate", version="0.0.4", matika_version="0.0.4"),
        },
    })

    errors = validate(recipe_path, resolvers={"github.com": mock})
    release_errors = [e for e in errors if ".releases" in e.pointer]
    assert release_errors == []
