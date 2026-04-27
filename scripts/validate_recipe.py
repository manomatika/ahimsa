"""
validate_recipe.py — validates a recipe.json against ahimsa rules.

Rules enforced:
  1. All applugs must declare identical matika_version values.
  2. All applug matika_version values must match recipe.matika.version.
  3. All version pins must be exact (no ranges — no ^, ~, >=, <=, *, etc.).

Usage:
  python scripts/validate_recipe.py recipes/pffp/recipe.json
"""

import json
import re
import sys


RANGE_PATTERN = re.compile(r"[^0-9.]")


def is_exact_version(v: str) -> bool:
    return bool(re.fullmatch(r"\d+\.\d+\.\d+", v))


def validate(path: str) -> list[str]:
    errors = []

    with open(path) as f:
        recipe = json.load(f)

    matika_version = recipe.get("matika", {}).get("version", "")
    applugs = recipe.get("applugs", [])
    app_version = recipe.get("application", {}).get("version", "")

    # Exact pin: application version
    if not is_exact_version(app_version):
        errors.append(f"application.version '{app_version}' is not an exact version pin (expected X.Y.Z).")

    # Exact pin: matika version
    if not is_exact_version(matika_version):
        errors.append(f"matika.version '{matika_version}' is not an exact version pin (expected X.Y.Z).")

    for plug in applugs:
        name = plug.get("name", "<unnamed>")

        # Exact pin: applug version
        plug_version = plug.get("version", "")
        if not is_exact_version(plug_version):
            errors.append(f"applugs[{name}].version '{plug_version}' is not an exact version pin.")

        # Exact pin: applug matika_version
        plug_mv = plug.get("matika_version", "")
        if not is_exact_version(plug_mv):
            errors.append(f"applugs[{name}].matika_version '{plug_mv}' is not an exact version pin.")

        # All applug matika_version values must match recipe.matika.version
        if plug_mv and plug_mv != matika_version:
            errors.append(
                f"applugs[{name}].matika_version '{plug_mv}' does not match "
                f"recipe matika.version '{matika_version}'."
            )

    # All applugs must declare identical matika_version values
    declared = [p.get("matika_version") for p in applugs if p.get("matika_version")]
    if len(set(declared)) > 1:
        errors.append(f"Applugs declare conflicting matika_version values: {sorted(set(declared))}.")

    return errors


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path/to/recipe.json>")
        sys.exit(1)

    path = sys.argv[1]
    errors = validate(path)

    if errors:
        print(f"INVALID: {path}")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"OK: {path}")


if __name__ == "__main__":
    main()
