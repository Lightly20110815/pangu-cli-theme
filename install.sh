#!/bin/sh
# One-step install for macOS / Linux:
#   curl -fsSL https://raw.githubusercontent.com/Lightly20110815/pangu-cli-theme/main/install.sh | sh
# With options (see `python3 install.py --help`):
#   curl -fsSL .../install.sh | sh -s -- --apps codex
set -eu
REPO="https://github.com/Lightly20110815/pangu-cli-theme"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
    PY="$c"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "pangu-cli-theme needs Python 3.8 or newer (python3)." >&2
  exit 1
fi

# PANGU_SOURCE: install from a local checkout instead of downloading (used by CI).
if [ -n "${PANGU_SOURCE:-}" ]; then
  exec "$PY" "$PANGU_SOURCE/install.py" "$@"
fi

TMP=$(mktemp -d 2>/dev/null || mktemp -d -t pangu)
trap 'rm -rf "$TMP"' EXIT INT TERM
if command -v git >/dev/null 2>&1; then
  git clone --quiet --depth 1 "$REPO.git" "$TMP/src"
else
  curl -fsSL "$REPO/archive/refs/heads/main.tar.gz" | tar -xz -C "$TMP"
  mv "$TMP/pangu-cli-theme-main" "$TMP/src"
fi
"$PY" "$TMP/src/install.py" "$@"
