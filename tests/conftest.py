from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from imuops.models import SessionMetadata
from imuops.session import SessionBundle


@pytest.fixture()
def synthetic_session() -> SessionBundle:
    t_ms = np.arange(0, 10_000, 10)
    yaw = np.linspace(0.0, 1.2, len(t_ms))
    ax = np.sin(np.linspace(0, 8 * np.pi, len(t_ms))) * 0.8
    imu = pd.DataFrame(
        {
            "t_ms": t_ms,
            "ax": ax,
            "ay": np.zeros_like(ax),
            "az": np.full_like(ax, 9.80665),
            "gx": np.zeros_like(ax),
            "gy": np.zeros_like(ax),
            "gz": np.gradient(yaw, 0.01),
            "mx": np.cos(yaw) * 42.0,
            "my": np.sin(yaw) * 42.0,
            "mz": np.full_like(ax, 5.0),
            "temp_c": np.nan,
            "pressure_pa": np.full_like(ax, 101325.0),
            "activity_label": pd.Series([None] * len(t_ms), dtype="string"),
        }
    )
    ground_truth = pd.DataFrame(
        {
            "t_ms": t_ms[::10],
            "x": np.linspace(0.0, 6.0, len(t_ms[::10])),
            "y": np.linspace(0.0, 2.0, len(t_ms[::10])),
            "z": np.zeros(len(t_ms[::10])),
            "heading": np.linspace(0.0, 1.0, len(t_ms[::10])),
        }
    )
    metadata = SessionMetadata(
        dataset="synthetic",
        session_id="synthetic_session",
        source_path="synthetic",
        task="pdr",
        reference_type="trajectory",
        nominal_hz=100.0,
        sensors={"imu": True, "mag": True, "pressure": True, "temperature": False, "gps": False},
        ground_truth_available=True,
        extra={"full_scale": {"acc_mps2": 19.6133, "gyro_rads": 4.3633, "mag_uT": 491.2}},
    )
    bundle = SessionBundle(metadata=metadata, imu=imu, ground_truth=ground_truth)
    bundle.artifacts["session_dir"] = "synthetic_session"
    return bundle


@pytest.fixture()
def ronin_fixture_dir(tmp_path: Path) -> Path:
    session_dir = tmp_path / "ronin_sample"
    session_dir.mkdir()
    (session_dir / "info.json").write_text(json.dumps({"path": "train/subject_01/session_01", "device": "pixel"}), encoding="utf-8")
    times = np.arange(0.0, 2.0, 0.01)
    with h5py.File(session_dir / "data.hdf5", "w") as handle:
        synced = handle.create_group("synced")
        synced.create_dataset("time", data=times)
        synced.create_dataset("acce", data=np.column_stack([np.zeros_like(times), np.zeros_like(times), np.full_like(times, 9.80665)]))
        synced.create_dataset("gyro_uncalib", data=np.zeros((len(times), 3)))
        pose = handle.create_group("pose")
        pose.create_dataset("time", data=times)
        pose.create_dataset("tango_pos", data=np.column_stack([times, times * 0.2, np.zeros_like(times)]))
    return session_dir


@pytest.fixture()
def oxiod_fixture_file(tmp_path: Path) -> Path:
    session_dir = tmp_path / "oxiod"
    session_dir.mkdir()
    times = np.arange(0.0, 2.0, 0.01)
    imu = np.column_stack(
        [
            times,
            np.zeros((len(times), 3)),
            np.zeros((len(times), 3)),
            np.tile([0.0, 0.0, 1.0], (len(times), 1)),
            np.tile([0.1, 0.0, 0.0], (len(times), 1)),
            np.tile([30.0, 0.0, 5.0], (len(times), 1)),
        ]
    )
    imu_path = session_dir / "imu1.csv"
    pd.DataFrame(imu).to_csv(imu_path, header=False, index=False)
    gt = np.column_stack(
        [
            times,
            np.zeros(len(times)),
            times,
            times * 0.3,
            np.zeros(len(times)),
            np.zeros((len(times), 4)),
        ]
    )
    pd.DataFrame(gt).to_csv(session_dir / "vi1.csv", header=False, index=False)
    return imu_path


