"""
Invocation coverage — four ways to run the validator.

All tests use the tests/fixtures/invalid_host/ scenario:
  - recipe uses host "test.invalid"
  - config.json at the fixture dir allows only "github.com"
  - validator fails at policy check (no network call made)
  - exit code 1, stdout contains the policy error message

test.invalid is an RFC 6761 reserved name; it never resolves on any network.
"""

import shutil
import subprocess
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "invalid_host"
FIXTURE_RECIPE = FIXTURE_DIR / "recipe.json"
EXPECTED_ERROR = 'host "test.invalid" not in allowed_hosts'
EXPECTED_EXIT = 1


def _run(*cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True)


# ---------------------------------------------------------------------------
# (a) python3 -m ahimsa.validate_recipe <recipe>
# ---------------------------------------------------------------------------

def test_invocation_module():
    result = _run(sys.executable, "-m", "ahimsa.validate_recipe", str(FIXTURE_RECIPE))
    assert result.returncode == EXPECTED_EXIT, (
        f"Expected exit {EXPECTED_EXIT}, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert EXPECTED_ERROR in result.stdout, (
        f"Expected {EXPECTED_ERROR!r} in stdout, got:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# (b) ahimsa-validate <recipe>  (requires pip install -e .)
# ---------------------------------------------------------------------------

def test_invocation_console_script():
    script = shutil.which("ahimsa-validate")
    assert script is not None, (
        "ahimsa-validate not on PATH — run: pip install -e '.[test]'"
    )
    result = _run(script, str(FIXTURE_RECIPE))
    assert result.returncode == EXPECTED_EXIT, (
        f"Expected exit {EXPECTED_EXIT}, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert EXPECTED_ERROR in result.stdout


# ---------------------------------------------------------------------------
# (c) python3 ahimsa/validate_recipe.py <recipe>  (direct file)
# ---------------------------------------------------------------------------

def test_invocation_direct_file():
    module_file = Path(__file__).parent.parent / "ahimsa" / "validate_recipe.py"
    result = _run(sys.executable, str(module_file), str(FIXTURE_RECIPE))
    assert result.returncode == EXPECTED_EXIT, (
        f"Expected exit {EXPECTED_EXIT}, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert EXPECTED_ERROR in result.stdout


# ---------------------------------------------------------------------------
# (d) python3 -c "from ahimsa.validate_recipe import validate; ..."
# ---------------------------------------------------------------------------

def test_invocation_programmatic():
    code = (
        "from ahimsa.validate_recipe import validate; "
        "from pathlib import Path; "
        f"errors = validate(Path({str(FIXTURE_RECIPE)!r})); "
        "[print(e) for e in errors]; "
        "import sys; sys.exit(1 if errors else 0)"
    )
    result = _run(sys.executable, "-c", code)
    assert result.returncode == EXPECTED_EXIT, (
        f"Expected exit {EXPECTED_EXIT}, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert EXPECTED_ERROR in result.stdout
