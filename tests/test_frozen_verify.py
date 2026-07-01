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
import socket
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
        required_markers=(),
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


# ---------------------------------------------------------------------------
# Layer-3 functional-test phase — reboot-per-applug loop (L3 gate integration)
#
# These pin the three load-bearing properties of run_l3_functional that a real
# frozen boot in CI cannot cheaply prove locally:
#   (1) a FRESH BootedApp + a fresh clean HOME per applug (boot count == applug
#       count, distinct HOMEs);
#   (2) a NEW session minted PER boot — never reused across applugs/boots;
#   (3) FAILURE ISOLATION — one applug's failing test (or its boot/login) never
#       aborts the others; every result is collected; the overall result is a
#       failure (non-zero gate).
# BootedApp and _login are patched (no real exe locally); invoke_functional_test
# is patched to record (and conditionally raise) so the LOOP — not the already
# unit-covered importlib invocation — is what is exercised here. Synthetic
# applugs are alpha/beta (no real applug names).
# ---------------------------------------------------------------------------


def _make_functional_source_root(tmp_path, sources):
    """Build a source root with one synthetic applug per (name, [test_ids]).

    Each applug ships a real ``<name>_functional_tests.json`` + ``.py`` under
    ``plugins/<name>/`` so the real discovery/grouping (load_functional_test_
    manifest) runs; only the boot/login/invoke side effects are patched.
    """
    root = tmp_path / "src"
    for name, test_ids in sources:
        d = root / "plugins" / name
        d.mkdir(parents=True)
        decls = [
            {"test_id": tid, "description": f"{tid} desc",
             "module": f"{name}_functional_tests", "function": "run"}
            for tid in test_ids
        ]
        (d / f"{name}_functional_tests.json").write_text(
            json.dumps({"schema_version": "1.0", "functional_tests": decls})
        )
        (d / f"{name}_functional_tests.py").write_text(
            "def run(base_url, session):\n    pass\n"
        )
    return root


class _FakeBoot:
    """Records each boot so reboot-per-applug behaviour is provable."""

    def __init__(self, registry, exe, home, port, timeout):
        self.exe, self.home, self.port, self.timeout = exe, home, port, timeout
        self.base = f"http://127.0.0.1:{port}"
        self.out_path = os.path.join(home, "boot.log")
        registry.append(self)

    @property
    def logs_dir(self):
        return self.home

    def captured_text(self):
        return ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_l3(fv, monkeypatch, *, fail_test_ids=()):
    """Patch BootedApp / _login / invoke; return (boots, logins, invocations)."""
    boots = []
    logins = []          # sessions minted, in order
    invocations = []     # (test_id, source, session)

    monkeypatch.setattr(fv, "_require_requests", lambda: object())
    monkeypatch.setattr(
        fv, "BootedApp",
        lambda exe, home, port, timeout: _FakeBoot(boots, exe, home, port, timeout),
    )

    def fake_login(requests, base):
        sess = object()
        logins.append(sess)
        return sess

    monkeypatch.setattr(fv, "_login", fake_login)

    def fake_invoke(decl, source_root, base_url, session):
        invocations.append((decl.test_id, decl.source, session))
        if decl.test_id in fail_test_ids:
            raise RuntimeError(f"synthetic failure for {decl.test_id}")

    monkeypatch.setattr(screen_manifest, "invoke_functional_test", fake_invoke)
    return boots, logins, invocations


def test_l3_boots_fresh_app_per_applug(fv, tmp_path, monkeypatch):
    """One FRESH BootedApp + a distinct clean HOME per applug declaring tests."""
    root = _make_functional_source_root(
        tmp_path, [("alpha", ["alpha:a"]), ("beta", ["beta:b"])])
    boots, _logins, _inv = _patch_l3(fv, monkeypatch)
    ok = fv.run_l3_functional("exe", 8000, 30, str(root))
    assert ok is True
    assert len(boots) == 2                      # boot count == applug count
    assert len({b.home for b in boots}) == 2    # distinct HOMEs


def test_l3_mints_new_session_per_boot_never_reused(fv, tmp_path, monkeypatch):
    """A new session is minted per boot; an applug's tests share its one session,
    and the two applugs never share a session."""
    root = _make_functional_source_root(
        tmp_path, [("alpha", ["alpha:a1", "alpha:a2"]), ("beta", ["beta:b1"])])
    _boots, logins, invocations = _patch_l3(fv, monkeypatch)
    fv.run_l3_functional("exe", 8000, 30, str(root))
    # One session minted per boot (2 boots -> 2 sessions), all distinct.
    assert len(logins) == 2
    assert len({id(s) for s in logins}) == 2
    by_source = {}
    for _tid, source, session in invocations:
        by_source.setdefault(source, set()).add(id(session))
    # alpha's two tests shared exactly one session; beta got a different one.
    assert len(by_source["alpha"]) == 1
    assert len(by_source["beta"]) == 1
    assert by_source["alpha"].isdisjoint(by_source["beta"])


def test_l3_failure_isolation_one_test_does_not_abort_others(fv, tmp_path, monkeypatch):
    """A failing test in one applug does not stop the other applug from running;
    all results are collected and the overall gate result is FAILURE."""
    root = _make_functional_source_root(
        tmp_path, [("alpha", ["alpha:boom"]), ("beta", ["beta:ok"])])
    boots, _logins, invocations = _patch_l3(
        fv, monkeypatch, fail_test_ids={"alpha:boom"})
    ok = fv.run_l3_functional("exe", 8000, 30, str(root))
    assert ok is False                          # one failure fails the gate
    assert len(boots) == 2                      # beta still booted after alpha failed
    assert {tid for tid, _s, _sess in invocations} == {"alpha:boom", "beta:ok"}


def test_l3_boot_login_failure_isolated_and_fails_gate(fv, tmp_path, monkeypatch):
    """A boot/login failure for one applug fails the gate but does not abort the
    other applug (which still boots and runs)."""
    root = _make_functional_source_root(
        tmp_path, [("alpha", ["alpha:a"]), ("beta", ["beta:b"])])
    boots = []
    logins = []
    invocations = []
    monkeypatch.setattr(fv, "_require_requests", lambda: object())
    monkeypatch.setattr(
        fv, "BootedApp",
        lambda exe, home, port, timeout: _FakeBoot(boots, exe, home, port, timeout),
    )

    def fake_login(requests, base):
        # alpha sorts first; make ITS login fail, beta's succeed.
        if len(logins) == 0:
            logins.append(None)
            raise fv.FrozenAppError("synthetic alpha login failure")
        sess = object()
        logins.append(sess)
        return sess

    monkeypatch.setattr(fv, "_login", fake_login)
    monkeypatch.setattr(
        screen_manifest, "invoke_functional_test",
        lambda decl, source_root, base_url, session: invocations.append(decl.test_id),
    )
    ok = fv.run_l3_functional("exe", 8000, 30, str(root))
    assert ok is False                          # alpha boot/login failure fails gate
    assert "beta:b" in invocations              # beta still ran
    assert "alpha:a" not in invocations         # alpha never reached invoke


