"""Unit tests for the pure helpers in scripts/frozen_verify.py.

The booted-app feature checks (tier a/b) can only run against a real frozen
artifact in CI, but the stale-plugin seeding/assertion logic and the CSRF
extraction are pure functions that MUST be correct — a bug here would make the
upgrade-over-stale proof silently vacuous. These tests pin them.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "frozen_verify.py"


@pytest.fixture(scope="module")
def fv():
    spec = importlib.util.spec_from_file_location("frozen_verify", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_fresh_eyerate(home: Path) -> Path:
    """Create a freshly-extracted eyerate plugin (as the first boot would)."""
    plugin = home / "matika" / "plugins" / "eyerate"
    tmpl = plugin / "src" / "eyerate" / "templates" / "eyerate_admin.html"
    tmpl.parent.mkdir(parents=True, exist_ok=True)
    tmpl.write_text("<legend>Financial Data Provider</legend>")
    (plugin / "applug.json").write_text(json.dumps({"id": "eyerate", "version": "0.0.4"}))
    (plugin / ".matika_plugin_install.json").write_text(
        json.dumps({"version": "0.0.4", "code_fingerprint": "abc", "files": []})
    )
    return plugin


def test_extract_csrf_both_attr_orders(fv):
    assert fv._extract_csrf('<input name="csrf_token" value="Tok123">') == "Tok123"
    assert fv._extract_csrf('<input value="ZZZ" name="csrf_token">') == "ZZZ"
    assert fv._extract_csrf("<input name='other' value='x'>") is None


def test_seed_stale_eyerate_makes_it_look_pre_fix(fv, tmp_path):
    plugin = _make_fresh_eyerate(tmp_path)
    fv._seed_stale_eyerate(str(tmp_path))

    tmpl = plugin / "src" / "eyerate" / "templates" / "eyerate_admin.html"
    assert "coming soon" in tmpl.read_text().lower()
    manifest = json.loads((plugin / "applug.json").read_text())
    assert manifest["version"] == "0.0.1"
    assert not (plugin / ".matika_plugin_install.json").exists()
    assert (plugin / fv.USER_DATA_NAME).read_text() == fv.USER_DATA_CONTENT


def test_seed_stale_eyerate_requires_extracted_plugin(fv, tmp_path):
    """If the first boot never extracted eyerate, seeding must fail loudly."""
    with pytest.raises(fv.FrozenAppError):
        fv._seed_stale_eyerate(str(tmp_path))


def test_assert_refreshed_passes_when_refreshed_and_data_kept(fv, tmp_path):
    plugin = _make_fresh_eyerate(tmp_path)
    # Simulate the launcher having refreshed the (previously stale) plugin:
    # fresh template on disk + user data preserved.
    (plugin / fv.USER_DATA_NAME).write_text(fv.USER_DATA_CONTENT)
    boot_log = "plugin eyerate: installed 0.0.1, bundled 0.0.4 -> refreshed (...)"
    fv._assert_refreshed(str(tmp_path), boot_log)  # must not raise


def test_assert_refreshed_fails_without_refresh_log(fv, tmp_path):
    plugin = _make_fresh_eyerate(tmp_path)
    (plugin / fv.USER_DATA_NAME).write_text(fv.USER_DATA_CONTENT)
    with pytest.raises(fv.FrozenAppError):
        fv._assert_refreshed(str(tmp_path), "boot log with no refresh line")


def test_assert_refreshed_fails_if_user_data_destroyed(fv, tmp_path):
    _make_fresh_eyerate(tmp_path)  # no USER_DATA_NAME written → destroyed
    boot_log = "plugin eyerate: installed 0.0.1, bundled 0.0.4 -> refreshed"
    with pytest.raises(fv.FrozenAppError):
        fv._assert_refreshed(str(tmp_path), boot_log)


def test_assert_refreshed_fails_if_stale_template_remains(fv, tmp_path):
    plugin = _make_fresh_eyerate(tmp_path)
    (plugin / fv.USER_DATA_NAME).write_text(fv.USER_DATA_CONTENT)
    # Stale template still on disk after the supposed refresh.
    (plugin / "src" / "eyerate" / "templates" / "eyerate_admin.html").write_text(
        "Administration features coming soon"
    )
    boot_log = "plugin eyerate: installed 0.0.1, bundled 0.0.4 -> refreshed"
    with pytest.raises(fv.FrozenAppError):
        fv._assert_refreshed(str(tmp_path), boot_log)
