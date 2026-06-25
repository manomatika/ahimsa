> Part of [CLAUDE.md](../CLAUDE.md) — see the main file for orientation.

## Frozen-App Feature Verification (the product QA gate, in CI)

This is the mechanism behind standing rule 22's "exercised against the frozen,
pinned artifact on BOTH install paths." It is **generic and manifest-driven**:
the gate names no component, route, marker, or applug. What it drives is read
from the declarative data each component ships (matika core + every applug). The
gate is **pure build automation** — there is no sandbox, no isolation, and no
trust dimension (see CLAUDE.md *AppLug trust, test posture & the three-layer
testing model*).

**Status: BUILT, not yet PROVEN.** The gate is implemented, unit-covered, and
wired into `build.yml` (L1 in component suites + L2 structural + L3 functional, on
both scenarios and both install paths). It has **not yet** been driven red→green
against a live frozen artifact on a real dispatch — that end-to-end proof is A5
(pending). Read the below as the built mechanism, not as a proven live run.

Three scripts, run by every `build.yml` build job after the freeze (and again by
the install-verify jobs against the installed artifact):

### `scripts/smoke_launch.py` — boot proof

Boots the frozen exe in a throwaway `HOME`, waits for the boot markers, and
asserts first-run schema init (`create_all` + `alembic stamp head`), that the
expected applug loaded (`--expect-plugin <name>`, `eyerate` for the reference
recipe), and that the server binds and serves. Forces UTF-8 stdout so non-ASCII
log lines don't break the Windows runner. This proves the app **starts** — not
that its features work; that is the job of the next two scripts.

### `scripts/frozen_verify.py` — the gate driver (L2 + L3)

Boots the frozen executable in a clean throwaway `HOME` and runs the
manifest-driven checks against the *running* product. The set of screens it
drives, the steps it runs, and the markers it asserts are NOT hardcoded — they
come from the assembled `*_screens.json` (and, for L3, `*_functional_tests.json`)
each component ships, discovered via `scripts/screen_manifest.py`.

It logs in **password-agnostically**: the seeded admin starts with the default
password and `force_password_change`, so the first login rotates it; later
logins accept either the default (first login of the run) or the rotated value,
decoupling tier/scenario order.

**Layer 2 — structural, single-boot per scenario:**

- **Tier (a) — authenticated HTTP route liveness.** For every declared `screen`,
  perform its `navigate` step over an authenticated GET and assert the route is
  alive, authorized, and returns a non-empty HTML body (catches a removed/renamed
  screen → 404, a crash → 5xx, an auth-gate misfire → 4xx). DOM-only verbs and
  CSS-selector markers are deferred to tier (b).
- **Tier (b) — headless-browser / DOM (`browser_verify.py`, opt-in `--browser`).**
  Drives each declared screen through Playwright Chromium and asserts its markers
  in the live DOM. A screen is considered present if **at least one** of its
  declared markers is found (the markers read as defensive alternative selectors
  for the same screen); a wholly-wrong render (e.g. a stale "coming soon" stub)
  matches none and fails.

Both tiers share one boot per scenario. Two scenarios, both required:

- `--scenario fresh` — a first-time install (pristine `HOME`): plugins extracted,
  every declared screen drives clean.
- `--scenario upgrade` — an upgrade **over a prior, stale install**. Boots once
  for the real first run, then mutates `~/matika/plugins/eyerate` into the exact
  stale state seen on the user's machine (old "coming soon" template, older applug
  version, `.matika_plugin_install.json` removed, plus a `USER_NOTES.txt`),
  reboots, and asserts the launcher **refreshed** the stale plugin to the bundled
  version while **preserving** the user-data file — then runs the same
  manifest-driven tier-a (and tier-b) checks. This stale-state seeding is the
  retained escaped-bug regression fixture (the "admin coming soon / lookup dead"
  regression that reached the user).

**Layer 3 — applug-authored functional tests, generically invoked
(`--functional`, or implied by `--source-root`):**

WHO AUTHORS the tests (each applug, via its `*_functional_tests.json` declaration
+ named module) is separate from WHO INVOKES them (this generic gate). After the
single-boot tier-a/b block has closed (so the port is free), the gate:

1. discovers every applug's declared functional tests from the pinned source
   clones (`screen_manifest.load_functional_test_manifest`),
2. groups them by applug, and
3. for **each** applug, boots a **fresh** app in a **new clean `HOME`**, mints a
   **new** authenticated session for that boot (never reused across boots), runs
   only that applug's declared tests in a **randomized (seeded) order** via
   `screen_manifest.invoke_functional_test` (which imports the declared module
   and calls the declared function with `base_url` + `session`), then tears the
   boot down before the next applug (**reboot-per-applug**).

