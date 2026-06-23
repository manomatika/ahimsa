> Part of [CLAUDE.md](../CLAUDE.md) — see the main file for orientation.

## Validation Rules

`validate_recipe.py` enforces all rules in a single pass, accumulating errors rather than failing fast. Every error carries a JSON pointer and a clear message. Exit codes: 0 (clean), 1 (validation failure), 2 (configuration error — bad `--config` path or malformed config JSON).

**Schema validation**
- Required fields: `application.{name, product_name, version, bundle_id, icon}`, `matika.{version, repo, tag}`, `applugs` (non-empty array), per-applug `{name, repo, version, matika_version, tag}`
- `product_name` is the canonical PRODUCT identity that names all user-facing artifacts and the installed bundle/exe. `build.yml` lower-cases + slugifies it for the artifact FILENAME (`<product_slug>-<version>-<os>-<arch>.dmg/.exe`) and uses it verbatim as the proper-noun installed identity (`<product_name>-<version>.app`/`.exe`, e.g. `ManoMatika-0.0.1`). `application.name` is a separate descriptive title and no longer drives any artifact/bundle name. Format: ASCII alphanumerics separated by single spaces or hyphens, starting and ending with an alphanumeric (`^[A-Za-z0-9]([A-Za-z0-9]| [A-Za-z0-9]|-[A-Za-z0-9])*$`) — underscores, dots, slashes, leading/trailing/double separators, and non-ASCII are rejected so the name slugs cleanly for a filename and reads as a bundle name
- Version (pin) format: every pin field (`application.version`, `matika.version`, applug `version`/`matika_version`) must match `^\d+\.\d+\.\d+$` exactly (bare core) — ranges (`^`, `>=`, `~`), wildcards (`*`, `latest`, `1.x`), and pre-release/build suffixes (`-dev`, `-rc.N`, `-rc1`, `+build`) are all rejected. The `tag` fields are git refs, not pins, and are NOT version-format-checked — a recipe may pin matika/applugs at a pre-release tag like `v0.0.4-rc.1` while the corresponding bare-core `version` stays `0.0.4`
- `bundle_id` format: reverse-DNS, minimum 3 dot-separated components, each starting with a letter and containing only letters/digits/hyphens: `^[a-zA-Z][a-zA-Z0-9-]*(\.[a-zA-Z][a-zA-Z0-9-]*){2,}$`

**Consistency rules**
- All `applugs[i].matika_version` values must be identical — mixing applugs built against different Matika versions is a hard error
- Every `applugs[i].matika_version` must equal `matika.version` — the bundled Matika must match what every applug declares it was built against

**Remote verification**
- For each structurally-valid applug, fetches `applug.json` from the declared GitHub repo at the declared tag via the Resolver (see below)
- Verifies: `applug.json.id` matches recipe `name`; `applug.json.version` matches recipe `version`; `applug.json.matika_version` matches recipe `matika_version`

**Repo format**
- `applugs[i].repo` (and `matika.repo`) must be exactly `<host>/<owner>/<repo>` — no URL scheme, no trailing `.git`, no SSH form, exactly three slash-separated components

## Config Precedence

```
--config <path>   >   walked-up config.json   >   default ["github.com"]
```

No environment-variable override. Walk-up starts at the recipe's directory,
stops at the first `config.json` found, or at a project-root marker (`.git`,
`pyproject.toml`, `package.json`), never crossing the filesystem root.

Security rationale: `config.json` is committed to the repo and controls which hosts recipes may reference. Keeping it in-repo (not env-vars) means the policy is auditable, version-controlled, and can't be silently overridden by the shell environment. This becomes important when ahimsa accepts third-party recipes (M4 registry era) — a recipe cannot bypass the validator's policy by declaring its own allowed hosts.

The defense is incomplete without code signing: unsigned installers can be modified in transit to ship a permissive `config.json` or a tampered validator. Code signing and notarization track in [M5 — Code Signing & Distribution Security](https://github.com/manomatika/ahimsa/milestone/10) and are required before any external distribution.
