# ahimsa

**Build, validation, and release system for Matika-based applications.**

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
    "version": "string — exact Matika version this recipe targets (X.Y.Z)"
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

## Validation Rules

Run `python scripts/validate_recipe.py <path/to/recipe.json>` to validate.

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
     "matika_version": "0.0.2",
     "tag": "v1.2.0"
   }
   ```

3. Run validation: `python scripts/validate_recipe.py recipes/<app>/recipe.json`

4. Commit the updated recipe and push. The `validate.yml` GitHub Action will
   run automatically.

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
