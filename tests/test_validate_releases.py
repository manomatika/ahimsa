"""
Tests for ahimsa.validate_releases.

All tests run offline. Network-dependent behavior is intercepted by
injecting BaseResolver subclasses via the `resolvers={"github.com": mock}`
parameter, mirroring tests/test_validate_recipe.py.

The central RELEASES.md lives in manomatika/manomatika (product authority).
Headings use the two-part form ``## <repo-slug> <tag>`` (e.g. ``## matika
v0.0.4``). The validator fetches RELEASES.md once and audits each repo's tag
list against the entries for that slug.

For single-repo tests we pass ``ahimsa_repo=REPO`` so the same mock instance
serves both the RELEASES.md fetch and the tag-list fetch (from the target
repo). The ``ahimsa_repo`` parameter name is retained for backward
compatibility; it now refers to the product-authority repo (mm). For
multi-repo tests the mock must have an explicit RELEASES.md-host entry.
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


# Canonical repo spec used in most single-repo tests.
REPO = "github.com/manomatika/matika"
AHIMSA_REPO = "github.com/manomatika/ahimsa"
# MM_REPO is the default RELEASES.md host (manomatika/manomatika).
MM_REPO = "github.com/manomatika/manomatika"

# The fixture dir still exists for the snapshot test (updated format).
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "releases_md"


# ---------------------------------------------------------------------------
# Mock resolvers
# ---------------------------------------------------------------------------


class _ReleasesMock(BaseResolver):
    """Single-repo mock.

    ``releases_md`` is served for ANY fetch_text call (used both for the ahimsa
    RELEASES.md fetch and, if needed, for the target repo). ``tags`` is returned
    for any list_tags call.
    """

    def __init__(
        self,
        *,
        releases_md: str | None = None,
        tags: list[str] | None = None,
        release_log: str | None = None,
    ) -> None:
        super().__init__(host="github.com")
        self._text = releases_md
        self._tags = list(tags) if tags is not None else []
        self._release_log = release_log

    def _canonicalize_repo(self, owner: str, repo: str) -> tuple[str, str]:
        return (owner, repo)

    def _raw_url(self, canonical: tuple[str, str], tag: str, path: str) -> str:
        return ""

    def fetch_text(self, repo: str, ref: str, path: str) -> str | None:
        if path == "release-log.yaml":
            return self._release_log
        return self._text

    def list_tags(self, repo: str) -> list[str]:
        return list(self._tags)


class _MultiRepoMock(BaseResolver):
    """Repo-aware mock for transitive-integration tests.

    responses: {repo_spec: {"releases_md": str | None, "tags": list[str],
                             "manifest": AppLugManifest | None}}

    The mm entry (keyed by MM_REPO = github.com/manomatika/manomatika) must
    provide "releases_md" so the validator can fetch the central RELEASES.md.
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
        if path == "release-log.yaml":
            return self._responses.get(repo, {}).get("release_log")
        return self._responses.get(repo, {}).get("releases_md")

    def list_tags(self, repo: str) -> list[str]:
        return list(self._responses.get(repo, {}).get("tags", []))


# ---------------------------------------------------------------------------
# parse_entries — direct unit tests
# ---------------------------------------------------------------------------


def test_parse_entries_extracts_h2_repo_slug_tag_headings():
    """New two-part heading format: ## <slug> <tag>."""
    text = "## matika v0.0.4-dev.1\n\nbody\n\n## matika v0.0.4-dev.0\n"
    assert parse_entries(text) == [
        ("matika", "v0.0.4-dev.1"),
        ("matika", "v0.0.4-dev.0"),
    ]


def test_parse_entries_multiple_repo_slugs():
    """Entries for different repos in the same file."""
    text = (
        "## matika v0.0.4\n"
        "## eyerate v0.0.4\n"
        "## ahimsa v0.0.1\n"
    )
    assert parse_entries(text) == [
        ("matika", "v0.0.4"),
        ("eyerate", "v0.0.4"),
        ("ahimsa", "v0.0.1"),
    ]


def test_parse_entries_ignores_preamble_and_non_tag_h2():
    text = (
        "# Releases\n"
        "Some prose.\n"
        "## Releases\n"
        "## Some Other Heading\n"
        "## matika v0.0.4\n"
    )
    assert parse_entries(text) == [("matika", "v0.0.4")]


