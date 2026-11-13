[CmdletBinding()]
param(
    [ValidateRange(0,65535)]
    [int] $Port = 0
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$agentPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $agentPython)) {
    throw 'The local virtual environment is missing. Review the beta setup guide and run setup.ps1 first.'
}

# This script intentionally does NOT discover employers, preview forms,
# schedule automation, import old configs, or enable submission on startup.
& $agentPython main.py doctor
if ($LASTEXITCODE -ne 0) {
    throw 'Local database/config preflight failed. Nothing has been started.'
}
& $agentPython -m scripts.beta_status
if ($LASTEXITCODE -ne 0) {
    throw 'Beta readiness check failed. Nothing has been started.'
}

Write-Host 'Starting local-only review dashboard. Opening it does not contact employers.'
Write-Host 'Use the exact 127.0.0.1 address printed below. Press Ctrl+C to stop.'
& $agentPython main.py serve --port $Port
exit $LASTEXITCODE
