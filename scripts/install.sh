#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Missing required command: python3" >&2
  exit 1
fi

rm -rf build dist src/huvcli.egg-info
python3 -m pip install --upgrade .
rm -rf build dist src/huvcli.egg-info

if [ "${HUV_API_KEY:-}" = "" ]; then
  echo "HUV_API_KEY not set. Add this to your shell profile:"
  echo '  export HUV_API_KEY="your-key"'
fi

huv --version
echo "Try:"
echo '  huv "explain this folder"'
echo "  huv chat"
echo "  huv assets"