def test_parse_entries_rejects_trailing_junk_in_heading():
    text = "## matika v0.0.4-dev.1 (notes)\n## matika v0.0.4-dev.0\n"
    # Only the clean heading is captured; the junk-decorated one is dropped.
    assert parse_entries(text) == [("matika", "v0.0.4-dev.0")]


def test_parse_entries_rejects_old_single_part_tag_heading():
    """Old-format headings like '## v0.0.4' (no slug) are NOT parsed."""
    text = "## v0.0.4\n## matika v0.0.4\n"
    assert parse_entries(text) == [("matika", "v0.0.4")]


def test_parse_entries_preserves_duplicates_in_order():
    text = "## matika v0.0.4\n## matika v0.0.4\n## matika v0.0.5\n"
    assert parse_entries(text) == [
        ("matika", "v0.0.4"),
        ("matika", "v0.0.4"),
        ("matika", "v0.0.5"),
    ]


def test_parse_entries_empty_text_returns_empty():
    assert parse_entries("") == []


# ---------------------------------------------------------------------------
# validate_releases — happy path and drift cases (single repo)
# ---------------------------------------------------------------------------


def test_happy_path_zero_errors():
    """Tags and entries align perfectly -> no errors."""
    text = "## matika v0.0.4-dev.1\n\n## matika v0.0.4-dev.0\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.1", "v0.0.4-dev.0"],
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []


def test_missing_entry_for_existing_tag():
    """Tag exists but no matching entry."""
    text = "## matika v0.0.4-dev.0\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.0", "v0.0.4-dev.1"],
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.tag["v0.0.4-dev.1"]'
    assert "tag exists but no entry" in errors[0].message


def test_orphan_entry_with_no_matching_tag():
    """Entry exists but no matching tag."""
    text = "## matika v0.0.4-dev.1\n## matika v0.0.4-dev.99\n"
    mock = _ReleasesMock(releases_md=text, tags=["v0.0.4-dev.1"])
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.entry["v0.0.4-dev.99"]'
    assert "tag does not exist" in errors[0].message


def test_combined_drift_reports_both_directions():
    """A repo with both missing-entry and orphan-entry drift reports both."""
    text = "## matika v0.0.4-dev.0\n## matika v0.0.4-dev.99\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.0", "v0.0.4-dev.1"],
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    pointers = sorted(e.pointer for e in errors)
    assert pointers == [
        'releases.entry["v0.0.4-dev.99"]',
        'releases.tag["v0.0.4-dev.1"]',
    ]


# ---------------------------------------------------------------------------
# validate_releases — file presence and emptiness
# ---------------------------------------------------------------------------


