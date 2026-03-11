"""Versioned QA and reliability scoring for canonical IMU sessions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from imuops.models import AuditSummaryModel, IssueModel, WindowScoreModel
from imuops.session import SessionBundle
from imuops.utils import load_json, merge_asof_series, sampling_stats

G = 9.80665
TAXONOMY = [
    "timing_bad",
    "dropout",
    "clipping",
    "gyro_bias_drift",
    "mag_disturbed",
    "gps_unreliable",
    "insufficient_static_segment",
    "pressure_unstable",
    "orientation_inconsistent",
]


@dataclass
class AuditResult:
    session_id: str
    summary: AuditSummaryModel
    issues: list[IssueModel]
    windows: list[WindowScoreModel]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "summary": self.summary.model_dump(),
            "issues": [issue.model_dump() for issue in self.issues],
            "windows": [window.model_dump() for window in self.windows],
        }

    @classmethod
    def from_dict(cls, config: dict[str, Any], session: SessionBundle, path: Path) -> "AuditResult":
        payload = load_json(path)
        issues = [IssueModel.model_validate(item) for item in payload.get("issues", [])]
        windows = [WindowScoreModel.model_validate(item) for item in payload.get("windows", [])]
        summary = AuditSummaryModel.model_validate(payload["summary"])
        return cls(session_id=payload["session_id"], summary=summary, issues=issues, windows=windows)


def run_audit(session: SessionBundle, config: dict[str, Any]) -> AuditResult:
    if session.imu.empty and session.artifacts.get("imu_path"):
        return _run_audit_streaming(session, config)
    return _run_audit_in_memory(session, config)


def _run_audit_in_memory(session: SessionBundle, config: dict[str, Any]) -> AuditResult:
    audit_cfg = config["audit"]
    weights = audit_cfg["weights"]
    imu = session.imu
    if imu.empty and session.artifacts.get("imu_path"):
        imu = pd.read_parquet(session.artifacts["imu_path"])
    imu = imu.sort_values("t_ms").reset_index(drop=True)
    stats = sampling_stats(imu["t_ms"])
    dt = np.diff(imu["t_ms"].to_numpy(dtype=float)) if len(imu) > 1 else np.array([])
    median_dt = max(stats["median_dt_ms"], 1.0)
    acc_norm = np.linalg.norm(imu[["ax", "ay", "az"]].to_numpy(dtype=float), axis=1)
    gyro_norm = np.linalg.norm(imu[["gx", "gy", "gz"]].to_numpy(dtype=float), axis=1)
    mag_norm = _safe_norm(imu[["mx", "my", "mz"]])
    pressure = imu["pressure_pa"].to_numpy(dtype=float)
    gps_valid_ratio = float(session.gps["valid"].mean()) if not session.gps.empty else 0.0
    gps_alignment_ratio = _gps_alignment_ratio(session)
    full_scale = session.metadata.extra.get("full_scale", {})
    clipping_ratio = _clipping_ratio(imu, full_scale)
    dropout_ratio = float(np.mean(dt > median_dt * audit_cfg["missing_gap_factor"])) if dt.size else 0.0
    freeze_zero_ratio = _freeze_zero_ratio(imu)

    windows: list[WindowScoreModel] = []
    penalty_totals = {name: 0.0 for name in TAXONOMY}
    static_means: list[np.ndarray] = []
    static_window_count = 0

    for start_idx, end_idx in _iter_windows(imu["t_ms"].to_numpy(dtype=int), audit_cfg["window_ms"], audit_cfg["step_ms"]):
        chunk = imu.iloc[start_idx:end_idx]
        if len(chunk) < 2:
            continue
        chunk_stats = sampling_stats(chunk["t_ms"])
        chunk_dt = np.diff(chunk["t_ms"].to_numpy(dtype=float))
        start_ms = int(chunk["t_ms"].iloc[0])
        end_ms = int(chunk["t_ms"].iloc[-1])
        missing_ratio = float(np.mean(chunk_dt > median_dt * audit_cfg["missing_gap_factor"])) if chunk_dt.size else 0.0
        freeze_ratio = _freeze_zero_ratio(chunk)
        chunk_acc_norm = acc_norm[start_idx:end_idx]
        chunk_gyro_norm = gyro_norm[start_idx:end_idx]
        chunk_mag_norm = mag_norm[start_idx:end_idx]
        gravity_residual = float(np.nanmedian(np.abs(chunk_acc_norm - G)))
        gyro_std = float(np.std(chunk_gyro_norm))
        acc_std = float(np.std(chunk_acc_norm))
        mag_cv = float(np.std(chunk_mag_norm) / np.mean(chunk_mag_norm)) if np.isfinite(chunk_mag_norm).sum() > 3 and np.nanmean(chunk_mag_norm) > 0 else 0.0
        chunk_clipping = _clipping_ratio(chunk, full_scale)
        chunk_pressure_delta = float(np.nanmax(pressure[start_idx:end_idx]) - np.nanmin(pressure[start_idx:end_idx])) if np.isfinite(pressure[start_idx:end_idx]).any() else 0.0
        chunk_pressure_std = float(np.nanstd(pressure[start_idx:end_idx])) if np.isfinite(pressure[start_idx:end_idx]).any() else 0.0
        penalties: dict[str, float] = {}
        reason_codes: list[str] = []

        if chunk_stats["jitter_ms"] >= audit_cfg["jitter_warn_ms"]:
            penalties["timing_bad"] = weights["timing_bad"] * min(1.0, chunk_stats["jitter_ms"] / max(audit_cfg["jitter_fail_ms"], 1e-6))
        if missing_ratio >= audit_cfg["dropout_ratio_warn"] or freeze_ratio >= audit_cfg["freeze_zero_ratio_warn"]:
            penalties["dropout"] = weights["dropout"] * min(1.0, max(missing_ratio, freeze_ratio) / max(audit_cfg["dropout_ratio_warn"], 1e-6))
        if chunk_clipping >= audit_cfg["clipping_warn_ratio"]:
            penalties["clipping"] = weights["clipping"] * min(1.0, chunk_clipping / max(audit_cfg["clipping_warn_ratio"], 1e-6))
        if mag_cv >= audit_cfg["mag_disturbance_cv_warn"]:
            penalties["mag_disturbed"] = weights["mag_disturbed"] * min(1.0, mag_cv / max(audit_cfg["mag_disturbance_cv_warn"], 1e-6))
        if session.metadata.sensors.get("gps") and gps_valid_ratio < audit_cfg["gps_valid_ratio_warn"]:
            penalties["gps_unreliable"] = weights["gps_unreliable"] * min(1.0, (audit_cfg["gps_valid_ratio_warn"] - gps_valid_ratio) / max(audit_cfg["gps_valid_ratio_warn"], 1e-6))
        is_static = acc_std <= audit_cfg["static_acc_std_mps2"] and gyro_std <= audit_cfg["static_gyro_std_rads"]
        if is_static:
            static_window_count += 1
            static_means.append(chunk[["gx", "gy", "gz"]].mean().to_numpy(dtype=float))
            if gravity_residual >= audit_cfg["gravity_residual_warn_mps2"]:
                penalties["orientation_inconsistent"] = weights["orientation_inconsistent"] * min(
                    1.0, gravity_residual / max(audit_cfg["gravity_residual_warn_mps2"], 1e-6)
                )
            if chunk_pressure_std >= audit_cfg["pressure_unstable_pa"]:
                penalties["pressure_unstable"] = weights["pressure_unstable"] * min(
                    1.0, chunk_pressure_std / max(audit_cfg["pressure_unstable_pa"], 1e-6)
                )
        elif chunk_pressure_delta >= audit_cfg["pressure_floor_change_pa"]:
            penalties["pressure_unstable"] = weights["pressure_unstable"] * 0.5

        for key, value in penalties.items():
            if value > 0:
                penalty_totals[key] += float(value)
                reason_codes.append(key)
        trust_score = max(0.0, 1.0 - sum(penalties.values()))
        windows.append(
            WindowScoreModel(
                start_ms=start_ms,
                end_ms=end_ms,
                trust_score=trust_score,
                reason_codes=sorted(set(reason_codes)),
                penalties={key: round(value, 6) for key, value in penalties.items()},
                metrics={
                    "jitter_ms": chunk_stats["jitter_ms"],
                    "missing_ratio": missing_ratio,
                    "freeze_ratio": freeze_ratio,
                    "clipping_ratio": chunk_clipping,
                    "acc_std": acc_std,
                    "gyro_std": gyro_std,
                    "gravity_residual": gravity_residual,
                    "mag_cv": mag_cv,
                    "pressure_delta": chunk_pressure_delta,
                    "pressure_std": chunk_pressure_std,
                },
            )
        )

    issues: list[IssueModel] = []
    for window in windows:
        severity = "fail" if window.trust_score < audit_cfg["fail_threshold"] else "warning" if window.reason_codes else "info"
        for code in window.reason_codes:
            issues.append(
                IssueModel(
                    code=code,
                    severity=severity,
                    message=f"{code.replace('_', ' ')} detected",
                    start_ms=window.start_ms,
                    end_ms=window.end_ms,
                    metrics=window.metrics,
                )
            )

    gyro_bias_drift = 0.0
    if len(static_means) >= 2:
        base = static_means[0]
        gyro_bias_drift = max(float(np.linalg.norm(mean - base)) for mean in static_means[1:])
        if gyro_bias_drift >= audit_cfg["bias_drift_warn_rads"]:
            penalty = weights["gyro_bias_drift"] * min(1.0, gyro_bias_drift / max(audit_cfg["bias_drift_warn_rads"], 1e-6))
            penalty_totals["gyro_bias_drift"] += penalty
            issues.append(
                IssueModel(
                    code="gyro_bias_drift",
                    severity="warning",
                    message="Static-window gyro bias drift exceeded threshold.",
                    metrics={"gyro_bias_drift_rads": gyro_bias_drift},
                )
            )

    static_window_ratio = float(static_window_count / len(windows)) if windows else 0.0
    if static_window_ratio < audit_cfg["static_window_ratio_warn"]:
        penalty = weights["insufficient_static_segment"] * min(
            1.0, (audit_cfg["static_window_ratio_warn"] - static_window_ratio) / max(audit_cfg["static_window_ratio_warn"], 1e-6)
        )
        penalty_totals["insufficient_static_segment"] += penalty
        issues.append(
            IssueModel(
                code="insufficient_static_segment",
                severity="warning",
                message="Too few static windows were available for stable calibration checks.",
                metrics={"static_window_ratio": static_window_ratio},
            )
        )

    if session.metadata.sensors.get("gps") and gps_alignment_ratio is not None and (
        gps_alignment_ratio < audit_cfg["gps_alignment_ratio_low"] or gps_alignment_ratio > audit_cfg["gps_alignment_ratio_high"]
    ):
        issues.append(
            IssueModel(
                code="gps_unreliable",
                severity="warning",
                message="GPS span does not line up well with IMU duration.",
                metrics={"gps_alignment_ratio": gps_alignment_ratio},
            )
        )
        penalty_totals["gps_unreliable"] += weights["gps_unreliable"] * 0.5

    issue_codes = sorted({issue.code for issue in issues if issue.code in TAXONOMY})
    window_mean = float(np.mean([window.trust_score for window in windows])) if windows else 1.0
    total_penalty = float(sum(penalty_totals.values()))
    trust_score = max(0.0, min(1.0, window_mean - total_penalty / max(len(windows), 1)))
    summary = AuditSummaryModel(
        dataset=session.metadata.dataset,
        session_id=session.metadata.session_id,
        task=session.metadata.task,
        duration_s=stats["duration_s"],
        nominal_hz=stats["nominal_hz"],
        jitter_ms=stats["jitter_ms"],
        trust_score=trust_score,
        trustscore_version=audit_cfg["trustscore_version"],
        status=_status_from_score(trust_score, audit_cfg["warning_threshold"], audit_cfg["fail_threshold"]),
        warning_threshold=audit_cfg["warning_threshold"],
        fail_threshold=audit_cfg["fail_threshold"],
        window_formula=audit_cfg.get("window_formula"),
        session_formula=audit_cfg.get("session_formula"),
        missing_gap_count=int(np.sum(dt > median_dt * audit_cfg["missing_gap_factor"])) if dt.size else 0,
        gps_valid_ratio=gps_valid_ratio if not session.gps.empty else None,
        gps_alignment_ratio=gps_alignment_ratio,
        clipping_ratio=clipping_ratio,
        dropout_ratio=max(dropout_ratio, freeze_zero_ratio),
        gyro_bias_drift_rads=gyro_bias_drift,
        pressure_stability_pa=float(np.nanstd(pressure)) if np.isfinite(pressure).any() else None,
        static_window_ratio=static_window_ratio,
        reason_codes=issue_codes,
        penalty_totals={key: round(value, 6) for key, value in penalty_totals.items() if value > 0},
        weight_profile={key: float(value) for key, value in weights.items()},
        thresholds={
            "warning_threshold": audit_cfg["warning_threshold"],
            "fail_threshold": audit_cfg["fail_threshold"],
            "jitter_warn_ms": audit_cfg["jitter_warn_ms"],
            "dropout_ratio_warn": audit_cfg["dropout_ratio_warn"],
            "clipping_warn_ratio": audit_cfg["clipping_warn_ratio"],
            "gravity_residual_warn_mps2": audit_cfg["gravity_residual_warn_mps2"],
        },
        window_count=len(windows),
        available_sensors=dict(session.metadata.sensors),
        skipped_checks=_skipped_checks(session),
    )
    return AuditResult(session_id=session.metadata.session_id, summary=summary, issues=issues, windows=windows)


def _iter_windows(t_ms: np.ndarray, window_ms: int, step_ms: int):
    if len(t_ms) == 0:
        return
    start = int(t_ms[0])
    end = int(t_ms[-1])
    current = start
    while current <= end:
        next_stop = current + window_ms
        start_idx = int(np.searchsorted(t_ms, current, side="left"))
        end_idx = int(np.searchsorted(t_ms, next_stop, side="right"))
        if end_idx - start_idx > 1:
            yield start_idx, end_idx
        current += step_ms


def _run_audit_streaming(session: SessionBundle, config: dict[str, Any]) -> AuditResult:
    audit_cfg = config["audit"]
    weights = audit_cfg["weights"]
    imu_path = Path(session.artifacts["imu_path"])
    scan = _scan_parquet_time_stats(imu_path, batch_size=int(audit_cfg.get("chunk_rows", 50_000)))
    if scan["row_count"] <= 1:
        return _run_audit_in_memory(session, config)

    median_dt = max(scan["median_dt_ms"], 1.0)
    full_scale = session.metadata.extra.get("full_scale", {})
    gps_valid_ratio = float(session.gps["valid"].mean()) if not session.gps.empty else 0.0
    imu_span = float(scan["last_t_ms"] - scan["first_t_ms"])
    gps_span = float(session.gps["t_ms"].max() - session.gps["t_ms"].min()) if len(session.gps) > 1 else None
    gps_alignment_ratio = gps_span / imu_span if gps_span is not None and imu_span > 0 else None

    windows: list[WindowScoreModel] = []
    penalty_totals = {name: 0.0 for name in TAXONOMY}
    static_means: list[np.ndarray] = []
    static_window_count = 0
    pressure_stats = _WelfordStats()
    clip_counts = {"acc_mps2": 0, "gyro_rads": 0, "mag_uT": 0}
    repeat_count = 0
    zero_count = 0
    missing_gap_count = 0
    dt_count = 0
    last_t_ms: int | None = None
    last_sensor_row: np.ndarray | None = None

    buffer = pd.DataFrame(columns=session.imu.columns if not session.imu.empty else None)
    current_start = int(scan["first_t_ms"])
    current_end = current_start + int(audit_cfg["window_ms"])

    for chunk in _iter_parquet_frames(imu_path, batch_size=int(audit_cfg.get("chunk_rows", 50_000))):
        if chunk.empty:
            continue
        chunk = chunk.sort_values("t_ms").reset_index(drop=True)
        _observe_global_counts(
            chunk,
            pressure_stats=pressure_stats,
            clip_counts=clip_counts,
            full_scale=full_scale,
            median_dt=median_dt,
            missing_gap_factor=float(audit_cfg["missing_gap_factor"]),
            state={
                "repeat_count": repeat_count,
                "zero_count": zero_count,
                "missing_gap_count": missing_gap_count,
                "dt_count": dt_count,
                "last_t_ms": last_t_ms,
                "last_sensor_row": last_sensor_row,
            },
        )
        repeat_count = int(chunk.attrs["repeat_count"])
        zero_count = int(chunk.attrs["zero_count"])
        missing_gap_count = int(chunk.attrs["missing_gap_count"])
        dt_count = int(chunk.attrs["dt_count"])
        last_t_ms = int(chunk.attrs["last_t_ms"]) if chunk.attrs.get("last_t_ms") is not None else None
        last_sensor_row = chunk.attrs.get("last_sensor_row")
        buffer = pd.concat([buffer, chunk], ignore_index=True)
        while not buffer.empty and int(buffer["t_ms"].iloc[-1]) >= current_end:
            window = buffer[buffer["t_ms"].between(current_start, current_end)]
            if len(window) > 1:
                _append_window(
                    windows,
                    penalty_totals,
                    static_means,
                    session,
                    window,
                    audit_cfg,
                    weights,
                    gps_valid_ratio=gps_valid_ratio,
                    full_scale=full_scale,
                )
                if _is_static_window(window, audit_cfg):
                    static_window_count += 1
            current_start += int(audit_cfg["step_ms"])
            current_end = current_start + int(audit_cfg["window_ms"])
            buffer = buffer.loc[buffer["t_ms"] >= current_start].reset_index(drop=True)

    while not buffer.empty and current_start <= int(scan["last_t_ms"]):
        window = buffer[buffer["t_ms"].between(current_start, current_end)]
        if len(window) > 1:
            _append_window(
                windows,
                penalty_totals,
                static_means,
                session,
                window,
                audit_cfg,
                weights,
                gps_valid_ratio=gps_valid_ratio,
                full_scale=full_scale,
            )
            if _is_static_window(window, audit_cfg):
                static_window_count += 1
        current_start += int(audit_cfg["step_ms"])
        current_end = current_start + int(audit_cfg["window_ms"])
        buffer = buffer.loc[buffer["t_ms"] >= current_start].reset_index(drop=True)

    return _finalize_audit_summary(
        session,
        audit_cfg=audit_cfg,
        stats={
            "duration_s": scan["duration_s"],
            "median_dt_ms": scan["median_dt_ms"],
            "mean_dt_ms": scan["mean_dt_ms"],
            "nominal_hz": scan["nominal_hz"],
            "jitter_ms": scan["jitter_ms"],
        },
        windows=windows,
        penalty_totals=penalty_totals,
        static_means=static_means,
        static_window_count=static_window_count,
        gps_valid_ratio=gps_valid_ratio,
        gps_alignment_ratio=gps_alignment_ratio,
        clipping_ratio=_clip_ratio_from_counts(clip_counts, scan["row_count"]),
        dropout_ratio=float(missing_gap_count / max(dt_count, 1)),
        freeze_ratio=float(max(repeat_count / max(dt_count, 1), zero_count / max(scan["row_count"], 1))),
        pressure_stability_pa=pressure_stats.stddev if pressure_stats.count else None,
        missing_gap_count=missing_gap_count,
    )


def _scan_parquet_time_stats(path: Path, *, batch_size: int) -> dict[str, float]:
    sample_values: list[float] = []
    max_samples = 200_000
    count = 0
    last_t_ms: float | None = None
    first_t_ms: float | None = None
    dt_count = 0
    dt_mean = 0.0
    dt_m2 = 0.0
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=batch_size, columns=["t_ms"]):
        frame = batch.to_pandas()
        if frame.empty:
            continue
        t_ms = frame["t_ms"].to_numpy(dtype=float)
        if first_t_ms is None:
            first_t_ms = float(t_ms[0])
        if last_t_ms is not None:
            dt = np.concatenate([[t_ms[0] - last_t_ms], np.diff(t_ms)])
        else:
            dt = np.diff(t_ms)
        for value in dt:
            if value <= 0:
                continue
            dt_count += 1
            delta = value - dt_mean
            dt_mean += delta / dt_count
            dt_m2 += delta * (value - dt_mean)
            sample_values.append(float(value))
        if len(sample_values) > max_samples:
            stride = int(np.ceil(len(sample_values) / max_samples))
            sample_values = sample_values[::stride][:max_samples]
        last_t_ms = float(t_ms[-1])
        count += len(t_ms)
    sample_array = np.asarray(sample_values, dtype=float) if sample_values else np.asarray([0.0], dtype=float)
    median_dt = float(np.median(sample_array)) if sample_array.size else 0.0
    return {
        "row_count": float(count),
        "first_t_ms": float(first_t_ms or 0.0),
        "last_t_ms": float(last_t_ms or 0.0),
        "duration_s": float(((last_t_ms or 0.0) - (first_t_ms or 0.0)) / 1000.0),
        "median_dt_ms": median_dt,
        "mean_dt_ms": float(dt_mean),
        "nominal_hz": float(1000.0 / median_dt) if median_dt > 0 else 0.0,
        "jitter_ms": float(np.sqrt(dt_m2 / max(dt_count, 1))) if dt_count else 0.0,
    }


def _iter_parquet_frames(path: Path, *, batch_size: int) -> pd.DataFrame:
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=batch_size):
        yield batch.to_pandas()


def _observe_global_counts(
    chunk: pd.DataFrame,
    *,
    pressure_stats: "_WelfordStats",
    clip_counts: dict[str, int],
    full_scale: dict[str, float],
    median_dt: float,
    missing_gap_factor: float,
    state: dict[str, Any],
) -> None:
    t_ms = chunk["t_ms"].to_numpy(dtype=float)
    if state["last_t_ms"] is not None and len(t_ms):
        dt = np.concatenate([[t_ms[0] - state["last_t_ms"]], np.diff(t_ms)])
    else:
        dt = np.diff(t_ms)
    state["missing_gap_count"] += int(np.sum(dt > median_dt * missing_gap_factor)) if dt.size else 0
    state["dt_count"] += int(len(dt))
    sensor_cols = ["ax", "ay", "az", "gx", "gy", "gz"]
    sensor_values = chunk[sensor_cols].to_numpy(dtype=float)
    if state["last_sensor_row"] is not None and len(sensor_values):
        repeat = np.all(np.isclose(sensor_values[0], state["last_sensor_row"], atol=1e-12))
        state["repeat_count"] += int(repeat)
    if len(sensor_values) > 1:
        repeat = np.all(np.isclose(sensor_values[1:], sensor_values[:-1], atol=1e-12), axis=1)
        state["repeat_count"] += int(np.sum(repeat))
    state["zero_count"] += int(np.sum(np.all(np.isclose(sensor_values, 0.0, atol=1e-12), axis=1)))
    for key, columns in {
        "acc_mps2": ["ax", "ay", "az"],
        "gyro_rads": ["gx", "gy", "gz"],
        "mag_uT": ["mx", "my", "mz"],
    }.items():
        limit = full_scale.get(key)
        if not limit:
            continue
        values = chunk[columns].to_numpy(dtype=float)
        clip_counts[key] += int(np.sum(np.abs(values) >= 0.98 * limit))
    pressure = chunk["pressure_pa"].to_numpy(dtype=float)
    finite_pressure = pressure[np.isfinite(pressure)]
    for value in finite_pressure:
        pressure_stats.observe(float(value))
    state["last_t_ms"] = int(t_ms[-1]) if len(t_ms) else state["last_t_ms"]
    state["last_sensor_row"] = sensor_values[-1] if len(sensor_values) else state["last_sensor_row"]
    chunk.attrs.update(state)


def _append_window(
    windows: list[WindowScoreModel],
    penalty_totals: dict[str, float],
    static_means: list[np.ndarray],
    session: SessionBundle,
    chunk: pd.DataFrame,
    audit_cfg: dict[str, Any],
    weights: dict[str, float],
    *,
    gps_valid_ratio: float,
    full_scale: dict[str, float],
) -> None:
    chunk_stats = sampling_stats(chunk["t_ms"])
    chunk_dt = np.diff(chunk["t_ms"].to_numpy(dtype=float))
    start_ms = int(chunk["t_ms"].iloc[0])
    end_ms = int(chunk["t_ms"].iloc[-1])
    median_dt = max(chunk_stats["median_dt_ms"], 1.0)
    missing_ratio = float(np.mean(chunk_dt > median_dt * audit_cfg["missing_gap_factor"])) if chunk_dt.size else 0.0
    freeze_ratio = _freeze_zero_ratio(chunk)
    chunk_acc_norm = np.linalg.norm(chunk[["ax", "ay", "az"]].to_numpy(dtype=float), axis=1)
    chunk_gyro_norm = np.linalg.norm(chunk[["gx", "gy", "gz"]].to_numpy(dtype=float), axis=1)
    chunk_mag_norm = _safe_norm(chunk[["mx", "my", "mz"]])
    gravity_residual = float(np.nanmedian(np.abs(chunk_acc_norm - G)))
    gyro_std = float(np.std(chunk_gyro_norm))
    acc_std = float(np.std(chunk_acc_norm))
    mag_cv = float(np.std(chunk_mag_norm) / np.mean(chunk_mag_norm)) if np.isfinite(chunk_mag_norm).sum() > 3 and np.nanmean(chunk_mag_norm) > 0 else 0.0
    chunk_clipping = _clipping_ratio(chunk, full_scale)
    pressure = chunk["pressure_pa"].to_numpy(dtype=float)
    chunk_pressure_delta = float(np.nanmax(pressure) - np.nanmin(pressure)) if np.isfinite(pressure).any() else 0.0
    chunk_pressure_std = float(np.nanstd(pressure)) if np.isfinite(pressure).any() else 0.0
    penalties: dict[str, float] = {}
    reason_codes: list[str] = []

    if chunk_stats["jitter_ms"] >= audit_cfg["jitter_warn_ms"]:
        penalties["timing_bad"] = weights["timing_bad"] * min(1.0, chunk_stats["jitter_ms"] / max(audit_cfg["jitter_fail_ms"], 1e-6))
    if missing_ratio >= audit_cfg["dropout_ratio_warn"] or freeze_ratio >= audit_cfg["freeze_zero_ratio_warn"]:
        penalties["dropout"] = weights["dropout"] * min(1.0, max(missing_ratio, freeze_ratio) / max(audit_cfg["dropout_ratio_warn"], 1e-6))
    if chunk_clipping >= audit_cfg["clipping_warn_ratio"]:
        penalties["clipping"] = weights["clipping"] * min(1.0, chunk_clipping / max(audit_cfg["clipping_warn_ratio"], 1e-6))
    if session.metadata.sensors.get("mag") and mag_cv >= audit_cfg["mag_disturbance_cv_warn"]:
        penalties["mag_disturbed"] = weights["mag_disturbed"] * min(1.0, mag_cv / max(audit_cfg["mag_disturbance_cv_warn"], 1e-6))
    if session.metadata.sensors.get("gps") and gps_valid_ratio < audit_cfg["gps_valid_ratio_warn"]:
        penalties["gps_unreliable"] = weights["gps_unreliable"] * min(1.0, (audit_cfg["gps_valid_ratio_warn"] - gps_valid_ratio) / max(audit_cfg["gps_valid_ratio_warn"], 1e-6))
    is_static = acc_std <= audit_cfg["static_acc_std_mps2"] and gyro_std <= audit_cfg["static_gyro_std_rads"]
    if is_static:
        static_means.append(chunk[["gx", "gy", "gz"]].mean().to_numpy(dtype=float))
        if gravity_residual >= audit_cfg["gravity_residual_warn_mps2"]:
            penalties["orientation_inconsistent"] = weights["orientation_inconsistent"] * min(
                1.0, gravity_residual / max(audit_cfg["gravity_residual_warn_mps2"], 1e-6)
            )
        if session.metadata.sensors.get("pressure") and chunk_pressure_std >= audit_cfg["pressure_unstable_pa"]:
            penalties["pressure_unstable"] = weights["pressure_unstable"] * min(
                1.0, chunk_pressure_std / max(audit_cfg["pressure_unstable_pa"], 1e-6)
            )
    elif session.metadata.sensors.get("pressure") and chunk_pressure_delta >= audit_cfg["pressure_floor_change_pa"]:
        penalties["pressure_unstable"] = weights["pressure_unstable"] * 0.5

    for key, value in penalties.items():
        if value > 0:
            penalty_totals[key] += float(value)
            reason_codes.append(key)
    trust_score = max(0.0, 1.0 - sum(penalties.values()))
    windows.append(
        WindowScoreModel(
            start_ms=start_ms,
            end_ms=end_ms,
            trust_score=trust_score,
            reason_codes=sorted(set(reason_codes)),
            penalties={key: round(value, 6) for key, value in penalties.items()},
            metrics={
                "jitter_ms": chunk_stats["jitter_ms"],
                "missing_ratio": missing_ratio,
                "freeze_ratio": freeze_ratio,
                "clipping_ratio": chunk_clipping,
                "acc_std": acc_std,
                "gyro_std": gyro_std,
                "gravity_residual": gravity_residual,
                "mag_cv": mag_cv,
                "pressure_delta": chunk_pressure_delta,
                "pressure_std": chunk_pressure_std,
            },
        )
    )


def _is_static_window(chunk: pd.DataFrame, audit_cfg: dict[str, Any]) -> bool:
    chunk_acc_norm = np.linalg.norm(chunk[["ax", "ay", "az"]].to_numpy(dtype=float), axis=1)
    chunk_gyro_norm = np.linalg.norm(chunk[["gx", "gy", "gz"]].to_numpy(dtype=float), axis=1)
    return float(np.std(chunk_acc_norm)) <= audit_cfg["static_acc_std_mps2"] and float(np.std(chunk_gyro_norm)) <= audit_cfg["static_gyro_std_rads"]


def _finalize_audit_summary(
    session: SessionBundle,
    *,
    audit_cfg: dict[str, Any],
    stats: dict[str, float],
    windows: list[WindowScoreModel],
    penalty_totals: dict[str, float],
    static_means: list[np.ndarray],
    static_window_count: int,
    gps_valid_ratio: float,
    gps_alignment_ratio: float | None,
    clipping_ratio: float,
    dropout_ratio: float,
    freeze_ratio: float,
    pressure_stability_pa: float | None,
    missing_gap_count: int,
) -> AuditResult:
    weights = audit_cfg["weights"]
    issues: list[IssueModel] = []
    for window in windows:
        severity = "fail" if window.trust_score < audit_cfg["fail_threshold"] else "warning" if window.reason_codes else "info"
        for code in window.reason_codes:
            issues.append(
                IssueModel(
                    code=code,
                    severity=severity,
                    message=f"{code.replace('_', ' ')} detected",
                    start_ms=window.start_ms,
                    end_ms=window.end_ms,
                    metrics=window.metrics,
                )
            )

    gyro_bias_drift = 0.0
    if len(static_means) >= 2:
        base = static_means[0]
        gyro_bias_drift = max(float(np.linalg.norm(mean - base)) for mean in static_means[1:])
        if gyro_bias_drift >= audit_cfg["bias_drift_warn_rads"]:
            penalty = weights["gyro_bias_drift"] * min(1.0, gyro_bias_drift / max(audit_cfg["bias_drift_warn_rads"], 1e-6))
            penalty_totals["gyro_bias_drift"] += penalty
            issues.append(
                IssueModel(
                    code="gyro_bias_drift",
                    severity="warning",
                    message="Static-window gyro bias drift exceeded threshold.",
                    metrics={"gyro_bias_drift_rads": gyro_bias_drift},
                )
            )

    static_window_ratio = float(static_window_count / len(windows)) if windows else 0.0
    if static_window_ratio < audit_cfg["static_window_ratio_warn"]:
        penalty = weights["insufficient_static_segment"] * min(
            1.0, (audit_cfg["static_window_ratio_warn"] - static_window_ratio) / max(audit_cfg["static_window_ratio_warn"], 1e-6)
        )
        penalty_totals["insufficient_static_segment"] += penalty
        issues.append(
            IssueModel(
                code="insufficient_static_segment",
                severity="warning",
                message="Too few static windows were available for stable calibration checks.",
                metrics={"static_window_ratio": static_window_ratio},
            )
        )

    if session.metadata.sensors.get("gps") and gps_alignment_ratio is not None and (
        gps_alignment_ratio < audit_cfg["gps_alignment_ratio_low"] or gps_alignment_ratio > audit_cfg["gps_alignment_ratio_high"]
    ):
        issues.append(
            IssueModel(
                code="gps_unreliable",
                severity="warning",
                message="GPS span does not line up well with IMU duration.",
                metrics={"gps_alignment_ratio": gps_alignment_ratio},
            )
        )
        penalty_totals["gps_unreliable"] += weights["gps_unreliable"] * 0.5

    issue_codes = sorted({issue.code for issue in issues if issue.code in TAXONOMY})
    window_mean = float(np.mean([window.trust_score for window in windows])) if windows else 1.0
    total_penalty = float(sum(penalty_totals.values()))
    trust_score = max(0.0, min(1.0, window_mean - total_penalty / max(len(windows), 1)))
    summary = AuditSummaryModel(
        dataset=session.metadata.dataset,
        session_id=session.metadata.session_id,
        task=session.metadata.task,
        duration_s=stats["duration_s"],
        nominal_hz=stats["nominal_hz"],
        jitter_ms=stats["jitter_ms"],
        trust_score=trust_score,
        trustscore_version=audit_cfg["trustscore_version"],
        status=_status_from_score(trust_score, audit_cfg["warning_threshold"], audit_cfg["fail_threshold"]),
        warning_threshold=audit_cfg["warning_threshold"],
        fail_threshold=audit_cfg["fail_threshold"],
        window_formula=audit_cfg.get("window_formula"),
        session_formula=audit_cfg.get("session_formula"),
        missing_gap_count=missing_gap_count,
        gps_valid_ratio=gps_valid_ratio if not session.gps.empty else None,
        gps_alignment_ratio=gps_alignment_ratio,
        clipping_ratio=clipping_ratio,
        dropout_ratio=max(dropout_ratio, freeze_ratio),
        gyro_bias_drift_rads=gyro_bias_drift,
        pressure_stability_pa=pressure_stability_pa,
        static_window_ratio=static_window_ratio,
        reason_codes=issue_codes,
        penalty_totals={key: round(value, 6) for key, value in penalty_totals.items() if value > 0},
        weight_profile={key: float(value) for key, value in weights.items()},
        thresholds={
            "warning_threshold": audit_cfg["warning_threshold"],
            "fail_threshold": audit_cfg["fail_threshold"],
            "jitter_warn_ms": audit_cfg["jitter_warn_ms"],
            "dropout_ratio_warn": audit_cfg["dropout_ratio_warn"],
            "clipping_warn_ratio": audit_cfg["clipping_warn_ratio"],
            "gravity_residual_warn_mps2": audit_cfg["gravity_residual_warn_mps2"],
        },
        window_count=len(windows),
        available_sensors=dict(session.metadata.sensors),
        skipped_checks=_skipped_checks(session),
    )
    return AuditResult(session_id=session.metadata.session_id, summary=summary, issues=issues, windows=windows)


def _clip_ratio_from_counts(counts: dict[str, int], row_count: float) -> float:
    if row_count <= 0:
        return 0.0
    ratios = [count / (row_count * 3.0) for count in counts.values() if count]
    return float(max(ratios)) if ratios else 0.0


class _WelfordStats:
    def __init__(self) -> None:
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0

    def observe(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)

    @property
    def stddev(self) -> float:
        if self.count < 2:
            return 0.0
        return float(np.sqrt(self.m2 / self.count))


def _clipping_ratio(frame: pd.DataFrame, full_scale: dict[str, float]) -> float:
    ratios = []
    mapping = {
        "acc_mps2": ["ax", "ay", "az"],
        "gyro_rads": ["gx", "gy", "gz"],
        "mag_uT": ["mx", "my", "mz"],
    }
    for key, columns in mapping.items():
        limit = full_scale.get(key)
        if not limit:
            continue
        values = frame[columns].to_numpy(dtype=float)
        ratios.append(float(np.mean(np.abs(values) >= 0.98 * limit)))
    return max(ratios) if ratios else 0.0


def _safe_norm(frame: pd.DataFrame) -> np.ndarray:
    values = frame.to_numpy(dtype=float)
    if np.isnan(values).all():
        return np.full(len(frame), np.nan)
    return np.linalg.norm(np.nan_to_num(values, nan=0.0), axis=1)


def _freeze_zero_ratio(frame: pd.DataFrame) -> float:
    sensor_cols = ["ax", "ay", "az", "gx", "gy", "gz"]
    values = frame[sensor_cols].to_numpy(dtype=float)
    if len(values) < 2:
        return 0.0
    repeat = np.all(np.isclose(values[1:], values[:-1], atol=1e-12), axis=1)
    all_zero = np.all(np.isclose(values, 0.0, atol=1e-12), axis=1)
    return float(max(np.mean(repeat), np.mean(all_zero)))


def _gps_alignment_ratio(session: SessionBundle) -> float | None:
    if session.gps.empty or len(session.gps) < 2:
        return None
    if not session.imu.empty:
        imu_span = float(session.imu["t_ms"].max() - session.imu["t_ms"].min())
    elif session.artifacts.get("imu_path"):
        imu_meta = pd.read_parquet(session.artifacts["imu_path"], columns=["t_ms"])
        if imu_meta.empty:
            return None
        imu_span = float(imu_meta["t_ms"].max() - imu_meta["t_ms"].min())
    else:
        return None
    gps_span = float(session.gps["t_ms"].max() - session.gps["t_ms"].min())
    return gps_span / imu_span if imu_span > 0 else None


def _status_from_score(score: float, warning_threshold: float, fail_threshold: float) -> str:
    if score < fail_threshold:
        return "fail"
    if score < warning_threshold:
        return "warning"
    return "pass"


def _skipped_checks(session: SessionBundle) -> list[str]:
    skipped = []
    if not session.metadata.sensors.get("mag"):
        skipped.append("mag_disturbed")
    if not session.metadata.sensors.get("gps"):
        skipped.append("gps_unreliable")
    if not session.metadata.sensors.get("pressure"):
        skipped.append("pressure_unstable")
    return skipped
