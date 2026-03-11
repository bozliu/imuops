"""General helpers used across imuops."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel
import yaml

from imuops.columns import GPS_COLUMNS, GROUND_TRUTH_COLUMNS, IMU_COLUMNS, REPLAY_COLUMNS


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip()).strip("_").lower()
    return slug or "session"


def jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return jsonable(value.model_dump())
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def dump_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML config at {path} must deserialize to a mapping.")
    return payload


def merge_nested_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_nested_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def ensure_columns(frame: pd.DataFrame, columns: list[str], fill_value: float | str | bool | None = np.nan) -> pd.DataFrame:
    frame = frame.copy()
    for column in columns:
        if column not in frame.columns:
            frame[column] = fill_value
    return frame[columns]


def normalize_imu_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = ensure_columns(frame, IMU_COLUMNS)
    if not normalized.empty:
        normalized["t_ms"] = normalized["t_ms"].astype("int64")
    normalized["activity_label"] = normalized["activity_label"].astype("string")
    return normalized


def normalize_gps_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = ensure_columns(frame, GPS_COLUMNS, fill_value=np.nan)
    normalized["raw_sentence"] = normalized["raw_sentence"].fillna("").astype(str)
    normalized["valid"] = normalized["valid"].fillna(False).astype(bool)
    if not normalized.empty:
        normalized["t_ms"] = normalized["t_ms"].astype("int64")
    return normalized


def normalize_ground_truth_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = ensure_columns(frame, GROUND_TRUTH_COLUMNS)
    if not normalized.empty:
        normalized["t_ms"] = normalized["t_ms"].astype("int64")
    return normalized


def normalize_replay_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = ensure_columns(frame, REPLAY_COLUMNS)
    if not normalized.empty:
        normalized["t_ms"] = normalized["t_ms"].astype("int64")
    return normalized


def sampling_stats(t_ms: pd.Series) -> dict[str, float]:
    if len(t_ms) < 2:
        return {
            "duration_s": 0.0,
            "median_dt_ms": 0.0,
            "mean_dt_ms": 0.0,
            "nominal_hz": 0.0,
            "jitter_ms": 0.0,
        }
    dt = np.diff(t_ms.to_numpy(dtype=np.float64))
    median_dt = float(np.median(dt))
    mean_dt = float(np.mean(dt))
    nominal_hz = float(1000.0 / median_dt) if median_dt > 0 else 0.0
    jitter = float(np.std(dt))
    duration_s = float((t_ms.iloc[-1] - t_ms.iloc[0]) / 1000.0)
    return {
        "duration_s": duration_s,
        "median_dt_ms": median_dt,
        "mean_dt_ms": mean_dt,
        "nominal_hz": nominal_hz,
        "jitter_ms": jitter,
    }


def maybe_heading_from_positions(frame: pd.DataFrame) -> pd.DataFrame:
    frame = normalize_ground_truth_frame(frame)
    if frame.empty:
        return frame
    heading = frame["heading"].to_numpy(dtype=float, copy=True)
    xy = frame[["x", "y"]].to_numpy(dtype=float)
    for idx in range(1, len(frame)):
        if math.isnan(heading[idx]):
            dx = xy[idx, 0] - xy[idx - 1, 0]
            dy = xy[idx, 1] - xy[idx - 1, 1]
            if dx != 0 or dy != 0:
                heading[idx] = math.atan2(dy, dx)
    if len(heading) > 1 and math.isnan(heading[0]):
        heading[0] = heading[1]
    frame["heading"] = heading
    return frame


def merge_asof_series(left: pd.DataFrame, right: pd.DataFrame, tolerance_ms: int = 250) -> pd.DataFrame:
    if left.empty or right.empty:
        return pd.DataFrame()
    left = left.sort_values("t_ms")
    right = right.sort_values("t_ms")
    return pd.merge_asof(left, right, on="t_ms", direction="nearest", tolerance=tolerance_ms)


def wrap_angle(values: np.ndarray) -> np.ndarray:
    return (values + np.pi) % (2.0 * np.pi) - np.pi


def nmea_to_decimal(raw: str, hemisphere: str) -> float | None:
    if not raw or not hemisphere:
        return None
    if "." not in raw:
        return None
    degrees_len = 2 if hemisphere in {"N", "S"} else 3
    degrees = float(raw[:degrees_len])
    minutes = float(raw[degrees_len:])
    decimal = degrees + minutes / 60.0
    if hemisphere in {"S", "W"}:
        decimal *= -1.0
    return decimal


def read_text_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def iter_session_dirs(root: Path) -> list[Path]:
    root = Path(root)
    found = []
    if (root / "session.json").exists():
        return [root]
    for path in sorted(root.rglob("session.json")):
        found.append(path.parent)
    return found


def redact_path(value: str | None) -> str:
    if not value:
        return "-"
    return Path(value).name


def markdown_kv_table(rows: list[tuple[str, Any]]) -> str:
    lines = ["| field | value |", "| --- | --- |"]
    for key, value in rows:
        text = str(value).replace("\n", "<br>")
        lines.append(f"| {key} | {text} |")
    return "\n".join(lines)


def downsample_indices(length: int, max_points: int) -> np.ndarray:
    if length <= max_points:
        return np.arange(length)
    return np.linspace(0, length - 1, num=max_points, dtype=int)


def series_to_svg(
    values: np.ndarray,
    *,
    width: int = 900,
    height: int = 220,
    stroke: str = "#2563eb",
    fill: str = "none",
    title: str | None = None,
) -> str:
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}"></svg>'
    y_min = float(finite.min())
    y_max = float(finite.max())
    if y_min == y_max:
        y_min -= 1.0
        y_max += 1.0
    xs = np.linspace(0, width, num=len(values))
    ys = height - ((np.nan_to_num(values, nan=y_min) - y_min) / (y_max - y_min)) * (height - 20) - 10
    points = " ".join(f"{x:.2f},{y:.2f}" for x, y in zip(xs, ys))
    title_node = f"<title>{title}</title>" if title else ""
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">'
        f'{title_node}<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" stroke="#d1d5db" />'
        f'<polyline fill="{fill}" stroke="{stroke}" stroke-width="2" points="{points}" />'
        "</svg>"
    )


def path_svg(
    xy_series: list[tuple[str, np.ndarray, np.ndarray]],
    *,
    width: int = 480,
    height: int = 360,
) -> str:
    finite_arrays = []
    for _, xs, ys in xy_series:
        finite_arrays.append(np.column_stack([xs[np.isfinite(xs)], ys[np.isfinite(ys)]]))
    finite_arrays = [arr for arr in finite_arrays if arr.size]
    if not finite_arrays:
        return f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}"></svg>'
    stack = np.vstack(finite_arrays)
    x_min, y_min = np.min(stack[:, 0]), np.min(stack[:, 1])
    x_max, y_max = np.max(stack[:, 0]), np.max(stack[:, 1])
    if x_min == x_max:
        x_min -= 1.0
        x_max += 1.0
    if y_min == y_max:
        y_min -= 1.0
        y_max += 1.0
    colors = ["#2563eb", "#dc2626", "#059669", "#9333ea"]
    legend = []
    paths = []
    for index, (label, xs, ys) in enumerate(xy_series):
        color = colors[index % len(colors)]
        x_scaled = (xs - x_min) / (x_max - x_min) * (width - 20) + 10
        y_scaled = height - ((ys - y_min) / (y_max - y_min) * (height - 20) + 10)
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in zip(x_scaled, y_scaled))
        paths.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{points}" />')
        legend.append(f'<text x="12" y="{18 + index * 18}" font-size="12" fill="{color}">{label}</text>')
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" stroke="#d1d5db" />'
        f'{"".join(paths)}{"".join(legend)}</svg>'
    )
