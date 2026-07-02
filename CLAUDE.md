# CLAUDE.md — ahimsa (recipe engine)

Ahimsa is the **recipe ENGINE** for ManoMatika: it validates recipes, builds DMG/EXE
installers from pinned component versions, and renders/validates the ecosystem release
log. It owns the build/validation *mechanism* and the recipe *schema* — not the
product, not the recipes, not the audit-log content. See [docs/architecture.md](docs/architecture.md)
for the full ecosystem model, engine detail, architecture decisions, and workflow positioning.

<!-- COMMON:BEGIN (generated from manomatika/docs/CLAUDE_COMMON.md — do not edit between these markers) -->
## Working Style & Discipline

This section captures the standing working rules across the manomatika ecosystem. **CLAUDE.md is authoritative for how a fresh Claude Code instance should operate in this repo; keep it current as practices evolve.** The terminal milestone of every release is `Documentation & Release Readiness`, which includes auditing and updating every CLAUDE.md against what actually shipped.

### Documentation integrity

CLAUDE.md must never knowingly contain stale information. Whenever CLAUDE.md is edited or regenerated, every factual claim about this repo (workflow/job status, ownership boundaries, file locations, build/release state) must be verified against the actual current repo state before being written. Stale claims are defects. When a claim cannot be verified, omit it rather than guess. This integrity requirement applies to all docs in this repo, not just CLAUDE.md. TARGET-vs-CURRENT divergence (where the intended model differs from what the code/repo physically contains today) must be stated honestly, not papered over.

### Collaboration model

- **Human in the loop for every change.** The user holds architecture, code review, and merge decisions. Don't merge PRs; don't push without explicit instruction; don't open PRs without the user's go-ahead.
- **One question or command batch at a time.** When asking a question or proposing actions, stop and wait for the user's answer or for the user to read previous output before continuing. Don't paste a new prompt or run new commands on top of unreviewed output.
- **Investigate-and-report before editing when scope is unclear.** Read the relevant code/docs first, surface what you find, and let the user direct the fix. Never assume; never silently expand scope.
- **Push back on overthinking and scope creep.** Best-practice patterns, never papered-over hacks. Fix issues correctly now — except items the user has explicitly deferred (e.g. follow-on issues filed against a later milestone).
- **Flag best-practice violations before implementing.** If a request would land an anti-pattern (security bypass, hack-around, etc.), surface the concern and let the user decide before writing code.

### Git, branches, references, and worktrees

- **The user does all git review and merges in the browser.** Don't merge PRs, push to main, or tag releases unless explicitly instructed.
- **Don't stage or commit unless explicitly granted.** The user handles `git add` / `git commit` manually by default. When granted, follow the conventional-commit pattern (`docs:`, `fix:`, `feat:`, `refactor:`, etc.) and include `Closes manomatika/<repo>#N` (fully qualified) where applicable.
- **Cross-repo issue/PR references must always be fully qualified.** Write `manomatika/matika#N`, `manomatika/eyerate#N`, `manomatika/ahimsa#N` — never a bare `#N` for an issue that lives in a different repo. Bare refs are only safe when the PR and the issue are in the same repo. Cross-repo `Closes` references only cross-link — they do NOT auto-close; close manually after merge.
- **cc does not run `git merge` locally.** Integration of branches is done by the user via PR merge in the browser. For any local branch updates cc performs, use `git rebase` or `git cherry-pick`. cc may run `rm -rf` ONLY within a repo working directory under `~/dev/projects/` (a clone `~/dev/projects/<repo>/` or a worktree `~/dev/projects/<repo>-<branch>/`) or under `~/dev/projects/cc_output/` — never anywhere else on the filesystem, and never with an unanchored or variable-expanded path that could resolve outside them. Targeted `git rm` for tracked files remains the norm; `rm -rf` is the constrained exception (rule 23).
- **`VERSION` is the single source of truth** for version metadata in this repo. Never hand-edit version literals in other files; release tooling propagates from `VERSION`.
- **The user uses git worktrees** for parallel work (e.g. `~/dev/projects/matika-45/` alongside `~/dev/projects/matika/` on a separate branch). At any moment, the user may be operating in any of several working directories for the same repo. Always check the current branch (`git branch --show-current`) and confirm it matches what you expect before assuming.
- **Multi-instance/parallel discipline.** When operating as one of multiple parallel cc instances, stay strictly within the assigned worktree, branch, and scope of files described in the task. Do not modify files outside the assigned scope, even if issues are noticed elsewhere — surface those issues to the user as separate items to triage rather than fixing in-flight. Cross-cutting changes that touch another agent's work area must be coordinated by the user, not initiated unilaterally.

