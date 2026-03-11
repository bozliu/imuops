from __future__ import annotations

import json
from pathlib import Path

import pytest

from imuops.audit import run_audit
from imuops.batch import batch_audit_sessions, build_batch_report
from imuops.benchmark import run_benchmark, save_benchmark
from imuops.compare import build_compare_report
from imuops.config import load_defaults
from imuops.corruption import corrupt_session, save_corrupted_session
from imuops.exporting import export_session
from imuops.replay import run_replay, save_replay
from imuops.session import load_session, save_session
from imuops.validation import run_trustscore_validation


def test_export_qa_filtered_removes_low_trust_rows(synthetic_session, tmp_path: Path) -> None:
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
    )
    assert result.removed_rows > 0
    assert (export_dir / "imu.csv").exists()


def test_compare_report_contains_delta_outputs(synthetic_session, tmp_path: Path) -> None:
    cfg = load_defaults()
    clean_dir = tmp_path / "clean"
    save_session(synthetic_session, clean_dir)
    clean_session = load_session(clean_dir)
    clean_audit = run_audit(clean_session, cfg)
    (clean_dir / "issues.json").write_text(json.dumps(clean_audit.to_dict()), encoding="utf-8")
    clean_replay = run_replay(clean_session, "pdr", cfg)
    save_replay(clean_replay, clean_dir)
    clean_benchmark = run_benchmark(clean_session, "pdr", cfg)
    save_benchmark(clean_benchmark, clean_dir)

    corrupted_bundle, corruption_summary = corrupt_session(clean_session, "packet_loss_5", cfg)
    corrupt_dir = tmp_path / "corrupt"
    save_corrupted_session(corrupted_bundle, corruption_summary, corrupt_dir)
    corrupt_session_bundle = load_session(corrupt_dir)
    corrupt_audit = run_audit(corrupt_session_bundle, cfg)
    (corrupt_dir / "issues.json").write_text(json.dumps(corrupt_audit.to_dict()), encoding="utf-8")
    corrupt_replay = run_replay(corrupt_session_bundle, "pdr", cfg)
    save_replay(corrupt_replay, corrupt_dir)
    corrupt_benchmark = run_benchmark(corrupt_session_bundle, "pdr", cfg)
    save_benchmark(corrupt_benchmark, corrupt_dir)

    out = tmp_path / "compare.html"
    result = build_compare_report(clean_session, corrupt_session_bundle, config=cfg, out_path=out)
    assert out.exists()
    assert "trust_score_delta" in json.dumps(result.summary.model_dump())
    assert result.summary.recommendation_status in {"improved", "regressed", "mixed"}
    assert result.summary.metadata_differences


def test_batch_audit_and_report(tmp_path: Path, synthetic_session) -> None:
    cfg = load_defaults()
    session_a_dir = tmp_path / "sessions" / "a"
    session_b_dir = tmp_path / "sessions" / "b"
    save_session(synthetic_session, session_a_dir)
    worse = load_session(session_a_dir)
    worse.imu.loc[50:120, "t_ms"] += 400
    save_session(worse, session_b_dir)
    batch_dir = tmp_path / "batch_artifacts"
    batch_result = batch_audit_sessions(tmp_path / "sessions", batch_dir, cfg)
    assert batch_result.summary.session_count == 2
    assert batch_result.summary.rows[0].trust_score <= batch_result.summary.rows[1].trust_score
    assert batch_result.summary.rows[0].rank == 1
    assert (batch_dir / "batch_summary.json").exists()
    assert (batch_dir / "batch_audit_summary.json").exists()
    assert (batch_dir / "batch_rankings.csv").exists()
    report_path = tmp_path / "batch_report.html"
    build_batch_report(batch_result, report_path)
    assert report_path.exists()
    html = report_path.read_text(encoding="utf-8")
    assert "Best and worst sessions" in html


def test_trustscore_validation_records_non_improving_packet_loss(synthetic_session) -> None:
    result = run_trustscore_validation(synthetic_session, load_defaults())
    presets = {item.preset: item for item in result.summary.presets}
    assert "packet_loss_5" in presets
    assert presets["packet_loss_5"].trust_score_delta <= 0.0


def test_replay_and_benchmark_row_limits_are_enforced(synthetic_session) -> None:
    cfg = load_defaults()
    cfg["limits"]["replay_max_rows"] = 100
    cfg["limits"]["benchmark_max_rows"] = 100
    with pytest.raises(ValueError, match="replay row limit exceeded"):
        run_replay(synthetic_session, "pdr", cfg)
    with pytest.raises(ValueError, match="benchmark row limit exceeded"):
        run_benchmark(synthetic_session, "pdr", cfg)
