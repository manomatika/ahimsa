"""
Run R5 (manomatika/ahimsa#128): ahimsa's own 31 error codes + `validate_recipe.Error.code`.

Three concerns, each with its own section below:

  1. Registry integrity — ``error-codes.yaml`` lints clean under the R0
     mechanism, declares exactly 32 codes (ahimsa numbers each facility
     contiguously from 001 by convention, though the lint no longer requires
     it — NNN is opaque/monotonic and gaps are allowed), is
     English-only (``supported_locales: [en]`` — ahimsa is the en-only
     carve-out, no es catalog), the checked-in
     ``ahimsa/error_code_constants.py`` is byte-identical to what the
     generator produces from that source RIGHT NOW (guards against hand-edited
     drift or a stale regen), and the ``ahimsa/locales/en.json`` catalog is a
     1:1, message-for-message mirror of the registry (en-from-registry).

  2. ``Error.code`` fail-loud construction — a non-``None`` code must be a
     well-formed ``AHIMSA-<FAC>-<NNN>`` string (reusing the same pattern the
     ``ManoMatikaError`` base class enforces); ``None`` (the default) is
     still accepted for construction sites this run does not touch.

  3. Threading — every ``validate_recipe.validate()`` / ``validate_releases()``
     finding carries its specific registered code (not just pointer/message),
     the ``matika.*`` / ``applugs[i].*`` wrap sites in ``validate()`` propagate
     the inner ``validate_releases`` code unchanged, and the ``--config``
     CLI failure paths (both console scripts) surface the two ``AHIMSA-CLI-*``
     codes.

Every test in section 3 FAILS on pre-R5 code (which never set ``.code``, so
every assertion below would see ``None``) and PASSES with the fix — the
run-22 regression contract.
"""

import json
from pathlib import Path

import pytest

from ahimsa import error_code_constants as ec
from ahimsa.error_codes import load_error_codes, render_constants_module
from ahimsa.manomatika_error import CODE_RE
from ahimsa.validate_recipe import (
    AppLugManifest,
    BaseResolver,
    Error,
    main as validate_recipe_main,
    validate,
)
from ahimsa.validate_releases import main as validate_releases_main, validate_releases

REPO_ROOT = Path(__file__).parent.parent
REGISTRY_PATH = REPO_ROOT / "error-codes.yaml"
CONSTANTS_PATH = REPO_ROOT / "ahimsa" / "error_code_constants.py"
CATALOG_PATH = REPO_ROOT / "ahimsa" / "locales" / "en.json"


# ---------------------------------------------------------------------------
# Shared fixtures (self-contained — no cross-test-file imports, matching this
# repo's convention).
# ---------------------------------------------------------------------------

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


def write_recipe(tmp_path, data) -> Path:
    p = tmp_path / "recipe.json"
    if isinstance(data, str):
        p.write_text(data)
    else:
        p.write_text(json.dumps(data))
    return p


class _OkResolver(BaseResolver):
    """Always returns a fixed manifest; fetch_text/list_tags opt this repo out
    of release-log auditing (returns None / []) so tests stay focused on the
    condition under test."""

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
    """resolve() always raises a fixed exception; release-log auditing opted out."""

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
    path = write_recipe(tmp_path, recipe)
    return validate(path, resolvers=ok_resolvers(), **kw)


def codes_of(errors: list[Error]) -> set[str | None]:
    return {e.code for e in errors}


class _ReleasesMock(BaseResolver):
    """Mirrors tests/test_validate_releases.py's single-repo mock."""

    def __init__(
        self,
        *,
        releases_md: str | None = None,
        tags: list[str] | None = None,
        fetch_exc: Exception | None = None,
        tags_exc: Exception | None = None,
    ) -> None:
        super().__init__(host="github.com")
        self._text = releases_md
        self._tags = list(tags) if tags is not None else []
        self._fetch_exc = fetch_exc
        self._tags_exc = tags_exc

    def _canonicalize_repo(self, owner: str, repo: str) -> tuple[str, str]:
        return (owner, repo)

    def _raw_url(self, canonical: tuple[str, str], tag: str, path: str) -> str:
        return ""

    def fetch_text(self, repo: str, ref: str, path: str) -> str | None:
        if path == "release-log.yaml":
            return None
        if self._fetch_exc is not None:
            raise self._fetch_exc
        return self._text

    def list_tags(self, repo: str) -> list[str]:
        if self._tags_exc is not None:
            raise self._tags_exc
        return list(self._tags)