### Code and test discipline

- **Regression tests are required for every fix.** A bug fix that doesn't include a test that would have caught the bug isn't done.
- **All tests must RUN IN FULL and pass — 100% clean.** Every affected repo's COMPLETE suite must RUN with nothing excluded, deselected, skipped, or marked integration-only, and pass: 0 failed / 0 skipped / 0 xfail / 0 deselected / 0 warnings. No test may be excluded or filtered and no warning suppressed without the product owner's explicit, per-case approval recorded as a documented rule variation.
- **Full-suite, every change, everywhere — 100% clean (standing rule 21).** ANY code change, in ANY repo, requires the COMPLETE unit-test suite of every affected repo (and any repo whose behavior could be impacted) to RUN IN FULL — nothing excluded, deselected, skipped, or marked integration-only — and pass 100%: 0 failed / 0 skipped / 0 xfail / 0 deselected / 0 warnings. Eliminate every warning at its ROOT (fix the code or bump the dependency); never blanket-suppress with a `filterwarnings` / `-W ignore` / `-m 'not …'` filter. Use each repo's correct test environment (the uv-managed `.venv`) so a green run is never an env artifact. A change is not done until every suite is 100% clean.
- **Escaped-bug regression mandate (standing rule 22).** Any bug that reaches CI, an rc, or install/runtime testing without being caught by the suite MUST, as part of its fix, gain a regression test that would have caught it — added at the layer where it escaped (unit/integration for logic gaps; a feature/E2E check against the FROZEN, pinned artifact for product-behavior gaps). The fix is not done until that test exists, fails without the fix, and passes with it. Product-behavior regressions must be exercised against the frozen artifact on BOTH install paths (fresh install AND upgrade over a prior install), since the upgrade path is where the stale-plugin regression escaped.
- **Never weaken or disable security / correctness checks** (CSRF, permission, auth, validation) as a workaround. If a check is producing a wrong answer, fix the call site to satisfy it correctly — never bypass.

### Error-code framework

- **Per-origin `error-codes.yaml`, one per origin.** Each of the four origins
  declares its own codes in its own file: matika at
  `src/matika/error/error-codes.yaml`, each applug at
  `src/<name>/error/error-codes.yaml`, manomatika (this org's product-authority
  repo) at `error/error-codes.yaml`, and ahimsa at its repo-root
  `error-codes.yaml`. A file with `codes: []` is a well-formed, reserved
  namespace — an empty registry is not a defect.
- **ahimsa owns the mechanism, not the codes.** ahimsa's `ahimsa/error_codes.py`
  defines the schema, the per-file lints, the cross-repo aggregator, and
  codegen; it owns no origin's codes and no repo's registry content.
