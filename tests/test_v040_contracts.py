from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from imuops.audit import run_audit
from imuops.cli import app
from imuops.config import load_defaults
from imuops.exporting import export_session
from imuops.session import save_session

runner = CliRunner()


def test_streamed_tabular_ingest_writes_preflight(tabular_csv_fixture: tuple[Path, Path], tmp_path: Path) -> None:
    csv_path, yaml_path = tabular_csv_fixture
    out_dir = tmp_path / "streamed_session"
    result = runner.invoke(app, ["ingest", "tabular", str(csv_path), "--config", str(yaml_path), "--out", str(out_dir)])
    assert result.exit_code == 0, result.stdout
    payload = json.loads((out_dir / "ingest_summary.json").read_text(encoding="utf-8"))
    assert payload["preflight"]["large_file_mode"] == "streamed_parquet"
    assert payload["rows"]["imu"] > 0
    assert (out_dir / "imu.parquet").exists()


def test_export_summary_includes_written_files_and_reason_coverage(synthetic_session, tmp_path: Path) -> None:
    cfg = load_defaults()
    session_dir = tmp_path / "session"
    synthetic_session.imu.loc[100:220, "t_ms"] += 600
    save_session(synthetic_session, session_dir)
    audit_result = run_audit(synthetic_session, cfg)
    export_dir = tmp_path / "export"
    result = export_session(
        synthetic_session,
        profile="qa_filtered",
        file_format="csv",
        out_dir=export_dir,
        config=cfg,
        audit_result=audit_result,
        threshold=0.95,
        reason_codes=["timing_bad"],
    )
    assert result.summary.written_files["imu"].endswith("imu.csv")
    assert result.summary.row_counts["imu"] == result.kept_rows
    assert result.summary.reason_code_coverage.requested_reason_codes == ["timing_bad"]


def test_cli_compare_can_fail_on_regression(tabular_csv_fixture: tuple[Path, Path], tmp_path: Path) -> None:
    csv_path, yaml_path = tabular_csv_fixture
    clean_dir = tmp_path / "clean"
    corrupt_dir = tmp_path / "corrupt"
    compare_path = tmp_path / "compare.html"
    runner.invoke(app, ["ingest", "tabular", str(csv_path), "--config", str(yaml_path), "--out", str(clean_dir)], catch_exceptions=False)
    runner.invoke(app, ["corrupt", str(clean_dir), "--preset", "packet_loss_5", "--out", str(corrupt_dir)], catch_exceptions=False)
    result = runner.invoke(
        app,
        [
            "compare",
            str(clean_dir),
            str(corrupt_dir),
            "--out",
            str(compare_path),
            "--summary-format",
            "json",
            "--fail-on",
            "regression",
            "--trust-drop-threshold",
            "0.01",
        ],
    )
    assert result.exit_code == 1
    assert '"artifact_schema_version": "0.4"' in result.stdout


def test_batch_validate_trustscore_writes_summary(tmp_path: Path, synthetic_session) -> None:
    session_dir = tmp_path / "sessions" / "a"
    save_session(synthetic_session, session_dir)
    out_dir = tmp_path / "trustscore_batch"
    result = runner.invoke(app, ["batch", "validate-trustscore", str(tmp_path / "sessions"), "--out", str(out_dir)])
    assert result.exit_code == 0, result.stdout
    assert (out_dir / "trustscore_validation_summary.json").exists()


def test_action_runner_smoke(tabular_csv_fixture: tuple[Path, Path], tmp_path: Path) -> None:
    csv_path, yaml_path = tabular_csv_fixture
    report_dir = tmp_path / "action_report"
    env = os.environ.copy()
    env.pop("GITHUB_OUTPUT", None)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_github_action.py",
            "--data-glob",
            str(csv_path),
            "--tabular-config",
            str(yaml_path),
            "--report-dir",
            str(report_dir),
            "--comment-mode",
            "summary",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (report_dir / "action_summary.json").exists()
