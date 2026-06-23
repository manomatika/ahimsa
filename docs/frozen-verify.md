> Part of [CLAUDE.md](../CLAUDE.md) — see the main file for orientation.

## Frozen-App Feature Verification (the product QA gate, in CI)

This is the mechanism behind standing rule 22's "exercised against the frozen,
pinned artifact on BOTH install paths." Three scripts, run by every `build.yml`
build job after the freeze:

- **`scripts/smoke_launch.py`** — boots the frozen exe, waits for boot markers,
  asserts first-run schema init (`create_all` + `alembic stamp head`) and that
  the `eyerate` applug loaded and the app serves. Forces UTF-8 stdout so
  non-ASCII log lines don't break the Windows runner.
- **`scripts/frozen_verify.py`** — **tier-a** authenticated-HTTP checks against
  the booted artifact in a throwaway `HOME`. It logs in **password-agnostically**
  (accepts the seeded default OR the rotated password, and performs the
  first-login `/change-password` rotation), then asserts: the `/eyerate/admin`
  page shows the **"Financial Data Provider"** form and **no "coming soon"**
  (the stale-plugin tell); a `VOO` search returns real results; and a forced
  keyless `finnhub` provider yields **HTTP 502 with a `detail` body** — never a
  silent HTTP 200 empty. Runs two scenarios: `--scenario fresh` and
  `--scenario upgrade` (the upgrade path seeds a stale `eyerate` — old version,
  `.matika_plugin_install.json` removed, a `USER_NOTES.txt` added — then asserts
  the launcher logged a refresh, dropped the stale template, and **preserved**
  the user file).
- **`scripts/browser_verify.py`** — **tier-b** headless-Chromium (Playwright)
  checks, invoked when `frozen_verify.py` is run with `--browser`. Mirrors the
  password-agnostic login (tier-a runs first and rotates the password), then
  drives the real UI: the admin form renders the provider control with no
  "coming soon"; the Securities lookup modal populates VOO rows (and not an
  `error:` row) and fills `#field-symbol`; and a forced keyless `finnhub`
  surfaces a visible `error:` in the results list.

Together these turn product-behavior regressions (stale plugin code after an
upgrade; silent-empty provider failures) into hard CI failures on the frozen
artifact, on both fresh-install and upgrade-over-stale paths.
