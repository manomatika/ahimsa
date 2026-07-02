"""
Tests for the R0 error-code mechanism: ManoMatikaError base class, the schema
lints, the report-only aggregator, and the codegen.

Every lint rule has a regression test that FAILS without the rule (a malformed
input must produce the expected Error) and a companion asserting a well-formed
input lints clean. The reserved MATIKA-LNCH-001/002/003 codes and the empty
MANOMATIKA namespace are asserted valid; the aggregator's report-only contract
is proven (a registry that WOULD fail blocking validation still exits 0).
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from ahimsa.error_codes import (
    COMPONENT_FOR_ORIGIN,
    LOG_ROUTES,
    SEVERITIES,
    aggregate_error_codes,
    lint_error_codes,
    load_error_codes,
    main,
    parse_error_codes_text,
    render_constants_module,
)
from ahimsa.manomatika_error import CODE_RE, ManoMatikaError, parse_code

FIXTURES = Path(__file__).parent / "fixtures" / "error_codes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lint(text: str) -> list[str]:
    """Parse + lint *text*, returning the finding messages (str) for easy asserts."""
    raw = parse_error_codes_text(text)
    return [str(e) for e in lint_error_codes(raw)]


def _valid_matika(codes_block: str) -> str:
    """Build a matika error-codes.yaml around *codes_block* (a dedent-able list)."""
    body = textwrap.indent(textwrap.dedent(codes_block).strip("\n"), "  ")
    return (
        "origin: matika\n"
        "component: MATIKA\n"
        "supported_locales: [en, es]\n"
        "codes:\n"
        f"{body}\n"
    )


# ---------------------------------------------------------------------------
# ManoMatikaError base class
# ---------------------------------------------------------------------------


def test_base_class_accepts_wellformed_code():
    err = ManoMatikaError("MATIKA-LNCH-001", "foreign holder", pid=42)
    assert err.code == "MATIKA-LNCH-001"
    assert err.context == {"pid": 42}
    assert str(err) == "[MATIKA-LNCH-001] foreign holder"


def test_base_class_message_optional():
    assert str(ManoMatikaError("AHIMSA-CFG-001")) == "[AHIMSA-CFG-001]"


@pytest.mark.parametrize("bad", ["not-a-code", "matika-lnch-001", "MATIKA-LNCH-1", "MATIKA-LNCH", "", None, 123])
def test_base_class_rejects_malformed_code(bad):
    """Fail-loud: constructing with a non-well-formed code raises ValueError."""
    with pytest.raises(ValueError) as exc:
        ManoMatikaError(bad)
    assert repr(bad) in str(exc.value)  # carries the offending value


def test_parse_code_roundtrip():
    assert parse_code("MATIKA-LNCH-003") == ("MATIKA", "LNCH", 3)


def test_parse_code_rejects_malformed():
    with pytest.raises(ValueError):
        parse_code("MATIKA-LNCH-01")


def test_reserved_lnch_codes_are_wellformed():
    for code in ("MATIKA-LNCH-001", "MATIKA-LNCH-002", "MATIKA-LNCH-003"):
        assert CODE_RE.match(code)


# ---------------------------------------------------------------------------
# parse_error_codes_text — fail-loud only on structural garbage
# ---------------------------------------------------------------------------


def test_parse_rejects_non_mapping_top_level():
    with pytest.raises(ValueError, match="top level must be a mapping"):
        parse_error_codes_text("- just\n- a\n- list\n")


def test_parse_rejects_non_list_codes():
    with pytest.raises(ValueError, match="'codes' must be a list"):
        parse_error_codes_text("origin: matika\ncodes: not-a-list\n")


def test_parse_tolerates_missing_fields():
    """Missing values are for the LINT to catch, not the parser (so aggregation
    can enumerate all findings instead of crashing)."""
    raw = parse_error_codes_text("origin: matika\n")
    assert raw.component is None
    assert raw.raw_codes == []


# ---------------------------------------------------------------------------
# Lints — happy path
# ---------------------------------------------------------------------------


def test_valid_file_lints_clean():
    text = _valid_matika("""\
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
          message: Foreign lock holder detected.
        - code: MATIKA-LNCH-002
          severity: error
          log_route: startup
          message: No lock holder.
        - code: MATIKA-LNCH-003
          severity: fatal
          log_route: startup
          message: Reclaim failed.
    """)
    assert _lint(text) == []


def test_empty_manomatika_namespace_is_valid():
    """The reserved, forward-looking MANOMATIKA namespace is a well-formed EMPTY file."""
    raw = parse_error_codes_text((FIXTURES / "manomatika.yaml").read_text())
    assert lint_error_codes(raw) == []


def test_multiple_facilities_with_gaps_lint_clean():
    """Several facilities coexist and each may carry gaps (CFG skips 002)."""
    text = _valid_matika("""\
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
          message: a
        - code: MATIKA-CFG-001
          severity: warning
          log_route: aggregate
          message: b
        - code: MATIKA-CFG-003
          severity: error
          log_route: aggregate
          message: c
    """)
    assert _lint(text) == []


# ---------------------------------------------------------------------------
# Lints — each rule rejects its target malformation
# ---------------------------------------------------------------------------


def test_lint_rejects_bad_pattern():
    text = _valid_matika("""\
        - code: MATIKA-LNCH-1
          severity: error
          log_route: startup
          message: a
    """)
    findings = _lint(text)
    assert any("not well-formed" in f for f in findings)


def test_lint_rejects_duplicate_code():
    text = _valid_matika("""\
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
          message: a
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
          message: b
    """)
    findings = _lint(text)
    assert any("duplicate code" in f for f in findings)


def test_lint_allows_nnn_gap():
    """Gaps are allowed: NNN is opaque and MONOTONIC (reserved/retired/skipped
    numbers are expected), so 001, 002, 004 (missing 003) lints CLEAN. This is
    the relaxed contract — the old rule flagged this as 'not contiguous'."""
    text = _valid_matika("""\
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
          message: a
        - code: MATIKA-LNCH-002
          severity: error
          log_route: startup
          message: b
        - code: MATIKA-LNCH-004
          severity: error
          log_route: startup
          message: c
    """)
    assert _lint(text) == []


def test_lint_allows_nnn_not_starting_at_001():
    """A facility need not start at 001 — reserved low numbers are allowed."""
    text = _valid_matika("""\
        - code: MATIKA-LNCH-002
          severity: error
          log_route: startup
          message: a
    """)
    assert _lint(text) == []


def test_lint_rejects_wrong_component_prefix():
    """A code whose prefix disagrees with the file's declared component."""
    text = _valid_matika("""\
        - code: EYERATE-LNCH-001
          severity: error
          log_route: startup
          message: a
    """)
    findings = _lint(text)
    assert any("does not match the file's component" in f for f in findings)


