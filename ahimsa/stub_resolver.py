"""
stub_resolver.py — StubTagResolver for renderer and local tooling.

Q16b STUB: Live cross-repo tag query is stubbed per Q16b; wire in
manomatika/ahimsa#49 after #38-early lands.

The StubTagResolver is used wherever the renderer needs tag data for
placeholder emission checks. It is NOT used in production validation (the
real GitHubResolver handles that). The stub exists so the renderer can work
offline and in tests without network access.
"""

# Live cross-repo tag query is stubbed per Q16b; wire in
# manomatika/ahimsa#49 after #38-early lands.

_DEFAULT_STUB_TAGS: dict[str, list[str]] = {
    "matika": [
        "v0.0.1",
        "v0.0.2",
        "v0.0.3",
        "v0.0.4-dev.0",
        "v0.0.4-dev.1",
        "v0.0.4-dev.2",
    ],
    "eyerate": [
        "v0.0.1",
        "v0.0.2",
        "v0.0.3",
    ],
    "ahimsa": [],
}


class StubTagResolver:
    """Returns injected (or default) tag data without network access.

    Initialized with a dict mapping repo slug -> list of tag names. When
    list_tags is called, it returns the injected list for the given slug.
    If the slug is not in the dict, an empty list is returned.

    Usage:
        resolver = StubTagResolver()
        tags = resolver.list_tags("matika")
        # -> ["v0.0.1", "v0.0.2", "v0.0.3", ...]

    To inject custom data (e.g. in tests):
        resolver = StubTagResolver({"matika": ["v0.0.1"], "eyerate": []})
    """

    def __init__(
        self,
        tags: dict[str, list[str]] | None = None,
    ) -> None:
        self._tags = dict(tags) if tags is not None else dict(_DEFAULT_STUB_TAGS)

    def list_tags(self, repo_slug: str) -> list[str]:
        """Return the tag list for *repo_slug*, or [] if not in the stub data."""
        return list(self._tags.get(repo_slug, []))
