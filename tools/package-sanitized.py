#!/usr/bin/env python3
"""Create a sanitized source ZIP after enforcing the release secret gate."""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

EXCLUDED_DIRS = {".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".idea", ".vscode"}
EXCLUDED_NAMES = {".env", ".env.local", ".env.production", ".env.staging", ".env.development", ".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log"}


def include(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return False
    if path.name in EXCLUDED_NAMES or (path.name.startswith(".env.") and path.name != ".env.example"):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="SiteOps_Sanitized_Source.zip")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output).resolve()

    check = root / "tools" / "check-release-secrets.py"
    result = subprocess.run([sys.executable, str(check), str(root)], check=False)
    if result.returncode:
        return result.returncode

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if include(path, root) and path.resolve() != output:
                archive.write(path, path.relative_to(root))
    print(f"Created sanitized source archive: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
