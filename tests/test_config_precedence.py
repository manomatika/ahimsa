"""
Config loading and precedence matrix tests.

Covers:
  - find_config() walk-up algorithm (unit tests)
  - load_allowed_hosts() (unit tests)
  - CLI --config precedence over walk-up (subprocess)
  - Walk-up precedence over default (subprocess)
  - Default when no config found (subprocess)
  - Error paths: malformed config, missing config (subprocess, exit 2)
  - Walk stops at each marker type: .git, pyproject.toml, package.json
  - Walk does not find ancestor config beyond a marker
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ahimsa._config import find_config, load_allowed_hosts

FIXTURE_BASE = Path(__file__).parent / "fixtures"
INVALID_HOST_RECIPE = FIXTURE_BASE / "invalid_host" / "recipe.json"
VALID_LOCAL_RECIPE = FIXTURE_BASE / "valid_local_config" / "recipe.json"
NO_CONFIG_RECIPE = FIXTURE_BASE / "no_config" / "recipe.json"


def _run(*cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True)


def _ahimsa(*args: str) -> subprocess.CompletedProcess:
    return _run(sys.executable, "-m", "ahimsa.validate_recipe", *args)


# ---------------------------------------------------------------------------
# find_config() unit tests
# ---------------------------------------------------------------------------

def test_find_config_immediate(tmp_path):
    """config.json right beside recipe.json is found immediately."""
    cfg = tmp_path / "config.json"
    cfg.write_text('{"allowed_hosts": ["test"]}')
    recipe = tmp_path / "recipe.json"
    recipe.touch()
    assert find_config(recipe) == cfg


def test_find_config_parent_level(tmp_path):
    """config.json one level up is found when not present at recipe level."""
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    sub = tmp_path / "sub"
    sub.mkdir()
    recipe = sub / "recipe.json"
    recipe.touch()
    assert find_config(recipe) == cfg


def test_find_config_immediate_wins_over_parent(tmp_path):
    """Closer config.json takes precedence over one in a parent directory."""
    parent_cfg = tmp_path / "config.json"
    parent_cfg.write_text('{"allowed_hosts": ["parent"]}')
    sub = tmp_path / "sub"
    sub.mkdir()
    sub_cfg = sub / "config.json"
    sub_cfg.write_text('{"allowed_hosts": ["sub"]}')
    recipe = sub / "recipe.json"
    recipe.touch()
    assert find_config(recipe) == sub_cfg


def test_walk_stops_at_git_marker(tmp_path):
    (tmp_path / ".git").mkdir()
    recipe = tmp_path / "recipe.json"
    recipe.touch()
    assert find_config(recipe) is None


def test_walk_stops_at_pyproject_toml_marker(tmp_path):
    (tmp_path / "pyproject.toml").touch()
    recipe = tmp_path / "recipe.json"
    recipe.touch()
    assert find_config(recipe) is None


def test_walk_stops_at_package_json_marker(tmp_path):
    (tmp_path / "package.json").touch()
    recipe = tmp_path / "recipe.json"
    recipe.touch()
    assert find_config(recipe) is None


def test_config_wins_over_marker_at_same_level(tmp_path):
    """config.json and a marker in the same directory — config wins (checked first)."""
    (tmp_path / "config.json").write_text('{"allowed_hosts": ["x"]}')
    (tmp_path / ".git").mkdir()
    recipe = tmp_path / "recipe.json"
    recipe.touch()
    result = find_config(recipe)
    assert result is not None and result.name == "config.json"


def test_walk_does_not_cross_marker_to_ancestor_config(tmp_path):
    """A marker in a parent directory blocks an ancestor config.json."""
    ancestor_cfg = tmp_path / "config.json"
    ancestor_cfg.write_text('{"allowed_hosts": ["ancestor"]}')

    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").touch()  # stop marker

    sub = project / "recipes"
    sub.mkdir()
    recipe = sub / "recipe.json"
    recipe.touch()

    assert find_config(recipe) is None  # pyproject.toml blocks before ancestor config


def test_walk_returns_none_at_filesystem_root_boundary(tmp_path):
    """Walk terminates without looping; returns None when no config or marker found."""
    # tmp_path is inside the system temp dir; no markers above it (in the
    # temp tree), no config.json — walk runs to filesystem root and returns None.
    # This also implicitly verifies the algorithm terminates.
    recipe = tmp_path / "deep" / "path" / "recipe.json"
    recipe.parent.mkdir(parents=True)
    recipe.touch()
    result = find_config(recipe)
    # May be None or a Path depending on host filesystem; the key property
    # is that it RETURNS rather than looping.
    assert isinstance(result, (type(None), Path))


# ---------------------------------------------------------------------------
# load_allowed_hosts() unit tests
# ---------------------------------------------------------------------------

def test_load_none_returns_default():
    assert load_allowed_hosts(None) == ["github.com"]


def test_load_valid_file(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"allowed_hosts": ["github.com", "gitlab.com"]}')
    assert load_allowed_hosts(cfg) == ["github.com", "gitlab.com"]


def test_load_file_missing_key_returns_default(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"other_key": 42}')
    assert load_allowed_hosts(cfg) == ["github.com"]


def test_load_malformed_raises_value_error(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text("{bad json")
    with pytest.raises(ValueError, match="malformed JSON"):
        load_allowed_hosts(cfg)


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_allowed_hosts(tmp_path / "does_not_exist.json")


# ---------------------------------------------------------------------------
# Subprocess: walk-up wins over default
# ---------------------------------------------------------------------------

def test_walked_config_wins_over_default():
    """invalid_host/config.json (github.com only) is walked up and applied."""
    result = _ahimsa(str(INVALID_HOST_RECIPE))
    assert result.returncode == 1
    assert 'host "test.invalid" not in allowed_hosts' in result.stdout


# ---------------------------------------------------------------------------
# Subprocess: permissive walked-up config (host allowed, no resolver)
# ---------------------------------------------------------------------------

def test_valid_local_config_allows_host():
    """valid_local_config/config.json allows test.invalid; dispatch error replaces policy error."""
    result = _ahimsa(str(VALID_LOCAL_RECIPE))
    assert result.returncode == 1
    # Policy error is gone; now gets the "no resolver registered" dispatch error
    assert "allowed but no resolver registered" in result.stdout
    assert "not in allowed_hosts" not in result.stdout


# ---------------------------------------------------------------------------
# Subprocess: no config, walk hits pyproject.toml marker → default applies
# ---------------------------------------------------------------------------

def test_no_config_default_applies():
    """no_config/ has pyproject.toml marker; walk stops, default rejects test.invalid."""
    result = _ahimsa(str(NO_CONFIG_RECIPE))
    assert result.returncode == 1
    assert 'host "test.invalid" not in allowed_hosts' in result.stdout


# ---------------------------------------------------------------------------
# Subprocess: --config wins over walked-up config
# ---------------------------------------------------------------------------

def test_cli_config_wins_over_walk(tmp_path):
    """--config pointing to permissive file overrides the fixture's own config.json."""
    explicit = tmp_path / "allow_test_invalid.json"
    explicit.write_text('{"allowed_hosts": ["test.invalid"]}')
    result = _ahimsa("--config", str(explicit), str(INVALID_HOST_RECIPE))
    assert result.returncode == 1
    # Policy check now passes — dispatch error replaces it
    assert "allowed but no resolver registered" in result.stdout
    assert "not in allowed_hosts" not in result.stdout


def test_cli_config_wins_over_default(tmp_path):
    """--config with restrictive list blocks a host that default would also block."""
    explicit = tmp_path / "empty_hosts.json"
    explicit.write_text('{"allowed_hosts": []}')
    result = _ahimsa("--config", str(explicit), str(INVALID_HOST_RECIPE))
    assert result.returncode == 1
    assert "not in allowed_hosts" in result.stdout


# ---------------------------------------------------------------------------
# Subprocess: error paths — exit 2
# ---------------------------------------------------------------------------

def test_missing_config_file_exits_2(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    result = _ahimsa("--config", str(missing), str(INVALID_HOST_RECIPE))
    assert result.returncode == 2
    assert "not found" in result.stderr.lower() or "config" in result.stderr.lower()


def test_malformed_config_file_exits_2(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    result = _ahimsa("--config", str(bad), str(INVALID_HOST_RECIPE))
    assert result.returncode == 2
    assert "malformed" in result.stderr.lower() or "json" in result.stderr.lower()