def test_lint_rejects_component_origin_mismatch():
    text = textwrap.dedent("""\
        origin: matika
        component: EYERATE
        supported_locales: [en]
        codes: []
    """)
    findings = _lint(text)
    assert any("does not match origin" in f for f in findings)


def test_lint_rejects_unknown_origin():
    text = textwrap.dedent("""\
        origin: bogus
        component: BOGUS
        supported_locales: [en]
        codes: []
    """)
    findings = _lint(text)
    assert any("unknown origin" in f for f in findings)


def test_lint_rejects_bad_severity():
    text = _valid_matika("""\
        - code: MATIKA-LNCH-001
          severity: catastrophic
          log_route: startup
          message: a
    """)
    findings = _lint(text)
    assert any("severity 'catastrophic' not in closed set" in f for f in findings)


def test_lint_rejects_bad_log_route():
    text = _valid_matika("""\
        - code: MATIKA-LNCH-001
          severity: error
          log_route: nowhere
          message: a
    """)
    findings = _lint(text)
    assert any("log_route 'nowhere' not in closed set" in f for f in findings)


def test_lint_rejects_missing_required_field():
    text = _valid_matika("""\
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
    """)
    findings = _lint(text)
    assert any("missing required field(s)" in f and "message" in f for f in findings)


def test_lint_rejects_empty_supported_locales():
    text = textwrap.dedent("""\
        origin: matika
        component: MATIKA
        supported_locales: []
        codes: []
    """)
    findings = _lint(text)
    assert any("non-empty list" in f for f in findings)


def test_lint_rejects_supported_locales_without_en():
    text = textwrap.dedent("""\
        origin: matika
        component: MATIKA
        supported_locales: [es]
        codes: []
    """)
    findings = _lint(text)
    assert any("must include 'en'" in f for f in findings)


def test_closed_sets_are_as_specified():
    assert SEVERITIES == ("fatal", "error", "warning")
    assert LOG_ROUTES == ("startup", "aggregate", "n/a")
    assert COMPONENT_FOR_ORIGIN == {
        "matika": "MATIKA",
        "eyerate": "EYERATE",
        "ahimsa": "AHIMSA",
        "manomatika": "MANOMATIKA",
    }


# ---------------------------------------------------------------------------
# load_error_codes — fail-loud on invalid input
# ---------------------------------------------------------------------------


def test_load_error_codes_valid(tmp_path):
    ecf = load_error_codes(FIXTURES / "example.yaml")
    assert ecf.origin == "ahimsa"
    assert [c.code for c in ecf.codes] == ["AHIMSA-CFG-001", "AHIMSA-CFG-002"]
    assert ecf.codes[0].facility == "CFG"
    assert ecf.codes[0].number == 1


