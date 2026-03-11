"""Session bundle and storage helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Any

import pandas as pd

from imuops.columns import GPS_COLUMNS, GROUND_TRUTH_COLUMNS, IMU_COLUMNS
from imuops.models import SessionMetadata
from imuops.utils import (
    dump_json,
    load_json,
    maybe_heading_from_positions,
    normalize_gps_frame,
    normalize_ground_truth_frame,
    normalize_imu_frame,
    sampling_stats,
)


@dataclass
class SessionBundle:
    metadata: SessionMetadata
    imu: pd.DataFrame
    gps: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=GPS_COLUMNS))
    ground_truth: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=GROUND_TRUTH_COLUMNS))
    artifacts: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.imu = normalize_imu_frame(self.imu)
        self.gps = normalize_gps_frame(self.gps)
        self.ground_truth = maybe_heading_from_positions(normalize_ground_truth_frame(self.ground_truth))
        if not self.ground_truth.empty:
            self.metadata.ground_truth_available = True
        if not self.imu.empty:
            self.metadata.labels_available = bool(self.imu["activity_label"].notna().any())
        if self.metadata.nominal_hz is None and not self.imu.empty:
            self.metadata.nominal_hz = sampling_stats(self.imu["t_ms"])["nominal_hz"]

    @property
    def session_dir_name(self) -> str:
        return self.metadata.session_id


def save_session(bundle: SessionBundle, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dump_json(out_dir / "session.json", bundle.metadata)
    _write_or_reuse_frame(bundle.imu, out_dir / "imu.parquet", bundle.artifacts.get("imu_path"))
    _write_or_reuse_frame(bundle.gps, out_dir / "gps.parquet", bundle.artifacts.get("gps_path"))
    _write_or_reuse_frame(bundle.ground_truth, out_dir / "ground_truth.parquet", bundle.artifacts.get("ground_truth_path"))
    bundle.artifacts["session_dir"] = str(out_dir)
    bundle.artifacts["imu_path"] = str(out_dir / "imu.parquet")
    bundle.artifacts["gps_path"] = str(out_dir / "gps.parquet")
    bundle.artifacts["ground_truth_path"] = str(out_dir / "ground_truth.parquet")
    return out_dir


def load_session(session_dir: str | Path, *, lazy: bool = False) -> SessionBundle:
    session_dir = Path(session_dir)
    meta = SessionMetadata.model_validate(load_json(session_dir / "session.json"))
    imu = pd.DataFrame(columns=IMU_COLUMNS) if lazy else pd.read_parquet(session_dir / "imu.parquet")
    gps_path = session_dir / "gps.parquet"
    gt_path = session_dir / "ground_truth.parquet"
    gps = pd.read_parquet(gps_path) if gps_path.exists() else pd.DataFrame(columns=GPS_COLUMNS)
    ground_truth = pd.read_parquet(gt_path) if gt_path.exists() else pd.DataFrame(columns=GROUND_TRUTH_COLUMNS)
    bundle = SessionBundle(metadata=meta, imu=imu, gps=gps, ground_truth=ground_truth)
    bundle.artifacts["session_dir"] = str(session_dir)
    bundle.artifacts["imu_path"] = str(session_dir / "imu.parquet")
    bundle.artifacts["gps_path"] = str(gps_path)
    bundle.artifacts["ground_truth_path"] = str(gt_path)
    return bundle


def _write_or_reuse_frame(frame: pd.DataFrame, out_path: Path, existing_path: Any) -> None:
    if existing_path:
        source_path = Path(existing_path)
        if source_path.exists():
            if source_path.resolve() == out_path.resolve():
                return
            if frame.empty:
                shutil.copy2(source_path, out_path)
                return
    frame.to_parquet(out_path, index=False)
