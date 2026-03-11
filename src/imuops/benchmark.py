"""Task-aware benchmark runners."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split

from imuops.models import BenchmarkBaselineModel, BenchmarkSummaryModel
from imuops.replay import run_replay
from imuops.session import SessionBundle
from imuops.utils import dump_json


@dataclass
class BenchmarkResult:
    summary: BenchmarkSummaryModel

    def to_dict(self) -> dict[str, Any]:
        return self.summary.model_dump()


def run_benchmark(session: SessionBundle, task: str, config: dict[str, Any]) -> BenchmarkResult:
    task = task.lower()
    limit = int(config.get("limits", {}).get("benchmark_max_rows", 0))
    if limit > 0 and len(session.imu) > limit:
        raise ValueError(
            f"benchmark row limit exceeded: session has {len(session.imu)} rows, limit is {limit}. "
            "v0.4.1 large-file support is aimed at ingest, audit, export, compare, and batch pipelines; "
            "benchmarking is still capped so a single huge session does not exhaust memory."
        )
    if task == "orientation":
        baselines = []
        for baseline in ("madgwick", "mahony"):
            replay = run_replay(session, baseline, config)
            baselines.append(BenchmarkBaselineModel(baseline=baseline, metrics=replay.metrics, warnings=replay.warnings))
        primary_name, primary_value = _select_primary_metric(baselines, preferred="heading_drift_rad", fallback="path_smoothness")
        return BenchmarkResult(
            summary=BenchmarkSummaryModel(
                session_id=session.metadata.session_id,
                task="orientation",
                dataset=session.metadata.dataset,
                baselines=baselines,
                primary_metric_name=primary_name,
                primary_metric_value=primary_value,
            )
        )
    if task == "pdr":
        replay = run_replay(session, "pdr", config)
        baselines = [BenchmarkBaselineModel(baseline="pdr", metrics=replay.metrics, warnings=replay.warnings)]
        primary_name, primary_value = _select_primary_metric(baselines, preferred="trajectory_rmse_m", fallback="step_count")
        return BenchmarkResult(
            summary=BenchmarkSummaryModel(
                session_id=session.metadata.session_id,
                task="pdr",
                dataset=session.metadata.dataset,
                baselines=baselines,
                primary_metric_name=primary_name,
                primary_metric_value=primary_value,
            )
        )
    if task == "har":
        return _run_har_benchmark(session, config)
    raise KeyError(f"Unknown benchmark task '{task}'")


def save_benchmark(result: BenchmarkResult, session_dir: Path) -> None:
    dump_json(session_dir / "benchmark_summary.json", result.summary)
    for baseline in result.summary.baselines:
        dump_json(session_dir / f"benchmark_{result.summary.task}_{baseline.baseline}.json", baseline)


def load_existing_benchmark(session_dir: Path) -> BenchmarkResult | None:
    path = session_dir / "benchmark_summary.json"
    if not path.exists():
        return None
    return BenchmarkResult(summary=BenchmarkSummaryModel.model_validate_json(path.read_text(encoding="utf-8")))


def _run_har_benchmark(session: SessionBundle, config: dict[str, Any]) -> BenchmarkResult:
    imu = session.imu.sort_values("t_ms").reset_index(drop=True)
    if "activity_label" not in imu.columns or not imu["activity_label"].notna().any():
        raise ValueError("HAR benchmark requires activity_label values in imu.parquet.")
    bench_cfg = config["benchmark"]
    hz = session.metadata.nominal_hz or 50.0
    window_samples = max(int(round(hz * bench_cfg["har_window_ms"] / 1000.0)), 4)
    step_samples = max(int(round(hz * bench_cfg["har_step_ms"] / 1000.0)), 2)
    feature_rows = []
    labels = []
    for start in range(0, max(len(imu) - window_samples + 1, 0), step_samples):
        window = imu.iloc[start : start + window_samples]
        label = _majority_label(window["activity_label"])
        if label is None:
            continue
        feature_rows.append(_extract_window_features(window))
        labels.append(label)
    if len(feature_rows) < bench_cfg["har_min_windows"]:
        raise ValueError("Not enough labeled windows for HAR benchmark.")
    X = pd.DataFrame(feature_rows)
    y = np.asarray(labels)
    stratify = y if len(set(y)) > 1 and min(np.unique(y, return_counts=True)[1]) > 1 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.3,
        random_state=bench_cfg["har_random_state"],
        stratify=stratify,
    )
    model = RandomForestClassifier(
        n_estimators=bench_cfg["har_n_estimators"],
        random_state=bench_cfg["har_random_state"],
    )
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    metrics = {
        "accuracy": float(accuracy_score(y_test, pred)),
        "macro_f1": float(f1_score(y_test, pred, average="macro")),
        "window_count": int(len(X)),
        "train_windows": int(len(X_train)),
        "test_windows": int(len(X_test)),
        "labels": sorted(set(labels)),
        "classification_report": classification_report(y_test, pred, output_dict=True, zero_division=0),
    }
    baseline = BenchmarkBaselineModel(baseline="rf_features", metrics=metrics, warnings=[])
    return BenchmarkResult(
        summary=BenchmarkSummaryModel(
            session_id=session.metadata.session_id,
            task="har",
            dataset=session.metadata.dataset,
            baselines=[baseline],
            primary_metric_name="macro_f1",
            primary_metric_value=metrics["macro_f1"],
        )
    )


def _majority_label(series: pd.Series) -> str | None:
    valid = series.dropna()
    if valid.empty:
        return None
    return str(valid.mode().iloc[0])


def _extract_window_features(window: pd.DataFrame) -> dict[str, float]:
    features: dict[str, float] = {}
    sensor_sets = {
        "acc": window[["ax", "ay", "az"]].to_numpy(dtype=float),
        "gyro": window[["gx", "gy", "gz"]].to_numpy(dtype=float),
    }
    for prefix, values in sensor_sets.items():
        norms = np.linalg.norm(values, axis=1)
        for axis_idx, axis in enumerate("xyz"):
            axis_values = values[:, axis_idx]
            features[f"{prefix}_{axis}_mean"] = float(np.mean(axis_values))
            features[f"{prefix}_{axis}_std"] = float(np.std(axis_values))
            features[f"{prefix}_{axis}_min"] = float(np.min(axis_values))
            features[f"{prefix}_{axis}_max"] = float(np.max(axis_values))
            features[f"{prefix}_{axis}_energy"] = float(np.mean(axis_values**2))
        features[f"{prefix}_norm_mean"] = float(np.mean(norms))
        features[f"{prefix}_norm_std"] = float(np.std(norms))
    return features


def _select_primary_metric(baselines: list[BenchmarkBaselineModel], preferred: str, fallback: str) -> tuple[str | None, float | None]:
    for metric_name in (preferred, fallback):
        values = [baseline.metrics.get(metric_name) for baseline in baselines if metric_name in baseline.metrics]
        if values:
            numeric = [float(value) for value in values if isinstance(value, (int, float))]
            if numeric:
                return metric_name, float(np.mean(numeric))
    return None, None
