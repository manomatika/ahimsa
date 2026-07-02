"""
validate_recipe.py — validates a recipe.json against ahimsa rules.

Usage:
  ahimsa-validate recipes/reference-app/recipe.json
  python3 -m ahimsa.validate_recipe recipes/reference-app/recipe.json

Exit codes:
  0 — all checks passed
  1 — one or more validation errors (all printed before exit)
  2 — configuration error (bad --config path or malformed config JSON)
"""

import json
import os
import re
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import requests

# Allow `python3 ahimsa/validate_recipe.py <recipe>` without pip installation.
if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ahimsa import error_code_constants as ec
from ahimsa._config import find_config, load_allowed_hosts
from ahimsa.manomatika_error import CODE_PATTERN, CODE_RE


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Error:
    """A single validation finding.

    ``code`` is the opaque ``AHIMSA-<FAC>-<NNN>`` error code (see
    ``error-codes.yaml`` / ``ahimsa.error_code_constants``) that identifies
    the CONDITION; ``pointer`` identifies WHERE in the recipe the condition
    was found. ``code`` defaults to ``None`` for construction sites that have
    not been threaded to a registered code (e.g. ``ahimsa.error_codes``'s
    lints, which validate OTHER origins' ``error-codes.yaml`` files — a
    separate meta-validation concern, out of scope for run R5). Every
    ``validate_recipe`` / ``validate_releases`` construction site DOES supply
    a code. Fail-loud (rule 18): a non-``None`` code that is not well-formed
    ``<COMPONENT>-<FAC>-<NNN>`` raises immediately, reusing the same pattern
    the ``ManoMatikaError`` base class enforces.
    """

    pointer: str
    message: str
    code: str | None = None

    def __post_init__(self) -> None:
        if self.code is not None and (not isinstance(self.code, str) or not CODE_RE.match(self.code)):
            raise ValueError(
                f"Error.code must be a well-formed <COMPONENT>-<FAC>-<NNN> "
                f"code or None; got {self.code!r}. Expected pattern: {CODE_PATTERN}"
            )

    def __str__(self) -> str:
        return f"{self.pointer}: {self.message}"


@dataclass
class AppLugManifest:
    id: str
    version: str
    matika_version: str


# ---------------------------------------------------------------------------
# Module-level GitHub API canonicalization cache
# ---------------------------------------------------------------------------

# Maps lowercase "owner/repo" -> (canonical_owner, canonical_repo).
# Populated on first access; lives for the process lifetime.
_repo_cache: dict[str, tuple[str, str]] = {}


# ---------------------------------------------------------------------------
# Resolver hierarchy
# ---------------------------------------------------------------------------

