> Part of [CLAUDE.md](../CLAUDE.md) — see the main file for orientation.

## Package Layout

Ahimsa is an installable Python package (PEP 621, hatchling backend).

```
ahimsa/                   — installable package (import as `ahimsa`)
  __init__.py             — exposes __version__ via importlib.metadata
  validate_recipe.py      — recipe validator + resolver protocol + CLI entry point; `Error.code` carries ahimsa's own AHIMSA-<FAC>-<NNN> code (run R5)
  validate_releases.py    — release-log (RELEASES.md) validator + CLI entry point; its `Error(...)` sites also carry AHIMSA-RELEASE-* codes
  release_log.py          — RELEASES.md renderer (merges release-log.yaml + live tags)
  releases_grammar.py     — shared (repo, tag) heading grammar for validator + renderer
  stub_resolver.py        — offline stub resolver used by tests/tooling
  _config.py              — config loader (walk-up algorithm)
  manomatika_error.py     — ecosystem-shared `ManoMatikaError` base class + the `<COMPONENT>-<FAC>-<NNN>` code pattern (run R0)
  error_codes.py          — error-code MECHANISM: schema, lints, BLOCKING cross-repo aggregator + registry-parity, codegen (run R0 mechanism; aggregator flipped to blocking R6)
  error_code_constants.py — AUTO-GENERATED typed constants for ahimsa's own 32 codes (run R5; regenerate via `scripts/gen_error_codes.py error-codes.yaml --out ahimsa/error_code_constants.py`; do not hand-edit)
  locales/en.json         — ahimsa's en-only error catalog (`errors.<CODE>` -> message, sourced from `error-codes.yaml`); ahimsa is the English-only carve-out, no es catalog
tests/                    — pytest test suite
  test_validate_recipe.py — unit tests (mock resolvers, no network)
  test_validate_releases.py — release-log validator tests
  test_release_log.py     — renderer tests
  test_invocation.py      — subprocess invocation-style tests
  test_packaging.py       — console-script entry-point contract (pyproject declarations, import resolution, installed-metadata path)
  test_config_precedence.py — walk-up and --config precedence matrix
  test_build_workflow.py  — build.yml workflow assertions
  test_frozen_verify.py   — unit tests for the frozen-feature verification harness
  test_browser_verify.py  — unit tests for the tier-b Playwright verb executor
  test_screen_manifest.py — unit tests for screen/functional-test discovery, parse + invoke
  test_screen_schema_parity.py — asserts ahimsa's mirrored screen-schema constants match matika's canon
  test_github_resolver_integration.py — real-network integration tier (runs in the full suite)
  test_error_codes.py     — R0 mechanism tests (schema/lints/aggregator/codegen)
  test_error_code_registry.py — run R5: ahimsa's own error-codes.yaml lints clean, declares exactly 32 codes (each facility contiguous from 001), en.json catalog parity, and validate_recipe/validate_releases Error.code threading
  test_i18n_completeness_gate.py — asserts ahimsa's build-gate consumption of matika's canonical STRICT i18n completeness checker
  fixtures/               — per-scenario recipe + config fixtures
scripts/
  build_standalone.py     — build orchestration (stubbed, not part of package)
  make_dmg.py / _dmg_settings.py — DMG wrapper invoked by build.yml (macOS)
  smoke_launch.py         — boots the frozen app and asserts it serves (build.yml smoke gate)
  frozen_verify.py        — the feature-gate driver: L2 tier-a (authenticated HTTP) + tier-b (Playwright, --browser) and L3 (--functional, reboot-per-applug) against the frozen artifact (fresh + upgrade scenarios)
  browser_verify.py       — tier-b headless-Playwright verb executor (driven via frozen_verify --browser)
  screen_manifest.py      — screen/functional-test discovery, parse + invoke (mechanism only; mirrors matika's canonical schema constants)
  render_releases_md.py   — RELEASES.md render entry point (used by build.yml refresh job)
  gen_error_codes.py      — codegen CLI: error-codes.yaml -> typed constants module (run R0)
  fetch_error_codes_sources.py — resolves the four SHA-pinned per-origin error-codes.yaml sources named by the recipe (fetched via `gh api`) and feeds them to the BLOCKING `ahimsa-aggregate-error-codes --require-all-origins` gate step
installer/                — windows_installer.iss (Inno Setup script for the Windows EXE)
docs/                     — release-notes/<tag>.md per-tag GitHub-release bodies
registry/                 — registry-era scaffolding (M4 RegistryResolver)
error-codes.yaml          — ahimsa's own error-code registry (origin: ahimsa, 32 codes, supported_locales: [en]; run R5)
VERSION                   — single source of version ("0.0.1-dev")
pyproject.toml            — package metadata; hatchling reads VERSION at build time
config.json               — project-level allowed_hosts (walked up from recipes/)
```

Console scripts (`[project.scripts]`): `ahimsa-validate`
(`ahimsa.validate_recipe:main`), `ahimsa-validate-releases`
(`ahimsa.validate_releases:main`), and `ahimsa-aggregate-error-codes`
(`ahimsa.error_codes:main`) — the BLOCKING cross-repo aggregator.
