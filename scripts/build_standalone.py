"""
build_standalone.py — builds a standalone installer from a recipe.json.

Placeholder implementation. Full build pipeline to be defined in a future
milestone. This script validates the recipe and reports what would be built.

Usage:
  python scripts/build_standalone.py recipes/reference-app/recipe.json [--platform mac|windows]
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="ahimsa standalone builder")
    parser.add_argument("recipe", help="Path to recipe.json")
    parser.add_argument(
        "--platform",
        choices=["mac", "windows"],
        default="mac",
        help="Target platform (default: mac)",
    )
    args = parser.parse_args()

    recipe_path = Path(args.recipe)
    if not recipe_path.exists():
        print(f"[ERROR] Recipe not found: {recipe_path}")
        sys.exit(1)

    # Validate before building
    from validate_recipe import validate
    errors = validate(str(recipe_path))
    if errors:
        print(f"[ERROR] Recipe validation failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    with open(recipe_path) as f:
        recipe = json.load(f)

    app = recipe["application"]
    matika = recipe["matika"]
    applugs = recipe.get("applugs", [])

    print(f"[ahimsa] Build plan for {recipe_path}")
    print(f"  Application : {app['name']} v{app['version']}")
    print(f"  Bundle ID   : {app['bundle_id']}")
    print(f"  Platform    : {args.platform}")
    print(f"  Matika      : {matika['version']}")
    print(f"  AppLugs     :")
    for plug in applugs:
        print(f"    - {plug['name']} v{plug['version']} (matika_version={plug['matika_version']})")
    print()
    print("[ahimsa] Build pipeline not yet implemented. Exiting.")
    sys.exit(0)


if __name__ == "__main__":
    main()
