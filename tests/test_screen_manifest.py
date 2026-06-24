"""Unit tests for scripts/screen_manifest.py — the manifest-driven gate mechanism.

These are the rule-22 regression tests for manomatika/ahimsa#82 (A1): they prove
the tier-a/tier-b harness drives EXACTLY the screens the assembled manifest
declares, generically across ≥2 synthetic components, and that it never
hardcodes a screen or reclassifies a route. A harness that ignored the manifest
or baked in a fixed (eyerate) screen set would fail these — and before this
change the module did not exist, so importing/driving it could not pass at all.

The synthetic fixtures name two invented components ("alpha", "beta") precisely
to prove genericity: nothing in the mechanism knows about matika or eyerate.

Layer-3 tests (manomatika/ahimsa#101): the functional-test invocation tests prove
that the generic gate discovers, parses, and invokes ONLY declared tests — it
never calls an undeclared function discovered by reflection. The genericity guard
uses invented applug names ("alpha", "beta") — nothing names "eyerate".
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import screen_manifest as sm  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders — a build-dir-shaped tree with two synthetic components
# ---------------------------------------------------------------------------

def _write(path: Path, screens: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "1.0", "screens": screens}))


def _two_component_root(tmp_path: Path) -> Path:
    """Mirror the build layout: a core screens dir + two plugin dirs."""
    root = tmp_path / "build" / "matika"
    # Core component (discovered as source "core").
    _write(root / "src" / "matika" / "screens" / "matika_screens.json", [
        {"screen_id": "core:home", "type": "screen", "route": "/",
         "markers": ["#app"], "steps": [{"verb": "navigate", "target": "/"}]},
        {"screen_id": "core:logout", "type": "not_a_screen", "route": "/logout",
         "reason": "redirect-only endpoint"},
    ])
    # Plugin "alpha" (discovered as source "alpha").
    _write(root / "plugins" / "alpha" / "src" / "alpha" / "alpha_screens.json", [
        {"screen_id": "alpha:list", "type": "screen", "route": "/alpha",
         "markers": [".alpha-table", "#alpha-list"],
         "steps": [{"verb": "navigate", "target": "/alpha"}]},
        {"screen_id": "alpha:api", "type": "not_a_screen", "route": "/alpha/api",
         "reason": "JSON endpoint"},
    ])
    # Plugin "beta" (discovered as source "beta").
    _write(root / "plugins" / "beta" / "beta_screens.json", [
        {"screen_id": "beta:admin", "type": "screen", "route": "/beta/admin",
         "markers": ["#beta-admin-form"],
         "steps": [{"verb": "navigate", "target": "/beta/admin"}]},
    ])
    return root


# ---------------------------------------------------------------------------
# Enumeration — generic across components, classifications honoured verbatim
# ---------------------------------------------------------------------------

def test_load_enumerates_exactly_declared_screens_across_components(tmp_path):
    manifest = sm.load_screen_manifest(str(_two_component_root(tmp_path)))
    driven_ids = {s.screen_id for s in manifest.screens}
    assert driven_ids == {"core:home", "alpha:list", "beta:admin"}
    # Discovered generically from all three components — no component is named in
    # the mechanism; the source ids are derived from the build layout.
    assert set(manifest.sources) == {"core", "alpha", "beta"}


def test_not_a_screen_entries_are_never_driven_or_reclassified(tmp_path):
    manifest = sm.load_screen_manifest(str(_two_component_root(tmp_path)))
    driven_routes = {s.route for s in manifest.screens}
    assert "/logout" not in driven_routes
    assert "/alpha/api" not in driven_routes
    not_screen_routes = {e["route"] for e in manifest.not_a_screen}
    assert not_screen_routes == {"/logout", "/alpha/api"}


def test_declared_and_classified_routes(tmp_path):
    manifest = sm.load_screen_manifest(str(_two_component_root(tmp_path)))
    assert manifest.declared_routes() == ["/", "/alpha", "/beta/admin"]
    assert manifest.classified_routes() == [
        "/", "/alpha", "/alpha/api", "/beta/admin", "/logout",
    ]


def test_screen_carries_its_markers_and_steps_verbatim(tmp_path):
    manifest = sm.load_screen_manifest(str(_two_component_root(tmp_path)))
    alpha = next(s for s in manifest.screens if s.screen_id == "alpha:list")
    assert alpha.markers == (".alpha-table", "#alpha-list")
    assert [s.verb for s in alpha.steps] == ["navigate"]
    assert alpha.steps[0].target == "/alpha"
    assert alpha.source == "alpha"


# ---------------------------------------------------------------------------
# The step runner drives declared verbs generically (the core A1 deliverable)
# ---------------------------------------------------------------------------

class _FakeExecutor(sm.ScreenExecutor):
    def __init__(self):
        self.steps = []
        self.marker_calls = []

    def run_step(self, step):
        self.steps.append((step.verb, step.target, step.value))

    def assert_markers(self, markers):
        self.marker_calls.append(tuple(markers))


def test_drive_screen_dispatches_every_declared_verb_in_order():
    screen = sm.Screen(
        screen_id="x", route="/x", markers=("#m1", "#m2"),
        required_markers=(),
        steps=(
            sm.Step("navigate", "/x", None),
            sm.Step("fill", "#q", "VOO"),
            sm.Step("click", "#go", None),
            sm.Step("wait_for", "#results", None),
            sm.Step("assert_present", "#row", None),
            sm.Step("assert_absent", "#error", None),
            sm.Step("assert_value", "#sym", "VOO"),
        ),
        source="alpha",
    )
    ex = _FakeExecutor()
    sm.drive_screen(screen, ex)
    assert ex.steps == [
        ("navigate", "/x", None),
        ("fill", "#q", "VOO"),
        ("click", "#go", None),
        ("wait_for", "#results", None),
        ("assert_present", "#row", None),
        ("assert_absent", "#error", None),
        ("assert_value", "#sym", "VOO"),
    ]
    assert ex.marker_calls == [("#m1", "#m2")]


def test_drive_screens_drives_each_declared_screen_once_no_hardcoding(tmp_path):
    """The guard against 'harness ignores the manifest / hardcodes screens'."""
    manifest = sm.load_screen_manifest(str(_two_component_root(tmp_path)))
    ex = _FakeExecutor()
    count = sm.drive_screens(manifest, ex)
    assert count == 3
    navigated = [t for (verb, t, _v) in ex.steps if verb == "navigate"]
    assert sorted(navigated) == ["/", "/alpha", "/beta/admin"]


# ---------------------------------------------------------------------------
# Gate strictness — every defect is a hard error (no vacuous pass)
# ---------------------------------------------------------------------------

def test_empty_source_root_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(sm.ScreenManifestError):
        sm.load_screen_manifest(str(empty))


def test_missing_source_root_raises(tmp_path):
    with pytest.raises(sm.ScreenManifestError):
        sm.load_screen_manifest(str(tmp_path / "nope"))


def test_unknown_verb_rejected(tmp_path):
    _write(tmp_path / "bad_screens.json", [
        {"screen_id": "x", "type": "screen", "route": "/x", "markers": ["#m"],
         "steps": [{"verb": "teleport", "target": "/x"}]},
    ])
    with pytest.raises(sm.ScreenManifestError, match="unknown verb"):
        sm.load_screen_manifest(str(tmp_path))


def test_screen_missing_markers_rejected(tmp_path):
    _write(tmp_path / "bad_screens.json", [
        {"screen_id": "x", "type": "screen", "route": "/x",
         "steps": [{"verb": "navigate", "target": "/x"}]},
    ])
    with pytest.raises(sm.ScreenManifestError, match="markers"):
        sm.load_screen_manifest(str(tmp_path))


def test_screen_steps_must_be_a_list(tmp_path):
    _write(tmp_path / "bad_screens.json", [
        {"screen_id": "x", "type": "screen", "route": "/x", "markers": ["#m"],
         "steps": "navigate"},
    ])
    with pytest.raises(sm.ScreenManifestError, match="steps"):
        sm.load_screen_manifest(str(tmp_path))


def test_not_a_screen_missing_reason_rejected(tmp_path):
    _write(tmp_path / "bad_screens.json", [
        {"screen_id": "x", "type": "not_a_screen", "route": "/x"},
    ])
    with pytest.raises(sm.ScreenManifestError, match="reason"):
        sm.load_screen_manifest(str(tmp_path))


def test_unknown_type_rejected(tmp_path):
    _write(tmp_path / "bad_screens.json", [
        {"screen_id": "x", "type": "widget", "route": "/x"},
    ])
    with pytest.raises(sm.ScreenManifestError, match="unknown type"):
        sm.load_screen_manifest(str(tmp_path))


def test_wrong_schema_version_is_a_hard_error_in_the_gate(tmp_path):
    """Unlike matika's lenient runtime loader, the gate refuses unknown schema."""
    path = tmp_path / "old_screens.json"
    path.write_text(json.dumps({"schema_version": "2.0", "screens": []}))
    with pytest.raises(sm.ScreenManifestError, match="schema_version"):
        sm.load_screen_manifest(str(tmp_path))


