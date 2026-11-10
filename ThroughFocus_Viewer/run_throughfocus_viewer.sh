#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)/src"
if [[ -x "$(pwd)/.conda/ThroughFocusViewer/bin/python" ]]; then
  PY="$(pwd)/.conda/ThroughFocusViewer/bin/python"
elif [[ -x "$(pwd)/.venv/bin/python" ]]; then
  PY="$(pwd)/.venv/bin/python"
else
  echo "[ERROR] Env ThroughFocusViewer not found. Run: bash setup_env.sh"
  exit 1
fi
exec "${PY}" -m viewer "$@"