REPO = "github.com/manomatika/matika"


# ---------------------------------------------------------------------------
# 1. Registry integrity
# ---------------------------------------------------------------------------


def test_registry_lints_clean_and_is_ahimsa_english_only():
    ecf = load_error_codes(REGISTRY_PATH)
    assert ecf.origin == "ahimsa"
    assert ecf.component == "AHIMSA"
    assert ecf.supported_locales == ["en"]  # the English-only carve-out — no es


def test_registry_declares_exactly_32_codes():
    ecf = load_error_codes(REGISTRY_PATH)
    assert len(ecf.codes) == 32


def test_registry_facilities_are_contiguous_from_001():
    """ahimsa numbers each of its OWN facilities contiguously from 001 as a
    housekeeping convention. The lint no longer REQUIRES contiguity (NNN is
    opaque/monotonic — gaps are allowed ecosystem-wide); this asserts ahimsa's
    self-imposed tidiness so an accidental gap in ahimsa's own registry is
    noticed and made deliberate."""
    ecf = load_error_codes(REGISTRY_PATH)
    by_facility: dict[str, list[int]] = {}
    for c in ecf.codes:
        by_facility.setdefault(c.facility, []).append(c.number)
    for facility, numbers in by_facility.items():
        assert sorted(numbers) == list(range(1, len(numbers) + 1)), (
            f"{facility} is not contiguous from 001: {sorted(numbers)}"
        )


def test_registry_all_codes_well_formed_ahimsa_prefix():
    ecf = load_error_codes(REGISTRY_PATH)
    for c in ecf.codes:
        assert CODE_RE.match(c.code), f"{c.code} is not well-formed"
        assert c.code.startswith("AHIMSA-"), f"{c.code} does not carry the AHIMSA component prefix"


def test_generated_constants_module_round_trips_from_source():
    """The checked-in ahimsa/error_code_constants.py is exactly what
    render_constants_module(load_error_codes(error-codes.yaml)) produces RIGHT
    NOW. Fails if the source is edited without regenerating, or the generated
    file is hand-edited out of sync with the source (rule 18: one canonical
    source of truth for the constants)."""
    ecf = load_error_codes(REGISTRY_PATH)
    expected = render_constants_module(ecf)
    actual = CONSTANTS_PATH.read_text()
    assert actual == expected


def test_all_code_constants_are_exported_and_registered():
    ecf = load_error_codes(REGISTRY_PATH)
    for c in ecf.codes:
        const_name = c.code.replace("-", "_")
        assert hasattr(ec, const_name), f"missing generated constant {const_name}"
        assert getattr(ec, const_name) == c.code
        assert c.code in ec.ALL_CODES


def test_en_catalog_exists_and_is_english_only():
    assert CATALOG_PATH.exists(), f"missing en catalog at {CATALOG_PATH}"
    catalog = json.loads(CATALOG_PATH.read_text())
    assert set(catalog.keys()) == {"errors"}
    # ahimsa carries no es catalog file (the English-only carve-out).
    assert not (CATALOG_PATH.parent / "es.json").exists()


def test_en_catalog_matches_registry_message_for_every_code():
    """en-from-registry (Q16): the catalog is sourced FROM the registry, so it
    can never drift — every code's message must match verbatim, and the
    catalog must declare no code the registry doesn't (and vice versa)."""
    ecf = load_error_codes(REGISTRY_PATH)
    catalog = json.loads(CATALOG_PATH.read_text())["errors"]

    registry_messages = {c.code: c.message for c in ecf.codes}
    assert set(catalog.keys()) == set(registry_messages.keys())
    for code, message in registry_messages.items():
        assert catalog[code] == message, f"{code}: catalog text drifted from the registry"


# ---------------------------------------------------------------------------
# 2. Error.code fail-loud construction
# ---------------------------------------------------------------------------


def test_error_code_defaults_to_none():
    err = Error("some.pointer", "some message")
    assert err.code is None


def test_error_accepts_wellformed_registered_code():
    err = Error("application.icon", "required field missing", code=ec.AHIMSA_APP_001)
    assert err.code == "AHIMSA-APP-001"


