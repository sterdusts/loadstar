"""Regression contracts for an accurate Windows launcher status."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_already_running_launcher_does_not_claim_the_service_stopped() -> None:
    script = (ROOT / "scripts" / "launch_learning_navigator.ps1").read_text(encoding="utf-8")
    batch = (ROOT / "启动 Learning Navigator.bat").read_text(encoding="utf-8")

    already_running = script[
        script.index("$ExistingHealth = Get-ApplicationHealth") : script.index(
            "if (-not (Test-Path -LiteralPath $EnvPath))"
        )
    ]
    assert "The existing service is still running in the background." in already_running
    assert script.index("$ExistingHealth = Get-ApplicationHealth") < script.index(
        "Applying database migrations"
    )
    assert "Learning Navigator has stopped." not in batch
    assert "Learning Navigator has stopped." in script


def test_launcher_protects_secrets_dependencies_and_migrations() -> None:
    script = (ROOT / "scripts" / "launch_learning_navigator.ps1").read_text(encoding="utf-8")

    assert "RandomNumberGenerator" in script
    assert "Protect-EnvironmentSecret" in script
    assert '$Payload.status -ne "ok"' in script
    assert '$Payload.database -ne "reachable"' in script
    assert "LN_AUTO_CREATE_SCHEMA=false" in script
    assert '@("sync", "--locked", "--extra", "dev")' in script
    assert "backup_before_migration.py" in script
    assert script.index("backup_before_migration.py") < script.index("Applying database migrations")


def test_launcher_reuses_only_same_build_and_stops_only_owned_stale_process() -> None:
    script = (ROOT / "scripts" / "launch_learning_navigator.ps1").read_text(encoding="utf-8")

    assert "Get-SourceFingerprint" in script
    assert "$ExistingHealth.source_fingerprint -eq $ExpectedFingerprint" in script
    assert "Test-StaleProcessOwnership" in script
    assert "$State.instance_token -eq [string]$Health.instance_token" in script
    assert "$ListeningPid -eq [int]$Health.process_id" in script
    assert "Stop-OwnedStaleProcess" in script
    assert "unknown or externally started service" in script
    assert ".launcher-state.json" in script
    assert "$env:LN_LAUNCH_INSTANCE_TOKEN = $InstanceToken" in script


def test_native_quality_and_start_commands_fail_closed() -> None:
    quality = (ROOT / "scripts" / "quality.ps1").read_text(encoding="utf-8")
    start = (ROOT / "scripts" / "start.ps1").read_text(encoding="utf-8")

    for script in (quality, start):
        assert "$LASTEXITCODE -ne 0" in script
        assert "throw" in script
        assert "$ProjectRoot = Split-Path -Parent $PSScriptRoot" in script
        assert "Set-Location -LiteralPath $ProjectRoot" in script
    assert '@("lock", "--check")' in quality
    assert '@("run", "alembic", "check")' in quality
    assert '@("sync", "--locked", "--extra", "dev")' in start
    assert "backup_before_migration.py" in start
