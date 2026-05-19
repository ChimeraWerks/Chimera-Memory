param(
    [string]$PersonaId = "",
    [string]$PersonaRoot = "",
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
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Invoke-Step {
    param(
        [string]$Label,
        [string[]]$Args
    )
    Write-Host ""
    Write-Host "==> $Label"
    & python @Args
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

if (-not $PersonaId) {
    $PersonaId = Read-Defaulted "Persona id, e.g. developer/asa"
}
if (-not $PersonaRoot) {
    $PersonaRoot = Read-Defaulted "Persona root path" (Get-Location).Path
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
    "--persona-id", $PersonaId,
    "--persona-root", $PersonaRoot,
    "--command", "chimera-memory"
)

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

Invoke-Step "Installing ChimeraMemory editable package" @("-m", "pip", "install", "-e", $RepoRoot)
Invoke-Step "Writing Codex MCP setup" $installArgs

$doctorArgs = @("-m", "chimera_memory.cli", "codex", "doctor")
if ($CodexConfig) {
    $doctorArgs += @("--config", $CodexConfig)
}

Write-Host ""
Write-Host "==> Running Codex doctor"
& python @doctorArgs
if ($LASTEXITCODE -gt 1) {
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Done. Restart Codex so it respawns the ChimeraMemory MCP server."
