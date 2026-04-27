"""
validate_recipe.py — validates a recipe.json against ahimsa rules.

Rules enforced:
  1. Schema check — required fields present: application.name,
     application.version, matika.version, applugs (non-empty array).
  2. Each applug entry must have: name, repo, version, matika_version, tag.
  3. All applugs must declare identical matika_version values.
  4. Every applug matika_version must match recipe.matika.version.
  5. For each applug, fetch its applug.json from the declared GitHub repo
     at the declared tag and assert its matika_version matches the recipe.

Usage:
  python3 scripts/validate_recipe.py recipes/pffp/recipe.json
"""

import json
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    passed: bool
    label: str
    message: str

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"  [{status}] {self.label}: {self.message}"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

REQUIRED_APPLUG_FIELDS = ["name", "repo", "version", "matika_version", "tag"]


def _github_raw_url(repo: str, tag: str, path: str) -> str:
    """Constructs a raw.githubusercontent.com URL from a repo identifier."""
    repo = repo.removeprefix("https://").removeprefix("http://").removeprefix("github.com/")
    return f"https://raw.githubusercontent.com/{repo}/{tag}/{path}"


def _fetch_json(url: str) -> dict:
    """Fetches and parses JSON from a URL. Raises RuntimeError on any failure."""
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} fetching {url}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error fetching {url}: {e.reason}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON at {url}: {e}")


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def resolve_applug(name: str, version: str, registry=None, **kwargs) -> dict:
    """
    Fetches the applug.json for a given AppLug and returns it as a dict.

    Args:
        name:     AppLug identifier (e.g. "eyerate").
        version:  AppLug version to resolve (e.g. "0.0.2").
        registry: Optional URL of the ahimsa registry repo. When provided,
                  metadata is fetched from the registry rather than directly
                  from the AppLug's source repo (future implementation).
        **kwargs: repo (str), tag (str) — required when registry is None.

    Returns:
        Parsed applug.json dict.

    Raises:
        RuntimeError on fetch or parse failure.
    """
    if registry:
        # Future: fetch pre-validated metadata from the ahimsa registry repo.
        # registry will be a URL such as "github.com/pjtallman/ahimsa-registry".
        # Look up by (name, version) to retrieve the canonical applug.json.
        raise NotImplementedError(
            f"Registry resolver not yet implemented (registry={registry})"
        )
    else:
        repo = kwargs.get("repo")
        tag = kwargs.get("tag")
        if not repo or not tag:
            raise ValueError(
                f"resolve_applug: 'repo' and 'tag' are required when registry is None "
                f"(applug '{name}')"
            )
        url = _github_raw_url(repo, tag, "applug.json")
        return _fetch_json(url)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate(path: str, registry=None) -> list[CheckResult]:
    """
    Validates a recipe.json at the given path.

    Runs all checks and returns a list of CheckResult — one per check.
    No check is skipped except when a preceding structural failure makes it
    impossible to run (e.g. if applugs is absent, per-applug checks are skipped).
    """
    results: list[CheckResult] = []

    def ok(label: str, message: str) -> None:
        results.append(CheckResult(passed=True, label=label, message=message))

    def fail(label: str, message: str) -> None:
        results.append(CheckResult(passed=False, label=label, message=message))

    # --- Load file ---
    try:
        with open(path) as f:
            recipe = json.load(f)
    except FileNotFoundError:
        fail("load", f"file not found: {path}")
        return results
    except json.JSONDecodeError as e:
        fail("load", f"invalid JSON: {e}")
        return results

    # --- 1. Schema: required top-level fields ---
    app = recipe.get("application") or {}
    matika = recipe.get("matika") or {}
    applugs_raw = recipe.get("applugs")

    for field, value in [
        ("application.name",    app.get("name")),
        ("application.version", app.get("version")),
        ("matika.version",      matika.get("version")),
    ]:
        if value:
            ok("schema", f"{field} present ({value!r})")
        else:
            fail("schema", f"{field} missing — required field not found")

    if isinstance(applugs_raw, list) and len(applugs_raw) > 0:
        ok("schema", f"applugs is a non-empty array ({len(applugs_raw)} entr{'y' if len(applugs_raw) == 1 else 'ies'})")
    elif isinstance(applugs_raw, list):
        fail("schema", "applugs is an empty array — at least one AppLug is required")
    else:
        fail("schema", "applugs missing or not an array — required field not found")

    recipe_mv = matika.get("version", "")
    applugs: list[dict] = applugs_raw if isinstance(applugs_raw, list) else []

    # --- 2. Per-applug: required field presence ---
    structurally_valid: list[dict] = []
    for plug in applugs:
        name = plug.get("name") or "<unnamed>"
        label = f"applug[{name}]"
        all_present = True
        for field in REQUIRED_APPLUG_FIELDS:
            if plug.get(field):
                ok(label, f"required field '{field}' present ({plug[field]!r})")
            else:
                fail(label, f"required field '{field}' missing")
                all_present = False
        if all_present:
            structurally_valid.append(plug)

    # --- 3. Consistency: identical matika_version across all applugs ---
    declared_mvs = [p["matika_version"] for p in structurally_valid if p.get("matika_version")]
    if len(set(declared_mvs)) <= 1:
        value_str = declared_mvs[0] if declared_mvs else "n/a"
        ok("consistency", f"all applug matika_version values are identical ({value_str!r})")
    else:
        fail(
            "consistency",
            f"applugs declare conflicting matika_version values: {sorted(set(declared_mvs))} "
            f"— all must be identical",
        )

    # --- 4. Consistency: every applug matika_version matches recipe.matika.version ---
    mismatches = [
        p["name"] for p in structurally_valid
        if p.get("matika_version") and p["matika_version"] != recipe_mv
    ]
    if not mismatches:
        ok(
            "consistency",
            f"all applug matika_version values match recipe matika.version ({recipe_mv!r})",
        )
    else:
        for plug in structurally_valid:
            if plug.get("name") in mismatches:
                fail(
                    "consistency",
                    f"applug '{plug['name']}' matika_version={plug['matika_version']!r} "
                    f"does not match recipe matika.version={recipe_mv!r}",
                )

    # --- 5. Resolve: fetch each applug.json and verify matika_version ---
    for plug in structurally_valid:
        name = plug["name"]
        tag = plug["tag"]
        repo = plug["repo"]
        label = f"resolve[{name}@{tag}]"

        try:
            remote = resolve_applug(name, plug["version"], registry=registry, repo=repo, tag=tag)
            ok(label, f"fetched applug.json from {repo}")
        except (RuntimeError, NotImplementedError, ValueError) as e:
            fail(label, str(e))
            continue

        remote_mv = remote.get("matika_version")
        if remote_mv is None:
            fail(label, "applug.json does not declare matika_version")
        elif remote_mv == recipe_mv:
            ok(label, f"matika_version {remote_mv!r} matches recipe ({recipe_mv!r})")
        else:
            fail(
                label,
                f"applug.json matika_version={remote_mv!r} does not match "
                f"recipe matika.version={recipe_mv!r}",
            )

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path/to/recipe.json>")
        sys.exit(1)

    path = sys.argv[1]
    results = validate(path)

    for r in results:
        print(r)

    failed = [r for r in results if not r.passed]
    total = len(results)

    print()
    if not failed:
        print(f"All {total} checks passed.")
        sys.exit(0)
    else:
        print(f"{len(failed)} of {total} checks failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
