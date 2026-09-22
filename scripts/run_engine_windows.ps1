[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateLength(24, 512)]
    [string]$ApiToken,

    [ValidateRange(1, 65535)]
    [int]$Port = 10350,

    [switch]$Install
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

if ($Install -or -not (Test-Path -LiteralPath $Python)) {
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $PyLauncher) {
        throw "Python 3.12 is required. Install it from python.org and select 'Add python.exe to PATH'."
    }
    & py -3.12 -m venv $Venv
    & $Python -m pip install --upgrade pip
    & $Python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    & $Python -m pip install -r (Join-Path $Root "truss_engine\requirements.txt")
}

$env:TRUSS_API_TOKEN = $ApiToken
$env:TRUSS_PORT = $Port.ToString()
$env:HF_HOME = Join-Path $Root "data\huggingface"

Write-Host "Starting Truss engine on port $Port. Press Ctrl+C to stop it."
& $Python (Join-Path $Root "truss_engine\run.py")
