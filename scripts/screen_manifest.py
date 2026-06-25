#!/usr/bin/env python3
"""screen_manifest.py — load the assembled screen manifest (gate MECHANISM only).

ahimsa owns ONLY the verify-gate MECHANISM; it RE-DECLARES NO screen content.
This module discovers and reads the ``*_screens.json`` data that the components
(matika core + each AppLug) assemble, and returns the declared ``screen`` entries
so the tier-a / tier-b harness can drive them GENERICALLY — it never hardcodes a
component name, route, or marker, and it NEVER reclassifies a route: each
component's own ``type`` (``screen`` / ``not_a_screen``) is authoritative.

Schema authority
----------------
The screen schema is canonical in manomatika/matika (ScreenLoaderService,
manomatika/matika#84). The schema CONSTANTS below (``SUPPORTED_SCHEMA``,
``ALLOWED_VERBS``) are a minimal, isolated MIRROR kept only so the gate can
validate the data it reads. They are parity-tested against the matika source by
manomatika/matika#84's follow-on schema-parity test (M4). Do NOT add
classification logic or screen content here — only the constants and the
mechanism that consumes the assembled data.

The Layer-3 functional-test constants (``FUNCTIONAL_TEST_SCHEMA``,
``FUNCTIONAL_TESTS_SUFFIX``) are the gate's MIRROR of the contract defined in
manomatika/matika#98. The discovery/parse/invoke functions below implement the
generic invocation contract from manomatika/ahimsa#101: discover
``*_functional_tests.json`` files, parse declarations, import the named module,
and call the declared function — never hardcoding an applug name or calling an
undeclared function.

Hybrid read
-----------
Coverage enumeration is a HYBRID read with two arms:

  * SOURCE-CLONE arm (this module / A1, manomatika/ahimsa#82): enumerate the
    ``*_screens.json`` files from the PINNED SOURCE CLONES embedded in the build
    dir (``build/matika`` core + ``build/matika/plugins/*``). Always fresh.
    ``load_screen_manifest(source_root)`` IS this arm.

  * INSTALLED-DISK arm (A2, manomatika/ahimsa#83): read the screens shipped
    INSIDE the installed artifact (for the upgrade-detection assertion). A2
    plugs into ``load_screen_manifest()`` by pointing it at a different source
    root (the installed bundle's screen tree). A1 leaves that seam open and does
    source-clone enumeration only.

Gate strictness vs. runtime leniency
------------------------------------
matika's runtime ScreenLoaderService is deliberately LENIENT (it skips a file
whose ``schema_version`` it does not understand, for forward compatibility). The
VERIFICATION GATE is deliberately STRICT: silently dropping a component's
screens here would make the gate pass vacuously (the exact failure mode standing
rule 22 exists to prevent), so any unreadable / wrong-schema / malformed screens
file is a hard ``ScreenManifestError`` that fails the build.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Schema constants — MIRROR of manomatika/matika's canonical schema (M1, #84).
# Parity-tested cross-repo by M4. Keep minimal and isolated; add NOTHING that
# encodes screen content or per-route classification here.
# ---------------------------------------------------------------------------
SUPPORTED_SCHEMA = "1.0"
ALLOWED_VERBS = frozenset({
    "navigate",
    "fill",
    "click",
    "wait_for",
    "assert_present",
    "assert_absent",
    "assert_value",
})

# Layer-3 functional-test constants — MIRROR of the contract in matika#98.
# The gate uses these to discover and validate applug-declared functional tests.
FUNCTIONAL_TEST_SCHEMA = "1.0"
FUNCTIONAL_TESTS_SUFFIX = "_functional_tests.json"

_SCREENS_SUFFIX = "_screens.json"
# Directories that never hold component screen data; skipped during discovery so
# a recursive walk of a source clone does not pick up build/vendor noise.
_SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", "dist", "build", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "site-packages",
})

_ROUTES_MARKER_RE = re.compile(r"\[ROUTES:\s*(.*?)\]")


class ScreenManifestError(RuntimeError):
    """Raised when the screen manifest cannot be loaded or is invalid.

    main() turns this into a non-zero exit so CI fails (acceptance criterion:
    "CI exits non-zero if ... the manifest cannot be loaded").
    """


# ---------------------------------------------------------------------------
# Declarative data, consumed verbatim (the harness RE-DECLARES nothing)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    """One declared interaction verb from a screen's ``steps`` list."""
    verb: str
    target: Optional[str] = None
    value: Optional[str] = None

    @classmethod
    def from_dict(cls, raw: dict) -> "Step":
        return cls(
            verb=raw.get("verb"),
            target=raw.get("target"),
            value=raw.get("value"),
        )


