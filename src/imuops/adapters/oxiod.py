"""Adapter for OxIOD sessions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from imuops.adapters.base import BaseAdapter
from imuops.models import SessionMetadata
from imuops.session import SessionBundle
from imuops.utils import maybe_heading_from_positions, sampling_stats
import numpy as np
import pandas as pd

G = 9.80665


def _normalize_time(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    rel = values - values[0]
    dt = np.median(np.diff(rel)) if len(rel) > 1 else 0.0
    if dt > 1e5:
        rel = rel / 1e6
    elif dt > 1e2:
        rel = rel / 1e3
    elif dt < 1e-2:
        rel = rel * 1000.0
    return rel.astype(np.int64)


class OxIODAdapter(BaseAdapter):
    name = "oxiod"

    @classmethod
    def detect(cls, src_path: Path) -> bool:
        if src_path.is_file() and src_path.name.startswith("imu") and src_path.suffix.lower() == ".csv":
            return True
        return src_path.is_dir() and any(src_path.glob("imu*.csv"))

    @classmethod
    def ingest(cls, src_path: Path, out_dir: Path, config: dict[str, Any]) -> SessionBundle:
        imu_path = cls._resolve_imu_path(src_path, config.get("session_id"))
        gt_path = imu_path.with_name(imu_path.name.replace("imu", "vi", 1))
        imu_raw = pd.read_csv(imu_path, header=None)
        times = _normalize_time(imu_raw.iloc[:, 0].to_numpy())
        gyro = imu_raw.iloc[:, 4:7].to_numpy(dtype=float)
        aux = imu_raw.iloc[:, 7:10].to_numpy(dtype=float) if imu_raw.shape[1] >= 10 else np.zeros((len(imu_raw), 3))
        acc = imu_raw.iloc[:, 10:13].to_numpy(dtype=float) if imu_raw.shape[1] >= 13 else imu_raw.iloc[:, 1:4].to_numpy(dtype=float)
        acc = cls._resolve_acceleration(acc, aux)
        mag = imu_raw.iloc[:, 13:16].to_numpy(dtype=float) if imu_raw.shape[1] >= 16 else np.full((len(imu_raw), 3), np.nan)
        imu = pd.DataFrame(
            {
                "t_ms": times,
                "ax": acc[:, 0],
                "ay": acc[:, 1],
                "az": acc[:, 2],
                "gx": gyro[:, 0],
                "gy": gyro[:, 1],
                "gz": gyro[:, 2],
                "mx": mag[:, 0],
                "my": mag[:, 1],
                "mz": mag[:, 2],
                "temp_c": np.nan,
                "pressure_pa": np.nan,
            }
        )
        ground_truth = pd.DataFrame(columns=["t_ms", "x", "y", "z", "heading"])
        if gt_path.exists():
            gt_raw = pd.read_csv(gt_path, header=None)
            gt_times = _normalize_time(gt_raw.iloc[:, 0].to_numpy())
            ground_truth = pd.DataFrame(
                {
                    "t_ms": gt_times,
                    "x": gt_raw.iloc[:, 2].to_numpy(dtype=float),
                    "y": gt_raw.iloc[:, 3].to_numpy(dtype=float),
                    "z": gt_raw.iloc[:, 4].to_numpy(dtype=float),
                    "heading": np.nan,
                }
            )
            ground_truth = maybe_heading_from_positions(ground_truth)
        stats = sampling_stats(imu["t_ms"])
        metadata = SessionMetadata(
            dataset="oxiod",
            session_id=imu_path.stem,
            source_path=str(imu_path),
            task="pdr",
            reference_type="trajectory" if not ground_truth.empty else None,
            nominal_hz=stats["nominal_hz"],
            labels_available=False,
            ground_truth_available=not ground_truth.empty,
            body_location="handheld",
            device_pose="arbitrary",
            notes=[str(imu_path.parent)],
            sensors={
                "imu": True,
                "mag": bool(np.isfinite(mag).any()),
                "pressure": False,
                "temperature": False,
                "gps": False,
            },
            extra={"oxiod_vi_path": str(gt_path) if gt_path.exists() else None},
        )
        return SessionBundle(metadata=metadata, imu=imu, ground_truth=ground_truth)

    @classmethod
    def _resolve_imu_path(cls, src_path: Path, session_id: str | None) -> Path:
        src_path = src_path.expanduser().resolve()
        if src_path.is_file():
            return src_path
        if session_id:
            candidate = src_path / session_id
            if candidate.exists():
                return candidate
        matches = sorted(src_path.glob("imu*.csv"))
        if not matches:
            raise FileNotFoundError(f"No imu*.csv files found under {src_path}")
        return matches[0]

    @classmethod
    def _resolve_acceleration(cls, acc: np.ndarray, aux: np.ndarray) -> np.ndarray:
        acc_norm = np.linalg.norm(acc, axis=1)
        aux_norm = np.linalg.norm(aux, axis=1)
        if np.nanmedian(aux_norm) > 0.5 and np.nanmedian(aux_norm) < 1.5:
            return (acc + aux) * G
        if np.nanmedian(acc_norm) > 0.5 and np.nanmedian(acc_norm) < 1.5:
            return acc * G
        return acc
