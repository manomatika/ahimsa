"""Unit tests for the ahimsa build-time i18n-completeness gate.

The gate (``scripts/frozen_verify.py::run_i18n_completeness``) INVOKES matika's
canonical checker (``src/matika/core/i18n_completeness.py``) against the pinned
source tree — it must not reimplement the logic (rule 18). These tests pin the
ahimsa wiring: it loads the canonical module by path, discovers the frozen-tree
components, fails the build (FrozenAppError) on a missing translation naming the
key, and refuses to pass vacuously (rule 22). They run the REAL canonical checker
resolved from matika (MATIKA_SRC in CI, sibling clone locally), so a drift in the
contract surfaces here too.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_SCRIPT = _SCRIPTS_DIR / "frozen_verify.py"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_AHIMSA_ROOT = Path(__file__).parent.parent


def _matika_root() -> Path:
    env = os.environ.get("MATIKA_SRC")
    return Path(env) if env else _AHIMSA_ROOT.parent / "matika"


_CANON = _matika_root() / "src" / "matika" / "core" / "i18n_completeness.py"


@pytest.fixture(scope="module")
def fv():
    spec = importlib.util.spec_from_file_location("frozen_verify", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _build_tree(root: Path) -> None:
    """Assemble a minimal frozen-style tree: matika core (with the canonical
    checker copied in) + one applug, all locale-complete."""
    assert _CANON.exists(), f"canonical checker not found at {_CANON}"
    core_pkg = root / "src" / "matika"
    (core_pkg / "core").mkdir(parents=True, exist_ok=True)
    shutil.copy(_CANON, core_pkg / "core" / "i18n_completeness.py")
    _write(core_pkg / "locales" / "en.json", {"title": "Home"})
    _write(core_pkg / "locales" / "es.json", {"title": "Inicio"})
    _write(core_pkg / "templates" / "x.html", "<h1>{{ t.title }}</h1>")

    plug = root / "plugins" / "foo"
    _write(plug / "src" / "foo" / "locales" / "en.json", {"menu_foo": "Foo"})
    _write(plug / "src" / "foo" / "locales" / "es.json", {"menu_foo": "Fú"})
    _write(plug / "foo_menus.json", {"items": [{"label_key": "menu_foo"}]})


def test_gate_passes_on_complete_tree(fv, tmp_path):
    _build_tree(tmp_path)
    # No exception == build passes.
    fv.run_i18n_completeness(str(tmp_path))


def test_gate_fails_naming_missing_translation(fv, tmp_path):
    _build_tree(tmp_path)
    # Drop the applug's es translation: referenced (foo_menus) + parity gap.
    _write(tmp_path / "plugins" / "foo" / "src" / "foo" / "locales" / "es.json", {})
    with pytest.raises(fv.FrozenAppError) as exc:
        fv.run_i18n_completeness(str(tmp_path))
    msg = str(exc.value)
    assert "menu_foo" in msg and "es" in msg


def test_gate_fails_when_core_locale_incomplete(fv, tmp_path):
    _build_tree(tmp_path)
    # Core references t.title but es lacks it.
    _write(tmp_path / "src" / "matika" / "locales" / "es.json", {})
    with pytest.raises(fv.FrozenAppError) as exc:
        fv.run_i18n_completeness(str(tmp_path))
    assert "title" in str(exc.value)


def test_gate_skips_without_source_root(fv):
    # The install-verify (A2) arm has no source tree; the source-derived gate skips.
    fv.run_i18n_completeness(None)


def test_gate_refuses_vacuous_pass_on_empty_tree(fv, tmp_path):
    # Checker present but no locale-bearing components -> must not pass silently.
    canon_dir = tmp_path / "src" / "matika" / "core"
    canon_dir.mkdir(parents=True)
    shutil.copy(_CANON, canon_dir / "i18n_completeness.py")
    with pytest.raises(fv.FrozenAppError) as exc:
        fv.run_i18n_completeness(str(tmp_path))
    assert "vacuous" in str(exc.value).lower() or "no locale" in str(exc.value).lower()


def test_gate_errors_when_checker_missing(fv, tmp_path):
    # Pinned source without the canonical module is a hard failure, not a skip.
    with pytest.raises(fv.FrozenAppError) as exc:
        fv._load_i18n_checker(str(tmp_path))
    assert "checker not found" in str(exc.value)