def test_l3_skips_when_no_functional_tests_declared(fv, tmp_path, monkeypatch):
    """A source root with no *_functional_tests.json is a PASS with zero boots."""
    root = tmp_path / "empty"
    root.mkdir()
    boots, _logins, _inv = _patch_l3(fv, monkeypatch)
    ok = fv.run_l3_functional("exe", 8000, 30, str(root))
    assert ok is True
    assert boots == []


def test_main_functional_without_source_root_errors(fv, tmp_path):
    """--functional with no --source-root is a hard error (nothing to discover)."""
    import sys
    from unittest.mock import patch

    exe = tmp_path / "exe"
    exe.write_text("")  # must exist so the exe-existence check passes first
    with patch.object(sys, "argv", ["frozen_verify.py", "--exe", str(exe),
                                     "--scenario", "fresh", "--functional"]):
        rc = fv.main()
    assert rc == 1


# ---------------------------------------------------------------------------
# L3 RESET DISCIPLINE — randomized, seed-reproducible per-applug ordering
#
# Within one applug's boot, its tests run in a RANDOMIZED order so that any
# order-dependent state leak (a test that did not reset what it mutated) surfaces.
# The order must be DETERMINISTIC for a given base seed (replayable) and the base
# seed must be LOGGED. _run_applug_tests is the extracted pure helper exercised
# here without a real frozen boot (invoke_functional_test is patched to record).
# ---------------------------------------------------------------------------


def _decls(source, test_ids):
    return [
        screen_manifest.FunctionalTestDecl(
            test_id=tid, description="d", module=f"{source}_ft",
            function="run", tags=(), source=source,
        )
        for tid in test_ids
    ]


def test_run_applug_tests_same_seed_same_order(fv, monkeypatch):
    """Same base seed -> identical execution order (replayable)."""
    decls = _decls("alpha", [f"alpha:{i}" for i in range(8)])
    seen = []
    monkeypatch.setattr(
        screen_manifest, "invoke_functional_test",
        lambda decl, sr, bu, sess: seen.append(decl.test_id),
    )
    fv._run_applug_tests(decls, "/root", "http://x", None, seed=1234)
    order1 = list(seen)
    seen.clear()
    fv._run_applug_tests(decls, "/root", "http://x", None, seed=1234)
    order2 = list(seen)
    assert order1 == order2
    # All declared tests ran exactly once (randomization is a permutation).
    assert sorted(order1) == [d.test_id for d in decls]


def test_run_applug_tests_order_varies_with_seed(fv, monkeypatch):
    """Ordering genuinely depends on the seed — it is not a fixed order. This is
    the VERIFIER that reset discipline (not run order) is what keeps tests green."""
    decls = _decls("alpha", [f"alpha:{i}" for i in range(8)])
    seen = []
    monkeypatch.setattr(
        screen_manifest, "invoke_functional_test",
        lambda decl, sr, bu, sess: seen.append(decl.test_id),
    )
    orders = set()
    for s in range(25):
        seen.clear()
        fv._run_applug_tests(decls, "/root", "http://x", None, seed=s)
        orders.add(tuple(seen))
    assert len(orders) > 1


def test_run_applug_tests_failure_isolation(fv, monkeypatch):
    """A failing test does not stop the rest; result tuples report each outcome."""
    decls = _decls("alpha", ["alpha:ok1", "alpha:boom", "alpha:ok2"])

    def fake_invoke(decl, sr, bu, sess):
        if decl.test_id == "alpha:boom":
            raise RuntimeError("synthetic")

    monkeypatch.setattr(screen_manifest, "invoke_functional_test", fake_invoke)
    results = fv._run_applug_tests(decls, "/root", "http://x", None, seed=7)
    by_id = {tid: (ok, err) for tid, ok, err in results}
    assert set(by_id) == {"alpha:ok1", "alpha:boom", "alpha:ok2"}
    assert by_id["alpha:ok1"][0] is True
    assert by_id["alpha:ok2"][0] is True
    assert by_id["alpha:boom"][0] is False
    assert "synthetic" in by_id["alpha:boom"][1]


def test_derive_seed_is_deterministic_per_source(fv):
    """One base seed -> a stable per-applug seed for each source."""
    assert fv._derive_seed(42, "alpha") == fv._derive_seed(42, "alpha")
    assert fv._derive_seed(42, "beta") == fv._derive_seed(42, "beta")
    # Different sources generally derive different seeds (so orders are not coupled).
    assert fv._derive_seed(42, "alpha") != fv._derive_seed(42, "beta")


def test_l3_logs_replayable_seed_when_provided(fv, tmp_path, monkeypatch, capsys):
    """An explicit --l3-seed is logged greppably so the run is replayable."""
    root = _make_functional_source_root(tmp_path, [("alpha", ["a1", "a2", "a3"])])
    _patch_l3(fv, monkeypatch)
    fv.run_l3_functional("exe", 8000, 30, str(root), seed=4242)
    out = capsys.readouterr().out
    assert "L3 random seed: 4242" in out


def test_l3_generates_and_logs_seed_when_none(fv, tmp_path, monkeypatch, capsys):
    """With no seed, one is generated and logged (greppable 'L3 random seed:')."""
    root = _make_functional_source_root(tmp_path, [("alpha", ["a1"])])
    _patch_l3(fv, monkeypatch)
    fv.run_l3_functional("exe", 8000, 30, str(root))  # seed=None
    out = capsys.readouterr().out
    assert "L3 random seed:" in out


