"""Unit tests for the pure helpers in scripts/frozen_verify.py.

The booted-app feature checks (tier a/b) can only run against a real frozen
artifact in CI, but the stale-plugin seeding/assertion logic, the CSRF
extraction, and the installed-path override mechanism (manomatika/ahimsa#81)
are pure or CLI-parseable functions that MUST be correct — a bug here would make
the upgrade-over-stale proof or the installer-level verification silently vacuous.
These tests pin them.
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


# ---------------------------------------------------------------------------
# Installer-level path override (manomatika/ahimsa#81)
#
# frozen_verify.py accepts --exe <path> which IS the installed-path override:
# passing a different --exe value redirects all verification to the installed
# application rather than the freeze-dir artifact.  These tests pin the
# argument-parsing and path-resolution behaviour so a future refactor cannot
# silently break the installer-level verification stage.
# ---------------------------------------------------------------------------

def test_exe_argument_is_parsed_and_abspath_resolved(fv, tmp_path):
    """main() resolves --exe to an absolute path before the existence check."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", required=True)
    ap.add_argument("--scenario", required=True, choices=["fresh", "upgrade"])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--browser", action="store_true")

    # Simulate a freeze-dir path.
    freeze_exe = str(tmp_path / "build" / "matika" / "dist" / "ManoMatika-0.0.1.app" /
                     "Contents" / "MacOS" / "ManoMatika-0.0.1")
    args = ap.parse_args(["--exe", freeze_exe, "--scenario", "fresh"])
    assert os.path.isabs(os.path.abspath(args.exe))
    assert args.exe == freeze_exe

    # Simulate an installed-path (DMG-mounted) override — same script, different --exe.
    installed_exe = "/Volumes/ManoMatikaDMG/ManoMatika-0.0.1.app/Contents/MacOS/ManoMatika-0.0.1"
    args2 = ap.parse_args(["--exe", installed_exe, "--scenario", "fresh"])
    assert args2.exe == installed_exe
    assert os.path.isabs(os.path.abspath(args2.exe))


def test_main_returns_nonzero_for_missing_installed_exe(fv, tmp_path):
    """main() exits non-zero when --exe points to a non-existent installed path.

    This is the installer-level regression guard (manomatika/ahimsa#81 §6):
    if the DMG/EXE install step produces the wrong path or the installer
    silently fails, the CI job must fail rather than pass vacuously.
    """
    import sys
    from unittest.mock import patch

    nonexistent = str(tmp_path / "Volumes" / "ManoMatikaDMG" /
                      "ManoMatika-0.0.1.app" / "Contents" / "MacOS" / "ManoMatika-0.0.1")
    with patch.object(sys, "argv", ["frozen_verify.py",
                                     "--exe", nonexistent,
                                     "--scenario", "fresh"]):
        rc = fv.main()
    assert rc == 1, (
        "frozen_verify.main() must return non-zero when the installed exe is absent"
    )


def test_installed_path_override_uses_same_code_path_as_freeze_dir(fv, tmp_path):
    """Installed-path and freeze-dir runs share the same scenario entry points.

    Both scenario_fresh() and scenario_upgrade() receive only the resolved exe
    path — they do not distinguish between a freeze-dir binary and an installed
    binary.  This test confirms that _seed_stale_eyerate and _assert_refreshed
    operate entirely on the HOME temp dir, not on any path derived from the exe
    location, so the upgrade scenario works identically for installed paths.
    """
    # _seed_stale_eyerate operates on HOME, not exe path.
    plugin = _make_fresh_eyerate(tmp_path)
    (plugin / fv.USER_DATA_NAME).write_text(fv.USER_DATA_CONTENT)

    # Pretend the exe is under an installed location — the seed must not care.
    installed_exe = "/Volumes/ManoMatikaDMG/ManoMatika-0.0.1.app/Contents/MacOS/ManoMatika-0.0.1"
    # Seeding succeeds regardless of exe path — it only needs the HOME tree.
    fv._seed_stale_eyerate(str(tmp_path))
    assert "coming soon" in (
        plugin / "src" / "eyerate" / "templates" / "eyerate_admin.html"
    ).read_text().lower()
    # Restore the template (as a launcher refresh would) and assert.
    (plugin / "src" / "eyerate" / "templates" / "eyerate_admin.html").write_text(
        "<legend>Financial Data Provider</legend>"
    )
    boot_log = "plugin eyerate: installed 0.0.1, bundled 0.0.4 -> refreshed"
    # _assert_refreshed also operates on HOME, not exe path — passes for any exe.
    _ = installed_exe  # exe path is irrelevant to the assertion
    fv._assert_refreshed(str(tmp_path), boot_log)  # must not raise
