from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from imuops.cli import app
from imuops.session import save_session

runner = CliRunner()


def test_cli_e2e_on_oxiod_fixture(oxiod_fixture_file: Path, tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    result = runner.invoke(app, ["ingest", "oxiod", str(oxiod_fixture_file), "--out", str(session_dir)])
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["audit", str(session_dir)])
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["replay", str(session_dir), "--baseline", "pdr"])
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["benchmark", str(session_dir), "--task", "pdr"])
    assert result.exit_code == 0, result.stdout
    corrupt_dir = tmp_path / "session_corrupt"
    result = runner.invoke(app, ["corrupt", str(session_dir), "--preset", "packet_loss_5", "--out", str(corrupt_dir)])
    assert result.exit_code == 0, result.stdout
    report_path = session_dir / "report.html"
    result = runner.invoke(app, ["report", str(session_dir), "--out", str(report_path)])
    assert result.exit_code == 0, result.stdout
    assert report_path.exists()


def test_cli_audit_ci_gate_and_markdown_summary(synthetic_session, tmp_path: Path) -> None:
    synthetic_session.imu.loc[100:180, "t_ms"] += 500
    session_dir = tmp_path / "gate_session"
    save_session(synthetic_session, session_dir)
    result = runner.invoke(app, ["audit", str(session_dir), "--summary-format", "markdown", "--fail-below", "0.95"])
    assert result.exit_code == 1
    assert "| field | value |" in result.stdout


def test_cli_audit_runtime_failure_returns_two(synthetic_session, tmp_path: Path) -> None:
    session_dir = tmp_path / "bad_summary_session"
    save_session(synthetic_session, session_dir)
    result = runner.invoke(app, ["audit", str(session_dir), "--summary-format", "bogus"])
    assert result.exit_code == 2
