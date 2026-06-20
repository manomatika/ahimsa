#!/usr/bin/env python3
"""smoke_launch.py — boot the frozen product bundle and prove it actually runs.

CI freezes and wraps the product but historically never LAUNCHED it, so
"the frozen app can't even start" stayed invisible until the bundle reached a
real machine (three boot failures in a row). This script closes that gap: it
boots the frozen executable in a CLEAN temporary HOME so the real first-run
path runs (SECRET_KEY generation, in-process alembic migration, applug
discovery/extraction/load, uvicorn server bind), then asserts the app reached a
running, serving state with the bundled applug loaded — and fails the build if
it did not, dumping the on-disk logs and the process output so the reason is
visible directly in the CI job log.

A TIMEOUT bounds the wait so a hung boot FAILS the job instead of blocking it.

Usage:
    python smoke_launch.py --exe <path-to-frozen-binary> \
        [--expect-plugin eyerate] [--port 8000] [--timeout 90]
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def _read_logs(logs_dir: str) -> str:
    """Concatenate every *.log under the frozen app's ~/matika/logs/ dir."""
    chunks = []
    for lf in sorted(glob.glob(os.path.join(logs_dir, "*.log"))):
        try:
            with open(lf, encoding="utf-8", errors="replace") as fh:
                chunks.append(f"\n----- {lf} -----\n{fh.read()}")
        except OSError as exc:  # pragma: no cover - defensive
            chunks.append(f"\n(could not read {lf}: {exc})\n")
    return "".join(chunks)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exe", required=True, help="frozen executable to launch")
    ap.add_argument("--expect-plugin", default="eyerate",
                    help="applug id that MUST be discovered + loaded at boot")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--timeout", type=int, default=90,
                    help="seconds to wait for the server before failing")
    args = ap.parse_args()

    exe = os.path.abspath(args.exe)
    if not os.path.exists(exe):
        print(f"::error::smoke: frozen executable not found: {exe}")
        return 1

    # A pristine HOME forces the genuine first-run path every time — this is the
    # exact code that has been failing on the mini (SECRET_KEY, alembic migrate,
    # plugin discovery/load, server bind).
    temp_home = tempfile.mkdtemp(prefix="mm-smoke-home-")
    env = dict(os.environ)
    env["HOME"] = temp_home          # POSIX Path.home()
    env["USERPROFILE"] = temp_home   # Windows Path.home()
    # Neutralise the launcher's browser-open in headless CI.
    env["BROWSER"] = "true" if os.name != "nt" else "cmd /c rem"

    out_path = os.path.join(temp_home, "smoke-stdout.log")
    print(f"smoke: launching frozen binary : {exe}")
    print(f"smoke: clean HOME              : {temp_home}")
    print(f"smoke: health URL              : http://127.0.0.1:{args.port}/")
    print(f"smoke: timeout                 : {args.timeout}s")

    out_fh = open(out_path, "w", encoding="utf-8")
    proc = subprocess.Popen([exe], env=env, stdout=out_fh,
                            stderr=subprocess.STDOUT)

    url = f"http://127.0.0.1:{args.port}/"
    deadline = time.time() + args.timeout
    server_up = False
    exited_early = False
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f"::error::smoke: process EXITED early (code {proc.returncode}) "
                  f"before the server came up")
            exited_early = True
            break
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                print(f"smoke: server responded HTTP {resp.status}")
                server_up = True
                break
        except urllib.error.HTTPError as exc:
            # Any HTTP status (401/404/...) means the server bound and is serving.
            print(f"smoke: server responded HTTP {exc.code}")
            server_up = True
            break
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(1.0)

    if not server_up and not exited_early:
        print(f"::error::smoke: TIMEOUT after {args.timeout}s — server never "
              f"bound on port {args.port}")

    logs_dir = os.path.join(temp_home, "matika", "logs")
    log_text = _read_logs(logs_dir)

    # Also fold in the process stdout/stderr. Some boot lines only reach the
    # console handler (e.g. uvicorn's "Uvicorn running", or any line emitted
    # while a library momentarily owns the root logger), so search both the
    # on-disk logs AND the captured process output for the boot markers.
    proc_output = ""
    try:
        with open(out_path, encoding="utf-8", errors="replace") as fh:
            proc_output = fh.read()
    except OSError:
        pass
    search_text = log_text + "\n" + proc_output

    # --- Assertions on the real first-run path -----------------------------
    # First-run establishes the schema via create_all() and records it with
    # `alembic stamp head` (the initial migration only ADDS indexes to an
    # existing table, so `upgrade head` on a fresh DB fails). Require BOTH the
    # schema-created line and the stamp-complete line so a half-finished init
    # (e.g. a model import error) does NOT count as applied. Still accept a
    # legacy "alembic upgrade head complete" line for forward/backward safety.
    migration_ok = (
        ("Database schema created" in search_text
         and "alembic stamp head complete" in search_text)
        or "alembic upgrade head complete" in search_text
    )
    plugin_ok = (f"[PLUGIN:{args.expect_plugin}]" in search_text
                 and "Successfully loaded plugin" in search_text)
    uvicorn_log_ok = "Uvicorn running" in search_text  # informational only

    # --- Shut the app down -------------------------------------------------
    try:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    except Exception:  # pragma: no cover - defensive
        pass
    out_fh.close()

    ok = server_up and migration_ok and plugin_ok

    print("\n=== SMOKE RESULT ===")
    print(f"  server bound / responding   : {server_up}")
    print(f"  alembic migration applied   : {migration_ok}")
    print(f"  applug '{args.expect_plugin}' loaded : {plugin_ok}")
    print(f"  'Uvicorn running' log line  : {uvicorn_log_ok}")

    if not ok:
        print("::error::smoke-launch FAILED — the frozen app did not reach a "
              "running, applug-loaded server. Logs + process output below.")
        print("\n========== ~/matika/logs (frozen app) ==========")
        print(log_text if log_text else "(NO log files were written!)")
        try:
            with open(out_path, encoding="utf-8", errors="replace") as fh:
                print("\n========== process stdout/stderr ==========")
                print(fh.read())
        except OSError:
            pass
        return 1

    print("\n========== BOOT PROOF (matching log lines) ==========")
    for line in search_text.splitlines():
        if any(marker in line for marker in (
            "First-run init", "SECRET_KEY generated", "Database schema created",
            "alembic stamp head", "alembic upgrade head",
            "Discovering plugins", "Successfully loaded plugin",
            "Loaded plugins:", "Uvicorn running",
        )):
            print("  " + line.strip())
    print("\nsmoke: PASS — frozen app booted, migrated, loaded "
          f"'{args.expect_plugin}', and served on port {args.port}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
