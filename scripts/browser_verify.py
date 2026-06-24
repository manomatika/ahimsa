#!/usr/bin/env python3
"""browser_verify.py — TIER (b) headless-browser / DOM checks (Playwright).

Drives a real headless Chromium against the running frozen product to prove each
declared screen actually RENDERS in the DOM — the layer the HTTP checks in
frozen_verify.py cannot see (rendered templates, JS-driven elements, markers
that only exist once the page is live).

This tier is MANIFEST-DRIVEN and GENERIC: the screens it visits, the steps it
runs, and the markers it asserts all come from the assembled ``*_screens.json``
data (see scripts/screen_manifest.py). No component name, route, or marker is
hardcoded here. Driving a screen = run its declared steps, then assert its
markers are present in the live DOM. A stale/wrong render (e.g. the historical
"coming soon" eyerate stub) fails because NONE of the real markers are found.

Step verbs (schema from manomatika/matika#84): navigate, fill, click, wait_for,
assert_present, assert_absent, assert_value.

Raises BrowserCheckError (which the caller turns into a build failure) on any
failure. Importable: frozen_verify.run_tier_b() calls run_browser_checks().
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen_manifest  # noqa: E402  (local sibling module)

# How long to wait for a marker / element before deciding it is absent.
_MARKER_TIMEOUT_MS = 8_000


class BrowserCheckError(RuntimeError):
    pass


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError as exc:
        raise BrowserCheckError(
            "playwright is not installed/available — install it and its browser "
            "(pip install playwright && python -m playwright install --with-deps chromium)"
        ) from exc
    from playwright.sync_api import sync_playwright
    return sync_playwright


def _submit_login(page, base, email, password) -> None:
    page.goto(f"{base}/login", wait_until="domcontentloaded")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("domcontentloaded")


def _login(page, base, admin_email, admin_password, new_password) -> None:
    """Password-agnostic browser login.

    Tier (a) runs first against the same server and rotates the admin password,
    so the browser login must accept either the default (first login of the run)
    or the already-rotated password. Mirrors frozen_verify._login.
    """
    _submit_login(page, base, admin_email, admin_password)
    if page.url.rstrip("/").endswith("/login"):
        # Default password rejected (already rotated) — use the new one.
        _submit_login(page, base, admin_email, new_password)
    if "/change-password" in page.url:
        page.fill('input[name="new_password"]', new_password)
        page.fill('input[name="confirm_password"]', new_password)
        page.click('button[type="submit"], input[type="submit"]')
        page.wait_for_load_state("domcontentloaded")
    if page.url.rstrip("/").endswith("/login"):
        raise BrowserCheckError(
            "browser login failed with both the default and the rotated password"
        )


class BrowserScreenExecutor(screen_manifest.ScreenExecutor):
    """Tier-(b) executor: drives a declared screen through the live DOM.

    Implements every schema verb against Playwright. ``assert_markers`` proves
    the screen RENDERED: a screen is considered present if AT LEAST ONE of its
    declared markers is found in the DOM — they read as defensive alternative
    selectors for the same screen (e.g. an id OR an ``action=`` form selector),
    and a wholly-wrong render matches none of them. (This any-present semantics
    is the gate MECHANISM A1 defines; the schema canon in matika#84 only requires
    that ``markers`` be present, leaving verification semantics to the gate.)
    """

    def __init__(self, page, base: str):
        self.page = page
        self.base = base
        self._route = "(none navigated)"
        from playwright.sync_api import TimeoutError as _PWTimeout
        self._timeout_error = _PWTimeout

    def run_step(self, step: screen_manifest.Step) -> None:
        verb, target, value = step.verb, step.target, step.value
        if verb == "navigate":
            self._route = target
            self.page.goto(self.base + (target or ""), wait_until="domcontentloaded")
        elif verb == "fill":
            self.page.fill(target, value or "")
        elif verb == "click":
            self.page.click(target)
        elif verb == "wait_for":
            self.page.wait_for_selector(target, state="visible",
                                        timeout=_MARKER_TIMEOUT_MS)
        elif verb == "assert_present":
            self._assert_present(target)
        elif verb == "assert_absent":
            self._assert_absent(target)
        elif verb == "assert_value":
            self._assert_value(target, value)
        else:  # pragma: no cover - loader already rejects unknown verbs
            raise BrowserCheckError(f"unknown verb {verb!r} on {self._route}")

    def _assert_present(self, selector: str) -> None:
        try:
            self.page.wait_for_selector(selector, state="visible",
                                        timeout=_MARKER_TIMEOUT_MS)
        except self._timeout_error:
            raise BrowserCheckError(
                f"assert_present failed on {self._route}: selector {selector!r} "
                f"not visible"
            )
        print(f"      · [browser] assert_present {selector!r} OK")

    def _assert_absent(self, selector: str) -> None:
        if self.page.query_selector(selector) is not None:
            raise BrowserCheckError(
                f"assert_absent failed on {self._route}: selector {selector!r} "
                f"is present but should be absent"
            )
        print(f"      · [browser] assert_absent {selector!r} OK")

    def _assert_value(self, selector: str, expected) -> None:
        try:
            self.page.wait_for_selector(selector, state="attached",
                                        timeout=_MARKER_TIMEOUT_MS)
            actual = self.page.input_value(selector)
        except self._timeout_error:
            raise BrowserCheckError(
                f"assert_value failed on {self._route}: selector {selector!r} "
                f"not found"
            )
        if (expected or "").upper() not in (actual or "").upper():
            raise BrowserCheckError(
                f"assert_value failed on {self._route}: selector {selector!r} "
                f"value {actual!r} does not contain expected {expected!r}"
            )
        print(f"      · [browser] assert_value {selector!r} contains {expected!r} OK")

    def assert_markers(self, markers) -> None:
        found = None
        for marker in markers:
            try:
                self.page.wait_for_selector(marker, state="attached",
                                            timeout=_MARKER_TIMEOUT_MS)
                found = marker
                break
            except self._timeout_error:
                continue
        if found is None:
            body = ""
            try:
                body = self.page.inner_text("body")[:500]
            except Exception:  # noqa: BLE001 - best-effort context for the failure
                pass
            raise BrowserCheckError(
                f"screen at {self._route}: NONE of the declared markers "
                f"{list(markers)} were found in the DOM — the page may be a "
                f"stale/wrong render. Body head:\n{body}"
            )
        print(f"      · [browser] marker present: {found!r}")


def run_browser_checks(base, manifest, admin_email, admin_password,
                       new_password) -> None:
    """Drive every declared screen in the manifest through the live DOM."""
    sync_playwright = _import_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(30_000)
            _login(page, base, admin_email, admin_password, new_password)
            executor = BrowserScreenExecutor(page, base)
            for screen in manifest.screens:
                print(f"    · [{screen.source}] {screen.screen_id} -> {screen.route}")
                screen_manifest.drive_screen(screen, executor)
            print(f"    [browser] drove {len(manifest.screens)} declared screen(s)")
        finally:
            browser.close()


if __name__ == "__main__":  # pragma: no cover - manual local use
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--source-root", required=True,
                    help="root of the pinned source clones holding *_screens.json")
    ap.add_argument("--admin-email", default="admin@matika.local")
    ap.add_argument("--admin-password", default="adminpassword")
    ap.add_argument("--new-password", default="Verify-Pass-123")
    a = ap.parse_args()
    manifest = screen_manifest.load_screen_manifest(a.source_root)
    run_browser_checks(a.base, manifest, a.admin_email, a.admin_password,
                       a.new_password)
    print("browser checks: PASS")
