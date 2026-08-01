#!/usr/bin/env python3
"""Fail release packaging when secret-bearing files or obvious credentials are present."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

IGNORED_DIRS = {".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__", ".pytest_cache"}
ALLOWED_ENV_FILES = {".env.example"}
SECRET_FILE_NAMES = {".env", ".env.local", ".env.production", ".env.staging", ".env.development"}
KEY_RE = re.compile(
    r"^(DATABASE_URL|SUPABASE_SECRET_KEY|SUPABASE_SERVICE_ROLE_KEY|JWT_SECRET|"
    r"BOOTSTRAP_SUPER_ADMIN_PASSWORD|MIGRATION_TEMP_PASSWORD|POSTGRES_PASSWORD)\s*=\s*(.+)$",
    re.IGNORECASE,
)
PLACEHOLDER_MARKERS = ("example", "placeholder", "changeme", "replace_me", "<", "${", "localhost", "127.0.0.1", "host.docker.internal")
ENV_LIKE_SUFFIXES = {".env", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf"}


def iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or any(part in IGNORED_DIRS for part in path.parts):
            continue
        yield path


def looks_real_secret(value: str) -> bool:
    value = value.strip().strip('"\'')
    if not value:
        return False
    lowered = value.lower()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return False
    if value in {"postgres", "password", "secret", "test", "dev"}:
        return False
    return len(value) >= 8


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    findings: list[str] = []

    for path in iter_files(root):
        rel = path.relative_to(root)
        name = path.name
        if name in SECRET_FILE_NAMES or (name.startswith(".env.") and name not in ALLOWED_ENV_FILES):
            findings.append(f"secret-bearing file must not be packaged: {rel}")
            continue
        if path.suffix.lower() not in ENV_LIKE_SUFFIXES and name not in ALLOWED_ENV_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            match = KEY_RE.match(line.strip())
            if match and looks_real_secret(match.group(2)) and name not in ALLOWED_ENV_FILES:
                findings.append(f"possible populated secret at {rel}:{line_no} ({match.group(1)})")

    if findings:
        print("Release secret check FAILED:")
        for finding in findings:
            print(f" - {finding}")
        return 1
    print("Release secret check passed: no prohibited env files or obvious populated secrets found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
