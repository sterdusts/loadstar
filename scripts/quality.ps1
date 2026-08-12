$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $ProjectRoot

function Invoke-Checked {
    param([string[]]$Arguments)

    & uv @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "uv $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

Invoke-Checked @("lock", "--check")
Invoke-Checked @("run", "ruff", "format", "--check", ".")
Invoke-Checked @("run", "ruff", "check", ".")
Invoke-Checked @("run", "mypy", "src/learning_navigator")
Invoke-Checked @("run", "alembic", "check")
Invoke-Checked @("run", "pytest")