@pytest.mark.parametrize("bad_code", [
    "not-a-code",
    "ahimsa-app-001",   # lowercase
    "AHIMSA-APP-1",     # not zero-padded to 3
    "AHIMSA-APP",       # missing NNN
    "",
])
def test_error_rejects_malformed_code(bad_code):
    with pytest.raises(ValueError) as exc:
        Error("some.pointer", "some message", code=bad_code)
    assert repr(bad_code) in str(exc.value)


def test_error_rejects_non_string_code():
    with pytest.raises(ValueError):
        Error("some.pointer", "some message", code=123)


# ---------------------------------------------------------------------------
# 3a. validate_recipe.validate() — Error.code threading
# ---------------------------------------------------------------------------


def test_recipe_file_not_found_carries_code(tmp_path):
    errors = validate(tmp_path / "nope.json", resolvers=ok_resolvers())
    assert ec.AHIMSA_RECIPE_001 in codes_of(errors)


def test_recipe_invalid_json_carries_code(tmp_path):
    path = write_recipe(tmp_path, "{not valid json")
    errors = validate(path, resolvers=ok_resolvers())
    assert ec.AHIMSA_RECIPE_002 in codes_of(errors)


def test_applugs_missing_carries_code(tmp_path):
    recipe = {k: v for k, v in VALID_RECIPE.items() if k != "applugs"}
    errors = _validate(recipe, tmp_path)
    err = next(e for e in errors if e.pointer == "applugs")
    assert err.code == ec.AHIMSA_RECIPE_003


def test_applugs_empty_array_carries_code(tmp_path):
    errors = _validate({**VALID_RECIPE, "applugs": []}, tmp_path)
    err = next(e for e in errors if e.pointer == "applugs")
    assert err.code == ec.AHIMSA_RECIPE_003


def test_conflicting_matika_versions_carries_code(tmp_path):
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
    err = next(e for e in errors if "conflicting matika_version" in e.message)
    assert err.code == ec.AHIMSA_RECIPE_004


@pytest.mark.parametrize("field,pointer", [
    ("name", "application.name"),
    ("product_name", "application.product_name"),
    ("version", "application.version"),
    ("bundle_id", "application.bundle_id"),
    ("icon", "application.icon"),
])
def test_missing_application_field_carries_code(tmp_path, field, pointer):
    app = {k: v for k, v in VALID_RECIPE["application"].items() if k != field}
    errors = _validate({**VALID_RECIPE, "application": app}, tmp_path)
    err = next(e for e in errors if e.pointer == pointer)
    assert err.code == ec.AHIMSA_APP_001


def test_invalid_product_name_carries_code(tmp_path):
    recipe = {**VALID_RECIPE, "application": {**VALID_RECIPE["application"], "product_name": "Mano_Matika"}}
    errors = _validate(recipe, tmp_path)
    err = next(e for e in errors if e.pointer == "application.product_name")
    assert err.code == ec.AHIMSA_APP_002


def test_invalid_bundle_id_carries_code(tmp_path):
    recipe = {**VALID_RECIPE, "application": {**VALID_RECIPE["application"], "bundle_id": "com.example"}}
    errors = _validate(recipe, tmp_path)
    err = next(e for e in errors if e.pointer == "application.bundle_id")
    assert err.code == ec.AHIMSA_APP_003


def test_invalid_application_version_carries_code(tmp_path):
    recipe = {**VALID_RECIPE, "application": {**VALID_RECIPE["application"], "version": "latest"}}
    errors = _validate(recipe, tmp_path)
    err = next(e for e in errors if e.pointer == "application.version")
    assert err.code == ec.AHIMSA_APP_004


@pytest.mark.parametrize("field,pointer", [
    ("version", "matika.version"),
    ("repo", "matika.repo"),
    ("tag", "matika.tag"),
])
def test_missing_matika_field_carries_code(tmp_path, field, pointer):
    matika = {k: v for k, v in VALID_RECIPE["matika"].items() if k != field}
    errors = _validate({**VALID_RECIPE, "matika": matika}, tmp_path)
    err = next(e for e in errors if e.pointer == pointer)
    assert err.code == ec.AHIMSA_MATIKA_001


