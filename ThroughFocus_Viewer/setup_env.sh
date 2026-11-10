#!/usr/bin/env bash
# ThroughFocus_Viewer env: .conda/ThroughFocusViewer
set -euo pipefail
cd "$(dirname "$0")"
TF_ENV="$(pwd)/.conda/ThroughFocusViewer"
TF_VPY="${TF_ENV}/bin/python"

pick_python() {
  if command -v python3.12 >/dev/null 2>&1; then echo "python3.12"
  elif command -v python3 >/dev/null 2>&1; then echo "python3"
  elif command -v python >/dev/null 2>&1; then echo "python"
  else return 1
  fi
}
if ! PYBOOT="$(pick_python)"; then
  echo "[ERROR] Python 3 not found."
  exit 1
fi
echo "[1/4] Creating env ThroughFocusViewer with ${PYBOOT} ..."
mkdir -p .conda
"${PYBOOT}" -m venv "${TF_ENV}"
echo "[2/4] Upgrading pip ..."
"${TF_VPY}" -m pip install --upgrade pip
echo "[3/4] Installing requirements.txt ..."
"${TF_VPY}" -m pip install -r "$(pwd)/requirements.txt"
echo "[4/4] Smoke import check ..."
export PYTHONPATH="$(pwd)/src"
"${TF_VPY}" "$(pwd)/tools/smoke_import.py"
echo
echo "[OK] Environment ThroughFocusViewer ready."
echo "Path: ${TF_ENV}"
echo "Run: ./run_throughfocus_viewer.sh"