class BaseResolver(ABC):
    def __init__(self, host: str) -> None:
        self.host = host

    def resolve(self, name: str, repo: str, tag: str) -> AppLugManifest:
        """Template method: parse → canonicalize → build URL → fetch → return."""
        owner, repo_name = self._parse_repo(repo)
        canonical = self._canonicalize_repo(owner, repo_name)
        url = self._raw_url(canonical, tag, "applug.json")
        data = self._fetch_json(url)
        return AppLugManifest(
            id=data.get("id", ""),
            version=data.get("version", ""),
            matika_version=data.get("matika_version", ""),
        )

    def _parse_repo(self, repo: str) -> tuple[str, str]:
        """Strict parsing: must be exactly <host>/<owner>/<repo>, no extras."""
        parts = repo.split("/")
        if len(parts) != 3 or parts[0] != self.host:
            raise ValueError(
                f'malformed repo "{repo}", expected "{self.host}/<owner>/<repo>"'
            )
        owner, repo_name = parts[1], parts[2]
        if not owner or not repo_name:
            raise ValueError(
                f'malformed repo "{repo}", expected "{self.host}/<owner>/<repo>"'
            )
        if repo_name.endswith(".git"):
            raise ValueError(
                f'malformed repo "{repo}" — trailing ".git" not allowed'
            )
        return owner, repo_name

    @abstractmethod
    def _canonicalize_repo(self, owner: str, repo: str) -> tuple[str, str]: ...

    @abstractmethod
    def _raw_url(self, canonical: tuple[str, str], tag: str, path: str) -> str: ...

    def _request_headers(self) -> dict[str, str]:
        """Return HTTP headers to include on every outbound request.

        Default: empty dict. Subclasses override to inject auth tokens or
        custom Accept headers. `_fetch_json` and `_fetch_text` consult this
        method on every call so subclass-level concerns (e.g. host auth)
        are applied uniformly without each helper knowing the host.
        """
        return {}

    def _fetch_json(self, url: str) -> dict:
        resp = requests.get(url, timeout=10, headers=self._request_headers())
        if resp.status_code == 404:
            raise FileNotFoundError(f"file not found at {url}")
        resp.raise_for_status()
        return resp.json()

    def _fetch_text(self, url: str) -> str | None:
        """HTTP GET text content. Returns None on 404, raises on other errors.

        Shared helper for subclasses that fetch arbitrary text files (e.g.
        RELEASES.md). Mirrors `_fetch_json` but for non-JSON payloads.
        """
        resp = requests.get(url, timeout=10, headers=self._request_headers())
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    # ----- Release-log support (used by ahimsa.validate_releases) -----

    @abstractmethod
    def list_tags(self, repo: str) -> list[str]:
        """Return all git tag names (without `refs/tags/` prefix) for *repo*.

        Concrete implementations enumerate tags from the host (e.g. via
        the GitHub git-refs endpoint). Resolvers whose host has no tag
        concept return [].

        Required because subclasses that silently no-op on this surface
        would let release-log drift go undetected — the abstract decl
        forces every BaseResolver subclass to make an explicit choice.
        """

    @abstractmethod
    def fetch_text(self, repo: str, ref: str, path: str) -> str | None:
        """Fetch the text content of *path* at *ref* from *repo*.

        Returns None on 404. Concrete implementations build the URL via
        `_raw_url` and call the shared `_fetch_text` helper. Resolvers
        whose host cannot serve arbitrary text files return None
        unconditionally.

        Required for the same reason as `list_tags` — silent no-ops on
        this surface would mask drift.
        """


class GitHubResolver(BaseResolver):
    def __init__(self) -> None:
        super().__init__(host="github.com")
        # Token precedence: GITHUB_TOKEN, then GH_TOKEN (the gh CLI legacy
        # fallback). Read once at construction; mid-process env changes are
        # not picked up. Public repos work without a token; private repos
        # 404 without one — see _canonicalize_repo for the auth-hint message.
        self._token: str | None = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    def _request_headers(self) -> dict[str, str]:
        """Inject Authorization when a token is present; otherwise empty."""
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    def _canonicalize_repo(self, owner: str, repo: str) -> tuple[str, str]:
        """Resolve owner/repo to canonical casing via the GitHub API (cached)."""
        key = f"{owner}/{repo}".lower()
        if key not in _repo_cache:
            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                timeout=10,
                headers={
                    "Accept": "application/vnd.github+json",
                    **self._request_headers(),
                },
            )
            if resp.status_code == 404:
                # 404 here is genuinely ambiguous: the repo doesn't exist OR
                # the request lacks credentials for a private repo. The token
                # presence/absence is the disambiguating signal we have.
                if self._token:
                    raise LookupError(
                        f'repository "{owner}/{repo}" not found on GitHub'
                    )
                raise LookupError(
                    f'repository "{owner}/{repo}" not found on GitHub '
                    f'(or no access — set GITHUB_TOKEN if this is a private repo)'
                )
            resp.raise_for_status()
            full_name: str = resp.json()["full_name"]
            canonical_owner, canonical_repo = full_name.split("/", 1)
            _repo_cache[key] = (canonical_owner, canonical_repo)
        return _repo_cache[key]

    def _raw_url(self, canonical: tuple[str, str], tag: str, path: str) -> str:
        owner, repo = canonical
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{tag}/{path}"

    def list_tags(self, repo: str) -> list[str]:
        owner, repo_name = self._parse_repo(repo)
        canonical_owner, canonical_repo = self._canonicalize_repo(owner, repo_name)

        # Follow GitHub's Link: rel="next" pagination until exhausted.
        # per_page=100 is the maximum the API allows and minimizes round trips.
        # The first request includes per_page in `params`; subsequent requests
        # use the fully-formed URL from the Link header (it already encodes
        # the page parameter).
        #
        # 404 here means "repo has zero tags" — _canonicalize_repo above has
        # already validated repo accessibility (and raises with an auth hint
        # if no token was sent against a private repo), so we don't need to
        # disambiguate auth at this layer.
        url: str | None = (
            f"https://api.github.com/repos/{canonical_owner}/{canonical_repo}/git/refs/tags"
        )
        params: dict | None = {"per_page": 100}
        tags: list[str] = []

        while url is not None:
            resp = requests.get(
                url,
                timeout=10,
                headers={
                    "Accept": "application/vnd.github+json",
                    **self._request_headers(),
                },
                params=params,
            )
            if resp.status_code == 404:
                return [] if not tags else tags
            resp.raise_for_status()
            refs = resp.json()
            tags.extend(r["ref"].removeprefix("refs/tags/") for r in refs)

            # `requests` parses the Link header into a dict-like structure.
            # If a "next" link exists, follow it on the next iteration.
            next_link = resp.links.get("next")
            url = next_link["url"] if next_link else None
            params = None  # next URL already includes its own page= param

        return tags

    def fetch_text(self, repo: str, ref: str, path: str) -> str | None:
        owner, repo_name = self._parse_repo(repo)
        canonical = self._canonicalize_repo(owner, repo_name)
        url = self._raw_url(canonical, ref, path)
        return self._fetch_text(url)


