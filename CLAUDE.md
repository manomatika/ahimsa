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

## Working Style & Discipline

This section captures the standing working rules across the manomatika ecosystem. **CLAUDE.md is authoritative for how a fresh Claude Code instance should operate in this repo; keep it current as practices evolve.** The terminal milestone of every release is `Documentation & Release Readiness`, which includes auditing and updating every CLAUDE.md against what actually shipped.

### Collaboration model

- **Human in the loop for every change.** The user holds architecture, code review, and merge decisions. Don't merge PRs; don't push without explicit instruction; don't open PRs without the user's go-ahead.
- **One question or command batch at a time.** When asking a question or proposing actions, stop and wait for the user's answer or for the user to read previous output before continuing. Don't paste a new prompt or run new commands on top of unreviewed output.
- **Investigate-and-report before editing when scope is unclear.** Read the relevant code/docs first, surface what you find, and let the user direct the fix. Never assume; never silently expand scope.
- **Push back on overthinking and scope creep.** Best-practice patterns, never papered-over hacks. Fix issues correctly now — except items the user has explicitly deferred (e.g. follow-on issues filed against a later milestone).
- **Flag best-practice violations before implementing.** If a request would land an anti-pattern (security bypass, hack-around, etc.), surface the concern and let the user decide before writing code.

### Git, branches, references, and worktrees

- **The user does all git review and merges in the browser.** Don't merge PRs, push to main, or tag releases unless explicitly instructed.
- **Don't stage or commit unless explicitly granted.** The user handles `git add` / `git commit` manually by default. When granted, follow the conventional-commit pattern (`docs:`, `fix:`, `feat:`, `refactor:`, etc.) and include `Closes manomatika/<repo>#N` (fully qualified) where applicable.
- **Cross-repo issue/PR references must always be fully qualified.** Write `manomatika/matika#N`, `manomatika/eyerate#N`, `manomatika/ahimsa#N` — never a bare `#N` for an issue that lives in a different repo. Bare refs have caused real damage: a misqualified `Closes #11` / `Closes #12` in matika PR #35 closed unrelated issues in another repo's tracker. Bare refs are only safe when the PR and the issue are in the same repo.
- **cc does not run `git merge` locally; never run `rm -rf`.** Integration of branches is done by the user via PR merge in the browser. For any local branch updates cc performs, use `git rebase` or `git cherry-pick`. Use targeted `git rm` if files must be removed.
- **`VERSION` is the single source of truth** for version metadata in this repo. Never hand-edit version literals in other files; release tooling propagates from `VERSION`.
- **The user uses git worktrees** for parallel work (e.g. `~/dev/projects/matika-45/` alongside `~/dev/projects/matika/` on a separate branch). At any moment, the user may be operating in any of several working directories for the same repo. Always check the current branch (`git branch --show-current`) and confirm it matches what you expect before assuming.
- **Multi-instance/parallel discipline.** When operating as one of multiple parallel cc instances, stay strictly within the assigned worktree, branch, and scope of files described in the task. Do not modify files outside the assigned scope, even if issues are noticed elsewhere — surface those issues to the user as separate items to triage rather than fixing in-flight. Cross-cutting changes that touch another agent's work area must be coordinated by the user, not initiated unilaterally.

### Code and test discipline

- **Regression tests are required for every fix.** A bug fix that doesn't include a test that would have caught the bug isn't done.
- **All tests must pass — 0 failed, 0 skipped, 0 xfail.** No exceptions without explicit user approval. In multi-repo changes, every affected repo's full suite must pass before any PR is opened.
- **Never weaken or disable security / correctness checks** (CSRF, permission, auth, validation) as a workaround. If a check is producing a wrong answer, fix the call site to satisfy it correctly — never bypass.

### Repository ecosystem