@pytest.fixture()
def wisdm_fixture_file(tmp_path: Path) -> Path:
    file_path = tmp_path / "WISDM_sample.txt"
    lines = [
        "user,activity,timestamp,x-axis,y-axis,z-axis;",
    ]
    timestamp = 0
    for activity, base in [("Walking", (0.8, 0.0, 1.1)), ("Jogging", (1.2, 0.2, 1.4)), ("Standing", (0.0, 0.0, 1.0))]:
        for idx in range(60):
            timestamp += 50
            x = base[0] + 0.05 * np.sin(idx / 3)
            y = base[1] + 0.03 * np.cos(idx / 5)
            z = base[2] + 0.04 * np.sin(idx / 7)
            lines.append(f"1,{activity},{timestamp},{x:.5f},{y:.5f},{z:.5f};")
    file_path.write_text("\n".join(lines), encoding="utf-8")
    return file_path


@pytest.fixture()
def tabular_csv_fixture(tmp_path: Path) -> tuple[Path, Path]:
    csv_path = tmp_path / "customer_session.csv"
    yaml_path = tmp_path / "customer_session.yaml"
    t_ms = np.arange(0, 4000, 20)
    yaw_deg = np.linspace(0.0, 45.0, len(t_ms))
    frame = pd.DataFrame(
        {
            "time_ms": t_ms,
            "ax_g": 0.05 * np.sin(np.linspace(0, 6 * np.pi, len(t_ms))),
            "ay_g": 0.02 * np.cos(np.linspace(0, 4 * np.pi, len(t_ms))),
            "az_g": 1.0 + 0.01 * np.sin(np.linspace(0, 3 * np.pi, len(t_ms))),
            "gx_dps": np.zeros(len(t_ms)),
            "gy_dps": np.zeros(len(t_ms)),
            "gz_dps": np.gradient(yaw_deg, 0.02),
            "mx_ut": np.full(len(t_ms), 28.0),
            "my_ut": np.full(len(t_ms), 3.0),
            "mz_ut": np.full(len(t_ms), 6.0),
            "temp_c": np.full(len(t_ms), 28.5),
            "pressure_kpa": np.full(len(t_ms), 101.325),
            "activity": ["walk"] * len(t_ms),
            "x_m": np.linspace(0.0, 3.5, len(t_ms)),
            "y_m": np.linspace(0.0, 0.5, len(t_ms)),
            "heading_deg": yaw_deg,
        }
    )
    frame.to_csv(csv_path, index=False)
    yaml_path.write_text(
        "\n".join(
            [
                "format: csv",
                "imu:",
                "  timestamp_col: time_ms",
                "  timestamp_unit: ms",
                "  accel_cols: [ax_g, ay_g, az_g]",
                "  accel_unit: g",
                "  gyro_cols: [gx_dps, gy_dps, gz_dps]",
                "  gyro_unit: deg/s",
                "  mag_cols: [mx_ut, my_ut, mz_ut]",
                "  mag_unit: uT",
                "  temp_col: temp_c",
                "  temp_unit: c",
                "  pressure_col: pressure_kpa",
                "  pressure_unit: kpa",
                "  label_col: activity",
                "ground_truth:",
                "  timestamp_col: time_ms",
                "  timestamp_unit: ms",
                "  position_cols: [x_m, y_m]",
                "  position_unit: m",
                "  heading_col: heading_deg",
                "  heading_unit: deg",
                "metadata:",
                "  dataset: customer_demo",
                "  session_id: customer_demo_session",
                "  task: pdr",
                "  reference_type: trajectory",
                "  body_location: handheld",
                "  device_pose: free_carry",
                "  label_namespace: custom_activity",
                "  subject_id: subject_01",
            ]
        ),
        encoding="utf-8",
    )
    return csv_path, yaml_path
