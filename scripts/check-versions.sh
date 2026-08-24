#!/bin/bash
# LokiLinux — platform version drift guard.
# Verifies every platform version location agrees with the root VERSION file.
# Exit 1 on any mismatch. Run before every release (release-platform.sh calls it).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [ ! -f VERSION ]; then
  echo "FAIL VERSION file missing at repo root" >&2
  exit 1
fi
V="$(cat VERSION)"
fail=0

check() { # name expected actual
  if [ "$2" = "$3" ]; then
    printf 'OK   %-28s %s\n' "$1" "$3"
  else
    printf 'FAIL %-28s %s (want %s)\n' "$1" "$3" "$2"
    fail=1
  fi
}

PY_VER="$(grep -oP '^version = "\K[^"]+' backend/pyproject.toml || true)"
INIT_VER="$(grep -oP '^__version__ = "\K[^"]+' backend/lokilinux/__init__.py || true)"
FE_VER="$(grep -oP '^\s*"version": "\K[^"]+' frontend/package.json || true)"

check "VERSION" "$V" "$V"
check "backend/pyproject.toml" "$V" "$PY_VER"
check "lokilinux/__init__.py" "$V" "$INIT_VER"
check "frontend/package.json" "$V" "$FE_VER"

if [ -f agent/VERSION ]; then
  printf 'OK   %-28s %s\n' "agent/VERSION (independent)" "$(cat agent/VERSION)"
else
  echo "FAIL agent/VERSION missing" >&2
  fail=1
fi

exit "$fail"
