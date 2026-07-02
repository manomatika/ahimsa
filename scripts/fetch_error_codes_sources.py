"""
fetch_error_codes_sources.py — resolve the four per-origin ``error-codes.yaml``
sources the product gate feeds to the BLOCKING cross-repo aggregator.

The merged per-build error-code registry is constructed at gate time by
aggregating the four SHA-pinned per-origin sources named by the recipe:

  - matika      — <recipe.matika.repo>@<recipe.matika.tag>:src/matika/error/error-codes.yaml
  - each applug — <applug.repo>@<applug.tag>:src/<applug.name>/error/error-codes.yaml
  - manomatika  — manomatika/manomatika@<MANOMATIKA_REF or default>:error/error-codes.yaml
  - ahimsa      — the LOCAL checkout's repo-root error-codes.yaml (this repo IS ahimsa)

The paths mirror ``COMPONENT_FOR_ORIGIN`` in ``ahimsa.error_codes``. Each remote
file is fetched at its recipe-pinned ref via ``gh api`` (authenticated by the
job's GH_TOKEN). Fetched files are written into --out and their paths printed,
newline-separated, on stdout — the gate step then runs
``ahimsa-aggregate-error-codes --require-all-origins`` over them, which is where
missing-origin/dup/drift are turned into a pass/fail verdict (V/X).

A per-source fetch failure is reported as a warning and the source is SKIPPED:
the authoritative completeness verdict is the aggregator's missing-origin parity
check (fail-safe — a source that cannot be resolved becomes a gate failure, never
a silent pass). Fail-loud (rule 18) only on structurally unusable input (missing
recipe / unreadable local ahimsa registry).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _canonical_repo(repo: str) -> str:
    """``github.com/manomatika/matika`` (or an https URL) -> ``manomatika/matika``."""
    repo = repo.strip()
    for prefix in ("https://", "http://"):
        if repo.startswith(prefix):
            repo = repo[len(prefix):]
    if repo.startswith("github.com/"):
        repo = repo[len("github.com/"):]
    return repo.rstrip("/")


def _fetch(owner_repo: str, ref: str, path: str, dest: Path) -> bool:
    """Fetch ``repos/<owner_repo>/contents/<path>?ref=<ref>`` (raw) into *dest*.

    Returns True on success. On any ``gh api`` failure prints a warning and
    returns False so the aggregator's missing-origin parity check renders the
    authoritative verdict.
    """
    ref_query = f"?ref={ref}" if ref else ""
    api_path = f"repos/{owner_repo}/contents/{path}{ref_query}"
    try:
        out = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github.raw+json", api_path],
            check=True, capture_output=True, text=True,
        ).stdout
    except subprocess.CalledProcessError as e:
        print(
            f"WARNING: could not fetch {owner_repo}@{ref or 'default'}:{path} "
            f"({e.stderr.strip() or e})",
            file=sys.stderr,
        )
        return False
    dest.write_text(out)
    print(f"fetched {owner_repo}@{ref or 'default'}:{path} -> {dest}", file=sys.stderr)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fetch-error-codes-sources",
        description=(
            "Resolve the four per-origin error-codes.yaml sources the product "
            "gate feeds to the blocking cross-repo aggregator."
        ),
    )
    parser.add_argument("--recipe", required=True, help="path to recipe.json")
    parser.add_argument("--out", required=True, help="output directory for the fetched sources")
    parser.add_argument(
        "--manomatika-ref",
        default="",
        help="ref for manomatika/manomatika's error/error-codes.yaml (default branch if empty)",
    )
    args = parser.parse_args(argv)

    recipe_path = Path(args.recipe)
    if not recipe_path.exists():
        print(f"ERROR: recipe not found at {recipe_path}", file=sys.stderr)
        return 2
    recipe = json.loads(recipe_path.read_text())

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    # matika (framework) — pinned by recipe.matika.tag.
    matika = recipe["matika"]
    dest = out_dir / "matika.error-codes.yaml"
    if _fetch(_canonical_repo(matika["repo"]), matika["tag"],
              "src/matika/error/error-codes.yaml", dest):
        written.append(dest)

    # each applug — pinned by its own tag; path derives from the applug name.
    for plug in recipe.get("applugs", []):
        name = plug["name"]
        dest = out_dir / f"{name}.error-codes.yaml"
        if _fetch(_canonical_repo(plug["repo"]), plug["tag"],
                  f"src/{name}/error/error-codes.yaml", dest):
            written.append(dest)

    # manomatika (product authority) — its own reserved namespace.
    dest = out_dir / "manomatika.error-codes.yaml"
    if _fetch("manomatika/manomatika", args.manomatika_ref,
              "error/error-codes.yaml", dest):
        written.append(dest)

    # ahimsa (this repo) — the LOCAL repo-root registry under gate.
    local_ahimsa = Path("error-codes.yaml")
    if not local_ahimsa.exists():
        print(f"ERROR: local ahimsa registry not found at {local_ahimsa}", file=sys.stderr)
        return 2
    dest = out_dir / "ahimsa.error-codes.yaml"
    dest.write_text(local_ahimsa.read_text())
    print(f"copied local {local_ahimsa} -> {dest}", file=sys.stderr)
    written.append(dest)

    for p in written:
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
