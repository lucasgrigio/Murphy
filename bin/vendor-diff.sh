#!/usr/bin/env bash
# Diff the local vendored browser_use/ against upstream browser-use.
# Usage:
#   bin/vendor-diff.sh              # diff against upstream HEAD
#   bin/vendor-diff.sh v0.1.40      # diff against a specific tag
#   bin/vendor-diff.sh abc1234      # diff against a specific commit

set -euo pipefail

UPSTREAM_REPO="https://github.com/browser-use/browser-use.git"
REF="${1:-main}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TMPDIR=$(mktemp -d)

trap 'rm -rf "$TMPDIR"' EXIT

echo "Cloning upstream browser-use at ref '$REF'..."
git clone --depth 1 --branch "$REF" "$UPSTREAM_REPO" "$TMPDIR/upstream" 2>/dev/null || \
  (git clone "$UPSTREAM_REPO" "$TMPDIR/upstream" && cd "$TMPDIR/upstream" && git checkout "$REF")

echo ""
echo "Diffing local browser_use/ against upstream browser_use/..."
echo "================================================================"
diff -rq "$REPO_ROOT/browser_use" "$TMPDIR/upstream/browser_use" \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='VENDOR.md' \
  || true

echo ""
echo "Full diff (files that differ):"
echo "================================================================"
diff -ru "$TMPDIR/upstream/browser_use" "$REPO_ROOT/browser_use" \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='VENDOR.md' \
  | head -500 || true

echo ""
echo "Done. Upstream ref: $REF"
