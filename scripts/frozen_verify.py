#!/usr/bin/env python3
"""frozen_verify.py — prove the FROZEN product actually WORKS, on both install paths.

The systemic leak (standing rule 22): tests ran against repo source, never the
frozen pinned artifact, and the smoke-launch gate only checked that the app
BOOTS — never that its features WORK, and never the UPGRADE path. That let the
"EyeRate admin shows *coming soon* / lookup dead" regression reach the user's
machine: a stale eyerate plugin in ~/matika/plugins/ survived every reinstall
and the boot smoke never exercised it.

This script closes that gap. It boots the FROZEN executable in a clean,
throwaway HOME and runs feature-level checks against the *running* product:

  TIER (a) — authenticated HTTP / route-content checks (this file):
    * log in as the seeded admin (clearing the forced first-run password change)
    * GET /eyerate/admin  → assert the real "Financial Data Provider" form is
      present AND the stale "coming soon" text is absent
    * GET /eyerate/securities/search?q=VOO → assert real results come back
    * force a provider failure → assert it surfaces as a VISIBLE error (HTTP 502
      with a detail body, Task-4), NOT a silent empty list

  TIER (b) — headless-browser / DOM checks (browser_verify.py, opt-in --browser):
    driven through Playwright against the same running server.

Two SCENARIOS, both required:

  --scenario fresh    a first-time install (pristine HOME) — plugin extracted,
                      admin form present, lookup works.

  --scenario upgrade  an upgrade OVER a prior install. The script boots once to
                      do the real first run, then mutates ~/matika/plugins/eyerate
                      into the exact STALE state seen on the user's machine (old
                      "coming soon" template, older applug version, no install
                      marker, plus a user-data file), reboots, and asserts the
                      launcher REFRESHED the stale plugin to the bundled version
                      while PRESERVING the user-data file — then runs the same
                      tier-a (and tier-b) feature checks.

Any failed assertion fails the build, dumping ~/matika/logs and the process
output so the reason is visible directly in the CI job log.

Usage:
    python frozen_verify.py --exe <frozen-binary> --scenario fresh|upgrade \
        [--port 8000] [--timeout 90] [--browser]
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
    """Return an authenticated session, clearing the forced first-run change."""
    s = requests.Session()
    r = s.post(
        f"{base}/login",
        data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        allow_redirects=False,
        timeout=15,
    )
    if r.status_code not in (302, 303):
        raise FrozenAppError(
            f"login POST returned {r.status_code} (expected a redirect); "
            f"body head: {r.text[:200]!r}"
        )
    location = r.headers.get("location", "")
    if "/change-password" in location:
        # First-run admin must set a new password before any route is usable.
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
    # Confirm we are actually authenticated now.
    home = s.get(f"{base}/", allow_redirects=False, timeout=15)
    if home.status_code not in (200, 302, 303):
        raise FrozenAppError(f"post-login GET / returned {home.status_code}")
    return s


def _extract_csrf(html: str) -> str | None:
    import re
    m = re.search(r'name="csrf_token"[^>]*value="([^"]*)"', html)
    if not m:
        m = re.search(r'value="([^"]*)"[^>]*name="csrf_token"', html)
    return m.group(1) if m else None


def check_admin_form(requests, s, base: str) -> None:
    r = s.get(f"{base}/eyerate/admin", timeout=15)
    if r.status_code != 200:
        raise FrozenAppError(
            f"GET /eyerate/admin returned {r.status_code} (expected 200); "
            f"body head: {r.text[:300]!r}"
        )
    text = r.text
    if "Financial Data Provider" not in text:
        raise FrozenAppError(
            "EyeRate admin page is MISSING the 'Financial Data Provider' form — "
            "the stale-plugin bug is present. Body head:\n" + text[:500]
        )
    if "coming soon" in text.lower():
        raise FrozenAppError(
            "EyeRate admin page still shows STALE 'coming soon' text — the "
            "bundled plugin was not refreshed. Body head:\n" + text[:500]
        )
    print('    ✓ /eyerate/admin: real "Financial Data Provider" form present, '
          'no "coming soon"')


def check_voo_lookup(requests, s, base: str) -> None:
    last_err = None
    for attempt in range(1, 4):
        try:
            r = s.get(
                f"{base}/eyerate/securities/search",
                params={"q": "VOO"}, timeout=30,
            )
        except Exception as exc:  # network hiccup against the live provider
            last_err = f"request error: {exc}"
            time.sleep(2.0)
            continue
        if r.status_code != 200:
            last_err = f"HTTP {r.status_code}; body: {r.text[:300]!r}"
            time.sleep(2.0)
            continue
        try:
            data = r.json()
        except ValueError:
            last_err = f"non-JSON body: {r.text[:300]!r}"
            break
        if not isinstance(data, list) or not data:
            last_err = f"empty/again non-list results: {data!r}"
            time.sleep(2.0)
            continue
        symbols = [str(d.get("symbol", "")).upper() for d in data if isinstance(d, dict)]
        if any("VOO" in sym for sym in symbols):
            print(f"    ✓ /securities/search?q=VOO: {len(data)} real result(s), "
                  f"e.g. {symbols[:3]}")
            return
        last_err = f"results present but none match VOO: {symbols[:5]}"
        time.sleep(2.0)
    raise FrozenAppError(
        f"securities VOO lookup did not return real results after retries: {last_err}"
    )


def check_provider_error_visible(requests, s, base: str) -> None:
    """Force a provider failure and assert it surfaces (502 + detail), not [].

    Switching the active provider to one that requires an API key, with no key
    configured, makes the next search raise ProviderError. Task-4's contract is
    that this surfaces as an explicit error (HTTP 502 with a detail body), never
    a silent empty list that the UI would render as "no results".
    """
    # Read the admin form to obtain the CSRF token for the settings POST.
    admin = s.get(f"{base}/eyerate/admin", timeout=15)
    csrf = _extract_csrf(admin.text)
    if not csrf:
        raise FrozenAppError("could not extract csrf_token from /eyerate/admin")
    payload = {"endpoint": "finnhub", "api_key": "", "csrf_token": csrf}
    set_resp = s.post(f"{base}/eyerate/admin", data=payload,
                      allow_redirects=False, timeout=15)
    if set_resp.status_code not in (200, 302, 303):
        raise FrozenAppError(
            f"setting provider=finnhub returned {set_resp.status_code}"
        )
    try:
        r = s.get(f"{base}/eyerate/securities/search",
                  params={"q": "VOO"}, timeout=30)
        if r.status_code == 200:
            body = r.json()
            raise FrozenAppError(
                "forced provider failure returned HTTP 200 (silent) instead of "
                f"a visible error — body: {body!r}"
            )
        if r.status_code != 502:
            raise FrozenAppError(
                f"forced provider failure returned HTTP {r.status_code} "
                f"(expected 502); body: {r.text[:300]!r}"
            )
        detail = r.json().get("detail", "")
        if not detail:
            raise FrozenAppError(
                f"502 response had no 'detail' message: {r.text[:300]!r}"
            )
        print(f'    ✓ forced provider failure surfaces HTTP 502 + detail: "{detail}"')
    finally:
        # Restore the default provider so any later checks behave normally.
        admin2 = s.get(f"{base}/eyerate/admin", timeout=15)
        csrf2 = _extract_csrf(admin2.text) or csrf
        with contextlib.suppress(Exception):
            s.post(f"{base}/eyerate/admin",
                   data={"endpoint": "yahoo", "api_key": "", "csrf_token": csrf2},
                   allow_redirects=False, timeout=15)


def run_tier_a(base: str) -> None:
    print("  TIER (a) — authenticated HTTP / route-content checks")
    requests = _require_requests()
    s = _login(requests, base)
    check_admin_form(requests, s, base)
    check_voo_lookup(requests, s, base)
    check_provider_error_visible(requests, s, base)
    print("  TIER (a): PASS")


def run_tier_b(base: str) -> None:
    print("  TIER (b) — headless-browser / DOM checks (Playwright)")
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import browser_verify  # local module
    browser_verify.run_browser_checks(
        base, admin_email=ADMIN_EMAIL, admin_password=ADMIN_PASSWORD,
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

def _run_checks(app: BootedApp, browser: bool) -> None:
    run_tier_a(app.base)
    if browser:
        run_tier_b(app.base)


def scenario_fresh(exe: str, port: int, timeout: int, browser: bool) -> None:
    print("=== SCENARIO: fresh (first-time install) ===")
    home = tempfile.mkdtemp(prefix="mm-verify-fresh-")
    try:
        with BootedApp(exe, home, port, timeout) as app:
            try:
                _run_checks(app, browser)
            except Exception:
                _dump_failure(app)
                raise
    finally:
        shutil.rmtree(home, ignore_errors=True)
    print("=== fresh: PASS ===\n")


def scenario_upgrade(exe: str, port: int, timeout: int, browser: bool) -> None:
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
                _run_checks(app, browser)
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


def main() -> int:
    _reconfigure_stdio()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exe", required=True, help="frozen executable to launch")
    ap.add_argument("--scenario", required=True, choices=["fresh", "upgrade"])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--browser", action="store_true",
                    help="also run tier (b) headless-browser checks (Playwright)")
    args = ap.parse_args()

    exe = os.path.abspath(args.exe)
    if not os.path.exists(exe):
        print(f"::error::frozen executable not found: {exe}")
        return 1

    try:
        if args.scenario == "fresh":
            scenario_fresh(exe, args.port, args.timeout, args.browser)
        else:
            scenario_upgrade(exe, args.port, args.timeout, args.browser)
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
