> Part of [CLAUDE.md](../CLAUDE.md) — see the main file for orientation.

## Resolver Protocol

`BaseResolver` is an ABC with a template-method `resolve(name, repo, tag) → AppLugManifest`. Subclasses implement `_canonicalize_repo()` and `_raw_url()`; `_parse_repo()`, `_fetch_json()`, and `_fetch_text()` are shared. `GitHubResolver` is the only concrete implementation today; a future `RegistryResolver` drops in at the M4 registry milestone without changing `validate()` call sites.

`BaseResolver` also requires two abstract release-log methods used by `validate_releases`:
- `list_tags(repo) -> list[str]` — returns all git tag names (without the `refs/tags/` prefix). Resolvers whose host has no tag concept return `[]`.
- `fetch_text(repo, ref, path) -> str | None` — returns the text content of `path` at `ref`, or `None` on 404. Resolvers whose host cannot serve arbitrary text files return `None` unconditionally.

Both are `@abstractmethod` rather than no-op defaults: silent no-op defaults would let release-log drift go undetected if a subclass forgot to implement either method. The abstract decl forces every `BaseResolver` subclass — production resolvers and test mocks alike — to make an explicit choice.

**Host dispatch** — `resolver_for(repo, allowed_hosts)` extracts the host from the repo string and looks it up in `_RESOLVER_REGISTRY`. Two distinct errors:
- Host not in `allowed_hosts` → `PermissionError` → error pointer `applugs[i].repo: host "X" not in allowed_hosts`
- Host in `allowed_hosts` but no registered resolver → `LookupError` → error pointer `applugs[i].repo: host "X" allowed but no resolver registered`

**GitHubResolver specifics** — `raw.githubusercontent.com` is case-sensitive on owner/repo paths. `GitHubResolver._canonicalize_repo()` resolves canonical casing via the GitHub API (which is case-insensitive) and caches the result per-process — recipes with multiple applugs from the same org hit the API once. `list_tags` calls `/repos/{owner}/{repo}/git/refs/tags` and follows `Link: rel="next"` pagination until exhausted (`per_page=100` per request, the API maximum). `fetch_text` reuses `_raw_url` + the shared `_fetch_text` helper.

**GitHub authentication** — `GitHubResolver.__init__` reads a token from the environment, with precedence `GITHUB_TOKEN` → `GH_TOKEN` (the gh-CLI legacy fallback). The token is stored as `self._token` and read once per resolver instance — mid-process env changes are not picked up. When a token is present, every outbound request from the resolver carries `Authorization: Bearer <token>`: the existence check, every paginated `list_tags` request, and the raw-content fetches via `_fetch_json` / `_fetch_text` (which consult `BaseResolver._request_headers()`, overridden on `GitHubResolver` to inject the auth header).

When no token is set the resolver makes unauthenticated requests — public repos still work, private repos 404. The `_canonicalize_repo` 404 handler distinguishes the two cases by token presence: with a token, the message stays `repository "..." not found on GitHub`; without a token, it appends `(or no access — set GITHUB_TOKEN if this is a private repo)`. The hint is applied ONLY at `_canonicalize_repo` because `list_tags` 404 has a legitimate "zero tags" meaning (auth is upstream-disambiguated by `_canonicalize_repo`) and the raw-content 404s mean "file does not exist at this ref".

The token value is never logged and never appears in any error message — only its env-var name is referenced in the auth hint. The token leaves the resolver only via the outbound `Authorization` header.

**Testing** — Two tiers. Both run as part of the full suite — `pytest` exercises everything, nothing is deselected by default (standing rule 21):

- **Unit tier** — `tests/test_validate_recipe.py`, `tests/test_validate_releases.py`. Tests inject `BaseResolver` subclasses via `validate(..., resolvers={"github.com": mock})` for protocol-contract checks, or patch `requests.get` directly to assert HTTP-layer details (headers, pagination, etc.). Mock resolvers must be genuine `BaseResolver` subclasses (not duck-typed) so interface changes are caught at test time. Runs offline.

- **Integration tier** — `tests/test_github_resolver_integration.py`. Real `requests.get` calls against guaranteed-public GitHub repos (`octocat/Hello-World`). Catches transport-layer surprises that mocked tests cannot — e.g. the GitHub auth requirement that PR `manomatika/ahimsa#28` shipped without auth handling. Tests are marked `@pytest.mark.integration`. The tier **runs as part of the default `pytest tests/` run** — it is no longer deselected (the former `addopts = "-m 'not integration'"` default-exclusion was removed so the full suite always exercises it). The `integration` marker stays registered in `pyproject.toml` so `@pytest.mark.integration` is a known mark and the tier can still be selected (`pytest -m integration`) or skipped for offline work (`pytest -m 'not integration'`) on demand.

  The tier needs outbound network to `api.github.com` and `raw.githubusercontent.com`. It runs unauthenticated by design — every test repo it touches is public, so it works in any developer environment without setup. CI (`validate.yml`) passes the auto-provisioned `GITHUB_TOKEN` to the step purely for rate-limit headroom on shared runners; the resolver reads `GITHUB_TOKEN` → `GH_TOKEN` and attaches `Authorization` when present (a no-op against public repos). The tests do not assume token presence or absence.
