> Part of [CLAUDE.md](../CLAUDE.md) — see the main file for orientation.

## Test Fixture Convention

`tests/fixtures/` contains per-scenario directories, each self-contained:
- `invalid_host/` — `recipe.json` + `config.json` allowing only `github.com` → policy rejects `test.invalid`
- `valid_local_config/` — same recipe + `config.json` allowing `test.invalid` → policy passes, dispatch fails (no resolver registered for `test.invalid`)
- `no_config/` — same recipe + `pyproject.toml` stop-marker, no `config.json` → walk-up stops, default policy rejects `test.invalid`

`test.invalid` is an RFC 6761 reserved name that never resolves on any real network — every fixture test runs offline.
