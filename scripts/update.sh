#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT"

if [ -d .git ] && command -v git >/dev/null 2>&1; then
  git pull --ff-only || echo "Git update skipped or failed. Continuing with local files."
fi

python3 -m pip install --upgrade .
huv --version
echo "Update done."
