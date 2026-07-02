"""
validate_releases.py — enforces RELEASES.md ↔ git tag consistency.

The central RELEASES.md lives in manomatika/manomatika (the product-authority
repo). It logs releases for all repos in the manomatika ecosystem, using
``## <repo-slug> <tag>`` headings (e.g. ``## matika v0.0.4``). The validator
fetches RELEASES.md once from manomatika/manomatika and runs per-repo
bidirectional consistency against each repo's tag list at HEAD.

Opt-in by file presence: if RELEASES.md is absent from manomatika/manomatika,
the validator is a no-op.

Each repo in the set is validated independently:
  - Every tag of the form vX.Y.Z or vX.Y.Z-PRERELEASE in that repo's tag list
    must have a corresponding ``## <slug> <tag>`` entry in RELEASES.md.
  - Every ``## <slug> <tag>`` entry must correspond to an actual tag in that
    repo's tag list, UNLESS the entry is marked ``deleted_tag: true`` (a
    BACKWARD-looking breadcrumb for a tag that existed and was intentionally
    removed) or ``pending: true`` (a FORWARD-looking placeholder for a release
    that does not exist YET) in release-log.yaml. The validator fetches
    release-log.yaml from manomatika/manomatika and builds the exemption set
    automatically. The opposite direction — live tag with no entry — is always
    enforced regardless of any ``deleted_tag``/``pending`` marking.

The repo set is derived by the CALLER and passed in — ``validate_releases``
does not read recipe.json itself. This keeps the function pure and testable.
The CLI entrypoint reads recipe.json if no repos are given on the command line.

Usage:
  ahimsa-validate-releases github.com/manomatika/matika
  ahimsa-validate-releases github.com/manomatika/matika github.com/manomatika/eyerate
  python3 -m ahimsa.validate_releases github.com/manomatika/matika

Exit codes:
  0 — clean (or RELEASES.md absent)
  1 — drift detected
  2 — configuration error
"""

import os
import sys
from collections import Counter
from pathlib import Path

from ahimsa import error_code_constants as ec
from ahimsa._config import load_allowed_hosts
from ahimsa.releases_grammar import HEADING_RE, TAG_RE, slug_from_repo
from ahimsa.validate_recipe import BaseResolver, Error, resolver_for


def parse_entries(text: str) -> list[tuple[str, str]]:
    """Return (repo_slug, tag) pairs found as H2 headings in *text*, in order.

    Duplicates are preserved (the caller deduplicates and reports them).
    Anything that isn't a matching ``## <slug> <tag>`` heading is silently
    ignored — the schema preamble, prose fields, separators, etc.

    Code-fence state is not tracked. RELEASES.md is human prose; in practice
    fenced blocks containing literal '## matika v...' lines do not occur.
    """
    entries: list[tuple[str, str]] = []
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            entries.append((m.group(1), m.group(2)))
    return entries


