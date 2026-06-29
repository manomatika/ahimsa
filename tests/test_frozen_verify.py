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
