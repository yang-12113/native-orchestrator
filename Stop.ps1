param([string]$Data = "$PSScriptRoot/data-live")
$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'orchestrator.py') --data $Data stop