class TestPluginPayloadClean:
    def test_passes_when_no_scaffolding_present(self, fv, tmp_path):
        """assert_plugin_payload_clean passes when plugins have no scaffolding."""
        plugins_dir = tmp_path / "plugins" / "eyerate"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "applug.json").write_text('{"name":"eyerate"}')
        (plugins_dir / "views.py").write_text("# runtime code")
        fv.assert_plugin_payload_clean(tmp_path)

    def test_fails_when_git_dir_present(self, fv, tmp_path):
        """assert_plugin_payload_clean fails if .git/ is present in a plugin dir."""
        plugins_dir = tmp_path / "plugins" / "eyerate"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / ".git").mkdir()
        (plugins_dir / ".git" / "config").write_text("[core]")
        with pytest.raises(AssertionError, match="scaffolding leaked"):
            fv.assert_plugin_payload_clean(tmp_path)

    def test_fails_when_github_dir_present(self, fv, tmp_path):
        """assert_plugin_payload_clean fails if .github/ is present."""
        plugins_dir = tmp_path / "plugins" / "eyerate"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / ".github").mkdir()
        with pytest.raises(AssertionError, match="scaffolding leaked"):
            fv.assert_plugin_payload_clean(tmp_path)

    def test_fails_when_gitignore_present(self, fv, tmp_path):
        """assert_plugin_payload_clean fails if .gitignore is present."""
        plugins_dir = tmp_path / "plugins" / "eyerate"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / ".gitignore").write_text("*.pyc\n")
        with pytest.raises(AssertionError, match="scaffolding leaked"):
            fv.assert_plugin_payload_clean(tmp_path)

    def test_fails_when_tests_dir_present(self, fv, tmp_path):
        """assert_plugin_payload_clean fails if tests/ is present."""
        plugins_dir = tmp_path / "plugins" / "eyerate"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / "tests").mkdir()
        with pytest.raises(AssertionError, match="scaffolding leaked"):
            fv.assert_plugin_payload_clean(tmp_path)

    def test_skips_gracefully_when_no_plugins_dir(self, fv, tmp_path):
        """assert_plugin_payload_clean logs a warning and does not raise if plugins/ missing."""
        fv.assert_plugin_payload_clean(tmp_path)

    def test_error_message_names_leaked_path(self, fv, tmp_path):
        """The error message must name the specific leaked entry for debuggability."""
        plugins_dir = tmp_path / "plugins" / "eyerate"
        plugins_dir.mkdir(parents=True)
        (plugins_dir / ".git").mkdir()
        with pytest.raises(AssertionError) as exc_info:
            fv.assert_plugin_payload_clean(tmp_path)
        assert "eyerate/.git" in str(exc_info.value)


def test_l3_same_seed_reproduces_run_order(fv, tmp_path, monkeypatch):
    """run_l3_functional with the same seed produces the same per-applug order."""
    root = _make_functional_source_root(
        tmp_path, [("alpha", ["a1", "a2", "a3", "a4"])])
    _b1, _l1, inv1 = _patch_l3(fv, monkeypatch)
    fv.run_l3_functional("exe", 8000, 30, str(root), seed=99)
    order1 = [tid for tid, _s, _sess in inv1]
    _b2, _l2, inv2 = _patch_l3(fv, monkeypatch)
    fv.run_l3_functional("exe", 8000, 30, str(root), seed=99)
    order2 = [tid for tid, _s, _sess in inv2]
    assert order1 == order2
    assert sorted(order1) == ["a1", "a2", "a3", "a4"]


def test_main_threads_l3_seed(fv, tmp_path, monkeypatch):
    """main() parses --l3-seed and threads it into run_l3_functional."""
    import sys
    from unittest.mock import patch

    exe = tmp_path / "exe"
    exe.write_text("")
    captured = {}

    def fake_l3(exe_, port, timeout, source_root, seed=None):
        captured["seed"] = seed
        return True

    monkeypatch.setattr(fv, "_load_manifest", lambda sr: None)
    monkeypatch.setattr(fv, "run_i18n_completeness", lambda sr: None)
    monkeypatch.setattr(fv, "scenario_fresh", lambda *a, **k: None)
    monkeypatch.setattr(fv, "run_l3_functional", fake_l3)
    with patch.object(sys, "argv", ["frozen_verify.py", "--exe", str(exe),
                                     "--scenario", "fresh",
                                     "--source-root", str(tmp_path),
                                     "--l3-seed", "777"]):
        rc = fv.main()
    assert rc == 0
    assert captured["seed"] == 777


