# Releases

Canonical log of every git tag pushed from component repositories. Entries use the form `## <repo> <tag>` so a single file covers all repos in the ecosystem. Every tag matching `vX.Y.Z` or `vX.Y.Z-PRERELEASE` must have an entry here; entries for failed-publish tags are retained as audit breadcrumbs. Entries are listed newest-first.

The tag/entry consistency rule is enforced by `ahimsa-validate-releases`.

---

## matika v0.0.4-dev.2

- **Date:** 2026-05-07
- **Status:** published
- **Artifact:** @manomatika/matika-frontend@0.0.4-dev.2 (GitHub Packages)
- **PRs:** manomatika/matika#37
- **Summary:** Adds the import map entry for @manomatika/matika-frontend in matika's
  base.html. Applugs (eyerate first) can now import the package via bare
  specifier; matika owns the URL mapping centrally so applugs do not hardcode
  /static/js/index.js. Package contents are unchanged from v0.0.4-dev.1 — the
  bump exists for ecosystem version coherence under the convention that
  committed-tree changes get their own prerelease-bumped tag.

## matika v0.0.4-dev.1

- **Date:** 2026-05-06
- **Status:** published
- **Artifact:** @manomatika/matika-frontend@0.0.4-dev.1 (GitHub Packages)
- **PRs:** manomatika/matika@23de78d (direct-to-main lockfile fix; no PR opened)
- **Summary:** First successful publish of @manomatika/matika-frontend. Establishes the
  public TypeScript surface for applugs to consume: MaintenanceActivityManager,
  ActivityMetadata, getCsrfToken, injectCsrfToken. Tagged from a direct-to-main
  commit that committed the previously-missing package-lock.json. Future
  lockfile changes must follow standard branch + PR discipline.

## matika v0.0.4-dev.0

- **Date:** 2026-05-06
- **Status:** superseded (by matika v0.0.4-dev.1)
- **Artifact:** none (publish failed; breadcrumb only)
- **PRs:** manomatika/matika#35
- **Summary:** First attempted publish of @manomatika/matika-frontend. The publish workflow
  failed in npm ci because package-lock.json was not committed to the
  repository. Tag retained as audit breadcrumb; superseded by v0.0.4-dev.1 which
  committed the lockfile and republished successfully.

## matika v0.0.3

- **Date:** 2026-04-28
- **Status:** published
- **Artifact:** none (pre-RELEASES.md historical release)
- **PRs:** (pre-RELEASES.md historical release)
- **Summary:** Pre-RELEASES.md historical release. See git log for commit details.

## matika v0.0.2

- **Date:** 2026-04-27
- **Status:** published
- **Artifact:** none (pre-RELEASES.md historical release)
- **PRs:** (pre-RELEASES.md historical release)
- **Summary:** Pre-RELEASES.md historical release. See git log for commit details.

## matika v0.0.1

- **Date:** 2026-04-18
- **Status:** published
- **Artifact:** none (pre-RELEASES.md historical release)
- **PRs:** (pre-RELEASES.md historical release)
- **Summary:** Pre-RELEASES.md historical release. See git log for commit details.

## eyerate v0.0.3

- **Date:** 2026-04-28
- **Status:** published
- **Artifact:** none (placeholder)
- **PRs:** (placeholder — to be filled)
- **Summary:** Placeholder entry. Summary to be filled before v0.0.1 release.

## eyerate v0.0.2

- **Date:** 2026-04-27
- **Status:** published
- **Artifact:** none (placeholder)
- **PRs:** (placeholder — to be filled)
- **Summary:** Placeholder entry. Summary to be filled before v0.0.1 release.

## eyerate v0.0.1

- **Date:** 2026-04-18
- **Status:** published
- **Artifact:** none (placeholder)
- **PRs:** (placeholder — to be filled)
- **Summary:** Placeholder entry. Summary to be filled before v0.0.1 release.

## ahimsa v0.0.1

- **Date:** (pending)
- **Status:** (pending — tag not yet pushed)
- **Artifact:** none (pending)
- **PRs:** (pending)
- **Summary:** Placeholder entry for ahimsa v0.0.1. To be filled at release time.

