"""
render_releases_md.py — render RELEASES.md from release-log.yaml + live tags.

PR-time render: run this script before opening a release PR to regenerate
RELEASES.md from the YAML source of truth. The generated RELEASES.md is
committed in the same PR so the file stays in sync with the YAML.

Paths default to the repo root but are overridable via env vars so the
refresh-releases-md CI job can point them at a manomatika/manomatika checkout:

    RELEASE_LOG_PATH=mm/release-log.yaml
    RELEASES_MD_PATH=mm/RELEASES.md
    python scripts/render_releases_md.py

Live tags are fetched from GitHub via GitHubResolver. Set GITHUB_TOKEN or
GH_TOKEN for authenticated requests (required for private repos; rate-limiting
applies for unauthenticated calls to public repos).

Usage:
    python scripts/render_releases_md.py
    # Writes RELEASES.md to RELEASES_MD_PATH (default: repo root).
    # Exits 1 if any live tag has no YAML record.
"""

import os
import sys
from pathlib import Path

# Allow running directly from the repo root without installing.
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from ahimsa.release_log import load_release_log, render_releases_md
from ahimsa.validate_recipe import GitHubResolver

RELEASE_LOG_PATH = Path(os.environ.get("RELEASE_LOG_PATH", str(_REPO_ROOT / "release-log.yaml")))
RELEASES_MD_PATH = Path(os.environ.get("RELEASES_MD_PATH", str(_REPO_ROOT / "RELEASES.md")))

_REPOS = {
    "matika": "github.com/manomatika/matika",
    "eyerate": "github.com/manomatika/eyerate",
    "ahimsa": "github.com/manomatika/ahimsa",
}


def main() -> int:
    # Load the YAML source of truth.
    entries = load_release_log(RELEASE_LOG_PATH)

    # Fetch live tag lists from GitHub (closes manomatika/ahimsa#49).
    resolver = GitHubResolver()
    live_tags: dict[str, list[str]] = {}
    for slug, repo_spec in _REPOS.items():
        live_tags[slug] = resolver.list_tags(repo_spec)

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
