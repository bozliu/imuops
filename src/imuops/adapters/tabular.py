"""Config-driven tabular adapter for customer-shaped IMU datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, model_validator

from imuops.adapters.base import BaseAdapter
from imuops.columns import GPS_COLUMNS, GROUND_TRUTH_COLUMNS, IMU_COLUMNS
from imuops.models import SessionMetadata
from imuops.session import SessionBundle
from imuops.utils import load_yaml, sampling_stats, slugify

G = 9.80665


class TabularMetadataConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    dataset: str | None = None
    session_id: str | None = None
    task: str | None = None
    reference_type: str | None = None
    body_location: str | None = None
    device_pose: str | None = None
    label_namespace: str | None = None
    subject_id: str | None = None
    notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class TabularImuConfig(BaseModel):
    timestamp_col: str
    timestamp_unit: str = "ms"
    accel_cols: list[str] | None = None
    accel_unit: str = "m/s^2"
    gyro_cols: list[str] | None = None
    gyro_unit: str = "rad/s"
    mag_cols: list[str] | None = None
    mag_unit: str = "uT"
    temp_col: str | None = None
    temp_unit: str = "c"
    pressure_col: str | None = None
    pressure_unit: str = "pa"
    label_col: str | None = None

    @model_validator(mode="after")
    def validate_signal_presence(self) -> "TabularImuConfig":
        if not any([self.accel_cols, self.gyro_cols, self.mag_cols, self.temp_col, self.pressure_col, self.label_col]):
            raise ValueError("At least one IMU-related mapping must be provided in the 'imu' section.")
        return self


class TabularGpsConfig(BaseModel):
    timestamp_col: str
    timestamp_unit: str = "ms"
    lat_col: str
    lon_col: str
    valid_col: str | None = None


class TabularGroundTruthConfig(BaseModel):
    timestamp_col: str
    timestamp_unit: str = "ms"
    position_cols: list[str]
    position_unit: str = "m"
    heading_col: str | None = None
    heading_unit: str = "rad"

    @model_validator(mode="after")
    def validate_positions(self) -> "TabularGroundTruthConfig":
        if len(self.position_cols) not in {2, 3}:
            raise ValueError("'ground_truth.position_cols' must contain 2 or 3 columns.")
        return self


class TabularIngestConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    format: str | None = None
    delimiter: str | None = None
    imu: TabularImuConfig
    gps: TabularGpsConfig | None = None
    ground_truth: TabularGroundTruthConfig | None = None
    metadata: TabularMetadataConfig = Field(default_factory=TabularMetadataConfig)


class TabularAdapter(BaseAdapter):
    name = "tabular"

    @classmethod
    def detect(cls, src_path: Path) -> bool:
        return src_path.is_file() and src_path.suffix.lower() in {".csv", ".tsv", ".parquet"}

    @classmethod
    def ingest(cls, src_path: Path, out_dir: Path, config: dict[str, Any]) -> SessionBundle:
        src_path = src_path.expanduser().resolve()
        adapter_config_path = config.get("adapter_config")
        if not adapter_config_path:
            raise ValueError("tabular ingest requires --config <yaml>.")
        ingest_cfg = TabularIngestConfig.model_validate(load_yaml(Path(adapter_config_path)))
        fmt = cls._resolve_format(src_path, ingest_cfg)
        chunk_rows = int(config.get("config", {}).get("tabular", {}).get("chunk_rows", 50000))
        out_dir.mkdir(parents=True, exist_ok=True)
        imu_path = out_dir / "imu.parquet"
        gps_path = out_dir / "gps.parquet"
        ground_truth_path = out_dir / "ground_truth.parquet"
        preflight = cls._preflight_estimate(src_path, fmt, ingest_cfg, chunk_rows)
        writers = {
            "imu": _StreamingParquetWriter(imu_path, IMU_COLUMNS),
            "gps": _StreamingParquetWriter(gps_path, GPS_COLUMNS),
            "ground_truth": _StreamingParquetWriter(ground_truth_path, GROUND_TRUTH_COLUMNS),
        }
        stats = _StreamingImuStats()
        row_counts = {"imu": 0, "gps": 0, "ground_truth": 0}
        seen = {"mag": False, "pressure": False, "temperature": False, "labels": False}

        for chunk in cls._iter_source_chunks(src_path, fmt, ingest_cfg.delimiter, chunk_rows):
            imu_chunk = cls._extract_imu(chunk, ingest_cfg.imu)
            writers["imu"].write(imu_chunk)
            row_counts["imu"] += int(len(imu_chunk))
            stats.observe(imu_chunk["t_ms"])
            seen["mag"] = seen["mag"] or bool(imu_chunk[["mx", "my", "mz"]].notna().any().any())
            seen["pressure"] = seen["pressure"] or bool(imu_chunk["pressure_pa"].notna().any())
            seen["temperature"] = seen["temperature"] or bool(imu_chunk["temp_c"].notna().any())
            seen["labels"] = seen["labels"] or bool(imu_chunk["activity_label"].notna().any())
            if ingest_cfg.gps:
                gps_chunk = cls._extract_gps(chunk, ingest_cfg.gps)
                writers["gps"].write(gps_chunk)
                row_counts["gps"] += int(len(gps_chunk))
            if ingest_cfg.ground_truth:
                gt_chunk = cls._extract_ground_truth(chunk, ingest_cfg.ground_truth)
                writers["ground_truth"].write(gt_chunk)
                row_counts["ground_truth"] += int(len(gt_chunk))

        for writer in writers.values():
            writer.close()
        meta_cfg = ingest_cfg.metadata
        metadata = SessionMetadata(
            dataset=meta_cfg.dataset or config.get("config", {}).get("tabular", {}).get("default_dataset", "tabular"),
            session_id=meta_cfg.session_id or config.get("session_id") or slugify(src_path.stem),
            source_path=str(src_path),
            task=meta_cfg.task or config.get("config", {}).get("tabular", {}).get("default_task", "orientation"),
            reference_type=meta_cfg.reference_type or (None if row_counts["ground_truth"] == 0 else "trajectory"),
            subject_id=meta_cfg.subject_id,
            nominal_hz=stats.nominal_hz,
            labels_available=seen["labels"],
            ground_truth_available=row_counts["ground_truth"] > 0,
            body_location=meta_cfg.body_location,
            device_pose=meta_cfg.device_pose,
            label_namespace=meta_cfg.label_namespace,
            notes=[*meta_cfg.notes, f"tabular_config={Path(adapter_config_path).name}"],
            sensors={
                "imu": True,
                "mag": seen["mag"],
                "pressure": seen["pressure"],
                "temperature": seen["temperature"],
                "gps": row_counts["gps"] > 0,
            },
            extra={
                **meta_cfg.extra,
                "tabular": {
                    "format": fmt,
                    "adapter_config": str(Path(adapter_config_path)),
                    "chunk_rows": chunk_rows,
                    "preflight": preflight,
                },
            },
        )
        eager_load = preflight["estimated_input_rows"] <= max(chunk_rows * 20, 5_000)
        bundle = SessionBundle(
            metadata=metadata,
            imu=pd.read_parquet(imu_path) if eager_load else pd.DataFrame(columns=IMU_COLUMNS),
            gps=pd.read_parquet(gps_path) if eager_load else pd.DataFrame(columns=GPS_COLUMNS),
            ground_truth=pd.read_parquet(ground_truth_path) if eager_load else pd.DataFrame(columns=GROUND_TRUTH_COLUMNS),
        )
        bundle.artifacts.update(
            {
                "imu_path": str(imu_path),
                "gps_path": str(gps_path),
                "ground_truth_path": str(ground_truth_path),
                "row_counts": row_counts,
                "ingest_preflight": preflight,
            }
        )
        return bundle

    @classmethod
    def _resolve_format(cls, src_path: Path, config: TabularIngestConfig) -> str:
        if config.format:
            return config.format.lower()
        suffix = src_path.suffix.lower()
        if suffix == ".csv":
            return "csv"
        if suffix == ".tsv":
            return "tsv"
        if suffix == ".parquet":
            return "parquet"
        raise ValueError(f"Cannot infer tabular format from {src_path}. Set 'format' in the YAML config.")

    @classmethod
    def _iter_source_chunks(cls, src_path: Path, fmt: str, delimiter: str | None, chunk_rows: int):
        if fmt == "parquet":
            parquet = pq.ParquetFile(src_path)
            for batch in parquet.iter_batches(batch_size=chunk_rows):
                yield batch.to_pandas()
            return
        sep = delimiter or ("\t" if fmt == "tsv" else ",")
        for chunk in pd.read_csv(src_path, sep=sep, chunksize=chunk_rows):
            yield chunk

    @classmethod
    def _preflight_estimate(cls, src_path: Path, fmt: str, ingest_cfg: TabularIngestConfig, chunk_rows: int) -> dict[str, Any]:
        source_bytes = int(src_path.stat().st_size)
        estimated_rows = 0
        estimated_imu_memory_bytes = 0
        if fmt == "parquet":
            parquet = pq.ParquetFile(src_path)
            estimated_rows = int(parquet.metadata.num_rows)
            sample = next(parquet.iter_batches(batch_size=min(chunk_rows, 2048)), None)
            sample_frame = sample.to_pandas() if sample is not None else pd.DataFrame()
        else:
            sep = ingest_cfg.delimiter or ("\t" if fmt == "tsv" else ",")
            sample_frame = pd.read_csv(src_path, sep=sep, nrows=min(chunk_rows, 2048))
            if not sample_frame.empty:
                sample_bytes = int(sample_frame.memory_usage(deep=True).sum())
                estimated_rows = int(max(1, round(source_bytes / max(sample_bytes / len(sample_frame), 1))))
        if not sample_frame.empty:
            extracted = cls._extract_imu(sample_frame, ingest_cfg.imu)
            bytes_per_row = extracted.memory_usage(deep=True).sum() / max(len(extracted), 1)
            estimated_imu_memory_bytes = int(bytes_per_row * max(estimated_rows, len(extracted)))
        return {
            "format": fmt,
            "source_bytes": source_bytes,
            "estimated_input_rows": estimated_rows,
            "estimated_imu_memory_bytes": estimated_imu_memory_bytes,
            "large_file_mode": "streamed_parquet",
        }

    @classmethod
    def _extract_imu(cls, frame: pd.DataFrame, config: TabularImuConfig) -> pd.DataFrame:
        cls._require_columns(frame, [config.timestamp_col])
        data: dict[str, Any] = {
            "t_ms": cls._convert_time(frame[config.timestamp_col], config.timestamp_unit),
            "ax": np.nan,
            "ay": np.nan,
            "az": np.nan,
            "gx": np.nan,
            "gy": np.nan,
            "gz": np.nan,
            "mx": np.nan,
            "my": np.nan,
            "mz": np.nan,
            "temp_c": np.nan,
            "pressure_pa": np.nan,
            "activity_label": pd.Series([None] * len(frame), dtype="string"),
        }
        if config.accel_cols:
            cls._require_columns(frame, config.accel_cols)
            values = cls._convert_accel(frame[config.accel_cols], config.accel_unit)
            data.update({"ax": values.iloc[:, 0], "ay": values.iloc[:, 1], "az": values.iloc[:, 2]})
        if config.gyro_cols:
            cls._require_columns(frame, config.gyro_cols)
            values = cls._convert_gyro(frame[config.gyro_cols], config.gyro_unit)
            data.update({"gx": values.iloc[:, 0], "gy": values.iloc[:, 1], "gz": values.iloc[:, 2]})
        if config.mag_cols:
            cls._require_columns(frame, config.mag_cols)
            values = cls._convert_mag(frame[config.mag_cols], config.mag_unit)
            data.update({"mx": values.iloc[:, 0], "my": values.iloc[:, 1], "mz": values.iloc[:, 2]})
        if config.temp_col:
            cls._require_columns(frame, [config.temp_col])
            data["temp_c"] = cls._convert_temp(frame[config.temp_col], config.temp_unit)
        if config.pressure_col:
            cls._require_columns(frame, [config.pressure_col])
            data["pressure_pa"] = cls._convert_pressure(frame[config.pressure_col], config.pressure_unit)
        if config.label_col:
            cls._require_columns(frame, [config.label_col])
            data["activity_label"] = frame[config.label_col].astype("string")
        return pd.DataFrame(data)

    @classmethod
    def _extract_gps(cls, frame: pd.DataFrame, config: TabularGpsConfig) -> pd.DataFrame:
        cls._require_columns(frame, [config.timestamp_col, config.lat_col, config.lon_col])
        valid = frame[config.valid_col].astype(bool) if config.valid_col else pd.Series(np.ones(len(frame), dtype=bool))
        return pd.DataFrame(
            {
                "t_ms": cls._convert_time(frame[config.timestamp_col], config.timestamp_unit),
                "lat": frame[config.lat_col].astype(float),
                "lon": frame[config.lon_col].astype(float),
                "valid": valid,
                "raw_sentence": "",
            }
        )

    @classmethod
    def _extract_ground_truth(cls, frame: pd.DataFrame, config: TabularGroundTruthConfig) -> pd.DataFrame:
        cls._require_columns(frame, [config.timestamp_col, *config.position_cols])
        positions = cls._convert_position(frame[config.position_cols], config.position_unit)
        data: dict[str, Any] = {
            "t_ms": cls._convert_time(frame[config.timestamp_col], config.timestamp_unit),
            "x": positions.iloc[:, 0],
            "y": positions.iloc[:, 1],
            "z": positions.iloc[:, 2] if positions.shape[1] > 2 else np.nan,
            "heading": np.nan,
        }
        if config.heading_col:
            cls._require_columns(frame, [config.heading_col])
            data["heading"] = cls._convert_heading(frame[config.heading_col], config.heading_unit)
        return pd.DataFrame(data)

    @staticmethod
    def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError(f"Missing required columns in tabular source: {', '.join(missing)}")

    @staticmethod
    def _convert_time(series: pd.Series, unit: str) -> pd.Series:
        unit_key = unit.lower()
        factor = {"s": 1000.0, "ms": 1.0, "us": 0.001, "ns": 0.000001}.get(unit_key)
        if factor is None:
            raise ValueError(f"Unsupported time unit '{unit}'.")
        return (series.astype(float) * factor).round().astype("int64")

    @staticmethod
    def _convert_accel(frame: pd.DataFrame, unit: str) -> pd.DataFrame:
        unit_key = unit.lower()
        factor = {"g": G, "m/s^2": 1.0, "mps2": 1.0}.get(unit_key)
        if factor is None:
            raise ValueError(f"Unsupported accelerometer unit '{unit}'.")
        return frame.astype(float) * factor

    @staticmethod
    def _convert_gyro(frame: pd.DataFrame, unit: str) -> pd.DataFrame:
        unit_key = unit.lower()
        if unit_key in {"rad/s", "rads", "radps"}:
            return frame.astype(float)
        if unit_key in {"deg/s", "dps", "degps"}:
            values = np.deg2rad(frame.astype(float).to_numpy(dtype=float))
            return pd.DataFrame(values, columns=frame.columns, index=frame.index)
        raise ValueError(f"Unsupported gyroscope unit '{unit}'.")

    @staticmethod
    def _convert_mag(frame: pd.DataFrame, unit: str) -> pd.DataFrame:
        unit_key = unit.lower()
        if unit_key != "ut":
            raise ValueError(f"Unsupported magnetometer unit '{unit}'.")
        return frame.astype(float)

    @staticmethod
    def _convert_temp(series: pd.Series, unit: str) -> pd.Series:
        unit_key = unit.lower()
        if unit_key in {"c", "celsius"}:
            return series.astype(float)
        if unit_key in {"k", "kelvin"}:
            return series.astype(float) - 273.15
        if unit_key in {"f", "fahrenheit"}:
            return (series.astype(float) - 32.0) * (5.0 / 9.0)
        raise ValueError(f"Unsupported temperature unit '{unit}'.")

    @staticmethod
    def _convert_pressure(series: pd.Series, unit: str) -> pd.Series:
        unit_key = unit.lower()
        factor = {"pa": 1.0, "kpa": 1000.0, "hpa": 100.0}.get(unit_key)
        if factor is None:
            raise ValueError(f"Unsupported pressure unit '{unit}'.")
        return series.astype(float) * factor

    @staticmethod
    def _convert_position(frame: pd.DataFrame, unit: str) -> pd.DataFrame:
        unit_key = unit.lower()
        factor = {"m": 1.0, "cm": 0.01, "mm": 0.001}.get(unit_key)
        if factor is None:
            raise ValueError(f"Unsupported position unit '{unit}'.")
        return frame.astype(float) * factor

    @staticmethod
    def _convert_heading(series: pd.Series, unit: str) -> pd.Series:
        unit_key = unit.lower()
        if unit_key in {"rad", "radian", "radians"}:
            return series.astype(float)
        if unit_key in {"deg", "degree", "degrees"}:
            return pd.Series(np.deg2rad(series.astype(float).to_numpy(dtype=float)), index=series.index)
        raise ValueError(f"Unsupported heading unit '{unit}'.")


class _StreamingParquetWriter:
    def __init__(self, path: Path, columns: list[str]) -> None:
        self.path = path
        self.columns = columns
        self.writer: pq.ParquetWriter | None = None

    def write(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self.writer is None:
            self.writer = pq.ParquetWriter(self.path, table.schema)
        self.writer.write_table(table)

    def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            return
        pd.DataFrame(columns=self.columns).to_parquet(self.path, index=False)


class _StreamingImuStats:
    def __init__(self) -> None:
        self.first_t_ms: int | None = None
        self.last_t_ms: int | None = None
        self.samples: list[float] = []

    @property
    def nominal_hz(self) -> float | None:
        if not self.samples:
            return None
        median_dt = float(np.median(np.asarray(self.samples, dtype=float)))
        if median_dt <= 0:
            return None
        return float(1000.0 / median_dt)

    def observe(self, t_ms: pd.Series) -> None:
        if t_ms.empty:
            return
        values = t_ms.to_numpy(dtype=float)
        if self.first_t_ms is None:
            self.first_t_ms = int(values[0])
        if self.last_t_ms is not None and len(values):
            dt = np.concatenate([[values[0] - self.last_t_ms], np.diff(values)])
        else:
            dt = np.diff(values)
        positive_dt = dt[dt > 0]
        if len(positive_dt):
            self.samples.extend(positive_dt.tolist())
        if len(self.samples) > 200_000:
            stride = int(np.ceil(len(self.samples) / 200_000))
            self.samples = self.samples[::stride][:200_000]
        self.last_t_ms = int(values[-1])
