"""Regression contracts for an accurate Windows launcher status."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_already_running_launcher_does_not_claim_the_service_stopped() -> None:
    script = (ROOT / "scripts" / "launch_learning_navigator.ps1").read_text(encoding="utf-8")
    batch = (ROOT / "启动 Learning Navigator.bat").read_text(encoding="utf-8")

    already_running = script[
        script.index("elseif (Test-ApplicationHealth)") : script.index(
            "else {", script.index("elseif (Test-ApplicationHealth)")
        )
    ]
    assert "The existing service is still running in the background." in already_running
    assert "Learning Navigator has stopped." not in batch
    assert "Learning Navigator has stopped." in script
