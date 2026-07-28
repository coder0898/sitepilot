#!/usr/bin/env python3
"""Run the mandatory local release gates before Phase 3."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run(label: str, command: list[str], cwd: Path, env: dict[str, str] | None = None) -> bool:
    print(f"\n== {label} ==")
    print("$", " ".join(command))
    result = subprocess.run(command, cwd=cwd, env=env, check=False)
    if result.returncode:
        print(f"FAILED: {label}")
        return False
    print(f"PASSED: {label}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-install", action="store_true", help="Skip npm ci when dependencies are already installed.")
    parser.add_argument("--live", action="store_true", help="Run the staging API lifecycle verifier using PHASE2_* environment variables.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    backend = root / "backend"
    frontend = root / "frontend"
    ok = True

    ok &= run("Secret/package safety", [sys.executable, str(root / "tools" / "check-release-secrets.py"), str(root)], root)

    backend_env = os.environ.copy()
    backend_env.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    backend_env["PYTHONPATH"] = "."
    ok &= run("Backend test suite", [sys.executable, "-m", "pytest", "-q"], backend, backend_env)

    if not args.skip_install:
        ok &= run("Frontend clean install", ["npm", "ci", "--no-audit", "--no-fund"], frontend)
    ok &= run("Frontend test suite", ["npm", "test"], frontend)
    ok &= run("Frontend production build", ["npm", "run", "build"], frontend)

    if args.live:
        ok &= run("Live Phase 2 lifecycle", [sys.executable, "-m", "app.scripts.verify_phase2_live"], backend, os.environ.copy())

    print("\nPHASE 2 RELEASE GATE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
