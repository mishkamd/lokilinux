#!/bin/bash
# LokiLinux — platform release: bump VERSION + pyproject + __init__.py +
# frontend package.json + .env LOKILINUX_VERSION, prepend CHANGELOG entry,
# commit + tag vX.Y.Z. Mechanical by design — the bump TYPE is decided by
# the caller (bump-version skill asks the user); this script only executes.
# Agent releases use .claude/skills/ship-changes/scripts/release.sh instead.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

BUMP="${1:-}"
DRY_RUN=false
for arg in "$@"; do
  [ "$arg" = "--dry-run" ] && DRY_RUN=true
done

case "$BUMP" in
  patch|minor|major) ;;
  *) echo "Usage: $0 <patch|minor|major> [--dry-run]" >&2; exit 1 ;;
esac

CURRENT="$(cat VERSION)"
IFS='.' read -r MAJ MIN PAT <<< "$CURRENT"
case "$BUMP" in
  patch) PAT=$((PAT + 1)) ;;
  minor) MIN=$((MIN + 1)); PAT=0 ;;
  major) MAJ=$((MAJ + 1)); MIN=0; PAT=0 ;;
esac
NEW="$MAJ.$MIN.$PAT"
echo "== platform release: $CURRENT -> $NEW ($BUMP) =="
$DRY_RUN && echo "(dry run — no writes, no commit, no tag)"

# ── Preflight ─────────────────────────────────────────────────────────────────
if ! $DRY_RUN; then
  if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: dirty working tree — commit or stash before releasing." >&2
    exit 1
  fi
  bash scripts/check-versions.sh
fi

# ── Bump version literals (prefix + any semver, so drifted files still match) ─
SEMVER='[0-9]\+\.[0-9]\+\.[0-9]\+'
edit() { # file prefix
  local f="$1" p="$2"
  if $DRY_RUN; then
    grep -q "${p}${SEMVER}" "$f" && echo "  [dry-run] would edit $f" || echo "  [dry-run] SKIP $f (expected line not found)"
    return
  fi
  if grep -q "${p}${SEMVER}" "$f"; then
    sed -i "s|${p}${SEMVER}|${p}${NEW}|" "$f"
    echo "  edited $f"
  else
    echo "  SKIP $f — expected line not found, leaving untouched" >&2
  fi
}

if $DRY_RUN; then
  echo "  [dry-run] would write VERSION=$NEW"
else
  echo "$NEW" > VERSION
  echo "  wrote VERSION=$NEW"
fi

edit backend/pyproject.toml 'version = "'
edit backend/lokilinux/__init__.py '__version__ = "'
if command -v npm >/dev/null 2>&1; then
  if $DRY_RUN; then
    echo "  [dry-run] would run: npm --prefix frontend version $NEW --no-git-tag-version"
  else
    npm --prefix frontend version "$NEW" --no-git-tag-version >/dev/null
    echo "  npm bumped frontend/package.json (+lock)"
  fi
else
  edit frontend/package.json '"version": "'
fi

# .env is gitignored — it only steers local image tags via ${LOKILINUX_VERSION}.
if [ -f .env ]; then
  if $DRY_RUN; then
    echo "  [dry-run] would set .env LOKILINUX_VERSION=$NEW"
  else
    sed -i "s/^LOKILINUX_VERSION=.*/LOKILINUX_VERSION=$NEW/" .env
    echo "  set .env LOKILINUX_VERSION=$NEW"
  fi
fi

# ── CHANGELOG.md — prepend section from git log since last vX tag ─────────────
LAST_TAG="$(git describe --tags --abbrev=0 --match 'v*' 2>/dev/null || true)"
RANGE="${LAST_TAG:+$LAST_TAG..}HEAD"
if $DRY_RUN; then
  echo "  [dry-run] would prepend CHANGELOG section for $NEW (git log ${RANGE:-all})"
else
  TMP="$(mktemp /tmp/opencode/changelog-entry.XXXXXX)"
  {
    echo "## [$NEW] - $(date +%F)"
    echo
    git log --no-merges --pretty=format:'- %s (%h)' "$RANGE" | head -30
    echo
    echo
  } >> "$TMP"
  [ -f CHANGELOG.md ] && cat CHANGELOG.md >> "$TMP"
  mv "$TMP" CHANGELOG.md
  echo "  prepended CHANGELOG.md section for $NEW"
fi

# ── Postflight: every location must now agree ────────────────────────────────
bash scripts/check-versions.sh

# ── Commit + tag ('v' prefix = platform namespace; agent tags have none) ──────
if $DRY_RUN; then
  echo "  [dry-run] would commit VERSION backend/ frontend/ CHANGELOG.md and tag v$NEW"
else
  git add VERSION backend/pyproject.toml backend/lokilinux/__init__.py \
    frontend/package.json CHANGELOG.md
  git add frontend/package-lock.json 2>/dev/null || true
  git commit -m "Release v$NEW"
  if git rev-parse "v$NEW" >/dev/null 2>&1; then
    echo "  Tag v$NEW already exists, leaving it."
  else
    git tag "v$NEW"
    echo "Tagged v$NEW — push with: git push origin main v$NEW"
  fi
  echo
  echo "Next: rebuild affected images so containers actually run v$NEW:"
  echo "  docker compose build lokilinux-api lokilinux-grpc lokilinux-frontend lokilinux-compliance lokilinux-migrate"
  echo "  docker compose up -d"
fi
echo "== done: $CURRENT -> $NEW =="
