# shfoot one-shot setup for WINDOWS (PowerShell).
# If blocked by execution policy, run once:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Core sanity checks ALWAYS run, even if the strands/boto3 install fails.

Set-Location $PSScriptRoot
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " [shfoot] Windows setup (PowerShell)"        -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# --- locate Python ---
$PY = $null
if (Get-Command py     -ErrorAction SilentlyContinue) { $PY = @('py','-3') }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $PY = @('python') }
if (-not $PY) {
  Write-Host "[FATAL] Python not found. Install 3.11+ from https://python.org (add to PATH), then re-run." -ForegroundColor Red
  Read-Host "Press Enter to exit"; exit 1
}
Write-Host "Using Python: $($PY -join ' ')"
& $PY[0] $PY[1..($PY.Count-1)] --version

# --- create venv if missing ---
$VPY = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $VPY)) {
  Write-Host "Creating virtual env .venv ..."
  & $PY[0] $PY[1..($PY.Count-1)] -m venv .venv
  if ($LASTEXITCODE -ne 0) { Write-Host "[FATAL] venv creation failed" -ForegroundColor Red; Read-Host "Enter to exit"; exit 1 }
}

# --- install deps (warn-and-continue) ---
Write-Host "Installing deploy deps (strands-agents, boto3)..."
& $VPY -m pip install --upgrade pip
& $VPY -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
  Write-Host "[WARN] dep install FAILED. squad.py deploy needs these, but the CORE below still runs." -ForegroundColor Yellow
  Write-Host "       Retry later:  .\.venv\Scripts\python -m pip install strands-agents boto3" -ForegroundColor Yellow
}

# --- sanity checks: ALWAYS run, pure stdlib ---
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Sanity checks (must say GREEN / OK)"         -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
& $VPY reconcile.py
& $VPY -m unittest test_policy

Write-Host ""
Write-Host "DONE." -ForegroundColor Green
Write-Host "Activate later:   .\.venv\Scripts\Activate.ps1"
Write-Host "Schema-check clipboard obs:   Get-Clipboard | .\.venv\Scripts\python reconcile.py -"
Read-Host "Press Enter to close"
