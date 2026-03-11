from __future__ import annotations

from imuops.audit import run_audit
from imuops.config import load_defaults
from imuops.corruption import corrupt_session


def test_corruption_presets_modify_session_and_degrade_quality(synthetic_session) -> None:
    cfg = load_defaults()
    clean = run_audit(synthetic_session, cfg)
    corrupted, summary = corrupt_session(synthetic_session, "packet_loss_5", cfg)
    dirty = run_audit(corrupted, cfg)
    assert summary.preset == "packet_loss_5"
    assert dirty.summary.trust_score <= clean.summary.trust_score
    assert dirty.summary.dropout_ratio >= clean.summary.dropout_ratio
