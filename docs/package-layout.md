> Part of [CLAUDE.md](../CLAUDE.md) — see the main file for orientation.

## Package Layout

Ahimsa is an installable Python package (PEP 621, hatchling backend).

```
ahimsa/                   — installable package (import as `ahimsa`)
  __init__.py             — exposes __version__ via importlib.metadata
  validate_recipe.py      — recipe validator + resolver protocol + CLI entry point
  validate_releases.py    — release-log (RELEASES.md) validator + CLI entry point
  release_log.py          — RELEASES.md renderer (merges release-log.yaml + live tags)
  releases_grammar.py     — shared (repo, tag) heading grammar for validator + renderer
  stub_resolver.py        — offline stub resolver used by tests/tooling
  _config.py              — config loader (walk-up algorithm)
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
  fixtures/               — per-scenario recipe + config fixtures
scripts/
  build_standalone.py     — build orchestration (stubbed, not part of package)
  make_dmg.py / _dmg_settings.py — DMG wrapper invoked by build.yml (macOS)
  smoke_launch.py         — boots the frozen app and asserts it serves (build.yml smoke gate)
  frozen_verify.py        — the feature-gate driver: L2 tier-a (authenticated HTTP) + tier-b (Playwright, --browser) and L3 (--functional, reboot-per-applug) against the frozen artifact (fresh + upgrade scenarios)
  browser_verify.py       — tier-b headless-Playwright verb executor (driven via frozen_verify --browser)
  screen_manifest.py      — screen/functional-test discovery, parse + invoke (mechanism only; mirrors matika's canonical schema constants)
  render_releases_md.py   — RELEASES.md render entry point (used by build.yml refresh job)
installer/                — windows_installer.iss (Inno Setup script for the Windows EXE)
docs/                     — release-notes/<tag>.md per-tag GitHub-release bodies
registry/                 — registry-era scaffolding (M4 RegistryResolver)
VERSION                   — single source of version ("0.0.1-dev")
pyproject.toml            — package metadata; hatchling reads VERSION at build time
config.json               — project-level allowed_hosts (walked up from recipes/)
```

Console scripts (`[project.scripts]`): `ahimsa-validate`
(`ahimsa.validate_recipe:main`) and `ahimsa-validate-releases`
(`ahimsa.validate_releases:main`).
