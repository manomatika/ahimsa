"""
release_log.py — YAML-driven release log loader and RELEASES.md renderer.

The central release log lives in release-log.yaml in manomatika/manomatika
(product authority). This module provides:
  - ReleaseEntry: dataclass for a single release record
  - load_release_log(path): reads release-log.yaml -> list[ReleaseEntry]
  - render_releases_md(entries, live_tags): renders RELEASES.md content

For a (repo, tag) that exists in live_tags but NOT in entries: a templated
placeholder entry is emitted and a warning is printed to stderr. For an
entry with no matching live tag: still rendered (breadcrumb tags may be
absent from git but retained in the log per the convention).

The live_tags dict is populated by the caller. render_releases_md.py uses
GitHubResolver to fetch live tag lists (manomatika/ahimsa#49 wired).
"""

from __future__ import annotations

import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ReleaseEntry:
    """A single release record from release-log.yaml."""
    repo: str
    tag: str
    date: str
    status: str
    artifact: str
    prs: str
    summary: str
    deleted_tag: bool = False
    pending: bool = False


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


_REQUIRED_FIELDS = ("repo", "tag", "date", "status", "artifact", "prs", "summary")


def _coerce_bool_field(value: Any, field: str, index: int, item: dict) -> bool:
    """Strictly interpret an entry's optional boolean exemption field.

    Both ``deleted_tag`` and ``pending`` are audit-integrity fields: each
    SUPPRESSES the "entry but no tag" safety check, so a misparse toward
    exemption is the dangerous direction. A permissive ``bool(value)`` would
    coerce the quoted YAML string ``"false"`` to ``True`` (Python truthiness),
    wrongly exempting an entry. We therefore accept ONLY a genuine YAML boolean
    or absence:

      - absent / null  -> False
      - real bool      -> that bool
      - anything else  -> ValueError naming the field, entry, and offending value
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    label = f"{item.get('repo', '?')} {item.get('tag', '?')}"
    raise ValueError(
        f"release-log.yaml entry [{index}] ({label}): '{field}' must be a "
        f"YAML boolean (true/false) or absent, got {value!r}"
    )


def parse_release_log_text(text: str) -> list[ReleaseEntry]:
    """Parse release-log.yaml *content* (a string) into ReleaseEntry objects.

    Requires PyYAML. Raises ImportError if pyyaml is not installed; ValueError
    if the YAML is malformed, missing required fields, carries a non-boolean
    ``deleted_tag``/``pending`` value (strict parsing — see
    ``_coerce_bool_field``), or marks an entry as BOTH ``deleted_tag: true`` and
    ``pending: true`` (a contradiction — a release cannot be simultaneously
    not-yet-created and deleted).
    """
    try:
        import yaml
    except ImportError as e:
        raise ImportError(
            "pyyaml is required to parse release-log.yaml. "
            "Install it with: pip install pyyaml"
        ) from e

    raw: Any = yaml.safe_load(text)

    if not isinstance(raw, dict) or "entries" not in raw:
        raise ValueError("release-log.yaml must have a top-level 'entries' key")

    entries: list[ReleaseEntry] = []
    for i, item in enumerate(raw["entries"]):
        missing = [f for f in _REQUIRED_FIELDS if f not in item]
        if missing:
            raise ValueError(
                f"release-log.yaml entry [{i}] missing required fields: {missing}"
            )
        deleted_tag = _coerce_bool_field(item.get("deleted_tag"), "deleted_tag", i, item)
        pending = _coerce_bool_field(item.get("pending"), "pending", i, item)
        if deleted_tag and pending:
            label = f"{item.get('repo', '?')} {item.get('tag', '?')}"
            raise ValueError(
                f"release-log.yaml entry [{i}] ({label}): 'deleted_tag' and "
                f"'pending' cannot both be true — a release cannot be "
                f"simultaneously not-yet-created (pending) and deleted."
            )
        entries.append(ReleaseEntry(
            repo=str(item["repo"]),
            tag=str(item["tag"]),
            date=str(item["date"]),
            status=str(item["status"]),
            artifact=str(item["artifact"]),
            prs=str(item["prs"]),
            summary=str(item["summary"]).strip(),
            deleted_tag=deleted_tag,
            pending=pending,
        ))
    return entries


def load_release_log(path: str | Path) -> list[ReleaseEntry]:
    """Read *path* (release-log.yaml) and return a list of ReleaseEntry objects.

    Delegates parsing to ``parse_release_log_text`` (DRY); this function only
    handles file I/O and decorates parse errors with the file path.

    Requires PyYAML. Raises ImportError if pyyaml is not installed.
    Raises FileNotFoundError if *path* does not exist.
    Raises ValueError if the YAML is malformed or missing required fields.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"release-log.yaml not found at {path}")

    text = path.read_text()
    try:
        return parse_release_log_text(text)
    except ValueError as e:
        raise ValueError(f"{e} (in {path})") from e


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def render_releases_md(
    entries: list[ReleaseEntry],
    live_tags: dict[str, list[str]],
) -> str:
    """Render RELEASES.md content from *entries* and *live_tags*.

    entries:   list of ReleaseEntry objects from release-log.yaml
    live_tags: {repo_slug: [tag, ...]} — tags known to exist in each repo.
               Provided by StubTagResolver (Q16b) until manomatika/ahimsa#49.

    Entries are rendered newest-first (as they appear in release-log.yaml —
    callers are responsible for ordering the input list newest-first).

    For a (repo, tag) that exists in live_tags but NOT in entries: a
    placeholder entry is emitted and a warning is printed to stderr.

    For an entry with no matching live tag: still rendered (breadcrumb tags
    may be absent from git but retained in the log per the convention).

    Headings use the two-part form ``## <repo> <tag>``.
    """
    # Build a set of (repo, tag) pairs already covered by entries.
    covered: set[tuple[str, str]] = {(e.repo, e.tag) for e in entries}

    # Find live tags with no corresponding entry.
    orphan_live: list[tuple[str, str]] = []
    for repo_slug, tags in sorted(live_tags.items()):
        for tag in tags:
            if (repo_slug, tag) not in covered:
                orphan_live.append((repo_slug, tag))
                print(
                    f"WARNING: live tag {repo_slug}/{tag} has no entry in "
                    "release-log.yaml — emitting placeholder",
                    file=sys.stderr,
                )

    # Build the rendered lines list.
    lines: list[str] = []
    lines.append("# Releases")
    lines.append("")
    lines.append(
        "Canonical log of every git tag pushed from component repositories. "
        "Entries use the form `## <repo> <tag>` so a single file covers all "
        "repos in the ecosystem. Every tag matching `vX.Y.Z` or "
        "`vX.Y.Z-PRERELEASE` must have an entry here; entries for "
        "failed-publish tags are retained as audit breadcrumbs. "
        "Entries are listed newest-first."
    )
    lines.append("")
    lines.append(
        "The tag/entry consistency rule is enforced by `ahimsa-validate-releases`."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    for entry in entries:
        lines.append(f"## {entry.repo} {entry.tag}")
        lines.append("")
        lines.append(f"- **Date:** {entry.date}")
        lines.append(f"- **Status:** {entry.status}")
        lines.append(f"- **Artifact:** {entry.artifact}")
        lines.append(f"- **PRs:** {entry.prs}")
        # Wrap summary at ~80 chars for readability; re-indent continuation lines.
        summary_lines = textwrap.wrap(entry.summary, width=78)
        if summary_lines:
            lines.append(f"- **Summary:** {summary_lines[0]}")
            for cont in summary_lines[1:]:
                lines.append(f"  {cont}")
        else:
            lines.append(f"- **Summary:** {entry.summary}")
        lines.append("")

    # Emit placeholder entries for live tags with no log entry.
    for repo_slug, tag in orphan_live:
        lines.append(f"## {repo_slug} {tag}")
        lines.append("")
        lines.append(f"- **Date:** (unknown)")
        lines.append(f"- **Status:** (unknown — auto-generated placeholder)")
        lines.append(f"- **Artifact:** (unknown)")
        lines.append(f"- **PRs:** (unknown)")
        lines.append(f"- **Summary:** Auto-generated placeholder for {repo_slug} {tag}.")
        lines.append(
            "  This entry was created because the tag exists in the repo but "
            "has no record in release-log.yaml. Update release-log.yaml to "
            "replace this placeholder."
        )
        lines.append("")

    return "\n".join(lines)
