param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8766,
    [string]$ProjectId = "Chimera-Memory",
    [string]$ProjectRoot = "",
    [string]$GlobalRoot = "",
    [string]$StateRoot = "",
    [string]$OAuthStore = "",
    [string]$Provider = "",
    [string]$JsonlDir = "",
    [int]$EmbeddingThreads = 4,
    [int]$EmbedBatchLimit = 128,
    [int]$EmbedBatchSize = 32,
    [switch]$EnableProviderWorker,
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

function Get-CmProcessInfo {
    param([int]$ProcessId)
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $processInfo) {
        return $null
    }
    $parentInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($processInfo.ParentProcessId)" -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        ProcessId = [int]$ProcessId
        ExecutablePath = [string]$processInfo.ExecutablePath
        CommandLine = [string]$processInfo.CommandLine
        ParentExecutablePath = if ($parentInfo) { [string]$parentInfo.ExecutablePath } else { "" }
        ParentCommandLine = if ($parentInfo) { [string]$parentInfo.CommandLine } else { "" }
    }
}

function ConvertTo-NormalizedPathText {
    param([string]$PathText)
    if (-not $PathText) {
        return ""
    }
    try {
        return [System.IO.Path]::GetFullPath($PathText.Trim('"')).ToLowerInvariant()
    } catch {
        return $PathText.Trim('"').ToLowerInvariant()
    }
}

function Test-TextContainsPath {
    param(
        [string]$Text,
        [string]$ExpectedPath
    )
    if (-not $Text -or -not $ExpectedPath) {
        return $false
    }
    return $Text.IndexOf($ExpectedPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Test-CmProcessUsesRuntime {
    param(
        [object]$ProcessInfo,
        [string]$ExpectedPath
    )
    if (-not $ProcessInfo -or -not $ExpectedPath) {
        return $false
    }
    $expected = ConvertTo-NormalizedPathText -PathText $ExpectedPath
    foreach ($pathValue in @($ProcessInfo.ExecutablePath, $ProcessInfo.ParentExecutablePath)) {
        if ((ConvertTo-NormalizedPathText -PathText $pathValue) -eq $expected) {
            return $true
        }
    }
    foreach ($textValue in @($ProcessInfo.CommandLine, $ProcessInfo.ParentCommandLine)) {
        if (Test-TextContainsPath -Text $textValue -ExpectedPath $ExpectedPath) {
            return $true
        }
    }
    return $false
}

$existingOwners = @(
    Get-NetTCPConnection -State Listen -LocalAddress $HostName -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)
if ($existingOwners.Count -gt 0) {
    $cmOwners = @()
    foreach ($processId in $existingOwners) {
        $processInfo = Get-CmProcessInfo -ProcessId $processId
        $commandLine = if ($processInfo) { $processInfo.CommandLine } else { Get-ProcessCommandLine -ProcessId $processId }
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
        $unexpectedRuntimeOwners = @()
        foreach ($processId in $cmOwners) {
            $processInfo = Get-CmProcessInfo -ProcessId $processId
            if (-not (Test-CmProcessUsesRuntime -ProcessInfo $processInfo -ExpectedPath $VenvPython)) {
                $unexpectedRuntimeOwners += $processId
            }
        }
        if ($unexpectedRuntimeOwners.Count -gt 0) {
            throw "ChimeraMemory HTTP MCP is listening on ${HostName}:${Port}, but not from this repo venv. Re-run with -Replace after confirming the stale PID(s): $($unexpectedRuntimeOwners -join ', ')."
        }
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
if (-not $GlobalRoot) {
    $GlobalRoot = Join-Path $HOME ".chimera-memory\global-memory"
}
if (-not $StateRoot) {
    $StateRoot = Join-Path $HOME ".chimera-memory"
}
if (-not $OAuthStore) {
    $OAuthStore = Join-Path $StateRoot "auth.json"
}

New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null
New-Item -ItemType Directory -Force -Path $ProjectRoot | Out-Null
New-Item -ItemType Directory -Force -Path $GlobalRoot | Out-Null

$env:TRANSCRIPT_JSONL_DIR = $JsonlDir
$env:CHIMERA_CLIENT = "codex"
$env:CHIMERA_MEMORY_MCP_SURFACE = "codex"
$env:CHIMERA_MEMORY_STATE_ROOT = $StateRoot
$env:CHIMERA_MEMORY_OAUTH_STORE = $OAuthStore
$env:CHIMERA_MEMORY_PROJECT_ID = $ProjectId
$env:CHIMERA_MEMORY_PROJECT_ROOT = $ProjectRoot
$env:CHIMERA_MEMORY_GLOBAL_ROOT = $GlobalRoot
$env:CHIMERA_MEMORY_STARTUP_BOOTSTRAP = "background"
$env:CHIMERA_MEMORY_EMBEDDING_MAX_THREADS = [string]$EmbeddingThreads
$env:CHIMERA_MEMORY_TRANSCRIPT_EMBED_BATCH_LIMIT = [string]$EmbedBatchLimit
$env:CHIMERA_MEMORY_TRANSCRIPT_EMBED_BATCH_SIZE = [string]$EmbedBatchSize
if ($Provider) {
    $env:CHIMERA_MEMORY_ENHANCEMENT_PROVIDER_AFFINITY = $Provider
}
if ($EnableProviderWorker) {
    $env:CHIMERA_MEMORY_ENHANCEMENT_WORKER = "true"
    if ($Provider -eq "openai") {
        $env:CHIMERA_MEMORY_ENHANCEMENT_WORKER_MODE = "cli_worker"
        $env:CHIMERA_MEMORY_CLI_WORKER_RUNTIME = "codex"
        $env:CHIMERA_MEMORY_CODEX_WORKER_PROVIDER = "openai"
        if (-not $env:CHIMERA_MEMORY_CODEX_WORKER_MODEL) {
            $env:CHIMERA_MEMORY_CODEX_WORKER_MODEL = "gpt-5.3-codex-spark"
        }
    }
}

& $VenvPython -m chimera_memory.cli serve --transport streamable-http --host $HostName --port $Port
exit $LASTEXITCODE
