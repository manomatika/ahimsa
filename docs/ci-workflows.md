> Part of [CLAUDE.md](../CLAUDE.md) — see the main file for orientation.

## GitHub Actions Workflows

- **`validate.yml`** — runs on every push and PR to `main`. Installs via `pip install uv` → `uv sync --frozen` → `uv run pytest tests/` (the COMPLETE suite — unit, invocation, AND the real-network integration tier; nothing deselected, per rule 21). Mints a GitHub App token (`permission-contents: read`) and fetches the reference recipe from `manomatika/manomatika`, then runs `uv run ahimsa-validate "$RECIPE_PATH"` as a live recipe-validation step.
- **`build.yml`** — runs on `workflow_dispatch` only. Inputs: `recipe_path`
  (default `recipes/reference-app/recipe.json`) and `manomatika_ref` (branch/tag/SHA
  in mm to fetch the recipe from — for cross-repo validation builds; default `""`).
  The `push: tags: v*` trigger and the `release` job have been removed; ahimsa
  builds artifacts on demand, never creates GitHub releases. Jobs:
  - `validate` → fetches recipe from `manomatika/manomatika` (using a minted App token, `permission-contents: write`), installs ahimsa via `pip install uv` → `uv sync --frozen`, runs `uv run ahimsa-validate "$RECIPE_PATH"` (fail fast).
  - `build-macos-arm` (**macos-14**), `build-macos-intel` (**macos-15-intel** —
    `macos-13` was retired), `build-windows` (**windows-latest**) — all
    `needs: validate`, run in parallel. **Fully implemented, not stubbed.** Each job:
    1. fetches recipe from mm, reads metadata, clones matika at `recipe.matika.tag`,
       clones each applug into `build/matika/plugins/`;
    2. **extracts matika's runtime deps from `pyproject.toml` and installs them
       individually BEFORE PyInstaller** (bypasses the `requires-python>=3.14` gate
       since CI runs Python 3.11; individual packages are 3.11-compatible); similarly
       installs each applug's deps from its `pyproject.toml` (falling back to
       `requirements.txt` for older pinned tags) — so `collect_all()` in
       `matika.spec` actually finds `alembic`/`curl_cffi`/`yfinance` rather than
       being a no-op (this ordering is why the freeze stopped failing with "No module
       named 'alembic'");
    3. `npm install && npm run build`, then `pyinstaller matika.spec --noconfirm`,
       asserting the bundle name matches the recipe's product identity;
    4. wraps the output — macOS via `scripts/make_dmg.py` (dmgbuild); Windows via
       `installer/windows_installer.iss` driven by **Inno Setup's `ISCC` on the
       runner PATH** (the bundle/output dirs are passed as absolute `%CD%`-rooted
       paths; the `.iss` path itself is repo-relative);
    5. **smoke-launches** the frozen app (`scripts/smoke_launch.py` — boot, migrate,
       load the `eyerate` applug, serve);
    6. runs the **frozen feature gate against the freeze-dir artifact, both
       scenarios** — `scripts/frozen_verify.py --exe <freeze-dir> --source-root
       build/matika --functional --scenario fresh` and `--scenario upgrade`, each
       with `--browser`. `--source-root build/matika` points discovery at the
       pinned source clones; tier-a (HTTP route liveness) + tier-b (Playwright DOM)
       are **L2**, and `--functional` runs **L3** (the applug-authored functional
       tests, reboot-per-applug, randomized seeded order — see
       [docs/frozen-verify.md](frozen-verify.md)). The `upgrade` scenario seeds a
       stale plugin (old version, marker removed, user data added) and asserts the
       launcher refreshed the code AND preserved the user data;
    7. uploads the DMG/EXE as a CI artifact, and **emits the resolved commit SHAs**
       of its pinned clones as job outputs (`matika_sha`, `applug_shas`) for the
       matching install-verify job to pin against.
  - `install-verify-macos-arm` (**macos-14**), `install-verify-macos-intel` (**macos-15-intel**), `install-verify-windows` (**windows-latest**) — each `needs` its corresponding build job. Downloads the DMG/EXE artifact, mounts/installs it to the OS-standard install path, then **side-clones the same sources checked out at the build job's resolved SHAs** (`needs.build-*.outputs.matika_sha` / `.applug_shas` — the Option-3 source-root fork; mutable tags are never re-resolved on the verify side) and re-runs `smoke_launch.py` + `frozen_verify.py --exe <installed-binary> --source-root build/matika --functional --scenario fresh` and `--scenario upgrade --browser` against the **installed** binary (not the freeze-dir artifact). Closes the installer-level gap: proves the packaged DMG/EXE ships a launchable bundle at the correct install path, and that L2+L3 feature checks pass on both install paths from the installed location.
  - `refresh-releases-md` (**ubuntu-latest**) — runs only on a production dispatch (skipped when `manomatika_ref` is set, i.e. a cross-repo validation build). Mints a GitHub App token, checks out `manomatika/manomatika`, re-renders `RELEASES.md` from that repo's `release-log.yaml` via `scripts/render_releases_md.py`, and opens a PR to `manomatika/manomatika` with the updated file (no-op if already current). ahimsa owns the rendering *mechanism*; the audit-log content lives in `manomatika/manomatika`.
