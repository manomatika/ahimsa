# Changelog

All notable changes to ahimsa are documented here.

---

## [Unreleased]

### Added
- `validate.yml`: add `workflow_dispatch` trigger so the workflow can be run on demand (e.g. after a key rotation).

---

## [1.0.0] — 2026-04-27

### Added
- Initial ahimsa repo — recipe system and build pipeline for Matika-based
  applications.
- `recipes/reference-app/recipe.json` — scaffold recipe for the Matika
  Reference Application (formerly "pffp" / "Pats Fantastic Finance Pro"),
  demonstrating the full schema with application metadata, matika version pin,
  and an EyeRate AppLug declaration.
- `scripts/validate_recipe.py` — validates a recipe.json against all ahimsa
  rules (exact version pins, consistent matika_version across applugs,
  applug matika_version matches recipe matika.version).
- `scripts/build_standalone.py` — build pipeline entry point (placeholder;
  full implementation in a future milestone).
- GitHub Actions workflows: `validate.yml` (runs on every recipe change),
  `build.yml` (manual dispatch, mac or windows target).
- `registry/` directory reserved for the release registry.
