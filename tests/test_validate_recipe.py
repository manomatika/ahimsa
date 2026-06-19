"""
Tests for ahimsa.validate_recipe and ahimsa._config.

All remote fetches are intercepted by injecting mock BaseResolver subclasses
into validate(). GitHubResolver-internal tests patch requests.get directly.
Config and walk-up tests live in test_config_precedence.py.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import ahimsa._config as _config_module
from ahimsa.validate_recipe import (
    AppLugManifest,
    BaseResolver,
    Error,
    GitHubResolver,
    _repo_cache,
    resolver_for,
    validate,
)


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------

def write_recipe(tmp_path, data: dict) -> object:
    p = tmp_path / "recipe.json"
    p.write_text(json.dumps(data))
    return p


VALID_RECIPE: dict = {
    "application": {
        "name": "Test App",
        "product_name": "TestProduct",
        "version": "1.0.0",
        "bundle_id": "com.example.test",
        "icon": "assets/icon.icns",
    },
    "matika": {
        "version": "0.0.2",
        "repo": "github.com/pjtallman/matika",
        "tag": "v0.0.2",
    },
    "applugs": [
        {
            "name": "eyerate",
            "repo": "github.com/pjtallman/eyerate",
            "version": "0.0.2",
            "matika_version": "0.0.2",
            "tag": "v0.0.2",
        }
    ],
}

VALID_MANIFEST = AppLugManifest(id="eyerate", version="0.0.2", matika_version="0.0.2")


class _OkResolver(BaseResolver):
    """Always returns a fixed manifest; overrides the template entirely.

    `list_tags` and `fetch_text` are concrete no-ops because these tests
    do not exercise release-log auditing — the transitive call from
    validate() short-circuits when fetch_text returns None.
    """

    def __init__(self, manifest: AppLugManifest = VALID_MANIFEST) -> None:
        super().__init__(host="github.com")
        self._manifest = manifest

    def _canonicalize_repo(self, owner: str, repo: str) -> tuple[str, str]:
        return (owner, repo)

    def _raw_url(self, canonical: tuple[str, str], tag: str, path: str) -> str:
        return ""

    def resolve(self, name: str, repo: str, tag: str) -> AppLugManifest:
        return self._manifest

    def list_tags(self, repo: str) -> list[str]:
        return []

    def fetch_text(self, repo: str, ref: str, path: str) -> str | None:
        return None


class _ErrorResolver(BaseResolver):
    """Always raises a fixed exception."""

    def __init__(self, exc: Exception) -> None:
        super().__init__(host="github.com")
        self._exc = exc

    def _canonicalize_repo(self, owner: str, repo: str) -> tuple[str, str]:
        return (owner, repo)

    def _raw_url(self, canonical: tuple[str, str], tag: str, path: str) -> str:
        return ""

    def resolve(self, name: str, repo: str, tag: str) -> AppLugManifest:
        raise self._exc

    def list_tags(self, repo: str) -> list[str]:
        return []

    def fetch_text(self, repo: str, ref: str, path: str) -> str | None:
        return None


def ok_resolvers(manifest: AppLugManifest = VALID_MANIFEST) -> dict[str, BaseResolver]:
    return {"github.com": _OkResolver(manifest)}


def _validate(recipe: dict, tmp_path, **kw) -> list[Error]:
    """Helper: write recipe to tmp_path and validate with injected resolvers."""
    path = write_recipe(tmp_path, recipe)
    return validate(path, resolvers=ok_resolvers(), **kw)


def pointers(errors: list[Error]) -> list[str]:
    return [e.pointer for e in errors]


# ---------------------------------------------------------------------------
# Error.__str__
# ---------------------------------------------------------------------------

def test_error_str_format():
    err = Error(
        pointer="application.bundle_id",
        message='not a valid reverse-DNS identifier ("foo")',
    )
    assert str(err) == 'application.bundle_id: not a valid reverse-DNS identifier ("foo")'


# ---------------------------------------------------------------------------
# Valid recipe passes
# ---------------------------------------------------------------------------

def test_valid_recipe_passes(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers=ok_resolvers())
    assert errors == [], f"Unexpected errors: {[str(e) for e in errors]}"


def test_prerelease_tag_passes_with_bare_core_pins(tmp_path):
    """Core/suffix contract: a recipe may pin matika/applugs at a pre-release
    git TAG (e.g. `v0.0.4-rc.1`) while the bare-core version pins stay X.Y.Z.

    Tags are git refs, not pins — they are NOT version-format-checked, so an
    rc tag must validate cleanly. This locks in that rc tags pass and is the
    reason validate.yml's live recipe step can be re-enabled at rc time.
    """
    recipe = {
        **VALID_RECIPE,
        "matika": {**VALID_RECIPE["matika"], "tag": "v0.0.2-rc.1"},
        "applugs": [{**VALID_RECIPE["applugs"][0], "tag": "v0.0.2-rc.1"}],
    }
    path = write_recipe(tmp_path, recipe)
    errors = validate(path, resolvers=ok_resolvers())
    assert errors == [], f"rc tag should pass: {[str(e) for e in errors]}"


# ---------------------------------------------------------------------------
# Schema: missing required application fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field,pointer", [
    ("name", "application.name"),
    ("product_name", "application.product_name"),
    ("version", "application.version"),
    ("bundle_id", "application.bundle_id"),
    ("icon", "application.icon"),
])
def test_missing_application_field(tmp_path, field, pointer):
    app = {k: v for k, v in VALID_RECIPE["application"].items() if k != field}
    errors = _validate({**VALID_RECIPE, "application": app}, tmp_path)
    assert pointer in pointers(errors)
    err = next(e for e in errors if e.pointer == pointer)
    assert "required field missing" in err.message


# ---------------------------------------------------------------------------
# product_name format: the canonical product identity that names user-facing
# artifacts (manomatika-0.0.1-macos-arm64.dmg) and the installed bundle/exe
# (ManoMatika-0.0.1.app). It must slug cleanly for a filename AND read as a
# proper-noun bundle name, so the charset is constrained.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("good_name", [
    "ManoMatika",
    "Matika",
    "Mano Matika",
    "mano-matika",
    "Product2",
    "A",
])
def test_valid_product_name_passes(tmp_path, good_name):
    recipe = {**VALID_RECIPE, "application": {**VALID_RECIPE["application"], "product_name": good_name}}
    errors = _validate(recipe, tmp_path)
    assert "application.product_name" not in pointers(errors)


@pytest.mark.parametrize("bad_name", [
    "Mano_Matika",      # underscore not allowed
    "Mano/Matika",      # slash not allowed
    "Mano.Matika",      # dot not allowed
    " ManoMatika",      # leading space
    "ManoMatika ",      # trailing space
    "-ManoMatika",      # leading hyphen
    "ManoMatika-",      # trailing hyphen
    "Mano  Matika",     # double space
    "Maño",             # non-ASCII
    "Mano@Matika",      # symbol
])
def test_invalid_product_name(tmp_path, bad_name):
    recipe = {**VALID_RECIPE, "application": {**VALID_RECIPE["application"], "product_name": bad_name}}
    errors = _validate(recipe, tmp_path)
    assert "application.product_name" in pointers(errors)
    err = next(e for e in errors if e.pointer == "application.product_name")
    assert "valid product name" in err.message


# ---------------------------------------------------------------------------
# Schema: missing required matika fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field,pointer", [
    ("version", "matika.version"),
    ("repo", "matika.repo"),
    ("tag", "matika.tag"),
])
def test_missing_matika_field(tmp_path, field, pointer):
    matika = {k: v for k, v in VALID_RECIPE["matika"].items() if k != field}
    errors = _validate({**VALID_RECIPE, "matika": matika}, tmp_path)
    assert pointer in pointers(errors)
    err = next(e for e in errors if e.pointer == pointer)
    assert "required field missing" in err.message


# ---------------------------------------------------------------------------
# Schema: applugs missing / empty
# ---------------------------------------------------------------------------

def test_missing_applugs_field(tmp_path):
    recipe = {k: v for k, v in VALID_RECIPE.items() if k != "applugs"}
    path = write_recipe(tmp_path, recipe)
    errors = validate(path, resolvers=ok_resolvers())
    assert "applugs" in pointers(errors)


def test_empty_applugs_array(tmp_path):
    path = write_recipe(tmp_path, {**VALID_RECIPE, "applugs": []})
    errors = validate(path, resolvers=ok_resolvers())
    assert "applugs" in pointers(errors)


# ---------------------------------------------------------------------------
# Version format: invalid strings rejected
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_version", [
    "^1.0",
    ">=0.0.2",
    "*",
    "latest",
    "1.x",
    "0.0.4-dev",
    "0.0.4-rc.1",
    "0.0.4-rc1",
    "0.0.4+build",
])
def test_invalid_application_version(tmp_path, bad_version):
    recipe = {**VALID_RECIPE, "application": {**VALID_RECIPE["application"], "version": bad_version}}
    errors = _validate(recipe, tmp_path)
    assert "application.version" in pointers(errors)


def test_dev_suffix_in_applug_version_rejected(tmp_path):
    # Pre-release suffixes (the -dev/-rc.N ladder) are human/audit-only markers;
    # recipe pin fields must be bare core. A pin carrying any suffix is rejected.
    plug = {**VALID_RECIPE["applugs"][0], "version": "0.0.4-dev"}
    errors = _validate({**VALID_RECIPE, "applugs": [plug]}, tmp_path)
    assert "applugs[0].version" in pointers(errors)


def test_dev_suffix_in_applug_matika_version_rejected(tmp_path):
    plug = {**VALID_RECIPE["applugs"][0], "matika_version": "0.0.4-dev"}
    recipe = {
        **VALID_RECIPE,
        "matika": {**VALID_RECIPE["matika"], "version": "0.0.4-dev"},
        "applugs": [plug],
    }
    errors = _validate(recipe, tmp_path)
    assert "applugs[0].matika_version" in pointers(errors)


# ---------------------------------------------------------------------------
# bundle_id format: invalid strings rejected
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_id,reason", [
    ("com.example", "too few components"),
    ("1com.example.test", "leading digit"),
    ("com.exa_mple.test", "underscore not allowed"),
])
def test_invalid_bundle_id(tmp_path, bad_id, reason):
    recipe = {**VALID_RECIPE, "application": {**VALID_RECIPE["application"], "bundle_id": bad_id}}
    errors = _validate(recipe, tmp_path)
    assert "application.bundle_id" in pointers(errors)
    err = next(e for e in errors if e.pointer == "application.bundle_id")
    assert "reverse-DNS" in err.message


# ---------------------------------------------------------------------------
# Per-applug: missing required fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["name", "repo", "version", "matika_version", "tag"])
def test_missing_applug_field(tmp_path, field):
    plug = {k: v for k, v in VALID_RECIPE["applugs"][0].items() if k != field}
    path = write_recipe(tmp_path, {**VALID_RECIPE, "applugs": [plug]})
    errors = validate(path, resolvers=ok_resolvers())
    assert f"applugs[0].{field}" in pointers(errors)
    err = next(e for e in errors if e.pointer == f"applugs[0].{field}")
    assert "required field missing" in err.message


# ---------------------------------------------------------------------------
# Cross-applug consistency
# ---------------------------------------------------------------------------

def test_conflicting_matika_versions_fails(tmp_path):
    class _MultiResolver(BaseResolver):
        def __init__(self): super().__init__("github.com")
        def _canonicalize_repo(self, o, r): return (o, r)
        def _raw_url(self, c, t, p): return ""
        def resolve(self, name, repo, tag):
            if name == "eyerate":
                return AppLugManifest(id="eyerate", version="0.0.2", matika_version="0.0.2")
            return AppLugManifest(id="other", version="1.0.0", matika_version="0.0.1")
        def list_tags(self, repo): return []
        def fetch_text(self, repo, ref, path): return None

    recipe = {
        **VALID_RECIPE,
        "applugs": [
            {"name": "eyerate", "repo": "github.com/pjtallman/eyerate",
             "version": "0.0.2", "matika_version": "0.0.2", "tag": "v0.0.2"},
            {"name": "other", "repo": "github.com/pjtallman/Other",
             "version": "1.0.0", "matika_version": "0.0.1", "tag": "v1.0.0"},
        ],
    }
    path = write_recipe(tmp_path, recipe)
    errors = validate(path, resolvers={"github.com": _MultiResolver()})
    assert any("conflicting matika_version" in str(e) for e in errors)


def test_identical_matika_versions_passes(tmp_path):
    class _MultiResolver(BaseResolver):
        def __init__(self): super().__init__("github.com")
        def _canonicalize_repo(self, o, r): return (o, r)
        def _raw_url(self, c, t, p): return ""
        def resolve(self, name, repo, tag):
            return AppLugManifest(id=name, version="0.0.2", matika_version="0.0.2")
        def list_tags(self, repo): return []
        def fetch_text(self, repo, ref, path): return None

    recipe = {
        **VALID_RECIPE,
        "applugs": [
            {"name": "eyerate", "repo": "github.com/pjtallman/eyerate",
             "version": "0.0.2", "matika_version": "0.0.2", "tag": "v0.0.2"},
            {"name": "other", "repo": "github.com/pjtallman/Other",
             "version": "0.0.2", "matika_version": "0.0.2", "tag": "v0.0.2"},
        ],
    }
    path = write_recipe(tmp_path, recipe)
    errors = validate(path, resolvers={"github.com": _MultiResolver()})
    assert not any("conflicting" in str(e) for e in errors)


# ---------------------------------------------------------------------------
# Recipe-matika consistency
# ---------------------------------------------------------------------------

def test_applug_matika_version_mismatch_with_recipe(tmp_path):
    plug = {**VALID_RECIPE["applugs"][0], "matika_version": "0.0.1"}
    recipe = {**VALID_RECIPE, "applugs": [plug]}
    path = write_recipe(tmp_path, recipe)
    resolver = _OkResolver(AppLugManifest(id="eyerate", version="0.0.2", matika_version="0.0.1"))
    errors = validate(path, resolvers={"github.com": resolver})
    assert "applugs[0].matika_version" in pointers(errors)
    err = next(e for e in errors if e.pointer == "applugs[0].matika_version")
    assert '"0.0.1"' in err.message and '"0.0.2"' in err.message


# ---------------------------------------------------------------------------
# Remote verification: happy path
# ---------------------------------------------------------------------------

def test_valid_manifest_passes(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers=ok_resolvers(VALID_MANIFEST))
    assert not any("resolve" in e.pointer for e in errors)


# ---------------------------------------------------------------------------
# Remote verification: error paths
# ---------------------------------------------------------------------------

def test_applug_json_not_found_fails(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(
        path,
        resolvers={"github.com": _ErrorResolver(FileNotFoundError("file not found"))},
    )
    assert any("resolve" in e.pointer for e in errors)
    err = next(e for e in errors if "resolve" in e.pointer)
    assert "not found" in err.message


def test_repo_not_found_fails(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(
        path,
        resolvers={"github.com": _ErrorResolver(
            LookupError('repository "pjtallman/eyerate" not found on GitHub')
        )},
    )
    assert any("repo" in e.pointer for e in errors)
    err = next(e for e in errors if "repo" in e.pointer)
    assert "not found" in err.message


def test_applug_json_id_mismatch_fails(tmp_path):
    wrong = AppLugManifest(id="wrong-id", version="0.0.2", matika_version="0.0.2")
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers=ok_resolvers(wrong))
    assert any("resolve" in e.pointer for e in errors)
    err = next(e for e in errors if "resolve" in e.pointer)
    assert '"wrong-id"' in err.message and '"eyerate"' in err.message


def test_applug_json_version_mismatch_fails(tmp_path):
    wrong = AppLugManifest(id="eyerate", version="9.9.9", matika_version="0.0.2")
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers=ok_resolvers(wrong))
    assert any("resolve" in e.pointer for e in errors)
    err = next(e for e in errors if "resolve" in e.pointer and "version" in e.message)
    assert '"9.9.9"' in err.message


def test_applug_json_matika_version_mismatch_fails(tmp_path):
    wrong = AppLugManifest(id="eyerate", version="0.0.2", matika_version="0.0.1")
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers=ok_resolvers(wrong))
    assert any("resolve" in e.pointer for e in errors)
    err = next(e for e in errors if "resolve" in e.pointer and "matika_version" in e.message)
    assert '"0.0.1"' in err.message


# ---------------------------------------------------------------------------
# BaseResolver._parse_repo
# ---------------------------------------------------------------------------

def test_parse_repo_ssh_form_rejected():
    with pytest.raises(ValueError, match="malformed"):
        GitHubResolver()._parse_repo("git@github.com:pjtallman/Matika.git")


def test_parse_repo_trailing_git_rejected():
    with pytest.raises(ValueError, match=r'\.git'):
        GitHubResolver()._parse_repo("github.com/pjtallman/Matika.git")


def test_parse_repo_missing_components_rejected():
    with pytest.raises(ValueError, match="malformed"):
        GitHubResolver()._parse_repo("pjtallman/Matika")


def test_parse_repo_scheme_rejected():
    with pytest.raises(ValueError, match="malformed"):
        GitHubResolver()._parse_repo("https://github.com/pjtallman/Matika")


def test_parse_repo_wrong_host_rejected():
    with pytest.raises(ValueError, match="malformed"):
        GitHubResolver()._parse_repo("gitlab.com/pjtallman/Matika")


def test_parse_repo_valid_passes():
    owner, repo = GitHubResolver()._parse_repo("github.com/pjtallman/Matika")
    assert owner == "pjtallman" and repo == "Matika"


# ---------------------------------------------------------------------------
# Dispatch: resolver_for()
# ---------------------------------------------------------------------------

def test_dispatch_github_routes_to_github_resolver():
    assert isinstance(resolver_for("github.com/owner/repo", allowed_hosts=["github.com"]), GitHubResolver)


def test_dispatch_host_not_allowed(tmp_path):
    plug = {**VALID_RECIPE["applugs"][0], "repo": "evil.com/owner/plugin"}
    path = write_recipe(tmp_path, {**VALID_RECIPE, "applugs": [plug]})
    errors = validate(path, allowed_hosts=["github.com"])
    assert any("repo" in e.pointer for e in errors)
    err = next(e for e in errors if "repo" in e.pointer)
    assert "not in allowed_hosts" in err.message


def test_dispatch_allowed_but_no_resolver(tmp_path):
    plug = {**VALID_RECIPE["applugs"][0], "repo": "fakehub.com/owner/plugin"}
    path = write_recipe(tmp_path, {**VALID_RECIPE, "applugs": [plug]})
    errors = validate(path, allowed_hosts=["fakehub.com"])
    assert any("repo" in e.pointer for e in errors)
    err = next(e for e in errors if "repo" in e.pointer)
    assert "allowed but no resolver" in err.message


# ---------------------------------------------------------------------------
# GitHubResolver: canonicalization and cache (requests.get patched)
# ---------------------------------------------------------------------------

def _make_mock_response(json_data: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def test_github_resolver_lowercase_repo_canonicalized():
    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    resolver = GitHubResolver()
    api_resp = _make_mock_response({"full_name": "pjtallman/EyeRate"})
    raw_resp = _make_mock_response({"id": "eyerate", "version": "0.0.2", "matika_version": "0.0.2"})
    captured_urls: list[str] = []

    def fake_get(url, **kwargs):
        captured_urls.append(url)
        return api_resp if "api.github.com" in url else raw_resp

    with patch("requests.get", side_effect=fake_get):
        manifest = resolver.resolve("eyerate", "github.com/pjtallman/eyerate", "v0.0.2")

    raw_urls = [u for u in captured_urls if "raw.githubusercontent.com" in u]
    assert raw_urls and "EyeRate" in raw_urls[0]
    assert manifest.id == "eyerate"


def test_github_resolver_cache_one_api_call():
    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    resolver = GitHubResolver()
    api_resp = _make_mock_response({"full_name": "pjtallman/EyeRate"})
    raw_resp = _make_mock_response({"id": "eyerate", "version": "0.0.2", "matika_version": "0.0.2"})

    def fake_get(url, **kwargs):
        return api_resp if "api.github.com" in url else raw_resp

    with patch("requests.get", side_effect=fake_get) as mock_get:
        resolver.resolve("eyerate", "github.com/pjtallman/EyeRate", "v0.0.2")
        resolver.resolve("eyerate", "github.com/pjtallman/EyeRate", "v0.0.3")

    api_calls = [c for c in mock_get.call_args_list if "api.github.com" in c.args[0]]
    assert len(api_calls) == 1


def test_github_resolver_cache_case_insensitive():
    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    resolver = GitHubResolver()
    api_resp = _make_mock_response({"full_name": "pjtallman/EyeRate"})
    raw_resp = _make_mock_response({"id": "eyerate", "version": "0.0.2", "matika_version": "0.0.2"})

    def fake_get(url, **kwargs):
        return api_resp if "api.github.com" in url else raw_resp

    with patch("requests.get", side_effect=fake_get) as mock_get:
        resolver.resolve("eyerate", "github.com/pjtallman/eyerate", "v0.0.2")
        resolver.resolve("eyerate", "github.com/PJTALLMAN/EYERATE", "v0.0.3")

    api_calls = [c for c in mock_get.call_args_list if "api.github.com" in c.args[0]]
    assert len(api_calls) == 1


# ---------------------------------------------------------------------------
# GitHubResolver: list_tags with Link: rel="next" pagination
# ---------------------------------------------------------------------------

def test_github_resolver_list_tags_paginates_link_header():
    """Two-page pagination: page 1 has rel="next" Link, page 2 does not.

    Asserts:
      - tags from BOTH pages are returned
      - first request includes per_page=100 in `params`
      - second request uses the URL from the Link header verbatim and
        passes params=None (the next URL already encodes page= and per_page=)
    """
    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    resolver = GitHubResolver()

    # Canonicalization step (unrelated to pagination).
    canon_resp = _make_mock_response({"full_name": "manomatika/matika"})

    # Page 1: 2 tags + Link: rel="next" to page 2.
    next_url = (
        "https://api.github.com/repositories/12345/git/refs/tags"
        "?page=2&per_page=100"
    )
    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = [
        {"ref": "refs/tags/v0.0.1"},
        {"ref": "refs/tags/v0.0.2"},
    ]
    page1.raise_for_status.return_value = None
    page1.links = {"next": {"url": next_url, "rel": "next"}}

    # Page 2: 2 more tags, no Link header (terminates the loop).
    page2 = MagicMock()
    page2.status_code = 200
    page2.json.return_value = [
        {"ref": "refs/tags/v0.0.3"},
        {"ref": "refs/tags/v0.0.4"},
    ]
    page2.raise_for_status.return_value = None
    page2.links = {}

    responses = iter([canon_resp, page1, page2])
    captured: list[tuple[str, dict]] = []

    def fake_get(url, **kwargs):
        captured.append((url, kwargs))
        return next(responses)

    with patch("requests.get", side_effect=fake_get):
        tags = resolver.list_tags("github.com/manomatika/matika")

    assert tags == ["v0.0.1", "v0.0.2", "v0.0.3", "v0.0.4"]

    tag_calls = [c for c in captured if "git/refs/tags" in c[0]]
    assert len(tag_calls) == 2

    # First call: base URL + per_page param.
    first_url, first_kwargs = tag_calls[0]
    assert "page=2" not in first_url
    assert first_kwargs.get("params") == {"per_page": 100}

    # Second call: full next URL from Link header, no params (URL embeds them).
    second_url, second_kwargs = tag_calls[1]
    assert second_url == next_url
    assert second_kwargs.get("params") is None


def test_github_resolver_list_tags_404_returns_empty():
    """A 404 on the first page (zero-tag repo) returns []."""
    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    resolver = GitHubResolver()
    canon_resp = _make_mock_response({"full_name": "manomatika/matika"})
    not_found = MagicMock()
    not_found.status_code = 404
    not_found.json.return_value = {}
    not_found.raise_for_status.return_value = None
    not_found.links = {}

    responses = iter([canon_resp, not_found])

    def fake_get(url, **kwargs):
        return next(responses)

    with patch("requests.get", side_effect=fake_get):
        tags = resolver.list_tags("github.com/manomatika/matika")

    assert tags == []


# ---------------------------------------------------------------------------
# GitHubResolver: authentication via GITHUB_TOKEN / GH_TOKEN
# ---------------------------------------------------------------------------

# Sentinel for the leak test. Deliberately NOT prefixed with `ghp_` /
# `github_pat_` / `ghs_` etc. — real PATs carry those prefixes, and a
# leaked-token scanner could false-positive on the sentinel even though
# it isn't a real token.
_FAKE_TOKEN = "TEST_SENTINEL_NEVER_REAL_TOKEN"


def _canon_response():
    """200 response shaped like the GitHub canonicalization endpoint."""
    return _make_mock_response({"full_name": "manomatika/matika"})


def _tags_404_response():
    """404 response for the tags endpoint (zero-tag repo case)."""
    resp = MagicMock()
    resp.status_code = 404
    resp.json.return_value = {"message": "Not Found"}
    resp.raise_for_status.return_value = None
    resp.links = {}
    return resp


def _raw_response():
    """200 response shaped to satisfy both _fetch_json and _fetch_text callers."""
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "content"
    resp.json.return_value = {
        "id": "matika", "version": "0.0.4", "matika_version": "0.0.4",
    }
    resp.raise_for_status.return_value = None
    resp.links = {}
    return resp


def _route_response(url: str):
    """Return a canned response shaped for *url*'s GitHub endpoint family."""
    if "api.github.com/repos/" in url and "/git/refs/tags" not in url:
        return _canon_response()
    if "/git/refs/tags" in url:
        return _tags_404_response()
    return _raw_response()


