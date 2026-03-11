from __future__ import annotations

from imuops.audit import run_audit
from imuops.config import load_defaults


def test_audit_detects_quality_regressions(synthetic_session) -> None:
    session = synthetic_session
    session.imu.loc[100:120, "t_ms"] += 300
    session.imu.loc[300:340, "gx"] = session.metadata.extra["full_scale"]["gyro_rads"]
    session.imu.loc[500:560, ["mx", "my", "mz"]] *= 8.0
    session.imu.loc[700:760, ["ax", "ay", "az", "gx", "gy", "gz"]] = 0.0
    result = run_audit(session, load_defaults())
    assert result.summary.trust_score < 1.0
    assert "timing_bad" in result.summary.reason_codes
    assert "clipping" in result.summary.reason_codes
    assert result.summary.trustscore_version == "v0.3.0"
    assert result.summary.window_formula
    assert result.summary.session_formula
    assert "clipping" in result.summary.penalty_totals
