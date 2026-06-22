# CLAUDE.md

**Ahimsa** | Copyright (c) 2026 Patrick James Tallman

Ahimsa is the **recipe ENGINE** for Matika-based applications: the build,
validation, and release *mechanism*, plus the recipe *schema*. It is the
machinery that turns a validated recipe into installer binaries — it is not
the product, and it is not the authority over what ships.

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

## Working Style & Discipline

This section captures the standing working rules across the manomatika ecosystem. **CLAUDE.md is authoritative for how a fresh Claude Code instance should operate in this repo; keep it current as practices evolve.** The terminal milestone of every release is `Documentation & Release Readiness`, which includes auditing and updating every CLAUDE.md against what actually shipped.

### Documentation integrity

CLAUDE.md must never knowingly contain stale information. Whenever CLAUDE.md is edited or regenerated, every factual claim about this repo (workflow/job status, ownership boundaries, file locations, build/release state) must be verified against the actual current repo state before being written. Stale claims are defects. When a claim cannot be verified, omit it rather than guess.

**Per-tag documentation triad.** CLAUDE.md, `CHANGELOG.md`, and `RELEASES.md`
are updated for EVERY tag — both rc and final. (CHANGELOG.md is per-repo;
`RELEASES.md` is generated from `manomatika/manomatika`'s `release-log.yaml` —
see *Release-Notes System & Central Release Log* below.)

### Collaboration model

- **Human in the loop for every change.** The user holds architecture, code review, and merge decisions. Don't merge PRs; don't push without explicit instruction; don't open PRs without the user's go-ahead.
- **One question or command batch at a time.** When asking a question or proposing actions, stop and wait for the user's answer or for the user to read previous output before continuing. Don't paste a new prompt or run new commands on top of unreviewed output.
- **Investigate-and-report before editing when scope is unclear.** Read the relevant code/docs first, surface what you find, and let the user direct the fix. Never assume; never silently expand scope.
- **Push back on overthinking and scope creep.** Best-practice patterns, never papered-over hacks. Fix issues correctly now — except items the user has explicitly deferred (e.g. follow-on issues filed against a later milestone).
- **Flag best-practice violations before implementing.** If a request would land an anti-pattern (security bypass, hack-around, etc.), surface the concern and let the user decide before writing code.

### Git, branches, references, and worktrees

- **The user does all git review and merges in the browser.** Don't merge PRs, push to main, or tag releases unless explicitly instructed.
- **Don't stage or commit unless explicitly granted.** The user handles `git add` / `git commit` manually by default. When granted, follow the conventional-commit pattern (`docs:`, `fix:`, `feat:`, `refactor:`, etc.) and include `Closes manomatika/<repo>#N` (fully qualified) where applicable.
- **Cross-repo issue/PR references must always be fully qualified.** Write `manomatika/matika#N`, `manomatika/eyerate#N`, `manomatika/ahimsa#N` — never a bare `#N` for an issue that lives in a different repo. Bare refs have caused real damage: a misqualified `Closes #11` / `Closes #12` in matika PR #35 closed unrelated issues in another repo's tracker. Bare refs are only safe when the PR and the issue are in the same repo. Cross-repo `Closes` references only cross-link — they do NOT auto-close; close manually after merge.
- **cc does not run `git merge` locally.** Integration of branches is done by the user via PR merge in the browser. For any local branch updates cc performs, use `git rebase` or `git cherry-pick`. cc may run `rm -rf` ONLY within a repo working directory under `~/dev/projects/` (a clone `~/dev/projects/<repo>/` or a worktree `~/dev/projects/<repo>-<branch>/`) or under `~/dev/projects/cc_output/` — never anywhere else on the filesystem, and never with an unanchored or variable-expanded path that could resolve outside them. Targeted `git rm` for tracked files remains the norm; `rm -rf` is the constrained exception (rule 23).
- **`VERSION` is the single source of truth** for version metadata in this repo. Never hand-edit version literals in other files; release tooling propagates from `VERSION`.
- **The user uses git worktrees** for parallel work (e.g. `~/dev/projects/matika-45/` alongside `~/dev/projects/matika/` on a separate branch). At any moment, the user may be operating in any of several working directories for the same repo. Always check the current branch (`git branch --show-current`) and confirm it matches what you expect before assuming.
- **Multi-instance/parallel discipline.** When operating as one of multiple parallel cc instances, stay strictly within the assigned worktree, branch, and scope of files described in the task. Do not modify files outside the assigned scope, even if issues are noticed elsewhere — surface those issues to the user as separate items to triage rather than fixing in-flight. Cross-cutting changes that touch another agent's work area must be coordinated by the user, not initiated unilaterally.

