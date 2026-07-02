"""
error_codes.py — ahimsa's error-code MECHANISM (schema, lints, aggregator, codegen).

ahimsa owns the *mechanism* of the ecosystem error-code framework (Model A, see
manomatika-v0.0.1-plan.md §2); it does not own the codes. Each origin
(matika / eyerate / ahimsa / manomatika) declares its own codes in a per-origin
``error-codes.yaml`` that must conform to the schema documented here. This module
provides:

  - the SCHEMA constants (closed severity/log_route sets, origin<->component map)
    and the loader that reads an ``error-codes.yaml`` into typed objects;
  - the LINTS that validate a single file for well-formedness, schema
    conformance, and per-file code uniqueness (numbers are opaque and
    MONOTONIC — reserved/retired/skipped values are allowed, so gaps are NOT
    a defect; only a duplicate is);
  - the BLOCKING AGGREGATOR that merges every origin's file and validates the
    merged per-build registry (cross-file uniqueness, component-prefix
    disjointness, and — under ``require_all_origins`` — registry parity: every
    expected origin present). It enumerates ALL findings, then :func:`main`
    exits 1 if any exist and 0 when the merged registry is clean (V/X). The
    aggregator was report-only at R0; it was flipped to blocking in R6
    (manomatika/ahimsa#129);
  - the CODEGEN that renders a file into a module of typed constants, giving
    compile-time "can't emit an unregistered code" safety.

Schema of an ``error-codes.yaml`` (top-level mapping):

    origin: matika                 # lowercase repo slug (one of the four)
    component: MATIKA              # uppercase prefix; must match the origin
    supported_locales: [en, es]   # non-empty; must include 'en'
    codes:                        # list; MAY be empty (reserved namespace)
      - code: MATIKA-LNCH-001     # well-formed <COMPONENT>-<FAC>-<NNN>
        severity: error           # closed set: fatal | error | warning
        log_route: startup        # closed set: startup | aggregate | n/a
        message: Foreign lock holder detected   # dev-facing / en source text

Facility and number are DERIVED from the code string (the code is the single
carrier) — they are not separate fields. The empty ``manomatika`` namespace
(``codes: []``) is a well-formed file.

Fail-loud discipline (rule 18): ``parse_error_codes_text`` raises only when the
input is structurally unparseable; every schema/value violation is surfaced as a
concrete ``Error`` (pointer + message carrying the offending value) so the
blocking aggregator can enumerate ALL findings across ALL files before failing —
most-data-available, never crashing on the first bad one.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ahimsa.manomatika_error import CODE_PATTERN, CODE_RE, parse_code
from ahimsa.validate_recipe import Error

# ---------------------------------------------------------------------------
# Schema constants (closed sets — see plan §2.1)
# ---------------------------------------------------------------------------

# Severity is a CLOSED enum; log_route is a CLOSED set. Ordered tuples keep the
# error messages deterministic.
SEVERITIES: tuple[str, ...] = ("fatal", "error", "warning")
LOG_ROUTES: tuple[str, ...] = ("startup", "aggregate", "n/a")

# The one-to-one origin(lowercase slug) <-> component(uppercase prefix) mapping.
# Global uniqueness of codes holds by prefix-disjointness, so this map is also
# the authority the aggregator uses to check no two origins share a component.
COMPONENT_FOR_ORIGIN: dict[str, str] = {
    "matika": "MATIKA",
    "eyerate": "EYERATE",
    "ahimsa": "AHIMSA",
    "manomatika": "MANOMATIKA",
}

# The locale every origin's catalog must provide (English is the source locale;
# it never drifts because en entries are generated from the registry).
REQUIRED_LOCALE = "en"

_REQUIRED_CODE_FIELDS = ("code", "severity", "log_route", "message")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ErrorCode:
    """A single validated code entry, with facility/number derived from ``code``."""

    code: str
    severity: str
    log_route: str
    message: str
    component: str
    facility: str
    number: int


@dataclass
class ErrorCodesFile:
    """A validated ``error-codes.yaml`` as typed objects.

    Produced by :func:`load_error_codes` only after the file lints cleanly, so
    consumers (the codegen) never see a malformed registry.
    """

    origin: str
    component: str
    supported_locales: list[str]
    codes: list[ErrorCode] = field(default_factory=list)


@dataclass
class RawErrorCodesFile:
    """A leniently-parsed ``error-codes.yaml``.

    Structural parsing only: the top level is a mapping and ``codes`` is a list
    of mappings. Missing/blank values are tolerated here and surfaced by the
    lints as :class:`Error`, so the blocking aggregator can enumerate every
    violation instead of crashing on the first one.
    """

    path: str
    origin: Any
    component: Any
    supported_locales: Any
    raw_codes: list[Any]


# ---------------------------------------------------------------------------
# Parsing (fail-loud only for structurally unparseable input)
# ---------------------------------------------------------------------------


def parse_error_codes_text(text: str, *, path: str = "<error-codes.yaml>") -> RawErrorCodesFile:
    """Parse ``error-codes.yaml`` *content* into a :class:`RawErrorCodesFile`.

    Raises ``ImportError`` if pyyaml is unavailable, and ``ValueError`` — naming
    *path* and the offending shape — ONLY when the input is structurally
    unparseable (invalid YAML, non-mapping top level, or a ``codes`` value that
    is not a list). Every other issue is left for the lints so that a single bad
    file cannot abort a whole-registry aggregation.
    """
    try:
        import yaml
    except ImportError as e:  # pragma: no cover - pyyaml is a hard dependency
        raise ImportError(
            "pyyaml is required to parse error-codes.yaml. "
            "Install it with: pip install pyyaml"
        ) from e

    try:
        raw: Any = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"{path}: malformed YAML — {e}") from e

    if not isinstance(raw, dict):
        raise ValueError(
            f"{path}: top level must be a mapping with keys "
            f"origin/component/supported_locales/codes, got {type(raw).__name__}"
        )

    codes_value = raw.get("codes", [])
    if codes_value is None:
        codes_value = []
    if not isinstance(codes_value, list):
        raise ValueError(
            f"{path}: 'codes' must be a list, got {type(codes_value).__name__}"
        )

    return RawErrorCodesFile(
        path=path,
        origin=raw.get("origin"),
        component=raw.get("component"),
        supported_locales=raw.get("supported_locales"),
        raw_codes=list(codes_value),
    )


# ---------------------------------------------------------------------------
# Lints (validate one file; return ALL findings)
# ---------------------------------------------------------------------------


def _pointer(origin: Any, suffix: str = "") -> str:
    label = origin if isinstance(origin, str) and origin else "?"
    return f'error-codes["{label}"]{suffix}'


def lint_error_codes(raw: RawErrorCodesFile) -> list[Error]:
    """Validate a single parsed ``error-codes.yaml`` and return ALL violations.

    Enforces, per the plan §2:
      - ``origin`` present and a known lowercase slug;
      - ``component`` present, uppercase, and equal to the origin's component;
      - ``supported_locales`` a non-empty list that includes ``'en'``;
      - each entry carries the required fields (code/severity/log_route/message);
      - each ``code`` matches ``<COMPONENT>-<FAC>-<NNN>``;
      - each code's component prefix equals the file's declared component;
      - ``severity`` / ``log_route`` are in their closed sets;
      - codes are unique within the file — which, since the component prefix is
        forced equal to the file's declared component, also makes each
        (origin, facility) NNN unique. NNN values are opaque and MONOTONIC:
        reserved / retired / skipped numbers are expected, so GAPS are allowed
        (``001, 002, 004`` is valid); only a DUPLICATE is a defect.

    An empty ``codes`` list (the reserved ``manomatika`` namespace) is valid.
    """
    errors: list[Error] = []
    origin = raw.origin

    # --- origin ---
    if not isinstance(origin, str) or not origin:
        errors.append(Error(_pointer(origin, ".origin"), "missing or non-string 'origin'"))
    elif origin not in COMPONENT_FOR_ORIGIN:
        errors.append(Error(
            _pointer(origin, ".origin"),
            f"unknown origin {origin!r}; expected one of "
            f"{sorted(COMPONENT_FOR_ORIGIN)}",
        ))

    # --- component (and origin<->component agreement) ---
    expected_component = COMPONENT_FOR_ORIGIN.get(origin) if isinstance(origin, str) else None
    component = raw.component
    if not isinstance(component, str) or not component:
        errors.append(Error(_pointer(origin, ".component"), "missing or non-string 'component'"))
    elif expected_component is not None and component != expected_component:
        errors.append(Error(
            _pointer(origin, ".component"),
            f"component {component!r} does not match origin {origin!r}; "
            f"expected {expected_component!r}",
        ))

    # --- supported_locales ---
    locales = raw.supported_locales
    if not isinstance(locales, list) or not locales:
        errors.append(Error(
            _pointer(origin, ".supported_locales"),
            f"'supported_locales' must be a non-empty list, got {locales!r}",
        ))
    elif REQUIRED_LOCALE not in locales:
        errors.append(Error(
            _pointer(origin, ".supported_locales"),
            f"'supported_locales' must include {REQUIRED_LOCALE!r}, got {locales!r}",
        ))

    # --- per-code checks ---
    seen: dict[str, int] = {}

    for i, item in enumerate(raw.raw_codes):
        cptr = _pointer(origin, f".codes[{i}]")
        if not isinstance(item, dict):
            errors.append(Error(cptr, f"code entry must be a mapping, got {type(item).__name__}"))
            continue

        missing = [f for f in _REQUIRED_CODE_FIELDS if f not in item or item[f] is None]
        if missing:
            errors.append(Error(cptr, f"missing required field(s): {missing}"))

        code = item.get("code")
        severity = item.get("severity")
        log_route = item.get("log_route")

        # severity / log_route closed sets (independent of code validity).
        if severity is not None and severity not in SEVERITIES:
            errors.append(Error(cptr, (
                f"severity {severity!r} not in closed set {list(SEVERITIES)}"
            )))
        if log_route is not None and log_route not in LOG_ROUTES:
            errors.append(Error(cptr, (
                f"log_route {log_route!r} not in closed set {list(LOG_ROUTES)}"
            )))

        # code well-formedness + prefix agreement + uniqueness.
        if not isinstance(code, str) or not CODE_RE.match(code):
            errors.append(Error(cptr, (
                f"code {code!r} is not well-formed; expected "
                f"<COMPONENT>-<FAC>-<NNN> ({CODE_PATTERN})"
            )))
            continue

        code_component, _facility, _number = parse_code(code)
        if isinstance(component, str) and component and code_component != component:
            errors.append(Error(
                _pointer(origin, f'.codes["{code}"]'),
                f"code prefix {code_component!r} does not match the file's "
                f"component {component!r}",
            ))

        # Uniqueness is enforced on the whole code string. Because the prefix
        # is required to equal the file's component (checked above), a unique
        # code string also guarantees a unique (facility, NNN) pair — so no
        # separate per-facility number check is needed. NNN values are opaque
        # and MONOTONIC: gaps (reserved/retired/skipped numbers) are allowed;
        # only a genuine duplicate is a defect.
        if code in seen:
            errors.append(Error(
                _pointer(origin, f'.codes["{code}"]'),
                f"duplicate code (also at codes[{seen[code]}])",
            ))
        else:
            seen[code] = i

    return errors


# ---------------------------------------------------------------------------
# Loader (fail-loud: refuse to hand back a malformed registry)
# ---------------------------------------------------------------------------


def load_error_codes(path: str | Path) -> ErrorCodesFile:
    """Read and VALIDATE *path*, returning typed :class:`ErrorCodesFile`.

    Runs the full lints; raises ``ValueError`` — carrying *path* and every
    violation — if the file does not lint cleanly. Used by the codegen, which
    must never generate constants from a malformed registry (compile-time
    "can't emit an unregistered code" safety depends on the source being valid).
    Raises ``FileNotFoundError`` if *path* is missing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"error-codes.yaml not found at {path}")

    raw = parse_error_codes_text(path.read_text(), path=str(path))
    errors = lint_error_codes(raw)
    if errors:
        joined = "\n  ".join(str(e) for e in errors)
        raise ValueError(f"{path}: error-codes.yaml is invalid:\n  {joined}")

    codes: list[ErrorCode] = []
    for item in raw.raw_codes:
        code = item["code"]
        component, facility, number = parse_code(code)
        codes.append(ErrorCode(
            code=code,
            severity=item["severity"],
            log_route=item["log_route"],
            message=str(item["message"]),
            component=component,
            facility=facility,
            number=number,
        ))
    return ErrorCodesFile(
        origin=raw.origin,
        component=raw.component,
        supported_locales=list(raw.supported_locales),
        codes=codes,
    )