# ---------------------------------------------------------------------------
# Resolver registry and dispatch
# ---------------------------------------------------------------------------

_RESOLVER_REGISTRY: dict[str, type[BaseResolver]] = {
    "github.com": GitHubResolver,
}


def resolver_for(repo: str, *, allowed_hosts: list[str]) -> BaseResolver:
    """Return a resolver instance for the host in *repo*.

    Raises PermissionError if the host is not in allowed_hosts.
    Raises LookupError if the host is allowed but has no registered resolver.
    """
    host = repo.split("/", 1)[0]
    if host not in allowed_hosts:
        raise PermissionError(f'host "{host}" not in allowed_hosts')
    cls = _RESOLVER_REGISTRY.get(host)
    if cls is None:
        raise LookupError(f'host "{host}" allowed but no resolver registered')
    return cls()


# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')
_BUNDLE_ID_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9-]*(\.[a-zA-Z][a-zA-Z0-9-]*){2,}$')

# product_name is the canonical PRODUCT identity used to name user-facing
# artifacts and the installed bundle/exe (e.g. "ManoMatika" ->
# manomatika-0.0.1-macos-arm64.dmg and ManoMatika-0.0.1.app). It must therefore
# survive two transforms unambiguously: lower-casing + slugifying for the
# artifact FILENAME, and verbatim use for the proper-noun app/bundle identity.
# Allowed charset: ASCII letters and digits, with single interior spaces or
# hyphens as separators; it must start and end with an alphanumeric. This bans
# leading/trailing/space-padding, underscores, slashes, dots, and any character
# that would corrupt a bundle name or a filename slug.
_PRODUCT_NAME_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9]| [A-Za-z0-9]|-[A-Za-z0-9])*$')


def _check_version(errors: list[Error], value: str, pointer: str, code: str) -> None:
    if not _VERSION_RE.match(value):
        errors.append(Error(
            pointer,
            f'"{value}" is not a valid version — must be exact X.Y.Z',
            code=code,
        ))


def _check_product_name(errors: list[Error], value: str, pointer: str) -> None:
    if not _PRODUCT_NAME_RE.match(value):
        errors.append(Error(
            pointer,
            f'"{value}" is not a valid product name — must be ASCII '
            f'alphanumerics separated by single spaces or hyphens, starting '
            f'and ending with an alphanumeric (e.g. "ManoMatika")',
            code=ec.AHIMSA_APP_002,
        ))


def _check_bundle_id(errors: list[Error], value: str, pointer: str) -> None:
    if not _BUNDLE_ID_RE.match(value):
        errors.append(Error(
            pointer,
            f'not a valid reverse-DNS identifier ("{value}")',
            code=ec.AHIMSA_APP_003,
        ))


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------

