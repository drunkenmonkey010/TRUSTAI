#!/usr/bin/env bash
# Meridian Vendor AI Intelligence Engine - Linux/macOS helper
# Usage:
#   ./run.sh          # set up venv, install deps, launch Streamlit
#   ./run.sh test     # set up venv, install deps, run the test suite
set -euo pipefail

PYTHON="${PYTHON:-python3.11}"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment (.venv)..."
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from .env.example (edit it to add API keys for LIVE OSINT)."
fi

if [ "${1:-}" = "test" ]; then
  echo "Running test suite..."
  python -m pytest -v
else
  echo "Launching Streamlit app at http://localhost:8501 ..."
  streamlit run app.py
fi
