"""
Integration-tier tests for GitHubResolver against real GitHub.

These tests make real HTTP calls to api.github.com and raw.githubusercontent.com
against a guaranteed-public test repo (`octocat/Hello-World`). They catch
transport-layer surprises that mocked unit tests cannot — for example, the
authentication requirement that PR `manomatika/ahimsa#28` shipped without
auth handling because every test mocked the resolver layer.

The tier is excluded from the default pytest run via `addopts = "-m 'not
integration'"` in `pyproject.toml`. Run explicitly:

    pytest -m integration

By design the tests run UNAUTHENTICATED. Hello-World is a public repo, so no
`GITHUB_TOKEN` is required. If `GITHUB_TOKEN` happens to be set in the env,
the resolver attaches an `Authorization` header automatically; against a
public repo this is a no-op. The tests do not assume token presence or
absence — they only assume Hello-World remains public.
"""

import pytest

import ahimsa.validate_recipe as vr
from ahimsa.validate_recipe import GitHubResolver


pytestmark = pytest.mark.integration


_TEST_REPO = "github.com/octocat/Hello-World"


def _fresh_resolver() -> GitHubResolver:
    """Clear the per-process canonicalize cache and return a new resolver.

    Each integration test exercises a clean code path; sharing cached state
    between tests would mask a regression in `_canonicalize_repo` itself.
    """
    vr._repo_cache.clear()
    return GitHubResolver()


def test_canonicalize_repo_returns_canonical_owner_and_repo():
    canonical = _fresh_resolver()._canonicalize_repo("octocat", "Hello-World")
    assert canonical == ("octocat", "Hello-World")


def test_canonicalize_repo_normalizes_mixed_case_input():
    """Mixed-case input resolves to the canonical owner/repo casing."""
    canonical = _fresh_resolver()._canonicalize_repo("OCTOCAT", "hello-world")
    assert canonical == ("octocat", "Hello-World")


def test_list_tags_returns_empty_for_zero_tag_repo():
    """Hello-World has zero tags; list_tags returns [].

    Deliberate choice of repo: the integration tier is about transport-layer
    surprises (GitHub API contract drift), NOT re-testing pagination logic
    that mocked unit tests already cover. A future maintainer may be tempted
    to switch to a populated repo for "better coverage" — don't. Hello-World's
    appeal is its frozenness; switching to a repo with tags introduces a
    moving-target dependency. The mocked pagination tests in
    `tests/test_validate_recipe.py` cover the populated-repo path.
    """
    tags = _fresh_resolver().list_tags(_TEST_REPO)
    assert tags == []


def test_fetch_text_returns_readme_content_at_head():
    """`fetch_text(repo, "HEAD", "README")` returns the README content.

    Exercises the same code path `validate_releases` uses in production,
    where `ref="HEAD"` resolves to the repo's default branch via
    `raw.githubusercontent.com`. Hello-World's README on the master branch
    contains exactly "Hello World!\\n".
    """
    text = _fresh_resolver().fetch_text(_TEST_REPO, "HEAD", "README")
    assert text is not None
    assert text.startswith("Hello World")


def test_fetch_text_returns_none_for_nonexistent_path():
    """A 404 on raw.githubusercontent.com (file does not exist) returns None.

    Confirms the no-RELEASES.md opt-out path against real GitHub:
    `validate_releases` treats `fetch_text(...) is None` as "this repo has not
    adopted the convention" and short-circuits cleanly.
    """
    text = _fresh_resolver().fetch_text(
        _TEST_REPO, "HEAD", "DEFINITELY_NOT_A_REAL_FILE_xyz123.txt"
    )
    assert text is None