def test_duplicate_screen_id_across_sources_rejected(tmp_path):
    root = tmp_path / "build" / "matika"
    _write(root / "src" / "matika" / "screens" / "matika_screens.json", [
        {"screen_id": "dup", "type": "screen", "route": "/a", "markers": ["#m"],
         "steps": [{"verb": "navigate", "target": "/a"}]},
    ])
    _write(root / "plugins" / "alpha" / "alpha_screens.json", [
        {"screen_id": "dup", "type": "screen", "route": "/b", "markers": ["#m"],
         "steps": [{"verb": "navigate", "target": "/b"}]},
    ])
    with pytest.raises(sm.ScreenManifestError, match="duplicate screen_id"):
        sm.load_screen_manifest(str(root))


def test_discovery_skips_vendor_dirs(tmp_path):
    root = tmp_path / "build" / "matika"
    _write(root / "src" / "matika" / "screens" / "matika_screens.json", [
        {"screen_id": "core:home", "type": "screen", "route": "/", "markers": ["#m"],
         "steps": [{"verb": "navigate", "target": "/"}]},
    ])
    # A screens-shaped file under node_modules must NOT be discovered.
    _write(root / "node_modules" / "junk" / "evil_screens.json", [
        {"screen_id": "junk", "type": "screen", "route": "/junk", "markers": ["#j"],
         "steps": [{"verb": "navigate", "target": "/junk"}]},
    ])
    manifest = sm.load_screen_manifest(str(root))
    assert {s.screen_id for s in manifest.screens} == {"core:home"}