**Self-arrange / self-reset (the reset discipline).** Each test **arranges** its
own preconditions (declared `setup`) and **resets** what it mutated back to
known-initial state (declared `teardown`, run with guaranteed-run try/finally
semantics — it runs even when the test body raises). The functional-test schema
is **version 1.0**, with `setup`/`teardown` as **optional** fields (same module,
same `(base_url, session)` signature as the test body). The **randomized order is
the verifier** that this reset discipline actually holds — order-dependent state
leakage surfaces as a failure rather than passing by luck. A test that cannot
reset its own mutation is a **defect**, never rebooted-around: the reboot is
**coarse containment BETWEEN applugs only** (independently-authored trust
domains), **not** a substitute for per-test reset — there is **no within-applug
reboot**.

**Replayability.** The whole run is reproducible from **one base seed**, logged
as `L3 random seed: <seed>` (greppable) and replayable via `--l3-seed <seed>`.
When `--l3-seed` is omitted a base seed is generated and logged; each applug's
ordering seed is derived deterministically from that one base seed, so the same
base seed reproduces the entire run's order.

**Failure isolation:** a failing boot, login, or test for one applug never aborts
the others — every result is collected and a per-applug, per-test PASS/FAIL
summary is printed, with logs dumped on failure. If **any** test failed, the L3
phase fails the gate (non-zero exit). L3 reuses the same port as tier-a/b (free
after teardown) and the boots are strictly sequential.

`--functional` **requires** `--source-root`: the functional manifest can only be
discovered from the pinned source clones, so `--functional` without a source root
is a hard error. Because CI invokes `frozen_verify.py` once per scenario (fresh
and upgrade), L3 runs on **both** install paths (rule 22).

`--exe` is the installed-path override: passing a different `--exe` redirects all
verification to the installed application rather than the freeze-dir artifact;
the scenario logic operates entirely on the throwaway `HOME`, so it is identical
for freeze-dir and installed binaries.

### `scripts/browser_verify.py` — tier (b) executor

Implements **every** schema verb generically against Playwright — `navigate`,
`fill`, `click`, `wait_for`, `assert_present`, `assert_absent`, `assert_value` —
plus the any-present marker semantics above. It hardcodes no component, route, or
marker; it mirrors the password-agnostic login (tier-a runs first and rotates the
password). Importable: `frozen_verify.run_tier_b()` calls `run_browser_checks()`.

### `scripts/screen_manifest.py` — discovery / parse / invoke (mechanism only)

ahimsa owns the gate **mechanism**, never screen or test content. This module
discovers and validates the `*_screens.json` data (strict: any malformed /
wrong-schema / unknown-type file is a hard error so the gate never passes
vacuously), and likewise discovers, parses, and invokes the
`*_functional_tests.json` declarations. The screen schema is canonical in
matika; the constants here (`SUPPORTED_SCHEMA`, `ALLOWED_VERBS`,
`FUNCTIONAL_TEST_SCHEMA`, `FUNCTIONAL_TESTS_SUFFIX`) are a minimal mirror used
only to validate the data the gate reads. It also parses the `[ROUTES: ...]`
startup log marker; the route-vs-manifest hard gate that compares live routes
against the declared set is a distinct follow-on (A3, manomatika/ahimsa#84).

## Where manifest + test discovery comes from (build vs. install-verify)

The gate discovers what to drive from `--source-root` — the **pinned source
clones**, not the product artifact. The L3 functional-test `.py` code is read
**only** from this clone; it is **never bundled** into the product artifact.

- **build-\* jobs** clone matika at the recipe's pinned `matika.tag` into
  `build/matika` and each applug at its pinned tag into
  `build/matika/plugins/<name>`, then run `frozen_verify.py --exe <freeze-dir>
  --source-root build/matika --functional` for both scenarios with `--browser`.
- **install-verify-\* jobs** (Option-3 source-root fork) mount/install the built
  artifact and keep `--exe` on that **installed** binary, but **also** side-clone
  the pinned sources (matika core + applugs) into `build/matika` checked out at
  the matching build job's **resolved commit SHAs** (see *Provenance note* below),
  then pass `--source-root build/matika --functional`. So the installed artifact
  is what is exercised, while screen + functional-test discovery comes from the
  SHA-pinned clone.

Together these turn product-behavior regressions — stale plugin code after an
upgrade, a removed/renamed screen, a wrong render, or a broken applug feature —
into hard CI failures on the frozen artifact, on both the fresh-install and
upgrade-over-stale paths, on all three OS targets.

### Provenance note (SHA-pinned discovery, Option-3)

The install-verify side-clone is pinned by **resolved commit SHA**, not by tag.
Each `build-*` job resolves its tag-pinned clones to commit SHAs and emits them
as job outputs (`matika_sha` — a string; `applug_shas` — a JSON object keyed by
applug name). The matching `install-verify-*` job consumes those outputs
(`needs.build-*.outputs.matika_sha` / `.applug_shas`) and checks the side-clone
out at **those exact SHAs** — never re-resolving the (mutable) tag on the verify
side. This gives byte-identical provenance between what was built and what
discovery reads, while test `.py` code is still read only from the side-clone and
**never bundled** into the product artifact. The per-product manifest/BOM (owned
by manomatika/manomatika) is where tag-AND-SHA pinning is recorded for the
shipped product.
