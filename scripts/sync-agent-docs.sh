#!/usr/bin/env bash
# Sync AGENTS.md (source of truth) to tool-native copies.
# Use this INSTEAD of symlinks on Windows / OSS-shared repos.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
for f in CLAUDE.md .goosehints; do
  if [ -L "$f" ]; then rm "$f"; fi
done
cp AGENTS.md CLAUDE.md
cp AGENTS.md .goosehints
echo "Synced AGENTS.md -> CLAUDE.md + .goosehints"
