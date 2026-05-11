#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT"

if [ -d .git ] && command -v git >/dev/null 2>&1; then
  git pull --ff-only || echo "Git update skipped or failed. Continuing with local files."
fi

rm -rf build dist src/huvcli.egg-info
python3 -m pip install --upgrade .
rm -rf build dist src/huvcli.egg-info
huv --version
echo "Update done."
