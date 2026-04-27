"""
Tests for scripts/validate_recipe.py.

All network calls are intercepted by patching validate_recipe._fetch_json
so tests run offline.
"""

import json
import sys
import os
from unittest.mock import patch

import pytest

# Make the scripts/ directory importable regardless of where pytest is invoked.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from validate_recipe import validate, CheckResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_recipe(tmp_path, data: dict) -> str:
    p = tmp_path / "recipe.json"
    p.write_text(json.dumps(data))
    return str(p)


def passed(results: list[CheckResult]) -> list[str]:
    return [r.label + ": " + r.message for r in results if r.passed]


def failed(results: list[CheckResult]) -> list[str]:
    return [r.label + ": " + r.message for r in results if not r.passed]


VALID_RECIPE = {
    "application": {
        "name": "Test App",
        "version": "1.0.0",
        "bundle_id": "com.example.test",
        "icon": "assets/icon.icns",
    },
    "matika": {"version": "0.0.2"},
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

REMOTE_APPLUG_JSON = {"id": "eyerate", "version": "0.0.2", "matika_version": "0.0.2"}


# ---------------------------------------------------------------------------
# 1. Valid recipe passes all checks
# ---------------------------------------------------------------------------

def test_valid_recipe_passes_all_checks(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)

    with patch("validate_recipe._fetch_json", return_value=REMOTE_APPLUG_JSON):
        results = validate(path)

    failures = failed(results)
    assert failures == [], f"Unexpected failures: {failures}"
    assert all(r.passed for r in results)


# ---------------------------------------------------------------------------
# 2. Mismatched matika_version across applugs fails
# ---------------------------------------------------------------------------

def test_mismatched_matika_version_across_applugs_fails(tmp_path):
    recipe = {
        **VALID_RECIPE,
        "applugs": [
            {
                "name": "eyerate",
                "repo": "github.com/pjtallman/eyerate",
                "version": "0.0.2",
                "matika_version": "0.0.2",
                "tag": "v0.0.2",
            },
            {
                "name": "otherplugin",
                "repo": "github.com/pjtallman/otherplugin",
                "version": "1.0.0",
                "matika_version": "0.0.1",   # different — conflict
                "tag": "v1.0.0",
            },
        ],
    }
    path = write_recipe(tmp_path, recipe)

    remote_eyerate = {"id": "eyerate", "matika_version": "0.0.2"}
    remote_other = {"id": "otherplugin", "matika_version": "0.0.1"}

    def fake_fetch(url):
        if "eyerate" in url:
            return remote_eyerate
        return remote_other

    with patch("validate_recipe._fetch_json", side_effect=fake_fetch):
        results = validate(path)

    failure_msgs = failed(results)
    assert any("conflicting matika_version" in m for m in failure_msgs), (
        f"Expected a conflicting matika_version failure, got: {failure_msgs}"
    )


# ---------------------------------------------------------------------------
# 3. Missing required field fails
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_field,expected_label", [
    ("name",    "application.name"),
    ("version", "application.version"),
])
def test_missing_application_field_fails(tmp_path, missing_field, expected_label):
    recipe = {
        "application": {k: v for k, v in VALID_RECIPE["application"].items() if k != missing_field},
        "matika": VALID_RECIPE["matika"],
        "applugs": VALID_RECIPE["applugs"],
    }
    path = write_recipe(tmp_path, recipe)

    with patch("validate_recipe._fetch_json", return_value=REMOTE_APPLUG_JSON):
        results = validate(path)

    failure_msgs = failed(results)
    assert any(expected_label in m for m in failure_msgs), (
        f"Expected failure mentioning '{expected_label}', got: {failure_msgs}"
    )


