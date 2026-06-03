"""
Structural regression tests for .github/workflows/build.yml.

build.yml runs on GitHub Actions and cannot be exercised end-to-end locally,
so these tests assert the *contract* of the foundation pipeline shipped in
manomatika/ahimsa#9, #10 and manomatika/matika#26:

  - the validate job invokes the installed validator (regression guard: it
    previously pointed at a non-existent scripts/validate_recipe.py path)
  - every platform build job clones matika at the recipe's pinned tag,
    clones applugs into build/matika/plugins/, runs the npm build, and
    invokes `pyinstaller matika.spec`

dmgbuild / Inno Setup / the release job are explicitly out of scope for this
PR (deferred to Wave 3 / PR 2) and are intentionally NOT asserted to be
implemented here — they remain stubs.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "build.yml"

# Platform build jobs that must each run the full clone → npm → pyinstaller
# foundation. The release job is excluded — it has no build steps.
BUILD_JOBS = ["build-macos-arm", "build-macos-intel", "build-windows"]


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _job_run_blocks(job: dict) -> str:
    """Concatenate every step's `run:` script in a job into one string."""
    return "\n".join(
        step.get("run", "") for step in job.get("steps", [])
    )


def _step_names(job: dict) -> list[str]:
    return [step.get("name", "") for step in job.get("steps", [])]


def test_build_yml_is_valid_yaml(workflow):
    assert "jobs" in workflow
    assert set(BUILD_JOBS).issubset(workflow["jobs"].keys())


def test_validate_job_uses_installed_validator(workflow):
    """The validate job must use the packaged validator, not a stale path.

    Regression: build.yml previously invoked `scripts/validate_recipe.py`,
    a path that does not exist — the validator lives in the `ahimsa` package
    and is exposed as the `ahimsa-validate` console script. That stale
    invocation would have failed the validate job on every run.
    """
    runs = _job_run_blocks(workflow["jobs"]["validate"])
    assert "scripts/validate_recipe.py" not in runs, (
        "validate job references the non-existent scripts/validate_recipe.py"
    )
    assert "ahimsa-validate" in runs, (
        "validate job must invoke the ahimsa-validate console script"
    )
    # The console script only exists after the package is installed.
    assert "pip install -e ." in runs


@pytest.mark.parametrize("job_name", BUILD_JOBS)
def test_build_job_clones_matika_at_recipe_tag(workflow, job_name):
    job = workflow["jobs"][job_name]
    runs = _job_run_blocks(job)
    # Clones matika into build/matika.
    assert "build/matika" in runs
    assert "git clone" in runs
    # The tag comes from the recipe's matika.tag, surfaced as an output —
    # not derived ad hoc. This keeps the recipe the single source of truth.
    assert "matika_tag" in runs
    assert 'r["matika"]["tag"]' in runs


@pytest.mark.parametrize("job_name", BUILD_JOBS)
def test_build_job_clones_applugs_into_plugins(workflow, job_name):
    job = workflow["jobs"][job_name]
    runs = _job_run_blocks(job)
    assert "build/matika/plugins/" in runs
    # Each applug is pinned by its own explicit tag from the recipe.
    assert 'plug["tag"]' in runs


@pytest.mark.parametrize("job_name", BUILD_JOBS)
def test_build_job_runs_npm_build(workflow, job_name):
    job = workflow["jobs"][job_name]
    runs = _job_run_blocks(job)
    assert "npm install" in runs
    assert "npm run build" in runs


@pytest.mark.parametrize("job_name", BUILD_JOBS)
def test_build_job_invokes_pyinstaller_on_spec(workflow, job_name):
    job = workflow["jobs"][job_name]
    runs = _job_run_blocks(job)
    assert "pyinstaller matika.spec" in runs
    # No PyInstaller TODO stub may remain in a build job.
    assert not any(
        "PyInstaller" in name and name.lstrip().startswith("TODO")
        for name in _step_names(job)
    ), f"{job_name} still has a TODO PyInstaller stub"


@pytest.mark.parametrize("job_name", BUILD_JOBS)
def test_pyinstaller_runs_in_cloned_matika_dir(workflow, job_name):
    """The spec resolves SPEC-relative paths, so it must run in build/matika."""
    job = workflow["jobs"][job_name]
    pyinstaller_steps = [
        step
        for step in job["steps"]
        if "pyinstaller matika.spec" in step.get("run", "")
    ]
    assert pyinstaller_steps, f"{job_name} has no pyinstaller step"
    for step in pyinstaller_steps:
        assert step.get("working-directory") == "build/matika", (
            f"{job_name} must run pyinstaller from build/matika"
        )
