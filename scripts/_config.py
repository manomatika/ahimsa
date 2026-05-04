"""Config loader for the ahimsa validator."""

import json
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_CONFIG_FILE = _REPO_ROOT / "config.json"
_DEFAULT_ALLOWED_HOSTS: list[str] = ["github.com"]


def load_allowed_hosts() -> list[str]:
    """Return allowed_hosts from env var > config file > default ["github.com"].

    AHIMSA_ALLOWED_HOSTS (comma-separated) overrides config.json.
    If config.json is absent, the default is used silently.
    If config.json exists but contains malformed JSON, ValueError is raised.
    """
    env = os.environ.get("AHIMSA_ALLOWED_HOSTS")
    if env:
        return [h.strip() for h in env.split(",") if h.strip()]

    try:
        with open(_CONFIG_FILE) as f:
            data = json.load(f)
        return data.get("allowed_hosts", _DEFAULT_ALLOWED_HOSTS)
    except FileNotFoundError:
        return _DEFAULT_ALLOWED_HOSTS
    except json.JSONDecodeError as e:
        raise ValueError(f"config.json: malformed JSON — {e}") from e
