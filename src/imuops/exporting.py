"""Export canonical and QA-filtered data for downstream consumers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from imuops.audit import AuditResult, run_audit
from imuops.columns import IMU_COLUMNS
from imuops.models import ExportCoverageModel, ExportSummaryModel
from imuops.session import SessionBundle
from imuops.utils import dump_json


@dataclass
class ExportResult:
    summary: ExportSummaryModel

    @property
    def out_dir(self) -> Path:
        return Path(self.summary.out_dir)

    @property
    def profile(self) -> str:
        return self.summary.profile

    @property
    def file_format(self) -> str:
        return self.summary.format

    @property
    def removed_rows(self) -> int:
        return self.summary.removed_rows

    @property
    def kept_rows(self) -> int:
        return self.summary.kept_rows

    def to_dict(self) -> dict[str, Any]:
        return self.summary.model_dump()


def export_session(
    session: SessionBundle,
    *,
    profile: str,
    file_format: str,
    out_dir: Path,
    config: dict[str, Any],
    audit_result: AuditResult | None = None,
    threshold: float | None = None,
    reason_codes: list[str] | None = None,
) -> ExportResult:
    profile = profile.lower()
    file_format = file_format.lower()
    if file_format not in {"csv", "parquet"}:
        raise ValueError("Export format must be 'csv' or 'parquet'.")

    threshold = threshold if threshold is not None else float(config["export"]["qa_filtered_threshold"])
    requested_reason_codes = sorted(set(reason_codes or []))
    selected_windows = []
    if profile == "qa_filtered":
        audit_result = audit_result or run_audit(session, config)
        selected_windows = _select_drop_windows(audit_result, threshold=threshold, reason_codes=requested_reason_codes)
    elif profile != "canonical":
        raise ValueError("Export profile must be 'canonical' or 'qa_filtered'.")

    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".csv" if file_format == "csv" else ".parquet"
    imu_out = out_dir / f"imu{suffix}"
    gps_out = out_dir / f"gps{suffix}"
    ground_truth_out = out_dir / f"ground_truth{suffix}"

    coverage = ExportCoverageModel(
        dropped_window_count=len(selected_windows),
        dropped_window_reason_counts=_reason_coverage(selected_windows),
        requested_reason_codes=requested_reason_codes,
    )
    kept_rows, source_rows = _export_imu(
        session,
        out_path=imu_out,
        file_format=file_format,
        selected_windows=selected_windows,
    )
    removed_rows = max(source_rows - kept_rows, 0)

    gps = _load_frame(session, "gps")
    ground_truth = _load_frame(session, "ground_truth")
    _write_frame(gps, gps_out, file_format)
    _write_frame(ground_truth, ground_truth_out, file_format)

    metadata = session.metadata.model_copy(deep=True)
    metadata.extra = {
        **metadata.extra,
        "export": {
            "profile": profile,
            "format": file_format,
            "removed_rows": removed_rows,
            "qa_threshold": threshold if profile == "qa_filtered" else None,
            "reason_codes": requested_reason_codes,
        },
    }
    dump_json(out_dir / "session.json", metadata)

    summary = ExportSummaryModel(
        out_dir=str(out_dir),
        profile=profile,
        format=file_format,
        removed_rows=removed_rows,
        kept_rows=kept_rows,
        threshold_used=threshold if profile == "qa_filtered" else None,
        row_counts={
            "imu": kept_rows,
            "gps": int(len(gps)),
            "ground_truth": int(len(ground_truth)),
        },
        written_files={
            "imu": str(imu_out),
            "gps": str(gps_out),
            "ground_truth": str(ground_truth_out),
            "session": str(out_dir / "session.json"),
        },
        reason_code_coverage=coverage,
    )
    result = ExportResult(summary=summary)
    dump_json(out_dir / "export_summary.json", result.summary)
    return result


def _export_imu(
    session: SessionBundle,
    *,
    out_path: Path,
    file_format: str,
    selected_windows: list[tuple[int, int, list[str]]],
) -> tuple[int, int]:
    merged_windows = _merge_intervals([(start_ms, end_ms) for start_ms, end_ms, _ in selected_windows])
    if session.imu.empty and session.artifacts.get("imu_path"):
        source_path = Path(session.artifacts["imu_path"])
        source_rows = _parquet_row_count(source_path)
        kept_rows = _stream_export_imu(source_path, out_path=out_path, file_format=file_format, selected_windows=merged_windows)
        return kept_rows, source_rows

    imu = session.imu.copy()
    filtered_imu = _apply_drop_windows(imu, merged_windows)
    _write_frame(filtered_imu, out_path, file_format)
    return int(len(filtered_imu)), int(len(imu))


def _select_drop_windows(
    audit_result: AuditResult,
    *,
    threshold: float,
    reason_codes: list[str],
) -> list[tuple[int, int, list[str]]]:
    intervals = []
    selected_codes = set(reason_codes)
    for window in audit_result.windows:
        below_threshold = window.trust_score < threshold
        code_match = bool(selected_codes.intersection(window.reason_codes))
        if not below_threshold and not code_match:
            continue
        intervals.append((window.start_ms, window.end_ms, list(window.reason_codes)))
    return intervals


def _reason_coverage(selected_windows: list[tuple[int, int, list[str]]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for _, _, reason_codes in selected_windows:
        for code in reason_codes:
            counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    merged: list[tuple[int, int]] = []
    for start_ms, end_ms in sorted(intervals):
        if not merged or start_ms > merged[-1][1]:
            merged.append((start_ms, end_ms))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end_ms))
    return merged


def _apply_drop_windows(imu: pd.DataFrame, selected_windows: list[tuple[int, int]]) -> pd.DataFrame:
    if imu.empty or not selected_windows:
        return imu.reset_index(drop=True)
    drop_mask = pd.Series(False, index=imu.index)
    for start_ms, end_ms in selected_windows:
        drop_mask = drop_mask | imu["t_ms"].between(start_ms, end_ms)
    return imu.loc[~drop_mask].reset_index(drop=True)


def _stream_export_imu(
    source_path: Path,
    *,
    out_path: Path,
    file_format: str,
    selected_windows: list[tuple[int, int]],
) -> int:
    kept_rows = 0
    writer: pq.ParquetWriter | None = None
    wrote_csv = False
    parquet = pq.ParquetFile(source_path)
    for batch in parquet.iter_batches(batch_size=50_000):
        frame = batch.to_pandas()
        filtered = _apply_drop_windows(frame, selected_windows)
        kept_rows += int(len(filtered))
        if file_format == "csv":
            filtered.to_csv(out_path, index=False, mode="a", header=not wrote_csv)
            wrote_csv = True
            continue
        if filtered.empty:
            continue
        table = pa.Table.from_pandas(filtered, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(out_path, table.schema)
        writer.write_table(table)
    if writer is not None:
        writer.close()
    elif file_format == "parquet":
        pd.DataFrame(columns=IMU_COLUMNS).to_parquet(out_path, index=False)
    elif not wrote_csv:
        pd.DataFrame(columns=IMU_COLUMNS).to_csv(out_path, index=False)
    return kept_rows


def _parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def _load_frame(session: SessionBundle, name: str) -> pd.DataFrame:
    frame = getattr(session, name)
    if not frame.empty:
        return frame.copy()
    path = session.artifacts.get(f"{name}_path")
    if path and Path(path).exists():
        return pd.read_parquet(path)
    return frame.copy()


def _write_frame(frame: pd.DataFrame, path: Path, file_format: str) -> None:
    if file_format == "csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_parquet(path, index=False)
