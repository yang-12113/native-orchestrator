param([Parameter(Mandatory=$true)][string]$Data, [string]$Config = "$PSScriptRoot/config.live.json")
$ErrorActionPreference = 'Stop'
$controllerPath = Join-Path $PSScriptRoot 'orchestrator.py'
& python -B -c "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from orchestrator import Controller; Controller.assert_current_database(Path(sys.argv[2]))" $PSScriptRoot $Data
if ($LASTEXITCODE -ne 0) { throw 'Legacy or unreadable database refused; no service logs or state were changed.' }
New-Item -ItemType Directory -Force -Path $Data | Out-Null
if (Test-Path -LiteralPath (Join-Path $Data 'stop.request')) { throw 'stop.request exists. Remove this one marker explicitly to resume.' }
$pythonPath = (Get-Command python).Source
$arguments = @('"' + $controllerPath + '"', '--data', '"' + $Data + '"', '--config', '"' + $Config + '"', 'run')
$serviceProcess = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $Data 'service.stdout.log') -RedirectStandardError (Join-Path $Data 'service.stderr.log')
@{ pid=$serviceProcess.Id; started=(Get-Date).ToString('o'); executable=$pythonPath; script=$controllerPath } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Data 'service.json') -Encoding utf8
Write-Output "Controller started: PID $($serviceProcess.Id). Stop.ps1 requests graceful stop."
