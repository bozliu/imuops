from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from imuops.cli import app

runner = CliRunner()


def test_public_docs_are_repo_safe() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    public_paths = [
        repo_root / "README.md",
        *sorted((repo_root / "docs").glob("*.md")),
        *sorted((repo_root / "examples").glob("*.sh")),
    ]
    for path in public_paths:
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text, path
        assert "app://" not in text, path
    assert "conda activate dl" not in (repo_root / "README.md").read_text(encoding="utf-8")


def test_bundled_sample_quickstart_runs(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    csv_path = repo_root / "examples" / "sample_tabular_imu.csv"
    yaml_path = repo_root / "examples" / "sample_tabular_config.yaml"
    session_dir = tmp_path / "sample_session"

    result = runner.invoke(app, ["ingest", "tabular", str(csv_path), "--config", str(yaml_path), "--out", str(session_dir)])
    assert result.exit_code == 0, result.stdout

    result = runner.invoke(app, ["audit", str(session_dir), "--summary-format", "markdown"])
    assert result.exit_code == 0, result.stdout
    assert "| field | value |" in result.stdout

    report_path = session_dir / "report.html"
    result = runner.invoke(app, ["report", str(session_dir), "--out", str(report_path)])
    assert result.exit_code == 0, result.stdout
    assert report_path.exists()


def test_compare_report_surfaces_recommendation(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    csv_path = repo_root / "examples" / "sample_tabular_imu.csv"
    yaml_path = repo_root / "examples" / "sample_tabular_config.yaml"
    clean_dir = tmp_path / "clean"
    corrupt_dir = tmp_path / "corrupt"
    compare_path = tmp_path / "compare.html"

    result = runner.invoke(app, ["ingest", "tabular", str(csv_path), "--config", str(yaml_path), "--out", str(clean_dir)])
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["corrupt", str(clean_dir), "--preset", "packet_loss_5", "--out", str(corrupt_dir)])
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["compare", str(clean_dir), str(corrupt_dir), "--out", str(compare_path)])
    assert result.exit_code == 0, result.stdout
    html = compare_path.read_text(encoding="utf-8")
    assert "Recommendation:" in html
    assert "Metadata differences" in html