def _invoke_canonicalize(resolver):
    resolver._canonicalize_repo("manomatika", "matika")


def _invoke_list_tags(resolver):
    resolver.list_tags("github.com/manomatika/matika")


def _invoke_resolve(resolver):
    resolver.resolve("matika", "github.com/manomatika/matika", "v0.0.4")


def _invoke_fetch_text(resolver):
    resolver.fetch_text("github.com/manomatika/matika", "HEAD", "RELEASES.md")


_AUTH_INVOCATIONS = [
    ("canonicalize", _invoke_canonicalize),
    ("list_tags",    _invoke_list_tags),
    ("resolve",      _invoke_resolve),
    ("fetch_text",   _invoke_fetch_text),
]


@pytest.mark.parametrize("label,invoke", _AUTH_INVOCATIONS)
def test_auth_header_present_when_token_set(monkeypatch, label, invoke):
    """Every outbound request carries Authorization when a token is set.

    Asserted across all four user-visible methods because each one routes
    through a different combination of helpers (api.github.com endpoints,
    raw.githubusercontent.com endpoints, paginated lists). Auth must be
    consistent across all of them.
    """
    monkeypatch.setenv("GITHUB_TOKEN", _FAKE_TOKEN)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    captured: list[dict] = []

    def fake_get(url, **kwargs):
        captured.append(kwargs)
        return _route_response(url)

    with patch("requests.get", side_effect=fake_get):
        invoke(GitHubResolver())

    assert captured, f"{label}: no requests captured"
    for kwargs in captured:
        headers = kwargs.get("headers") or {}
        assert headers.get("Authorization") == f"Bearer {_FAKE_TOKEN}", (
            f"{label}: missing or wrong Authorization in {headers}"
        )


