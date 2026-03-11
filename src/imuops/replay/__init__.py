"""Replay baseline algorithms."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from ahrs.filters import Madgwick, Mahony

from imuops.models import ReplaySummaryModel
from imuops.session import SessionBundle
from imuops.utils import dump_json, merge_asof_series, normalize_replay_frame, wrap_angle


@dataclass
class ReplayResult:
    summary: ReplaySummaryModel
    frame: pd.DataFrame

    @property
    def baseline(self) -> str:
        return self.summary.baseline

    @property
    def metrics(self) -> dict[str, Any]:
        return self.summary.metrics

    @property
    def warnings(self) -> list[str]:
        return self.summary.warnings

    def to_dict(self) -> dict[str, Any]:
        return self.summary.model_dump()


def save_replay(result: ReplayResult, session_dir: Path) -> None:
    result.frame.to_parquet(session_dir / f"replay_{result.baseline}.parquet", index=False)
    dump_json(session_dir / f"replay_{result.baseline}_summary.json", result.summary)


def run_replay(session: SessionBundle, baseline: str, config: dict[str, Any]) -> ReplayResult:
    baseline = baseline.lower()
    _enforce_row_limit(session, config, kind="replay")
    if baseline == "madgwick":
        return _run_orientation_baseline(session, config, "madgwick")
    if baseline == "mahony":
        return _run_orientation_baseline(session, config, "mahony")
    if baseline == "pdr":
        return _run_pdr(session, config)
    raise KeyError(f"Unknown baseline '{baseline}'")


def _run_orientation_baseline(session: SessionBundle, config: dict[str, Any], baseline: str) -> ReplayResult:
    imu = session.imu.sort_values("t_ms").reset_index(drop=True)
    freq = session.metadata.nominal_hz or 100.0
    gyr = imu[["gx", "gy", "gz"]].to_numpy(dtype=float)
    acc = imu[["ax", "ay", "az"]].to_numpy(dtype=float)
    mag_frame = imu[["mx", "my", "mz"]].dropna()
    mag = imu[["mx", "my", "mz"]].to_numpy(dtype=float) if not mag_frame.empty else None
    replay_cfg = config["replay"]
    if baseline == "madgwick":
        kwargs = {"frequency": freq, "gain": replay_cfg["madgwick_gain"]}
        estimator = Madgwick(gyr=gyr, acc=acc, mag=mag, **kwargs) if mag is not None else Madgwick(gyr=gyr, acc=acc, **kwargs)
    else:
        kwargs = {"frequency": freq, "k_P": replay_cfg["mahony_kp"], "k_I": replay_cfg["mahony_ki"]}
        estimator = Mahony(gyr=gyr, acc=acc, mag=mag, **kwargs) if mag is not None else Mahony(gyr=gyr, acc=acc, **kwargs)
    quats = estimator.Q
    euler = _quat_to_euler(quats)
    frame = normalize_replay_frame(
        pd.DataFrame(
            {
                "t_ms": imu["t_ms"],
                "qw": quats[:, 0],
                "qx": quats[:, 1],
                "qy": quats[:, 2],
                "qz": quats[:, 3],
                "roll": euler[:, 0],
                "pitch": euler[:, 1],
                "yaw": euler[:, 2],
                "x": np.nan,
                "y": np.nan,
            }
        )
    )
    metrics = _orientation_metrics(frame, session.ground_truth)
    summary = ReplaySummaryModel(baseline=baseline, task="orientation", metrics=metrics, warnings=[])
    return ReplayResult(summary=summary, frame=frame)


def _run_pdr(session: SessionBundle, config: dict[str, Any]) -> ReplayResult:
    orientation = _run_orientation_baseline(session, config, "madgwick")
    imu = session.imu.sort_values("t_ms").reset_index(drop=True)
    replay_cfg = config["replay"]
    acc_norm = np.linalg.norm(imu[["ax", "ay", "az"]].to_numpy(dtype=float), axis=1)
    baseline = pd.Series(acc_norm).rolling(window=max(int((session.metadata.nominal_hz or 100.0) * 0.8), 3), center=True, min_periods=1).mean()
    dynamic = acc_norm - baseline.to_numpy()
    t_ms = imu["t_ms"].to_numpy(dtype=int)
    peak_indices = []
    last_peak = -10**9
    min_interval = replay_cfg["step_min_interval_ms"]
    for idx in range(1, len(dynamic) - 1):
        if dynamic[idx] <= replay_cfg["step_prominence_mps2"]:
            continue
        if dynamic[idx] <= dynamic[idx - 1] or dynamic[idx] <= dynamic[idx + 1]:
            continue
        if t_ms[idx] - last_peak < min_interval:
            continue
        peak_indices.append(idx)
        last_peak = t_ms[idx]
    x = np.zeros(len(imu))
    y = np.zeros(len(imu))
    if peak_indices:
        cumulative_x = 0.0
        cumulative_y = 0.0
        for idx in peak_indices:
            step_boost = np.clip(dynamic[idx] / 6.0, 0.8, 1.3)
            step_len = replay_cfg["default_step_length_m"] * step_boost
            yaw = orientation.frame["yaw"].iloc[idx]
            cumulative_x += step_len * np.cos(yaw)
            cumulative_y += step_len * np.sin(yaw)
            x[idx:] = cumulative_x
            y[idx:] = cumulative_y
    frame = orientation.frame.copy()
    frame["x"] = x
    frame["y"] = y
    metrics = _orientation_metrics(frame, session.ground_truth)
    metrics["step_count"] = len(peak_indices)
    metrics.update(_trajectory_metrics(frame, session.ground_truth))
    warnings = [] if peak_indices else ["No steps were detected; trajectory remained at the origin."]
    summary = ReplaySummaryModel(baseline="pdr", task="pdr", metrics=metrics, warnings=warnings)
    return ReplayResult(summary=summary, frame=normalize_replay_frame(frame))


def _quat_to_euler(quats: np.ndarray) -> np.ndarray:
    qw, qx, qy, qz = quats[:, 0], quats[:, 1], quats[:, 2], quats[:, 3]
    roll = np.arctan2(2.0 * (qw * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy))
    pitch = np.arcsin(np.clip(2.0 * (qw * qy - qz * qx), -1.0, 1.0))
    yaw = np.arctan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
    return np.column_stack([roll, pitch, yaw])


def _orientation_metrics(frame: pd.DataFrame, ground_truth: pd.DataFrame) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "path_smoothness": _path_smoothness(frame["yaw"].to_numpy(dtype=float)),
    }
    if ground_truth.empty:
        return metrics
    aligned = merge_asof_series(frame[["t_ms", "yaw"]], ground_truth[["t_ms", "heading"]].dropna(), tolerance_ms=250)
    aligned = aligned.dropna()
    if not aligned.empty:
        diff = wrap_angle(aligned["yaw"].to_numpy(dtype=float) - aligned["heading"].to_numpy(dtype=float))
        metrics["heading_drift_rad"] = float(np.mean(np.abs(diff)))
    return metrics


def _trajectory_metrics(frame: pd.DataFrame, ground_truth: pd.DataFrame) -> dict[str, Any]:
    if ground_truth.empty or frame[["x", "y"]].isna().all().all():
        return {}
    replay_xy = frame[["t_ms", "x", "y"]].copy()
    gt_xy = ground_truth[["t_ms", "x", "y"]].copy()
    replay_xy[["x", "y"]] = replay_xy[["x", "y"]] - replay_xy[["x", "y"]].iloc[0]
    gt_xy[["x", "y"]] = gt_xy[["x", "y"]] - gt_xy[["x", "y"]].iloc[0]
    aligned = merge_asof_series(replay_xy, gt_xy, tolerance_ms=300)
    aligned = aligned.dropna()
    if aligned.empty:
        return {}
    err = aligned[["x_x", "y_x"]].to_numpy(dtype=float) - aligned[["x_y", "y_y"]].to_numpy(dtype=float)
    rmse = float(np.sqrt(np.mean(np.sum(err**2, axis=1))))
    return {"trajectory_rmse_m": rmse}


def _path_smoothness(angles: np.ndarray) -> float:
    valid = np.unwrap(angles[np.isfinite(angles)])
    if valid.size < 3:
        return 0.0
    second_diff = np.diff(valid, n=2)
    return float(np.mean(np.abs(second_diff)))


def _enforce_row_limit(session: SessionBundle, config: dict[str, Any], *, kind: str) -> None:
    limit_key = f"{kind}_max_rows"
    limit = int(config.get("limits", {}).get(limit_key, 0))
    row_count = len(session.imu)
    if limit > 0 and row_count > limit:
        raise ValueError(
            f"{kind} row limit exceeded: session has {row_count} rows, limit is {limit}. "
            "v0.4.0 large-file support is designed for ingest, audit, export, compare, and batch workflows; "
            "replay remains intentionally bounded so it does not overcommit memory on very large sessions."
        )
