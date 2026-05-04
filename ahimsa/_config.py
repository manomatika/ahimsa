"""Config loader for the ahimsa validator.

Configuration precedence (highest to lowest):
  1. CLI --config <path>   (caller resolves before passing config_path here)
  2. Walked-up config.json (find_config() walks up from the recipe directory)
  3. Default: ["github.com"]

No environment-variable override. The walk never escapes the project tree
(bounded by .git, pyproject.toml, or package.json markers).
"""

import json
from pathlib import Path

_DEFAULT_ALLOWED_HOSTS: list[str] = ["github.com"]
_ROOT_MARKERS: frozenset[str] = frozenset({".git", "pyproject.toml", "package.json"})


def find_config(recipe_path: Path) -> Path | None:
    """Walk up from recipe_path.parent looking for config.json.

    Algorithm:
      1. At each directory, check for config.json first — if found, return it.
      2. If not found, check for a project-root marker (.git, pyproject.toml,
         package.json). If any marker exists, return None (stop the walk).
      3. Ascend one level and repeat. Stop at the filesystem root.

    The closest config.json wins. A marker stops the walk before an ancestor
    config.json can be found, preventing unrelated project configs from leaking
    into this project's validation.
    """
    current = recipe_path.parent.resolve()

    while True:
        config = current / "config.json"
        if config.is_file():
            return config

        if any((current / m).exists() for m in _ROOT_MARKERS):
            return None

        parent = current.parent
        if parent == current:  # filesystem root
            return None
        current = parent


def load_allowed_hosts(config_path: Path | None) -> list[str]:
    """Return the allowed_hosts list from config_path.

    config_path=None → returns the default list ["github.com"].
    Raises ValueError for malformed JSON.
    Raises FileNotFoundError if config_path is given but missing.
    """
    if config_path is None:
        return list(_DEFAULT_ALLOWED_HOSTS)

    try:
        with open(config_path) as f:
            data = json.load(f)
        return data.get("allowed_hosts", list(_DEFAULT_ALLOWED_HOSTS))
    except FileNotFoundError:
        raise FileNotFoundError(f"config file not found: {config_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"{config_path}: malformed JSON — {e}") from e
