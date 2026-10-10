param([Parameter(Mandatory=$true)][string]$RequestFile,
      [Parameter(Mandatory=$true)][string]$RequestId,
      [Parameter(Mandatory=$true)][string]$Data)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$env:PYTHONIOENCODING = 'utf-8'
& python (Join-Path $repoRoot 'src/native_orchestrator/master.py') --data $Data plan $RequestFile --key $RequestId
if ($LASTEXITCODE -ne 0) { throw 'Planning failed; see persisted planning records.' }
& python (Join-Path $repoRoot 'src/native_orchestrator/orchestrator.py') --data $Data --config (Join-Path $repoRoot 'config/config.live.json') run --idle-exit
if ($LASTEXITCODE -ne 0) { throw 'Controller failed; see task evidence.' }
