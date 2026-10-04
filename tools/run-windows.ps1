param(
    [ValidateSet('check', 'discover', 'once', 'run')]
    [string]$Command = 'check',
    [string]$Config = (Join-Path $env:LOCALAPPDATA 'LuxtronikMqtt\config\devices\heatpump_old.toml')
)
$ErrorActionPreference = 'Stop'
if (-not $env:LUXTRONIK_PASSWORD_FILE) {
    $env:LUXTRONIK_PASSWORD_FILE = Join-Path $env:LOCALAPPDATA 'LuxtronikMqtt\secrets\controller-password'
}
$taskPython = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run uv sync --locked first.' }
& $taskPython -m luxtronik_mqtt --config $Config $Command
exit $LASTEXITCODE