# ---------------------------------------------------------------------------
# Aggregator (BLOCKING — :func:`main` exits 1 on any finding: V/X)
# ---------------------------------------------------------------------------


def aggregate_error_codes(
    paths: list[str | Path], *, require_all_origins: bool = False
) -> list[Error]:
    """Aggregate every origin's ``error-codes.yaml`` and validate the MERGED registry.

    For each file: parse (leniently) and run the per-file lints. Then validate
    the union (registry parity — the merged per-build registry must agree with
    the per-origin DECLARED registries):

      - **dup** — no code string appears in more than one origin, and no two
        origins declare the same component (prefix-disjointness). A duplicate is
        drift: a code/component in the merged registry not backed by *exactly
        one* declaring origin.
      - **missing-origin** (only when *require_all_origins* is True) — every
        expected origin in :data:`COMPONENT_FOR_ORIGIN`
        (matika / eyerate / ahimsa / manomatika) must contribute a declaring
        file to the inputs. The product gate feeds all four SHA-pinned sources
        and sets this flag, so an origin whose ``error-codes.yaml`` is absent
        from the merged registry inputs fails the gate.

    Returns ALL findings — per-file lint, cross-file dup, and (when required)
    missing-origin — as a flat list. This function is pure: it computes findings
    but takes no action on them. The BLOCKING policy (exit 1 on any finding)
    lives in :func:`main`; the aggregator was flipped from report-only to
    blocking in R6 (manomatika/ahimsa#129).
    """
    errors: list[Error] = []
    # code -> origin that first declared it; component -> origin likewise.
    code_owner: dict[str, str] = {}
    component_owner: dict[str, str] = {}
    # Expected origins that actually contributed a declaring file (parity input).
    present_origins: set[str] = set()

    for path in paths:
        p = Path(path)
        try:
            raw = parse_error_codes_text(p.read_text(), path=str(p))
        except FileNotFoundError:
            errors.append(Error(f'error-codes.file["{p}"]', "file not found"))
            continue
        except ValueError as e:
            errors.append(Error(f'error-codes.file["{p}"]', str(e)))
            continue

        errors.extend(lint_error_codes(raw))

        origin = raw.origin if isinstance(raw.origin, str) and raw.origin else str(p)
        if isinstance(raw.origin, str) and raw.origin in COMPONENT_FOR_ORIGIN:
            present_origins.add(raw.origin)

        # Cross-file component disjointness.
        if isinstance(raw.component, str) and raw.component:
            prior = component_owner.get(raw.component)
            if prior is not None and prior != origin:
                errors.append(Error(
                    f'error-codes.registry.component["{raw.component}"]',
                    f"component declared by both {prior!r} and {origin!r}",
                ))
            else:
                component_owner[raw.component] = origin

        # Cross-file code uniqueness.
        for item in raw.raw_codes:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            if not isinstance(code, str) or not CODE_RE.match(code):
                continue
            prior_origin = code_owner.get(code)
            if prior_origin is not None:
                errors.append(Error(
                    f'error-codes.registry.code["{code}"]',
                    f"code declared by both {prior_origin!r} and {origin!r}",
                ))
            else:
                code_owner[code] = origin

    # Registry-parity: every expected origin must be present in the merged
    # inputs. Enumerated LAST (after every per-file/cross-file finding) so the
    # blocking gate reports the most data available (rule 18) before failing.
    if require_all_origins:
        for expected_origin, expected_component in COMPONENT_FOR_ORIGIN.items():
            if expected_origin not in present_origins:
                errors.append(Error(
                    f'error-codes.registry.origin["{expected_origin}"]',
                    f"expected origin {expected_origin!r} (component "
                    f"{expected_component!r}) is absent from the merged registry "
                    f"inputs (missing-origin)",
                ))

    return errors


