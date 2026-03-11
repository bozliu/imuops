"""Trust-score validation against corruption presets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from imuops.audit import run_audit
from imuops.benchmark import run_benchmark
from imuops.corruption import corrupt_session
from imuops.models import (
    MetricCorrelationModel,
    TrustScoreValidationSummaryModel,
    ValidationCleanModel,
    ValidationPresetModel,
)
from imuops.replay import run_replay
from imuops.session import SessionBundle
from imuops.utils import dump_json


@dataclass
class TrustScoreValidationResult:
    summary: TrustScoreValidationSummaryModel


def run_trustscore_validation(session: SessionBundle, config: dict[str, Any]) -> TrustScoreValidationResult:
    clean_audit = run_audit(session, config)
    presets: list[ValidationPresetModel] = []
    clean_replay_metrics = _baseline_metrics(session, config)
    for preset in ("packet_loss_5", "timestamp_jitter_3ms", "axis_flip_x", "gyro_bias_small", "mag_bias_30ut"):
        corrupted, _ = corrupt_session(session, preset, config)
        audit_result = run_audit(corrupted, config)
        metrics = _baseline_metrics(corrupted, config)
        presets.append(
            ValidationPresetModel(
                preset=preset,
                trust_score=audit_result.summary.trust_score,
                trust_score_delta=audit_result.summary.trust_score - clean_audit.summary.trust_score,
                non_improving=audit_result.summary.trust_score <= clean_audit.summary.trust_score + 1e-9,
                baseline_metric_deltas=_metric_delta(clean_replay_metrics, metrics),
            )
        )
    summary = TrustScoreValidationSummaryModel(
        session_id=session.metadata.session_id,
        task=session.metadata.task,
        clean=ValidationCleanModel(
            trust_score=clean_audit.summary.trust_score,
            status=clean_audit.summary.status,
        ),
        presets=presets,
        all_non_improving=all(item.non_improving for item in presets),
        metric_correlation_rows=_metric_correlation_rows(presets),
        known_limitations=_known_limitations(presets),
    )
    return TrustScoreValidationResult(summary=summary)


def save_trustscore_validation(result: TrustScoreValidationResult, out_path: Path) -> None:
    dump_json(out_path, result.summary)


def _baseline_metrics(session: SessionBundle, config: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if session.metadata.task in {"orientation", "pdr"}:
        replay_baseline = "pdr" if session.metadata.task == "pdr" else "madgwick"
        replay_result = run_replay(session, replay_baseline, config)
        metrics.update(_flatten_numeric_metrics(replay_result.metrics, prefix=f"replay_{replay_baseline}_"))
    try:
        benchmark_result = run_benchmark(session, session.metadata.task, config)
    except Exception:
        return metrics
    for baseline in benchmark_result.summary.baselines:
        metrics.update(_flatten_numeric_metrics(baseline.metrics, prefix=f"benchmark_{baseline.baseline}_"))
    return metrics


def _flatten_numeric_metrics(metrics: dict[str, Any], *, prefix: str) -> dict[str, float]:
    return {f"{prefix}{key}": float(value) for key, value in metrics.items() if isinstance(value, (int, float))}


def _metric_delta(base: dict[str, float], other: dict[str, float]) -> dict[str, float]:
    return {key: other[key] - base[key] for key in sorted(set(base) & set(other))}


def _metric_correlation_rows(presets: list[ValidationPresetModel]) -> list[MetricCorrelationModel]:
    by_metric: dict[str, list[float]] = {}
    for preset in presets:
        for metric, delta in preset.baseline_metric_deltas.items():
            by_metric.setdefault(metric, []).append(delta)
    rows = []
    for metric, values in sorted(by_metric.items()):
        rows.append(
            MetricCorrelationModel(
                metric=metric,
                preset_count=len(values),
                average_delta=float(sum(values) / len(values)),
                max_delta=float(max(values)),
                min_delta=float(min(values)),
            )
        )
    return rows


def _known_limitations(presets: list[ValidationPresetModel]) -> list[str]:
    limitations = []
    for preset in presets:
        if preset.non_improving and abs(preset.trust_score_delta) < 1e-6:
            limitations.append(f"{preset.preset} did not improve trust_score, but the delta was effectively zero.")
        if not preset.baseline_metric_deltas:
            limitations.append(f"{preset.preset} had no replay or benchmark metric deltas for correlation.")
    return limitations
