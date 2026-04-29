# applug.json Schema

`applug.json` is the manifest file every AppLug must ship at its repository
root. ahimsa fetches this file from the AppLug's declared GitHub repo and tag
during recipe validation to verify compatibility before including the AppLug in
a build.

---

## Required Fields

| Field | Type | Description |
|---|---|---|
| `id` | string | AppLug identifier. Must match `applugs[].name` in the recipe. |
| `version` | string | AppLug version. Exact `X.Y.Z` pin. Must match `applugs[].version` in the recipe. |
| `matika_version` | string | Matika version this AppLug was built and tested against. Exact `X.Y.Z` pin. **Must match `recipe.matika.version` at validation time.** |

## Optional Fields

| Field | Type | Description |
|---|---|---|
| `name` | string | Human-readable display name. |
| `description` | string | Short description of what the AppLug does. |
| `author` | string | Author name or organization. |
| `license` | string | SPDX license identifier (e.g. `MIT`, `Apache-2.0`). |
| `entry_point` | string | Python import path to the AppLug class (e.g. `eyerate.plugin:EyeRatePlugin`). |

---

## matika_version

`matika_version` is a required field. ahimsa enforces three rules:

1. **Exact pin only.** The value must be an exact `X.Y.Z` string. Ranges
   (`^1.0`, `>=0.0.2`, `~0.0.2`), wildcards (`*`), and aliases (`latest`)
   are rejected.

2. **Cross-applug consistency.** Every `applugs[].matika_version` in a recipe
   must be identical. You cannot mix AppLugs built against different Matika
   versions in a single recipe.

3. **Recipe-matika agreement.** Every `applugs[].matika_version` must equal
   `recipe.matika.version`. The Matika bundled by the build system must be the
   same version each AppLug was built and tested against.

### Compatibility guarantee

An AppLug built against Matika `0.0.2` will load on any `0.0.x` release —
patch bumps are non-breaking. A minor-version bump (`0.1.0`) may introduce
breaking interface changes. AppLugs must update their `matika_version`
declaration and be re-tested before inclusion in a recipe targeting the new
minor.

---

## Example

```json
{
  "id": "eyerate",
  "version": "0.0.2",
  "matika_version": "0.0.2",
  "name": "EyeRate",
  "description": "Real-time eye strain scoring for extended work sessions.",
  "author": "Patrick Tallman",
  "license": "MIT",
  "entry_point": "eyerate.plugin:EyeRatePlugin"
}
```

---

## How ahimsa Fetches applug.json

For each AppLug in a recipe, ahimsa constructs:

```
https://raw.githubusercontent.com/<org>/<repo>/<tag>/applug.json
```

using `applugs[].repo` (with `github.com/` prefix stripped) and
`applugs[].tag`. The validator then asserts:

| Check | Expected |
|---|---|
| File exists (HTTP 200) | — |
| `id` | equals `applugs[].name` |
| `version` | equals `applugs[].version` |
| `matika_version` | equals `applugs[].matika_version` (and therefore `recipe.matika.version`) |
