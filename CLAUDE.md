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

## Current Recipe

recipes/pffp/recipe.json — Pats Fantastic Finance Pro
- matika 0.0.4 from github.com/pjtallman/Matika
- eyerate 0.0.4 from github.com/pjtallman/EyeRate

## Running the Validator

python3 scripts/validate_recipe.py recipes/pffp/recipe.json

## Validation Rules

- All applugs must declare identical matika_version values
- All applug matika_version values must match recipe.matika.version
- matika.repo is required
- Exact version pins only — never ranges
- Validator fetches applug.json from GitHub at declared tag

## GitHub Actions Workflows

- validate.yml — runs on every push and PR to main
  Validates all recipe.json files under recipes/
- build.yml — runs on workflow_dispatch or tag push (v*)
  Jobs: validate → build-macos-arm → build-macos-intel → 
  build-windows → release
  All build jobs are currently stubbed with TODOs

## Architecture Decisions

- Decentralized: recipes point directly at GitHub repos/tags
- resolve_applug() abstraction ready for future registry support
- DMG via dmgbuild Python library (macos-14 arm64, macos-13 intel)
- Windows installer via Inno Setup
- Release job creates GitHub release with all three artifacts

## Directory Structure

recipes/          — one subdirectory per application
  pffp/
    recipe.json   — the lockfile
registry/         — reserved for future applug registry
scripts/
  validate_recipe.py  — recipe validator with resolver abstraction
  build_standalone.py — build orchestration (stubbed)
.github/
  workflows/
    validate.yml  — CI validation on every PR
    build.yml     — full build pipeline

## Standing Rules

- Never git merge, never rm -rf
- All recipe changes must pass validate.yml before merge
- Exact version pins only in recipe.json — never ranges
- recipe.json is the sole source of truth for what ships
