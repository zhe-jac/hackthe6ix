[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$WakeWordArguments
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$testScript = Join-Path $PSScriptRoot "test-chudvis-wake-word.py"
$env:PYTHONUTF8 = "1"
$pythonVersion = if ($env:CHUDVIS_WINDOWS_PYTHON) {
    $env:CHUDVIS_WINDOWS_PYTHON
} else {
    "3.12"
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Error @"
Windows uv is not installed. From PowerShell, install it once with:
  winget install --id astral-sh.uv -e
Then rerun this launcher from WSL.
"@
}

Write-Host "Chudvis wake-word test (Windows microphone)"
Write-Host "  Python: $pythonVersion"
Write-Host "  Script: $testScript"

Push-Location $projectRoot
try {
    $uvArguments = @(
        "run",
        "--python", $pythonVersion,
        "--no-project",
        "--with", "sherpa-onnx==1.13.4",
        "--with", "sherpa-onnx-bin==1.13.4",
        "--with", "sherpa-onnx-core==1.13.4",
        "--with", "numpy>=1.24,<3",
        "--with", "sentencepiece>=0.2",
        "--with", "sounddevice>=0.4.7",
        "--",
        "python", $testScript
    ) + $WakeWordArguments
    & $uv.Source @uvArguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
