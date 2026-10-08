param([Parameter(Mandatory=$true)][string]$RequestFile,
      [Parameter(Mandatory=$true)][string]$RequestId,
      [string]$Data = "$PSScriptRoot/data-live")
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
& python (Join-Path $PSScriptRoot 'master.py') --data $Data plan $RequestFile --key $RequestId
if ($LASTEXITCODE -ne 0) { throw 'Planning failed; see persisted planning records.' }
& python (Join-Path $PSScriptRoot 'orchestrator.py') --data $Data --config (Join-Path $PSScriptRoot 'config.live.json') run --idle-exit
if ($LASTEXITCODE -ne 0) { throw 'Controller failed; see task evidence.' }
