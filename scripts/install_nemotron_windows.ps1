[CmdletBinding()]
param([ValidateSet("vulkan", "cpu", "cuda")][string]$Backend = "vulkan")

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Backend = $Backend.ToLowerInvariant()
$Root = Split-Path -Parent $PSScriptRoot
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() -ne "X64") {
    throw "This installer requires x86-64 Windows. Use an externally installed NVIDIA runtime on other platforms."
}
$Drive = (Get-Item -LiteralPath $Root).PSDrive
if ($null -ne $Drive.Free -and $Drive.Free -lt 1GB) {
    throw "Free at least 1 GB on the Truss drive before installing Nemotron. The model alone needs about 700 MB."
}
$env:NEMO_SPEECH_MODEL_DIR = Join-Path $Root "data\nemotron-models"
$Version = "0.1.0"
$Destination = Join-Path $Root ".runtime\nemotron-$Version-$Backend"
$Archive = Join-Path $Root ".runtime\nemo-speech-$Version-windows-x86_64-$Backend.zip"
$Url = "https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v$Version/nemo-speech-$Version-windows-x86_64-$Backend.zip"
New-Item -ItemType Directory -Force -Path (Split-Path $Archive) | Out-Null
Write-Host "Downloading NVIDIA NeMo-Speech.cpp $Version ($Backend)..."
Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Archive
$Checksum = (Invoke-WebRequest -UseBasicParsing -Uri "$Url.sha256").Content
if ($Checksum -is [byte[]]) { $Checksum = [System.Text.Encoding]::UTF8.GetString($Checksum) }
$Expected = ($Checksum.Trim() -split '\s+')[0].ToLowerInvariant()
if ($Expected -notmatch '^[0-9a-f]{64}$' -or (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToLowerInvariant() -ne $Expected) {
    throw "NVIDIA runtime checksum verification failed."
}
Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
$Executable = @(Get-ChildItem -LiteralPath $Destination -Filter nemo-speech.exe -File -Recurse)
if ($Executable.Count -ne 1) { throw "Expected one nemo-speech.exe in the release archive." }
& $Executable[0].FullName pull nemotron-en
if ($LASTEXITCODE -ne 0) { throw "Nemotron English model download failed." }
Set-Content -LiteralPath (Join-Path $Destination ".truss-ready") -Value $Version
Write-Host "Nemotron installed. Its model is cached by the NVIDIA runtime."
