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
$BackupScriptPath = Join-Path $ProjectRoot "scripts\backup_before_migration.py"
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
        if ($Response.StatusCode -ne 200) {
            return $false
        }
        $Payload = $Response.Content | ConvertFrom-Json -ErrorAction Stop
        return (
            $Payload.status -eq "ok" -and
            $Payload.database -eq "reachable"
        )
    }
    catch {
        return $false
    }
}

function New-StorageSecret {
    $Bytes = New-Object byte[] 48
    $Generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $Generator.GetBytes($Bytes)
    }
    finally {
        $Generator.Dispose()
    }
    return ([System.BitConverter]::ToString($Bytes)).Replace("-", "").ToLowerInvariant()
}

function Protect-EnvironmentSecret {
    $Content = [System.IO.File]::ReadAllText($EnvPath)
    $Changed = $false
    $Pattern = '(?m)^LN_STORAGE_SECRET=(.*)$'
    $Match = [System.Text.RegularExpressions.Regex]::Match($Content, $Pattern)
    $Current = if ($Match.Success) { $Match.Groups[1].Value.Trim() } else { "" }
    if (
        (-not $Current) -or
        $Current -eq "replace-with-a-long-random-value" -or
        $Current -eq "development-only-change-me"
    ) {
        $Replacement = "LN_STORAGE_SECRET=$(New-StorageSecret)"
        if ($Match.Success) {
            $Content = [System.Text.RegularExpressions.Regex]::Replace(
                $Content,
                $Pattern,
                $Replacement
            )
        }
        else {
            $Content = $Content.TrimEnd() + [Environment]::NewLine + $Replacement + [Environment]::NewLine
        }
        $Changed = $true
    }
    $SafeSchemaContent = [System.Text.RegularExpressions.Regex]::Replace(
        $Content,
        '(?mi)^LN_AUTO_CREATE_SCHEMA\s*=\s*true\s*$',
        'LN_AUTO_CREATE_SCHEMA=false'
    )
    if ($SafeSchemaContent -ne $Content) {
        $Content = $SafeSchemaContent
        $Changed = $true
    }
    if (-not $Changed) {
        return
    }
    $Utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($EnvPath, $Content, $Utf8WithoutBom)
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

    if (Test-ApplicationHealth) {
        Write-Step "[1/4] Learning Navigator is already running."
        if (-not $NoBrowser) {
            Start-Process $UiUrl
        }
        Write-Host "Open: $UiUrl"
        Write-Host "The existing service is still running in the background." -ForegroundColor Green
        return
    }

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
    Protect-EnvironmentSecret

    $EnvironmentReady =
        (Test-Path -LiteralPath $PythonPath) -and
        (Test-Path -LiteralPath $AlembicPath)

    $UvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $EnvironmentReady) {
        Write-Step "[2/4] Installing the Python environment..."
        if ($null -eq $UvCommand) {
            throw (
                "uv is required for the first launch. Install it from " +
                "https://docs.astral.sh/uv/getting-started/installation/"
            )
        }
        Invoke-NativeCommand `
            -FilePath $UvCommand.Path `
            -Arguments @("sync", "--locked", "--extra", "dev") `
            -FailureMessage "Dependency installation failed"
    }
    elseif ($null -ne $UvCommand) {
        Write-Step "[2/4] Synchronizing the locked Python environment..."
        Invoke-NativeCommand `
            -FilePath $UvCommand.Path `
            -Arguments @("sync", "--locked", "--extra", "dev") `
            -FailureMessage "Dependency synchronization failed"
    }
    else {
        Write-Step "[2/4] Found the Python environment (uv is unavailable; verifying it)."
        Invoke-NativeCommand `
            -FilePath $PythonPath `
            -Arguments @("-m", "pip", "check") `
            -FailureMessage "The existing Python environment is inconsistent"
    }

    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw "Python was not found at $PythonPath"
    }
    if (-not (Test-Path -LiteralPath $AlembicPath)) {
        throw "Alembic was not found at $AlembicPath"
    }

    if (-not (Test-Path -LiteralPath $BackupScriptPath)) {
        throw "The migration backup helper is missing at $BackupScriptPath"
    }
    Write-Step "[3/4] Verifying and backing up the database before migrations..."
    Invoke-NativeCommand `
        -FilePath $PythonPath `
        -Arguments @($BackupScriptPath) `
        -FailureMessage "Database verification or backup failed"
    Write-Step "[3/4] Applying database migrations..."
    Invoke-NativeCommand `
        -FilePath $AlembicPath `
        -Arguments @("upgrade", "head") `
        -FailureMessage "Database migration failed"

    if ($CheckOnly) {
        Write-Step "[4/4] Launcher check passed. The server was not started."
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
