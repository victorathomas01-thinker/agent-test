[CmdletBinding()]
param(
    [switch] $PreflightOnly,
    [switch] $AllowSchemaUpgrade,
    [switch] $InitializeMissingDatabase,
    [string] $FromMvp
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# This guard runs BEFORE any dependency installs, initialization, or SQLite
# migration. It never reads applicant records beyond schema/count checks.
$guard = @('-m', 'scripts.beta_guard')
if ($AllowSchemaUpgrade) { $guard += '--allow-upgrade' }
if ($InitializeMissingDatabase) { $guard += '--initialize-missing' }
if ($FromMvp) { $guard += @('--from-mvp', $FromMvp) }
if ($PreflightOnly) { $guard += '--dry-run' }
& python @guard
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($PreflightOnly) {
    Write-Host 'Preflight-only mode: no installation, backup, migration or network operations performed.'
    return
}

if (-not (Test-Path -LiteralPath .venv\Scripts\python.exe)) {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$agentPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $agentPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $agentPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Importing a legacy config requires a specific explicit file argument. We
# NEVER silently read a user's Downloads folder or overwrite local settings.
if ($FromMvp) {
    & $agentPython main.py init --from-mvp $FromMvp
} else {
    & $agentPython main.py init
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $agentPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $agentPython -m scripts.beta_status
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Beta installation checks passed. Live submission remains disabled.'
exit 0