def test_invalid_matika_version_carries_code(tmp_path):
    recipe = {**VALID_RECIPE, "matika": {**VALID_RECIPE["matika"], "version": "0.0.4-dev"}}
    errors = _validate(recipe, tmp_path)
    err = next(e for e in errors if e.pointer == "matika.version")
    assert err.code == ec.AHIMSA_MATIKA_002


@pytest.mark.parametrize("field", ["name", "repo", "version", "matika_version", "tag"])
def test_missing_applug_field_carries_code(tmp_path, field):
    plug = {k: v for k, v in VALID_RECIPE["applugs"][0].items() if k != field}
    errors = _validate({**VALID_RECIPE, "applugs": [plug]}, tmp_path)
    err = next(e for e in errors if e.pointer == f"applugs[0].{field}")
    assert err.code == ec.AHIMSA_PLUG_001


def test_applug_matika_version_mismatch_carries_code(tmp_path):
    plug = {**VALID_RECIPE["applugs"][0], "matika_version": "0.0.1"}
    recipe = {**VALID_RECIPE, "applugs": [plug]}
    path = write_recipe(tmp_path, recipe)
    resolver = _OkResolver(AppLugManifest(id="eyerate", version="0.0.2", matika_version="0.0.1"))
    errors = validate(path, resolvers={"github.com": resolver})
    err = next(e for e in errors if e.pointer == "applugs[0].matika_version")
    assert err.code == ec.AHIMSA_PLUG_002


@pytest.mark.parametrize("field", ["version", "matika_version"])
def test_invalid_applug_version_fields_carry_code(tmp_path, field):
    plug = {**VALID_RECIPE["applugs"][0], field: "0.0.4-dev"}
    recipe = {**VALID_RECIPE, "matika": {**VALID_RECIPE["matika"], "version": "0.0.4-dev"}, "applugs": [plug]}
    errors = _validate(recipe, tmp_path)
    err = next(e for e in errors if e.pointer == f"applugs[0].{field}")
    assert err.code == ec.AHIMSA_PLUG_003


def test_resolve_no_resolver_test_injected_carries_code(tmp_path):
    """resolvers={} (test-injected dict without the recipe's host)."""
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers={})
    err = next(e for e in errors if e.pointer == "applugs[0].repo")
    assert err.code == ec.AHIMSA_RESOLVE_001


def test_resolve_host_not_allowed_carries_code(tmp_path):
    """resolver_for's PermissionError branch (resolvers=None, production path)."""
    plug = {**VALID_RECIPE["applugs"][0], "repo": "evil.com/owner/plugin"}
    path = write_recipe(tmp_path, {**VALID_RECIPE, "applugs": [plug]})
    errors = validate(path, allowed_hosts=["github.com"])
    err = next(e for e in errors if e.pointer == "applugs[0].repo")
    assert err.code == ec.AHIMSA_RESOLVE_002


def test_resolve_allowed_but_no_resolver_registered_carries_code(tmp_path):
    """resolver_for's LookupError branch (host allowed, no resolver class)."""
    plug = {**VALID_RECIPE["applugs"][0], "repo": "fakehub.com/owner/plugin"}
    path = write_recipe(tmp_path, {**VALID_RECIPE, "applugs": [plug]})
    errors = validate(path, allowed_hosts=["fakehub.com"])
    err = next(e for e in errors if e.pointer == "applugs[0].repo")
    assert err.code == ec.AHIMSA_RESOLVE_002


def test_resolve_value_error_carries_code(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers={"github.com": _ErrorResolver(ValueError("malformed data"))})
    err = next(e for e in errors if e.pointer == "applugs[0].repo")
    assert err.code == ec.AHIMSA_RESOLVE_003


def test_resolve_lookup_error_carries_code(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers={"github.com": _ErrorResolver(LookupError("not found on GitHub"))})
    err = next(e for e in errors if e.pointer == "applugs[0].repo")
    assert err.code == ec.AHIMSA_RESOLVE_004


def test_resolve_permission_error_carries_code(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers={"github.com": _ErrorResolver(PermissionError("denied"))})
    err = next(e for e in errors if e.pointer == "applugs[0].repo")
    assert err.code == ec.AHIMSA_RESOLVE_004