### Code and test discipline

- **Regression tests are required for every fix.** A bug fix that doesn't include a test that would have caught the bug isn't done.
- **All tests must RUN IN FULL and pass — 100% clean.** Every affected repo's COMPLETE suite must RUN with nothing excluded, deselected, skipped, or marked integration-only, and pass: 0 failed / 0 skipped / 0 xfail / 0 deselected / 0 warnings. No test may be excluded or filtered and no warning suppressed without the product owner's explicit, per-case approval recorded as a documented rule variation.
- **Full-suite, every change, everywhere — 100% clean (standing rule 21).** ANY code change, in ANY repo, requires the COMPLETE unit-test suite of every affected repo (and any repo whose behavior could be impacted) to RUN IN FULL — nothing excluded, deselected, skipped, or marked integration-only — and pass 100%: 0 failed / 0 skipped / 0 xfail / 0 deselected / 0 warnings. Eliminate every warning at its ROOT (fix the code or bump the dependency); never blanket-suppress with a `filterwarnings` / `-W ignore` / `-m 'not …'` filter. Use each repo's correct test environment (the uv-managed `.venv`) so a green run is never an env artifact. A change is not done until every suite is 100% clean.
- **Escaped-bug regression mandate (standing rule 22).** Any bug that reaches CI, an rc, or install/runtime testing without being caught by the suite MUST, as part of its fix, gain a regression test that would have caught it — added at the layer where it escaped (unit/integration for logic gaps; a feature/E2E check against the FROZEN, pinned artifact for product-behavior gaps). The fix is not done until that test exists, fails without the fix, and passes with it.
- **Never weaken or disable security / correctness checks** (CSRF, permission, auth, validation) as a workaround. If a check is producing a wrong answer, fix the call site to satisfy it correctly — never bypass.

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
  - `Cleanup & Tooling`
  - `Registry` (ahimsa only)
  - `Signing & Distribution` (ahimsa only)
  - `QA & System Test` (ahimsa only)
  - `Planning` (matika + eyerate + ahimsa)
  - `Playwright` (matika only)
  - `Documentation & Release Readiness` — the terminal release gate (all three)
