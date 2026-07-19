[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $projectRoot "editors\vscode\chudvis-vscode.vsix"
if (-not (Test-Path -LiteralPath $source)) {
    throw "Packaged extension not found at $source"
}

$destination = Join-Path $env:TEMP "chudvis-vscode.vsix"
Copy-Item -LiteralPath $source -Destination $destination -Force

$code = Get-Command code.cmd -ErrorAction SilentlyContinue
if ($null -eq $code) {
    $code = Get-Command code -ErrorAction SilentlyContinue
}
if ($null -eq $code) {
    throw "Windows VS Code CLI was not found. Add the VS Code bin directory to PATH."
}

# code.cmd delegates through cmd.exe, which cannot inherit a WSL UNC working directory.
Set-Location -LiteralPath $env:TEMP
& $code.Source --install-extension $destination --force
if ($LASTEXITCODE -ne 0) {
    throw "VS Code extension installation failed with exit code $LASTEXITCODE"
}