@pytest.mark.parametrize("label,invoke", _AUTH_INVOCATIONS)
def test_auth_header_absent_when_no_token(monkeypatch, label, invoke):
    """No Authorization header on any outbound request when both env vars are unset."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    captured: list[dict] = []

    def fake_get(url, **kwargs):
        captured.append(kwargs)
        return _route_response(url)

    with patch("requests.get", side_effect=fake_get):
        invoke(GitHubResolver())

    assert captured, f"{label}: no requests captured"
    for kwargs in captured:
        headers = kwargs.get("headers") or {}
        assert "Authorization" not in headers, (
            f"{label}: unexpected Authorization in {headers}"
        )


def test_github_token_wins_over_gh_token(monkeypatch):
    """When both env vars are set, GITHUB_TOKEN takes precedence."""
    monkeypatch.setenv("GITHUB_TOKEN", "primary_token")
    monkeypatch.setenv("GH_TOKEN", "fallback_token")

    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    captured: list[dict] = []

    def fake_get(url, **kwargs):
        captured.append(kwargs)
        return _canon_response()

    with patch("requests.get", side_effect=fake_get):
        GitHubResolver()._canonicalize_repo("manomatika", "matika")

    assert captured[0]["headers"]["Authorization"] == "Bearer primary_token"


def test_gh_token_used_when_github_token_unset(monkeypatch):
    """Fallback to GH_TOKEN when GITHUB_TOKEN is not set."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "fallback_token")

    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    captured: list[dict] = []

    def fake_get(url, **kwargs):
        captured.append(kwargs)
        return _canon_response()

    with patch("requests.get", side_effect=fake_get):
        GitHubResolver()._canonicalize_repo("manomatika", "matika")

    assert captured[0]["headers"]["Authorization"] == "Bearer fallback_token"


