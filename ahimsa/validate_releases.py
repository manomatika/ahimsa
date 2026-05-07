"""
validate_releases.py — enforces RELEASES.md ↔ git tag consistency.

For a repo that has a `RELEASES.md` at its root, every git tag of the form
`vX.Y.Z` or `vX.Y.Z-PRERELEASE` must have a corresponding H2 entry in
RELEASES.md, and every entry must correspond to an actual tag. The audit
runs at the repo's default-branch HEAD — it asks "is this repo's release
log currently consistent with its tag list?", regardless of any specific
recipe pin. See ahimsa's CLAUDE.md "Release Log Validation" for rationale.

Opt-in by file presence: a repo without RELEASES.md is a no-op.

Usage:
  ahimsa-validate-releases github.com/manomatika/Matika
  python3 -m ahimsa.validate_releases github.com/manomatika/Matika

Exit codes:
  0 — clean (or RELEASES.md absent)
  1 — drift detected
  2 — configuration error
"""

import re
import sys
from collections import Counter
from pathlib import Path

from ahimsa._config import load_allowed_hosts
from ahimsa.validate_recipe import BaseResolver, Error, resolver_for


# H2 heading whose entire content is a tag name (with leading 'v').
# Example: '## v0.0.4-dev.1' captures 'v0.0.4-dev.1'.
# Headings with trailing junk ('## v0.0.4 (notes)') deliberately do NOT
# match — convention says the heading IS the tag name, nothing else.
_HEADING_RE = re.compile(
    r'^##[ \t]+(v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)[ \t]*$'
)

# Tag-name regex used to filter the repo's tag list. Tags that don't match
# (e.g. 'legacy-rev', 'release-1') are out of scope for this validator.
_TAG_RE = re.compile(r'^v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$')


def parse_entries(text: str) -> list[str]:
    """Return the tag names found as H2 headings in *text*, in document order.

    Duplicates are preserved (the caller deduplicates and reports them).
    Anything that isn't a matching H2 heading is silently ignored — the
    schema preamble, prose fields, separators, etc.

    Code-fence state is not tracked. RELEASES.md is human prose; in practice
    fenced blocks containing literal '## v...' lines do not occur. Phase B
    candidate if it ever bites.
    """
    entries: list[str] = []
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            entries.append(m.group(1))
    return entries


def validate_releases(
    repo: str,
    *,
    resolvers: dict[str, BaseResolver] | None = None,
    allowed_hosts: list[str] | None = None,
) -> list[Error]:
    """Audit *repo*'s RELEASES.md against its git tag list at HEAD.

    repo:           '<host>/<owner>/<repo>'
    resolvers:      host -> resolver instance map; tests inject mocks here
    allowed_hosts:  direct override; bypasses config-file walk-up

    Returns a (possibly empty) list of Error objects with pointers like
    'releases.tag["<tag>"]' or 'releases.entry["<tag>"]'.

    No-op (returns []) if RELEASES.md is absent at HEAD.
    """
    errors: list[Error] = []

    # --- Resolver dispatch ---
    if resolvers is not None:
        host = repo.split("/", 1)[0]
        res = resolvers.get(host)
        if res is None:
            errors.append(Error("releases.repo", f'no resolver for host "{host}"'))
            return errors
    else:
        if allowed_hosts is None:
            allowed_hosts = ["github.com"]
        try:
            res = resolver_for(repo, allowed_hosts=allowed_hosts)
        except (PermissionError, LookupError) as e:
            errors.append(Error("releases.repo", str(e)))
            return errors

    # --- Fetch RELEASES.md at HEAD ---
    try:
        text = res.fetch_text(repo, "HEAD", "RELEASES.md")
    except Exception as e:
        errors.append(Error("releases.fetch", f"could not fetch RELEASES.md: {e}"))
        return errors

    if text is None:
        # Opt-in by file presence: repo without RELEASES.md is a no-op.
        return errors

    entries = parse_entries(text)

    # --- Duplicate detection ---
    counts = Counter(entries)
    for tag in sorted(t for t, n in counts.items() if n > 1):
        errors.append(Error(f'releases.entry["{tag}"]', "duplicate entry"))

    entry_set = set(entries)

    # --- Fetch tags ---
    try:
        all_tags = res.list_tags(repo)
    except Exception as e:
        errors.append(Error("releases.tags", f"could not list tags: {e}"))
        return errors

    # Filter to in-scope tags only — non-conforming names are ignored.
    tag_set = {t for t in all_tags if _TAG_RE.match(t)}

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

    parser = argparse.ArgumentParser(
        prog="ahimsa-validate-releases",
        description=(
            "Audit a repo's RELEASES.md against its git tag list at HEAD. "
            "Opt-in by file presence; no-op if RELEASES.md is absent."
        ),
    )
    parser.add_argument(
        "repo",
        help='repository spec, e.g. "github.com/manomatika/Matika"',
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

    errors = validate_releases(args.repo, allowed_hosts=allowed_hosts)

    for err in errors:
        print(err)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
