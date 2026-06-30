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
    declared tests in a RANDOMIZED (seeded) order, then tears down
    (reboot-per-applug). Each test ARRANGES its own preconditions (declared
    ``setup``) and RESETS what it mutated (declared ``teardown``, guaranteed-run);
    randomized order is the verifier that reset discipline holds. The reboot is
    coarse containment BETWEEN trust domains, NOT a substitute for per-test reset
    (no within-applug reboot). The order is reproducible from one base seed
    (logged as ``L3 random seed: <seed>``, replayable via ``--l3-seed``). Failure
    for one applug never aborts the others; ANY failed test fails the gate. WHO
    AUTHORS (the applug) is separate from WHO INVOKES (this generic gate) — no
    isolation/sandbox is implied.

Usage:
    python frozen_verify.py --exe <frozen-binary> --scenario fresh|upgrade \
        [--source-root build/matika] [--functional] [--port 8000] \
        [--timeout 90] [--browser]
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import socket
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

SCAFFOLDING_ENTRIES = ['.git', '.github', '.husky', '.gitattributes', '.gitignore', 'node_modules', 'tests']


def assert_plugin_payload_clean(data_dir: Path) -> None:
    """Assert that no dev scaffolding leaked into the extracted plugin payload.

    Rule 22: this assertion must FAIL on a build from the unpatched build.yml
    and PASS on a build from the patched build.yml.
    """
    plugins_dir = data_dir / "plugins"
    if not plugins_dir.exists():
        print(f"WARNING: plugins dir not found at {plugins_dir}; skipping cleanliness check")
        return
    leaked = []
    for plug_dir in sorted(plugins_dir.iterdir()):
        if not plug_dir.is_dir():
            continue
        for entry in SCAFFOLDING_ENTRIES:
            path = plug_dir / entry
            if path.exists():
                leaked.append(f"{plug_dir.name}/{entry}")
    if leaked:
        raise AssertionError(
            f"ERROR: scaffolding leaked into payload: {leaked!r}\n"
            f"  These entries must not exist in {plugins_dir}.\n"
            f"  Fix: ensure build.yml strips scaffolding before bundling."
        )
    print(f"INFO: plugin payload clean — no scaffolding in {plugins_dir}")


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
# Lifecycle assertions (D — rule-22 frozen-artifact gate regressions)
# ---------------------------------------------------------------------------

def assert_healthz_reachable_and_version(port: int, expected_matika_tag: str) -> None:
    """Probe /healthz, assert product==ManoMatika + version matches tag + status==ok.

    Also verifies the server is NOT reachable on any non-loopback interface.
    The non-loopback check is skipped when no non-loopback interface is
    discoverable (pure-loopback CI container).
    """
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body_bytes = resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise AssertionError(
            f"Failed to probe /healthz on port {port}: {exc}"
        ) from exc

    try:
        body = json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"/healthz on port {port} returned non-JSON body: {body_bytes!r}"
        ) from exc

    assert body.get("product") == "ManoMatika", (
        f"/healthz product mismatch on port {port}: "
        f"expected 'ManoMatika', got {body.get('product')!r}; body: {body!r}"
    )
    assert body.get("status") == "ok", (
        f"/healthz status mismatch on port {port}: "
        f"expected 'ok', got {body.get('status')!r}; body: {body!r}"
    )
    expected_version = expected_matika_tag.lstrip("v")
    actual_version = body.get("version", "")
    assert actual_version == expected_version, (
        f"/healthz version mismatch on port {port}: "
        f"expected {expected_version!r} (tag {expected_matika_tag!r}), "
        f"got {actual_version!r}; body: {body!r}"
    )
    print(f"INFO: healthz OK: {body!r} (port {port})")

    # Loopback-only sub-check: assert non-loopback address is refused.
    # Use socket.create_connection so this check is independent of urllib mocking.
    try:
        non_loopback_ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        non_loopback_ip = "127.0.0.1"

    if non_loopback_ip.startswith("127."):
        # Hostname resolved to loopback — try IPv6 loopback as the test target
        non_loopback_ip = "::1"

    if non_loopback_ip == "::1":
        print("INFO: healthz loopback-only: skipped (no non-loopback interface found)")
        return

    # Non-loopback IP found — assert the server cannot be reached there
    try:
        conn = socket.create_connection((non_loopback_ip, port), timeout=3)
        conn.close()
        raise AssertionError(
            f"/healthz is reachable on non-loopback {non_loopback_ip}:{port} "
            f"— server must bind loopback-only (127.0.0.1)"
        )
    except OSError:
        print(f"INFO: healthz loopback-only: {non_loopback_ip} correctly refused")