def test_no_releases_md_is_a_noop():
    """Resolver returning None for fetch_text -> zero errors regardless of tags."""
    mock = _ReleasesMock(
        releases_md=None,
        tags=["v0.0.4", "v0.0.4-dev.1"],
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []


def test_empty_releases_md_with_tags_is_all_missing():
    """RELEASES.md present but parseable-empty: every tag is a missing-entry error."""
    mock = _ReleasesMock(releases_md="", tags=["v0.0.4-dev.0", "v0.0.4-dev.1"])
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    pointers = sorted(e.pointer for e in errors)
    assert pointers == [
        'releases.tag["v0.0.4-dev.0"]',
        'releases.tag["v0.0.4-dev.1"]',
    ]


def test_empty_releases_md_with_no_tags_is_clean():
    """Empty file + zero tags -> trivially consistent, no errors."""
    mock = _ReleasesMock(releases_md="", tags=[])
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []


def test_empty_repos_list_is_a_noop():
    """Passing an empty repos list -> no errors (nothing to validate)."""
    mock = _ReleasesMock(releases_md="## matika v0.0.4\n", tags=["v0.0.4"])
    errors = validate_releases(
        [],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []


# ---------------------------------------------------------------------------
# validate_releases — collision safety (multi-repo same-version tags)
# ---------------------------------------------------------------------------


def test_same_version_tag_in_different_repos_is_not_a_collision():
    """## matika v0.0.1 and ## eyerate v0.0.1 must NOT be flagged as duplicates.

    This is the collision-safety fixture: two repos sharing the same version
    string are distinct (repo_slug, tag) pairs and must not collide.
    """
    text = "## matika v0.0.1\n## eyerate v0.0.1\n"
    mock = _MultiRepoMock({
        AHIMSA_REPO: {"releases_md": text, "tags": []},
        "github.com/manomatika/matika": {"releases_md": text, "tags": ["v0.0.1"]},
        "github.com/manomatika/eyerate": {"releases_md": text, "tags": ["v0.0.1"]},
    })
    errors = validate_releases(
        ["github.com/manomatika/matika", "github.com/manomatika/eyerate"],
        ahimsa_repo=AHIMSA_REPO,
        resolvers={"github.com": mock},
    )
    assert errors == [], f"Expected no errors but got: {errors}"


# ---------------------------------------------------------------------------
# validate_releases — per-repo missing-entry and orphan-entry
# ---------------------------------------------------------------------------


def test_per_repo_missing_entry_matika_has_tag_no_entry():
    """matika has a tag but no RELEASES.md entry -> missing-entry error."""
    text = "## eyerate v0.0.1\n"
    mock = _MultiRepoMock({
        AHIMSA_REPO: {"releases_md": text, "tags": []},
        "github.com/manomatika/matika": {"releases_md": text, "tags": ["v0.0.1"]},
        "github.com/manomatika/eyerate": {"releases_md": text, "tags": ["v0.0.1"]},
    })
    errors = validate_releases(
        ["github.com/manomatika/matika"],
        ahimsa_repo=AHIMSA_REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.tag["v0.0.1"]'
    assert "tag exists but no entry" in errors[0].message


def test_per_repo_orphan_entry_eyerate_has_entry_no_tag():
    """eyerate has an entry but no matching tag -> orphan-entry error."""
    text = "## matika v0.0.1\n## eyerate v0.0.2\n"
    mock = _MultiRepoMock({
        AHIMSA_REPO: {"releases_md": text, "tags": []},
        "github.com/manomatika/matika": {"releases_md": text, "tags": ["v0.0.1"]},
        "github.com/manomatika/eyerate": {"releases_md": text, "tags": []},
    })
    errors = validate_releases(
        ["github.com/manomatika/eyerate"],
        ahimsa_repo=AHIMSA_REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.entry["v0.0.2"]'
    assert "tag does not exist" in errors[0].message


# ---------------------------------------------------------------------------
# validate_releases — duplicates, ignored tags, status irrelevance
# ---------------------------------------------------------------------------


def test_duplicate_entry_emits_error():
    """Same tag heading appearing twice in RELEASES.md -> duplicate-entry error."""
    text = "## matika v0.0.4\n## matika v0.0.4\n"
    mock = _ReleasesMock(releases_md=text, tags=["v0.0.4"])
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    pointers = [e.pointer for e in errors]
    assert 'releases.entry["v0.0.4"]' in pointers
    assert any("duplicate entry" in e.message for e in errors)


def test_non_conforming_tags_are_ignored():
    """Tags like 'legacy-rev' that don't match the version regex are out of scope."""
    text = "## matika v0.0.4-dev.1\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.1", "legacy-rev", "release-1", "v0.0"],
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []


def test_status_field_does_not_affect_validation():
    """Entry with `Status: superseded` or `Status: failed` still counts as an entry."""
    text = (
        "## matika v0.0.4-dev.1\n"
        "- **Status:** published\n\n"
        "## matika v0.0.4-dev.0\n"
        "- **Status:** superseded (by matika v0.0.4-dev.1)\n"
    )
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.0", "v0.0.4-dev.1"],
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []


def test_trailing_junk_in_heading_is_treated_as_missing():
    """`## matika v0.0.4-dev.1 (notes)` does not parse; tag becomes missing."""
    text = "## matika v0.0.4-dev.1 (notes)\n"
    mock = _ReleasesMock(releases_md=text, tags=["v0.0.4-dev.1"])
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.tag["v0.0.4-dev.1"]'


# ---------------------------------------------------------------------------
# validate_releases — real-world snapshot fixture (updated format)
# ---------------------------------------------------------------------------


def test_real_matika_snapshot_round_trips_cleanly():
    """The frozen snapshot of the central RELEASES.md round-trips with matika's tags.

    The fixture uses the new ``## matika <tag>`` heading format. The snapshot
    covers the matika entries present as of 2026-05-07 — tags v0.0.4-dev.0 and
    v0.0.4-dev.1 only. Later matika tags do NOT require updating this fixture
    (it is intentionally frozen).
    """
    text = (FIXTURE_DIR / "matika.md").read_text()
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.0", "v0.0.4-dev.1"],
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []


# ---------------------------------------------------------------------------
# validate_releases — deleted_tag exemption (intentionally-absent breadcrumbs)
# ---------------------------------------------------------------------------


def _release_log_yaml(*entries: tuple[str, bool | None]) -> str:
    """Build a minimal release-log.yaml string for matika entries.

    Each entry is ``(tag, deleted_tag)``; ``deleted_tag=None`` omits the field.
    """
    lines = ["entries:"]
    for tag, deleted in entries:
        lines.append("  - repo: matika")
        lines.append(f"    tag: {tag}")
        lines.append('    date: "2026-05-06"')
        lines.append("    status: published")
        lines.append('    artifact: "none"')
        lines.append('    prs: "manomatika/matika#1"')
        if deleted is not None:
            lines.append(f"    deleted_tag: {'true' if deleted else 'false'}")
        lines.append('    summary: "test entry"')
    return "\n".join(lines) + "\n"


def test_intentionally_absent_tag_is_exempted():
    """Entry marked deleted_tag=true, tag absent from remote -> no error."""
    text = "## matika v0.0.4-dev.0\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=[],
        release_log=_release_log_yaml(("v0.0.4-dev.0", True)),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []


def test_unmarked_absent_tag_still_errors():
    """Entry WITHOUT deleted_tag but tag absent -> still errors (explicit opt-in)."""
    text = "## matika v0.0.4-dev.99\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=[],
        release_log=_release_log_yaml(("v0.0.4-dev.99", None)),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.entry["v0.0.4-dev.99"]'
    assert "tag does not exist" in errors[0].message


def test_live_tag_without_entry_still_errors_after_exemption():
    """Regression: Category A (tag but no entry) is unaffected by exemptions."""
    text = "## matika v0.0.4-dev.0\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4", "v0.0.4-dev.0"],  # v0.0.4 has no entry
        release_log=_release_log_yaml(("v0.0.4-dev.0", True)),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.tag["v0.0.4"]'
    assert "tag exists but no entry" in errors[0].message


def test_deleted_tag_that_still_exists_emits_warning(capsys):
    """Edge case: deleted_tag=true but the tag still exists -> warning, no error."""
    text = "## matika v0.0.4-dev.0\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4-dev.0"],  # tag IS still present
        release_log=_release_log_yaml(("v0.0.4-dev.0", True)),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "deleted_tag=true" in captured.err


def test_mixed_exempt_and_nonexempt_absent_entries():
    """Multiple absent entries; only the explicitly-marked one is exempted."""
    text = "## matika v0.0.4-dev.0\n## matika v0.0.4-dev.99\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=[],  # neither tag exists
        release_log=_release_log_yaml(
            ("v0.0.4-dev.0", True),
            ("v0.0.4-dev.99", None),
        ),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.entry["v0.0.4-dev.99"]'


def test_no_release_log_yaml_gives_no_exemptions():
    """release-log.yaml absent (fetch returns None) -> no exemptions (fail-open)."""
    text = "## matika v0.0.4-dev.99\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=[],
        release_log=None,  # release-log.yaml not served
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.entry["v0.0.4-dev.99"]'


def test_malformed_release_log_collapses_exemptions_and_errors_loudly():
    """Fail-mode: a malformed deleted_tag value collapses the exemption set to
    empty (strict parse raises -> fail-open except), so a legitimately-marked
    breadcrumb errors LOUDLY rather than being silently exempted. This is the
    intended safe direction (visible failure, never silent wrongful exemption).
    """
    text = "## matika v0.0.4-dev.0\n"
    # deleted_tag is a quoted string, not a YAML boolean -> strict parse raises.
    bad_release_log = (
        "entries:\n"
        "  - repo: matika\n"
        "    tag: v0.0.4-dev.0\n"
        '    date: "2026-05-06"\n'
        "    status: published\n"
        '    artifact: "none"\n'
        '    prs: "manomatika/matika#1"\n'
        '    deleted_tag: "false"\n'
        '    summary: "test entry"\n'
    )
    mock = _ReleasesMock(
        releases_md=text,
        tags=[],
        release_log=bad_release_log,
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.entry["v0.0.4-dev.0"]'


# ---------------------------------------------------------------------------
# validate_releases — pending exemption (forward-looking placeholders)
# ---------------------------------------------------------------------------


def _release_log_yaml_flagged(*entries: tuple[str, bool | None, bool | None]) -> str:
    """Build a minimal release-log.yaml for matika entries with both flags.

    Each entry is ``(tag, deleted_tag, pending)``; a ``None`` flag omits its
    field entirely (so the parser sees absence, not an explicit ``false``).
    """
    lines = ["entries:"]
    for tag, deleted, pending in entries:
        lines.append("  - repo: matika")
        lines.append(f"    tag: {tag}")
        lines.append('    date: "2026-05-06"')
        lines.append("    status: published")
        lines.append('    artifact: "none"')
        lines.append('    prs: "manomatika/matika#1"')
        if deleted is not None:
            lines.append(f"    deleted_tag: {'true' if deleted else 'false'}")
        if pending is not None:
            lines.append(f"    pending: {'true' if pending else 'false'}")
        lines.append('    summary: "test entry"')
    return "\n".join(lines) + "\n"


def test_pending_absent_tag_is_exempted():
    """Entry marked pending=true, tag absent from remote -> no error."""
    text = "## matika v0.0.5\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=[],
        release_log=_release_log_yaml_flagged(("v0.0.5", None, True)),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []


def test_unmarked_absent_tag_still_errors_without_pending():
    """Entry WITHOUT pending but tag absent -> still errors (explicit opt-in)."""
    text = "## matika v0.0.5\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=[],
        release_log=_release_log_yaml_flagged(("v0.0.5", None, None)),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.entry["v0.0.5"]'
    assert "tag does not exist" in errors[0].message


def test_pending_does_not_suppress_category_a():
    """Regression: Category A (tag but no entry) is unaffected by pending."""
    text = "## matika v0.0.5\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.4"],  # v0.0.4 has no entry; v0.0.5 entry is pending
        release_log=_release_log_yaml_flagged(("v0.0.5", None, True)),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.tag["v0.0.4"]'
    assert "tag exists but no entry" in errors[0].message


def test_pending_tag_now_exists_emits_warning(capsys):
    """Edge case: pending=true but the tag now exists -> warning, no error."""
    text = "## matika v0.0.5\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=["v0.0.5"],  # the release happened
        release_log=_release_log_yaml_flagged(("v0.0.5", None, True)),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "pending=true" in captured.err


def test_mixed_pending_and_nonexempt_absent_entries():
    """Multiple absent entries; only the pending-marked one is exempted."""
    text = "## matika v0.0.5\n## matika v0.0.6\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=[],  # neither tag exists
        release_log=_release_log_yaml_flagged(
            ("v0.0.5", None, True),
            ("v0.0.6", None, None),
        ),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.entry["v0.0.6"]'


def test_pending_and_deleted_tag_contradiction_collapses_and_errors_loudly():
    """An entry marked BOTH pending and deleted_tag raises in the parser, which
    (fail-open) collapses the exemption set to empty -> the entry errors LOUDLY
    rather than being silently exempted. Mirrors the malformed-value behavior."""
    text = "## matika v0.0.5\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=[],
        release_log=_release_log_yaml_flagged(("v0.0.5", True, True)),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == 'releases.entry["v0.0.5"]'


def test_pending_and_deleted_tag_coexist_on_distinct_entries():
    """deleted_tag and pending on SEPARATE entries both exempt correctly."""
    text = "## matika v0.0.4-dev.0\n## matika v0.0.5\n"
    mock = _ReleasesMock(
        releases_md=text,
        tags=[],  # neither tag exists
        release_log=_release_log_yaml_flagged(
            ("v0.0.4-dev.0", True, None),  # deleted breadcrumb
            ("v0.0.5", None, True),        # pending placeholder
        ),
    )
    errors = validate_releases(
        [REPO],
        ahimsa_repo=REPO,
        resolvers={"github.com": mock},
    )
    assert errors == []


# ---------------------------------------------------------------------------
# validate_releases — host dispatch
# ---------------------------------------------------------------------------


def test_unknown_host_in_resolvers_dict_emits_error():
    """If `resolvers` is provided but doesn't include the ahimsa repo's host."""
    mock = _ReleasesMock(releases_md=None, tags=[])
    errors = validate_releases(
        ["example.com/foo/bar"],
        ahimsa_repo="example.com/foo/ahimsa",
        resolvers={"github.com": mock},
    )
    assert len(errors) == 1
    assert errors[0].pointer == "releases.repo"
    assert 'no resolver for host "example.com"' in errors[0].message


def test_disallowed_host_via_allowed_hosts_emits_error():
    """If `allowed_hosts` excludes the ahimsa repo's host."""
    errors = validate_releases(
        ["example.com/foo/bar"],
        ahimsa_repo="example.com/foo/ahimsa",
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
        "repo": "github.com/manomatika/matika",
        "tag": "v0.0.4",
    },
    "applugs": [
        {
            "name": "eyerate",
            "repo": "github.com/manomatika/eyerate",
            "version": "0.0.4",
            "matika_version": "0.0.4",
            "tag": "v0.0.4",
        }
    ],
}


