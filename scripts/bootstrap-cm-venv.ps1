param(
    [string]$Python = "python",
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating ChimeraMemory local venv: $VenvDir"
    & $Python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Write-Host "Installing ChimeraMemory into local venv"
$extra = "${RepoRoot}[mcp]"
if ($Dev) {
    $extra = "${RepoRoot}[mcp,dev]"
}
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
& $VenvPython -m pip install -e $extra
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "ChimeraMemory venv ready: $VenvPython"