def validate(
    recipe_path: Path,
    *,
    config_path: Path | None = None,
    resolvers: dict[str, BaseResolver] | None = None,
    allowed_hosts: list[str] | None = None,
) -> list[Error]:
    """Validate a recipe.json. Returns a (possibly empty) list of errors.

    config_path: explicit config file; None triggers walk-up from recipe_path.
    resolvers:   host -> resolver instance map, injected by tests to avoid network.
    allowed_hosts: direct override, bypasses both config_path and walk-up.

    Raises ValueError  if the resolved config file contains malformed JSON.
    Raises FileNotFoundError if config_path is provided but does not exist.
    """
    if allowed_hosts is None:
        effective_config = config_path if config_path is not None else find_config(recipe_path)
        allowed_hosts = load_allowed_hosts(effective_config)

    errors: list[Error] = []

    # --- Load file ---
    try:
        with open(recipe_path) as f:
            recipe = json.load(f)
    except FileNotFoundError:
        errors.append(Error("recipe", f'file not found: "{recipe_path}"', code=ec.AHIMSA_RECIPE_001))
        return errors
    except json.JSONDecodeError as e:
        errors.append(Error("recipe", f"invalid JSON: {e}", code=ec.AHIMSA_RECIPE_002))
        return errors

    # --- Schema: application ---
    app = recipe.get("application") or {}

    for field in ("name", "product_name", "version", "bundle_id", "icon"):
        if not app.get(field):
            errors.append(Error(f"application.{field}", "required field missing", code=ec.AHIMSA_APP_001))

    if app.get("product_name"):
        _check_product_name(errors, app["product_name"], "application.product_name")

    if app.get("version"):
        _check_version(errors, app["version"], "application.version", ec.AHIMSA_APP_004)

    if app.get("bundle_id"):
        _check_bundle_id(errors, app["bundle_id"], "application.bundle_id")

    # --- Schema: matika ---
    matika = recipe.get("matika") or {}

    for field in ("version", "repo", "tag"):
        if not matika.get(field):
            errors.append(Error(f"matika.{field}", "required field missing", code=ec.AHIMSA_MATIKA_001))

    if matika.get("version"):
        _check_version(errors, matika["version"], "matika.version", ec.AHIMSA_MATIKA_002)

    # --- Schema: applugs ---
    applugs_raw = recipe.get("applugs")
    if not isinstance(applugs_raw, list) or len(applugs_raw) == 0:
        errors.append(Error("applugs", "required field missing or empty array", code=ec.AHIMSA_RECIPE_003))
        return errors

    recipe_mv = matika.get("version", "")
    applugs: list[dict] = applugs_raw
    structurally_valid: list[tuple[int, dict]] = []

    for i, plug in enumerate(applugs):
        ptr = f"applugs[{i}]"
        all_present = True

        for field in ("name", "repo", "version", "matika_version", "tag"):
            if not plug.get(field):
                errors.append(Error(f"{ptr}.{field}", "required field missing", code=ec.AHIMSA_PLUG_001))
                all_present = False

        if plug.get("version"):
            _check_version(errors, plug["version"], f"{ptr}.version", ec.AHIMSA_PLUG_003)

        if plug.get("matika_version"):
            _check_version(errors, plug["matika_version"], f"{ptr}.matika_version", ec.AHIMSA_PLUG_003)

        if all_present:
            structurally_valid.append((i, plug))

    # --- Cross-applug consistency ---
    declared_mvs = {
        plug["matika_version"]
        for _, plug in structurally_valid
        if plug.get("matika_version")
    }
    if len(declared_mvs) > 1:
        errors.append(Error(
            "applugs",
            f"applugs declare conflicting matika_version values: {sorted(declared_mvs)}",
            code=ec.AHIMSA_RECIPE_004,
        ))

    # --- Recipe-matika consistency ---
    for i, plug in structurally_valid:
        mv = plug.get("matika_version", "")
        if mv and mv != recipe_mv:
            errors.append(Error(
                f"applugs[{i}].matika_version",
                f'"{mv}" does not match recipe matika.version "{recipe_mv}"',
                code=ec.AHIMSA_PLUG_002,
            ))

    # --- Remote verification ---
    for i, plug in structurally_valid:
        ptr = f"applugs[{i}]"
        name = plug["name"]
        repo = plug["repo"]
        tag = plug["tag"]

        # Select resolver
        if resolvers is not None:
            host = repo.split("/", 1)[0]
            res = resolvers.get(host)
            if res is None:
                errors.append(Error(f"{ptr}.repo", f'no resolver for host "{host}"', code=ec.AHIMSA_RESOLVE_001))
                continue
        else:
            try:
                res = resolver_for(repo, allowed_hosts=allowed_hosts)
            except (PermissionError, LookupError) as e:
                errors.append(Error(f"{ptr}.repo", str(e), code=ec.AHIMSA_RESOLVE_002))
                continue

        # Fetch and verify manifest
        try:
            manifest = res.resolve(name, repo, tag)
        except ValueError as e:
            errors.append(Error(f"{ptr}.repo", str(e), code=ec.AHIMSA_RESOLVE_003))
            continue
        except (LookupError, PermissionError) as e:
            errors.append(Error(f"{ptr}.repo", str(e), code=ec.AHIMSA_RESOLVE_004))
            continue
        except FileNotFoundError as e:
            errors.append(Error(f"{ptr}.resolve", str(e), code=ec.AHIMSA_RESOLVE_005))
            continue
        except Exception as e:
            errors.append(Error(f"{ptr}.resolve", str(e), code=ec.AHIMSA_RESOLVE_006))
            continue

        if manifest.id != name:
            errors.append(Error(
                f"{ptr}.resolve",
                f'applug.json id "{manifest.id}" does not match recipe name "{name}"',
                code=ec.AHIMSA_RESOLVE_007,
            ))
        if manifest.version != plug["version"]:
            errors.append(Error(
                f"{ptr}.resolve",
                f'applug.json version "{manifest.version}" does not match recipe version "{plug["version"]}"',
                code=ec.AHIMSA_RESOLVE_008,
            ))
        if manifest.matika_version != plug["matika_version"]:
            errors.append(Error(
                f"{ptr}.resolve",
                f'applug.json matika_version "{manifest.matika_version}" does not match recipe matika_version "{plug["matika_version"]}"',
                code=ec.AHIMSA_RESOLVE_009,
            ))

    # --- Release-log audits (transitive validate_releases) ---
    #
    # IMPORTANT: validate_releases audits each repo's release log against its
    # current tag list at HEAD — it does NOT audit at the recipe's pinned tag.
    # The check asks "is this repo's release log currently consistent with its
    # tag list?", regardless of which tag the recipe pins. Drift in a repo's
    # release log is worth flagging regardless of recipe state. See
    # CLAUDE.md "Release Log Validation" for the full rationale.
    #
    # The central RELEASES.md lives in manomatika/manomatika (product authority).
    # When tests inject resolvers, those resolvers also serve the mm entry.
    # The recipe's allowed_hosts is NOT passed here: it governs which hosts the
    # recipe may reference, not which hosts ahimsa's own infrastructure uses.
    # Using allowed_hosts=None preserves the default ["github.com"] so the
    # ahimsa RELEASES.md fetch always works regardless of a restrictive recipe
    # config (e.g. a recipe that only allows "test.invalid").
    #
    # Function-level import breaks the circular dependency: validate_releases
    # imports BaseResolver/Error/resolver_for from this module.
    from ahimsa.validate_releases import validate_releases as _validate_releases

    _releases_allowed = allowed_hosts

    if matika.get("repo"):
        for e in _validate_releases(
            [matika["repo"]], resolvers=resolvers, allowed_hosts=_releases_allowed,
        ):
            errors.append(Error(f"matika.{e.pointer}", e.message, code=e.code))

    for i, plug in structurally_valid:
        for e in _validate_releases(
            [plug["repo"]], resolvers=resolvers, allowed_hosts=_releases_allowed,
        ):
            errors.append(Error(f"applugs[{i}].{e.pointer}", e.message, code=e.code))

    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="ahimsa-validate",
        description="Validate a recipe.json against ahimsa rules.",
    )
    parser.add_argument("recipe", type=Path, help="path to recipe.json")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="explicit config.json — overrides walk-up discovery",
    )
    args = parser.parse_args(argv)

    try:
        errors = validate(args.recipe, config_path=args.config)
    except FileNotFoundError as e:
        print(f"error: [{ec.AHIMSA_CLI_001}] {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"error: [{ec.AHIMSA_CLI_002}] {e}", file=sys.stderr)
        return 2

    for err in errors:
        print(err)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
