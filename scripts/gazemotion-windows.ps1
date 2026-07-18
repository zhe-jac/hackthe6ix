[CmdletBinding()]
param(
    [ValidateSet("doctor", "calibrate", "test", "run", "ide")]
    [string]$Command = "run",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GazemotionArguments
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$stateRoot = Join-Path $env:LOCALAPPDATA "GazeMotion"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $stateRoot "windows-venv"
$pythonVersion = if ($env:GAZEMOTION_WINDOWS_PYTHON) {
    $env:GAZEMOTION_WINDOWS_PYTHON
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

New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null

Write-Host "GazeMotion Windows launcher"
Write-Host "  project: $projectRoot"
Write-Host "  environment: $env:UV_PROJECT_ENVIRONMENT"
Write-Host "  command: gazemotion $Command $($GazemotionArguments -join ' ')"

Push-Location $projectRoot
try {
    $uvArguments = @(
        "run",
        "--python", $pythonVersion,
        "--extra", "voice",
        "gazemotion",
        $Command
    ) + $GazemotionArguments
    & $uv.Source @uvArguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
