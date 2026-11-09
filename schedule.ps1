[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')]
    [string] $At = '09:00',
    [ValidateRange(1, 30)]
    [int] $EveryDays = 1
)

$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $runner)) {
    throw 'Run setup.ps1 before registering the dry-run schedule.'
}

$action = New-ScheduledTaskAction -Execute $runner -Argument 'main.py run' -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -DaysInterval $EveryDays -At ([datetime]::Today.Add([timespan]::Parse($At)))
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable
if ($PSCmdlet.ShouldProcess('PersonalJobAgent-DryRun', 'Register the local dry-run task')) {
    Register-ScheduledTask -TaskName 'PersonalJobAgent-DryRun' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force
}