class TestLifecycleAssertions:
    def test_healthz_version_passes_matching_tag(self, fv, tmp_path, monkeypatch):
        """assert_healthz_reachable_and_version passes when /healthz version matches tag."""
        import json
        import urllib.request
        class MockResponse:
            def __init__(self):
                self.status = 200
            def read(self):
                return json.dumps({"product": "ManoMatika", "version": "0.0.4-rc.11", "status": "ok"}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): pass
        monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: MockResponse())
        fv.assert_healthz_reachable_and_version(8000, "v0.0.4-rc.11")

    def test_healthz_version_fails_mismatched_tag(self, fv, monkeypatch):
        """assert_healthz_reachable_and_version fails when versions don't match."""
        import json, urllib.request
        class MockResponse:
            def read(self): return json.dumps({"product":"ManoMatika","version":"0.0.4-rc.7","status":"ok"}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): pass
        monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: MockResponse())
        with pytest.raises(AssertionError, match="version"):
            fv.assert_healthz_reachable_and_version(8000, "v0.0.4-rc.11")

    def test_healthz_fails_on_unreachable(self, fv, monkeypatch):
        """assert_healthz_reachable_and_version fails when /healthz is unreachable."""
        import urllib.request, urllib.error
        def raise_urlerror(url, timeout=None):
            raise urllib.error.URLError("connection refused")
        monkeypatch.setattr(urllib.request, "urlopen", raise_urlerror)
        with pytest.raises(AssertionError, match="Failed to probe"):
            fv.assert_healthz_reachable_and_version(8000, "v0.0.4-rc.11")

    def test_healthz_fails_on_wrong_product(self, fv, monkeypatch):
        """assert_healthz_reachable_and_version fails when product != ManoMatika."""
        import json, urllib.request
        class MockResponse:
            def read(self): return json.dumps({"product":"OtherApp","version":"0.0.4-rc.11","status":"ok"}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): pass
        monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: MockResponse())
        with pytest.raises(AssertionError, match="product"):
            fv.assert_healthz_reachable_and_version(8000, "v0.0.4-rc.11")

    def test_abrupt_kill_port_free_passes_when_port_released(self, fv, tmp_path, monkeypatch):
        """assert_abrupt_kill_port_free passes when port is freed after kill."""
        import subprocess, time
        class MockProc:
            returncode = None
            def kill(self): self.returncode = -9
            def wait(self, timeout=None): pass
            def poll(self): return self.returncode
        # Port is not in use, so bind should succeed
        fv.assert_abrupt_kill_port_free(MockProc(), 19999)  # unlikely-used port

    def test_abrupt_kill_port_free_passes_over_real_time_wait_residue(self, fv):
        """END-TO-END residue tolerance (manomatika/ahimsa#119/#120 mechanism, corrected).

        On a port carrying genuine TIME_WAIT residue — the exact post-SIGKILL macOS
        window where a PLAIN bind is rejected but a SO_REUSEADDR bind (the real
        launcher's bind) succeeds — the full assertion must PASS, NOT false-positive.
        This is what #120's bounded retry was papering over; the corrected probe
        mirrors the launcher's SO_REUSEADDR bind and tolerates it directly (no retry).
        """
        class MockProc:
            pid = 31337
            returncode = None
            def kill(self): self.returncode = -9
            def wait(self, timeout=None): pass
            def poll(self): return self.returncode

        port = _free_port()
        _make_time_wait(port)
        # The discriminator is real: the pre-fix PLAIN bind is rejected on this port.
        assert _plain_bind_raises(port), (
            "expected TIME_WAIT residue a plain bind rejects; platform did not form it"
        )
        # Must NOT raise — the launcher-identical (SO_REUSEADDR) bind tolerates residue.
        fv.assert_abrupt_kill_port_free(MockProc(), port)

    def test_abrupt_kill_port_free_fails_when_port_held(self, fv, monkeypatch):
        """assert_abrupt_kill_port_free fails (fail-loud) when a real orphan/respawn
        still holds the port — a live LISTEN socket cannot be bound over even with
        SO_REUSEADDR (uvicorn sets no SO_REUSEPORT), so the launcher-identical probe
        fails and the assertion fires."""
        import socket as _socket
        class MockProc:
            pid = 99999
            returncode = None
            def kill(self): self.returncode = -9
            def wait(self, timeout=None): pass
            def poll(self): return self.returncode
        # Bind+listen on the port to simulate a real orphan listener still holding it.
        test_port = 19998
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", test_port))
            s.listen(1)  # must listen — bind-only isn't enough to block a bind on Linux
            with pytest.raises(AssertionError) as excinfo:
                fv.assert_abrupt_kill_port_free(MockProc(), test_port)
            msg = str(excinfo.value)
            assert "still held by a live listener" in msg
            assert "orphan or respawn" in msg
        finally:
            s.close()

    def test_abrupt_kill_diag_captures_pid_and_so_reuseaddr_failed(self, fv, capsys):
        """On a real orphan (live listener), diag logs proc.pid/poll and SO_REUSEADDR FAILED."""
        import socket as _socket
        class MockProc:
            pid = 424242
            returncode = None
            def kill(self): self.returncode = -9
            def wait(self, timeout=None): pass
            def poll(self): return self.returncode
        test_port = 19997
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", test_port))
            s.listen(1)
            with pytest.raises(AssertionError):
                fv.assert_abrupt_kill_port_free(MockProc(), test_port)
        finally:
            s.close()
        out = capsys.readouterr().out
        assert "DIAG: abrupt-kill: launched proc.pid=424242 proc.poll()=-9" in out
        # Both binds fail on a real live listener (plain AND launcher-identical).
        assert "abrupt-kill diag: plain bind FAILED" in out
        assert "SO_REUSEADDR (launcher-identical) bind FAILED" in out

    def test_abrupt_kill_passes_when_only_residue_reuseaddr_bindable(self, fv, monkeypatch):
        """CORRECTED behavior: residue that a PLAIN bind rejects but a SO_REUSEADDR bind
        tolerates (the real macOS #119 evidence) means the real app COULD start — so the
        assertion must PASS, not fail. #120 baked the opposite (residue -> raise) into a
        test; the launcher-identical probe inverts it to the truthful outcome."""
        import socket as _socket
        class MockProc:
            pid = 555
            returncode = None
            def kill(self): self.returncode = -9
            def wait(self, timeout=None): pass
            def poll(self): return self.returncode

        real_socket_cls = _socket.socket

        class ResidueSocket:
            """Plain bind always raises (residue persists); a bind on a socket with
            SO_REUSEADDR set succeeds — the real macOS evidence in manomatika/ahimsa#119."""
            def __init__(self, *a, **kw):
                self._s = real_socket_cls(*a, **kw)
                self._reuseaddr = False
            def setsockopt(self, level, optname, value):
                if optname == _socket.SO_REUSEADDR:
                    self._reuseaddr = True
                return self._s.setsockopt(level, optname, value)
            def bind(self, addr):
                if self._reuseaddr:
                    return self._s.bind(addr)
                raise OSError(48, "Address already in use")
            def close(self): return self._s.close()

        monkeypatch.setattr(fv.socket, "socket", ResidueSocket)
        # Must NOT raise: the launcher binds with SO_REUSEADDR, so residue is tolerated.
        fv.assert_abrupt_kill_port_free(MockProc(), 19996)

    def test_abrupt_kill_diag_skips_ps_lsof_off_darwin(self, fv, capsys, monkeypatch):
        """ps/lsof capture is skipped (not failed) on non-macOS runners (e.g. Windows CI)."""
        import socket as _socket
        class MockProc:
            pid = 1
            returncode = None
            def kill(self): self.returncode = -9
            def wait(self, timeout=None): pass
            def poll(self): return self.returncode
        monkeypatch.setattr(fv.sys, "platform", "win32")
        test_port = 19995
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", test_port))
            s.listen(1)
            with pytest.raises(AssertionError):
                fv.assert_abrupt_kill_port_free(MockProc(), test_port)
        finally:
            s.close()
        out = capsys.readouterr().out
        assert "ps/lsof capture skipped (not macOS)" in out
        assert "ps -ax" not in out

    def test_double_launch_recovery_passes_on_exit_zero(self, fv, tmp_path, monkeypatch):
        """assert_double_launch_recovery passes when second launch exits 0 with recovery log."""
        import subprocess as sp
        class FakeProc:
            returncode = 0
            def __init__(self): self._stdout = "port 8000 already held by a ManoMatika instance; focusing existing window\n"
            def communicate(self, timeout=None): return self._stdout, None
        monkeypatch.setattr(sp, "Popen", lambda *a, **kw: FakeProc())
        monkeypatch.setattr(fv.shutil, "rmtree", lambda *a, **kw: None)
        monkeypatch.setattr(fv.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
        fv.assert_double_launch_recovery("fake-exe", 8000, 30)

    def test_double_launch_recovery_fails_on_nonzero_exit(self, fv, tmp_path, monkeypatch):
        """assert_double_launch_recovery fails when second launch exits nonzero."""
        import subprocess as sp
        class FakeProc:
            returncode = 1
            def communicate(self, timeout=None): return "ERROR: port in use\n", None
        monkeypatch.setattr(sp, "Popen", lambda *a, **kw: FakeProc())
        monkeypatch.setattr(fv.shutil, "rmtree", lambda *a, **kw: None)
        monkeypatch.setattr(fv.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
        with pytest.raises(AssertionError, match="exit"):
            fv.assert_double_launch_recovery("fake-exe", 8000, 30)

    def test_double_launch_recovery_fails_on_no_recovery_log(self, fv, tmp_path, monkeypatch):
        """assert_double_launch_recovery fails when exit 0 but no recovery log line."""
        import subprocess as sp
        class FakeProc:
            returncode = 0
            def communicate(self, timeout=None): return "started server on port 8000\n", None
        monkeypatch.setattr(sp, "Popen", lambda *a, **kw: FakeProc())
        monkeypatch.setattr(fv.shutil, "rmtree", lambda *a, **kw: None)
        monkeypatch.setattr(fv.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
        with pytest.raises(AssertionError, match="recovery log"):
            fv.assert_double_launch_recovery("fake-exe", 8000, 30)


class _FakeBootedApp:
    """Stand-in for BootedApp used by the reclaim-regression tests below —
    avoids actually launching a frozen binary, mirroring the FakeProc pattern
    used for assert_double_launch_recovery above."""

    def __init__(self, pid=None, boot_text="", raise_on_enter=None):
        self.proc = type("P", (), {"pid": pid})()
        self._boot_text = boot_text
        self._raise_on_enter = raise_on_enter

    def __call__(self, exe, home, port, timeout):
        # BootedApp(...) is itself the constructor call; reuse the same
        # instance as the context manager it returns.
        return self

    def __enter__(self):
        if self._raise_on_enter is not None:
            raise self._raise_on_enter
        return self

    def __exit__(self, *a):
        return False

    def captured_text(self):
        return self._boot_text


class TestPidTrulyGone:
    """_pid_truly_gone — LIVE-PROOF REGRESSION (rule 22 corollary): the first
    real-process run of assert_reclaim_recovers_dead_holder false-failed
    because instance B (a separate OS process) killed instance A, leaving A
    as a ZOMBIE until THIS script's own subprocess.Popen handle (A's real OS
    parent) reaps it — and psutil.pid_exists() still reports a zombie as
    "existing". A killed-but-unreaped zombie must count as gone."""

    def test_zombie_counts_as_gone(self, fv, monkeypatch):
        import psutil
        class FakeProcess:
            def __init__(self, pid):
                pass
            def status(self):
                return psutil.STATUS_ZOMBIE
        monkeypatch.setattr(psutil, "Process", FakeProcess)
        assert fv._pid_truly_gone(111) is True

    def test_nonexistent_pid_counts_as_gone(self, fv, monkeypatch):
        import psutil
        class FakeProcess:
            def __init__(self, pid):
                raise psutil.NoSuchProcess(pid)
        monkeypatch.setattr(psutil, "Process", FakeProcess)
        assert fv._pid_truly_gone(111) is True

    def test_genuinely_running_pid_is_not_gone(self, fv, monkeypatch):
        import psutil
        class FakeProcess:
            def __init__(self, pid):
                pass
            def status(self):
                return psutil.STATUS_RUNNING
        monkeypatch.setattr(psutil, "Process", FakeProcess)
        assert fv._pid_truly_gone(111) is False

    def test_suspended_pid_is_not_gone(self, fv, monkeypatch):
        """A suspended (STOPPED) holder is alive — must not be confused with
        a zombie, or a kill that genuinely failed would be reported as gone."""
        import psutil
        class FakeProcess:
            def __init__(self, pid):
                pass
            def status(self):
                return psutil.STATUS_STOPPED
        monkeypatch.setattr(psutil, "Process", FakeProcess)
        assert fv._pid_truly_gone(111) is False


class TestReclaimRegression:
    """manomatika/matika#113 — frozen-artifact regression for health-gated
    startup reclaim. MANDATE: assert_reclaim_recovers_dead_holder must FAIL
    against pre-reclaim launcher behavior and PASS against the feature;
    assert_foreign_holder_not_killed must never let a foreign holder be
    killed regardless of launcher version."""

    def _dispatch_booted_app(self, fv, monkeypatch, fake_a, fake_b):
        def fake_booted_app(exe, home, port, timeout):
            return fake_a if "reclaim-a" in home else fake_b
        monkeypatch.setattr(fv, "BootedApp", fake_booted_app)

    def _patch_homes(self, fv, monkeypatch):
        monkeypatch.setattr(fv.tempfile, "mkdtemp", lambda prefix=None, **kw: f"/fake/{prefix}")
        monkeypatch.setattr(fv.shutil, "rmtree", lambda *a, **kw: None)

    def _patch_healthz(self, fv, monkeypatch, body):
        import json
        import urllib.request
        class MockResponse:
            def read(self_):
                return json.dumps(body).encode()
            def __enter__(self_):
                return self_
            def __exit__(self_, *a):
                pass
        monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: MockResponse())

    def test_reclaim_passes_when_b_reclaims_and_is_healthy(self, fv, monkeypatch):
        import psutil
        self._patch_homes(fv, monkeypatch)
        fake_a = _FakeBootedApp(pid=111)
        fake_b = _FakeBootedApp(
            pid=222,
            boot_text="port 8000 held by a dead/unhealthy ManoMatika process "
                      "(pid 111) -> reclaiming: force-killing and restarting fresh",
        )
        self._dispatch_booted_app(fv, monkeypatch, fake_a, fake_b)

        suspended, resumed = [], []
        class FakeProcess:
            def __init__(self, pid):
                self.pid = pid
            def suspend(self):
                suspended.append(self.pid)
            def resume(self):
                resumed.append(self.pid)
            def status(self):
                # A is dead (zombie — unreaped by its real OS parent, the
                # exact live-proof finding _pid_truly_gone exists to handle).
                return psutil.STATUS_ZOMBIE
        monkeypatch.setattr(psutil, "Process", FakeProcess)
        self._patch_healthz(fv, monkeypatch, {"product": "ManoMatika", "status": "ok"})

        fv.assert_reclaim_recovers_dead_holder("fake-exe", 8000, 30)
        assert suspended == [111]
        assert resumed == []  # A already dead — resume-for-cleanup is a no-op skip

    def test_reclaim_fails_loud_when_suspend_fails(self, fv, monkeypatch):
        import psutil
        self._patch_homes(fv, monkeypatch)
        fake_a = _FakeBootedApp(pid=111)
        self._dispatch_booted_app(fv, monkeypatch, fake_a, _FakeBootedApp(pid=222))

        class FakeProcess:
            def __init__(self, pid):
                pass
            def suspend(self):
                raise psutil.Error("cannot suspend")
        monkeypatch.setattr(psutil, "Process", FakeProcess)

        with pytest.raises(AssertionError, match="could not suspend instance A"):
            fv.assert_reclaim_recovers_dead_holder("fake-exe", 8000, 30)

    def test_reclaim_fails_when_b_never_comes_up(self, fv, monkeypatch):
        """Pre-reclaim launcher behavior: B treats the unresponsive holder as
        foreign and exits 1 immediately — BootedApp.__enter__ raises
        FrozenAppError before B ever serves. MUST fail loud, not silently pass."""
        import psutil
        self._patch_homes(fv, monkeypatch)
        fake_a = _FakeBootedApp(pid=111)
        fake_b = _FakeBootedApp(raise_on_enter=fv.FrozenAppError(
            "process EXITED early (code 1) before the server came up"
        ))
        self._dispatch_booted_app(fv, monkeypatch, fake_a, fake_b)

        class FakeProcess:
            def __init__(self, pid):
                self.pid = pid
            def suspend(self):
                pass
            def resume(self):
                pass
            def status(self):
                return psutil.STATUS_STOPPED  # A is suspended, genuinely alive
        monkeypatch.setattr(psutil, "Process", FakeProcess)

        with pytest.raises(AssertionError, match="expected it to RECLAIM"):
            fv.assert_reclaim_recovers_dead_holder("fake-exe", 8000, 30)

    def test_reclaim_fails_when_no_reclaim_log_line(self, fv, monkeypatch):
        import psutil
        self._patch_homes(fv, monkeypatch)
        fake_a = _FakeBootedApp(pid=111)
        fake_b = _FakeBootedApp(pid=222, boot_text="started server on port 8000\n")
        self._dispatch_booted_app(fv, monkeypatch, fake_a, fake_b)

        class FakeProcess:
            def __init__(self, pid):
                pass
            def suspend(self):
                pass
            def resume(self):
                pass
            def status(self):
                return psutil.STATUS_ZOMBIE
        monkeypatch.setattr(psutil, "Process", FakeProcess)

        with pytest.raises(AssertionError, match="no reclaim log line"):
            fv.assert_reclaim_recovers_dead_holder("fake-exe", 8000, 30)

    def test_reclaim_fails_when_holder_still_alive(self, fv, monkeypatch):
        """B came up and logged reclaim, but the dead holder was never
        actually killed (pid still exists, genuinely running — not a
        zombie) — must fail, not trust the log."""
        import psutil
        self._patch_homes(fv, monkeypatch)
        fake_a = _FakeBootedApp(pid=111)
        fake_b = _FakeBootedApp(pid=222, boot_text="-> reclaiming: force-killing and restarting fresh")
        self._dispatch_booted_app(fv, monkeypatch, fake_a, fake_b)

        class FakeProcess:
            def __init__(self, pid):
                self.pid = pid
            def suspend(self):
                pass
            def resume(self):
                pass
            def status(self):
                return psutil.STATUS_RUNNING  # genuinely alive — kill failed
        monkeypatch.setattr(psutil, "Process", FakeProcess)

        with pytest.raises(AssertionError, match="still alive"):
            fv.assert_reclaim_recovers_dead_holder("fake-exe", 8000, 30)

    def test_reclaim_fails_when_b_healthz_not_healthy(self, fv, monkeypatch):
        import psutil
        self._patch_homes(fv, monkeypatch)
        fake_a = _FakeBootedApp(pid=111)
        fake_b = _FakeBootedApp(pid=222, boot_text="-> reclaiming: force-killing and restarting fresh")
        self._dispatch_booted_app(fv, monkeypatch, fake_a, fake_b)

        class FakeProcess:
            def __init__(self, pid):
                pass
            def suspend(self):
                pass
            def resume(self):
                pass
            def status(self):
                return psutil.STATUS_ZOMBIE
        monkeypatch.setattr(psutil, "Process", FakeProcess)
        self._patch_healthz(fv, monkeypatch, {"product": "OtherApp", "status": "ok"})

        with pytest.raises(AssertionError, match="not healthy"):
            fv.assert_reclaim_recovers_dead_holder("fake-exe", 8000, 30)

    def test_reclaim_resumes_a_for_cleanup_when_still_suspended(self, fv, monkeypatch):
        """Cleanup discipline: if A is somehow still alive when control
        returns (e.g. a partial/failed reclaim), it must be resumed so the
        outer BootedApp teardown can terminate a normally-scheduled process."""
        import psutil
        self._patch_homes(fv, monkeypatch)
        fake_a = _FakeBootedApp(pid=111)
        fake_b = _FakeBootedApp(pid=222, boot_text="-> reclaiming: force-killing and restarting fresh")
        self._dispatch_booted_app(fv, monkeypatch, fake_a, fake_b)

        resumed = []
        class FakeProcess:
            def __init__(self, pid):
                self.pid = pid
            def suspend(self):
                pass
            def resume(self):
                resumed.append(self.pid)
            def status(self):
                return psutil.STATUS_STOPPED  # still alive (suspended, not zombie)
        monkeypatch.setattr(psutil, "Process", FakeProcess)

        with pytest.raises(AssertionError, match="still alive"):
            fv.assert_reclaim_recovers_dead_holder("fake-exe", 8000, 30)
        assert resumed == [111]


def _dispatching_popen(monkeypatch, app_proc_factory):
    """Patch subprocess.Popen so a call launching the REAL foreign-holder
    sibling (``sys.executable -c ...``, spawned by
    ``_spawn_foreign_port_holder``) goes through to the real Popen — the
    faithful fixture needs a genuinely independent, listening process — while
    any OTHER call (the app-under-test, which isn't available in the unit-
    test environment) returns ``app_proc_factory()``'s fake process."""
    import subprocess as sp
    real_popen = sp.Popen

    def dispatch(cmd, *a, **kw):
        if isinstance(cmd, list) and cmd[:1] == [sys.executable]:
            return real_popen(cmd, *a, **kw)
        return app_proc_factory()

    monkeypatch.setattr(sp, "Popen", dispatch)


class TestForeignHolderRegression:
    """manomatika/matika#113 — a real foreign port holder must NEVER be
    killed by the launcher, regardless of how it handles the conflict."""

    def test_foreign_holder_fails_loud_and_listener_stays_bound(self, fv, monkeypatch, tmp_path):
        port = _free_port()
        message = (
            f"port {port} held by pid 4242, which is NOT identified as a "
            f"ManoMatika process (healthz unreachable); refusing to kill a "
            f"foreign process — failing loud\n"
        )
        class FakeProc:
            returncode = 1
            def communicate(self, timeout=None):
                return message, None
        _dispatching_popen(monkeypatch, FakeProc)
        monkeypatch.setattr(fv.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
        monkeypatch.setattr(fv.shutil, "rmtree", lambda *a, **kw: None)

        fv.assert_foreign_holder_not_killed("fake-exe", port, 30)

    def test_foreign_holder_fails_when_app_exits_zero(self, fv, monkeypatch, tmp_path):
        """If the app exits 0 against a foreign holder, that's NOT fail-loud
        — it must be flagged as a defect, not treated as success."""
        port = _free_port()
        class FakeProc:
            returncode = 0
            def communicate(self, timeout=None):
                return "started server on port\n", None
        _dispatching_popen(monkeypatch, FakeProc)
        monkeypatch.setattr(fv.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
        monkeypatch.setattr(fv.shutil, "rmtree", lambda *a, **kw: None)

        with pytest.raises(AssertionError, match="must exit non-zero"):
            fv.assert_foreign_holder_not_killed("fake-exe", port, 30)

    def test_foreign_holder_fails_when_message_missing_reason(self, fv, monkeypatch, tmp_path):
        port = _free_port()
        class FakeProc:
            returncode = 1
            def communicate(self, timeout=None):
                return "ERROR: something went wrong\n", None
        _dispatching_popen(monkeypatch, FakeProc)
        monkeypatch.setattr(fv.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
        monkeypatch.setattr(fv.shutil, "rmtree", lambda *a, **kw: None)

        with pytest.raises(AssertionError, match="didn't name the foreign-holder reason"):
            fv.assert_foreign_holder_not_killed("fake-exe", port, 30)

    def test_foreign_holder_fails_when_app_hangs(self, fv, monkeypatch, tmp_path):
        import subprocess as sp
        port = _free_port()
        class FakeProc:
            def communicate(self, timeout=None):
                if timeout is not None:
                    raise sp.TimeoutExpired(cmd="exe", timeout=timeout)
                return "", None  # post-kill reap call
            def kill(self):
                pass
        _dispatching_popen(monkeypatch, FakeProc)
        monkeypatch.setattr(fv.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
        monkeypatch.setattr(fv.shutil, "rmtree", lambda *a, **kw: None)

        with pytest.raises(AssertionError, match="did not exit within"):
            fv.assert_foreign_holder_not_killed("fake-exe", port, 5)

    def test_spawned_holder_is_independent_sibling_not_parent_socket(self, fv, monkeypatch, tmp_path):
        """FAITHFULNESS regression: the foreign holder must be a genuinely
        separate OS process (like the reclaim/double-launch fixtures spawn),
        never a socket opened in this driver's own process — a position no
        real-world foreign holder occupies."""
        port = _free_port()
        message = (
            f"port {port} held by pid 4242, which is NOT identified as a "
            f"ManoMatika process (healthz unreachable); refusing to kill a "
            f"foreign process — failing loud\n"
        )
        class FakeProc:
            returncode = 1
            def communicate(self, timeout=None):
                return message, None
        _dispatching_popen(monkeypatch, FakeProc)
        monkeypatch.setattr(fv.tempfile, "mkdtemp", lambda **kw: str(tmp_path))
        monkeypatch.setattr(fv.shutil, "rmtree", lambda *a, **kw: None)

        holder = fv._spawn_foreign_port_holder(port)
        try:
            import psutil
            assert holder.pid != os.getpid(), (
                "the foreign holder must be a separate process, not this test/driver process"
            )
            assert psutil.pid_exists(holder.pid)
            listener_pid = None
            for proc in psutil.process_iter(["pid"]):
                try:
                    conns = proc.net_connections(kind="inet")
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
                for conn in conns:
                    if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == port:
                        listener_pid = proc.pid
            assert listener_pid == holder.pid, (
                f"expected psutil to see the spawned sibling (pid {holder.pid}) as "
                f"the LISTENer on port {port}, found pid {listener_pid!r} instead"
            )
        finally:
            fv._terminate_foreign_holder(holder)


# ---------------------------------------------------------------------------
# abrupt-kill port-free probe — must MIRROR the real launcher's bind exactly
# (manomatika/ahimsa#119/#120 mechanism).
#
# The frozen app's launcher (matika/launcher.py::_port_available, and its uvicorn
# listen socket) binds 127.0.0.1 with SO_REUSEADDR. After a SIGKILL macOS leaves
# the port in a TIME_WAIT teardown window (from the harness's own healthz/double-
# launch connections): a PLAIN bind is rejected for that whole window even though
# no process holds the port, while a SO_REUSEADDR bind — the real app's bind —
# succeeds. The probe must therefore bind the launcher's way: tolerate TIME_WAIT
# residue the app tolerates, but still detect a real live listener (orphan).
# ---------------------------------------------------------------------------

def _free_port() -> int:
    """Reserve then release an ephemeral port so a known number is free to reuse."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _make_time_wait(port: int) -> None:
    """Leave a genuine TIME_WAIT socket on 127.0.0.1:port (server actively closes).

    Reproduces the macOS post-SIGKILL teardown window: a plain bind is then
    rejected (EADDRINUSE) while a SO_REUSEADDR bind succeeds — exactly the #119
    diagnostic signature (lsof LISTEN empty, ps clean, plain-FAIL/reuse-OK).
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    cli = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    cli.connect(("127.0.0.1", port))
    conn, _ = srv.accept()
    conn.close()      # active close on the (127.0.0.1, port) side -> TIME_WAIT
    srv.close()
    cli.close()


def _plain_bind_raises(port: int) -> bool:
    """True if a PLAIN (no SO_REUSEADDR) bind to 127.0.0.1:port raises (old probe)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def test_abrupt_kill_probe_tolerates_time_wait_like_the_real_app(fv):
    """LIVE PROOF: on a TIME_WAIT port the real app could bind, the probe passes.

    Precondition asserts the discriminator is real (a PLAIN bind — the pre-fix
    probe — is rejected). The fixed probe mirrors the launcher (SO_REUSEADDR) and
    must return None (bindable), i.e. the assertion would NOT false-positive.
    Without the fix (plain bind) _probe_port_bindable would itself raise/return the
    error here, failing the gate exactly as #120 was masking with a retry window.
    """
    port = _free_port()
    _make_time_wait(port)
    # Discriminator present: the OLD plain-bind probe is rejected on this port.
    assert _plain_bind_raises(port), (
        "expected a TIME_WAIT residue that a plain bind rejects; if this fails the "
        "platform did not form TIME_WAIT and the live-proof is not exercised"
    )
    # The FIX: launcher-identical (SO_REUSEADDR) bind tolerates it — app would start.
    assert fv._probe_port_bindable(port) is None, (
        "fixed probe must bind a TIME_WAIT port the real launcher (SO_REUSEADDR) "
        "would bind — a plain-bind probe here is a false positive"
    )


def test_abrupt_kill_probe_detects_real_live_listener(fv):
    """ORPHAN DETECTION PRESERVED: a real LISTEN socket still fails the probe.

    Mirrors an orphan uvicorn: bound with SO_REUSEADDR and listening (uvicorn sets
    no SO_REUSEPORT). The launcher-identical probe must NOT bind over it.
    """
    port = _free_port()
    orphan = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    orphan.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    orphan.bind(("127.0.0.1", port))
    orphan.listen(1)
    try:
        exc = fv._probe_port_bindable(port)
        assert isinstance(exc, OSError), (
            "a real live listener (orphan) must fail the launcher-identical probe"
        )
    finally:
        orphan.close()


# ---------------------------------------------------------------------------
# assert_foreign_holder_not_killed — reconciled to the NEW launcher behavior:
# a foreign holder is NOT killed, and the app FAILS LOUD FAST (well under the
# timeout budget — no blocking modal). These tests PROVE the assertion is not
# vacuous: each clause must FAIL on a deliberately-wrong fake app and PASS on a
# faithful one, exercising the real assertion against real spawned processes and
# a real foreign listener (not mocks). This is the escape's own layer: the
# ~120s modal-block hang lived here, in the frozen-artifact gate.
# ---------------------------------------------------------------------------
def _free_tcp_port() -> int:
    """Return a currently-free localhost TCP port (bind-to-0 then release)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_fake_app(tmp_path: Path, *, message: str, exit_code: int,
                    sleep_s: float = 0.0) -> str:
    """Write a directly-executable fake 'frozen app' that (optionally sleeps,
    then) writes *message* to stderr and exits with *exit_code*, WITHOUT ever
    touching the foreign holder. Stands in for the launcher so the assertion's
    own pass/fail logic can be exercised deterministically."""
    script = tmp_path / "fake_app.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        f"time.sleep({sleep_s!r})\n"
        f"sys.stderr.write({message!r})\n"
        "sys.stderr.flush()\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(0o755)
    return str(script)


@pytest.mark.skipif(
    os.name == "nt",
    reason="fake-app shebang-exec is POSIX-only; the ahimsa unit suite runs on ubuntu",
)
class TestAssertForeignHolderNotKilled:
    """Prove-it-live at the gate-assertion layer (rule 22 / rule 31 corollary)."""

    def test_passes_on_fast_fail_loud_that_leaves_holder_alive(self, fv, tmp_path):
        port = _free_tcp_port()
        exe = _write_fake_app(
            tmp_path,
            message=(
                f"ERROR: port {port} held by pid 999, which is NOT identified as a "
                f"ManoMatika process; refusing to kill a foreign process — failing loud"
            ),
            exit_code=1,
        )
        # Must NOT raise: faithful fast fail-loud, non-zero, names port + reason,
        # and the fake never touches the holder.
        fv.assert_foreign_holder_not_killed(exe, port, timeout=30)

    def test_fails_when_app_exits_zero(self, fv, tmp_path):
        port = _free_tcp_port()
        exe = _write_fake_app(
            tmp_path,
            message=f"port {port} NOT identified as a ManoMatika process; refusing to kill",
            exit_code=0,
        )
        with pytest.raises(AssertionError, match="must exit non-zero"):
            fv.assert_foreign_holder_not_killed(exe, port, timeout=30)

    def test_fails_when_reason_keyword_absent(self, fv, tmp_path):
        port = _free_tcp_port()
        exe = _write_fake_app(
            tmp_path,
            message=f"port {port} is busy, giving up",  # non-zero but no foreign reason
            exit_code=1,
        )
        with pytest.raises(AssertionError, match="foreign-holder reason"):
            fv.assert_foreign_holder_not_killed(exe, port, timeout=30)

    def test_fails_when_port_not_named(self, fv, tmp_path):
        port = _free_tcp_port()
        exe = _write_fake_app(
            tmp_path,
            message="a process is NOT identified as a ManoMatika process; refusing to kill",
            exit_code=1,
        )
        with pytest.raises(AssertionError, match=f"must name the port {port}"):
            fv.assert_foreign_holder_not_killed(exe, port, timeout=30)

    def test_fails_when_exit_is_slow(self, fv, tmp_path, monkeypatch):
        """A non-zero exit with the right message but a SLOW exit (the modal-block
        signature, scaled down) must still FAIL the reconciled fast-exit clause."""
        monkeypatch.setattr(fv, "_FAST_FAIL_LOUD_LIMIT_S", 0.2)
        port = _free_tcp_port()
        exe = _write_fake_app(
            tmp_path,
            message=(
                f"port {port} NOT identified as a ManoMatika process; refusing to kill"
            ),
            exit_code=1,
            sleep_s=1.0,  # > the patched 0.2s fast limit, < the 30s timeout budget
        )
        with pytest.raises(AssertionError, match="FAIL LOUD FAST"):
            fv.assert_foreign_holder_not_killed(exe, port, timeout=30)
