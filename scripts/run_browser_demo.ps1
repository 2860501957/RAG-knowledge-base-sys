$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$apiUrl = "http://127.0.0.1:8000/health"
$appUrl = "http://localhost:8501"
$apiScript = Join-Path $repoRoot "scripts\run_api.ps1"
$appScript = Join-Path $repoRoot "scripts\run_app.ps1"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

$env:PYTHONPATH = "."
$env:VECTOR_STORE = "local"
$env:LLM_PROVIDER = "mock"
$env:EMBEDDING_PROVIDER = "hash"

function Test-Url {
    param([string]$Url)
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Wait-Url {
    param(
        [string]$Url,
        [int]$TimeoutSec = 60
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Url -Url $Url) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "Timed out waiting for $Url"
}

if (-not (Test-Url -Url $apiUrl)) {
    Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -WorkingDirectory $repoRoot -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $apiScript
    )
}

if (-not (Test-Url -Url $appUrl)) {
    Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -WorkingDirectory $repoRoot -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $appScript
    )
}

Wait-Url -Url $apiUrl -TimeoutSec 90
Wait-Url -Url $appUrl -TimeoutSec 90

& $pythonExe -m backend.cli browser-demo `
    --api-base-url "http://127.0.0.1:8000" `
    --app-url "http://localhost:8501" `
    --question "Orion 支持 SSO 吗？" `
    --user-id alice `
    --roles employee
