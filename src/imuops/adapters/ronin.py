"""Adapter for RoNIN sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from imuops.adapters.base import BaseAdapter
from imuops.models import SessionMetadata
from imuops.session import SessionBundle
from imuops.utils import maybe_heading_from_positions, sampling_stats
import h5py
import numpy as np
import pandas as pd


def _time_to_ms(values: np.ndarray) -> np.ndarray:
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


class RoNINAdapter(BaseAdapter):
    name = "ronin"

    @classmethod
    def detect(cls, src_path: Path) -> bool:
        return (src_path / "data.hdf5").exists() and (src_path / "info.json").exists()

    @classmethod
    def ingest(cls, src_path: Path, out_dir: Path, config: dict[str, Any]) -> SessionBundle:
        session_dir = src_path.expanduser().resolve()
        if not cls.detect(session_dir):
            raise FileNotFoundError(f"{session_dir} does not look like a RoNIN session.")
        info = json.loads((session_dir / "info.json").read_text(encoding="utf-8"))
        with h5py.File(session_dir / "data.hdf5", "r") as handle:
            synced = handle["synced"]
            times = _time_to_ms(synced["time"][:])
            acc = synced["acce"][:]
            gyro_key = "gyro" if "gyro" in synced else "gyro_uncalib"
            gyro = synced[gyro_key][:]
            mag = None
            for candidate in ("magnet", "magnet_uncalib", "mag"):
                if candidate in synced:
                    mag = synced[candidate][:]
                    break
            imu = pd.DataFrame(
                {
                    "t_ms": times,
                    "ax": acc[:, 0],
                    "ay": acc[:, 1],
                    "az": acc[:, 2],
                    "gx": gyro[:, 0],
                    "gy": gyro[:, 1],
                    "gz": gyro[:, 2],
                    "mx": mag[:, 0] if mag is not None else np.nan,
                    "my": mag[:, 1] if mag is not None else np.nan,
                    "mz": mag[:, 2] if mag is not None else np.nan,
                    "temp_c": np.nan,
                    "pressure_pa": np.nan,
                }
            )
            pose = handle["pose"]
            gt_times = _time_to_ms(pose["time"][:]) if "time" in pose else times[: len(pose["tango_pos"][:])]
            tango_pos = pose["tango_pos"][:]
            ground_truth = pd.DataFrame(
                {
                    "t_ms": gt_times[: len(tango_pos)],
                    "x": tango_pos[:, 0],
                    "y": tango_pos[:, 1],
                    "z": tango_pos[:, 2],
                    "heading": np.nan,
                }
            )
            ground_truth = maybe_heading_from_positions(ground_truth)
        stats = sampling_stats(imu["t_ms"])
        metadata = SessionMetadata(
            dataset="ronin",
            session_id=info.get("path") or session_dir.name,
            source_path=str(session_dir),
            task="pdr",
            reference_type="trajectory",
            subject_id=str(info.get("device", info.get("user", ""))) or None,
            nominal_hz=stats["nominal_hz"],
            labels_available=False,
            ground_truth_available=True,
            body_location="body_unknown",
            device_pose="arbitrary",
            notes=[info.get("device", ""), info.get("source", "")],
            sensors={
                "imu": True,
                "mag": bool(np.isfinite(imu[["mx", "my", "mz"]].to_numpy()).any()),
                "pressure": False,
                "temperature": False,
                "gps": False,
            },
            extra={"ronin_info": info},
        )
        return SessionBundle(metadata=metadata, imu=imu, ground_truth=ground_truth)

