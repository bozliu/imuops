from __future__ import annotations

from imuops.config import load_defaults
from imuops.replay import run_replay


def test_replay_baselines_run(synthetic_session) -> None:
    cfg = load_defaults()
    madgwick = run_replay(synthetic_session, "madgwick", cfg)
    mahony = run_replay(synthetic_session, "mahony", cfg)
    pdr = run_replay(synthetic_session, "pdr", cfg)
    assert len(madgwick.frame) == len(synthetic_session.imu)
    assert "path_smoothness" in mahony.metrics
    assert "step_count" in pdr.metrics
    assert pdr.summary.task == "pdr"

