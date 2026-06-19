"""
make_dmg.py — wrap a macOS .app bundle in a DMG using the dmgbuild library.

Used by .github/workflows/build.yml on the macOS build jobs (arm64 / x86_64)
to package PyInstaller's one-dir .app output into a distributable disk image.

dmgbuild is a pure-Python macOS-only library; it shells out to `hdiutil` under
the hood. This wrapper exists so the workflow does not embed a multi-line
dmgbuild settings module inline in YAML — keeping the build step readable and
the DMG layout testable/auditable as real source.

The DMG presents the .app next to an /Applications symlink, the standard
"drag to install" layout. No code signing is performed (see
manomatika/ahimsa#26 — unsigned-installer limitation, M5 milestone).

Usage:
  python scripts/make_dmg.py --app <path/to/App.app> \
      --volname "<Volume Name>" --output <name.dmg>
"""

import argparse
import os
import sys
from pathlib import Path


def build_dmg(app_path: str, volname: str, output: str) -> None:
    import dmgbuild  # imported lazily — only present on the macOS build runner

    app = Path(app_path)
    if not app.is_dir():
        print(f"[make_dmg] error: app bundle not found: {app}", file=sys.stderr)
        sys.exit(1)

    app_name = app.name  # e.g. "ManoMatika-0.0.1.app"

    # dmgbuild reads its layout from a settings module namespace. We build that
    # namespace as a dict and hand it to dmgbuild.build_dmg(..., defines=...)
    # via a tiny on-disk settings file, which is dmgbuild's supported entry
    # point. The settings file references variables passed through `defines`.
    settings_py = Path(__file__).parent / "_dmg_settings.py"

    out = Path(output)
    if out.exists():
        out.unlink()

    dmgbuild.build_dmg(
        filename=str(out),
        volume_name=volname,
        settings_file=str(settings_py),
        defines={
            "app_path": str(app),
            "app_name": app_name,
        },
    )

    if not out.exists():
        print(f"[make_dmg] error: dmgbuild produced no output at {out}", file=sys.stderr)
        sys.exit(1)
    size = os.path.getsize(out)
    print(f"[make_dmg] wrote {out} ({size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a DMG from a .app bundle")
    parser.add_argument("--app", required=True, help="Path to the .app bundle")
    parser.add_argument("--volname", required=True, help="Mounted volume name")
    parser.add_argument("--output", required=True, help="Output .dmg filename")
    args = parser.parse_args()
    build_dmg(args.app, args.volname, args.output)


if __name__ == "__main__":
    main()
