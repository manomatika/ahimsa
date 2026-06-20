#!/usr/bin/env python3
"""browser_verify.py — TIER (b) headless-browser / DOM checks (Playwright).

Drives a real headless Chromium against the running frozen product to prove the
EyeRate UI actually WORKS end-to-end through the DOM — the layer the HTTP checks
in frozen_verify.py cannot see (rendered templates, JS fetch wiring, the lookup
dialog populating, a provider error surfacing visibly).

Checks (against an already-running server at *base*):
  1. log in through the browser (clearing the forced first-run password change)
  2. EyeRate admin → the real "Financial Data Provider" form is visible, the
     stale "coming soon" text is NOT
  3. Securities → New → Lookup → type VOO → the dialog CALLS the endpoint and
     POPULATES results; selecting one fills the symbol field
  4. a forced provider failure surfaces a VISIBLE error in the dialog (Task-4),
     not a silent empty list

Raises RuntimeError (which the caller turns into a build failure) on any failure.
Importable: frozen_verify.run_tier_b() calls run_browser_checks().
"""

from __future__ import annotations

import contextlib


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


def _check_admin_form(page, base) -> None:
    page.goto(f"{base}/eyerate/admin", wait_until="domcontentloaded")
    body = page.inner_text("body")
    if "Financial Data Provider" not in body:
        raise BrowserCheckError(
            "EyeRate admin DOM is missing the 'Financial Data Provider' form. "
            f"Body head:\n{body[:500]}"
        )
    if "coming soon" in body.lower():
        raise BrowserCheckError(
            "EyeRate admin DOM still shows stale 'coming soon'. "
            f"Body head:\n{body[:500]}"
        )
    print("    ✓ [browser] admin form visible, no 'coming soon'")


def _open_lookup(page, base) -> None:
    page.goto(f"{base}/eyerate/securities", wait_until="domcontentloaded")
    # Enter "new" mode so the edit panel (and its Lookup button) is shown.
    page.click("#btn-new")
    # The .btn-lookup button is hidden until edit mode; wait for it to show.
    page.wait_for_selector(".btn-lookup", state="visible", timeout=10_000)
    page.click(".btn-lookup")
    page.wait_for_selector("#lookup-modal", state="visible", timeout=10_000)


def _search_in_dialog(page, query) -> None:
    page.fill("#lookup-search-input", query)
    page.click("#btn-lookup-search")


def _check_lookup_populates_and_fills(page, base) -> None:
    _open_lookup(page, base)
    _search_in_dialog(page, "VOO")
    # Wait for at least one real result row to appear in the results body.
    page.wait_for_function(
        """() => {
            const tb = document.querySelector('#lookup-results-list');
            if (!tb) return false;
            const rows = tb.querySelectorAll('tr');
            if (rows.length === 0) return false;
            // Exclude the 'Error:' / 'no results' placeholder rows.
            const txt = tb.innerText.toLowerCase();
            return !txt.includes('error:') && txt.includes('voo');
        }""",
        timeout=30_000,
    )
    print("    ✓ [browser] lookup dialog populated real VOO results")

    # Select the first result row (single-select), enabling OK, then confirm.
    row = page.query_selector("#lookup-results-list tr")
    if row is None:
        raise BrowserCheckError("no result row to select in lookup dialog")
    checkbox = row.query_selector(".row-check")
    (checkbox or row).click()
    page.wait_for_selector("#btn-ok-lookup:not([disabled])", timeout=10_000)
    page.click("#btn-ok-lookup")
    # The selection must populate the symbol field via /securities/lookup.
    page.wait_for_function(
        """() => {
            const f = document.querySelector('#field-symbol');
            return f && f.value && f.value.toUpperCase().includes('VOO');
        }""",
        timeout=30_000,
    )
    print("    ✓ [browser] selecting a result filled #field-symbol with VOO")


def _set_provider_finnhub_no_key(page, base) -> None:
    page.goto(f"{base}/eyerate/admin", wait_until="domcontentloaded")
    page.check('input[name="endpoint"][value="finnhub"]')
    with contextlib.suppress(Exception):
        page.fill('input[name="api_key"]', "")
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.click('button[type="submit"], input[type="submit"]')


def _set_provider_yahoo(page, base) -> None:
    page.goto(f"{base}/eyerate/admin", wait_until="domcontentloaded")
    with contextlib.suppress(Exception):
        page.check('input[name="endpoint"][value="yahoo"]')
        with page.expect_navigation(wait_until="domcontentloaded"):
            page.click('button[type="submit"], input[type="submit"]')


def _check_provider_error_visible(page, base) -> None:
    _set_provider_finnhub_no_key(page, base)
    try:
        _open_lookup(page, base)
        _search_in_dialog(page, "VOO")
        page.wait_for_function(
            """() => {
                const tb = document.querySelector('#lookup-results-list');
                return tb && tb.innerText.toLowerCase().includes('error:');
            }""",
            timeout=30_000,
        )
        print("    ✓ [browser] forced provider failure shows a VISIBLE error in the dialog")
    finally:
        _set_provider_yahoo(page, base)


def run_browser_checks(base, admin_email, admin_password, new_password) -> None:
    sync_playwright = _import_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(30_000)
            _login(page, base, admin_email, admin_password, new_password)
            _check_admin_form(page, base)
            _check_lookup_populates_and_fills(page, base)
            _check_provider_error_visible(page, base)
        finally:
            browser.close()


if __name__ == "__main__":  # pragma: no cover - manual local use
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--admin-email", default="admin@matika.local")
    ap.add_argument("--admin-password", default="adminpassword")
    ap.add_argument("--new-password", default="Verify-Pass-123")
    a = ap.parse_args()
    run_browser_checks(a.base, a.admin_email, a.admin_password, a.new_password)
    print("browser checks: PASS")
