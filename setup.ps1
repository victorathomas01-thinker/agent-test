$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath .venv\Scripts\python.exe)) {
    python -m venv .venv
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
$agentPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $agentPython -m pip install -r requirements.txt
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $agentPython -m playwright install chromium
if ($LASTEXITCODE) { exit $LASTEXITCODE }

$mvpConfig = Join-Path $env:USERPROFILE 'Downloads\Personal_Job_Agent_MVP\job_agent\config.json'
if (Test-Path -LiteralPath $mvpConfig) {
    & $agentPython main.py init --from-mvp $mvpConfig
} else {
    & $agentPython main.py init
}
if ($LASTEXITCODE) { exit $LASTEXITCODE }
& $agentPython -m unittest discover -s tests -v
exit $LASTEXITCODE