- **Org-level Project: [ManoMatika Roadmap](https://github.com/orgs/manomatika/projects/1)** is the cross-repo backlog view. Its description records which component versions compose each manomatika release (e.g. ManoMatika v0.0.1 = matika v0.0.4 + eyerate v0.0.4 + ahimsa v0.0.1).
- **Milestone due dates are the single source of truth for dates.** The roadmap renders timelines from milestone Markers; do NOT create per-item date fields on the Project for scheduling (Pattern A — milestone-driven).

### Communication and output

- **Put prompts and commands in code blocks** so the user can one-tap copy them.
- The user is on **macOS / iTerm2** (tmux planned). Shell defaults to zsh.
- The user is **expert in software architecture and engineering, novice in git/GitHub specifics.** When git or `gh` commands appear in plans or output, explain plainly what they do, what they touch, and what the user will see.

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
  test_github_resolver_integration.py — real-network integration tier (runs in the full suite)
  fixtures/               — per-scenario recipe + config fixtures
scripts/
  build_standalone.py     — build orchestration (stubbed, not part of package)
  make_dmg.py / _dmg_settings.py — DMG wrapper invoked by build.yml (macOS)
  smoke_launch.py         — boots the frozen app and asserts it serves (build.yml smoke gate)
  frozen_verify.py        — tier-a authenticated-HTTP feature checks against the frozen artifact (fresh + upgrade scenarios)
  browser_verify.py       — tier-b headless-Playwright feature checks (driven via frozen_verify --browser)
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

## Development Install

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

## Validation Rules

`validate_recipe.py` enforces all rules in a single pass, accumulating errors rather than failing fast. Every error carries a JSON pointer and a clear message. Exit codes: 0 (clean), 1 (validation failure), 2 (configuration error — bad `--config` path or malformed config JSON).

**Schema validation**
- Required fields: `application.{name, product_name, version, bundle_id, icon}`, `matika.{version, repo, tag}`, `applugs` (non-empty array), per-applug `{name, repo, version, matika_version, tag}`
- `product_name` is the canonical PRODUCT identity that names all user-facing artifacts and the installed bundle/exe. `build.yml` lower-cases + slugifies it for the artifact FILENAME (`<product_slug>-<version>-<os>-<arch>.dmg/.exe`) and uses it verbatim as the proper-noun installed identity (`<product_name>-<version>.app`/`.exe`, e.g. `ManoMatika-0.0.1`). `application.name` is a separate descriptive title and no longer drives any artifact/bundle name. Format: ASCII alphanumerics separated by single spaces or hyphens, starting and ending with an alphanumeric (`^[A-Za-z0-9]([A-Za-z0-9]| [A-Za-z0-9]|-[A-Za-z0-9])*$`) — underscores, dots, slashes, leading/trailing/double separators, and non-ASCII are rejected so the name slugs cleanly for a filename and reads as a bundle name
- Version (pin) format: every pin field (`application.version`, `matika.version`, applug `version`/`matika_version`) must match `^\d+\.\d+\.\d+$` exactly (bare core) — ranges (`^`, `>=`, `~`), wildcards (`*`, `latest`, `1.x`), and pre-release/build suffixes (`-dev`, `-rc.N`, `-rc1`, `+build`) are all rejected. The `tag` fields are git refs, not pins, and are NOT version-format-checked — a recipe may pin matika/applugs at a pre-release tag like `v0.0.4-rc.1` while the corresponding bare-core `version` stays `0.0.4`
- `bundle_id` format: reverse-DNS, minimum 3 dot-separated components, each starting with a letter and containing only letters/digits/hyphens: `^[a-zA-Z][a-zA-Z0-9-]*(\.[a-zA-Z][a-zA-Z0-9-]*){2,}$`

**Consistency rules**
- All `applugs[i].matika_version` values must be identical — mixing applugs built against different Matika versions is a hard error
- Every `applugs[i].matika_version` must equal `matika.version` — the bundled Matika must match what every applug declares it was built against

**Remote verification**
- For each structurally-valid applug, fetches `applug.json` from the declared GitHub repo at the declared tag via the Resolver (see below)
- Verifies: `applug.json.id` matches recipe `name`; `applug.json.version` matches recipe `version`; `applug.json.matika_version` matches recipe `matika_version`

**Repo format**
- `applugs[i].repo` (and `matika.repo`) must be exactly `<host>/<owner>/<repo>` — no URL scheme, no trailing `.git`, no SSH form, exactly three slash-separated components

## Config Precedence

```
--config <path>   >   walked-up config.json   >   default ["github.com"]
```

No environment-variable override. Walk-up starts at the recipe's directory,
stops at the first `config.json` found, or at a project-root marker (`.git`,
`pyproject.toml`, `package.json`), never crossing the filesystem root.

Security rationale: `config.json` is committed to the repo and controls which hosts recipes may reference. Keeping it in-repo (not env-vars) means the policy is auditable, version-controlled, and can't be silently overridden by the shell environment. This becomes important when ahimsa accepts third-party recipes (M4 registry era) — a recipe cannot bypass the validator's policy by declaring its own allowed hosts.

The defense is incomplete without code signing: unsigned installers can be modified in transit to ship a permissive `config.json` or a tampered validator. Code signing and notarization track in [M5 — Code Signing & Distribution Security](https://github.com/manomatika/ahimsa/milestone/10) and are required before any external distribution.

## Resolver Protocol

`BaseResolver` is an ABC with a template-method `resolve(name, repo, tag) → AppLugManifest`. Subclasses implement `_canonicalize_repo()` and `_raw_url()`; `_parse_repo()`, `_fetch_json()`, and `_fetch_text()` are shared. `GitHubResolver` is the only concrete implementation today; a future `RegistryResolver` drops in at the M4 registry milestone without changing `validate()` call sites.

`BaseResolver` also requires two abstract release-log methods used by `validate_releases`:
- `list_tags(repo) -> list[str]` — returns all git tag names (without the `refs/tags/` prefix). Resolvers whose host has no tag concept return `[]`.
- `fetch_text(repo, ref, path) -> str | None` — returns the text content of `path` at `ref`, or `None` on 404. Resolvers whose host cannot serve arbitrary text files return `None` unconditionally.

Both are `@abstractmethod` rather than no-op defaults: silent no-op defaults would let release-log drift go undetected if a subclass forgot to implement either method. The abstract decl forces every `BaseResolver` subclass — production resolvers and test mocks alike — to make an explicit choice.

**Host dispatch** — `resolver_for(repo, allowed_hosts)` extracts the host from the repo string and looks it up in `_RESOLVER_REGISTRY`. Two distinct errors:
- Host not in `allowed_hosts` → `PermissionError` → error pointer `applugs[i].repo: host "X" not in allowed_hosts`
- Host in `allowed_hosts` but no registered resolver → `LookupError` → error pointer `applugs[i].repo: host "X" allowed but no resolver registered`

**GitHubResolver specifics** — `raw.githubusercontent.com` is case-sensitive on owner/repo paths. `GitHubResolver._canonicalize_repo()` resolves canonical casing via the GitHub API (which is case-insensitive) and caches the result per-process — recipes with multiple applugs from the same org hit the API once. `list_tags` calls `/repos/{owner}/{repo}/git/refs/tags` and follows `Link: rel="next"` pagination until exhausted (`per_page=100` per request, the API maximum). `fetch_text` reuses `_raw_url` + the shared `_fetch_text` helper.

**GitHub authentication** — `GitHubResolver.__init__` reads a token from the environment, with precedence `GITHUB_TOKEN` → `GH_TOKEN` (the gh-CLI legacy fallback). The token is stored as `self._token` and read once per resolver instance — mid-process env changes are not picked up. When a token is present, every outbound request from the resolver carries `Authorization: Bearer <token>`: the existence check, every paginated `list_tags` request, and the raw-content fetches via `_fetch_json` / `_fetch_text` (which consult `BaseResolver._request_headers()`, overridden on `GitHubResolver` to inject the auth header).

When no token is set the resolver makes unauthenticated requests — public repos still work, private repos 404. The `_canonicalize_repo` 404 handler distinguishes the two cases by token presence: with a token, the message stays `repository "..." not found on GitHub`; without a token, it appends `(or no access — set GITHUB_TOKEN if this is a private repo)`. The hint is applied ONLY at `_canonicalize_repo` because `list_tags` 404 has a legitimate "zero tags" meaning (auth is upstream-disambiguated by `_canonicalize_repo`) and the raw-content 404s mean "file does not exist at this ref".

The token value is never logged and never appears in any error message — only its env-var name is referenced in the auth hint. The token leaves the resolver only via the outbound `Authorization` header.

**Testing** — Two tiers. Both run as part of the full suite — `pytest` exercises everything, nothing is deselected by default (standing rule 21):

- **Unit tier** — `tests/test_validate_recipe.py`, `tests/test_validate_releases.py`. Tests inject `BaseResolver` subclasses via `validate(..., resolvers={"github.com": mock})` for protocol-contract checks, or patch `requests.get` directly to assert HTTP-layer details (headers, pagination, etc.). Mock resolvers must be genuine `BaseResolver` subclasses (not duck-typed) so interface changes are caught at test time. Runs offline.

- **Integration tier** — `tests/test_github_resolver_integration.py`. Real `requests.get` calls against guaranteed-public GitHub repos (`octocat/Hello-World`). Catches transport-layer surprises that mocked tests cannot — e.g. the GitHub auth requirement that PR `manomatika/ahimsa#28` shipped without auth handling. Tests are marked `@pytest.mark.integration`. The tier **runs as part of the default `pytest tests/` run** — it is no longer deselected (the former `addopts = "-m 'not integration'"` default-exclusion was removed so the full suite always exercises it). The `integration` marker stays registered in `pyproject.toml` so `@pytest.mark.integration` is a known mark and the tier can still be selected (`pytest -m integration`) or skipped for offline work (`pytest -m 'not integration'`) on demand.

  The tier needs outbound network to `api.github.com` and `raw.githubusercontent.com`. It runs unauthenticated by design — every test repo it touches is public, so it works in any developer environment without setup. CI (`validate.yml`) passes the auto-provisioned `GITHUB_TOKEN` to the step purely for rate-limit headroom on shared runners; the resolver reads `GITHUB_TOKEN` → `GH_TOKEN` and attaches `Authorization` when present (a no-op against public repos). The tests do not assume token presence or absence.

## Release-Notes System & Central Release Log

The release log is the **manomatika-wide release log** for the whole ecosystem.
It lives in `manomatika/manomatika` (product authority). ahimsa owns the
rendering/validation *machinery*; the content lives in mm.

### `RELEASES.md` is a GENERATED artifact

`RELEASES.md` is the single, ecosystem-wide audit log covering tags across
**all three repos** (matika, eyerate, ahimsa). **It is generated — do NOT
hand-edit `RELEASES.md`.** The human-edited source of truth is **`release-log.yaml`**,
both living in `manomatika/manomatika`.

- **`release-log.yaml`** — one record per `(repo, tag)` with the non-derivable, human-curated fields: `summary`, `status` (incl. `superseded_by`), `prs`, `artifact`, `date`. **Edit this file in mm**, then regenerate `RELEASES.md`.
  - **`deleted_tag`** (optional boolean, default `false`, **BACKWARD-looking**): set to `true` when the entry's git tag existed and was deliberately deleted after publishing (e.g. dev-phase tags removed during rc prep). The tag's audit record stays in `release-log.yaml` and `RELEASES.md` as a breadcrumb; the validator exempts the entry from the "entry but no tag" check (see *Validator* below). Parsing is **strict** — only a genuine YAML boolean (or absence) is accepted; a non-boolean value raises `ValueError`. Leave unset/`false` for every entry whose tag still exists.
  - **`pending`** (optional boolean, default `false`, **FORWARD-looking**): set to `true` for a "coming soon" placeholder row — an entry for a release that does NOT exist yet (no tag pushed). Mirror of `deleted_tag` but for the opposite time direction: `deleted_tag` is a tag that existed and was removed, `pending` is a tag that has not been created yet. Same strict boolean parsing and the same one-directional Category-B exemption (see *Validator* below). An entry **cannot** be both `pending: true` and `deleted_tag: true` — that is a contradiction (a release cannot be simultaneously not-yet-created and deleted) and raises `ValueError`. Drop `pending` (and fill in the real fields) once the tag is actually pushed.
- **Renderer** (`ahimsa/release_log.py` + `scripts/render_releases_md.py`) — merges `release-log.yaml` with live cross-repo tag data (via `GitHubResolver`, manomatika/ahimsa#49) and renders `RELEASES.md` newest-first, with `## <repo> <tag>` headings. A live tag with no YAML record produces a templated placeholder entry plus a warning so a human backfills it. Run `python scripts/render_releases_md.py` (with `RELEASE_LOG_PATH`/`RELEASES_MD_PATH` env vars pointing to a mm checkout) before opening a release PR.

### Validator — repo-aware `(repo, tag)` keying

`ahimsa.validate_releases` audits `RELEASES.md` (in `manomatika/manomatika`) against the git tag lists of all in-scope repos. Bidirectional, keyed on `(repo, tag)`:

- Every git tag (`vX.Y.Z` / `vX.Y.Z-PRERELEASE`) in each repo MUST have a matching `## <repo> <tag>` entry.
- Every entry MUST correspond to an actual tag in that repo.
- Duplicate `(repo, tag)` entries fail with a `duplicate entry` error. **Cross-repo same-version tags do NOT collide** — e.g. `## matika v0.0.1` and `## eyerate v0.0.1` are distinct, valid entries (this is why the heading carries the repo slug).

**Intentionally-absent tags (backward-looking).** The "entry but no tag" direction is NOT enforced for entries whose corresponding record in `release-log.yaml` has `deleted_tag: true`. These are deliberate audit breadcrumbs for tags that were removed after publishing (e.g. dev-phase tags deleted during rc prep). The validator fetches `release-log.yaml` from `manomatika/manomatika` using the same resolver, repo, and ref (`HEAD`) it uses for `RELEASES.md`, and builds the exemption set automatically. An entry must be EXPLICITLY opted in with `deleted_tag: true`; the exemption is never implicit. The exemption is strictly one-directional — the opposite direction (live tag with no entry) is always enforced regardless of any `deleted_tag` marking. If a `deleted_tag: true` entry's tag STILL exists on the remote, the validator emits a stderr WARNING (not an error) so the stale marking is corrected. Building the exemption set is fail-open: a missing or malformed `release-log.yaml` collapses the set to empty, so legitimate breadcrumbs surface their error LOUDLY rather than being silently exempted.

**Pending placeholders (forward-looking).** The "entry but no tag" direction is likewise NOT enforced for entries marked `pending: true` — a legitimate "coming soon" audit row for a release that does not exist YET (no tag pushed). This is the exact mirror of `deleted_tag` but for the opposite time direction, and shares all of its rules: explicit opt-in only, the same fail-open exemption-set construction, and the same strict one-directionality (Category A — a live tag with no entry — is always enforced, never suppressed by `pending`). If a `pending: true` entry's tag NOW exists on the remote (the release happened), the validator emits a stderr WARNING so the stale marking is removed and the entry filled in. An entry marked BOTH `pending: true` and `deleted_tag: true` is a contradiction: `parse_release_log_text` raises `ValueError`, which (being fail-open) collapses the whole exemption set to empty so the bad data surfaces LOUDLY rather than silently exempting anything.

**Heading grammar** (`ahimsa/releases_grammar.py`, shared by validator and renderer per R-H): two-group regex `^##[ \t]+([a-z][a-z0-9-]*)[ \t]+(v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)[ \t]*$` — repo slug + tag. `slug_from_repo()` derives the slug (lowercase last path segment) from a full `host/owner/repo` spec. Headings with trailing junk deliberately do not match.

**Repo set.** `validate_releases(repos: list[str], ...)` takes the repo list explicitly. The CLI (`ahimsa-validate-releases`) derives it from `recipe.json` (`matika.repo` + `applugs[].repo`) plus ahimsa's own repo; recipe.json is read-only here. The RELEASES.md is fetched from `manomatika/manomatika` (default).

**Unchanged invariants.** Field-level content (`Date`/`Status`/`Artifact`/`PRs`/`Summary`) is still NOT parsed — only `(repo, tag)`-heading presence. So `published`/`superseded`/`failed`/breadcrumb/newest-first remain human conventions. Audit point is HEAD, not the recipe's pinned tag. Non-conforming tag names (`legacy-rev`, etc.) are ignored. CLI exit codes: 0 clean, 1 drift, 2 config error.

**Transitive integration.** `ahimsa-validate <recipe>` invokes `validate_releases` over the recipe's repos; release-log drift surfaces as errors alongside recipe-validation errors.

### Per-repo release notes (file-based)

Each repo ships a human-facing GitHub Release at tag time whose body comes from
a versioned file `docs/release-notes/<tag>.md` (never inline in CI). The
`manomatika/manomatika` product release body is assembled from the recipe-derived
header + per-tag notes file. matika and eyerate publish **notes-only** releases
(no installer binaries). The single hosted installer attaches to the
`manomatika/manomatika` product release.

### `workflow_dispatch` refresh

`build.yml` has a `refresh-releases-md` job (`workflow_dispatch` only) that
re-renders `RELEASES.md` in `manomatika/manomatika` from its `release-log.yaml`
and **opens a PR to mm** with the result — it never pushes to `main`. Use it to
log a between-release / single-repo hotfix tag without a full manomatika release.

## GitHub Actions Workflows

- **`validate.yml`** — runs on every push and PR to `main`. Installs via `pip install uv` → `uv sync --frozen` → `uv run pytest tests/` (the COMPLETE suite — unit, invocation, AND the real-network integration tier; nothing deselected, per rule 21). Mints a GitHub App token (`permission-contents: read`) and fetches the reference recipe from `manomatika/manomatika`, then runs `uv run ahimsa-validate "$RECIPE_PATH"` as a live recipe-validation step.
- **`build.yml`** — runs on `workflow_dispatch` only. Inputs: `recipe_path`
  (default `recipes/reference-app/recipe.json`) and `manomatika_ref` (branch/tag/SHA
  in mm to fetch the recipe from — for cross-repo validation builds; default `""`).
  The `push: tags: v*` trigger and the `release` job have been removed; ahimsa
  builds artifacts on demand, never creates GitHub releases. Jobs:
  - `validate` → fetches recipe from `manomatika/manomatika` (using a minted App token, `permission-contents: write`), installs ahimsa via `pip install uv` → `uv sync --frozen`, runs `uv run ahimsa-validate "$RECIPE_PATH"` (fail fast).
  - `build-macos-arm` (**macos-14**), `build-macos-intel` (**macos-15-intel** —
    `macos-13` was retired), `build-windows` (**windows-latest**) — all
    `needs: validate`, run in parallel. **Fully implemented, not stubbed.** Each job:
    1. fetches recipe from mm, reads metadata, clones matika at `recipe.matika.tag`,
       clones each applug into `build/matika/plugins/`;
    2. **installs matika's `requirements.txt` AND every `plugins/*/requirements.txt`
       BEFORE PyInstaller** — so `collect_all()` in `matika.spec` actually finds
       `alembic`/`curl_cffi`/`yfinance` rather than being a no-op (this ordering is
       why the freeze stopped failing with "No module named 'alembic'");
    3. `npm install && npm run build`, then `pyinstaller matika.spec --noconfirm`,
       asserting the bundle name matches the recipe's product identity;
    4. wraps the output — macOS via `scripts/make_dmg.py` (dmgbuild); Windows via
       `installer/windows_installer.iss` driven by **Inno Setup's `ISCC` on the
       runner PATH** (the bundle/output dirs are passed as absolute `%CD%`-rooted
       paths; the `.iss` path itself is repo-relative);
    5. **smoke-launches** the frozen app (`scripts/smoke_launch.py` — boot, migrate,
       load the `eyerate` applug, serve);
    6. runs **frozen feature verification on BOTH install paths** —
       `scripts/frozen_verify.py --scenario fresh` and `--scenario upgrade`, each
       with `--browser` (tier-a HTTP + tier-b Playwright). The `upgrade` scenario
       seeds a stale plugin (old version, marker removed, user data added) and
       asserts the launcher refreshed the code AND preserved the user data;
    7. uploads the DMG/EXE as a CI artifact.
  - `install-verify-macos-arm` (**macos-14**), `install-verify-macos-intel` (**macos-15-intel**), `install-verify-windows` (**windows-latest**) — each `needs` its corresponding build job. Downloads the DMG/EXE artifact, mounts/installs it to the OS-standard install path, then re-runs `smoke_launch.py` + `frozen_verify.py --scenario fresh` and `--scenario upgrade` against the **installed** binary (not the freeze-dir artifact). Closes the installer-level gap: proves the packaged DMG/EXE ships a launchable bundle at the correct install path, and that feature checks pass on both install paths from the installed location.

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
  `manomatika/manomatika`) → the build jobs now **automate the QA gate** in CI
  (smoke-launch + tier-a/tier-b frozen feature verification on fresh + upgrade
  paths; see *Frozen-App Feature Verification*) and produce the DMG/EXE → on a
  green build + DMG QA pass, tag ahimsa v0.0.1, author the
  `manomatika/manomatika` manifest/BOM, and cut the `manomatika/manomatika`
  product release with the DMG attached there. The prerelease flag is the trust
  boundary; the `manomatika/manomatika` product release is the only blessed
  product.
- v0.0.4 is the exception cycle: ahimsa is being built for the first time (its
  own version is v0.0.1, still unreleased — its release-log entry in mm is a
  `pending` placeholder). matika and eyerate release first; ahimsa v0.0.1 is then
  finalized against those real tags.

## Test Fixture Convention

`tests/fixtures/` contains per-scenario directories, each self-contained:
- `invalid_host/` — `recipe.json` + `config.json` allowing only `github.com` → policy rejects `test.invalid`
- `valid_local_config/` — same recipe + `config.json` allowing `test.invalid` → policy passes, dispatch fails (no resolver registered for `test.invalid`)
- `no_config/` — same recipe + `pyproject.toml` stop-marker, no `config.json` → walk-up stops, default policy rejects `test.invalid`

`test.invalid` is an RFC 6761 reserved name that never resolves on any real network — every fixture test runs offline.

## Standing Rules

General working discipline (tests, git, security checks, cross-repo refs, etc.) lives in the *Working Style & Discipline* section at the top of this file. The bullets below are ahimsa-specific.

- All recipe changes must pass `validate.yml` before merge.
- Exact version pins only in `recipe.json` — never ranges.
- `recipe.json` is the build input that defines the triple the engine assembles; the authority over what *ships as the product* is `manomatika/manomatika`'s manifest/BOM + product release.
- Standard Python `.gitignore` (GitHub's official Python template) is in place: covers `__pycache__/`, build/dist, `*.egg-info/`, `.pytest_cache/`, `.coverage`, `htmlcov/`, venv variants, `.tox/`, installer artifacts (`*.dmg`, `*.exe`, etc.), and OS/IDE noise. Never commit compiled artifacts.