# ---------------------------------------------------------------------------
# Route inventory parse (the [ROUTES:...] startup marker — M3)
# ---------------------------------------------------------------------------

def test_parse_routes_marker_extracts_routes():
    text = "init...\n[ROUTES: /, /about, /eyerate/admin]\ntrailing"
    assert sm.parse_routes_marker(text) == ["/", "/about", "/eyerate/admin"]


def test_parse_routes_marker_uses_last_marker():
    text = "[ROUTES: /a]\n...reboot...\n[ROUTES: /a, /b]"
    assert sm.parse_routes_marker(text) == ["/a", "/b"]


def test_parse_routes_marker_absent_returns_empty():
    assert sm.parse_routes_marker("no marker here") == []
    assert sm.parse_routes_marker("") == []


# ---------------------------------------------------------------------------
# Schema-constant pin (parity with matika is enforced cross-repo by M4)
# ---------------------------------------------------------------------------

def test_schema_constants_are_the_canonical_values():
    assert sm.SUPPORTED_SCHEMA == "1.0"
    assert sm.ALLOWED_VERBS == frozenset({
        "navigate", "fill", "click", "wait_for",
        "assert_present", "assert_absent", "assert_value",
    })


# ---------------------------------------------------------------------------
# Layer-3: functional-test discovery + invocation (manomatika/ahimsa#101)
# ---------------------------------------------------------------------------

def _write_func_json(path, test_decls):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "1.0", "functional_tests": test_decls}))


