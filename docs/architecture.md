> Part of [CLAUDE.md](../CLAUDE.md) — see the main file for orientation.

## Ecosystem Architecture

The shipped PRODUCT is **ManoMatika** — a pinned *triple* of component versions
(matika + eyerate + ahimsa). A release blesses exactly one validated triple.

- **`manomatika/manomatika`** — PRODUCT AUTHORITY. Owns the recipes, the audit
  log (`release-log.yaml` + `RELEASES.md`), the product release and the single
  hosted installer binary, the cross-component umbrella docs, the per-version
  manifest/BOM (pins each component by tag AND resolved SHA), and the QA gate.
- **`ahimsa`** — RECIPE ENGINE ONLY. Owns the build / validation / release
  *mechanism* and the recipe *schema*. Owns no recipes, no audit-log content,
  and hosts no GitHub releases of its own. Builds installers as transient CI
  artifacts (`workflow_dispatch`); the product release is cut by
  `manomatika/manomatika`.
- **`matika`, `eyerate`** — components. Self-scoped architecture docs;
  notes-only GitHub releases (no installer binaries).

> **Migration status** — resolved. `manomatika/manomatika` now exists and all
> planned moves have completed: the recipe lives in mm (fetched from mm at
> `workflow_dispatch` time, not stored in ahimsa); the audit log
> (`release-log.yaml` + `RELEASES.md`) lives in mm; and the `build.yml`
> `release` job and `push: tags: v*` trigger have been removed. ahimsa now
> holds only the engine mechanism: recipe schema + validator, build pipeline
> (`workflow_dispatch`-only), and release-notes rendering/validation machinery.

## What the Engine Does

- **Recipe schema + validator** — defines the recipe format and enforces every
  rule in a single pass (see *Validation Rules*).
- **Build pipeline** — clones matika + the recipe's applugs at their pinned
  tags and produces DMG/EXE installer artifacts.
- **Build pipeline trigger** — `build.yml` runs on `workflow_dispatch` only.
  It orchestrates validate → build (DMG/EXE artifacts). The product release
  is cut by `manomatika/manomatika`, not by this engine.

## Mental Model

- Matika is the framework (like Electron or Qt)
- AppLugs are plugins
- recipe.json is the lockfile — exact version pins, no ranges
- Ahimsa is the build machinery; the product/recipe/audit-log authority is
  `manomatika/manomatika`

## Key Concepts

- All applugs in a recipe must declare identical matika_version
- matika.repo in recipe.json is the source of matika
- Validator fetches applug.json from GitHub at declared tag to verify
- Backward compatibility is mandatory — no breaking changes within 
  a matika minor version

## Architecture Decisions

- Decentralized: recipes point directly at GitHub repos/tags
- BaseResolver ABC + registry ready for future RegistryResolver (M4)
- DMG via dmgbuild Python library (macos-14 arm64, macos-15-intel)
- Windows installer via Inno Setup
- Installer artifacts are produced by the engine's build jobs as transient CI
  artifacts. The product release that attaches them is the authority of
  `manomatika/manomatika`. ahimsa no longer runs `gh release create`.

## Workflow Positioning

- Ahimsa is downstream of matika and applug releases — it consumes only released, tagged versions. Steady-state: a matika or applug release → recipe update (in `manomatika/manomatika`) → engine build.
- **Release / QA flow:** tag matika + eyerate as **prereleases** (the cycle is
  iterating through `v0.0.4-rc.N` candidates — re-pin the mm recipe each rc) →
  dispatch ahimsa `build.yml` (`workflow_dispatch`, recipe fetched from
  `manomatika/manomatika`) → the build + install-verify jobs **automate the QA
  gate** in CI (smoke-launch + L2 tier-a/tier-b structural checks + L3
  applug-authored functional tests, on fresh + upgrade scenarios, against both the
  freeze-dir and the installed artifact on all three OS targets; see *Frozen-App
  Feature Verification*) and produce the DMG/EXE → on a green build + DMG QA pass,
  tag ahimsa v0.0.1, author the
  `manomatika/manomatika` manifest/BOM, and cut the `manomatika/manomatika`
  product release with the DMG attached there. The prerelease flag is the trust
  boundary; the `manomatika/manomatika` product release is the only blessed
  product.
- v0.0.4 is the exception cycle: ahimsa is being built for the first time (its
  own version is v0.0.1, still unreleased — its release-log entry in mm is a
  `pending` placeholder). matika and eyerate release first; ahimsa v0.0.1 is then
  finalized against those real tags.
