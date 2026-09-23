[CmdletBinding()]
param(
    [ValidateLength(24, 512)]
    [string]$ApiToken,

    [ValidateRange(1, 65535)]
    [int]$Port = 10350,

    [switch]$Install,

    [ValidateSet("laya", "jev")]
    [string]$DecisionBackend = $(if ($env:TRUSS_DECISION_BACKEND) { $env:TRUSS_DECISION_BACKEND } else { "laya" }),

    [ValidateSet("sherpa", "nemotron")]
    [string]$SttBackend = $(if ($env:TRUSS_STT_BACKEND) { $env:TRUSS_STT_BACKEND } else { "sherpa" }),

    [ValidateSet("vulkan", "cpu", "cuda")]
    [string]$NemotronBackend = "vulkan"
)

$ErrorActionPreference = "Stop"
$DecisionBackend = $DecisionBackend.ToLowerInvariant()
$SttBackend = $SttBackend.ToLowerInvariant()
$NemotronBackend = $NemotronBackend.ToLowerInvariant()
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
$env:TRUSS_STT_BACKEND = $SttBackend
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
$NemotronProcess = $null
try {
    if ($SttBackend -eq "nemotron" -and -not $env:TRUSS_NEMOTRON_URL) {
        $env:NEMO_SPEECH_MODEL_DIR = Join-Path $Root "data\nemotron-models"
        $RuntimeDirectory = Join-Path $Root ".runtime\nemotron-0.1.0-$NemotronBackend"
        if ($Install -or -not (Test-Path -LiteralPath (Join-Path $RuntimeDirectory ".truss-ready"))) {
            & (Join-Path $PSScriptRoot "install_nemotron_windows.ps1") -Backend $NemotronBackend
        }
        $Executable = @(Get-ChildItem -LiteralPath $RuntimeDirectory -Filter nemo-speech.exe -File -Recurse)
        if ($Executable.Count -ne 1) { throw "Nemotron installation is incomplete. Run again with -Install." }
        # Do not silently reuse an unrelated service on the private runtime port.
        $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 10351)
        try { $Listener.Start() } finally { $Listener.Stop() }
        $DataDirectory = Join-Path $Root "data"
        New-Item -ItemType Directory -Force -Path $DataDirectory | Out-Null
        $NemotronProcess = Start-Process -FilePath $Executable[0].FullName -ArgumentList @(
            "serve", "--asr-model", "nemotron-en", "--host", "127.0.0.1", "--port", "10351",
            "--no-ui", "--asr.streaming.rnnt_right_context", "1", "--asr.endpointing.enable=false"
        ) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $DataDirectory "nemotron.stdout.log") -RedirectStandardError (Join-Path $DataDirectory "nemotron.stderr.log")
        Write-Host "Loading Nemotron (160 ms chunks). Runtime logs: $DataDirectory\nemotron.*.log"
        $Deadline = [DateTime]::UtcNow.AddMinutes(5)
        $Ready = $false
        while ([DateTime]::UtcNow -lt $Deadline) {
            if ($NemotronProcess.HasExited) { throw "Nemotron stopped. Check data\nemotron.stderr.log; try -NemotronBackend cpu if GPU initialization failed." }
            try {
                $Status = Invoke-RestMethod -Uri "http://127.0.0.1:10351/ready" -TimeoutSec 2
                if ($Status.ready -eq $true) { $Ready = $true; break }
            } catch { }
            Start-Sleep -Seconds 1
        }
        if (-not $Ready) { throw "Nemotron did not become ready within five minutes. Check its logs." }
    }
    & $Python (Join-Path $Root "truss_engine\run.py")
    if ($LASTEXITCODE -ne 0) { throw "Truss engine exited with code $LASTEXITCODE." }
} finally {
    if ($NemotronProcess -and -not $NemotronProcess.HasExited) {
        Stop-Process -Id $NemotronProcess.Id -ErrorAction SilentlyContinue
    }
}