- **manomatika** is the GitHub org. Three repos compose the ecosystem:
  - **manomatika/matika** — the framework (plugin-agnostic FastAPI host)
  - **manomatika/eyerate** — the reference AppLug (financial security tracking)
  - **manomatika/ahimsa** — release / build / recipe-validation tooling
- Local clones live at `~/dev/projects/<repo>/` (sibling directories). Additional worktrees for the same repo live at `~/dev/projects/<repo>-<branch>/`.

### Milestones, Project, and dates

- **Milestone naming is shared and match-when-present** across repos. When a milestone exists in more than one repo, its title is byte-for-byte identical so the org Project rolls it up into a single cross-repo group. Milestone names never contain version numbers or dates.
- **Canonical milestone titles in the current release cycle:**
  - `Deployment & Install`
  - `Cleanup & Tooling`
  - `Registry` (ahimsa only)
  - `Signing & Distribution` (ahimsa only)
  - `QA & System Test` (ahimsa only)
  - `v0.0.5 Planning` (eyerate + ahimsa)
  - `Documentation & Release Readiness` — the terminal release gate (all three)
- **Org-level Project: [ManoMatika Roadmap](https://github.com/orgs/manomatika/projects/1)** is the cross-repo backlog view. Its description records which component versions compose each manomatika release (e.g. ManoMatika v0.0.1 = matika v0.0.4 + eyerate v0.0.4 + ahimsa v0.0.1).
- **Milestone due dates are the single source of truth for dates.** The roadmap renders timelines from milestone Markers; do NOT create per-item date fields on the Project for scheduling (Pattern A — milestone-driven).

### Communication and output

- **Put prompts and commands in code blocks** so the user can one-tap copy them.
- The user is on **macOS / iTerm2** (tmux planned). Shell defaults to zsh.
- The user is **expert in software architecture and engineering, novice in git/GitHub specifics.** When git or `gh` commands appear in plans or output, explain plainly what they do, what they touch, and what the user will see.

## Recipes

- Recipes live at `recipes/<app>/recipe.json`. One directory per application. Asset paths inside the recipe (e.g. `application.icon`) are relative to the recipe's directory, not the repo root.
- Recipes pin exact X.Y.Z versions. No ranges, no wildcards, no `_dev` suffixes. `_dev` is a development-only marker in source repos (matika, applugs); recipes consume only released tags.

## Current Recipe

recipes/reference-app/recipe.json — Matika Reference Application
- matika 0.0.4 from github.com/pjtallman/matika
- eyerate 0.0.4 from github.com/pjtallman/eyerate

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
ahimsa-validate recipes/reference-app/recipe.json        # console-script entry point
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
ahimsa-validate recipes/reference-app/recipe.json
ahimsa-validate --config path/to/config.json recipes/reference-app/recipe.json
```

## Validation Rules

`validate_recipe.py` enforces all rules in a single pass, accumulating errors rather than failing fast. Every error carries a JSON pointer and a clear message. Exit codes: 0 (clean), 1 (validation failure), 2 (configuration error — bad `--config` path or malformed config JSON).

**Schema validation**
- Required fields: `application.{name, version, bundle_id, icon}`, `matika.{version, repo, tag}`, `applugs` (non-empty array), per-applug `{name, repo, version, matika_version, tag}`
- Version format: every version field must match `^\d+\.\d+\.\d+$` exactly — ranges (`^`, `>=`, `~`), wildcards (`*`, `latest`, `1.x`), pre-release suffixes (`-rc1`, `+build`), and `_dev` suffixes are all rejected
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

**Testing** — Two tiers, both run offline by default:

- **Unit tier** — `tests/test_validate_recipe.py`, `tests/test_validate_releases.py`. Tests inject `BaseResolver` subclasses via `validate(..., resolvers={"github.com": mock})` for protocol-contract checks, or patch `requests.get` directly to assert HTTP-layer details (headers, pagination, etc.). Mock resolvers must be genuine `BaseResolver` subclasses (not duck-typed) so interface changes are caught at test time.

- **Integration tier** — `tests/test_github_resolver_integration.py`. Real `requests.get` calls against guaranteed-public GitHub repos (`octocat/Hello-World`). Catches transport-layer surprises that mocked tests cannot — e.g. the GitHub auth requirement that PR `manomatika/ahimsa#28` shipped without auth handling. Tests are marked `@pytest.mark.integration` and **excluded from the default `pytest tests/` run** via `addopts = "-m 'not integration'"` in `pyproject.toml`. Opt in with `pytest -m integration`.

  The integration tier runs unauthenticated by design — every test repo it touches must be public. This guarantees the tier works in any developer environment without setup. If `GITHUB_TOKEN` happens to be set, the resolver attaches `Authorization` automatically; against public repos this is a no-op. The tests do not assume token presence or absence.

## Release Log Validation

`ahimsa.validate_releases` enforces RELEASES.md ↔ git tag consistency for any repo that opts in by having a `RELEASES.md` at its root. The check is bidirectional:

- Every git tag matching `vX.Y.Z` or `vX.Y.Z-PRERELEASE` MUST have a corresponding H2 entry in `RELEASES.md`.
- Every H2 entry in `RELEASES.md` MUST correspond to an actual git tag.
- Duplicate entries (same tag heading appearing twice) fail with a `releases.entry["<tag>"]: duplicate entry` error.

**Opt-in by file presence.** If a repo has no `RELEASES.md`, the check is a no-op (zero errors). No flag, no allowlist — file presence is the only signal. Repos that have not adopted the convention are not penalized.

**Audit point: HEAD, not the recipe's pinned tag.** The check fetches `RELEASES.md` and the tag list from the repo's default branch HEAD. When invoked transitively by `validate_recipe.validate(...)`, it asks "is this repo's release log currently consistent with its tag list?" — NOT "is the recipe's pinned snapshot consistent?". Drift in a repo's release log is worth flagging regardless of which tag the recipe pins. A future feature could add a `--at-ref <tag>` flag for historical audits.

**Parser.** Strict line-based regex on H2 headings: `^##[ \t]+(v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)[ \t]*$`. The schema preamble at the top of `RELEASES.md` is informational and ignored. Headings with trailing junk (`## v0.0.4 (notes)`) deliberately do not match — the convention requires the heading IS the tag name. Code-fence state is not tracked (Phase B candidate if it ever bites).

**Field-level validation is out of scope.** This validator's single invariant is tag↔entry presence. The `Date`, `Status`, `Artifact`, `PRs`, and `Summary` field formats are not parsed or checked. A separate `validate-entry-contents` check is a Phase B candidate.

**Status values are invisible.** A tag whose entry has `Status: failed` or `Status: superseded` still satisfies the bidirectional rule. The validator does not interpret status semantics — that's the job of human readers.

**Tag filtering.** Tags whose names do not match `^v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$` (e.g. `legacy-rev`, `release-1`) are ignored entirely; they neither require entries nor count as drift.

**CLI.** `ahimsa-validate-releases <repo-spec>` runs the check standalone. Exit codes match the rest of ahimsa: 0 clean, 1 drift, 2 configuration error.

**Transitive integration.** `ahimsa-validate <recipe>` invokes `validate_releases` for `matika.repo` and each `applugs[i].repo`. Errors flow into the same returned list with pointers like `matika.releases.tag["..."]` or `applugs[i].releases.entry["..."]`. This means a recipe-validation pass enforces release-log consistency across every repo the recipe pins.

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
- `recipe.json` is the sole source of truth for what ships.
- Standard Python `.gitignore` (GitHub's official Python template) is in place: covers `__pycache__/`, build/dist, `*.egg-info/`, `.pytest_cache/`, `.coverage`, `htmlcov/`, venv variants, `.tox/`, installer artifacts (`*.dmg`, `*.exe`, etc.), and OS/IDE noise. Never commit compiled artifacts.