def test_canonicalize_404_no_token_suggests_setting_github_token(monkeypatch):
    """A 404 with no token disambiguates as 'maybe private repo, set GITHUB_TOKEN'."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    not_found = MagicMock()
    not_found.status_code = 404
    not_found.json.return_value = {"message": "Not Found"}
    not_found.raise_for_status.return_value = None

    with patch("requests.get", return_value=not_found):
        with pytest.raises(LookupError) as exc:
            GitHubResolver()._canonicalize_repo("manomatika", "matika")

    msg = str(exc.value)
    assert "GITHUB_TOKEN" in msg
    assert "no access" in msg
    assert "private repo" in msg


def test_canonicalize_404_with_token_does_not_suggest_setting_token(monkeypatch):
    """A 404 with a token set means a real 'not found' — no auth hint."""
    monkeypatch.setenv("GITHUB_TOKEN", _FAKE_TOKEN)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    not_found = MagicMock()
    not_found.status_code = 404
    not_found.json.return_value = {"message": "Not Found"}
    not_found.raise_for_status.return_value = None

    with patch("requests.get", return_value=not_found):
        with pytest.raises(LookupError) as exc:
            GitHubResolver()._canonicalize_repo("manomatika", "matika")

    msg = str(exc.value)
    assert "GITHUB_TOKEN" not in msg
    assert "private repo" not in msg
    assert "no access" not in msg
    assert "not found" in msg


def test_token_value_never_appears_in_error_messages(monkeypatch):
    """Even on the 404 path that constructs error text, the token value must not leak."""
    monkeypatch.setenv("GITHUB_TOKEN", _FAKE_TOKEN)

    import ahimsa.validate_recipe as vr
    vr._repo_cache.clear()

    not_found = MagicMock()
    not_found.status_code = 404
    not_found.json.return_value = {"message": "Not Found"}
    not_found.raise_for_status.return_value = None

    with patch("requests.get", return_value=not_found):
        with pytest.raises(LookupError) as exc:
            GitHubResolver()._canonicalize_repo("manomatika", "matika")

    assert _FAKE_TOKEN not in str(exc.value), "token sentinel leaked into str(exc)"
    assert _FAKE_TOKEN not in repr(exc.value), "token sentinel leaked into repr(exc)"