def assert_double_launch_recovery(exe: str, port: int, timeout: int) -> None:
    """Boot a second instance while the first is running; assert graceful exit 0.

    Instance B must detect port already in use, identify the running ManoMatika
    instance, and exit 0 — logging the graceful-recovery decision line.

    MANDATE: FAILS against pre-fix artifact (exits 1 silently on port conflict);
    PASSES against post-fix artifact (exits 0 gracefully).
    """
    b_home = tempfile.mkdtemp(prefix="mm-verify-dl-b-")
    try:
        env = dict(os.environ)
        env["HOME"] = b_home
        env["USERPROFILE"] = b_home
        env["BROWSER"] = "true" if os.name != "nt" else "cmd /c rem"
        proc_b = subprocess.Popen(
            [exe], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            stdout_b, _ = proc_b.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc_b.kill()
            stdout_b, _ = proc_b.communicate()
            raise AssertionError(
                f"double-launch: instance B timed out after 30s (did not exit); "
                f"B output: {stdout_b!r}"
            )
        out_b = (
            stdout_b.decode("utf-8", errors="replace")
            if isinstance(stdout_b, bytes)
            else (stdout_b or "")
        )
        assert proc_b.returncode == 0, (
            f"double-launch: instance B must exit 0 (graceful recovery) but "
            f"exited {proc_b.returncode}; B output:\n{out_b}"
        )
        recovery_keywords = [
            "ManoMatika instance",
            "focusing existing window",
            "already held",
        ]
        match = next((kw for kw in recovery_keywords if kw in out_b), None)
        assert match is not None, (
            f"double-launch: instance B exited 0 but no recovery log line found "
            f"(checked for: {recovery_keywords!r}); B output:\n{out_b}"
        )
        print("INFO: double-launch: instance B exited 0 (graceful recovery confirmed)")
        print(f"INFO: double-launch: B output contained recovery log line: {match!r}")
    finally:
        shutil.rmtree(b_home, ignore_errors=True)


def _probe_port_bindable(port: int) -> "OSError | None":
    """Mirror the REAL launcher's port-free decision EXACTLY.

    The matika launcher's own "can I start here?" gate is ``_port_available()``
    (matika/launcher.py): ``AF_INET`` + ``SOCK_STREAM`` + ``SO_REUSEADDR`` +
    ``bind(("127.0.0.1", port))``; its uvicorn listen socket binds the same
    address with SO_REUSEADDR too. This probe binds IDENTICALLY so the assertion
    means precisely "would the real app bind here?", nothing stricter.

    Returns ``None`` if the port is bindable the launcher's way (the app WOULD
    start), or the ``OSError`` a launcher-identical bind raises (a real live
    LISTEN socket still holds the port — SO_REUSEADDR does not let us bind over an
    active listener, only over TIME_WAIT residue).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        return None
    except OSError as exc:
        return exc
    finally:
        with contextlib.suppress(Exception):
            s.close()


def assert_abrupt_kill_port_free(proc: "subprocess.Popen[bytes]", port: int) -> None:
    """SIGKILL a running app; assert the port is free 1s later and stays free 3s later.

    Proves the OS released the port after an abrupt kill (D3 freeze_support fix).
    The free-check binds the port EXACTLY as the real launcher does (AF_INET +
    SO_REUSEADDR + 127.0.0.1) so a transient TIME_WAIT teardown window — which the
    real app tolerates but a plain bind rejects — is not a false positive, while a
    real orphan/respawned LISTEN socket still fails the assertion.
    """
    if proc.poll() is not None:
        print(f"INFO: abrupt-kill: process already dead (skipping SIGKILL)")
        return

    proc.kill()
    proc.wait(timeout=10)

    time.sleep(1.0)

    def _capture_diagnostics(port_: int) -> None:
        """Best-effort OS-state capture for diagnosing an abrupt-kill bind failure.

        Settles two competing explanations: (1) harness false-positive — the
        launched process IS reaped and the plain (no-SO_REUSEADDR) bind is
        rejecting transient kernel socket residue the real app would tolerate —
        vs (2) a real orphan still holds the port. Each probe is independently
        wrapped so a missing tool (ps/lsof may not exist on the Windows runner)
        never masks the original assertion below.
        """
        print(f"DIAG: abrupt-kill: launched proc.pid={proc.pid} proc.poll()={proc.poll()}")

        if sys.platform == "darwin":
            try:
                ps_out = subprocess.run(
                    ["ps", "-ax", "-o", "pid,ppid,pgid,stat,command"],
                    capture_output=True, text=True, timeout=10,
                ).stdout
                lines = ps_out.splitlines()
                header, body = (lines[0], lines[1:]) if lines else ("", [])
                related = [header] if header else []
                for line in body:
                    fields = line.split(None, 4)
                    if len(fields) < 5:
                        continue
                    pid_s, ppid_s = fields[0], fields[1]
                    if "ManoMatika" in line or pid_s == str(proc.pid) or ppid_s == str(proc.pid):
                        related.append(line)
                print("DIAG: abrupt-kill: ps -ax -o pid,ppid,pgid,stat,command "
                      "(ManoMatika / launched-pid-and-children lines):")
                for line in (related or ["  (no matching ps lines)"]):
                    print(f"DIAG:   {line}")
            except Exception as exc:
                print(f"DIAG: abrupt-kill: ps capture unavailable: {exc!r}")

            for cmd, label in (
                (["lsof", "-nP", f"-iTCP:{port_}"], "all"),
                (["lsof", "-nP", f"-iTCP:{port_}", "-sTCP:LISTEN"], "LISTEN-only"),
            ):
                try:
                    lsof_out = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=10,
                    ).stdout
                    print(f"DIAG: abrupt-kill: lsof -iTCP:{port_} ({label}):")
                    for line in (lsof_out.splitlines() or ["  (no output — nothing matched)"]):
                        print(f"DIAG:   {line}")
                except Exception as exc:
                    print(f"DIAG: abrupt-kill: lsof ({label}) capture unavailable: {exc!r}")
        else:
            print("DIAG: abrupt-kill: ps/lsof capture skipped (not macOS)")

        # Contrast a PLAIN bind against the launcher-identical SO_REUSEADDR bind.
        # The assertion now uses the SO_REUSEADDR form, so reaching this failure
        # path means even the launcher's own bind was rejected (a real listener).
        # plain-FAILS + reuseaddr-FAILS together = genuine orphan; plain-FAILS +
        # reuseaddr-SUCCEEDS would have been the old TIME_WAIT false positive
        # (no longer possible to reach here, by construction).
        def _probe_bind(use_reuseaddr: bool) -> str:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if use_reuseaddr:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("127.0.0.1", port_))
                return "SUCCEEDED"
            except OSError as exc:
                return f"FAILED ({exc!r})"
            except Exception as exc:
                return f"FAILED ({exc!r})"
            finally:
                with contextlib.suppress(Exception):
                    probe.close()

        print(f"DIAG: abrupt-kill diag: plain bind {_probe_bind(False)}; "
              f"SO_REUSEADDR (launcher-identical) bind {_probe_bind(True)}")

    def _try_bind(port_: int, elapsed_label: str) -> None:
        # Bind EXACTLY as the real launcher does — AF_INET + SO_REUSEADDR + 127.0.0.1
        # (see _probe_port_bindable). The assertion must mean "would the real app
        # bind here?", nothing stricter.
        #
        # Why SO_REUSEADDR (the manomatika/ahimsa#119/#120 mechanism): after SIGKILL
        # macOS leaves the port in a TIME_WAIT teardown window — produced by the
        # harness's own healthz/double-launch connections to the server. The process
        # is reaped (ps clean, lsof LISTEN empty), yet a PLAIN bind is rejected
        # (EADDRINUSE) for that whole window. The real launcher always binds with
        # SO_REUSEADDR, which bypasses exactly that residue, so it would start fine;
        # a plain-bind probe is stricter than the app and false-positives. This is a
        # SEMANTIC bind difference, not a timing window — so we mirror the launcher's
        # bind, NOT widen a retry (the #120 bounded retry is removed). SO_REUSEADDR
        # still cannot bind over an active LISTEN socket (uvicorn sets no SO_REUSEPORT),
        # so a real orphan/respawn fails here and fires the assertion.
        exc = _probe_port_bindable(port_)
        if exc is None:
            return
        _capture_diagnostics(port_)
        raise AssertionError(
            f"ERROR: abrupt-kill: port {port_} still held by a live listener "
            f"(checked {elapsed_label}s after SIGKILL; launcher-identical bind: "
            f"AF_INET + SO_REUSEADDR + 127.0.0.1) — possible orphan or respawn! ({exc})"
        ) from exc

    _try_bind(port, "1")
    print(f"INFO: abrupt-kill: port {port} confirmed free 1s after SIGKILL")

    time.sleep(2.0)

    _try_bind(port, "3")
    print(f"INFO: abrupt-kill: no respawn detected (port still free after 3s)")


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


def scenario_fresh(exe: str, port: int, timeout: int, browser: bool, manifest,
                   matika_tag: str | None = None) -> None:
    print("=== SCENARIO: fresh (first-time install) ===")
    home = tempfile.mkdtemp(prefix="mm-verify-fresh-")
    try:
        with BootedApp(exe, home, port, timeout) as app:
            try:
                _run_checks(app, browser, manifest)
                if matika_tag is not None:
                    assert_healthz_reachable_and_version(port, matika_tag)
                if matika_tag is not None:
                    assert_double_launch_recovery(exe, port, timeout)
                assert_abrupt_kill_port_free(app.proc, port)
            except Exception:
                _dump_failure(app)
                raise
    finally:
        shutil.rmtree(home, ignore_errors=True)
    print("=== fresh: PASS ===\n")


def scenario_upgrade(exe: str, port: int, timeout: int, browser: bool, manifest,
                     matika_tag: str | None = None) -> None:
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
                if matika_tag is not None:
                    assert_healthz_reachable_and_version(port, matika_tag)
                assert_abrupt_kill_port_free(app.proc, port)
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
# RESET DISCIPLINE + RANDOMIZED ORDER: within a single applug's boot, that
# applug's tests run in a RANDOMIZED (seeded) order. Each test is expected to
# ARRANGE its own preconditions (declared ``setup``) and RESET what it mutated
# back to known-initial-state (declared ``teardown``, guaranteed-run via
# try/finally in screen_manifest.invoke_functional_test). Randomized order is the
# VERIFIER that reset discipline is complete — order-dependent state leaks surface
# as flakes. The reboot is coarse containment BETWEEN independently-authored
# applugs (separate trust domains), NOT a substitute for a test resetting its own
# state: there is NO within-applug reboot. The whole run is reproducible from one
# base seed (logged as "L3 random seed: <seed>", replayable via --l3-seed).
#
# Port: reuses the SAME port the single-boot tier-a/b phase used. The L3 boots
# happen only AFTER that phase's `with BootedApp(...)` block has closed and its
# process has been terminated/waited, so the port is free for each L3 boot
# (which are themselves strictly sequential — one applug at a time).
# ---------------------------------------------------------------------------

def _derive_seed(base_seed: int, source: str) -> int:
    """Deterministically derive a per-applug ordering seed from the base seed.

    The whole run is reproducible from the ONE logged base seed: the same base
    seed yields the same per-applug seed (and therefore the same order) for every
    applug, independent of how many applugs there are.
    """
    return random.Random(f"{base_seed}:{source}").randrange(2 ** 32)


def _run_applug_tests(decls, source_root: str, base_url: str, session, seed: int):
    """Run ONE applug's declared L3 tests in RANDOMIZED (seeded) order.

    Pure of any boot/login concern (the caller injects an already-authenticated
    ``session``) so the ordering + setup/teardown contract is unit-testable
    without a real frozen app. Each declared test is invoked via
    ``screen_manifest.invoke_functional_test`` — which runs its declared
    ``setup`` first and its declared ``teardown`` with guaranteed-run semantics.
    Per-test failures are ISOLATED: one failing test never stops the rest.

    Returns a list of ``(test_id, ok: bool, error: str | None)`` in EXECUTION
    (randomized) order.
    """
    ordered = list(decls)
    random.Random(seed).shuffle(ordered)
    results = []
    for decl in ordered:
        try:
            screen_manifest.invoke_functional_test(
                decl, source_root, base_url, session
            )
            results.append((decl.test_id, True, None))
            print(f"      · [{decl.source}] {decl.test_id}: PASS")
        except Exception as exc:  # noqa: BLE001 - isolate per test
            results.append((decl.test_id, False, str(exc)))
            print(f"      · [{decl.source}] {decl.test_id}: FAIL — {exc}")
    return results


def run_l3_functional(exe: str, port: int, timeout: int, source_root: str,
                      seed: int | None = None) -> bool:
    """Run the Layer-3 applug-functional-test phase, REBOOT-PER-APPLUG.

    Each applug's tests run in a randomized order derived from ``seed`` (a base
    seed; when None one is generated and LOGGED so the run is replayable via
    ``--l3-seed``). Returns True if every declared functional test passed (or none
    were declared), False if ANY test (or its applug's boot/login) failed. The
    caller turns a False return into a non-zero overall exit.
    """
    print("=== LAYER 3: applug-authored functional tests (reboot-per-applug) ===")
    manifest = screen_manifest.load_functional_test_manifest(source_root)
    if not manifest.tests:
        print("  L3 — no applug declared *_functional_tests.json; phase SKIPPED")
        print("=== L3: PASS (no functional tests declared) ===\n")
        return True

    if seed is None:
        seed = random.randrange(2 ** 32)
    # Greppable + replayable: the one base seed reproduces the entire run's order.
    print(f"  L3 random seed: {seed}  (replay this run with --l3-seed {seed})")

    # Group the flat declared-test list by applug source so each applug gets one
    # fresh boot covering exactly its own tests.
    by_source: dict = {}
    for decl in manifest.tests:
        by_source.setdefault(decl.source, []).append(decl)

    requests = _require_requests()
    results = []  # list of (source, test_id, ok: bool, error: str | None)

    for source in sorted(by_source):
        decls = by_source[source]
        applug_seed = _derive_seed(seed, source)
        print(f"  L3 — applug {source!r}: {len(decls)} functional test(s); "
              f"booting a FRESH app in a clean HOME (order seed {applug_seed})")
        home = tempfile.mkdtemp(prefix=f"mm-verify-l3-{source}-")
        app = BootedApp(exe, home, port, timeout)
        applug_failed = False
        try:
            with app:
                # A NEW authenticated session is minted PER boot — never reused
                # across applugs/boots.
                session = _login(requests, app.base)
                # This applug's tests run in RANDOMIZED order; each ARRANGES and
                # RESETS its own state (setup/teardown). No within-applug reboot.
                applug_results = _run_applug_tests(
                    decls, source_root, app.base, session, applug_seed
                )
                for test_id, ok, error in applug_results:
                    results.append((source, test_id, ok, error))
                    if not ok:
                        applug_failed = True
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


def _load_i18n_checker(source_root: str):
    """Load matika's CANONICAL i18n-completeness checker from the pinned source.

    matika owns the one implementation (``src/matika/core/i18n_completeness.py``);
    the gate INVOKES it — it never reimplements the merge/scan logic (rule 18). The
    module is stdlib-only and self-contained, so we exec it by file path without
    importing the matika package or installing its dependencies.
    """
    path = os.path.join(
        source_root, "src", "matika", "core", "i18n_completeness.py"
    )
    if not os.path.exists(path):
        raise FrozenAppError(
            "i18n-completeness checker not found in pinned source "
            f"(expected canonical module at {path}); cannot verify translations"
        )
    name = "matika_i18n_completeness"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so the module's @dataclass definitions can resolve their
    # own annotations namespace via sys.modules[cls.__module__] (the module uses
    # ``from __future__ import annotations``; without this dataclasses raises).
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_i18n_completeness(source_root) -> None:
    """STRICT i18n-completeness gate over the assembled product (source-clone arm).

    Verifies every i18n key referenced anywhere in matika core and each bundled
    applug resolves in EVERY shipped locale, and that all locales are at parity —
    against the FROZEN, pinned source tree ``ahimsa`` assembled. A miss FAILS the
    build, naming the key, locale and file (rule 18). Like the screen-manifest
    checks this is the source-clone arm: with no ``--source-root`` there is no tree
    to scan, so it is skipped (the property is source-derived, not artifact-derived).
    """
    if not source_root:
        print("  · no --source-root given: i18n-completeness gate SKIPPED for this "
              "run (source-clone arm only; the property is verified from the pinned "
              "source tree, which the install-verify A2 arm does not carry).")
        return
    checker = _load_i18n_checker(source_root)
    components = checker.frozen_tree_components(source_root)
    # Refuse to pass vacuously (rule 22): the assembled product MUST ship matika
    # core translations. A run that found no core catalogs scanned nothing, so a
    # green result would be meaningless — fail the build instead.
    core = next((c for c in components if getattr(c, "is_core", False)), None)
    if core is None or not checker.discover_catalogs(core.locales_dir):
        raise FrozenAppError(
            f"i18n-completeness gate found no matika-core locale catalogs under "
            f"{source_root}; the assembled product must ship core translations. "
            f"Refusing to pass vacuously (rule 22)."
        )
    violations = checker.analyze(components)
    if violations:
        raise FrozenAppError(
            "i18n-completeness gate FAILED: a referenced translated string is "
            "missing from a shipped locale. Every referenced i18n key must resolve "
            "in every locale, and all locales must be at parity:\n"
            + "\n".join(v.render() for v in violations)
        )
    names = ", ".join(c.name for c in components)
    print(f"  · i18n-completeness gate PASS: {len(components)} component(s) "
          f"[{names}] — all referenced keys resolve in every shipped locale")


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
    ap.add_argument("--l3-seed", type=int, default=None,
                    help="replay seed for the Layer-3 randomized per-applug test "
                         "ordering. When omitted, a base seed is generated and "
                         "LOGGED ('L3 random seed: <seed>') so a failing run can be "
                         "reproduced verbatim by passing that value back here.")
    ap.add_argument("--matika-tag", default=None,
                    help="Matika release tag (e.g. v0.0.4-rc.11) — used to verify "
                         "/healthz version matches")
    args = ap.parse_args()

    exe = os.path.abspath(args.exe)
    if not os.path.exists(exe):
        print(f"::error::frozen executable not found: {exe}")
        return 1

    matika_tag = args.matika_tag

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
        run_i18n_completeness(args.source_root)
        if args.scenario == "fresh":
            if args.source_root:
                assert_plugin_payload_clean(Path(args.source_root))
            scenario_fresh(exe, args.port, args.timeout, args.browser, manifest,
                           matika_tag=matika_tag)
        else:
            scenario_upgrade(exe, args.port, args.timeout, args.browser, manifest,
                             matika_tag=matika_tag)
        # Layer-3 functional tests run AFTER the single-boot tier-a/b block has
        # closed (so the port is free), on BOTH scenarios (rule 22, both install
        # paths — CI invokes this once per scenario, so L3 runs on each path).
        if l3_enabled:
            if not run_l3_functional(exe, args.port, args.timeout,
                                     args.source_root, seed=args.l3_seed):
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
