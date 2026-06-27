"""Cross-repo schema-constant parity between matika (canonical) and ahimsa (mirror).

RELOCATED HERE from matika's unit suite per manomatika/matika#105. The parity
assertion used to live in matika's hermetic unit suite, where it reached out to
the ahimsa sibling on disk — which made matika's CI (matika alone, no sibling)
RED while green locally. The gate layer is the correct home: ahimsa legitimately
owns BOTH sides of this contract (it ships the MIRROR constants in
``scripts/screen_manifest.py`` and runs the product/structural gate), and CI here
checks out matika alongside ahimsa, so both sides are present and importable.

What it asserts (the same 4 parities the matika test asserted):
  1. SUPPORTED_SCHEMA          (matika ScreenLoaderService canon vs ahimsa mirror)
  2. ALLOWED_VERBS             (frozenset of screen-step verbs)
  3. FUNCTIONAL_TEST_SCHEMA    (Layer-3 functional-test contract, matika#98)
  4. FUNCTIONAL_TESTS_SUFFIX   (Layer-3 discovery suffix)

ahimsa's side is read by IMPORTING ``screen_manifest`` (its mirror constants are
real module-level Python). matika's CANONICAL side is read by AST-extracting the
literals from matika's source — no matika install required, mirroring how the
original test AST-parsed the foreign repo. matika's source root is located via
the ``MATIKA_SRC`` env var (set by CI after checking matika out), falling back to
the co-located sibling clone at ``../matika`` for local dev. The check is MOVED,
never skipped: an absent matika source is a hard ``pytest.fail`` (rule 21 —
zero-skip), and any drift fails the build.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

# Make ahimsa's gate module importable (same pattern as test_screen_manifest.py).
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import screen_manifest as sm  # noqa: E402


# ---------------------------------------------------------------------------
# Locate matika's canonical source (the foreign side of the contract).
# ---------------------------------------------------------------------------
_AHIMSA_ROOT = Path(__file__).parent.parent


def _matika_root() -> Path:
    """Resolve matika's repo root: MATIKA_SRC env (CI) or sibling clone (local)."""
    env = os.environ.get("MATIKA_SRC")
    if env:
        return Path(env)
    return _AHIMSA_ROOT.parent / "matika"


_MATIKA_ROOT = _matika_root()
_MATIKA_SCREEN_LOADER = _MATIKA_ROOT / "src" / "matika" / "core" / "screen_loader.py"
_MATIKA_FT_CONTRACT = (
    _MATIKA_ROOT / "src" / "matika" / "core" / "functional_test_contract.py"
)


def _extract_constants(path: Path) -> dict:
    """AST-extract module-level constant assignments (literals + frozenset/set)."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    constants: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                val = node.value
                # Try literal first.
                try:
                    constants[target.id] = ast.literal_eval(val)
                    continue
                except (ValueError, TypeError):
                    pass
                # Handle frozenset({...}) or set({...}) calls.
                if (
                    isinstance(val, ast.Call)
                    and isinstance(val.func, ast.Name)
                    and val.func.id in ("frozenset", "set")
                    and len(val.args) == 1
                ):
                    try:
                        inner = ast.literal_eval(val.args[0])
                        constants[target.id] = (
                            frozenset(inner) if val.func.id == "frozenset" else set(inner)
                        )
                    except (ValueError, TypeError):
                        pass
    return constants


@pytest.fixture(scope="module")
def matika_constants() -> dict:
    """The canonical constants read from matika's source (screen_loader + contract)."""
    for path in (_MATIKA_SCREEN_LOADER, _MATIKA_FT_CONTRACT):
        if not path.exists():
            pytest.fail(
                f"matika source not found at {path}. Set MATIKA_SRC to matika's "
                f"repo root, or co-locate the sibling clone at "
                f"{_AHIMSA_ROOT.parent / 'matika'}. (Relocated parity gate for "
                f"manomatika/matika#105 — this check is MOVED, never skipped.)"
            )
    merged: dict = {}
    merged.update(_extract_constants(_MATIKA_SCREEN_LOADER))
    merged.update(_extract_constants(_MATIKA_FT_CONTRACT))
    return merged


class TestSchemaConstantParity:
    """ahimsa's mirror constants must match matika's canon — drift fails the gate."""

    def test_supported_schema_matches(self, matika_constants):
        matika_val = matika_constants.get("SUPPORTED_SCHEMA")
        assert matika_val is not None, (
            "SUPPORTED_SCHEMA not found in matika screen_loader.py"
        )
        assert sm.SUPPORTED_SCHEMA == matika_val, (
            f"SUPPORTED_SCHEMA drift: matika={matika_val!r}, "
            f"ahimsa={sm.SUPPORTED_SCHEMA!r}"
        )

    def test_allowed_verbs_matches(self, matika_constants):
        matika_val = matika_constants.get("ALLOWED_VERBS")
        assert matika_val is not None, (
            "ALLOWED_VERBS not found in matika screen_loader.py"
        )
        if not isinstance(matika_val, (set, frozenset)):
            pytest.fail(
                f"ALLOWED_VERBS in matika has unexpected type: {type(matika_val)}"
            )
        assert frozenset(sm.ALLOWED_VERBS) == frozenset(matika_val), (
            f"ALLOWED_VERBS drift:\n"
            f"  matika:  {sorted(matika_val)}\n"
            f"  ahimsa:  {sorted(sm.ALLOWED_VERBS)}"
        )

    def test_functional_test_schema_parity(self, matika_constants):
        matika_val = matika_constants.get("FUNCTIONAL_TEST_SCHEMA")
        assert matika_val is not None, (
            "FUNCTIONAL_TEST_SCHEMA not found in matika functional_test_contract.py"
        )
        assert sm.FUNCTIONAL_TEST_SCHEMA == matika_val, (
            f"FUNCTIONAL_TEST_SCHEMA drift: matika={matika_val!r}, "
            f"ahimsa={sm.FUNCTIONAL_TEST_SCHEMA!r}"
        )

    def test_functional_tests_suffix_parity(self, matika_constants):
        matika_val = matika_constants.get("FUNCTIONAL_TESTS_SUFFIX")
        assert matika_val is not None, (
            "FUNCTIONAL_TESTS_SUFFIX not found in matika functional_test_contract.py"
        )
        assert sm.FUNCTIONAL_TESTS_SUFFIX == matika_val, (
            f"FUNCTIONAL_TESTS_SUFFIX drift: matika={matika_val!r}, "
            f"ahimsa={sm.FUNCTIONAL_TESTS_SUFFIX!r}"
        )
