"""
Tests for scripts/validate_recipe.py and scripts/_config.py.

All remote fetches are intercepted by injecting mock BaseResolver subclasses
into validate(). GitHubResolver-internal tests patch requests.get directly.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import _config
from _config import load_allowed_hosts
from validate_recipe import (
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
        "version": "1.0.0",
        "bundle_id": "com.example.test",
        "icon": "assets/icon.icns",
    },
    "matika": {
        "version": "0.0.2",
        "repo": "github.com/pjtallman/Matika",
        "tag": "v0.0.2",
    },
    "applugs": [
        {
            "name": "eyerate",
            "repo": "github.com/pjtallman/EyeRate",
            "version": "0.0.2",
            "matika_version": "0.0.2",
            "tag": "v0.0.2",
        }
    ],
}

VALID_MANIFEST = AppLugManifest(id="eyerate", version="0.0.2", matika_version="0.0.2")


class _OkResolver(BaseResolver):
    """Always returns a fixed manifest; overrides the template entirely."""

    def __init__(self, manifest: AppLugManifest = VALID_MANIFEST) -> None:
        super().__init__(host="github.com")
        self._manifest = manifest

    def _canonicalize_repo(self, owner: str, repo: str) -> tuple[str, str]:
        return (owner, repo)

    def _raw_url(self, canonical: tuple[str, str], tag: str, path: str) -> str:
        return ""

    def resolve(self, name: str, repo: str, tag: str) -> AppLugManifest:
        return self._manifest


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


def ok_resolvers(manifest: AppLugManifest = VALID_MANIFEST) -> dict[str, BaseResolver]:
    return {"github.com": _OkResolver(manifest)}


def errors_for(recipe: dict, tmp_path, **kw) -> list[Error]:
    path = write_recipe(tmp_path, recipe)
    return validate(path, resolvers=ok_resolvers(), **kw)


def pointers(errors: list[Error]) -> list[str]:
    return [e.pointer for e in errors]


def messages(errors: list[Error]) -> list[str]:
    return [e.message for e in errors]


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


# ---------------------------------------------------------------------------
# Schema: missing required application fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field,pointer", [
    ("name", "application.name"),
    ("version", "application.version"),
    ("bundle_id", "application.bundle_id"),
    ("icon", "application.icon"),
])
def test_missing_application_field(tmp_path, field, pointer):
    app = {k: v for k, v in VALID_RECIPE["application"].items() if k != field}
    recipe = {**VALID_RECIPE, "application": app}
    errors = errors_for(recipe, tmp_path)
    assert pointer in pointers(errors), f"Expected error at {pointer}, got: {pointers(errors)}"
    err = next(e for e in errors if e.pointer == pointer)
    assert "required field missing" in err.message


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
    recipe = {**VALID_RECIPE, "matika": matika}
    errors = errors_for(recipe, tmp_path)
    assert pointer in pointers(errors), f"Expected error at {pointer}, got: {pointers(errors)}"
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
    recipe = {**VALID_RECIPE, "applugs": []}
    path = write_recipe(tmp_path, recipe)
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
    "0.0.4_dev",
    "0.0.4-rc1",
    "0.0.4+build",
])
def test_invalid_application_version(tmp_path, bad_version):
    recipe = {**VALID_RECIPE, "application": {**VALID_RECIPE["application"], "version": bad_version}}
    errors = errors_for(recipe, tmp_path)
    assert "application.version" in pointers(errors), (
        f"Expected version error for {bad_version!r}, got: {pointers(errors)}"
    )


def test_dev_suffix_in_applug_version_rejected(tmp_path):
    plug = {**VALID_RECIPE["applugs"][0], "version": "0.0.4_dev"}
    recipe = {**VALID_RECIPE, "applugs": [plug]}
    errors = errors_for(recipe, tmp_path)
    assert "applugs[0].version" in pointers(errors)


def test_dev_suffix_in_applug_matika_version_rejected(tmp_path):
    plug = {**VALID_RECIPE["applugs"][0], "matika_version": "0.0.4_dev"}
    recipe = {
        **VALID_RECIPE,
        "matika": {**VALID_RECIPE["matika"], "version": "0.0.4_dev"},
        "applugs": [plug],
    }
    errors = errors_for(recipe, tmp_path)
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
    errors = errors_for(recipe, tmp_path)
    assert "application.bundle_id" in pointers(errors), (
        f"Expected bundle_id error for {bad_id!r} ({reason}), got: {pointers(errors)}"
    )
    err = next(e for e in errors if e.pointer == "application.bundle_id")
    assert "reverse-DNS" in err.message


# ---------------------------------------------------------------------------
# Per-applug: missing required fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["name", "repo", "version", "matika_version", "tag"])
def test_missing_applug_field(tmp_path, field):
    plug = {k: v for k, v in VALID_RECIPE["applugs"][0].items() if k != field}
    recipe = {**VALID_RECIPE, "applugs": [plug]}
    path = write_recipe(tmp_path, recipe)
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

    recipe = {
        **VALID_RECIPE,
        "applugs": [
            {
                "name": "eyerate",
                "repo": "github.com/pjtallman/EyeRate",
                "version": "0.0.2",
                "matika_version": "0.0.2",
                "tag": "v0.0.2",
            },
            {
                "name": "other",
                "repo": "github.com/pjtallman/Other",
                "version": "1.0.0",
                "matika_version": "0.0.1",
                "tag": "v1.0.0",
            },
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

    recipe = {
        **VALID_RECIPE,
        "applugs": [
            {
                "name": "eyerate",
                "repo": "github.com/pjtallman/EyeRate",
                "version": "0.0.2",
                "matika_version": "0.0.2",
                "tag": "v0.0.2",
            },
            {
                "name": "other",
                "repo": "github.com/pjtallman/Other",
                "version": "0.0.2",
                "matika_version": "0.0.2",
                "tag": "v0.0.2",
            },
        ],
    }
    path = write_recipe(tmp_path, recipe)
    errors = validate(path, resolvers={"github.com": _MultiResolver()})
    consistency_errors = [e for e in errors if "conflicting" in str(e)]
    assert consistency_errors == []


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
    assert '"0.0.1"' in err.message
    assert '"0.0.2"' in err.message


# ---------------------------------------------------------------------------
# Remote verification: happy path
# ---------------------------------------------------------------------------

def test_valid_manifest_passes(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers=ok_resolvers(VALID_MANIFEST))
    resolve_errors = [e for e in errors if "resolve" in e.pointer]
    assert resolve_errors == []


# ---------------------------------------------------------------------------
# Remote verification: 404 on applug.json
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


# ---------------------------------------------------------------------------
# Remote verification: 404 on repo (canonicalization)
# ---------------------------------------------------------------------------

def test_repo_not_found_fails(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(
        path,
        resolvers={"github.com": _ErrorResolver(
            LookupError('repository "pjtallman/EyeRate" not found on GitHub')
        )},
    )
    assert any("repo" in e.pointer for e in errors)
    err = next(e for e in errors if "repo" in e.pointer)
    assert "not found" in err.message


# ---------------------------------------------------------------------------
# Remote verification: field mismatches
# ---------------------------------------------------------------------------

def test_applug_json_id_mismatch_fails(tmp_path):
    wrong = AppLugManifest(id="wrong-id", version="0.0.2", matika_version="0.0.2")
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers=ok_resolvers(wrong))
    assert any("resolve" in e.pointer for e in errors)
    err = next(e for e in errors if "resolve" in e.pointer)
    assert '"wrong-id"' in err.message
    assert '"eyerate"' in err.message


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
    assert owner == "pjtallman"
    assert repo == "Matika"


# ---------------------------------------------------------------------------
# Dispatch: resolver_for()
# ---------------------------------------------------------------------------

def test_dispatch_github_routes_to_github_resolver():
    res = resolver_for("github.com/owner/repo", allowed_hosts=["github.com"])
    assert isinstance(res, GitHubResolver)


def test_dispatch_host_not_allowed(tmp_path):
    plug = {**VALID_RECIPE["applugs"][0], "repo": "evil.com/owner/plugin"}
    recipe = {**VALID_RECIPE, "applugs": [plug]}
    path = write_recipe(tmp_path, recipe)
    errors = validate(path, allowed_hosts=["github.com"])
    assert any("repo" in e.pointer for e in errors)
    err = next(e for e in errors if "repo" in e.pointer)
    assert "not in allowed_hosts" in err.message


def test_dispatch_allowed_but_no_resolver(tmp_path):
    plug = {**VALID_RECIPE["applugs"][0], "repo": "fakehub.com/owner/plugin"}
    recipe = {**VALID_RECIPE, "applugs": [plug]}
    path = write_recipe(tmp_path, recipe)
    errors = validate(path, allowed_hosts=["fakehub.com"])
    assert any("repo" in e.pointer for e in errors)
    err = next(e for e in errors if "repo" in e.pointer)
    assert "allowed but no resolver" in err.message


# ---------------------------------------------------------------------------
# Config: load_allowed_hosts()
# ---------------------------------------------------------------------------

def test_config_file_present_and_valid(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"allowed_hosts": ["github.com", "gitlab.com"]}')
    monkeypatch.setattr(_config, "_CONFIG_FILE", cfg)
    monkeypatch.delenv("AHIMSA_ALLOWED_HOSTS", raising=False)
    assert load_allowed_hosts() == ["github.com", "gitlab.com"]


def test_config_file_missing_returns_default(tmp_path, monkeypatch):
    monkeypatch.setattr(_config, "_CONFIG_FILE", tmp_path / "missing.json")
    monkeypatch.delenv("AHIMSA_ALLOWED_HOSTS", raising=False)
    assert load_allowed_hosts() == ["github.com"]


def test_config_file_malformed_raises(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{not valid json")
    monkeypatch.setattr(_config, "_CONFIG_FILE", cfg)
    monkeypatch.delenv("AHIMSA_ALLOWED_HOSTS", raising=False)
    with pytest.raises(ValueError, match="malformed JSON"):
        load_allowed_hosts()


def test_config_env_var_overrides_file(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"allowed_hosts": ["github.com"]}')
    monkeypatch.setattr(_config, "_CONFIG_FILE", cfg)
    monkeypatch.setenv("AHIMSA_ALLOWED_HOSTS", "gitlab.com, bitbucket.org")
    assert load_allowed_hosts() == ["gitlab.com", "bitbucket.org"]


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
    """Lowercase repo string resolves to canonical casing in the raw URL."""
    import validate_recipe as vr
    vr._repo_cache.clear()

    resolver = GitHubResolver()
    api_resp = _make_mock_response({"full_name": "pjtallman/EyeRate"})
    raw_resp = _make_mock_response({"id": "eyerate", "version": "0.0.2", "matika_version": "0.0.2"})

    captured_urls: list[str] = []

    def fake_get(url, **kwargs):
        captured_urls.append(url)
        if "api.github.com" in url:
            return api_resp
        return raw_resp

    with patch("requests.get", side_effect=fake_get):
        manifest = resolver.resolve("eyerate", "github.com/pjtallman/eyerate", "v0.0.2")

    raw_urls = [u for u in captured_urls if "raw.githubusercontent.com" in u]
    assert raw_urls, "Expected a raw.githubusercontent.com fetch"
    assert "EyeRate" in raw_urls[0], (
        f"Expected canonical casing 'EyeRate' in URL, got: {raw_urls[0]}"
    )
    assert manifest.id == "eyerate"


def test_github_resolver_cache_one_api_call():
    """Two resolve() calls for the same repo hit the GitHub API exactly once."""
    import validate_recipe as vr
    vr._repo_cache.clear()

    resolver = GitHubResolver()
    api_resp = _make_mock_response({"full_name": "pjtallman/EyeRate"})
    raw_resp = _make_mock_response({"id": "eyerate", "version": "0.0.2", "matika_version": "0.0.2"})

    def fake_get(url, **kwargs):
        if "api.github.com" in url:
            return api_resp
        return raw_resp

    with patch("requests.get", side_effect=fake_get) as mock_get:
        resolver.resolve("eyerate", "github.com/pjtallman/EyeRate", "v0.0.2")
        resolver.resolve("eyerate", "github.com/pjtallman/EyeRate", "v0.0.3")

    api_calls = [
        c for c in mock_get.call_args_list
        if "api.github.com" in c.args[0]
    ]
    assert len(api_calls) == 1, (
        f"Expected 1 GitHub API call, got {len(api_calls)}"
    )


def test_github_resolver_cache_case_insensitive():
    """Cache treats same repo in different casing as one entry."""
    import validate_recipe as vr
    vr._repo_cache.clear()

    resolver = GitHubResolver()
    api_resp = _make_mock_response({"full_name": "pjtallman/EyeRate"})
    raw_resp = _make_mock_response({"id": "eyerate", "version": "0.0.2", "matika_version": "0.0.2"})

    def fake_get(url, **kwargs):
        if "api.github.com" in url:
            return api_resp
        return raw_resp

    with patch("requests.get", side_effect=fake_get) as mock_get:
        resolver.resolve("eyerate", "github.com/pjtallman/eyerate", "v0.0.2")
        resolver.resolve("eyerate", "github.com/PJTALLMAN/EYERATE", "v0.0.3")

    api_calls = [
        c for c in mock_get.call_args_list
        if "api.github.com" in c.args[0]
    ]
    assert len(api_calls) == 1, (
        f"Different casings of same repo should share one cache entry; got {len(api_calls)} API calls"
    )
