param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8766,
    [string]$ProjectId = "Chimera-Memory",
    [string]$ProjectRoot = "",
    [string]$JsonlDir = "",
    [int]$EmbeddingThreads = 4,
    [int]$EmbedBatchLimit = 128,
    [int]$EmbedBatchSize = 32,
    [switch]$Replace,
    [switch]$Bootstrap
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Get-ProcessCommandLine {
    param([int]$ProcessId)
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($processInfo) {
        return [string]$processInfo.CommandLine
    }
    return ""
}

$existingOwners = @(
    Get-NetTCPConnection -LocalAddress $HostName -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)
if ($existingOwners.Count -gt 0) {
    $cmOwners = @()
    foreach ($processId in $existingOwners) {
        $commandLine = Get-ProcessCommandLine -ProcessId $processId
        if ($commandLine -like "*chimera_memory.cli*" -and $commandLine -like "*serve*" -and $commandLine -like "*--port $Port*") {
            $cmOwners += $processId
        }
    }

    if ($Replace) {
        foreach ($processId in $existingOwners) {
            Stop-Process -Id $processId -Force
        }
        Start-Sleep -Seconds 1
    } elseif ($cmOwners.Count -gt 0) {
        Write-Host "ChimeraMemory HTTP MCP is already listening on ${HostName}:${Port}."
        exit 0
    } else {
        throw "Port ${HostName}:${Port} is already in use by another process. Re-run with -Replace only if you intend to stop it."
    }
}

if ($Bootstrap -or -not (Test-Path $VenvPython)) {
    & (Join-Path $PSScriptRoot "bootstrap-cm-venv.ps1")
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if (-not (Test-Path $VenvPython)) {
    throw "ChimeraMemory local venv is missing. Run scripts\bootstrap-cm-venv.ps1 first."
}

if (-not $ProjectRoot) {
    $ProjectRoot = Join-Path $RepoRoot ".chimera-memory"
}
if (-not $JsonlDir) {
    $JsonlDir = Join-Path $HOME ".codex\sessions"
}

$env:TRANSCRIPT_JSONL_DIR = $JsonlDir
$env:CHIMERA_CLIENT = "codex"
$env:CHIMERA_MEMORY_MCP_SURFACE = "codex"
$env:CHIMERA_MEMORY_PROJECT_ID = $ProjectId
$env:CHIMERA_MEMORY_PROJECT_ROOT = $ProjectRoot
$env:CHIMERA_MEMORY_STARTUP_BOOTSTRAP = "background"
$env:CHIMERA_MEMORY_EMBEDDING_MAX_THREADS = [string]$EmbeddingThreads
$env:CHIMERA_MEMORY_TRANSCRIPT_EMBED_BATCH_LIMIT = [string]$EmbedBatchLimit
$env:CHIMERA_MEMORY_TRANSCRIPT_EMBED_BATCH_SIZE = [string]$EmbedBatchSize

& $VenvPython -m chimera_memory.cli serve --transport streamable-http --host $HostName --port $Port
exit $LASTEXITCODE
