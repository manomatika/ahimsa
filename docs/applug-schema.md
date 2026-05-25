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
  "version": "0.0.4",
  "matika_version": "0.0.4",
  "name": "EyeRate",
  "description": "Real-time eye strain scoring for extended work sessions.",
  "author": "Patrick Tallman",
  "license": "MIT",
  "entry_point": "eyerate.plugin:EyeRatePlugin"
}
```

---

## repo Format

`applugs[].repo` (and `matika.repo`) must be exactly three slash-separated
components: `<host>/<owner>/<repo>`. No URL scheme, no trailing `.git`, no SSH
form.

| Form | Valid? |
|---|---|
| `github.com/manomatika/Matika` | ✓ |
| `https://github.com/manomatika/Matika` | ✗ — no scheme allowed |
| `github.com/manomatika/Matika.git` | ✗ — trailing `.git` not allowed |
| `git@github.com:manomatika/Matika.git` | ✗ — SSH form not allowed |
| `manomatika/Matika` | ✗ — host component required |

The host component must appear in `allowed_hosts` (see below) or the validator
rejects the recipe.

---

## allowed_hosts

ahimsa maintains a whitelist of hosts from which applugs may be fetched.

**Default:** `["github.com"]`

**Configuration precedence (highest → lowest):**

1. `--config <path>` CLI flag — explicit path to a config.json file.
2. Walked-up `config.json` — the validator searches upward from the recipe
   file's directory, stopping at the first `config.json` found or at a
   project-root marker (`.git`, `pyproject.toml`, `package.json`).
3. Built-in default: `["github.com"]`

There is no environment-variable override. Configuration lives in files,
not in the process environment.

**Walk-up algorithm:**

Starting at the recipe file's directory, at each level:
1. If `config.json` is present, use it and stop.
2. If a project-root marker (`.git`, `pyproject.toml`, `package.json`) is
   present, stop and use the default.
3. Otherwise, ascend one level. Stop at the filesystem root.

This means the closest `config.json` wins, and the walk never escapes the
project tree to find an unrelated config in an ancestor directory.

**`--config` flag:**

```
ahimsa-validate --config path/to/config.json recipes/myapp/recipe.json
```

Exit code 2 if the provided config file is missing or contains malformed JSON.

If `config.json` is absent (and no `--config` given), the default is used
silently. If a `config.json` is found but contains malformed JSON, validation
aborts with exit code 2.

---

## How ahimsa Fetches applug.json

For each AppLug in a recipe, ahimsa:

1. Verifies the repo host is in `allowed_hosts`.
2. Canonicalizes the owner/repo casing via the GitHub API (case-insensitive)
   and caches the result for the process lifetime — recipes with multiple
   AppLugs from the same org hit the API once.
3. Constructs the raw URL:

```
https://raw.githubusercontent.com/<canonical-owner>/<canonical-repo>/<tag>/applug.json
```

The validator then asserts:

| Check | Expected |
|---|---|
| File exists (HTTP 200) | — |
| `id` | equals `applugs[].name` |
| `version` | equals `applugs[].version` |
| `matika_version` | equals `applugs[].matika_version` (and therefore `recipe.matika.version`) |
