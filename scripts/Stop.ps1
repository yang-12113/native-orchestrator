param([Parameter(Mandatory=$true)][string]$Data)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
& python (Join-Path $repoRoot 'src/native_orchestrator/orchestrator.py') --data $Data stop
