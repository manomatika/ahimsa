#!/usr/bin/env python3
"""frozen_verify.py — prove the FROZEN product actually WORKS, on both install paths.

The systemic leak (standing rule 22): tests ran against repo source, never the
frozen pinned artifact, and the smoke-launch gate only checked that the app
BOOTS — never that its features WORK, and never the UPGRADE path. That let the
"EyeRate admin shows *coming soon* / lookup dead" regression reach the user's
machine: a stale eyerate plugin in ~/matika/plugins/ survived every reinstall
and the boot smoke never exercised it.

This script closes that gap. It boots the FROZEN executable in a clean,
throwaway HOME and runs MANIFEST-DRIVEN feature-level checks against the
*running* product. The set of screens it drives, and the markers/steps it
asserts, are NOT hardcoded: they are read from the assembled ``*_screens.json``
declarative data each component ships (matika core + every AppLug). The harness
is generic — it names no component, route, or marker, and discovers whatever the
manifest declares (see scripts/screen_manifest.py).

  TIER (a) — authenticated HTTP / route checks (this file): log in as the seeded
    admin (clearing the forced first-run password change), then for EVERY
    declared ``screen`` execute its navigate step(s) over authenticated HTTP and
    assert the route is alive, authorized, and renders HTML. CSS-selector marker
    assertions need a real DOM engine and are tier (b)'s job.

  TIER (b) — headless-browser / DOM checks (browser_verify.py, opt-in --browser):
    drives each declared screen's steps through Playwright and asserts its
    markers in the live DOM (this is the tier that catches a stale "coming soon"
    render — the real admin markers are absent).

Coverage enumeration reads the manifest from the PINNED SOURCE CLONES embedded
in the build dir via ``--source-root`` (e.g. ``build/matika`` — the A1 arm of
the hybrid read). The route inventory comes from the product's ``[ROUTES: ...]``
STARTUP LOG line (M3) — parsed from the booted app's logs, no runtime test
endpoint. Both the declared-screen set and the live-route set are captured and
made available for the A3 route-vs-manifest gate (manomatika/ahimsa#84).

Two SCENARIOS, both required:

  --scenario fresh    a first-time install (pristine HOME) — plugins extracted,
                      every declared screen drives clean.

  --scenario upgrade  an upgrade OVER a prior install. The script boots once to
                      do the real first run, then mutates ~/matika/plugins/eyerate
                      into the exact STALE state seen on the user's machine (old
                      "coming soon" template, older applug version, no install
                      marker, plus a user-data file), reboots, and asserts the
                      launcher REFRESHED the stale plugin to the bundled version
                      while PRESERVING the user-data file — then runs the same
                      manifest-driven tier-a (and tier-b) checks. The stale-state
                      seeding is the retained escaped-bug regression fixture; the
                      INSTALLED-DISK manifest read for upgrade-detection is A2
                      (manomatika/ahimsa#83).

Any failed assertion fails the build, dumping ~/matika/logs and the process
output so the reason is visible directly in the CI job log.

  LAYER 3 — applug-authored functional tests (--functional, or implied by
    --source-root): after the single-boot tier-a/b block closes, the gate
    discovers each applug's declared ``*_functional_tests.json`` from the pinned
    source clones, groups the tests by applug, and for EACH applug boots a FRESH
    app in a NEW clean HOME, mints a NEW session, runs only THAT applug's
    declared tests, then tears down (reboot-per-applug). Failure for one applug
    never aborts the others; ANY failed test fails the gate. WHO AUTHORS (the
    applug) is separate from WHO INVOKES (this generic gate) — no isolation/
    sandbox is implied.

Usage:
    python frozen_verify.py --exe <frozen-binary> --scenario fresh|upgrade \
        [--source-root build/matika] [--functional] [--port 8000] \
        [--timeout 90] [--browser]
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen_manifest  # noqa: E402  (local sibling module)

# The seeded first-run admin (matika src/matika/database.py::init_db).
ADMIN_EMAIL = "admin@matika.local"
ADMIN_PASSWORD = "adminpassword"
# A compliant replacement password (>= 8 chars) to clear force_password_change.
NEW_PASSWORD = "Verify-Pass-123"

STALE_COMING_SOON = (
    "<!doctype html><html><body>"
    "<h1>EyeRate Administration</h1>"
    "<p>Administration features coming soon.</p>"
    "</body></html>\n"
)
USER_DATA_NAME = "USER_NOTES.txt"
USER_DATA_CONTENT = "user-created data that MUST survive a plugin refresh\n"


def _reconfigure_stdio() -> None:
    # Frozen-app logs contain non-ASCII (e.g. "SECRET_KEY generated → …").
    # Force UTF-8 so reporting never crashes the step on Windows cp1252.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _read_logs(logs_dir: str) -> str:
    chunks = []
    for lf in sorted(glob.glob(os.path.join(logs_dir, "*.log"))):
        try:
            with open(lf, encoding="utf-8", errors="replace") as fh:
                chunks.append(f"\n----- {lf} -----\n{fh.read()}")
        except OSError as exc:  # pragma: no cover - defensive
            chunks.append(f"\n(could not read {lf}: {exc})\n")
    return "".join(chunks)


class FrozenAppError(RuntimeError):
    """Raised when the frozen app fails to boot or a feature check fails."""


class BootedApp:
    """Boot the frozen executable in a given HOME and wait until it serves.

    Used as a context manager so the process is always terminated and its logs
    are always available, even when a feature assertion raises.
    """

    def __init__(self, exe: str, home: str, port: int, timeout: int):
        self.exe = exe
        self.home = home
        self.port = port
        self.timeout = timeout
        self.base = f"http://127.0.0.1:{port}"
        self.proc: subprocess.Popen | None = None
        self.out_path = os.path.join(home, f"boot-stdout-{int(time.time()*1000)}.log")
        self._out_fh = None

    @property
    def logs_dir(self) -> str:
        return os.path.join(self.home, "matika", "logs")

    def captured_text(self) -> str:
        text = _read_logs(self.logs_dir)
        try:
            with open(self.out_path, encoding="utf-8", errors="replace") as fh:
                text += "\n" + fh.read()
        except OSError:
            pass
        return text

    def __enter__(self) -> "BootedApp":
        env = dict(os.environ)
        env["HOME"] = self.home          # POSIX Path.home()
        env["USERPROFILE"] = self.home   # Windows Path.home()
        # Neutralise the launcher's browser-open in headless CI.
        env["BROWSER"] = "true" if os.name != "nt" else "cmd /c rem"
        self._out_fh = open(self.out_path, "w", encoding="utf-8")
        print(f"  · launching {self.exe}")
        print(f"  · HOME = {self.home}")
        self.proc = subprocess.Popen(
            [self.exe], env=env, stdout=self._out_fh, stderr=subprocess.STDOUT
        )

        deadline = time.time() + self.timeout
        url = f"{self.base}/"
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise FrozenAppError(
                    f"process EXITED early (code {self.proc.returncode}) before "
                    f"the server came up"
                )
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    print(f"  · server responding HTTP {resp.status}")
                    return self
            except urllib.error.HTTPError as exc:
                # Any HTTP status means the server bound and is serving.
                print(f"  · server responding HTTP {exc.code}")
                return self
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(1.0)
        raise FrozenAppError(
            f"TIMEOUT after {self.timeout}s — server never bound on port {self.port}"
        )

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.proc is not None:
            with contextlib.suppress(Exception):
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=10)
        if self._out_fh is not None:
            with contextlib.suppress(Exception):
                self._out_fh.close()


# ---------------------------------------------------------------------------
# TIER (a) — authenticated HTTP / route-content feature checks (requests)
# ---------------------------------------------------------------------------

def _require_requests():
    try:
        import requests  # noqa: F401
    except ImportError as exc:  # pragma: no cover - CI installs it
        raise FrozenAppError(
            "the 'requests' package is required for tier-a checks "
            "(pip install requests)"
        ) from exc
    import requests
    return requests


def _login(requests, base: str):
    """Return an authenticated session, password-agnostic.

    The seeded admin starts with the default password and ``force_password_change``
    set, so the first login rotates it to NEW_PASSWORD. Because tier (a) and tier
    (b) share the same running server (and DB), a later login must accept EITHER
    the default password (first login of the run) OR the already-rotated one
    (any subsequent login). This avoids coupling the two tiers' order.
    """
    s = requests.Session()

    def attempt(pw):
        return s.post(
            f"{base}/login",
            data={"email": ADMIN_EMAIL, "password": pw},
            allow_redirects=False,
            timeout=15,
        )

    r = attempt(ADMIN_PASSWORD)
    if r.status_code in (302, 303):
        if "/change-password" in r.headers.get("location", ""):
            cp = s.post(
                f"{base}/change-password",
                data={"new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD},
                allow_redirects=False,
                timeout=15,
            )
            if cp.status_code not in (302, 303):
                raise FrozenAppError(
                    f"change-password POST returned {cp.status_code} "
                    f"(expected a redirect); body head: {cp.text[:200]!r}"
                )
    else:
        # Default password rejected — it was already rotated earlier this run.
        r2 = attempt(NEW_PASSWORD)
        if r2.status_code not in (302, 303):
            raise FrozenAppError(
                "login failed with BOTH the default and the rotated password "
                f"(HTTP {r.status_code}/{r2.status_code}); body head: {r2.text[:200]!r}"
            )
    # Confirm we are actually authenticated now.
    home = s.get(f"{base}/", allow_redirects=False, timeout=15)
    if home.status_code not in (200, 302, 303):
        raise FrozenAppError(f"post-login GET / returned {home.status_code}")
    return s


class HttpScreenExecutor(screen_manifest.ScreenExecutor):
    """Tier-(a) executor: drives a declared screen over authenticated HTTP.

    ``navigate`` is performed as an authenticated GET and the response is
    asserted to be a live, authorized, HTML render (catches a removed/renamed
    screen → 404, a crash → 5xx, or an auth-gate misfire → 4xx). CSS-selector
    markers and DOM-interaction verbs (fill/click/wait_for/assert_*) require a
    real DOM engine and are deferred to tier (b); with today's navigate-only
    screen data nothing is silently dropped.
    """

    def __init__(self, session, base: str):
        self.session = session
        self.base = base

    def run_step(self, step: screen_manifest.Step) -> None:
        if step.verb == "navigate":
            url = self.base + (step.target or "")
            try:
                r = self.session.get(url, allow_redirects=False, timeout=30)
            except Exception as exc:  # noqa: BLE001 - surface as a feature failure
                raise FrozenAppError(f"GET {step.target} raised: {exc}") from exc
            if r.status_code != 200:
                raise FrozenAppError(
                    f"declared screen route {step.target} returned HTTP "
                    f"{r.status_code} (expected 200 for the authenticated admin); "
                    f"body head: {r.text[:300]!r}"
                )
            ctype = r.headers.get("Content-Type", "")
            if "html" not in ctype.lower() or not r.text.strip():
                raise FrozenAppError(
                    f"declared screen route {step.target} returned 200 but not a "
                    f"non-empty HTML body (Content-Type {ctype!r})"
                )
            print(f"      · [http] GET {step.target} -> 200 HTML")
        else:
            # DOM-only verb: tier (a) cannot perform it without a browser.
            print(f"      · [http] defer '{step.verb}' to tier (b) (no DOM in HTTP tier)")

    def assert_markers(self, markers) -> None:
        # Marker selectors are evaluated against the live DOM in tier (b); the
        # HTTP tier's per-screen proof is route liveness (above).
        print(f"      · [http] {len(markers)} marker(s) verified in tier (b)")


def run_tier_a(base: str, manifest: screen_manifest.ScreenManifest) -> None:
    print("  TIER (a) — manifest-driven authenticated-HTTP route checks")
    requests = _require_requests()
    s = _login(requests, base)
    executor = HttpScreenExecutor(s, base)
    for screen in manifest.screens:
        print(f"    · [{screen.source}] {screen.screen_id} -> {screen.route}")
        screen_manifest.drive_screen(screen, executor)
    print(f"  TIER (a): PASS ({len(manifest.screens)} screen(s) driven)")


def run_tier_b(base: str, manifest: screen_manifest.ScreenManifest) -> None:
    print("  TIER (b) — manifest-driven headless-browser / DOM checks (Playwright)")
    import browser_verify  # local sibling module
    browser_verify.run_browser_checks(
        base, manifest, admin_email=ADMIN_EMAIL, admin_password=ADMIN_PASSWORD,
        new_password=NEW_PASSWORD,
    )
    print("  TIER (b): PASS")


# ---------------------------------------------------------------------------
# Upgrade-over-stale: mutate the extracted plugin into the user's stale state
# ---------------------------------------------------------------------------

def _seed_stale_eyerate(home: str) -> None:
    """Rewrite ~/matika/plugins/eyerate into the exact stale state from the mini.

    This is what an install OVER an older version leaves behind: an old
    "coming soon" admin template, an older applug version, NO install marker
    (the marker predates the fix), plus a user-data file that must be preserved.
    """
    plugin = os.path.join(home, "matika", "plugins", "eyerate")
    if not os.path.isdir(plugin):
        raise FrozenAppError(
            f"upgrade seed: extracted eyerate plugin not found at {plugin} — "
            f"the first boot did not extract it"
        )
    # 1) Stale admin template.
    tmpl = os.path.join(plugin, "src", "eyerate", "templates", "eyerate_admin.html")
    if not os.path.isfile(tmpl):
        # Fall back to a flat templates/ layout if the repo layout differs.
        alt = os.path.join(plugin, "templates", "eyerate_admin.html")
        tmpl = alt if os.path.isfile(alt) else tmpl
    os.makedirs(os.path.dirname(tmpl), exist_ok=True)
    with open(tmpl, "w", encoding="utf-8") as fh:
        fh.write(STALE_COMING_SOON)
    # 2) Older applug version.
    manifest_path = os.path.join(plugin, "applug.json")
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        manifest = {"id": "eyerate"}
    manifest["version"] = "0.0.1"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    # 3) Remove the install marker so it looks like a pre-fix install.
    marker = os.path.join(plugin, ".matika_plugin_install.json")
    with contextlib.suppress(OSError):
        os.remove(marker)
    # 4) A user-data file that MUST survive the refresh.
    with open(os.path.join(plugin, USER_DATA_NAME), "w", encoding="utf-8") as fh:
        fh.write(USER_DATA_CONTENT)
    print(f"  · seeded STALE eyerate plugin at {plugin}")
    print("    (coming-soon template, version 0.0.1, marker removed, user data added)")


def _assert_refreshed(home: str, boot_text: str) -> None:
    """After the upgrade reboot, prove the stale plugin was refreshed + data kept."""
    plugin = os.path.join(home, "matika", "plugins", "eyerate")
    # The launcher must log a refresh decision for eyerate.
    if "plugin eyerate:" not in boot_text or "refreshed" not in boot_text:
        raise FrozenAppError(
            "launcher did NOT log an eyerate refresh on the upgrade boot — the "
            "stale plugin was not detected/refreshed. Boot log head:\n"
            + boot_text[:800]
        )
    # The stale template must be gone on disk.
    for cand in (
        os.path.join(plugin, "src", "eyerate", "templates", "eyerate_admin.html"),
        os.path.join(plugin, "templates", "eyerate_admin.html"),
    ):
        if os.path.isfile(cand):
            with open(cand, encoding="utf-8") as fh:
                if "coming soon" in fh.read().lower():
                    raise FrozenAppError(
                        f"stale 'coming soon' template still on disk after refresh: {cand}"
                    )
    # User data must be preserved.
    user_file = os.path.join(plugin, USER_DATA_NAME)
    if not os.path.isfile(user_file):
        raise FrozenAppError(
            f"user-data file {USER_DATA_NAME} was DESTROYED by the refresh — "
            f"data preservation failed"
        )
    with open(user_file, encoding="utf-8") as fh:
        if fh.read() != USER_DATA_CONTENT:
            raise FrozenAppError(f"user-data file {USER_DATA_NAME} was modified by refresh")
    print("  · upgrade refresh verified: stale template replaced, user data preserved")


# ---------------------------------------------------------------------------
# Scenario drivers
# ---------------------------------------------------------------------------

def _capture_route_inventory(app: BootedApp, manifest) -> None:
    """Capture the live-route set (from [ROUTES:...]) beside the declared set.

    A1 only CAPTURES and EXPOSES both sets; it does NOT compare them. The
    route-vs-manifest HARD GATE that fails the build on an undeclared live screen
    is A3 (manomatika/ahimsa#84) and plugs in at the SEAM marked below.
    """
    live_routes = screen_manifest.parse_routes_marker(app.captured_text())
    declared = manifest.declared_routes() if manifest is not None else []
    print(f"  · route inventory (from [ROUTES:...] startup marker): "
          f"{len(live_routes)} live GET route(s)")
    if manifest is not None:
        print(f"  · declared screen routes (from manifest): {len(declared)}")
    if not live_routes:
        print("  · WARNING: no [ROUTES:...] marker found in the boot logs "
              "(matika#86 / M3 emits it at startup)")
    # SEAM (A3, manomatika/ahimsa#84): the route-vs-manifest hard gate compares
    # `live_routes` against the manifest's classified routes HERE and fails the
    # build on any live GET route the manifest does not declare. A1 stops at
    # capture so both sets are available without yet enforcing the comparison.


def _run_checks(app: BootedApp, browser: bool, manifest) -> None:
    _capture_route_inventory(app, manifest)
    if manifest is None:
        return
    run_tier_a(app.base, manifest)
    if browser:
        run_tier_b(app.base, manifest)


def scenario_fresh(exe: str, port: int, timeout: int, browser: bool, manifest) -> None:
    print("=== SCENARIO: fresh (first-time install) ===")
    home = tempfile.mkdtemp(prefix="mm-verify-fresh-")
    try:
        with BootedApp(exe, home, port, timeout) as app:
            try:
                _run_checks(app, browser, manifest)
            except Exception:
                _dump_failure(app)
                raise
    finally:
        shutil.rmtree(home, ignore_errors=True)
    print("=== fresh: PASS ===\n")


def scenario_upgrade(exe: str, port: int, timeout: int, browser: bool, manifest) -> None:
    print("=== SCENARIO: upgrade (over a prior, stale install) ===")
    home = tempfile.mkdtemp(prefix="mm-verify-upgrade-")
    try:
        # 1) Real first run extracts eyerate fresh.
        print("  [1/2] initial install boot (extracts eyerate)")
        with BootedApp(exe, home, port, timeout) as app:
            pass
        # 2) Make it look like the user's stale machine.
        _seed_stale_eyerate(home)
        # 3) Reboot — the launcher must refresh the stale plugin.
        print("  [2/2] upgrade boot (must refresh the stale plugin)")
        with BootedApp(exe, home, port, timeout) as app:
            boot_text = app.captured_text()
            try:
                _assert_refreshed(home, boot_text)
                _run_checks(app, browser, manifest)
            except Exception:
                _dump_failure(app)
                raise
    finally:
        shutil.rmtree(home, ignore_errors=True)
    print("=== upgrade: PASS ===\n")


def _dump_failure(app: BootedApp) -> None:
    print("\n========== ~/matika/logs (frozen app) ==========")
    text = _read_logs(app.logs_dir)
    print(text if text else "(NO log files were written!)")
    try:
        with open(app.out_path, encoding="utf-8", errors="replace") as fh:
            print("\n========== process stdout/stderr ==========")
            print(fh.read())
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Layer-3 — applug-AUTHORED functional tests, GENERICALLY INVOKED (reboot model)
#
# WHO AUTHORS (each applug, via its *_functional_tests.json + module) is separate
# from WHO INVOKES (this generic gate). The gate discovers the declared tests
# from the PINNED SOURCE CLONES (source_root), groups them by applug, and for
# EACH applug boots a FRESH frozen app in a NEW clean throwaway HOME, mints a NEW
# authenticated session for THAT boot, runs only THAT applug's declared tests,
# and tears the boot down before the next applug (reboot-per-applug, decided
# model 2a). No isolation/sandbox is implied — this is plain build automation.
#
# Failure isolation: a failing boot, login, or test for one applug NEVER aborts
# the others. Every result is collected; the phase fails the gate (non-zero exit
# overall) if ANY test failed.
#
# Port: reuses the SAME port the single-boot tier-a/b phase used. The L3 boots
# happen only AFTER that phase's `with BootedApp(...)` block has closed and its
# process has been terminated/waited, so the port is free for each L3 boot
# (which are themselves strictly sequential — one applug at a time).
# ---------------------------------------------------------------------------

def run_l3_functional(exe: str, port: int, timeout: int, source_root: str) -> bool:
    """Run the Layer-3 applug-functional-test phase, REBOOT-PER-APPLUG.

    Returns True if every declared functional test passed (or none were
    declared), False if ANY test (or its applug's boot/login) failed. The caller
    turns a False return into a non-zero overall exit.
    """
    print("=== LAYER 3: applug-authored functional tests (reboot-per-applug) ===")
    manifest = screen_manifest.load_functional_test_manifest(source_root)
    if not manifest.tests:
        print("  L3 — no applug declared *_functional_tests.json; phase SKIPPED")
        print("=== L3: PASS (no functional tests declared) ===\n")
        return True

    # Group the flat declared-test list by applug source so each applug gets one
    # fresh boot covering exactly its own tests.
    by_source: dict = {}
    for decl in manifest.tests:
        by_source.setdefault(decl.source, []).append(decl)

    requests = _require_requests()
    results = []  # list of (source, test_id, ok: bool, error: str | None)

    for source in sorted(by_source):
        decls = by_source[source]
        print(f"  L3 — applug {source!r}: {len(decls)} functional test(s); "
              f"booting a FRESH app in a clean HOME")
        home = tempfile.mkdtemp(prefix=f"mm-verify-l3-{source}-")
        app = BootedApp(exe, home, port, timeout)
        applug_failed = False
        try:
            with app:
                # A NEW authenticated session is minted PER boot — never reused
                # across applugs/boots.
                session = _login(requests, app.base)
                for decl in decls:
                    try:
                        screen_manifest.invoke_functional_test(
                            decl, source_root, app.base, session
                        )
                        results.append((source, decl.test_id, True, None))
                        print(f"      · [{source}] {decl.test_id}: PASS")
                    except Exception as exc:  # noqa: BLE001 - isolate per test
                        applug_failed = True
                        results.append((source, decl.test_id, False, str(exc)))
                        print(f"      · [{source}] {decl.test_id}: FAIL — {exc}")
                if applug_failed:
                    _dump_failure(app)
        except Exception as exc:  # noqa: BLE001 - boot/login failure for this applug
            # Boot or login failed: mark every declared test for THIS applug as
            # failed, dump its logs, and continue with the next applug.
            applug_failed = True
            _dump_failure(app)
            for decl in decls:
                results.append((source, decl.test_id, False,
                                f"boot/login failed: {exc}"))
            print(f"      · [{source}] boot/login FAILED — {exc}")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    # Per-applug, per-test PASS/FAIL summary.
    print("  L3 summary:")
    failed = [(s, t, e) for (s, t, ok, e) in results if not ok]
    for source in sorted(by_source):
        for (s, t, ok, e) in results:
            if s == source:
                print(f"    [{s}] {t}: {'PASS' if ok else 'FAIL'}"
                      + (f" — {e}" if not ok else ""))
    overall_ok = not failed
    if overall_ok:
        print(f"=== L3: PASS ({len(results)} test(s) across "
              f"{len(by_source)} applug(s)) ===\n")
    else:
        print(f"=== L3: FAIL ({len(failed)}/{len(results)} test(s) failed) ===\n")
    return overall_ok


def _load_manifest(source_root):
    """Load the screen manifest from the pinned source clones (A1 arm), or skip.

    When --source-root is given the manifest MUST load (a missing/empty/malformed
    manifest is a ScreenManifestError → non-zero exit, per the acceptance
    criterion). When --source-root is omitted the source-clone arm is not
    available (e.g. the install-verify jobs, which only have the installed
    artifact): the per-screen manifest drive is SKIPPED here and supplied by the
    INSTALLED-DISK arm (A2, manomatika/ahimsa#83). Boot + route-inventory capture
    + the upgrade-refresh assertions still run.
    """
    if not source_root:
        print("  · no --source-root given: manifest-driven screen checks SKIPPED "
              "for this run (installed-disk arm is manomatika/ahimsa#83 / A2). "
              "Boot, [ROUTES:...] capture and upgrade-refresh checks still run.")
        return None
    manifest = screen_manifest.load_screen_manifest(source_root)
    print(f"  · loaded screen manifest from {source_root}: "
          f"{len(manifest.screens)} screen(s) + {len(manifest.not_a_screen)} "
          f"not-a-screen across sources {list(manifest.sources)}")
    return manifest


def main() -> int:
    _reconfigure_stdio()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exe", required=True, help="frozen executable to launch")
    ap.add_argument("--scenario", required=True, choices=["fresh", "upgrade"])
    ap.add_argument("--source-root", default=None,
                    help="root of the pinned source clones holding the assembled "
                         "*_screens.json (e.g. build/matika). Enables the "
                         "manifest-driven per-screen checks (A1 source-clone arm).")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--browser", action="store_true",
                    help="also run tier (b) headless-browser checks (Playwright)")
    ap.add_argument("--functional", action="store_true",
                    help="run the Layer-3 applug-authored functional tests "
                         "(reboot-per-applug). Also implied whenever --source-root "
                         "is given (the functional manifest is discovered from it). "
                         "Requires --source-root.")
    args = ap.parse_args()

    exe = os.path.abspath(args.exe)
    if not os.path.exists(exe):
        print(f"::error::frozen executable not found: {exe}")
        return 1

    # L3 runs when explicitly requested OR whenever a source-root is available
    # (the functional manifest is discovered from the pinned source clones).
    # --functional WITHOUT a source-root is a hard error: there is nothing to
    # discover the functional manifest from.
    l3_enabled = args.functional or bool(args.source_root)
    if args.functional and not args.source_root:
        print("::error::frozen-verify: --functional requires --source-root "
              "(the functional-test manifest is discovered from the pinned "
              "source clones; without it there is nothing to discover)")
        return 1

    try:
        manifest = _load_manifest(args.source_root)
        if args.scenario == "fresh":
            scenario_fresh(exe, args.port, args.timeout, args.browser, manifest)
        else:
            scenario_upgrade(exe, args.port, args.timeout, args.browser, manifest)
        # Layer-3 functional tests run AFTER the single-boot tier-a/b block has
        # closed (so the port is free), on BOTH scenarios (rule 22, both install
        # paths — CI invokes this once per scenario, so L3 runs on each path).
        if l3_enabled:
            if not run_l3_functional(exe, args.port, args.timeout, args.source_root):
                print(f"::error::frozen-verify [{args.scenario}] L3 functional "
                      f"phase FAILED")
                return 1
    except screen_manifest.ScreenManifestError as exc:
        print(f"::error::frozen-verify [{args.scenario}] could not load the screen "
              f"manifest: {exc}")
        return 1
    except FrozenAppError as exc:
        print(f"::error::frozen-verify [{args.scenario}] FAILED: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - surface anything as a build failure
        print(f"::error::frozen-verify [{args.scenario}] unexpected error: {exc}")
        import traceback
        traceback.print_exc()
        return 1
    print(f"frozen-verify [{args.scenario}]: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