- **The cross-repo aggregator is BLOCKING (registry parity).** At gate time,
  ahimsa resolves the four SHA-pinned per-origin files the recipe names and
  runs `ahimsa-aggregate-error-codes --require-all-origins` over them: it
  enforces cross-file code uniqueness, component-prefix disjointness, and that
  every expected origin actually contributed a file. Any finding fails the
  gate (V/X) — no report-only mode remains (flipped to blocking in R6,
  manomatika/ahimsa#129).
- **Codes are asserted, not prose.** Tests and call sites reference the typed,
  codegen'd constant (e.g. `MATIKA_LNCH_001`), never the free-text `message`
  string — the code is the single stable carrier; message text may change
  without breaking a caller.

### Repository ecosystem

- **manomatika** is the GitHub org. The shipped PRODUCT is **ManoMatika** — a pinned *triple* of component versions (matika + eyerate + ahimsa), blessed by a single product release. The repos:
  - **manomatika/manomatika** — PRODUCT AUTHORITY. Owns the recipes, the audit log (`release-log.yaml` + `RELEASES.md`), the product release + single hosted installer binary, cross-component umbrella docs, the per-version manifest/BOM (pins each component by tag AND resolved SHA), and the QA gate.
  - **manomatika/matika** — the framework (plugin-agnostic FastAPI host). Component; notes-only releases.
  - **manomatika/eyerate** — the reference AppLug (financial security tracking). Component; notes-only releases.
  - **manomatika/ahimsa** — the recipe ENGINE: build / validation / release *mechanism* + recipe *schema*. Owns no recipes, no audit-log content, and hosts no product releases of its own. **This repo.**
- Local clones live at `~/dev/projects/<repo>/` (sibling directories). Additional worktrees for the same repo live at `~/dev/projects/<repo>-<branch>/`.

### Milestones, Project, and dates

- **Milestone naming is shared and match-when-present** across repos. When a milestone exists in more than one repo, its title is byte-for-byte identical so the org Project rolls it up into a single cross-repo group. Milestone names never contain version numbers or dates.
- **Canonical milestone titles in the current release cycle:**
  - `Deployment & Install`
  - `Cleanup & Tooling` (matika + eyerate + ahimsa)
  - `Registry` (ahimsa only)
  - `Signing & Distribution` (ahimsa only)
  - `QA & System Test` (ahimsa only)
  - `Planning` (matika + eyerate + ahimsa)
  - `Playwright` (matika only)
  - `Documentation & Release Readiness` — the terminal release gate (all four)
- **Org-level Project: [ManoMatika Roadmap](https://github.com/orgs/manomatika/projects/1)** is the cross-repo backlog view. Its description records which component versions compose each manomatika release (e.g. ManoMatika v0.0.1 = matika v0.0.4 + eyerate v0.0.4 + ahimsa v0.0.1).
- **Milestone due dates are the single source of truth for dates.** The roadmap renders timelines from milestone Markers; do NOT create per-item date fields on the Project for scheduling (Pattern A — milestone-driven).

### Communication and output

- **Put prompts and commands in code blocks** so the user can one-tap copy them.
- The user is on **macOS** and uses **Ghostty** and **tmux** for terminal work (shell defaults to zsh). The user also runs a **Dell Latitude** (64 GB RAM, no high-performance GPU) for local models via **Ollama**, currently favoring **qwen**. All configs are managed with **chezmoi**; any change to any config must follow chezmoi best practice and standards. chezmoi usage is captured in a separate handoff file, `chezmoi-dotfiles-handoff.md`. The user edits in **neovim**, and may also use **VSC**.
- The user is **expert in software architecture and engineering, novice in git/GitHub specifics.** When git or `gh` commands appear in plans or output, explain plainly what they do, what they touch, and what the user will see.
<!-- COMMON:END -->

## Recipes (engine consumes; authority is `manomatika/manomatika`)

Recipe *content* is owned by `manomatika/manomatika`; ahimsa owns the recipe
*schema* and consumes a recipe as the build input. The recipe-format rules the
engine enforces:

- Recipes live at `recipes/<app>/recipe.json`. One directory per application. Asset paths inside the recipe (e.g. `application.icon`) are relative to the recipe's directory, not the repo root.
- Recipes pin exact **bare-core** X.Y.Z versions. No ranges, no wildcards, no pre-release suffixes. Pre-release suffixes (`-dev`, `-rc.N`) are development/audit-only markers in source repos (matika, applugs) and live only on human/audit surfaces (VERSION string, git tags, release titles); recipes consume only the bare core. Note: a recipe's `tag` field is a git ref and MAY carry a suffix (e.g. `v0.0.4-rc.1`) — only the `version`/`matika_version`/`matika.version` **pin** fields must be bare core.
- `matika_version` (per-applug, and `matika.version`) is the matika **framework compatibility pin** — the matika version the applug was built against — not a product version. It is always bare core.

**Version ladder & CORE/SUFFIX contract.** The pre-release ladder is
`X.Y.Z-dev` < `X.Y.Z-rc.N` < `X.Y.Z` (final); the dev marker is the
SemVer-valid `-dev` (hyphen), never `_dev` (underscore). The version **CORE**
(`X.Y.Z`) is canonical for ALL comparison, artifact/bundle naming, and
OS/installer/`Info.plist` fields; the pre-release **suffix** (`-dev`, `-rc.N`)
lives ONLY on human/audit surfaces (VERSION string, git tags, release
titles/bodies, audit log). ahimsa does NOT own the canonical SemVer parser
(`_parse_semver` / `version_core` / `is_prerelease`) — its source of truth is
matika's `src/matika/core/paths.py`; ahimsa's validator only format-checks that
recipe pin fields are bare core (regex `^\d+\.\d+\.\d+$`) and passes `tag`
fields through to resolvers as opaque git refs.

The reference-app recipe lives in `manomatika/manomatika` at
`recipes/reference-app/recipe.json`. It pins matika and the eyerate applug to a
**bare-core** `version` (`0.0.4` today) while its git-ref `tag` fields carry the
currently-blessed **pre-release tag** (e.g. `v0.0.4-rc.N` for matika, a possibly
different rc for eyerate) from `github.com/manomatika/matika` and
`github.com/manomatika/eyerate`. Those tag values are transient and owned by mm —
they get re-pinned each rc, so do not treat any specific rc here as canonical.
The invariant that IS canonical: version pins stay bare core; `tag` fields MAY
carry a pre-release suffix, and the two are decoupled. `build.yml`'s
`workflow_dispatch` fetches the recipe from mm at the path given by the
`recipe_path` input (default `recipes/reference-app/recipe.json`).

## AppLug trust, test posture & the three-layer testing model

**Install-trust posture ("posture (a)").** Installing an applug — via recipe at
build time, or via future runtime applug loading — IS the trust decision; we
trust everything at this stage. There is NO first-party/third-party distinction
in mechanism: matika treats every applug identically. ManoMatika-org applugs are
trusted by provenance and will live in a NON-PUBLIC org applug repo; the SDK only
ever bundles the reference applug (eyerate). Dangerous host ops (network,
filesystem, process, secrets) are expected THROUGH matika APIs — a reduced,
documented, auditable safe-by-default surface — but this is CONVENTION + review,
NOT a hard guarantee: an applug is in-process Python and cannot be prevented from
reaching host primitives directly. We add hindrances to bad behavior to the
extent practical, with no claim a determined bad actor is stopped. Posture
authority of record: `manomatika/manomatika`'s `docs/ManoMatikaUseCases.md`.

**Test execution is pure build automation — NOT a security boundary.** The
framework discovers each applug's unit tests through a known interface and runs
them ALL automatically at build time, identically for every applug. No trust
dimension, no sandbox, no isolation. There is no WASM/Wasmtime/WASI sandboxing of
applug code or tests — that approach is rejected on complexity, on introducing a
security-critical runtime dependency, and on its inability to run the real
product stack (compiled C/Rust extensions, sockets).

**Three-layer testing model** (keep the three distinct; never collapse):

- **L1** — every component unit/integration-tests its OWN functions in its OWN
  suite.
- **L2** — generic STRUCTURAL harness: domain-blind "every declared screen
  routes, renders, shows its markers." Applug-agnostic. matika owns the contract;
  ahimsa's gate RUNS it — the tier-a/tier-b frozen-app checks (see *Frozen-App
  Feature Verification*). (A1 — merged.)
- **L3** — applug-AUTHORED FUNCTIONAL tests, GENERICALLY INVOKED by the product
  gate via a contract. WHO AUTHORS (the applug) is separate from WHO INVOKES (the
  generic gate). No isolation requirement. ahimsa's gate invokes it
  **reboot-per-applug**: for each applug declaring `*_functional_tests.json`, a
  fresh frozen boot in a clean HOME with a new session runs that applug's tests in
  **randomized (seeded) order** (base seed logged as `L3 random seed: <seed>`,
  replayable via `--l3-seed`). Each test self-arranges (declared `setup`) and
  self-resets (declared `teardown`, guaranteed-run); the randomized order is the
  verifier that reset discipline holds, so a test that cannot reset its own
  mutation is a **defect**, never rebooted-around — the reboot is coarse
  containment BETWEEN applugs only, with no within-applug reboot. The
  functional-test schema is version 1.0 with optional `setup`/`teardown`. A
  failure for one applug never aborts the others, and any failed test fails the
  gate.

**ahimsa's slice (pure mechanism).** ahimsa owns the GATE, not the tests and not
the route classifications (applugs own those). It GENERICALLY INVOKES the testing
model via the contract at the product gate: **L2** runs as the manifest-driven
tier-a/tier-b frozen-feature checks, and **L3** is now wired in as the
`--functional` reboot-per-applug phase of `frozen_verify.py` (discovery from the
pinned source clones via `--source-root`; runs in every build-* job and, via the
Option-3 source-root fork, every install-verify-* job — see *Frozen-App Feature
Verification*). Either way, test execution is plain build
automation: NO sandbox, NO WASM. The forthcoming advisory applug inspection
(v0.0.2: import-linter allowlist + AST check + Bandit) is matika-OWNED (the
canonical check) and is INVOKED by ahimsa at recipe build/validate; it is
advisory, not blocking.

## Development Install & Testing

Two install surfaces, two purposes (see README "Installing the CLI" for the
full rationale). On a Homebrew-Python / PEP 668 macOS host **never**
`pip install` into the system interpreter and **never** use
`--break-system-packages` — that is what produces stale, dangling
`/opt/homebrew/bin/ahimsa-*` shims (`ModuleNotFoundError: No module named
'ahimsa'`).

**Tests — canonical uv flow (rule 21):**

```
uv sync                 # installs ahimsa + pytest into .venv (dev group)
uv run pytest tests/    # runs the COMPLETE suite — 0 failed / 0 skipped / 0 xfail / 0 deselected / 0 warnings
```

`uv run` resolves to the venv pytest (where ahimsa is installed), satisfying
rule 21. Pytest is declared in `[dependency-groups] dev` (PEP 735) so
`uv sync` always installs it without extra flags.

Both `validate.yml` and `build.yml` install ahimsa via uv (`pip install uv` → `uv sync --frozen` → `uv run …`), matching the local canonical flow.

**Global on-PATH `ahimsa-*` commands** — pipx, editable so they track this
source tree:

```
pipx install --editable ~/dev/projects/ahimsa   # exposes shims on ~/.local/bin
# code edits are live; after a pyproject DEPENDENCY change: pipx reinstall ahimsa
```

With either install on `PATH`, all four invocation styles work:

```bash
ahimsa-validate <path/to/recipe.json>                    # console-script entry point
python3 -m ahimsa.validate_recipe <recipe>      # module invocation
python3 ahimsa/validate_recipe.py <recipe>      # direct file
python3 -c "from ahimsa.validate_recipe import validate; ..."
```

## Running the Validator

```
ahimsa-validate <path/to/recipe.json>
ahimsa-validate --config path/to/config.json <path/to/recipe.json>
```

## Tiered Documentation

Deep-detail sections are maintained in `docs/` to keep this file navigable:

- **Package Layout** → [docs/package-layout.md](docs/package-layout.md)
- **Validation Rules & Config Precedence** → [docs/validation-rules.md](docs/validation-rules.md)
- **Resolver Protocol** → [docs/resolver.md](docs/resolver.md)
- **Release-Notes System & Central Release Log** → [docs/release-log.md](docs/release-log.md)
- **GitHub Actions Workflows** → [docs/ci-workflows.md](docs/ci-workflows.md)
- **Frozen-App Feature Verification** → [docs/frozen-verify.md](docs/frozen-verify.md)
- **Test Fixture Convention** → [docs/testing.md](docs/testing.md)
- **Ecosystem Architecture / Engine Detail / Architecture Decisions** → [docs/architecture.md](docs/architecture.md)

## Standing Rules

General working discipline (tests, git, security checks, cross-repo refs, etc.) lives in the *Working Style & Discipline* section at the top of this file. The bullets below are ahimsa-specific.

- All recipe changes must pass `validate.yml` before merge.
- Exact version pins only in `recipe.json` — never ranges.
- `recipe.json` is the build input that defines the triple the engine assembles; the authority over what *ships as the product* is `manomatika/manomatika`'s manifest/BOM + product release.
- Standard Python `.gitignore` (GitHub's official Python template) is in place: covers `__pycache__/`, build/dist, `*.egg-info/`, `.pytest_cache/`, `.coverage`, `htmlcov/`, venv variants, `.tox/`, installer artifacts (`*.dmg`, `*.exe`, etc.), and OS/IDE noise. Never commit compiled artifacts.
