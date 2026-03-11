from __future__ import annotations

from pathlib import Path

from imuops.audit import run_audit
from imuops.benchmark import run_benchmark, save_benchmark
from imuops.config import load_defaults
from imuops.reporting import build_report
from imuops.replay import run_replay, save_replay
from imuops.session import save_session


def test_report_contains_expected_sections(synthetic_session, tmp_path: Path) -> None:
    cfg = load_defaults()
    session_dir = tmp_path / "session"
    save_session(synthetic_session, session_dir)
    audit_result = run_audit(synthetic_session, cfg)
    (session_dir / "issues.json").write_text(__import__("json").dumps(audit_result.to_dict()), encoding="utf-8")
    replay = run_replay(synthetic_session, "pdr", cfg)
    save_replay(replay, session_dir)
    benchmark = run_benchmark(synthetic_session, "pdr", cfg)
    save_benchmark(benchmark, session_dir)
    out = tmp_path / "report.html"
    build_report(synthetic_session, audit_result, [replay], out)
    html = out.read_text(encoding="utf-8")
    assert "imuops report" in html
    assert "Benchmark Summary" in html
    assert "Reliability Summary" in html
    assert "Window formula" in html
