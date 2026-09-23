[CmdletBinding()]
param(
    [ValidateLength(24, 512)]
    [string]$ApiToken,

    [ValidateRange(1, 65535)]
    [int]$Port = 10350,

    [switch]$Install,

    [ValidateSet("laya", "jev")]
    [string]$DecisionBackend = $(if ($env:TRUSS_DECISION_BACKEND) { $env:TRUSS_DECISION_BACKEND } else { "laya" })
)

$ErrorActionPreference = "Stop"
$DecisionBackend = $DecisionBackend.ToLowerInvariant()
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

if ($Install -or -not (Test-Path -LiteralPath $Python)) {
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $PyLauncher) {
        throw "Python 3.12 is required. Install it from python.org and select 'Add python.exe to PATH'."
    }
    & py -3.12 -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Failed to create Python environment." }
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip." }
    $Requirements = "truss_engine\requirements-base.txt"
    if ($DecisionBackend -eq "laya") {
        & $Python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
        if ($LASTEXITCODE -ne 0) { throw "Failed to install PyTorch." }
        $Requirements = "truss_engine\requirements.txt"
    }
    & $Python -m pip install -r (Join-Path $Root $Requirements)
    if ($LASTEXITCODE -ne 0) { throw "Failed to install engine dependencies." }
}

$env:TRUSS_DECISION_BACKEND = $DecisionBackend
if ($DecisionBackend -eq "jev" -and -not $env:TYPESAFE_API_KEY) {
    throw "Set TYPESAFE_API_KEY in your environment before starting Jev mode."
}

if ($ApiToken) {
    $env:TRUSS_API_TOKEN = $ApiToken
} elseif (Test-Path Env:TRUSS_API_TOKEN) {
    Remove-Item Env:TRUSS_API_TOKEN
}
$env:TRUSS_PORT = $Port.ToString()
$env:HF_HOME = Join-Path $Root "data\huggingface"
$env:TRUSS_TOKEN_FILE = Join-Path $Root "data\truss_engine_token"

Write-Host "Starting Truss engine on port $Port. Press Ctrl+C to stop it."
& $Python (Join-Path $Root "truss_engine\run.py")
