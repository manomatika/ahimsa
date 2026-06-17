# ahimsa

**Recipe engine — build and validation system for Matika-based applications.**

A recipe repo is how a developer or software company defines, validates, and
releases a Matika application composed of one or more AppLugs. ahimsa provides
the schema, the validation rules, and the build machinery that turns a recipe
into a distributable installer.

---

## Mental Model

| Layer | What it is |
|---|---|
| **Matika** | The framework — a plugin-agnostic FastAPI host |
| **AppLugs** | Plugins — business logic that extends Matika |
| **recipe.json** | The lockfile — declares exactly which AppLugs and versions compose an application |
| **ahimsa** | The build machinery — validates recipes and produces installers |

A recipe is analogous to a `package.json` or a `Pipfile.lock`: it is the single
source of truth for what goes into a build. Exact version pins are mandatory —
no ranges, no wildcards.

---

## recipe.json Schema

```json
{
  "application": {
    "name": "string — human-readable application name",
    "version": "string — exact application version (X.Y.Z)",
    "bundle_id": "string — reverse-DNS bundle identifier (e.g. com.example.myapp)",
    "icon": "string — relative path to the .icns or .ico file"
  },
  "matika": {
    "version": "string — exact Matika version this recipe targets (X.Y.Z)",
    "repo": "string — source repository in <host>/<owner>/<repo> form (e.g. github.com/manomatika/matika)",
    "tag": "string — git tag to check out (e.g. v0.0.4)"
  },
  "applugs": [
    {
      "name": "string — AppLug identifier (matches applug.json id field)",
      "repo": "string — source repository (e.g. github.com/org/repo)",
      "version": "string — exact AppLug version to include (X.Y.Z)",
      "matika_version": "string — Matika version this AppLug was built against (X.Y.Z)",
      "tag": "string — git tag to check out (e.g. v0.0.2)"
    }
  ]
}
```

### Field Notes

- **`application.version`** is the version of the assembled application, independent
  of any individual component version.
- **`matika.version`** is the exact version of the Matika framework that will be
  bundled. The build system fetches this version of Matika.
- **`applugs[].matika_version`** is the Matika version each AppLug declares in its
  own `applug.json`. The validator checks this matches `matika.version` — an AppLug
  built against a different Matika version cannot be bundled.
- **`applugs[].tag`** is the git tag the build system checks out. It must correspond
  to the declared `version`.

---

## Installing the CLI

ahimsa ships two console scripts — `ahimsa-validate` and
`ahimsa-validate-releases`. There are two distinct ways to install, for two
distinct purposes; pick by what you need.

### Global commands (use the CLI from any directory): **pipx**

On a Homebrew-Python / PEP 668 "externally-managed" macOS system you must **not**
`pip install` into the system interpreter (it is refused, and forcing it with
`--break-system-packages` pollutes — and eventually corrupts — the Homebrew
Python). The blessed tool for installing a Python CLI globally on such a system
is [pipx](https://pipx.pypa.io/): it puts the app in its own isolated venv and
exposes the console scripts on `~/.local/bin` (which is on `PATH`).

Because ahimsa is actively developed locally, install it **editable** so the
global commands always track the canonical source tree:

```bash
brew install pipx        # one-time, if not already installed
pipx ensurepath          # one-time, ensures ~/.local/bin is on PATH

# editable install from your local clone — the global commands track the source:
pipx install --editable ~/dev/projects/ahimsa
```

Now `ahimsa-validate` / `ahimsa-validate-releases` work by bare name from any
directory:

```bash
ahimsa-validate <path/to/recipe.json>
ahimsa-validate-releases github.com/manomatika/matika  ...
```

Verify the on-PATH command is the pipx one (a single shim) and is backed by the
source tree:

```bash
which -a ahimsa-validate-releases     # -> ~/.local/bin/ahimsa-validate-releases (only)
```

Notes / durability:
- Editable means **code** edits are picked up immediately. If `pyproject.toml`
  **dependencies** change, refresh the isolated venv with
  `pipx reinstall ahimsa`.
- Do **not** `pip install` ahimsa into the Homebrew system Python. A stale
  system-Python editable install (e.g. one whose source dir was later removed)
  leaves dangling `/opt/homebrew/bin/ahimsa-*` shims that fail with
  `ModuleNotFoundError: No module named 'ahimsa'`. If you ever hit that, the
  fix is to remove the stale artifacts (the two `bin` shims plus the
  `ahimsa-*.dist-info/` and `_editable_impl_ahimsa.pth` recorded in the
  dist-info `RECORD`) and reinstall via pipx as above — never
  `--break-system-packages`.

### Running the test suite: a project virtualenv

pipx's isolated venv is for *running* the CLI, not for development/testing. To
run the tests, use a normal project venv (this is the standard pipx dev-workflow
split — global CLI via pipx, tests via a venv):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
pytest
```

## Validation Rules

Once the CLI is installed (see **Installing the CLI** above), run:

```bash
ahimsa-validate <path/to/recipe.json>
# or, equivalently, with any interpreter that has ahimsa importable:
python -m ahimsa.validate_recipe <path/to/recipe.json>
```

The earlier `scripts/validate_recipe.py` entry point no longer exists — the validator was reorganised into the installable `ahimsa` package.

The following rules are enforced:

1. **Exact version pins only.** Every version field (`application.version`,
   `matika.version`, `applugs[].version`, `applugs[].matika_version`) must be
   an exact `X.Y.Z` string. Ranges (`^1.0`, `>=0.0.2`, `*`) are rejected.

2. **All AppLugs must declare identical `matika_version` values.** You cannot
   mix AppLugs built against different Matika versions in the same recipe.

3. **All AppLug `matika_version` values must match `recipe.matika.version`.**
   The Matika version bundled by the build system must be the same version each
   AppLug was built and tested against.

---

## Adding a New AppLug to a Recipe

1. Ensure the AppLug's `applug.json` declares a `matika_version` that matches
   the `matika.version` in your recipe. If it does not, the AppLug must be
   updated first.

2. Add an entry to the `applugs` array:
   ```json
   {
     "name": "myplugin",
     "repo": "github.com/org/myplugin",
     "version": "1.2.0",
     "matika_version": "0.0.4",
     "tag": "v1.2.0"
   }
   ```

3. Run validation: `ahimsa-validate <path/to/recipe.json>` (the recipe lives
   in `manomatika/manomatika`; clone mm and supply the local path).

4. Commit the updated recipe to `manomatika/manomatika` and open a PR there.

---

## Backward Compatibility Guarantee

Matika 0.0.2 establishes the formal compatibility contract baseline:

> **No breaking changes will be made to the `BaseAppLug` interface or the
> plugin discovery contract within a Matika minor version.**

Concretely:
- An AppLug built against Matika `0.0.2` will continue to load on any
  `0.0.x` release (patch bumps are non-breaking).
- A minor version bump (`0.1.0`) may introduce breaking changes to the
  interface. AppLugs must update their `matika_version` declaration and
  be re-tested before being included in a recipe targeting the new minor.
- ahimsa enforces this at recipe-validation time: mismatched `matika_version`
  values are a hard error.
