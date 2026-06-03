"""
releases_grammar.py — shared regex and slug utilities for RELEASES.md parsing.

Centralised here so validate_releases.py and release_log.py both use the same
patterns, and so tests can import them directly without going through the higher-
level modules.
"""

import re


# H2 heading whose content is a repo slug followed by a tag name.
# Example: '## matika v0.0.4-dev.1' captures ('matika', 'v0.0.4-dev.1').
# Headings with trailing junk ('## matika v0.0.4 (notes)') deliberately do NOT
# match — convention says the heading IS "<slug> <tag>", nothing else.
HEADING_RE = re.compile(
    r'^##[ \t]+([a-z][a-z0-9-]*)[ \t]+(v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)[ \t]*$'
)

# Tag-name regex used to filter the repo's tag list. Tags that don't match
# (e.g. 'legacy-rev', 'release-1') are out of scope for the validator.
TAG_RE = re.compile(r'^v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$')


def slug_from_repo(repo_spec: str) -> str:
    """Derive the slug from a full repo spec.

    Examples:
        'github.com/manomatika/matika' -> 'matika'
        'github.com/manomatika/Matika' -> 'matika'  (lowercased defensively)

    The slug is the last path segment, lowercased. After the org migration
    (#38-early) repo names are expected to be lowercase; the defensive lower()
    here ensures correctness regardless of case in the spec.
    """
    last_segment = repo_spec.rstrip("/").rsplit("/", 1)[-1]
    return last_segment.lower()
