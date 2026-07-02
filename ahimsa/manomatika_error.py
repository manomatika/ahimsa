"""
manomatika_error.py — the shared ``ManoMatikaError`` base class and the canonical
error-code pattern.

This module is the ONE canonical implementation of the base exception every
component's typed error subclasses extend, and of the well-formed error-code
pattern ``<COMPONENT>-<FAC>-<NNN>``. It is deliberately SELF-CONTAINED — it
imports nothing beyond the standard library — so other repos can mirror it
byte-identically (the plan keeps matika's copy under ``src/matika/error/``).
Do not add ahimsa-only imports here; ahimsa's mechanism imports FROM this module,
never the other way round.

Model A (see manomatika-v0.0.1-plan.md §2): a code is an opaque
``<COMPONENT>-<FAC>-<NNN>`` that is simultaneously (a) the machine carrier
stamped on the log record / HTTP detail and (b) the i18n catalog key.

  - COMPONENT — the emitting component's prefix (MATIKA, EYERATE, AHIMSA,
    MANOMATIKA). Uppercase letters.
  - FAC       — the facility (e.g. LNCH, CFG, AUTH, RBAC, CSRF, PROV, API,
    PLUGIN). Uppercase, may carry trailing digits.
  - NNN       — a zero-padded 3-digit number.

Fail-loud discipline (rule 18): a ``ManoMatikaError`` cannot be constructed with
a code that is not well-formed. The offending value and the expected pattern are
carried in the raised message.
"""

from __future__ import annotations

import re

# The canonical well-formed error-code pattern. This is the single source of
# truth for "what a code looks like"; ahimsa's lints import CODE_RE from here so
# the emit-time guard and the build-time validator can never disagree.
CODE_PATTERN = r"^[A-Z]+-[A-Z][A-Z0-9]*-\d{3}$"
CODE_RE = re.compile(CODE_PATTERN)


def parse_code(code: str) -> tuple[str, str, int]:
    """Split a well-formed code into ``(component, facility, number)``.

    ``number`` is returned as an ``int`` (``"001"`` -> ``1``) so callers can
    reason about contiguity. Raises ``ValueError`` — carrying the offending
    value and the expected pattern — if *code* is not well-formed.
    """
    if not isinstance(code, str) or not CODE_RE.match(code):
        raise ValueError(
            f"not a well-formed error code: {code!r}. Expected pattern "
            f"<COMPONENT>-<FAC>-<NNN> ({CODE_PATTERN})"
        )
    component, facility, number = code.split("-")
    return component, facility, int(number)


class ManoMatikaError(Exception):
    """Base exception for every ManoMatika component's typed errors.

    Carries the opaque error ``code`` (the machine carrier and i18n catalog
    key). Subclasses pin their code and add typed context; call sites raise the
    subclass. Constructing with a code that is not a well-formed
    ``<COMPONENT>-<FAC>-<NNN>`` string fails loud immediately — a code is never
    silently coerced or defaulted.

    The human-readable ``message`` is a DEVELOPER-facing fallback only; the
    user-facing string is resolved from the i18n catalog by ``code``. Arbitrary
    keyword ``context`` is retained on the instance for structured logging.
    """

    def __init__(self, code: str, message: str = "", **context: object) -> None:
        if not isinstance(code, str) or not CODE_RE.match(code):
            raise ValueError(
                f"ManoMatikaError requires a well-formed <COMPONENT>-<FAC>-<NNN> "
                f"code; got {code!r}. Expected pattern: {CODE_PATTERN}"
            )
        self.code = code
        self.message = message
        self.context: dict[str, object] = dict(context)
        rendered = f"[{code}] {message}" if message else f"[{code}]"
        super().__init__(rendered)
