"""
Structural regression tests for .github/workflows/build.yml.

build.yml runs on GitHub Actions and cannot be exercised end-to-end locally,
so these tests assert the *contract* of the pipeline:

  - the workflow is workflow_dispatch ONLY — no tag-push trigger, no PR trigger
  - the validate job fetches the recipe from manomatika/manomatika and invokes
    the installed validator (regression guard: it previously pointed at a
    non-existent scripts/validate_recipe.py path)
  - every platform build job fetches the recipe from mm, then clones matika at
    the recipe's pinned tag, clones applugs into build/matika/plugins/, runs
    the npm build, and invokes `pyinstaller matika.spec`
  - macOS build jobs wrap the .app in a DMG via dmgbuild (no TODO stub left)
  - the Windows job runs Inno Setup against the one-dir bundle (no TODO stub)
  - no `release` job exists — ahimsa builds artifacts on demand only;
    product releases are cut by manomatika/manomatika

The packaging + release work (manomatika/ahimsa#13, #14, #17, #18, #26;
tracked by manomatika/matika#29, #30, #31) is implemented; the release job
that shipped in that wave has since been removed (manomatika/ahimsa#55) as
the product release authority moved to manomatika/manomatika.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "build.yml"
REPO_ROOT = Path(__file__).parent.parent
ISS_FILE = REPO_ROOT / "installer" / "windows_installer.iss"

# Platform build jobs that must each run the full clone → npm → pyinstaller
# foundation. The release job is excluded — it has no build steps.
BUILD_JOBS = ["build-macos-arm", "build-macos-intel", "build-windows"]
MACOS_BUILD_JOBS = ["build-macos-arm", "build-macos-intel"]


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


# ---------------------------------------------------------------------------
# Packaging — macOS DMG (manomatika/ahimsa#13, #14; manomatika/matika#29)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("job_name", MACOS_BUILD_JOBS)
def test_macos_job_builds_dmg_not_stub(workflow, job_name):
    """Each macOS job must produce a real DMG via dmgbuild, no TODO stub."""
    job = workflow["jobs"][job_name]
    runs = _job_run_blocks(job)
    # The PyInstaller .app is wrapped by the make_dmg helper (dmgbuild lib).
    assert "scripts/make_dmg.py" in runs, (
        f"{job_name} must invoke the make_dmg dmgbuild helper"
    )
    # No `touch <name>.dmg` placeholder may remain.
    assert "touch " not in runs, f"{job_name} still touches a placeholder DMG"
    # No remaining dmgbuild TODO step.
    assert not any(
        name.lstrip().startswith("TODO") and "dmgbuild" in name
        for name in _step_names(job)
    ), f"{job_name} still has a TODO dmgbuild stub"


def test_macos_dmg_filenames_follow_arch_convention(workflow):
    """arm64 job sets DMG_ARCH=arm64; intel job sets DMG_ARCH=x86_64, and the
    DMG name interpolates the arch so the artifacts match agent-E's upload
    names (<slug>-<version>-macos-<arch>.dmg)."""
    arm_step = _dmg_build_step(workflow, "build-macos-arm")
    intel_step = _dmg_build_step(workflow, "build-macos-intel")
    assert arm_step["env"]["DMG_ARCH"] == "arm64"
    assert intel_step["env"]["DMG_ARCH"] == "x86_64"
    assert "macos-${DMG_ARCH}" in arm_step["run"]
    assert "macos-${DMG_ARCH}" in intel_step["run"]


def _dmg_build_step(workflow: dict, job_name: str) -> dict:
    for step in workflow["jobs"][job_name]["steps"]:
        if "make_dmg.py" in step.get("run", ""):
            return step
    raise AssertionError(f"{job_name} has no DMG build step")


def test_make_dmg_helper_exists():
    assert (REPO_ROOT / "scripts" / "make_dmg.py").is_file()
    assert (REPO_ROOT / "scripts" / "_dmg_settings.py").is_file()


# ---------------------------------------------------------------------------
# Packaging — Windows installer (manomatika/ahimsa#17, #18; manomatika/matika#30)
# ---------------------------------------------------------------------------
def test_windows_job_runs_inno_setup_not_stub(workflow):
    job = workflow["jobs"]["build-windows"]
    runs = _job_run_blocks(job)
    assert "ISCC" in runs, "windows job must invoke Inno Setup compiler (ISCC)"
    assert "windows_installer.iss" in runs
    assert "touch " not in runs, "windows job still touches a placeholder exe"
    assert not any(
        name.lstrip().startswith("TODO") and "Inno" in name
        for name in _step_names(job)
    ), "windows job still has a TODO Inno Setup stub"


def test_iss_file_exists():
    assert ISS_FILE.is_file(), "windows_installer.iss must exist"


def test_iss_packages_directory_bundle_recursively():
    """#17: the [Files] section must recurse the whole one-dir bundle."""
    text = ISS_FILE.read_text()
    assert "recursesubdirs" in text, "iss must recurse the bundle directory"
    assert "createallsubdirs" in text
    # Source globs the bundle dir, not a single exe.
    assert "{#MyBundleDir}\\*" in text


