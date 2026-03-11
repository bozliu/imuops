"""Adapter for WISDM accelerometer activity data."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from imuops.adapters.base import BaseAdapter
from imuops.models import SessionMetadata
from imuops.session import SessionBundle
from imuops.utils import sampling_stats, slugify

G = 9.80665
WISDM_COLUMNS = ["user", "activity", "timestamp", "x", "y", "z"]


class WISDMAdapter(BaseAdapter):
    name = "wisdm"

    @classmethod
    def detect(cls, src_path: Path) -> bool:
        if src_path.is_file() and src_path.suffix.lower() in {".txt", ".csv"}:
            return "wisdm" in src_path.name.lower() or src_path.stat().st_size > 0
        return src_path.is_dir() and any(path.suffix.lower() in {".txt", ".csv"} for path in src_path.iterdir())

    @classmethod
    def ingest(cls, src_path: Path, out_dir: Path, config: dict) -> SessionBundle:
        file_path = cls._resolve_file(src_path)
        frame = cls._load_raw(file_path)
        requested_session = config.get("session_id")
        if requested_session:
            user_id = requested_session.replace("user_", "")
            frame = frame[frame["user"].astype(str) == user_id]
        else:
            first_user = str(frame["user"].iloc[0])
            frame = frame[frame["user"].astype(str) == first_user]
        frame = frame.reset_index(drop=True)
        t_ms = cls._normalize_time(frame["timestamp"].to_numpy(dtype=float))
        imu = pd.DataFrame(
            {
                "t_ms": t_ms,
                "ax": frame["x"].to_numpy(dtype=float) * G,
                "ay": frame["y"].to_numpy(dtype=float) * G,
                "az": frame["z"].to_numpy(dtype=float) * G,
                "gx": np.nan,
                "gy": np.nan,
                "gz": np.nan,
                "mx": np.nan,
                "my": np.nan,
                "mz": np.nan,
                "temp_c": np.nan,
                "pressure_pa": np.nan,
                "activity_label": frame["activity"].astype(str).to_numpy(),
            }
        )
        session_id = requested_session or f"user_{frame['user'].iloc[0]}"
        stats = sampling_stats(imu["t_ms"])
        metadata = SessionMetadata(
            dataset="wisdm",
            session_id=slugify(session_id),
            source_path=str(file_path),
            task="har",
            reference_type="activity_labels",
            subject_id=str(frame["user"].iloc[0]),
            nominal_hz=stats["nominal_hz"],
            labels_available=True,
            ground_truth_available=False,
            body_location="phone",
            device_pose="free_carry",
            label_namespace="wisdm_activity",
            notes=["WISDM accelerometer activity data"],
            sensors={
                "imu": True,
                "mag": False,
                "pressure": False,
                "temperature": False,
                "gps": False,
            },
            extra={"full_scale": {"acc_mps2": 4.0 * G}},
        )
        return SessionBundle(metadata=metadata, imu=imu)

    @classmethod
    def _resolve_file(cls, src_path: Path) -> Path:
        src_path = src_path.expanduser().resolve()
        if src_path.is_file():
            return src_path
        candidates = sorted(path for path in src_path.iterdir() if path.suffix.lower() in {".txt", ".csv"})
        if not candidates:
            raise FileNotFoundError(f"No WISDM text/csv files found under {src_path}")
        return candidates[0]

    @classmethod
    def _load_raw(cls, path: Path) -> pd.DataFrame:
        records = []
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line = line.rstrip(";")
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 6 or parts[0].lower() == "user":
                continue
            try:
                records.append(
                    {
                        "user": parts[0],
                        "activity": parts[1],
                        "timestamp": float(parts[2]),
                        "x": float(parts[3]),
                        "y": float(parts[4]),
                        "z": float(parts[5]),
                    }
                )
            except ValueError:
                continue
        frame = pd.DataFrame.from_records(records, columns=WISDM_COLUMNS)
        if frame.empty:
            raise ValueError(f"No valid WISDM rows were parsed from {path}")
        return frame

    @classmethod
    def _normalize_time(cls, values: np.ndarray) -> np.ndarray:
        rel = values - values[0]
        if len(rel) < 2:
            return rel.astype(int)
        dt = np.median(np.diff(rel))
        if dt > 1e5:
            rel = rel / 1e6
        elif dt > 1e2:
            rel = rel / 1e3
        elif dt < 1e-2:
            rel = rel * 1000.0
        return rel.astype(int)
