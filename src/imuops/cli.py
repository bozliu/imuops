"""Typer CLI for imuops."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from pydantic import ValidationError
import yaml

from imuops.adapters import get_adapter
from imuops.audit import AuditResult, run_audit
from imuops.batch import batch_audit_sessions, build_batch_report, load_batch_summary
from imuops.benchmark import run_benchmark, save_benchmark
from imuops.compare import build_compare_report
from imuops.config import load_defaults
from imuops.corruption import corrupt_session, save_corrupted_session
from imuops.exporting import export_session
from imuops.models import (
    BatchTrustScoreValidationRowModel,
    BatchTrustScoreValidationSummaryModel,
    CompareSummaryModel,
)
from imuops.reporting import build_report, load_existing_replays
from imuops.replay import run_replay, save_replay
from imuops.session import load_session, save_session
from imuops.utils import dump_json, iter_session_dirs, markdown_kv_table
from imuops.validation import run_trustscore_validation, save_trustscore_validation

app = typer.Typer(no_args_is_help=True, add_completion=False)
batch_app = typer.Typer(no_args_is_help=True, add_completion=False)
app.add_typer(batch_app, name="batch")


@app.command()
def ingest(
    adapter: str,
    src: Path,
    out: Path = typer.Option(..., "--out", help="Output session directory."),
    session_id: Optional[str] = typer.Option(None, "--session-id", help="Explicit session id when src is a dataset root."),
    config: Optional[Path] = typer.Option(None, "--config", help="Adapter-specific config, required for the tabular adapter."),
) -> None:
    """Ingest a supported dataset into the canonical session format."""
    try:
        cfg = load_defaults()
        adapter_impl = get_adapter(adapter)
        bundle = adapter_impl.ingest(src, out, {"session_id": session_id, "config": cfg, "adapter_config": config})
        save_session(bundle, out)
        row_counts = bundle.artifacts.get(
            "row_counts",
            {
                "imu": int(len(bundle.imu)),
                "gps": int(len(bundle.gps)),
                "ground_truth": int(len(bundle.ground_truth)),
            },
        )
        dump_json(
            out / "ingest_summary.json",
            {
                "adapter": adapter_impl.name,
                "session_id": bundle.metadata.session_id,
                "dataset": bundle.metadata.dataset,
                "task": bundle.metadata.task,
                "out_dir": str(out),
                "rows": row_counts,
                "preflight": bundle.artifacts.get("ingest_preflight"),
            },
        )
        typer.echo(f"Ingested {bundle.metadata.session_id} -> {out}")
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='ingest')}", err=True)
        raise typer.Exit(2)


@app.command()
def audit(
    session_dir: Path,
    fail_below: Optional[float] = typer.Option(None, "--fail-below", min=0.0, max=1.0),
    warning_below: Optional[float] = typer.Option(None, "--warning-below", min=0.0, max=1.0),
    summary_format: str = typer.Option("text", "--summary-format", help="One of: text, markdown, json."),
) -> None:
    """Audit a canonical session directory."""
    try:
        cfg = load_defaults()
        session = load_session(session_dir, lazy=True)
        result = run_audit(session, cfg)
        dump_json(session_dir / "issues.json", result.to_dict())
        dump_json(session_dir / "audit_summary.json", result.summary)
        status = _cli_gate_status(result.summary.trust_score, fail_below, warning_below, result.summary.status)
        typer.echo(_format_audit_summary(result, status=status, summary_format=summary_format))
        if fail_below is not None and result.summary.trust_score < fail_below:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='audit')}", err=True)
        raise typer.Exit(2)


@app.command()
def replay(session_dir: Path, baseline: str = typer.Option(..., "--baseline")) -> None:
    """Replay a baseline algorithm on a canonical session."""
    try:
        session = load_session(session_dir)
        result = run_replay(session, baseline, load_defaults())
        save_replay(result, session_dir)
        typer.echo(f"Replay complete: {baseline}")
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='replay')}", err=True)
        raise typer.Exit(2)


@app.command()
def benchmark(session_dir: Path, task: str = typer.Option(..., "--task")) -> None:
    """Run task-aware benchmark baselines on a canonical session."""
    try:
        session = load_session(session_dir)
        result = run_benchmark(session, task, load_defaults())
        save_benchmark(result, session_dir)
        typer.echo(f"Benchmark complete: {task}")
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='benchmark')}", err=True)
        raise typer.Exit(2)


@app.command()
def corrupt(session_dir: Path, preset: str = typer.Option(..., "--preset"), out: Path = typer.Option(..., "--out")) -> None:
    """Create a corrupted canonical session using a built-in robustness preset."""
    try:
        session = load_session(session_dir)
        corrupted, summary = corrupt_session(session, preset, load_defaults())
        save_corrupted_session(corrupted, summary, out)
        typer.echo(f"Corrupted session written to {out}")
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='corrupt')}", err=True)
        raise typer.Exit(2)


@app.command()
def export(
    session_dir: Path,
    profile: str = typer.Option("canonical", "--profile"),
    file_format: str = typer.Option("parquet", "--format"),
    out: Path = typer.Option(..., "--out"),
    threshold: Optional[float] = typer.Option(None, "--threshold", min=0.0, max=1.0),
    reason_code: list[str] = typer.Option(None, "--reason-code"),
) -> None:
    """Export canonical or QA-filtered data for downstream pipelines."""
    try:
        cfg = load_defaults()
        session = load_session(session_dir, lazy=True)
        audit_result = _load_or_run_audit(session_dir, session, cfg)
        result = export_session(
            session,
            profile=profile,
            file_format=file_format,
            out_dir=out,
            config=cfg,
            audit_result=audit_result,
            threshold=threshold,
            reason_codes=reason_code,
        )
        typer.echo(f"Export complete: {result.out_dir}")
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='export')}", err=True)
        raise typer.Exit(2)


@app.command()
def report(
    session_dir: Path,
    out: Path = typer.Option(..., "--out"),
    redact_source_path: Optional[bool] = typer.Option(None, "--redact-source-path/--no-redact-source-path"),
    redact_subject_id: Optional[bool] = typer.Option(None, "--redact-subject-id/--no-redact-subject-id"),
) -> None:
    """Generate a self-contained HTML report for a canonical session."""
    try:
        cfg = load_defaults()
        session = load_session(session_dir, lazy=True)
        audit_result = _load_or_run_audit(session_dir, session, cfg)
        replay_results = load_existing_replays(session_dir)
        build_report(
            session,
            audit_result,
            replay_results,
            out,
            redact_source_path=cfg["report"]["redact_source_path"] if redact_source_path is None else redact_source_path,
            redact_subject_id=cfg["report"]["redact_subject_id"] if redact_subject_id is None else redact_subject_id,
        )
        dump_json(out.with_suffix(".json"), {"report": str(out), "session_dir": str(session_dir)})
        typer.echo(f"Report written to {out}")
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='report')}", err=True)
        raise typer.Exit(2)


@app.command()
def compare(
    session_a: Path,
    session_b: Path,
    out: Path = typer.Option(..., "--out"),
    json_out: Optional[Path] = typer.Option(None, "--json-out"),
    summary_format: str = typer.Option("text", "--summary-format", help="One of: text, markdown, json."),
    fail_on: str = typer.Option("never", "--fail-on", help="One of: regression, mixed, never."),
    trust_drop_threshold: float = typer.Option(0.03, "--trust-drop-threshold", min=0.0, max=1.0),
    redact_source_path: Optional[bool] = typer.Option(None, "--redact-source-path/--no-redact-source-path"),
    redact_subject_id: Optional[bool] = typer.Option(None, "--redact-subject-id/--no-redact-subject-id"),
) -> None:
    """Compare two canonical sessions and emit a trust-score and metric delta report."""
    try:
        cfg = load_defaults()
        bundle_a = load_session(session_a, lazy=True)
        bundle_b = load_session(session_b, lazy=True)
        result = build_compare_report(
            bundle_a,
            bundle_b,
            config=cfg,
            out_path=out,
            json_path=json_out,
            redact_source_path=cfg["report"]["redact_source_path"] if redact_source_path is None else redact_source_path,
            redact_subject_id=cfg["report"]["redact_subject_id"] if redact_subject_id is None else redact_subject_id,
        )
        typer.echo(_format_compare_summary(result.summary, summary_format=summary_format))
        typer.echo(f"Compare report written to {out}")
        if _compare_should_fail(result.summary, fail_on=fail_on, trust_drop_threshold=trust_drop_threshold):
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='compare')}", err=True)
        raise typer.Exit(2)


@app.command("validate-trustscore")
def validate_trustscore(session_dir: Path, out: Path = typer.Option(..., "--out")) -> None:
    """Validate trust-score behavior across built-in corruption presets."""
    try:
        session = load_session(session_dir)
        result = run_trustscore_validation(session, load_defaults())
        save_trustscore_validation(result, out)
        typer.echo(f"Trust-score validation written to {out}")
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='validate-trustscore')}", err=True)
        raise typer.Exit(2)


@batch_app.command("audit")
def batch_audit(
    sessions_root: Path,
    out: Path = typer.Option(..., "--out"),
    fail_below: Optional[float] = typer.Option(None, "--fail-below", min=0.0, max=1.0),
) -> None:
    """Run audit over every canonical session under a root directory."""
    try:
        result = batch_audit_sessions(sessions_root, out, load_defaults())
        typer.echo(json.dumps(result.summary.model_dump(), indent=2))
        if fail_below is not None and any(row.trust_score < fail_below for row in result.summary.rows):
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='batch audit')}", err=True)
        raise typer.Exit(2)


@batch_app.command("report")
def batch_report(sessions_root: Path, out: Path = typer.Option(..., "--out")) -> None:
    """Generate a batch report across every canonical session under a root directory."""
    try:
        batch_dir = out.parent / f"{out.stem}_batch_artifacts"
        summary_path = batch_dir / "batch_summary.json"
        summary = load_batch_summary(summary_path) if summary_path.exists() else batch_audit_sessions(sessions_root, batch_dir, load_defaults()).summary
        build_batch_report(summary, out)
        typer.echo(f"Batch report written to {out}")
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='batch report')}", err=True)
        raise typer.Exit(2)


@batch_app.command("validate-trustscore")
def batch_validate_trustscore(sessions_root: Path, out: Path = typer.Option(..., "--out")) -> None:
    """Run trust-score validation across every canonical session under a root directory."""
    try:
        out.mkdir(parents=True, exist_ok=True)
        rows = []
        for session_dir in iter_session_dirs(sessions_root):
            session = load_session(session_dir)
            result = run_trustscore_validation(session, load_defaults())
            validation_path = out / f"{session.metadata.session_id}_trustscore_validation.json"
            save_trustscore_validation(result, validation_path)
            rows.append(
                BatchTrustScoreValidationRowModel(
                    session_dir=str(Path(session_dir).relative_to(sessions_root)),
                    session_id=session.metadata.session_id,
                    task=session.metadata.task,
                    all_non_improving=result.summary.all_non_improving,
                    validation_path=str(validation_path.relative_to(out)),
                )
            )
        summary = BatchTrustScoreValidationSummaryModel(
            session_count=len(rows),
            rows=rows,
            non_improving_count=sum(1 for row in rows if row.all_non_improving),
        )
        dump_json(out / "trustscore_validation_summary.json", summary)
        typer.echo(json.dumps(summary.model_dump(), indent=2))
    except Exception as exc:
        typer.echo(f"Error: {_format_cli_exception(exc, command='batch validate-trustscore')}", err=True)
        raise typer.Exit(2)


def _load_or_run_audit(session_dir: Path, session, cfg) -> AuditResult:
    issues_path = session_dir / "issues.json"
    if issues_path.exists():
        return AuditResult.from_dict(cfg, session, issues_path)
    return run_audit(session, cfg)


def _cli_gate_status(score: float, fail_below: float | None, warning_below: float | None, default_status: str) -> str:
    if fail_below is not None and score < fail_below:
        return "fail"
    if warning_below is not None and score < warning_below:
        return "warning"
    return default_status


def _format_audit_summary(result: AuditResult, *, status: str, summary_format: str) -> str:
    summary_format = summary_format.lower()
    rows = [
        ("session_id", result.summary.session_id),
        ("dataset", result.summary.dataset),
        ("task", result.summary.task),
        ("status", status),
        ("trust_score", f"{result.summary.trust_score:.3f}"),
        ("reason_codes", ", ".join(result.summary.reason_codes) or "-"),
        ("skipped_checks", ", ".join(result.summary.skipped_checks) or "-"),
    ]
    if summary_format == "text":
        return " | ".join(f"{key}={value}" for key, value in rows)
    if summary_format == "markdown":
        return markdown_kv_table(rows)
    if summary_format == "json":
        return json.dumps({key: value for key, value in rows}, indent=2)
    raise ValueError("summary-format must be one of: text, markdown, json.")


def _format_compare_summary(summary: CompareSummaryModel, *, summary_format: str) -> str:
    summary_format = summary_format.lower()
    rows = [
        ("session_a", summary.session_a.session_id),
        ("session_b", summary.session_b.session_id),
        ("status", summary.recommendation_status),
        ("trust_score_delta", f"{summary.trust_score_delta:.3f}"),
        ("reason_codes_added", ", ".join(summary.reason_codes_added) or "-"),
        ("reason_codes_removed", ", ".join(summary.reason_codes_removed) or "-"),
        ("regression_reasons", "; ".join(summary.regression_reasons) or "-"),
    ]
    if summary_format == "text":
        return " | ".join(f"{key}={value}" for key, value in rows)
    if summary_format == "markdown":
        return markdown_kv_table(rows)
    if summary_format == "json":
        return json.dumps(summary.model_dump(), indent=2)
    raise ValueError("summary-format must be one of: text, markdown, json.")


def _compare_should_fail(summary: CompareSummaryModel, *, fail_on: str, trust_drop_threshold: float) -> bool:
    fail_on = fail_on.lower()
    if fail_on == "never":
        return False
    if fail_on not in {"regression", "mixed"}:
        raise ValueError("fail-on must be one of: regression, mixed, never.")
    material_trust_drop = summary.trust_score_delta <= -trust_drop_threshold
    material_regression = material_trust_drop or bool(summary.regression_reasons)
    if fail_on == "regression":
        return summary.recommendation_status == "regressed" and material_regression
    return summary.recommendation_status in {"regressed", "mixed"} and (material_regression or summary.recommendation_status == "mixed")


def _format_cli_exception(exc: Exception, *, command: str) -> str:
    if isinstance(exc, ValidationError):
        details = []
        for error in exc.errors():
            loc = ".".join(str(part) for part in error.get("loc", []))
            details.append(f"{loc}: {error.get('msg')}")
        hint = ""
        if command == "ingest":
            hint = " Example: imu.timestamp_col: time_ms, imu.accel_cols: [ax, ay, az], imu.gyro_cols: [gx, gy, gz]."
        return "Invalid config. " + "; ".join(details) + hint
    if isinstance(exc, yaml.YAMLError):
        return f"Invalid YAML config. {exc}"
    message = str(exc)
    if command == "ingest" and "tabular ingest requires --config" in message:
        return message + " Example: imuops ingest tabular data.csv --config mapping.yaml --out output/session."
    if "Missing required columns in tabular source" in message:
        return message + " Update the YAML mapping so the listed columns match the incoming file headers."
    if "Unsupported" in message and "unit" in message:
        return message + " Check the adapter config units and use one of the documented unit aliases in examples/sample_tabular_config.yaml."
    return message


def main() -> None:
    app()


if __name__ == "__main__":
    main()
