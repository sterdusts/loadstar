[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$CheckOnly,
    [switch]$SmokeTest,
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
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
$LauncherStatePath = Join-Path $ProjectRoot ".launcher-state.json"
$HealthUrl = "http://127.0.0.1:$Port/api/health"
$UiUrl = "http://127.0.0.1:$Port/ui/"
$ProductId = "learning-navigator"
$ServerProcess = $null
$ExitCode = 0
$TranscriptStarted = $false
$ActiveLogPath = $LogPath

function Write-Step {
    param([string]$Message)

    Write-Host $Message -ForegroundColor Cyan
}

function Initialize-LauncherLog {
    $Header = "Learning Navigator launcher - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    try {
        Set-Content `
            -LiteralPath $LogPath `
            -Value $Header `
            -Encoding UTF8 `
            -ErrorAction Stop
        $script:ActiveLogPath = $LogPath
    }
    catch [System.IO.IOException] {
        $FallbackName = "launcher.$(Get-Date -Format 'yyyyMMdd-HHmmss').$PID.log"
        $script:ActiveLogPath = Join-Path $ProjectRoot $FallbackName
        Set-Content `
            -LiteralPath $script:ActiveLogPath `
            -Value $Header `
            -Encoding UTF8 `
            -ErrorAction Stop
        Write-Host (
            "The main launcher log is in use; this run will use $script:ActiveLogPath"
        ) -ForegroundColor Yellow
    }

    Start-Transcript -LiteralPath $script:ActiveLogPath -Append -Force | Out-Null
    $script:TranscriptStarted = $true
}

function Stop-LauncherTranscript {
    if (-not $script:TranscriptStarted) {
        return
    }
    try {
        Stop-Transcript | Out-Null
    }
    finally {
        $script:TranscriptStarted = $false
    }
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

function Get-ApplicationHealth {
    try {
        $Response = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri $HealthUrl `
            -TimeoutSec 1
        if ($Response.StatusCode -ne 200) {
            return $null
        }
        $Payload = $Response.Content | ConvertFrom-Json -ErrorAction Stop
        if ($Payload.status -ne "ok" -or $Payload.database -ne "reachable") {
            return $null
        }
        return $Payload
    }
    catch {
        return $null
    }
}

function Get-SourceFingerprint {
    $Files = @()
    foreach ($RelativePath in @("pyproject.toml", "uv.lock")) {
        $Candidate = Join-Path $ProjectRoot $RelativePath
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            $Files += Get-Item -LiteralPath $Candidate
        }
    }
    foreach ($RelativeDirectory in @("src\learning_navigator", "migrations")) {
        $Directory = Join-Path $ProjectRoot $RelativeDirectory
        if (Test-Path -LiteralPath $Directory -PathType Container) {
            $Files += Get-ChildItem -LiteralPath $Directory -Recurse -File | Where-Object {
                $_.Extension -ne ".pyc" -and $_.FullName -notlike "*\__pycache__\*"
            }
        }
    }
    $Entries = @(
        $Files | Sort-Object FullName -Unique | ForEach-Object {
            $Relative = $_.FullName.Substring($ProjectRoot.Length).TrimStart("\").Replace("\", "/")
            $FileHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
            "$Relative`0$FileHash"
        }
    )
    $Manifest = [string]::Join("`n", $Entries)
    $Hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Manifest)
        return ([System.BitConverter]::ToString($Hasher.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $Hasher.Dispose()
    }
}

