"""
validate_releases.py — enforces RELEASES.md ↔ git tag consistency.

The central RELEASES.md lives in ahimsa (this repo). It logs releases for all
repos in the manomatika ecosystem, using ``## <repo-slug> <tag>`` headings
(e.g. ``## matika v0.0.4``). The validator fetches RELEASES.md once from
ahimsa and runs per-repo bidirectional consistency against each repo's tag list
at HEAD.

Opt-in by file presence: if RELEASES.md is absent from ahimsa, the validator
is a no-op.

Each repo in the set is validated independently:
  - Every tag of the form vX.Y.Z or vX.Y.Z-PRERELEASE in that repo's tag list
    must have a corresponding ``## <slug> <tag>`` entry in RELEASES.md.
  - Every ``## <slug> <tag>`` entry must correspond to an actual tag in that
    repo's tag list (breadcrumb tags retained intentionally may appear as
    orphan entries — these are expected false-positives per the convention).

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
    """Audit RELEASES.md (in ahimsa) against git tag lists for all repos.

    repos:          list of '<host>/<owner>/<repo>' specs to audit
    ahimsa_repo:    '<host>/<owner>/<repo>' spec for the ahimsa repo that holds
                    RELEASES.md; defaults to github.com/manomatika/ahimsa (or
                    derived from GITHUB_REPOSITORY env var in CI). The caller
                    may override for testing.
    resolvers:      host -> resolver instance map; tests inject mocks here
    allowed_hosts:  direct override; bypasses config-file walk-up

    Returns a (possibly empty) list of Error objects with pointers like
    'releases.tag["<tag>"]' or 'releases.entry["<tag>"]'.

    No-op (returns []) if RELEASES.md is absent from ahimsa at HEAD.
    """
    errors: list[Error] = []

    if not repos:
        return errors

    # --- Determine ahimsa repo spec for RELEASES.md fetch ---
    if ahimsa_repo is None:
        # In CI the GITHUB_REPOSITORY env var is set to 'owner/repo'. The host
        # is always github.com for our ecosystem; prepend it.
        env_repo = os.environ.get("GITHUB_REPOSITORY", "")
        if env_repo:
            ahimsa_repo = f"github.com/{env_repo}"
        else:
            ahimsa_repo = "github.com/manomatika/ahimsa"

    ahimsa_host = ahimsa_repo.split("/", 1)[0]

    # --- Resolver for ahimsa (RELEASES.md fetch) ---
    if resolvers is not None:
        ahimsa_res = resolvers.get(ahimsa_host)
        if ahimsa_res is None:
            errors.append(Error("releases.repo", f'no resolver for host "{ahimsa_host}"'))
            return errors
    else:
        if allowed_hosts is None:
            allowed_hosts = ["github.com"]
        try:
            ahimsa_res = resolver_for(ahimsa_repo, allowed_hosts=allowed_hosts)
        except (PermissionError, LookupError) as e:
            errors.append(Error("releases.repo", str(e)))
            return errors

    # --- Fetch RELEASES.md from ahimsa at HEAD ---
    try:
        text = ahimsa_res.fetch_text(ahimsa_repo, "HEAD", "RELEASES.md")
    except Exception as e:
        errors.append(Error("releases.fetch", f"could not fetch RELEASES.md: {e}"))
        return errors

    if text is None:
        # Opt-in by file presence: no RELEASES.md → no-op.
        return errors

    all_entries = parse_entries(text)

    # --- Per-repo validation ---
    for repo_spec in repos:
        slug = slug_from_repo(repo_spec)
        repo_host = repo_spec.split("/", 1)[0]

        # Resolver for this repo's tags
        if resolvers is not None:
            res = resolvers.get(repo_host)
            if res is None:
                errors.append(Error("releases.repo", f'no resolver for host "{repo_host}"'))
                continue
        else:
            try:
                res = resolver_for(repo_spec, allowed_hosts=allowed_hosts)
            except (PermissionError, LookupError) as e:
                errors.append(Error("releases.repo", str(e)))
                continue

        # Entries for this slug
        slug_entries = [(s, t) for s, t in all_entries if s == slug]

        # --- Duplicate detection (per slug) ---
        tag_counts = Counter(t for _, t in slug_entries)
        for tag in sorted(t for t, n in tag_counts.items() if n > 1):
            errors.append(Error(f'releases.entry["{tag}"]', "duplicate entry"))

        entry_set = {t for _, t in slug_entries}

        # --- Fetch tags for this repo ---
        try:
            all_tags = res.list_tags(repo_spec)
        except Exception as e:
            errors.append(Error("releases.tags", f"could not list tags: {e}"))
            continue

        # Filter to in-scope tags only — non-conforming names are ignored.
        tag_set = {t for t in all_tags if TAG_RE.match(t)}

        # --- Bidirectional consistency (deterministic ordering) ---
        for tag in sorted(tag_set - entry_set):
            errors.append(Error(
                f'releases.tag["{tag}"]',
                "tag exists but no entry in RELEASES.md",
            ))

        for tag in sorted(entry_set - tag_set):
            errors.append(Error(
                f'releases.entry["{tag}"]',
                "entry in RELEASES.md but tag does not exist",
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
            "Audit RELEASES.md (in ahimsa) against git tag lists for all repos. "
            "Opt-in by file presence; no-op if RELEASES.md is absent. "
            "Repos are derived from recipe.json if not supplied on the command line."
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
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
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