@dataclass(frozen=True)
class Screen:
    """A declared ``screen`` entry the harness must drive."""
    screen_id: str
    route: str
    markers: Tuple[str, ...]
    required_markers: Tuple[str, ...]  # subset of markers that MUST be present
    steps: Tuple[Step, ...]
    source: str  # component source id (e.g. "core", "eyerate") — discovery-derived


@dataclass(frozen=True)
class ScreenManifest:
    """The assembled, validated manifest the harness drives.

    ``screens`` are the ``type == "screen"`` entries (driven). ``not_a_screen``
    are the components' OWN declarations that a route is not user-facing — kept
    verbatim and NEVER reclassified; exposed so the A3 route-vs-manifest gate
    (manomatika/ahimsa#84) can reason about the full classified route set.
    """
    screens: Tuple[Screen, ...]
    not_a_screen: Tuple[dict, ...]
    sources: Tuple[str, ...]

    def declared_routes(self) -> List[str]:
        """Sorted, de-duplicated routes of all driven ``screen`` entries."""
        return sorted({s.route for s in self.screens})

    def classified_routes(self) -> List[str]:
        """Sorted union of every route the components classified (screen + not)."""
        routes = {s.route for s in self.screens}
        routes.update(e.get("route") for e in self.not_a_screen if e.get("route"))
        return sorted(r for r in routes if r)


@dataclass(frozen=True)
class FunctionalTestDecl:
    """A single functional test declaration from an applug's ``*_functional_tests.json``.

    The gate invokes ONLY what each applug explicitly declares here — it never
    calls undeclared functions discovered by reflection (rule-22 genericity guard).
    """
    test_id: str
    description: str
    module: str
    function: str
    tags: Tuple[str, ...]
    source: str  # applug source id (derived from discovery path)


@dataclass(frozen=True)
class FunctionalTestManifest:
    """The assembled functional-test manifest across all applugs.

    ``tests`` is the flat, de-duplicated list of declared tests.
    ``sources`` is the sorted tuple of applug source ids that declared tests.
    """
    tests: Tuple[FunctionalTestDecl, ...]
    sources: Tuple[str, ...]


# ---------------------------------------------------------------------------
# Discovery + parse + load — the SOURCE-CLONE arm of the hybrid read (A1)
# ---------------------------------------------------------------------------

