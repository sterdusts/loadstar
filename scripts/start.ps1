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

Invoke-Checked @("sync", "--locked", "--extra", "dev")
Invoke-Checked @("run", "python", "scripts/backup_before_migration.py")
Invoke-Checked @("run", "alembic", "upgrade", "head")
Invoke-Checked @("run", "learning-navigator")