def validate_releases(
    repos: list[str],
    *,
    ahimsa_repo: str | None = None,
    resolvers: dict[str, BaseResolver] | None = None,
    allowed_hosts: list[str] | None = None,
) -> list[Error]:
    """Audit RELEASES.md (in manomatika/manomatika) against git tag lists for all repos.

    repos:          list of '<host>/<owner>/<repo>' specs to audit
    ahimsa_repo:    '<host>/<owner>/<repo>' spec for the repo that holds
                    RELEASES.md; defaults to github.com/manomatika/manomatika.
                    Parameter named 'ahimsa_repo' for backward compatibility;
                    it now refers to the product-authority repo (mm). The caller
                    may override for testing.
    resolvers:      host -> resolver instance map; tests inject mocks here
    allowed_hosts:  direct override; bypasses config-file walk-up

    Returns a (possibly empty) list of Error objects with pointers like
    'releases.tag["<tag>"]' or 'releases.entry["<tag>"]'.

    No-op (returns []) if RELEASES.md is absent from manomatika/manomatika at HEAD.

    Exemptions: entries with ``deleted_tag: true`` (backward-looking — a tag that
    existed and was intentionally removed) or ``pending: true`` (forward-looking
    — a release that does not exist YET) in release-log.yaml (fetched from the
    same repo, with the same resolver, as RELEASES.md) are EXEMPT from the "entry
    but no tag" check. Both exemptions are one-directional: each can only suppress
    an "entry but no tag" error, never a "tag but no entry" error (Category A is
    always enforced). If an exempted entry's tag NOW exists on the remote, a
    stderr WARNING is emitted so the stale marking is corrected. Building the
    exemption set is fail-open: if release-log.yaml is absent or malformed (incl.
    a contradictory ``deleted_tag: true`` + ``pending: true`` entry, which raises)
    the set collapses to empty, so legitimately-absent breadcrumbs/placeholders
    surface their pre-fix error LOUDLY rather than being silently exempted.
    """
    errors: list[Error] = []

    if not repos:
        return errors

    # --- Determine repo spec for RELEASES.md fetch ---
    # RELEASES.md lives in manomatika/manomatika (product authority), not in ahimsa.
    if ahimsa_repo is None:
        ahimsa_repo = "github.com/manomatika/manomatika"

    ahimsa_host = ahimsa_repo.split("/", 1)[0]

    # --- Resolver for ahimsa (RELEASES.md fetch) ---
    if resolvers is not None:
        ahimsa_res = resolvers.get(ahimsa_host)
        if ahimsa_res is None:
            errors.append(Error("releases.repo", f'no resolver for host "{ahimsa_host}"', code=ec.AHIMSA_RELEASE_001))
            return errors
    else:
        # RELEASES.md always lives on github.com — bypass recipe's allowed_hosts for this fetch
        try:
            ahimsa_res = resolver_for(ahimsa_repo, allowed_hosts=["github.com"])
        except (PermissionError, LookupError) as e:
            errors.append(Error("releases.repo", str(e), code=ec.AHIMSA_RELEASE_002))
            return errors
        # Per-repo tag checks use the passed allowed_hosts (default to github.com if not specified)
        if allowed_hosts is None:
            allowed_hosts = ["github.com"]

    # --- Fetch RELEASES.md from ahimsa at HEAD (or MANOMATIKA_REF if set) ---
    # MANOMATIKA_REF is an optional env var that redirects the RELEASES.md and
    # release-log.yaml fetches to a specific branch/SHA — used by cross-repo
    # validation builds (ahimsa build.yml manomatika_ref input) so that a
    # not-yet-merged manomatika branch can be validated end-to-end without
    # requiring a push to main. Defaults to "HEAD" (repo default branch).
    _mm_ref = os.environ.get("MANOMATIKA_REF") or "HEAD"
    try:
        text = ahimsa_res.fetch_text(ahimsa_repo, _mm_ref, "RELEASES.md")
    except Exception as e:
        errors.append(Error("releases.fetch", f"could not fetch RELEASES.md: {e}", code=ec.AHIMSA_RELEASE_003))
        return errors

    if text is None:
        # Opt-in by file presence: no RELEASES.md → no-op.
        return errors

    # --- Build the Category-B exemption set from release-log.yaml ---
    # Two kinds of entry are exempt from the "entry but no tag" check:
    #   - deleted_tag: true — BACKWARD-looking breadcrumb (tag existed, removed)
    #   - pending: true     — FORWARD-looking placeholder (release not created yet)
    # Both are tracked separately so the right "...but the tag now exists"
    # WARNING is emitted; the union drives the actual Category-B exemption.
    # release-log.yaml is fetched with the SAME resolver, the SAME repo (mm), and
    # the SAME ref ("HEAD") as RELEASES.md above — the authoritative source.
    #
    # Fail-open: if release-log.yaml is missing or malformed, the exemption set
    # collapses to empty. With strict deleted_tag/pending parsing this is the
    # SAFE direction — a malformed (or contradictory deleted_tag+pending) value
    # makes legitimate breadcrumbs/placeholders error LOUDLY rather than being
    # silently and wrongly exempted.
    deleted_pairs: set[tuple[str, str]] = set()
    pending_pairs: set[tuple[str, str]] = set()
    try:
        rl_text = ahimsa_res.fetch_text(ahimsa_repo, _mm_ref, "release-log.yaml")
    except Exception:
        rl_text = None

    if rl_text is not None:
        try:
            from ahimsa.release_log import parse_release_log_text
            rl_entries = parse_release_log_text(rl_text)
            deleted_pairs = {(e.repo, e.tag) for e in rl_entries if e.deleted_tag}
            pending_pairs = {(e.repo, e.tag) for e in rl_entries if e.pending}
        except (ValueError, ImportError):
            deleted_pairs = set()
            pending_pairs = set()

    exempt_pairs: set[tuple[str, str]] = deleted_pairs | pending_pairs

    all_entries = parse_entries(text)

    # --- Per-repo validation ---
    for repo_spec in repos:
        slug = slug_from_repo(repo_spec)
        repo_host = repo_spec.split("/", 1)[0]

        # Resolver for this repo's tags
        if resolvers is not None:
            res = resolvers.get(repo_host)
            if res is None:
                errors.append(Error("releases.repo", f'no resolver for host "{repo_host}"', code=ec.AHIMSA_RELEASE_001))
                continue
        else:
            try:
                res = resolver_for(repo_spec, allowed_hosts=allowed_hosts)
            except (PermissionError, LookupError) as e:
                errors.append(Error("releases.repo", str(e), code=ec.AHIMSA_RELEASE_002))
                continue

        # Entries for this slug
        slug_entries = [(s, t) for s, t in all_entries if s == slug]

        # --- Duplicate detection (per slug) ---
        tag_counts = Counter(t for _, t in slug_entries)
        for tag in sorted(t for t, n in tag_counts.items() if n > 1):
            errors.append(Error(f'releases.entry["{tag}"]', "duplicate entry", code=ec.AHIMSA_RELEASE_004))

        entry_set = {t for _, t in slug_entries}

        # --- Fetch tags for this repo ---
        try:
            all_tags = res.list_tags(repo_spec)
        except Exception as e:
            errors.append(Error("releases.tags", f"could not list tags: {e}", code=ec.AHIMSA_RELEASE_005))
            continue

        # Filter to in-scope tags only — non-conforming names are ignored.
        tag_set = {t for t in all_tags if TAG_RE.match(t)}

        # --- Warn on stale exemptions: flag set but tag STILL exists ---
        # The entry/tag pair is consistent (no drift), so this is not an error —
        # only a data-quality issue worth surfacing for human attention. The
        # deleted_tag and pending cases get distinct messages.
        for tag in sorted(t for s, t in deleted_pairs if s == slug and t in tag_set):
            print(
                f"WARNING: {slug} {tag} is marked deleted_tag=true in "
                "release-log.yaml but the tag still exists on the remote. "
                "Remove deleted_tag: true if the tag is intentionally present.",
                file=sys.stderr,
            )
        for tag in sorted(t for s, t in pending_pairs if s == slug and t in tag_set):
            print(
                f"WARNING: {slug} {tag} is marked pending=true in "
                "release-log.yaml but the tag now exists on the remote — the "
                "release happened. Remove pending: true and fill in the entry.",
                file=sys.stderr,
            )

        # --- Bidirectional consistency (deterministic ordering) ---
        # Category A (tag but no entry) is UNCHANGED — never exempted.
        for tag in sorted(tag_set - entry_set):
            errors.append(Error(
                f'releases.tag["{tag}"]',
                "tag exists but no entry in RELEASES.md",
                code=ec.AHIMSA_RELEASE_006,
            ))

        # Category B (entry but no tag) — exempt deleted_tag breadcrumbs AND
        # pending forward-looking placeholders (exempt_pairs is their union).
        for tag in sorted(entry_set - tag_set):
            if (slug, tag) in exempt_pairs:
                continue  # intentionally-absent breadcrumb or pending placeholder: skip
            errors.append(Error(
                f'releases.entry["{tag}"]',
                "entry in RELEASES.md but tag does not exist",
                code=ec.AHIMSA_RELEASE_007,
            ))

    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="ahimsa-validate-releases",
        description=(
            "Audit RELEASES.md (in manomatika/manomatika) against git tag lists "
            "for all repos. Opt-in by file presence; no-op if RELEASES.md is "
            "absent. Repos are derived from recipe.json if not supplied on the "
            "command line."
        ),
    )
    parser.add_argument(
        "repos",
        nargs="*",
        metavar="REPO",
        help='repository specs, e.g. "github.com/manomatika/matika"',
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="explicit config.json — defaults to ['github.com'] if omitted",
    )
    args = parser.parse_args(argv)

    try:
        allowed_hosts = load_allowed_hosts(args.config)
    except FileNotFoundError as e:
        print(f"error: [{ec.AHIMSA_CLI_001}] {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"error: [{ec.AHIMSA_CLI_002}] {e}", file=sys.stderr)
        return 2

    repos = list(args.repos)

    if not repos:
        # Derive repo list from recipe.json if no repos given on the CLI.
        recipe_path = Path("recipes/reference-app/recipe.json")
        if recipe_path.exists():
            try:
                with open(recipe_path) as f:
                    recipe = json.load(f)
                matika_repo = recipe.get("matika", {}).get("repo")
                if matika_repo:
                    repos.append(matika_repo)
                for plug in recipe.get("applugs", []):
                    plug_repo = plug.get("repo")
                    if plug_repo:
                        repos.append(plug_repo)
            except (json.JSONDecodeError, KeyError):
                print("error: could not parse recipes/reference-app/recipe.json", file=sys.stderr)
                return 2

        # Always include ahimsa itself.
        env_repo = os.environ.get("GITHUB_REPOSITORY", "")
        if env_repo:
            ahimsa_slug = env_repo.rsplit("/", 1)[-1].lower()
            ahimsa_spec = f"github.com/manomatika/{ahimsa_slug}"
        else:
            ahimsa_spec = "github.com/manomatika/ahimsa"
        if ahimsa_spec not in repos:
            repos.append(ahimsa_spec)

    errors = validate_releases(repos, allowed_hosts=allowed_hosts)

    for err in errors:
        print(err)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
