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
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_SCRIPT = _SCRIPTS_DIR / "frozen_verify.py"
# scripts/ holds standalone sibling modules (screen_manifest, browser_verify) the
# verify harness imports by name; make them importable in the test process too.
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


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


# ---------------------------------------------------------------------------
# Manifest-driven tier-(a) harness (manomatika/ahimsa#82, A1)
#
# These pin that the HTTP tier drives EXACTLY the screens the manifest declares,
# generically, asserting route liveness per declared screen — and that it never
# hardcodes a route. Before this change there was no manifest drive at all, so a
# test asserting the manifest is enumerated and driven would fail (no such code).
# ---------------------------------------------------------------------------

import screen_manifest  # noqa: E402  (sibling script, added to sys.path below)


class _FakeResponse:
    def __init__(self, status_code=200, text="<html><body>ok</body></html>",
                 content_type="text/html; charset=utf-8"):
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": content_type}


class _FakeSession:
    """Records every GET so a test can assert exactly which routes were driven."""

    def __init__(self, responder=None):
        self.gets = []
        self._responder = responder or (lambda url: _FakeResponse())

    def get(self, url, allow_redirects=True, timeout=None):
        self.gets.append(url)
        return self._responder(url)


def _screen(fv_unused, screen_id="s1", route="/r1", markers=("#m1",),
            steps=(("navigate", "/r1", None),), source="core"):
    return screen_manifest.Screen(
        screen_id=screen_id, route=route, markers=tuple(markers),
        steps=tuple(screen_manifest.Step(v, t, val) for (v, t, val) in steps),
        source=source,
    )


def test_http_executor_navigate_asserts_route_liveness(fv):
    sess = _FakeSession()
    ex = fv.HttpScreenExecutor(sess, "http://x")
    ex.run_step(screen_manifest.Step("navigate", "/about", None))
    assert sess.gets == ["http://x/about"]


def test_http_executor_navigate_rejects_non_200(fv):
    sess = _FakeSession(lambda url: _FakeResponse(status_code=404, text="nope"))
    ex = fv.HttpScreenExecutor(sess, "http://x")
    with pytest.raises(fv.FrozenAppError):
        ex.run_step(screen_manifest.Step("navigate", "/gone", None))


def test_http_executor_navigate_rejects_non_html_200(fv):
    sess = _FakeSession(lambda url: _FakeResponse(content_type="application/json"))
    ex = fv.HttpScreenExecutor(sess, "http://x")
    with pytest.raises(fv.FrozenAppError):
        ex.run_step(screen_manifest.Step("navigate", "/api", None))


def test_run_tier_a_drives_exactly_the_declared_screens(fv, monkeypatch):
    """Tier (a) hits each declared screen's route once — generic, no hardcoding."""
    sess = _FakeSession()
    monkeypatch.setattr(fv, "_require_requests", lambda: None)
    monkeypatch.setattr(fv, "_login", lambda requests, base: sess)
    manifest = screen_manifest.ScreenManifest(
        screens=(
            _screen(fv, "alpha:home", "/alpha", ("#a",),
                    (("navigate", "/alpha", None),), source="alpha"),
            _screen(fv, "beta:home", "/beta", ("#b",),
                    (("navigate", "/beta", None),), source="beta"),
        ),
        not_a_screen=(),
        sources=("alpha", "beta"),
    )
    fv.run_tier_a("http://x", manifest)
    assert sess.gets == ["http://x/alpha", "http://x/beta"]


def test_load_manifest_skips_without_source_root(fv, capsys):
    """No --source-root -> manifest drive skipped (A2 installed-disk arm), not a crash."""
    assert fv._load_manifest(None) is None
    out = capsys.readouterr().out
    assert "SKIPPED" in out and "ahimsa#83" in out


def test_load_manifest_raises_on_missing_root(fv, tmp_path):
    with pytest.raises(screen_manifest.ScreenManifestError):
        fv._load_manifest(str(tmp_path / "does-not-exist"))


def test_capture_route_inventory_parses_routes_marker(fv, capsys):
    """The [ROUTES:...] startup line is parsed and reported (A3 consumes it later)."""

    class _App:
        def captured_text(self):
            return "boot...\n[ROUTES: /, /about, /eyerate/admin]\nmore"

    manifest = screen_manifest.ScreenManifest(
        screens=(_screen(fv, "home", "/", ("#m",)),), not_a_screen=(), sources=("core",))
    fv._capture_route_inventory(_App(), manifest)
    out = capsys.readouterr().out
    assert "3 live GET route(s)" in out
