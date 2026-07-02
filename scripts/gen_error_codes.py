"""
gen_error_codes.py — generate a typed-constants module from an error-codes.yaml.

Each origin (matika / eyerate / ahimsa / manomatika) runs this at build time to
codegen typed constants from its ``error-codes.yaml`` into a Python module. Emit
sites reference the generated constants, so a code that is not registered has no
constant and cannot be emitted — compile-time "can't emit an unregistered code"
safety.

The generator VALIDATES the source first (via ahimsa.error_codes.load_error_codes)
and refuses — fail-loud, non-zero exit — to generate from a malformed registry.
This is a distinct single-file codegen guard (not the cross-repo aggregator):
codegen from an invalid file would defeat the whole point, so it blocks.

Usage:
    python scripts/gen_error_codes.py <error-codes.yaml> [--out <module.py>]
    # With no --out, the generated source is written to stdout.

Exit codes:
  0 — generated cleanly
  1 — the error-codes.yaml is invalid or missing (nothing generated)
"""

import argparse
import sys
from pathlib import Path

# Allow running directly from the repo root without installing.
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from ahimsa.error_codes import load_error_codes, render_constants_module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gen_error_codes.py",
        description=(
            "Generate typed error-code constants from an error-codes.yaml. "
            "Validates the source first and refuses to generate from an invalid file."
        ),
    )
    parser.add_argument(
        "source",
        metavar="ERROR_CODES_YAML",
        help="path to the origin's error-codes.yaml",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="MODULE_PY",
        help="write the generated module here (default: stdout)",
    )
    args = parser.parse_args(argv)

    try:
        ecf = load_error_codes(args.source)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    source = render_constants_module(ecf)

    if args.out is None:
        sys.stdout.write(source)
    else:
        args.out.write_text(source)
        print(f"wrote {len(ecf.codes)} code constant(s) to {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