def test_transitive_drift_in_matika_surfaces_with_matika_pointer(tmp_path):
    """Drift in matika's release log surfaces under the `matika.releases.*` pointer.

    The central RELEASES.md (served from manomatika/manomatika) has only
    ``## matika v0.0.3`` -- tag v0.0.4 exists but has no entry.
    """
    recipe_path = _write_recipe(tmp_path, _VALID_RECIPE)

    releases_md = "## matika v0.0.3\n"

    mock = _MultiRepoMock({
        MM_REPO: {
            "releases_md": releases_md,
            "tags": [],
        },
        "github.com/manomatika/matika": {
            "releases_md": releases_md,
            "tags": ["v0.0.3", "v0.0.4"],
            "manifest": AppLugManifest(id="matika", version="0.0.4", matika_version="0.0.4"),
        },
        "github.com/manomatika/eyerate": {
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
    """Drift in an applug's release log surfaces under `applugs[i].releases.*`.

    The central RELEASES.md (served from manomatika/manomatika) has
    ``## eyerate v0.0.5`` but eyerate has no such tag.
    """
    recipe_path = _write_recipe(tmp_path, _VALID_RECIPE)

    releases_md_for_eyerate = "## eyerate v0.0.5\n"

    mock = _MultiRepoMock({
        MM_REPO: {
            "releases_md": releases_md_for_eyerate,
            "tags": [],
        },
        "github.com/manomatika/matika": {
            "releases_md": None,
            "tags": [],
            "manifest": AppLugManifest(id="matika", version="0.0.4", matika_version="0.0.4"),
        },
        "github.com/manomatika/eyerate": {
            "releases_md": releases_md_for_eyerate,
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
    """All repos opting out (no RELEASES.md in ahimsa) -> no release errors."""
    recipe_path = _write_recipe(tmp_path, _VALID_RECIPE)

    mock = _MultiRepoMock({
        AHIMSA_REPO: {
            "releases_md": None,
            "tags": [],
        },
        "github.com/manomatika/matika": {
            "releases_md": None,
            "tags": [],
            "manifest": AppLugManifest(id="matika", version="0.0.4", matika_version="0.0.4"),
        },
        "github.com/manomatika/eyerate": {
            "releases_md": None,
            "tags": [],
            "manifest": AppLugManifest(id="eyerate", version="0.0.4", matika_version="0.0.4"),
        },
    })

    errors = validate(recipe_path, resolvers={"github.com": mock})
    release_errors = [e for e in errors if ".releases" in e.pointer]
    assert release_errors == []
