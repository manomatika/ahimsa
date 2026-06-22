"""
Packaging regression tests for the console-script entry points.

Background — defect this guards against:
  The installed ``ahimsa-validate`` / ``ahimsa-validate-releases`` console
  scripts were observed failing with ``ModuleNotFoundError: No module named
  'ahimsa'``. The current ``pyproject.toml`` is correct (a clean wheel or
  editable install both expose working entry points); the live failure came
  from a STALE editable install whose redirect pointed at a deleted source
  tree. These tests lock the entry-point contract so any FUTURE pyproject
  regression — a renamed module, a typo'd ``module:function`` target, or a
  package-discovery (``[tool.hatch.build.targets.wheel] packages``) mistake
  that drops the ``ahimsa`` package — fails loudly in CI instead of silently
  shipping a broken console script.

There is no ``python3 -m`` workaround here: the declared targets are imported
and resolved exactly as ``pip``-installed console scripts resolve them.
"""

import importlib
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"

# The console scripts the package documents and ships.
EXPECTED_SCRIPTS = {"ahimsa-validate", "ahimsa-validate-releases"}


def _declared_scripts() -> dict[str, str]:
    """Return the ``[project.scripts]`` table from pyproject.toml."""
    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    return data.get("project", {}).get("scripts", {})


def test_pyproject_declares_expected_scripts():
    """pyproject.toml declares both documented console scripts."""
    scripts = _declared_scripts()
    assert EXPECTED_SCRIPTS <= set(scripts), (
        f"missing console scripts: {EXPECTED_SCRIPTS - set(scripts)}"
    )


@pytest.mark.parametrize("script_name", sorted(EXPECTED_SCRIPTS))
def test_declared_entry_point_target_is_importable_and_callable(script_name):
    """Each ``module:function`` target imports and resolves to a callable.

    This is the direct guard against ``ModuleNotFoundError`` / a dangling
    entry-point target: if the ``ahimsa`` package or the named function ever
    stops being importable under the declared name, this fails.
    """
    scripts = _declared_scripts()
    target = scripts[script_name]
    assert ":" in target, f"{script_name} target {target!r} is not 'module:function'"
    module_name, func_name = target.split(":", 1)

    module = importlib.import_module(module_name)
    func = getattr(module, func_name, None)
    assert callable(func), f"{target} does not resolve to a callable"


def test_installed_console_scripts_load():
    """When ahimsa is installed, dist-metadata entry points must exactly match
    pyproject.toml declarations and ``.load()`` to callables.

    Portable across all three run modes without skipping or failing:
    (a) ``uv run pytest tests/`` in a synced uv .venv,
    (b) ``pip install -e ".[test]"`` then ``pytest tests/``,
    (c) bare ``PYTHONPATH=src`` checkout with no install.
    In mode (c) dist metadata is absent; the pyproject-based importability
    tests above already cover the entry-point contract in that case.
    """
    from importlib.metadata import entry_points

    declared = _declared_scripts()

    try:
        eps = entry_points(group="console_scripts")
    except TypeError:  # pragma: no cover - very old importlib.metadata
        eps = entry_points().get("console_scripts", [])

    ahimsa_eps = {ep.name: ep for ep in eps if ep.name in EXPECTED_SCRIPTS}

    if not ahimsa_eps:
        # Not installed in this interpreter — the pyproject-based tests above
        # already verified importability.  Nothing to assert here.
        return

    # Installed: installed entry points must exactly match pyproject declarations.
    assert set(ahimsa_eps) == set(declared), (
        f"installed console scripts {set(ahimsa_eps)} != declared {set(declared)}"
    )
    for name, ep in sorted(ahimsa_eps.items()):
        loaded = ep.load()
        assert callable(loaded), f"console script {name} did not load a callable"