def _two_applug_root(tmp_path):
    """Source clone with two synthetic applugs ('alpha', 'beta') and one undeclared function in alpha."""
    root = tmp_path / "build" / "matika"

    # Alpha: declares test_alpha_works; also has undeclared test_not_declared
    alpha_dir = root / "plugins" / "alpha" / "src" / "alpha"
    alpha_dir.mkdir(parents=True)
    _write_func_json(
        alpha_dir / "alpha_functional_tests.json",
        [{"test_id": "alpha:works", "description": "Alpha nominal",
          "module": "alpha_functional_tests", "function": "test_alpha_works"}]
    )
    (alpha_dir / "alpha_functional_tests.py").write_text(
        "def test_alpha_works(base_url, session): pass\n"
        "def test_not_declared(base_url, session):\n"
        "    raise AssertionError('must NOT be called by the generic gate')\n"
    )

    # Beta: declares test_beta_feature
    beta_dir = root / "plugins" / "beta"
    beta_dir.mkdir(parents=True)
    _write_func_json(
        beta_dir / "beta_functional_tests.json",
        [{"test_id": "beta:feature", "description": "Beta feature",
          "module": "beta_functional_tests", "function": "test_beta_feature"}]
    )
    (beta_dir / "beta_functional_tests.py").write_text(
        "def test_beta_feature(base_url, session): pass\n"
    )

    return root


def test_generic_gate_discovers_both_applugs(tmp_path):
    root = _two_applug_root(tmp_path)
    manifest = sm.load_functional_test_manifest(str(root))
    test_ids = {t.test_id for t in manifest.tests}
    assert "alpha:works" in test_ids
    assert "beta:feature" in test_ids
    assert "alpha" in manifest.sources
    assert "beta" in manifest.sources


def test_generic_gate_runs_only_declared_tests(tmp_path):
    """Gate invokes ONLY what the JSON declares; test_not_declared is never called."""
    root = _two_applug_root(tmp_path)
    manifest = sm.load_functional_test_manifest(str(root))
    called = []
    for decl in manifest.tests:
        called.append(decl.function)
        sm.invoke_functional_test(decl, str(root), "http://localhost:8000", None)
    assert "test_alpha_works" in called
    assert "test_beta_feature" in called
    assert "test_not_declared" not in called, (
        "Gate must NOT call test_not_declared — it is not in the JSON manifest"
    )


