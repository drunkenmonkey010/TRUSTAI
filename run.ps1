# Meridian Vendor AI Intelligence Engine - Windows helper
# Usage:
#   .\run.ps1            # set up venv, install deps, launch Streamlit
#   .\run.ps1 -Test      # set up venv, install deps, run the test suite
param([switch]$Test)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment (.venv) with Python 3.11..."
    py -3.11 -m venv .venv
}
. .\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip | Out-Null
pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example (edit it to add API keys for LIVE OSINT)."
}

if ($Test) {
    Write-Host "Running test suite..."
    python -m pytest -v
} else {
    Write-Host "Launching Streamlit app at http://localhost:8501 ..."
    streamlit run app.py
}