def test_load_error_codes_raises_on_invalid(tmp_path):
    # A DUPLICATE code is still a defect under the relaxed (uniqueness-only) rule.
    bad = tmp_path / "bad.yaml"
    bad.write_text(_valid_matika("""\
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
          message: a
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
          message: b
    """))
    with pytest.raises(ValueError, match="is invalid"):
        load_error_codes(bad)


def test_load_error_codes_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_error_codes(tmp_path / "nope.yaml")


# ---------------------------------------------------------------------------
# Aggregator — cross-file rules + REPORT-ONLY contract
# ---------------------------------------------------------------------------


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_aggregate_clean_registry(tmp_path):
    a = _write(tmp_path, "matika.yaml", _valid_matika("""\
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
          message: a
    """))
    b = _write(tmp_path, "manomatika.yaml", (FIXTURES / "manomatika.yaml").read_text())
    assert aggregate_error_codes([a, b]) == []


def test_aggregate_detects_cross_file_duplicate_code(tmp_path):
    """Two origins declaring the same code string is a merged-registry violation."""
    # Deliberately break prefix-disjointness to force a cross-file dup.
    a = _write(tmp_path, "a.yaml", _valid_matika("""\
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
          message: a
    """))
    b = _write(tmp_path, "b.yaml", textwrap.dedent("""\
        origin: eyerate
        component: EYERATE
        supported_locales: [en]
        codes:
          - code: MATIKA-LNCH-001
            severity: error
            log_route: startup
            message: b
    """))
    findings = [str(e) for e in aggregate_error_codes([a, b])]
    assert any("declared by both" in f and "registry.code" in f for f in findings)


def test_aggregate_missing_file_is_reported(tmp_path):
    findings = [str(e) for e in aggregate_error_codes([tmp_path / "ghost.yaml"])]
    assert any("file not found" in f for f in findings)


def test_aggregate_is_report_only_exit_zero(tmp_path, capsys):
    """A registry that WOULD fail blocking validation must STILL exit 0 at R0."""
    bad = _write(tmp_path, "bad.yaml", _valid_matika("""\
        - code: MATIKA-LNCH-002
          severity: catastrophic
          log_route: nowhere
          message: a
    """))
    # The pure function reports findings...
    assert aggregate_error_codes([bad]) != []
    # ...but the CLI is REPORT-ONLY: exit code 0 regardless.
    rc = main([str(bad)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "REPORT-ONLY" in captured.err


def test_aggregate_clean_cli_exit_zero(tmp_path, capsys):
    good = _write(tmp_path, "manomatika.yaml", (FIXTURES / "manomatika.yaml").read_text())
    assert main([str(good)]) == 0
    assert "clean" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Codegen — typed constants
# ---------------------------------------------------------------------------


def test_render_constants_module_content():
    ecf = load_error_codes(FIXTURES / "example.yaml")
    src = render_constants_module(ecf)
    assert "AHIMSA_CFG_001 = 'AHIMSA-CFG-001'" in src
    assert "AHIMSA_CFG_002 = 'AHIMSA-CFG-002'" in src
    assert "ALL_CODES = frozenset({" in src
    assert "CODE_METADATA = {" in src


def test_generated_module_is_valid_python_and_registers_codes(tmp_path):
    """The generated source must import and expose exactly the registered codes."""
    ecf = load_error_codes(FIXTURES / "example.yaml")
    src = render_constants_module(ecf)
    ns: dict = {}
    exec(compile(src, "<generated>", "exec"), ns)
    assert ns["AHIMSA_CFG_001"] == "AHIMSA-CFG-001"
    assert ns["ALL_CODES"] == frozenset({"AHIMSA-CFG-001", "AHIMSA-CFG-002"})
    assert ns["CODE_METADATA"]["AHIMSA-CFG-001"]["severity"] == "error"
    assert ns["COMPONENT"] == "AHIMSA"


def test_gen_script_refuses_invalid_source(tmp_path):
    """scripts/gen_error_codes.py fails loud (exit 1) on a malformed registry."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(_valid_matika("""\
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
          message: a
        - code: MATIKA-LNCH-001
          severity: error
          log_route: startup
          message: b
    """))
    script = Path(__file__).parent.parent / "scripts" / "gen_error_codes.py"
    result = subprocess.run(
        [sys.executable, str(script), str(bad)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "invalid" in result.stderr


def test_gen_script_generates_valid_module(tmp_path):
    out = tmp_path / "generated_codes.py"
    script = Path(__file__).parent.parent / "scripts" / "gen_error_codes.py"
    result = subprocess.run(
        [sys.executable, str(script), str(FIXTURES / "example.yaml"), "--out", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    ns: dict = {}
    exec(compile(out.read_text(), str(out), "exec"), ns)
    assert ns["AHIMSA_CFG_001"] == "AHIMSA-CFG-001"
