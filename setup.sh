#!/usr/bin/env bash
# shfoot one-shot setup for macOS / Linux.  Run:  bash setup.sh
# Core sanity checks ALWAYS run, even if the strands/boto3 install fails.
set -uo pipefail
cd "$(dirname "$0")"
echo "============================================"
echo " [shfoot] setup (macOS/Linux)"
echo "============================================"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "[FATAL] Python not found. Install Python 3.11+ then re-run." >&2
  exit 1
fi
echo "Using Python: $PY"; "$PY" --version

[ -x ".venv/bin/python" ] || { echo "Creating venv .venv ..."; "$PY" -m venv .venv || { echo "[FATAL] venv failed" >&2; exit 1; }; }
VPY=".venv/bin/python"

echo "Installing deploy deps (strands-agents, boto3)..."
"$VPY" -m pip install --upgrade pip
if ! "$VPY" -m pip install -r requirements.txt; then
  echo "[WARN] dep install FAILED. squad.py deploy needs these; CORE below still runs." >&2
  echo "       Retry later:  .venv/bin/python -m pip install strands-agents boto3" >&2
fi

echo "============================================"
echo " Sanity checks (must say GREEN / OK)"
echo "============================================"
"$VPY" reconcile.py
"$VPY" -m unittest test_policy

echo
echo "DONE.  Activate later:  source .venv/bin/activate"
echo "Schema-check clipboard obs (mac):  pbpaste | .venv/bin/python reconcile.py -"
