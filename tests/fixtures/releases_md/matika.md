<!--
Snapshot of the central ahimsa RELEASES.md (matika entries only) as of 2026-05-07,
representing matika tags v0.0.4-dev.0 and v0.0.4-dev.1.

Updated from the old single-repo heading format (## v0.0.4-dev.1) to the new
two-part format (## matika v0.0.4-dev.1) when the central RELEASES.md moved
to ahimsa (PR feat/release-notes-system).

Do not auto-sync. This fixture is intentionally frozen to prevent test
flakiness as matika's release log evolves. The corresponding test
asserts that this snapshot's tag list (v0.0.4-dev.0, v0.0.4-dev.1)
round-trips cleanly through validate_releases -- that is the invariant
being tested, NOT matika's current state.

When matika ships future tags (v0.0.4-dev.2, v0.0.4, ...), this fixture
does NOT update. Only update if the schema or the representation
changes in a way that this real-world test should reflect.
-->

# Releases

Canonical log of every git tag pushed from component repositories.
Entries use the form ``## <repo-slug> <tag>`` so a single file serves
all repos in the ecosystem.

---

## matika v0.0.4-dev.1

- **Date:** 2026-05-06
- **Status:** published
- **Artifact:** `@manomatika/matika-frontend@0.0.4-dev.1` (GitHub Packages)
- **PRs:** manomatika/matika@23de78d (direct-to-main lockfile fix; no PR opened)
- **Summary:** First successful publish of `@manomatika/matika-frontend`.
  Establishes the public TypeScript surface for applugs to consume:
  `MaintenanceActivityManager`, `ActivityMetadata`, `getCsrfToken`,
  `injectCsrfToken`. Tagged from a direct-to-main commit that committed
  the previously-missing `package-lock.json`. Future lockfile changes
  must follow standard branch + PR discipline.

## matika v0.0.4-dev.0

- **Date:** 2026-05-06
- **Status:** superseded (by matika v0.0.4-dev.1)
- **Artifact:** none (publish failed; breadcrumb only)
- **PRs:** manomatika/matika#35
- **Summary:** First attempted publish of `@manomatika/matika-frontend`.
  The publish workflow failed in `npm ci` because `package-lock.json`
  was not committed to the repository. Tag retained as audit breadcrumb;
  superseded by v0.0.4-dev.1 which committed the lockfile and republished
  successfully.