def test_iss_appversion_is_dynamic():
    """#17: AppVersion must come from a define, never a hardcoded literal."""
    text = ISS_FILE.read_text()
    assert "AppVersion={#MyAppVersion}" in text, (
        "AppVersion must be driven by the MyAppVersion define"
    )


def test_windows_job_passes_version_defines_to_iscc(workflow):
    runs = _job_run_blocks(workflow["jobs"]["build-windows"])
    # Version + path are passed as /D defines so the iss stays recipe-driven.
    assert "/DMyAppVersion=" in runs
    assert "/DMyBundleDir=" in runs


# ---------------------------------------------------------------------------
# Release model guard — ahimsa does NOT create GitHub releases
# ---------------------------------------------------------------------------
def test_release_job_does_not_exist(workflow):
    """ahimsa must NOT have a release job. Product releases are cut by
    manomatika/manomatika. This guard prevents accidental re-introduction.
    """
    assert "release" not in workflow["jobs"], (
        "ahimsa must not have a release job — product releases belong to "
        "manomatika/manomatika; remove any re-introduced release job"
    )


def test_workflow_dispatch_only_trigger(workflow):
    """build.yml must be workflow_dispatch ONLY — no tag push, no PR.

    Tag push was removed (manomatika/ahimsa#55): ahimsa builds artifacts on
    demand only. PR trigger was never added (would let the QA gate fire early).
    """
    # PyYAML maps the bare `on:` key to the boolean True (the Norway problem).
    triggers = workflow.get(True, workflow.get("on"))
    assert triggers is not None, "could not locate the workflow `on:` block"
    assert "workflow_dispatch" in triggers, "build.yml must be workflow_dispatch-triggered"
    assert "push" not in triggers, (
        "build.yml must NOT have a push trigger — ahimsa builds on demand only"
    )
    assert "pull_request" not in triggers, (
        "build.yml must not run on pull_request"
    )


def test_release_notes_include_unsigned_limitation():
    """docs/release-notes/v0.0.4.md must carry the unsigned-installer known limitation.

    This file is the per-tag release notes source for the manomatika/manomatika
    product release. The unsigned-installer prose documents the known limitation
    that matika/eyerate/ahimsa installers are not yet code-signed.
    """
    notes_file = REPO_ROOT / "docs" / "release-notes" / "v0.0.4.md"
    assert notes_file.is_file(), "docs/release-notes/v0.0.4.md must exist"
    notes_text = notes_file.read_text()
    assert "not code-signed" in notes_text
    assert "Gatekeeper" in notes_text
    assert "SmartScreen" in notes_text
    assert "milestone/10" in notes_text


# ---------------------------------------------------------------------------
# workflow_dispatch refresh-releases-md job
# ---------------------------------------------------------------------------


def test_refresh_releases_md_job_exists(workflow):
    """The refresh-releases-md job must exist in the workflow."""
    assert "refresh-releases-md" in workflow["jobs"]


def test_refresh_releases_md_only_runs_on_workflow_dispatch(workflow):
    """The refresh-releases-md job must only run on workflow_dispatch.

    It must never run on tag push — that would risk an erroneous push
    that bypasses PR review.
    """
    job = workflow["jobs"]["refresh-releases-md"]
    cond = job["if"]
    assert "workflow_dispatch" in cond
    # Must NOT fire on push events — guard against accidental PR opens on tag push.
    assert "push" not in cond


def test_refresh_releases_md_opens_pr_not_direct_push(workflow):
    """The refresh job must open a PR, not push directly to main.

    Pushing directly to main would bypass code review and silently update
    the central release log without a review step.
    """
    job = workflow["jobs"]["refresh-releases-md"]
    runs = _job_run_blocks(job)
    # Must use gh pr create to open a PR.
    assert "gh pr create" in runs
    # Must NOT push directly to main.
    assert "push origin main" not in runs
    assert "push origin master" not in runs


def test_refresh_releases_md_uses_render_script(workflow):
    """The refresh job must run the render script, not inline rendering logic."""
    job = workflow["jobs"]["refresh-releases-md"]
    runs = _job_run_blocks(job)
    assert "render_releases_md.py" in runs


