param([Parameter(Mandatory=$true)][string]$Data)
$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'orchestrator.py') --data $Data stop
