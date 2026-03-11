"""Self-contained HTML reporting."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader, select_autoescape
from plotly.offline.offline import get_plotlyjs
import pyarrow.parquet as pq

from imuops.audit import AuditResult
from imuops.benchmark import BenchmarkResult, load_existing_benchmark
from imuops.config import load_defaults
from imuops.models import CorruptionSummaryModel, ReplaySummaryModel
from imuops.replay import ReplayResult
from imuops.session import SessionBundle
from imuops.utils import downsample_indices, load_json, redact_path


def load_existing_replays(session_dir: Path) -> list[ReplayResult]:
    results: list[ReplayResult] = []
    for summary_path in sorted(session_dir.glob("replay_*_summary.json")):
        baseline = summary_path.stem.replace("replay_", "").replace("_summary", "")
        frame_path = session_dir / f"replay_{baseline}.parquet"
        if not frame_path.exists():
            continue
        payload = load_json(summary_path)
        frame = pd.read_parquet(frame_path)
        summary = ReplaySummaryModel.model_validate(payload)
        results.append(ReplayResult(summary=summary, frame=frame))
    return results


def load_corruption_summary(session_dir: Path) -> CorruptionSummaryModel | None:
    path = session_dir / "corruption.json"
    if not path.exists():
        return None
    return CorruptionSummaryModel.model_validate(load_json(path))


def build_report(
    session: SessionBundle,
    audit_result: AuditResult | None,
    replay_result: ReplayResult | list[ReplayResult] | None,
    out_path: str | Path,
    *,
    redact_source_path: bool = False,
    redact_subject_id: bool = False,
) -> Path:
    out_path = Path(out_path)
    session_dir = Path(session.artifacts.get("session_dir", "")) if session.artifacts.get("session_dir") else None
    benchmark_result = load_existing_benchmark(session_dir) if session_dir else None
    corruption_summary = load_corruption_summary(session_dir) if session_dir else None
    corruption_comparison = _load_corruption_comparison(corruption_summary) if corruption_summary else None
    replays = _coerce_replays(replay_result)
    env = _template_env()
    template = env.get_template("report.html.j2")
    context = _build_context(
        session,
        audit_result,
        replays,
        benchmark_result,
        corruption_summary,
        corruption_comparison,
        redact_source_path=redact_source_path,
        redact_subject_id=redact_subject_id,
    )
    html = template.render(**context)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _template_env() -> Environment:
    template_dir = resources.files("imuops.reporting").joinpath("templates")
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _build_context(
    session: SessionBundle,
    audit_result: AuditResult | None,
    replays: list[ReplayResult],
    benchmark_result: BenchmarkResult | None,
    corruption_summary: CorruptionSummaryModel | None,
    corruption_comparison: dict[str, Any] | None,
    *,
    redact_source_path: bool,
    redact_subject_id: bool,
) -> dict[str, Any]:
    cfg = load_defaults()
    imu_frame = _report_imu_frame(session, max_points=int(cfg["report"]["max_points"]))
    source_path = redact_path(session.metadata.source_path) if redact_source_path else session.metadata.source_path
    subject_id = "-" if redact_subject_id and session.metadata.subject_id else session.metadata.subject_id
    session_meta = session.metadata.model_dump()
    session_meta["source_path"] = source_path
    session_meta["subject_id"] = subject_id
    accel_fig = _line_plot(
        imu_frame["t_ms"],
        np.linalg.norm(imu_frame[["ax", "ay", "az"]].to_numpy(dtype=float), axis=1),
        "Acceleration magnitude",
        "m/s²",
        cfg["report"]["max_points"],
    )
    trust_fig = None
    issue_rows = []
    if audit_result:
        trust_fig = _window_trust_plot(audit_result)
        issue_rows = [issue.model_dump() for issue in audit_result.issues[:30]]
    gps_fig = _gps_plot(session)
    replay_cards = [_replay_card(result, session) for result in replays]
    benchmark_table = _benchmark_table(benchmark_result)
    benchmark_fig = _benchmark_plot(benchmark_result)
    return {
        "title": f"imuops report - {session.metadata.session_id}",
        "plotly_js": get_plotlyjs(),
        "session": session_meta,
        "audit_summary": audit_result.summary.model_dump() if audit_result else None,
        "issue_rows": issue_rows,
        "benchmark_summary": benchmark_result.summary.model_dump() if benchmark_result else None,
        "corruption_summary": corruption_summary.model_dump() if corruption_summary else None,
        "corruption_comparison": corruption_comparison,
        "accel_div": accel_fig,
        "trust_div": trust_fig,
        "gps_div": gps_fig,
        "replay_cards": replay_cards,
        "benchmark_table": benchmark_table,
        "benchmark_div": benchmark_fig,
        "product_promise": "Validate whether IMU data is trustworthy, why it is failing, and how that affects baseline algorithms.",
    }


def _coerce_replays(replay_result: ReplayResult | list[ReplayResult] | None) -> list[ReplayResult]:
    if replay_result is None:
        return []
    if isinstance(replay_result, list):
        return replay_result
    return [replay_result]


def _line_plot(x: pd.Series | np.ndarray, y: np.ndarray, title: str, y_label: str, max_points: int) -> str:
    indices = downsample_indices(len(y), max_points)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=np.asarray(x)[indices], y=np.asarray(y)[indices], mode="lines", name=title))
    fig.update_layout(
        title=title,
        xaxis_title="t_ms",
        yaxis_title=y_label,
        margin=dict(l=40, r=20, t=40, b=40),
        template="plotly_white",
        height=280,
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _report_imu_frame(session: SessionBundle, *, max_points: int) -> pd.DataFrame:
    if not session.imu.empty:
        return session.imu
    imu_path = session.artifacts.get("imu_path")
    if not imu_path or not Path(imu_path).exists():
        return pd.DataFrame(columns=["t_ms", "ax", "ay", "az"])
    parquet = pq.ParquetFile(imu_path)
    frames = []
    for batch in parquet.iter_batches(batch_size=50_000, columns=["t_ms", "ax", "ay", "az"]):
        frame = batch.to_pandas()
        if frame.empty:
            continue
        stride = max(1, len(frame) // max(max_points // max(1, parquet.metadata.num_row_groups), 1))
        frames.append(frame.iloc[::stride].reset_index(drop=True))
    if not frames:
        return pd.DataFrame(columns=["t_ms", "ax", "ay", "az"])
    merged = pd.concat(frames, ignore_index=True)
    if len(merged) <= max_points:
        return merged
    return merged.iloc[downsample_indices(len(merged), max_points)].reset_index(drop=True)


def _window_trust_plot(audit_result: AuditResult) -> str:
    max_points = load_defaults()["report"]["max_points"]
    x = [int((window.start_ms + window.end_ms) / 2) for window in audit_result.windows]
    y = [window.trust_score for window in audit_result.windows]
    indices = downsample_indices(len(y), max_points)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=np.asarray(x)[indices], y=np.asarray(y)[indices], mode="lines+markers", name="Trust score", line=dict(color="#dc2626")))
    fig.update_layout(
        title="Trust score timeline",
        xaxis_title="t_ms",
        yaxis_title="score",
        yaxis=dict(range=[0, 1.02]),
        margin=dict(l=40, r=20, t=40, b=40),
        template="plotly_white",
        height=280,
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _gps_plot(session: SessionBundle) -> str | None:
    if session.gps.empty:
        return None
    valid = session.gps[session.gps["valid"]].dropna(subset=["lat", "lon"])
    if valid.empty:
        return None
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=valid["lon"], y=valid["lat"], mode="lines+markers", name="GPS"))
    fig.update_layout(
        title="GPS track",
        xaxis_title="longitude",
        yaxis_title="latitude",
        template="plotly_white",
        height=320,
        margin=dict(l=40, r=20, t=40, b=40),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _replay_card(replay: ReplayResult, session: SessionBundle) -> dict[str, Any]:
    max_points = load_defaults()["report"]["max_points"]
    yaw_fig = _line_plot(replay.frame["t_ms"], replay.frame["yaw"].to_numpy(dtype=float), f"{replay.baseline} yaw", "rad", max_points)
    path_div = None
    if replay.frame[["x", "y"]].notna().any().any():
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=replay.frame["x"], y=replay.frame["y"], mode="lines", name=replay.baseline))
        if not session.ground_truth.empty:
            gt = session.ground_truth.copy()
            gt[["x", "y"]] = gt[["x", "y"]] - gt[["x", "y"]].iloc[0]
            fig.add_trace(go.Scatter(x=gt["x"], y=gt["y"], mode="lines", name="ground_truth"))
        fig.update_layout(
            title=f"{replay.baseline} trajectory",
            xaxis_title="x",
            yaxis_title="y",
            template="plotly_white",
            height=320,
            margin=dict(l=40, r=20, t=40, b=40),
        )
        path_div = fig.to_html(full_html=False, include_plotlyjs=False)
    return {
        "baseline": replay.baseline,
        "task": replay.summary.task,
        "metrics": replay.metrics,
        "warnings": replay.warnings,
        "yaw_div": yaw_fig,
        "path_div": path_div,
    }


def _benchmark_table(benchmark_result: BenchmarkResult | None) -> list[dict[str, Any]]:
    if benchmark_result is None:
        return []
    rows = []
    for baseline in benchmark_result.summary.baselines:
        rows.append(
            {
                "baseline": baseline.baseline,
                "metrics": baseline.metrics,
                "warnings": baseline.warnings,
            }
        )
    return rows


def _benchmark_plot(benchmark_result: BenchmarkResult | None) -> str | None:
    if benchmark_result is None or not benchmark_result.summary.baselines:
        return None
    metric_name = benchmark_result.summary.primary_metric_name
    if not metric_name:
        return None
    xs = [baseline.baseline for baseline in benchmark_result.summary.baselines]
    ys = [baseline.metrics.get(metric_name, np.nan) for baseline in benchmark_result.summary.baselines]
    fig = go.Figure(go.Bar(x=xs, y=ys, marker_color="#2563eb"))
    fig.update_layout(
        title=f"Benchmark primary metric: {metric_name}",
        xaxis_title="baseline",
        yaxis_title=metric_name,
        template="plotly_white",
        height=280,
        margin=dict(l=40, r=20, t=40, b=40),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _load_corruption_comparison(corruption_summary: CorruptionSummaryModel) -> dict[str, Any] | None:
    source_dir = Path(corruption_summary.source_session_dir)
    if not source_dir.exists():
        return None
    source_audit = source_dir / "audit_summary.json"
    if not source_audit.exists():
        return None
    source_summary = load_json(source_audit)
    return {
        "source_session_dir": str(source_dir),
        "source_trust_score": source_summary.get("trust_score"),
        "source_reason_codes": source_summary.get("reason_codes", []),
    }
