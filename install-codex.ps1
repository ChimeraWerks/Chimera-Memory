param(
    [string]$PersonaId = "",
    [string]$PersonaRoot = "",
    [string]$ProjectId = "",
    [string]$ProjectRoot = "",
    [string]$GlobalRoot = "",
    [string]$Provider = "",
    [switch]$ReuseProviderLogin,
    [switch]$EnableProviderWorker,
    [switch]$ImportHistory,
    [switch]$NoImportHistory,
    [string]$CodexConfig = "",
    [string]$OAuthStore = "",
    [string]$CodexAuthPath = "",
    [string]$HermesHome = "",
    [string]$ClaudeCredentialsPath = "",
    [string]$Python = "python",
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$BootstrapScript = Join-Path $RepoRoot "scripts\bootstrap-cm-venv.ps1"

function Invoke-Step {
    param(
        [string]$Label,
        [string[]]$Args
    )
    Write-Host ""
    Write-Host "==> $Label"
    & $VenvPython @Args
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Read-Defaulted {
    param(
        [string]$Prompt,
        [string]$Default = ""
    )
    if ($Default) {
        $value = Read-Host "$Prompt [$Default]"
        if (-not $value) {
            return $Default
        }
        return $value
    }
    return Read-Host $Prompt
}

function Read-YesNo {
    param(
        [string]$Prompt,
        [bool]$Default = $false
    )
    if ($Yes) {
        return $Default
    }
    $suffix = "[y/N]"
    if ($Default) {
        $suffix = "[Y/n]"
    }
    $value = Read-Host "$Prompt $suffix"
    if (-not $value) {
        return $Default
    }
    return @("y", "yes", "true", "1", "on") -contains $value.Trim().ToLowerInvariant()
}

if ($ImportHistory -and $NoImportHistory) {
    throw "Use only one of -ImportHistory or -NoImportHistory."
}

$reuseProviderLoginValue = [bool]$ReuseProviderLogin

if ($PersonaId -and -not $PersonaRoot) {
    $PersonaRoot = Read-Defaulted "Persona root path" (Get-Location).Path
}
if (-not $PersonaId) {
    if (-not $ProjectRoot) {
        $ProjectRoot = Join-Path $RepoRoot ".chimera-memory"
    }
    if (-not $ProjectId) {
        $ProjectId = [regex]::Replace((Split-Path -Leaf $RepoRoot), "[^A-Za-z0-9_.-]+", "-").Trim(".-")
        if (-not $ProjectId) {
            $ProjectId = "default"
        }
    }
}
if (-not $Provider) {
    $Provider = Read-Defaulted "Enhancement provider preference, blank for dry_run" ""
}
if ($Provider -and -not $reuseProviderLoginValue) {
    $reuseProviderLoginValue = Read-YesNo "Reuse an existing provider login for CM?" $false
}

$installArgs = @(
    "-m", "chimera_memory.cli",
    "codex", "install",
    "--command", "`"$VenvPython`" -m chimera_memory.cli"
)
if ($PersonaId) {
    $installArgs += @("--persona-id", $PersonaId, "--persona-root", $PersonaRoot)
} else {
    $installArgs += @("--project-id", $ProjectId, "--project-root", $ProjectRoot)
    if ($GlobalRoot) {
        $installArgs += @("--global-root", $GlobalRoot)
    }
}

if ($CodexConfig) {
    $installArgs += @("--config", $CodexConfig)
}
if ($ImportHistory) {
    $installArgs += "--import-history"
}
if ($NoImportHistory) {
    $installArgs += "--no-import-history"
}
if ($Provider) {
    $installArgs += @("--provider", $Provider)
}
if ($reuseProviderLoginValue) {
    $installArgs += "--reuse-provider-login"
}
if ($EnableProviderWorker) {
    $installArgs += "--enable-provider-worker"
}
if ($OAuthStore) {
    $installArgs += @("--oauth-store", $OAuthStore)
}
if ($CodexAuthPath) {
    $installArgs += @("--codex-auth-path", $CodexAuthPath)
}
if ($HermesHome) {
    $installArgs += @("--hermes-home", $HermesHome)
}
if ($ClaudeCredentialsPath) {
    $installArgs += @("--claude-credentials-path", $ClaudeCredentialsPath)
}
if ($Yes) {
    $installArgs += "--yes"
}

if (-not (Test-Path $BootstrapScript)) {
    throw "Missing ChimeraMemory venv bootstrap script: $BootstrapScript"
}

Write-Host ""
Write-Host "==> Preparing ChimeraMemory local venv"
& $BootstrapScript -Python $Python
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Invoke-Step "Writing Codex MCP setup" $installArgs

$doctorArgs = @("-m", "chimera_memory.cli", "codex", "doctor")
if ($CodexConfig) {
    $doctorArgs += @("--config", $CodexConfig)
}

Write-Host ""
Write-Host "==> Running Codex doctor"
& $VenvPython @doctorArgs
if ($LASTEXITCODE -gt 1) {
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Done. Restart Codex so it respawns the ChimeraMemory MCP server."
