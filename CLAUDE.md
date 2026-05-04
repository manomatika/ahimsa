# CLAUDE.md

**Ahimsa** | Copyright (c) 2026 Patrick James Tallman

Ahimsa is the build, validation, and release system for 
Matika-based applications. A recipe repo is how a developer 
or software company defines and releases a Matika application 
composed of one or more AppLugs.

## What Ahimsa Is

- A recipe repo — defines what applugs make up an application
- A validator — ensures all applugs target the same matika version
- A build pipeline — clones matika + applugs and produces DMG/EXE
- A reference implementation for Matika application distribution

## Mental Model

- Matika is the framework (like Electron or Qt)
- AppLugs are plugins
- recipe.json is the lockfile — exact version pins, no ranges
- Ahimsa is the build machinery

## Key Concepts

- All applugs in a recipe must declare identical matika_version
- matika.repo in recipe.json is the source of matika
- Validator fetches applug.json from GitHub at declared tag to verify
- Backward compatibility is mandatory — no breaking changes within 
  a matika minor version

## Recipes

- Recipes live at `recipes/<app>/recipe.json`. One directory per application. Asset paths inside the recipe (e.g. `application.icon`) are relative to the recipe's directory, not the repo root.
- Recipes pin exact X.Y.Z versions. No ranges, no wildcards, no `_dev` suffixes. `_dev` is a development-only marker in source repos (matika, applugs); recipes consume only released tags.

## Current Recipe

recipes/pffp/recipe.json — Pats Fantastic Finance Pro
- matika 0.0.4 from github.com/pjtallman/Matika
- eyerate 0.0.4 from github.com/pjtallman/EyeRate

## Package Layout

Ahimsa is an installable Python package (PEP 621, hatchling backend).

```
ahimsa/                   — installable package (import as `ahimsa`)
  __init__.py             — exposes __version__ via importlib.metadata
  validate_recipe.py      — validator library + CLI entry point
  _config.py              — config loader (walk-up algorithm)
tests/                    — pytest test suite
  test_validate_recipe.py — unit tests (mock resolvers, no network)
  test_invocation.py      — four subprocess invocation-style tests
  test_config_precedence.py — walk-up and --config precedence matrix
  fixtures/               — per-scenario recipe + config fixtures
scripts/
  build_standalone.py     — build orchestration (stubbed, not part of package)
VERSION                   — single source of version ("0.0.1_dev")
pyproject.toml            — package metadata; hatchling reads VERSION at build time
config.json               — project-level allowed_hosts (walked up from recipes/)
```

## Development Install

```
pip install -e ".[test]"
```

After install, all four invocation styles work:

```bash
ahimsa-validate recipes/pffp/recipe.json        # console-script entry point
python3 -m ahimsa.validate_recipe <recipe>      # module invocation
python3 ahimsa/validate_recipe.py <recipe>      # direct file
python3 -c "from ahimsa.validate_recipe import validate; ..."
```

Run tests:

```
pytest tests/
```

## Running the Validator

```
ahimsa-validate recipes/pffp/recipe.json
ahimsa-validate --config path/to/config.json recipes/pffp/recipe.json
```

## Validation Rules

- All applugs must declare identical matika_version values
- All applug matika_version values must match recipe.matika.version
- matika.repo is required
- Exact version pins only — never ranges
- Validator fetches applug.json from GitHub at declared tag

## Config Precedence

```
--config <path>   >   walked-up config.json   >   default ["github.com"]
```

No environment-variable override. Walk-up starts at the recipe's directory,
stops at the first `config.json` found, or at a project-root marker (`.git`,
`pyproject.toml`, `package.json`), never crossing the filesystem root.

Security rationale: config.json is committed to the repo and controls which
hosts recipes may reference. Keeping it in-repo (not env-vars) means the
policy is auditable, version-controlled, and can't be silently overridden by
shell environment.

## Resolver Protocol

- `ahimsa/validate_recipe.py` abstracts manifest fetching behind `BaseResolver` ABC with a template-method `resolve()`. `GitHubResolver` is the only concrete implementation today; a future `RegistryResolver` will land for the registry milestone (M4) without changing call sites.
- `raw.githubusercontent.com` is case-sensitive on owner/repo paths. `GitHubResolver` canonicalizes via the GitHub API (which is case-insensitive) before constructing raw URLs. Cached per-process to avoid redundant API calls.
- Tests inject `BaseResolver` subclasses via `validate(..., resolvers={...})` — no network hit in tests.

## GitHub Actions Workflows

- validate.yml — runs on every push and PR to main
  Installs `pip install -e ".[test]"`, runs `pytest tests/`
  Live recipe step commented out (TODO: re-enable after v0.0.4 tags ship)
- build.yml — runs on workflow_dispatch or tag push (v*)
  Jobs: validate → build-macos-arm → build-macos-intel → 
  build-windows → release
  All build jobs are currently stubbed with TODOs

## Architecture Decisions

- Decentralized: recipes point directly at GitHub repos/tags
- BaseResolver ABC + registry ready for future RegistryResolver (M4)
- DMG via dmgbuild Python library (macos-14 arm64, macos-13 intel)
- Windows installer via Inno Setup
- Release job creates GitHub release with all three artifacts

## Workflow Positioning

- Ahimsa is downstream of matika and applug releases — it consumes only released, tagged versions. Steady-state: a matika or applug release → ahimsa picks it up via recipe update → ahimsa releases.
- v0.0.4 is the exception cycle: ahimsa is being built for the first time (its own version is v0.0.1). matika v0.0.4 and eyerate v0.0.4 will be released first; ahimsa v0.0.1 will then be finalized against those real tags.

## Standing Rules

- Never git merge, never rm -rf
- All recipe changes must pass validate.yml before merge
- Exact version pins only in recipe.json — never ranges
- recipe.json is the sole source of truth for what ships