function Get-ListeningProcessId {
    $Connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    $ProcessIds = @($Connections | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($ProcessIds.Count -eq 1) {
        return [int]$ProcessIds[0]
    }
    return $null
}

function Get-LauncherState {
    if (-not (Test-Path -LiteralPath $LauncherStatePath -PathType Leaf)) {
        return $null
    }
    try {
        return Get-Content -Raw -LiteralPath $LauncherStatePath | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        return $null
    }
}

function Test-StaleProcessOwnership {
    param([object]$Health, [object]$State)

    if ($null -eq $State) { return $false }
    $ListeningPid = Get-ListeningProcessId
    $ExpectedRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd("\")
    $StateRoot = [System.IO.Path]::GetFullPath([string]$State.project_root).TrimEnd("\")
    return (
        $Health.product_id -eq $ProductId -and
        [string]$Health.instance_token -and
        [int]$Health.process_id -gt 0 -and
        $State.product_id -eq $ProductId -and
        [string]$State.instance_token -eq [string]$Health.instance_token -and
        [int]$State.process_id -eq [int]$Health.process_id -and
        [int]$State.port -eq $Port -and
        $StateRoot.Equals($ExpectedRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
        $ListeningPid -eq [int]$Health.process_id
    )
}

function Test-LegacyLearningNavigatorProcess {
    param([object]$Health)

    if (
        $Health.product_id -ne $ProductId -or
        [string]$Health.source_fingerprint -notmatch '^[a-fA-F0-9]{64}$' -or
        [string]$Health.instance_token -notmatch '^[a-fA-F0-9]{32}$' -or
        [int]$Health.process_id -le 0
    ) {
        return $false
    }

    $ListeningPid = Get-ListeningProcessId
    if ($ListeningPid -ne [int]$Health.process_id) {
        return $false
    }
    $Connections = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if (
        $Connections.Count -eq 0 -or
        @($Connections | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') }).Count -gt 0
    ) {
        return $false
    }

    try {
        $Process = Get-CimInstance Win32_Process -Filter "ProcessId=$($Health.process_id)"
        $ExecutableName = [System.IO.Path]::GetFileName([string]$Process.ExecutablePath)
        $CommandLine = [string]$Process.CommandLine
        $PortPattern = [System.Text.RegularExpressions.Regex]::Escape([string]$Port)
        return (
            $ExecutableName -match '^pythonw?(\.exe)?$' -and
            $CommandLine -match '(?i)(^|\s)-m\s+uvicorn\s+learning_navigator\.main:app(\s|$)' -and
            $CommandLine -match '(?i)(^|\s)--host\s+127\.0\.0\.1(\s|$)' -and
            $CommandLine -match "(?i)(^|\s)--port\s+$PortPattern(\s|$)"
        )
    }
    catch {
        return $false
    }
}

function Stop-OwnedStaleProcess {
    param([object]$Health)

    Stop-Process -Id ([int]$Health.process_id) -Force -ErrorAction Stop
    for ($Attempt = 1; $Attempt -le 20; $Attempt++) {
        Start-Sleep -Milliseconds 250
        if ($null -eq (Get-ListeningProcessId)) {
            Remove-Item -LiteralPath $LauncherStatePath -Force -ErrorAction SilentlyContinue
            return
        }
    }
    throw "The stale Learning Navigator process did not release port $Port."
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
    Initialize-LauncherLog

    Write-Host ""
    Write-Host "========================================"
    Write-Host "       Learning Navigator Launcher"
    Write-Host "========================================"
    Write-Host ""

    $ExpectedFingerprint = Get-SourceFingerprint
    $ExistingHealth = Get-ApplicationHealth
    if ($null -ne $ExistingHealth) {
        if (
            $ExistingHealth.product_id -eq $ProductId -and
            $ExistingHealth.source_fingerprint -eq $ExpectedFingerprint
        ) {
            Write-Step "[1/4] This Learning Navigator build is already running."
            if (-not $NoBrowser) {
                Start-Process $UiUrl
            }
            Write-Host "Open: $UiUrl"
            Write-Host "The existing service is still running in the background." -ForegroundColor Green
            return
        }
        $LauncherState = Get-LauncherState
        $OwnedStaleProcess = Test-StaleProcessOwnership `
            -Health $ExistingHealth `
            -State $LauncherState
        $VerifiedLegacyProcess = (
            $null -eq $LauncherState -and
            (Test-LegacyLearningNavigatorProcess -Health $ExistingHealth)
        )
        if (-not $OwnedStaleProcess -and -not $VerifiedLegacyProcess) {
            throw (
                "Port $Port is occupied by an unknown or externally started service. " +
                "It was not stopped. Close it manually or choose another port."
            )
        }
        if ($VerifiedLegacyProcess) {
            Write-Step "[1/4] Verified an older Learning Navigator instance without launcher state."
        }
        Write-Step "[1/4] Stopping the stale Learning Navigator build..."
        Stop-OwnedStaleProcess -Health $ExistingHealth
    }
    elseif ($null -ne (Get-ListeningProcessId)) {
        throw "Port $Port is occupied by a service without a valid Learning Navigator health response; it was not stopped."
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
        $InstanceToken = [Guid]::NewGuid().ToString("N")
        $env:LN_LAUNCH_INSTANCE_TOKEN = $InstanceToken
        $ServerProcess = Start-Process `
            -FilePath $PythonPath `
            -ArgumentList @(
                "-m",
                "uvicorn",
                "learning_navigator.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "$Port"
            ) `
            -WorkingDirectory $ProjectRoot `
            -NoNewWindow `
            -PassThru

        $ServerReady = $false
        for ($Attempt = 1; $Attempt -le 60; $Attempt++) {
            if ($ServerProcess.HasExited) {
                throw "The server exited during startup with code $($ServerProcess.ExitCode)."
            }
            $StartedHealth = Get-ApplicationHealth
            if (
                $null -ne $StartedHealth -and
                $StartedHealth.product_id -eq $ProductId -and
                $StartedHealth.source_fingerprint -eq $ExpectedFingerprint -and
                $StartedHealth.instance_token -eq $InstanceToken
            ) {
                $ServerReady = $true
                break
            }
            Start-Sleep -Milliseconds 500
        }

        if (-not $ServerReady) {
            throw "The server did not become ready within 30 seconds."
        }

        @{
            product_id = $ProductId
            project_root = [System.IO.Path]::GetFullPath($ProjectRoot)
            port = $Port
            process_id = [int]$StartedHealth.process_id
            instance_token = $InstanceToken
            source_fingerprint = $ExpectedFingerprint
        } | ConvertTo-Json | Set-Content -LiteralPath $LauncherStatePath -Encoding UTF8

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
            Remove-Item -LiteralPath $LauncherStatePath -Force -ErrorAction SilentlyContinue
        }
        else {
            Write-Host ""
            Write-Host "Learning Navigator is ready: $UiUrl" -ForegroundColor Green
            Write-Host "Press Ctrl+C to stop the service."
            Write-Host ""

            if (-not $NoBrowser) {
                Start-Process $UiUrl
            }

            # The server can run for hours. Do not hold an exclusive handle on
            # launcher.log while this wrapper waits for it to exit.
            Stop-LauncherTranscript
            $ServerProcess.WaitForExit()
            Remove-Item -LiteralPath $LauncherStatePath -Force -ErrorAction SilentlyContinue
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
    Write-Host "See the complete launcher log at: $ActiveLogPath" -ForegroundColor Yellow

    if ($null -ne $ServerProcess -and -not $ServerProcess.HasExited) {
        Stop-Process -Id $ServerProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Stop-LauncherTranscript
}

exit $ExitCode