def test_refresh_releases_md_has_pr_write_permission(workflow):
    """The refresh job needs contents: write and pull-requests: write permissions."""
    job = workflow["jobs"]["refresh-releases-md"]
    perms = job.get("permissions", {})
    assert perms.get("contents") == "write"
    assert perms.get("pull-requests") == "write"


# ---------------------------------------------------------------------------
# Product-identity naming — user-facing artifacts and the installed bundle/exe
# are named after the PRODUCT (application.product_name + application.version),
# NOT after the matika component or matika's framework version.
# ---------------------------------------------------------------------------


def _pyinstaller_step(workflow: dict, job_name: str) -> dict:
    for step in workflow["jobs"][job_name]["steps"]:
        if "pyinstaller matika.spec" in step.get("run", ""):
            return step
    raise AssertionError(f"{job_name} has no pyinstaller step")


@pytest.mark.parametrize("job_name", BUILD_JOBS)
def test_recipe_info_reads_product_name(workflow, job_name):
    """recipe_info derives the artifact identity from application.product_name
    (the product brand), the lowercased+slugified filename slug, and the PRODUCT
    version — never the matika component name/version."""
    runs = _job_run_blocks(workflow["jobs"][job_name])
    assert 'r["application"]' in runs
    assert 'app["product_name"]' in runs
    assert "product_slug=" in runs
    assert "product_version=" in runs
    # The matika component version must NOT name any user-facing artifact.
    assert 'r["matika"]["version"]' not in runs
    assert "matika_version=" not in runs


@pytest.mark.parametrize("job_name", BUILD_JOBS)
def test_pyinstaller_step_passes_product_identity_env(workflow, job_name):
    """The spec is told the product identity via env so the frozen bundle is
    <product_name>-<product_version>, not Matika-<matika_version>."""
    step = _pyinstaller_step(workflow, job_name)
    env = step.get("env", {})
    assert env.get("MATIKA_PRODUCT_NAME") == "${{ steps.recipe_info.outputs.product_name }}"
    assert env.get("MATIKA_PRODUCT_VERSION") == "${{ steps.recipe_info.outputs.product_version }}"


@pytest.mark.parametrize("job_name", MACOS_BUILD_JOBS)
def test_dmg_named_after_product(workflow, job_name):
    """The DMG filename and the .app it wraps are product-named; the volume name
    is the product identity, not the descriptive application.name."""
    step = _dmg_build_step(workflow, job_name)
    run = step["run"]
    assert 'APP_BUNDLE="build/matika/dist/${PRODUCT_NAME}-${PRODUCT_VERSION}.app"' in run
    assert 'DMG_NAME="${PRODUCT_SLUG}-${PRODUCT_VERSION}-macos-${DMG_ARCH}.dmg"' in run
    assert '--volname "${PRODUCT_NAME} ${PRODUCT_VERSION}"' in run
    # The matika component version must not appear anywhere in the DMG step.
    assert "MATIKA_VERSION" not in run


def test_windows_installer_named_after_product(workflow):
    """The Windows installer's AppName/bundle/output basename are product-driven."""
    job = workflow["jobs"]["build-windows"]
    runs = _job_run_blocks(job)
    assert '/DMyAppName="%PRODUCT_NAME%"' in runs
    assert '/DMyAppVersion="%PRODUCT_VERSION%"' in runs
    assert 'set "BUNDLE_DIR=%CD%\\build\\matika\\dist\\%PRODUCT_NAME%-%PRODUCT_VERSION%"' in runs
    assert 'set "OUTPUT_BASENAME=%PRODUCT_SLUG%-%PRODUCT_VERSION%-windows-x86_64"' in runs
    # The removed matika-version define must not return.
    assert "/DMyMatikaVersion" not in runs


@pytest.mark.parametrize("job_name", BUILD_JOBS)
def test_upload_artifact_named_after_product(workflow, job_name):
    """Uploaded artifact names use the product slug + product version."""
    job = workflow["jobs"][job_name]
    upload = next(
        s for s in job["steps"]
        if "upload-artifact" in str(s.get("uses", ""))
    )
    name = upload["with"]["name"]
    assert name.startswith(
        "${{ steps.recipe_info.outputs.product_slug }}-"
        "${{ steps.recipe_info.outputs.product_version }}-"
    )


def test_iss_exe_name_derived_from_product_appname(workflow):
    """The .iss derives the exe from MyAppName + MyAppVersion (the product
    identity) and no longer carries a separate matika-version define."""
    text = ISS_FILE.read_text()
    assert '#define MyAppExeName MyAppName + "-" + MyAppVersion + ".exe"' in text
    assert "MyMatikaVersion" not in text