def test_missing_matika_version_fails(tmp_path):
    recipe = {**VALID_RECIPE, "matika": {}}
    path = write_recipe(tmp_path, recipe)

    with patch("validate_recipe._fetch_json", return_value=REMOTE_APPLUG_JSON):
        results = validate(path)

    failure_msgs = failed(results)
    assert any("matika.version" in m for m in failure_msgs), (
        f"Expected failure mentioning 'matika.version', got: {failure_msgs}"
    )


def test_missing_applugs_field_fails(tmp_path):
    recipe = {"application": VALID_RECIPE["application"], "matika": VALID_RECIPE["matika"]}
    path = write_recipe(tmp_path, recipe)

    results = validate(path)

    failure_msgs = failed(results)
    assert any("applugs" in m for m in failure_msgs), (
        f"Expected failure mentioning 'applugs', got: {failure_msgs}"
    )


def test_empty_applugs_array_fails(tmp_path):
    recipe = {**VALID_RECIPE, "applugs": []}
    path = write_recipe(tmp_path, recipe)

    results = validate(path)

    failure_msgs = failed(results)
    assert any("applugs" in m for m in failure_msgs), (
        f"Expected failure mentioning 'applugs', got: {failure_msgs}"
    )


# ---------------------------------------------------------------------------
# 4. applug matika_version mismatch with recipe.matika.version fails
# ---------------------------------------------------------------------------

def test_applug_matika_version_mismatch_with_recipe_fails(tmp_path):
    recipe = {
        **VALID_RECIPE,
        "applugs": [
            {
                **VALID_RECIPE["applugs"][0],
                "matika_version": "0.0.1",   # recipe says 0.0.2
            }
        ],
    }
    path = write_recipe(tmp_path, recipe)

    remote = {"id": "eyerate", "matika_version": "0.0.1"}
    with patch("validate_recipe._fetch_json", return_value=remote):
        results = validate(path)

    failure_msgs = failed(results)
    assert any("does not match recipe matika.version" in m for m in failure_msgs), (
        f"Expected a matika_version mismatch failure, got: {failure_msgs}"
    )


def test_remote_applug_matika_version_mismatch_fails(tmp_path):
    """Fetched applug.json declares a different matika_version than the recipe."""
    path = write_recipe(tmp_path, VALID_RECIPE)

    remote = {"id": "eyerate", "matika_version": "0.0.1"}   # recipe says 0.0.2
    with patch("validate_recipe._fetch_json", return_value=remote):
        results = validate(path)

    failure_msgs = failed(results)
    assert any("matika_version" in m and "does not match" in m for m in failure_msgs), (
        f"Expected a remote matika_version mismatch failure, got: {failure_msgs}"
    )


# ---------------------------------------------------------------------------
# 5. Missing applug array entry fields fails
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_field", ["name", "repo", "version", "matika_version", "tag"])
def test_missing_applug_entry_field_fails(tmp_path, missing_field):
    plug = {k: v for k, v in VALID_RECIPE["applugs"][0].items() if k != missing_field}
    recipe = {**VALID_RECIPE, "applugs": [plug]}
    path = write_recipe(tmp_path, recipe)

    # Structurally invalid applugs skip the resolve step — no network mock needed.
    results = validate(path)

    failure_msgs = failed(results)
    assert any(f"'{missing_field}'" in m for m in failure_msgs), (
        f"Expected failure mentioning '{missing_field}', got: {failure_msgs}"
    )


# ---------------------------------------------------------------------------
# Edge: resolve fetch failure is reported as FAIL, not exception
# ---------------------------------------------------------------------------

def test_resolve_network_failure_is_a_fail_not_an_exception(tmp_path):
    path = write_recipe(tmp_path, VALID_RECIPE)

    with patch("validate_recipe._fetch_json", side_effect=RuntimeError("HTTP 404 fetching ...")):
        results = validate(path)

    failure_msgs = failed(results)
    assert any("resolve" in r.label for r in results if not r.passed), (
        f"Expected a resolve failure, got: {failure_msgs}"
    )
    # Must not propagate as an unhandled exception — validate() returns normally.
