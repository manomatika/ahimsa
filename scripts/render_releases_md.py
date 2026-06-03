"""
render_releases_md.py — render RELEASES.md from release-log.yaml + stub tags.

PR-time render: this script is run by the developer before opening a release
PR (it is NOT a CI step itself — the CI step just validates with
ahimsa-validate-releases). The generated RELEASES.md is committed as part of
the release PR so the file stays in sync with the YAML source of truth.

Q16b STUB: live cross-repo tag data comes from StubTagResolver until
manomatika/ahimsa#49 after #38-early lands. Update this script to use the
live GitHubResolver when wiring that issue.

Usage:
    python scripts/render_releases_md.py
    # Writes RELEASES.md to the repo root.
    # Exits 1 if any live tag has no YAML record.
"""

import sys
from pathlib import Path

# Allow running directly from the repo root without installing.
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from ahimsa.release_log import load_release_log, render_releases_md
from ahimsa.stub_resolver import StubTagResolver

RELEASE_LOG_PATH = _REPO_ROOT / "release-log.yaml"
RELEASES_MD_PATH = _REPO_ROOT / "RELEASES.md"


def main() -> int:
    # Load the YAML source of truth.
    entries = load_release_log(RELEASE_LOG_PATH)

    # Build live_tags from the stub resolver (Q16b).
    # Live cross-repo tag query is stubbed per Q16b; wire in
    # manomatika/ahimsa#49 after #38-early lands.
    resolver = StubTagResolver()
    live_tags: dict[str, list[str]] = {}
    for slug in ("matika", "eyerate", "ahimsa"):
        live_tags[slug] = resolver.list_tags(slug)

    # Check: every live tag must have a YAML record.
    covered = {(e.repo, e.tag) for e in entries}
    missing_records: list[tuple[str, str]] = []
    for slug, tags in live_tags.items():
        for tag in tags:
            if (slug, tag) not in covered:
                missing_records.append((slug, tag))

    if missing_records:
        for slug, tag in missing_records:
            print(
                f"ERROR: live tag {slug}/{tag} has no record in release-log.yaml",
                file=sys.stderr,
            )
        print(
            "Add the missing entries to release-log.yaml before rendering.",
            file=sys.stderr,
        )
        return 1

    # Render and write RELEASES.md.
    content = render_releases_md(entries, live_tags=live_tags)
    RELEASES_MD_PATH.write_text(content + "\n")
    print(f"Written: {RELEASES_MD_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