def test_resolve_file_not_found_carries_code(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers={"github.com": _ErrorResolver(FileNotFoundError("file not found"))})
    err = next(e for e in errors if e.pointer == "applugs[0].resolve")
    assert err.code == ec.AHIMSA_RESOLVE_005


def test_resolve_unexpected_exception_carries_code(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers={"github.com": _ErrorResolver(RuntimeError("boom"))})
    err = next(e for e in errors if e.pointer == "applugs[0].resolve")
    assert err.code == ec.AHIMSA_RESOLVE_006


def test_applug_id_mismatch_carries_code(tmp_path):
    wrong = AppLugManifest(id="wrong-id", version="0.0.2", matika_version="0.0.2")
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers=ok_resolvers(wrong))
    err = next(e for e in errors if e.pointer == "applugs[0].resolve" and "id" in e.message)
    assert err.code == ec.AHIMSA_RESOLVE_007


def test_applug_version_mismatch_carries_code(tmp_path):
    wrong = AppLugManifest(id="eyerate", version="9.9.9", matika_version="0.0.2")
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers=ok_resolvers(wrong))
    err = next(e for e in errors if e.pointer == "applugs[0].resolve" and "9.9.9" in e.message)
    assert err.code == ec.AHIMSA_RESOLVE_008


def test_applug_matika_version_manifest_mismatch_carries_code(tmp_path):
    wrong = AppLugManifest(id="eyerate", version="0.0.2", matika_version="0.0.1")
    path = write_recipe(tmp_path, VALID_RECIPE)
    errors = validate(path, resolvers=ok_resolvers(wrong))
    err = next(
        e for e in errors
        if e.pointer == "applugs[0].resolve" and "matika_version" in e.message
    )
    assert err.code == ec.AHIMSA_RESOLVE_009


# ---------------------------------------------------------------------------
# 3b. validate_releases() — Error.code threading
# ---------------------------------------------------------------------------


def test_releases_no_resolver_carries_code():
    mock = _ReleasesMock(releases_md=None, tags=[])
    errors = validate_releases(
        ["example.com/foo/bar"],
        ahimsa_repo="example.com/foo/ahimsa",
        resolvers={"github.com": mock},
    )
    err = next(e for e in errors if e.pointer == "releases.repo")
    assert err.code == ec.AHIMSA_RELEASE_001


def test_releases_host_not_allowed_carries_code():
    errors = validate_releases(
        ["example.com/foo/bar"],
        ahimsa_repo="example.com/foo/ahimsa",
        allowed_hosts=["github.com"],
    )
    err = next(e for e in errors if e.pointer == "releases.repo")
    assert err.code == ec.AHIMSA_RELEASE_002


def test_releases_fetch_failure_carries_code():
    mock = _ReleasesMock(fetch_exc=RuntimeError("network down"))
    errors = validate_releases([REPO], ahimsa_repo=REPO, resolvers={"github.com": mock})
    err = next(e for e in errors if e.pointer == "releases.fetch")
    assert err.code == ec.AHIMSA_RELEASE_003


def test_releases_duplicate_entry_carries_code():
    text = "## matika v0.0.4\n## matika v0.0.4\n"
    mock = _ReleasesMock(releases_md=text, tags=["v0.0.4"])
    errors = validate_releases([REPO], ahimsa_repo=REPO, resolvers={"github.com": mock})
    err = next(e for e in errors if "duplicate entry" in e.message)
    assert err.code == ec.AHIMSA_RELEASE_004


def test_releases_list_tags_failure_carries_code():
    text = "## matika v0.0.4\n"
    mock = _ReleasesMock(releases_md=text, tags_exc=RuntimeError("rate limited"))
    errors = validate_releases([REPO], ahimsa_repo=REPO, resolvers={"github.com": mock})
    err = next(e for e in errors if e.pointer == "releases.tags")
    assert err.code == ec.AHIMSA_RELEASE_005


def test_releases_tag_without_entry_carries_code():
    text = "## matika v0.0.4-dev.0\n"
    mock = _ReleasesMock(releases_md=text, tags=["v0.0.4-dev.0", "v0.0.4-dev.1"])
    errors = validate_releases([REPO], ahimsa_repo=REPO, resolvers={"github.com": mock})
    err = next(e for e in errors if e.pointer == 'releases.tag["v0.0.4-dev.1"]')
    assert err.code == ec.AHIMSA_RELEASE_006