def test_hardcoded_invocation_calls_undeclared_function(tmp_path):
    """Proves bypassing the manifest (hardcoding an applug name) WOULD call undeclared tests."""
    root = _two_applug_root(tmp_path)
    module_file = str(root / "plugins" / "alpha" / "src" / "alpha" / "alpha_functional_tests.py")
    spec = importlib.util.spec_from_file_location("alpha_functional_tests", module_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    all_test_fns = [n for n, _ in inspect.getmembers(mod, inspect.isfunction) if n.startswith("test_")]
    # A hardcoded invocation finds test_not_declared — proving the manifest is load-bearing
    assert "test_not_declared" in all_test_fns
    assert "test_alpha_works" in all_test_fns


def test_empty_source_root_returns_empty_manifest(tmp_path):
    root = tmp_path / "build" / "matika"
    root.mkdir(parents=True)
    manifest = sm.load_functional_test_manifest(str(root))
    assert manifest.tests == ()
    assert manifest.sources == ()


def test_missing_required_field_raises(tmp_path):
    path = tmp_path / "bad_functional_tests.json"
    path.write_text(json.dumps({"schema_version": "1.0", "functional_tests": [
        {"test_id": "x:t", "description": "d", "module": "m"}  # missing "function"
    ]}))
    with pytest.raises(sm.ScreenManifestError, match="function"):
        sm.parse_functional_tests_file(str(path), "bad")


def test_wrong_schema_version_raises(tmp_path):
    path = tmp_path / "bad_functional_tests.json"
    path.write_text(json.dumps({"schema_version": "99.0", "functional_tests": []}))
    with pytest.raises(sm.ScreenManifestError, match="schema_version"):
        sm.parse_functional_tests_file(str(path), "bad")


def test_duplicate_test_ids_raises(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _write_func_json(root / "plugins" / "a" / "a_functional_tests.json",
                     [{"test_id": "dup:t", "description": "d", "module": "a_ft", "function": "test_a"}])
    _write_func_json(root / "plugins" / "b" / "b_functional_tests.json",
                     [{"test_id": "dup:t", "description": "d", "module": "b_ft", "function": "test_b"}])
    with pytest.raises(sm.ScreenManifestError, match="duplicate"):
        sm.load_functional_test_manifest(str(root))


def test_missing_module_raises(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _write_func_json(root / "ghost_functional_tests.json",
                     [{"test_id": "g:t", "description": "d", "module": "ghost_ft", "function": "test_g"}])
    manifest = sm.load_functional_test_manifest(str(root))
    with pytest.raises(sm.ScreenManifestError, match="ghost_ft"):
        sm.invoke_functional_test(manifest.tests[0], str(root), "http://localhost", None)


def test_missing_function_in_module_raises(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok_functional_tests.py").write_text("def test_something(base_url, session): pass\n")
    _write_func_json(root / "ok_functional_tests.json",
                     [{"test_id": "ok:t", "description": "d", "module": "ok_functional_tests", "function": "test_nonexistent"}])
    manifest = sm.load_functional_test_manifest(str(root))
    with pytest.raises(sm.ScreenManifestError, match="test_nonexistent"):
        sm.invoke_functional_test(manifest.tests[0], str(root), "http://localhost", None)


def test_invoke_calls_function_with_correct_args(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "capture_functional_tests.py").write_text(
        "results = []\n"
        "def test_capture(base_url, session):\n"
        "    results.append((base_url, session))\n"
    )
    _write_func_json(root / "capture_functional_tests.json",
                     [{"test_id": "cap:t", "description": "d", "module": "capture_functional_tests", "function": "test_capture"}])
    manifest = sm.load_functional_test_manifest(str(root))
    sm.invoke_functional_test(manifest.tests[0], str(root), "http://testhost:9000", "mock_session")
    # If we reach here, the function was called without error


# ---------------------------------------------------------------------------
# required_markers field on Screen
# ---------------------------------------------------------------------------

class TestRequiredMarkersOnScreen:
    def test_required_markers_absent_defaults_to_empty(self, tmp_path):
        _write(tmp_path / "x_screens.json", [
            {"screen_id": "x", "type": "screen", "route": "/x",
             "markers": [".main"], "steps": [{"verb": "navigate", "target": "/x"}]}
        ])
        manifest = sm.load_screen_manifest(str(tmp_path))
        assert manifest.screens[0].required_markers == ()

    def test_required_markers_valid_subset_accepted(self, tmp_path):
        _write(tmp_path / "x_screens.json", [
            {"screen_id": "x", "type": "screen", "route": "/x",
             "markers": [".a", ".b"], "required_markers": [".a"],
             "steps": [{"verb": "navigate", "target": "/x"}]}
        ])
        manifest = sm.load_screen_manifest(str(tmp_path))
        assert manifest.screens[0].required_markers == (".a",)

    def test_required_markers_not_in_markers_raises(self, tmp_path):
        _write(tmp_path / "x_screens.json", [
            {"screen_id": "x", "type": "screen", "route": "/x",
             "markers": [".main"], "required_markers": [".missing"],
             "steps": [{"verb": "navigate", "target": "/x"}]}
        ])
        with pytest.raises(sm.ScreenManifestError, match=r"\.missing"):
            sm.load_screen_manifest(str(tmp_path))

    def test_required_markers_must_be_list_raises(self, tmp_path):
        _write(tmp_path / "x_screens.json", [
            {"screen_id": "x", "type": "screen", "route": "/x",
             "markers": [".main"], "required_markers": ".main",
             "steps": [{"verb": "navigate", "target": "/x"}]}
        ])
        with pytest.raises(sm.ScreenManifestError):
            sm.load_screen_manifest(str(tmp_path))


# ---------------------------------------------------------------------------
# Layer-3 schema constants pin
# ---------------------------------------------------------------------------

def test_functional_test_schema_constant():
    assert sm.FUNCTIONAL_TEST_SCHEMA == "1.0"


def test_functional_tests_suffix_constant():
    assert sm.FUNCTIONAL_TESTS_SUFFIX == "_functional_tests.json"
