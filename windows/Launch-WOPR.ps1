# Source-development launcher. Portable releases run WOPR.exe directly.
[CmdletBinding()]
param(
    [ValidateRange(0, 65535)][int]$Port = 0,
    [switch]$NoBrowser,
    [switch]$Offline
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host 'WOPR // SOURCE SETUP REQUIRED' -ForegroundColor Green
    Write-Host 'For the easiest experience, extract the portable Windows ZIP and open WOPR.exe.'
    Write-Host 'Developers: install Python 3.11+ from python.org, then run in this folder:'
    Write-Host '  py -3 -m venv .venv'
    Write-Host '  .\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt'
    Write-Host 'Run this launcher again afterwards. No activation or policy change is required.'
    exit 1
}
& $python -c 'import psutil'
if ($LASTEXITCODE -ne 0) {
    Write-Error 'Missing dependency. Run: .\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt'
    exit 1
}
$arguments = @((Join-Path $PSScriptRoot 'wopr.py'), '--port', "$Port")
if ($NoBrowser) { $arguments += '--no-browser' }
if ($Offline) { $arguments += '--offline' }
& $python @arguments
exit $LASTEXITCODE