def test_releases_entry_without_tag_carries_code():
    text = "## matika v0.0.4-dev.1\n## matika v0.0.4-dev.99\n"
    mock = _ReleasesMock(releases_md=text, tags=["v0.0.4-dev.1"])
    errors = validate_releases([REPO], ahimsa_repo=REPO, resolvers={"github.com": mock})
    err = next(e for e in errors if e.pointer == 'releases.entry["v0.0.4-dev.99"]')
    assert err.code == ec.AHIMSA_RELEASE_007


# ---------------------------------------------------------------------------
# 3c. validate() wrap sites propagate the inner validate_releases code
# ---------------------------------------------------------------------------


class _MultiRepoMock(BaseResolver):
    """Mirrors tests/test_validate_releases.py's transitive-integration mock."""

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
            return None
        return self._responses.get(repo, {}).get("releases_md")

    def list_tags(self, repo: str) -> list[str]:
        return list(self._responses.get(repo, {}).get("tags", []))


_MM_REPO = "github.com/manomatika/manomatika"


def test_transitive_matika_release_drift_propagates_code(tmp_path):
    recipe_path = write_recipe(tmp_path, VALID_RECIPE)
    releases_md = "## matika v0.0.1\n"  # matika's real tag (v0.0.2) has no entry

    mock = _MultiRepoMock({
        _MM_REPO: {"releases_md": releases_md, "tags": []},
        "github.com/pjtallman/matika": {
            "releases_md": releases_md,
            "tags": ["v0.0.1", "v0.0.2"],
            "manifest": VALID_MANIFEST,
        },
        "github.com/pjtallman/eyerate": {
            "releases_md": None,
            "tags": [],
            "manifest": VALID_MANIFEST,
        },
    })

    errors = validate(recipe_path, resolvers={"github.com": mock})
    err = next(e for e in errors if e.pointer == 'matika.releases.tag["v0.0.2"]')
    assert err.code == ec.AHIMSA_RELEASE_006


def test_transitive_applug_release_drift_propagates_code(tmp_path):
    recipe_path = write_recipe(tmp_path, VALID_RECIPE)
    releases_md = "## eyerate v9.9.9\n"  # entry with no matching eyerate tag

    mock = _MultiRepoMock({
        _MM_REPO: {"releases_md": releases_md, "tags": []},
        "github.com/pjtallman/matika": {"releases_md": None, "tags": [], "manifest": VALID_MANIFEST},
        "github.com/pjtallman/eyerate": {
            "releases_md": releases_md,
            "tags": [],
            "manifest": VALID_MANIFEST,
        },
    })

    errors = validate(recipe_path, resolvers={"github.com": mock})
    err = next(e for e in errors if e.pointer == 'applugs[0].releases.entry["v9.9.9"]')
    assert err.code == ec.AHIMSA_RELEASE_007


# ---------------------------------------------------------------------------
# 3d. CLI --config failures surface AHIMSA-CLI-* codes
# ---------------------------------------------------------------------------


def test_validate_recipe_cli_missing_config_surfaces_code(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.json"
    recipe_path = write_recipe(tmp_path, VALID_RECIPE)
    rc = validate_recipe_main(["--config", str(missing), str(recipe_path)])
    assert rc == 2
    assert ec.AHIMSA_CLI_001 in capsys.readouterr().err


def test_validate_recipe_cli_malformed_config_surfaces_code(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    recipe_path = write_recipe(tmp_path, VALID_RECIPE)
    rc = validate_recipe_main(["--config", str(bad), str(recipe_path)])
    assert rc == 2
    assert ec.AHIMSA_CLI_002 in capsys.readouterr().err


def test_validate_releases_cli_missing_config_surfaces_code(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.json"
    rc = validate_releases_main(["--config", str(missing), REPO])
    assert rc == 2
    assert ec.AHIMSA_CLI_001 in capsys.readouterr().err


def test_validate_releases_cli_malformed_config_surfaces_code(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    rc = validate_releases_main(["--config", str(bad), REPO])
    assert rc == 2
    assert ec.AHIMSA_CLI_002 in capsys.readouterr().err