def discover_screen_files(source_root: str) -> List[str]:
    """Return sorted absolute paths of every ``*_screens.json`` under source_root.

    Generic over components: any directory that ships a ``*_screens.json`` is
    discovered, so the harness picks up matika core, every cloned AppLug, and any
    future component without naming one of them.
    """
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(source_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(_SCREENS_SUFFIX):
                found.append(os.path.join(dirpath, fn))
    return sorted(found)


def _source_id_for(path: str, source_root: str) -> str:
    """Derive a component source id from a screens-file path (for grouping).

    Mirrors the build layout: ``.../plugins/<name>/...`` -> ``<name>``; a file
    under a ``screens`` directory -> ``core``; otherwise fall back to the file's
    own ``<id>_screens.json`` stem. This is purely for reporting/grouping — it
    encodes no per-route classification.
    """
    rel = os.path.relpath(path, source_root)
    parts = rel.split(os.sep)
    if "plugins" in parts:
        i = parts.index("plugins")
        if i + 1 < len(parts):
            return parts[i + 1]
    if "screens" in parts:
        return "core"
    stem = os.path.basename(path)[: -len(_SCREENS_SUFFIX)]
    return stem or "core"


def parse_screens_file(path: str, source_id: str) -> Tuple[List[Screen], List[dict]]:
    """Read + validate one ``*_screens.json``; return (screens, not_a_screen).

    Raises ScreenManifestError on ANY defect (bad JSON, wrong schema_version,
    unknown type, unknown verb, missing required fields) — the gate is strict.
    The component's ``type`` is authoritative and is never overridden here.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ScreenManifestError(f"could not read screens file {path}: {exc}") from exc

    schema = data.get("schema_version")
    if schema != SUPPORTED_SCHEMA:
        raise ScreenManifestError(
            f"{path}: unsupported schema_version {schema!r} "
            f"(gate requires {SUPPORTED_SCHEMA!r})"
        )

    screens: List[Screen] = []
    not_a_screen: List[dict] = []

    for entry in data.get("screens", []):
        sid = entry.get("screen_id")
        etype = entry.get("type")

        if etype == "not_a_screen":
            if "reason" not in entry:
                raise ScreenManifestError(
                    f"{path}: entry {sid!r} is 'not_a_screen' but is missing the "
                    f"required 'reason' field"
                )
            # Stamp provenance so duplicate-id errors can name the source. This is
            # reporting metadata only — the component's own classification stands.
            entry = {**entry, "_source": source_id}
            not_a_screen.append(entry)

        elif etype == "screen":
            if "markers" not in entry:
                raise ScreenManifestError(
                    f"{path}: screen {sid!r} is missing the required 'markers' field"
                )
            steps_raw = entry.get("steps")
            if not isinstance(steps_raw, list):
                raise ScreenManifestError(
                    f"{path}: screen {sid!r} 'steps' must be a list"
                )
            steps: List[Step] = []
            for step_raw in steps_raw:
                verb = step_raw.get("verb")
                if verb not in ALLOWED_VERBS:
                    raise ScreenManifestError(
                        f"{path}: screen {sid!r} has unknown verb {verb!r}; "
                        f"allowed: {sorted(ALLOWED_VERBS)}"
                    )
                steps.append(Step.from_dict(step_raw))
            markers_set = set(entry.get("markers") or ())
            required_markers_raw = entry.get("required_markers", [])
            if not isinstance(required_markers_raw, list):
                raise ScreenManifestError(
                    f"{path}: screen {sid!r} 'required_markers' must be a list"
                )
            for rm in required_markers_raw:
                if rm not in markers_set:
                    raise ScreenManifestError(
                        f"{path}: screen {sid!r} required_markers entry {rm!r} "
                        f"is not in the screen's 'markers' list"
                    )
            screens.append(Screen(
                screen_id=sid,
                route=entry.get("route"),
                markers=tuple(entry.get("markers") or ()),
                required_markers=tuple(required_markers_raw),
                steps=tuple(steps),
                source=source_id,
            ))

        else:
            raise ScreenManifestError(
                f"{path}: entry {sid!r} has unknown type {etype!r} "
                f"(expected 'screen' or 'not_a_screen')"
            )

    return screens, not_a_screen


def load_screen_manifest(source_root: str) -> ScreenManifest:
    """Load + merge the screen manifest from the pinned SOURCE CLONES (A1 arm).

    ``source_root`` is the embedded build dir (e.g. ``build/matika``) holding the
    core screens and ``plugins/*`` AppLugs. Raises ScreenManifestError if the
    root is absent, holds no screens files, has malformed data, or declares a
    duplicate screen_id across sources — every one of those fails the build.
    """
    if not os.path.isdir(source_root):
        raise ScreenManifestError(f"source root not found: {source_root}")

    files = discover_screen_files(source_root)
    if not files:
        raise ScreenManifestError(
            f"no {_SCREENS_SUFFIX} files found under {source_root} — the manifest "
            f"could not be loaded"
        )

    screens: List[Screen] = []
    not_a_screen: List[dict] = []
    sources: set = set()
    for path in files:
        sid = _source_id_for(path, source_root)
        parsed_screens, parsed_not = parse_screens_file(path, source_id=sid)
        screens.extend(parsed_screens)
        not_a_screen.extend(parsed_not)
        sources.add(sid)

    _check_duplicate_ids(screens, not_a_screen)

    return ScreenManifest(
        screens=tuple(screens),
        not_a_screen=tuple(not_a_screen),
        sources=tuple(sorted(sources)),
    )


def _check_duplicate_ids(screens: Iterable[Screen], not_a_screen: Iterable[dict]) -> None:
    """Fail loud if any screen_id repeats across sources (mirrors matika loader)."""
    seen: dict = {}
    pairs = [(s.screen_id, s.source) for s in screens]
    pairs += [(e.get("screen_id"), e.get("_source", "?")) for e in not_a_screen]
    for sid, src in pairs:
        if sid is None:
            continue
        if sid in seen:
            raise ScreenManifestError(
                f"duplicate screen_id {sid!r} found in both {seen[sid]!r} and "
                f"{src!r}; each screen_id must be unique across all sources"
            )
        seen[sid] = src


# ---------------------------------------------------------------------------
# Layer-3: functional-test discovery, parse, load, and invocation (ahimsa#101)
#
# The gate discovers *_functional_tests.json files generically across all
# applugs, parses their declared test entries, and invokes ONLY the declared
# functions via importlib — it never names an applug and never calls an
# undeclared function (rule-22 genericity guard).
# ---------------------------------------------------------------------------

def discover_functional_test_files(source_root: str) -> List[str]:
    """Return sorted absolute paths of every ``*_functional_tests.json`` under source_root.

    Generic over applugs: any file matching the suffix is discovered, so the
    gate picks up every applug that ships a functional-test declaration without
    naming any of them. Uses the same ``_SKIP_DIRS`` exclusions as screen
    discovery.
    """
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(source_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(FUNCTIONAL_TESTS_SUFFIX):
                found.append(os.path.join(dirpath, fn))
    return sorted(found)


def parse_functional_tests_file(path: str, source_id: str) -> List[FunctionalTestDecl]:
    """Read + validate one ``*_functional_tests.json``; return list of FunctionalTestDecl.

    Raises ScreenManifestError on any defect (bad JSON, wrong schema_version,
    missing required fields) — the gate is strict (same policy as screens).
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ScreenManifestError(
            f"could not read functional tests file {path}: {exc}"
        ) from exc

    schema = data.get("schema_version")
    if schema != FUNCTIONAL_TEST_SCHEMA:
        raise ScreenManifestError(
            f"{path}: unsupported schema_version {schema!r} "
            f"(gate requires {FUNCTIONAL_TEST_SCHEMA!r})"
        )

    decls: List[FunctionalTestDecl] = []
    for entry in data.get("functional_tests", []):
        for required_field in ("test_id", "description", "module", "function"):
            if required_field not in entry:
                raise ScreenManifestError(
                    f"{path}: functional test entry is missing required field "
                    f"{required_field!r}: {entry!r}"
                )
        decls.append(FunctionalTestDecl(
            test_id=entry["test_id"],
            description=entry["description"],
            module=entry["module"],
            function=entry["function"],
            tags=tuple(entry.get("tags") or ()),
            source=source_id,
        ))
    return decls


def _source_id_for_functional(path: str, source_root: str) -> str:
    """Derive a source id from a functional-tests-file path (for grouping/dedup)."""
    rel = os.path.relpath(path, source_root)
    parts = rel.split(os.sep)
    if "plugins" in parts:
        i = parts.index("plugins")
        if i + 1 < len(parts):
            return parts[i + 1]
    stem = os.path.basename(path)[: -len(FUNCTIONAL_TESTS_SUFFIX)]
    return stem or "unknown"


def load_functional_test_manifest(source_root: str) -> FunctionalTestManifest:
    """Load + merge the functional-test manifest from the pinned SOURCE CLONES.

    ``source_root`` is the embedded build dir. Raises ScreenManifestError if
    the root is absent or holds malformed data, or if duplicate test_ids are
    found across sources. Returns an empty manifest (not an error) if no
    ``*_functional_tests.json`` files are found.
    """
    if not os.path.isdir(source_root):
        raise ScreenManifestError(f"source root not found: {source_root}")

    files = discover_functional_test_files(source_root)
    if not files:
        return FunctionalTestManifest(tests=(), sources=())

    all_decls: List[FunctionalTestDecl] = []
    sources: set = set()
    for path in files:
        sid = _source_id_for_functional(path, source_root)
        decls = parse_functional_tests_file(path, source_id=sid)
        all_decls.extend(decls)
        if decls:
            sources.add(sid)

    # Check for duplicate test_ids across sources
    seen_ids: dict = {}
    for decl in all_decls:
        if decl.test_id in seen_ids:
            raise ScreenManifestError(
                f"duplicate test_id {decl.test_id!r} found in both "
                f"{seen_ids[decl.test_id]!r} and {decl.source!r}; "
                f"each test_id must be unique across all sources"
            )
        seen_ids[decl.test_id] = decl.source

    return FunctionalTestManifest(
        tests=tuple(all_decls),
        sources=tuple(sorted(sources)),
    )


def _find_module_file(source_root: str, module_name: str) -> Optional[str]:
    """Walk source_root for ``{module_name}.py``, skipping ``_SKIP_DIRS``.

    Returns the first matching absolute path, or None if not found.
    """
    target = f"{module_name}.py"
    for dirpath, dirnames, filenames in os.walk(source_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if target in filenames:
            return os.path.join(dirpath, target)
    return None


def invoke_functional_test(
    decl: FunctionalTestDecl,
    source_root: str,
    base_url: str,
    session,
) -> None:
    """Load the declared module and call the declared function.

    The gate calls ONLY what is explicitly declared in the manifest — it never
    discovers or calls undeclared functions (rule-22 genericity guard). Raises
    ScreenManifestError if the module file or the declared function cannot be found.
    """
    module_file = _find_module_file(source_root, decl.module)
    if module_file is None:
        raise ScreenManifestError(
            f"functional test {decl.test_id!r}: module file not found for "
            f"{decl.module!r} under {source_root}"
        )

    spec = importlib.util.spec_from_file_location(decl.module, module_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    fn = getattr(mod, decl.function, None)
    if fn is None:
        raise ScreenManifestError(
            f"functional test {decl.test_id!r}: function {decl.function!r} not "
            f"found in module {decl.module!r} ({module_file})"
        )

    fn(base_url=base_url, session=session)


# ---------------------------------------------------------------------------
# Generic step runner — drives whatever the manifest declares, tier-agnostic
# ---------------------------------------------------------------------------

class ScreenExecutor:
    """Tier-specific verb executor.

    The runner (``drive_screen``) is GENERIC: it iterates the declared steps and
    markers and dispatches them to a tier executor. Each tier (a = HTTP, b =
    browser) subclasses this and implements the verbs it can perform; no screen
    names, routes, or markers are baked into the runner.
    """

    def run_step(self, step: Step) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def assert_markers(self, markers: Tuple[str, ...]) -> None:  # pragma: no cover
        raise NotImplementedError


def drive_screen(screen: Screen, executor: ScreenExecutor) -> None:
    """Run a single declared screen: every step in order, then its markers."""
    for step in screen.steps:
        executor.run_step(step)
    if screen.markers:
        executor.assert_markers(screen.markers)


def drive_screens(manifest: ScreenManifest, executor: ScreenExecutor) -> int:
    """Drive every declared ``screen`` in the manifest. Returns the count driven."""
    for screen in manifest.screens:
        drive_screen(screen, executor)
    return len(manifest.screens)


# ---------------------------------------------------------------------------
# Route inventory — parse the [ROUTES:...] startup marker (M3, matika#86)
# ---------------------------------------------------------------------------

def parse_routes_marker(text: str) -> List[str]:
    """Extract the live GET-route inventory from the ``[ROUTES: ...]`` log line.

    matika emits ``[ROUTES: /a, /b, ...]`` at startup (M3). Returns the routes
    from the LAST such marker in ``text`` (the most recent boot), or ``[]`` if no
    marker is present. A1 only CAPTURES this; the route-vs-manifest hard gate
    that compares it against the manifest is A3 (manomatika/ahimsa#84).
    """
    matches = _ROUTES_MARKER_RE.findall(text or "")
    if not matches:
        return []
    return [r.strip() for r in matches[-1].split(",") if r.strip()]