# ---------------------------------------------------------------------------
# Codegen (typed constants — "can't emit an unregistered code")
# ---------------------------------------------------------------------------


def _const_name(code: str) -> str:
    """``MATIKA-LNCH-001`` -> ``MATIKA_LNCH_001`` (a valid Python identifier)."""
    return code.replace("-", "_")


def render_constants_module(ecf: ErrorCodesFile) -> str:
    """Render *ecf* into the SOURCE of a typed-constants module.

    Emits one ``NAME = "CODE"`` constant per code, an ``ALL_CODES`` frozenset,
    and a ``CODE_METADATA`` mapping (code -> severity/log_route/facility) for the
    downstream stamping filter. Emit sites reference the constants, so a code
    that is not in the registry has no constant and cannot be emitted.
    """
    lines: list[str] = []
    lines.append(f'# AUTO-GENERATED by scripts/gen_error_codes.py from {ecf.origin}\'s')
    lines.append("# error-codes.yaml. DO NOT EDIT — regenerate from the YAML source.")
    lines.append(f'"""Typed error-code constants for {ecf.origin} ({ecf.component})."""')
    lines.append("")
    lines.append(f"COMPONENT = {ecf.component!r}")
    lines.append(f"SUPPORTED_LOCALES = {list(ecf.supported_locales)!r}")
    lines.append("")

    for ec in ecf.codes:
        lines.append(f"{_const_name(ec.code)} = {ec.code!r}")

    lines.append("")
    lines.append("ALL_CODES = frozenset({")
    for ec in ecf.codes:
        lines.append(f"    {ec.code!r},")
    lines.append("})")
    lines.append("")
    lines.append("CODE_METADATA = {")
    for ec in ecf.codes:
        lines.append(
            f"    {ec.code!r}: {{'severity': {ec.severity!r}, "
            f"'log_route': {ec.log_route!r}, 'facility': {ec.facility!r}}},"
        )
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI — BLOCKING aggregator (V/X)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Blocking aggregator CLI (V/X).

    Aggregates the ``error-codes.yaml`` files given on the command line and
    registry-parity-checks the merged registry, printing every finding first
    (fail-loud, most-data-available — rule 18) and then returning the verdict:
    exit 1 (X) if :func:`aggregate_error_codes` returns any finding, exit 0 (V)
    when the merged registry is clean. This is the R6 blocking behaviour
    (manomatika/ahimsa#129); the aggregator was report-only at R0.

    ``--require-all-origins`` additionally fails if any expected origin
    (matika / eyerate / ahimsa / manomatika) is absent from the inputs
    (missing-origin). The product gate passes this flag because it always feeds
    all four SHA-pinned per-origin sources.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="ahimsa-aggregate-error-codes",
        description=(
            "Aggregate, validate, and registry-parity-check every origin's "
            "error-codes.yaml. BLOCKING (V/X): prints all findings then exits 1 "
            "if any exist, 0 when the merged registry is clean "
            "(manomatika/ahimsa#129)."
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        metavar="ERROR_CODES_YAML",
        help="paths to per-origin error-codes.yaml files",
    )
    parser.add_argument(
        "--require-all-origins",
        action="store_true",
        help=(
            "fail if any expected origin (matika/eyerate/ahimsa/manomatika) is "
            "absent from the inputs (missing-origin parity check). The product "
            "gate sets this because it feeds all four pinned sources."
        ),
    )
    args = parser.parse_args(argv)

    errors = aggregate_error_codes(
        list(args.files), require_all_origins=args.require_all_origins
    )

    if errors:
        print(
            f"error-codes aggregation FAILED with {len(errors)} finding(s) "
            "[BLOCKING — manomatika/ahimsa#129]:",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        # BLOCKING: any finding fails the gate (X).
        return 1

    print("error-codes aggregation: merged registry is clean.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
