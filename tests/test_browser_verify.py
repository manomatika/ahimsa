"""Unit tests for scripts/browser_verify.py — the tier-(b) DOM checks.

The headline test here is the regression for the tier-b ``assert_value`` race
(manomatika/ahimsa A5 / #11 dispatch-proof). A declared screen step can assert
that an input holds a value that the page only fills *asynchronously* — eyerate's
``admin-securities.js`` populates ``#field-symbol`` only after the awaited
``/eyerate/securities/lookup`` round-trip resolves. The original ``_assert_value``
read ``input_value`` exactly once, immediately after the element attached, so it
raced the fill and deterministically saw ``''`` — a spurious gate RED that blocks
the whole product matrix. The fix polls the live value (web-first semantics) like
``_assert_present`` already does.

These tests drive ``BrowserScreenExecutor._assert_value`` against a fake page that
models the async fill, so they run with no real Playwright/Chromium install. The
``test_polls_until_async_fill`` case FAILS against the old immediate-read code and
PASSES against the polling fix (rule 22).
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_SCRIPT = _SCRIPTS_DIR / "browser_verify.py"
# scripts/ holds standalone sibling modules (screen_manifest, browser_verify) the
# verify harness imports by name; make them importable in the test process too.
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


@pytest.fixture(scope="module")
def bv():
    spec = importlib.util.spec_from_file_location("browser_verify", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeTimeout(Exception):
    """Stand-in for playwright.sync_api.TimeoutError (not installed in dev env)."""


class _FakePage:
    """Minimal Playwright-page stand-in for ``_assert_value`` polling tests.

    Models an asynchronously-filled input: ``input_value`` returns ``''`` for the
    first ``fill_after`` reads, then ``final_value`` — exactly the race where
    ``admin-securities.js`` fills ``#field-symbol`` only after an awaited
    ``/lookup`` round-trip completes. ``fill_after=0`` means the value is present
    on the very first read (the synchronous fast path).
    """

    def __init__(self, final_value="VOO", fill_after=0, attached=True):
        self.final_value = final_value
        self.fill_after = fill_after
        self.attached = attached
        self.reads = 0
        self.sleeps = 0

    def wait_for_selector(self, selector, state=None, timeout=None):
        if not self.attached:
            raise _FakeTimeout(f"{selector!r} never attached")
        return object()

    def input_value(self, selector):
        self.reads += 1
        if self.reads > self.fill_after:
            return self.final_value
        return ""

    def wait_for_timeout(self, ms):
        # Real Playwright sleeps in the browser; here we only need to avoid a hot
        # spin in the never-match case and to count that polling happened.
        self.sleeps += 1
        time.sleep(0.005)


def _executor(bv, page):
    ex = bv.BrowserScreenExecutor(page, "http://127.0.0.1:8000",
                                  timeout_error=_FakeTimeout)
    ex._route = "/eyerate/securities"
    return ex


def test_polls_until_async_fill(bv):
    """REGRESSION: value arrives only after several reads — must still pass.

    Old immediate-read code reads once (reads == 1), sees '', and raises. The
    polling fix keeps reading until the awaited fill lands.
    """
    page = _FakePage(final_value="VOO", fill_after=3)
    _executor(bv, page)._assert_value("#field-symbol", "VOO")
    assert page.reads > 1, "must have polled more than once for the async fill"


def test_immediate_match_fast_path(bv):
    """Value present on the first read passes without extra polling."""
    page = _FakePage(final_value="VOO", fill_after=0)
    _executor(bv, page)._assert_value("#field-symbol", "VOO")
    assert page.reads == 1
    assert page.sleeps == 0


def test_case_insensitive_substring_preserved(bv):
    """Contains + case-insensitive semantics are preserved by the fix."""
    page = _FakePage(final_value="my-VOO-holding", fill_after=1)
    _executor(bv, page)._assert_value("#field-symbol", "voo")


def test_never_matches_fails_loud(bv, monkeypatch):
    """A value that never matches fails loud with selector + actual + expected."""
    monkeypatch.setattr(bv, "_MARKER_TIMEOUT_MS", 150)
    page = _FakePage(final_value="SPY", fill_after=0)
    with pytest.raises(bv.BrowserCheckError) as exc:
        _executor(bv, page)._assert_value("#field-symbol", "VOO")
    msg = str(exc.value)
    assert "#field-symbol" in msg
    assert "SPY" in msg          # actual surfaced
    assert "VOO" in msg          # expected surfaced
    assert page.reads > 1, "must have polled before giving up"


def test_selector_not_found_is_distinct_failure(bv):
    """An absent field fails as 'not found', not as a value mismatch."""
    page = _FakePage(attached=False)
    with pytest.raises(bv.BrowserCheckError) as exc:
        _executor(bv, page)._assert_value("#field-symbol", "VOO")
    assert "not found" in str(exc.value)
