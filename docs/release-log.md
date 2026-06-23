> Part of [CLAUDE.md](../CLAUDE.md) — see the main file for orientation.

**Per-tag documentation triad.** CLAUDE.md, `CHANGELOG.md`, and `RELEASES.md`
are updated for EVERY tag — both rc and final. (CHANGELOG.md is per-repo;
`RELEASES.md` is generated from `manomatika/manomatika`'s `release-log.yaml` —
see *Release-Notes System & Central Release Log* below.)

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
