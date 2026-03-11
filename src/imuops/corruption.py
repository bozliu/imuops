"""Config-driven corruption presets for robustness testing."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from imuops.models import CorruptionSummaryModel, SessionMetadata
from imuops.session import SessionBundle, save_session
from imuops.utils import dump_json


def corrupt_session(session: SessionBundle, preset: str, config: dict[str, dict]) -> tuple[SessionBundle, CorruptionSummaryModel]:
    preset = preset.lower()
    rng = np.random.default_rng(config["corruption"]["random_seed"])
    imu = session.imu.copy()
    modifications: dict[str, object] = {}

    if preset == "packet_loss_5":
        keep = np.ones(len(imu), dtype=bool)
        drop_count = max(1, int(round(len(imu) * config["corruption"]["packet_loss_rate"])))
        indices = rng.choice(len(imu), size=drop_count, replace=False)
        keep[indices] = False
        imu = imu.loc[keep].reset_index(drop=True)
        modifications["dropped_samples"] = int(drop_count)
    elif preset == "timestamp_jitter_3ms":
        jitter = rng.integers(-config["corruption"]["jitter_ms"], config["corruption"]["jitter_ms"] + 1, size=len(imu))
        imu["t_ms"] = np.maximum.accumulate((imu["t_ms"].to_numpy(dtype=int) + jitter).astype(int))
        modifications["max_jitter_ms"] = int(np.max(np.abs(jitter)))
    elif preset == "axis_flip_x":
        for column in ("ax", "gx", "mx"):
            if column in imu.columns:
                imu[column] = -imu[column]
        modifications["flipped_axis"] = "x"
    elif preset == "gyro_bias_small":
        bias = np.asarray(config["corruption"]["gyro_bias_small"], dtype=float)
        imu.loc[:, ["gx", "gy", "gz"]] = imu[["gx", "gy", "gz"]].to_numpy(dtype=float) + bias
        modifications["gyro_bias"] = bias.tolist()
    elif preset == "mag_bias_30ut":
        bias = np.asarray(config["corruption"]["mag_bias_30ut"], dtype=float)
        for columns in [["mx", "my", "mz"]]:
            existing = [column for column in columns if column in imu.columns]
            if existing:
                imu.loc[:, existing] = imu[existing].to_numpy(dtype=float) + bias[: len(existing)]
        modifications["mag_bias_ut"] = bias.tolist()
    else:
        raise KeyError(f"Unknown corruption preset '{preset}'")

    metadata = SessionMetadata.model_validate(session.metadata.model_dump())
    metadata.session_id = f"{session.metadata.session_id}__{preset}"
    metadata.notes = [*metadata.notes, f"Corruption preset applied: {preset}"]
    metadata.extra = {
        **metadata.extra,
        "corruption": {
            "preset": preset,
            "source_session_dir": session.artifacts.get("session_dir", ""),
            "modifications": modifications,
        },
    }
    corrupted = SessionBundle(metadata=metadata, imu=imu, gps=session.gps.copy(), ground_truth=session.ground_truth.copy())
    summary = CorruptionSummaryModel(
        preset=preset,
        source_session_dir=str(session.artifacts.get("session_dir", "")),
        out_dir="",
        description=f"Applied corruption preset {preset}.",
        modifications=modifications,
    )
    return corrupted, summary


def save_corrupted_session(session: SessionBundle, summary: CorruptionSummaryModel, out_dir: Path) -> Path:
    save_session(session, out_dir)
    summary.out_dir = str(out_dir)
    dump_json(out_dir / "corruption.json", summary)
    return out_dir

