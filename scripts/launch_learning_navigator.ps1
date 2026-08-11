[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$CheckOnly,
    [switch]$SmokeTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogPath = Join-Path $ProjectRoot "launcher.log"
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$AlembicPath = Join-Path $ProjectRoot ".venv\Scripts\alembic.exe"
$EnvPath = Join-Path $ProjectRoot ".env"
$EnvExamplePath = Join-Path $ProjectRoot ".env.example"
$HealthUrl = "http://127.0.0.1:8000/api/health"
$UiUrl = "http://127.0.0.1:8000/ui/"
$ServerProcess = $null
$ExitCode = 0
$TranscriptStarted = $false

function Write-Step {
    param([string]$Message)

    Write-Host $Message -ForegroundColor Cyan
}

function Invoke-NativeCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$FailureMessage
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)."
    }
}

function Test-ApplicationHealth {
    try {
        $Response = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri $HealthUrl `
            -TimeoutSec 1
        return $Response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

try {
    Set-Location -LiteralPath $ProjectRoot
    Set-Content `
        -LiteralPath $LogPath `
        -Value "Learning Navigator launcher - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" `
        -Encoding UTF8
    Start-Transcript -LiteralPath $LogPath -Append -Force | Out-Null
    $TranscriptStarted = $true

    Write-Host ""
    Write-Host "========================================"
    Write-Host "       Learning Navigator Launcher"
    Write-Host "========================================"
    Write-Host ""

    if (-not (Test-Path -LiteralPath $EnvPath)) {
        Write-Step "[1/4] Creating .env from .env.example..."
        if (-not (Test-Path -LiteralPath $EnvExamplePath)) {
            throw "The required .env.example file is missing."
        }
        Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
    }
    else {
        Write-Step "[1/4] Found existing .env."
    }

    $EnvironmentReady =
        (Test-Path -LiteralPath $PythonPath) -and
        (Test-Path -LiteralPath $AlembicPath)

    if (-not $EnvironmentReady) {
        Write-Step "[2/4] Installing the Python environment..."
        $UvCommand = Get-Command uv -ErrorAction SilentlyContinue
        if ($null -eq $UvCommand) {
            throw (
                "uv is required for the first launch. Install it from " +
                "https://docs.astral.sh/uv/getting-started/installation/"
            )
        }
        Invoke-NativeCommand `
            -FilePath $UvCommand.Path `
            -Arguments @("sync", "--extra", "dev") `
            -FailureMessage "Dependency installation failed"
    }
    else {
        Write-Step "[2/4] Found the Python environment."
    }

    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw "Python was not found at $PythonPath"
    }
    if (-not (Test-Path -LiteralPath $AlembicPath)) {
        throw "Alembic was not found at $AlembicPath"
    }

    Write-Step "[3/4] Applying database migrations..."
    Invoke-NativeCommand `
        -FilePath $AlembicPath `
        -Arguments @("upgrade", "head") `
        -FailureMessage "Database migration failed"

    if ($CheckOnly) {
        Write-Step "[4/4] Launcher check passed. The server was not started."
    }
    elseif (Test-ApplicationHealth) {
        Write-Step "[4/4] Learning Navigator is already running."
        if (-not $NoBrowser) {
            Start-Process $UiUrl
        }
        Write-Host "Open: $UiUrl"
        Write-Host "The existing service is still running in the background." -ForegroundColor Green
    }
    else {
        Write-Step "[4/4] Starting Learning Navigator..."
        $ServerProcess = Start-Process `
            -FilePath $PythonPath `
            -ArgumentList @(
                "-m",
                "uvicorn",
                "learning_navigator.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000"
            ) `
            -WorkingDirectory $ProjectRoot `
            -NoNewWindow `
            -PassThru

        $ServerReady = $false
        for ($Attempt = 1; $Attempt -le 60; $Attempt++) {
            if ($ServerProcess.HasExited) {
                throw "The server exited during startup with code $($ServerProcess.ExitCode)."
            }
            if (Test-ApplicationHealth) {
                $ServerReady = $true
                break
            }
            Start-Sleep -Milliseconds 500
        }

        if (-not $ServerReady) {
            throw "The server did not become ready within 30 seconds."
        }

        if ($SmokeTest) {
            $UiResponse = Invoke-WebRequest `
                -UseBasicParsing `
                -Uri $UiUrl `
                -TimeoutSec 5
            if ($UiResponse.StatusCode -ne 200) {
                throw "The UI smoke test returned status $($UiResponse.StatusCode)."
            }

            Write-Host ""
            Write-Host "Smoke test passed: health and UI returned HTTP 200." `
                -ForegroundColor Green
            Stop-Process -Id $ServerProcess.Id -Force
            $ServerProcess.WaitForExit()
            $ServerProcess = $null
        }
        else {
            Write-Host ""
            Write-Host "Learning Navigator is ready: $UiUrl" -ForegroundColor Green
            Write-Host "Press Ctrl+C to stop the service."
            Write-Host ""

            if (-not $NoBrowser) {
                Start-Process $UiUrl
            }

            $ServerProcess.WaitForExit()
            if ($ServerProcess.ExitCode -ne 0) {
                throw "The server stopped with code $($ServerProcess.ExitCode)."
            }
            Write-Host "Learning Navigator has stopped."
        }
    }
}
catch {
    $ExitCode = 1
    Write-Host ""
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "See the complete launcher log at: $LogPath" -ForegroundColor Yellow

    if ($null -ne $ServerProcess -and -not $ServerProcess.HasExited) {
        Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
finally {
    if ($TranscriptStarted) {
        Stop-Transcript | Out-Null
    }
}

exit $ExitCode
