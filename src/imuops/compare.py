"""Compare two canonical sessions and emit HTML and JSON diff reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.offline.offline import get_plotlyjs

from imuops.audit import AuditResult, run_audit
from imuops.benchmark import BenchmarkResult, load_existing_benchmark
from imuops.models import CompareSessionModel, CompareSummaryModel
from imuops.replay import ReplayResult
from imuops.reporting import load_existing_replays
from imuops.session import SessionBundle
from imuops.utils import dump_json, redact_path


@dataclass
class CompareResult:
    summary: CompareSummaryModel
    html_path: Path
    json_path: Path


def build_compare_report(
    session_a: SessionBundle,
    session_b: SessionBundle,
    *,
    config: dict[str, Any],
    out_path: Path,
    json_path: Path | None = None,
    redact_source_path: bool = False,
    redact_subject_id: bool = False,
) -> CompareResult:
    audit_a = _load_or_run_audit(session_a, config)
    audit_b = _load_or_run_audit(session_b, config)
    replays_a = {item.baseline: item for item in load_existing_replays(Path(session_a.artifacts["session_dir"]))}
    replays_b = {item.baseline: item for item in load_existing_replays(Path(session_b.artifacts["session_dir"]))}
    benchmark_a = load_existing_benchmark(Path(session_a.artifacts["session_dir"]))
    benchmark_b = load_existing_benchmark(Path(session_b.artifacts["session_dir"]))
    trust_delta = audit_b.summary.trust_score - audit_a.summary.trust_score
    metadata_a = _session_meta(session_a, redact_source_path, redact_subject_id)
    metadata_b = _session_meta(session_b, redact_source_path, redact_subject_id)
    reason_codes_added = sorted(set(audit_b.summary.reason_codes) - set(audit_a.summary.reason_codes))
    reason_codes_removed = sorted(set(audit_a.summary.reason_codes) - set(audit_b.summary.reason_codes))
    replay_metric_deltas = _metric_deltas(replays_a, replays_b)
    benchmark_metric_deltas = _benchmark_deltas(benchmark_a, benchmark_b)
    regression_reasons, improvement_reasons = _delta_reasons(
        trust_delta=trust_delta,
        reason_codes_added=reason_codes_added,
        reason_codes_removed=reason_codes_removed,
        replay_metric_deltas=replay_metric_deltas,
        benchmark_metric_deltas=benchmark_metric_deltas,
    )
    recommendation_status, recommendation_summary = _recommendation_summary(
        trust_delta=trust_delta,
        regression_reasons=regression_reasons,
        improvement_reasons=improvement_reasons,
    )
    summary = CompareSummaryModel(
        session_a=metadata_a,
        session_b=metadata_b,
        trust_score_a=audit_a.summary.trust_score,
        trust_score_b=audit_b.summary.trust_score,
        trust_score_delta=trust_delta,
        reason_codes_added=reason_codes_added,
        reason_codes_removed=reason_codes_removed,
        replay_metric_deltas=replay_metric_deltas,
        benchmark_metric_deltas=benchmark_metric_deltas,
        metadata_differences=_metadata_differences(metadata_a.model_dump(), metadata_b.model_dump()),
        audit_formula={
            "window_formula": audit_b.summary.window_formula or audit_a.summary.window_formula,
            "session_formula": audit_b.summary.session_formula or audit_a.summary.session_formula,
            "weights": audit_b.summary.weight_profile or audit_a.summary.weight_profile,
            "thresholds": audit_b.summary.thresholds or audit_a.summary.thresholds,
        },
        recommendation_status=recommendation_status,
        recommendation_summary=recommendation_summary,
        regression_reasons=regression_reasons,
        improvement_reasons=improvement_reasons,
    )
    html = _render_compare_html(summary)
    out_path.write_text(html, encoding="utf-8")
    resolved_json_path = json_path or out_path.with_suffix(".json")
    dump_json(resolved_json_path, summary)
    return CompareResult(summary=summary, html_path=out_path, json_path=resolved_json_path)


def _load_or_run_audit(session: SessionBundle, config: dict[str, Any]) -> AuditResult:
    session_dir = Path(session.artifacts["session_dir"])
    issues_path = session_dir / "issues.json"
    if issues_path.exists():
        return AuditResult.from_dict(config, session, issues_path)
    return run_audit(session, config)


def _session_meta(session: SessionBundle, redact_source_path: bool, redact_subject_id: bool) -> CompareSessionModel:
    source_path = session.metadata.source_path
    subject_id = session.metadata.subject_id
    return CompareSessionModel(
        session_id=session.metadata.session_id,
        dataset=session.metadata.dataset,
        task=session.metadata.task,
        source_path=redact_path(source_path) if redact_source_path else source_path,
        subject_id="-" if redact_subject_id and subject_id else subject_id,
    )


def _metric_deltas(replays_a: dict[str, ReplayResult], replays_b: dict[str, ReplayResult]) -> dict[str, dict[str, float]]:
    deltas: dict[str, dict[str, float]] = {}
    for baseline in sorted(set(replays_a) & set(replays_b)):
        delta = _numeric_metric_delta(replays_a[baseline].metrics, replays_b[baseline].metrics)
        if delta:
            deltas[baseline] = delta
    return deltas


def _benchmark_deltas(benchmark_a: BenchmarkResult | None, benchmark_b: BenchmarkResult | None) -> dict[str, dict[str, float]]:
    if benchmark_a is None or benchmark_b is None:
        return {}
    by_name_a = {baseline.baseline: baseline.metrics for baseline in benchmark_a.summary.baselines}
    by_name_b = {baseline.baseline: baseline.metrics for baseline in benchmark_b.summary.baselines}
    deltas: dict[str, dict[str, float]] = {}
    for baseline in sorted(set(by_name_a) & set(by_name_b)):
        delta = _numeric_metric_delta(by_name_a[baseline], by_name_b[baseline])
        if delta:
            deltas[baseline] = delta
    return deltas


def _numeric_metric_delta(metrics_a: dict[str, Any], metrics_b: dict[str, Any]) -> dict[str, float]:
    delta = {}
    for key in sorted(set(metrics_a) & set(metrics_b)):
        value_a = metrics_a[key]
        value_b = metrics_b[key]
        if isinstance(value_a, (int, float)) and isinstance(value_b, (int, float)):
            delta[key] = float(value_b) - float(value_a)
    return delta


def _metadata_differences(meta_a: dict[str, Any], meta_b: dict[str, Any]) -> dict[str, dict[str, Any]]:
    differences: dict[str, dict[str, Any]] = {}
    for key in sorted(set(meta_a) | set(meta_b)):
        if meta_a.get(key) != meta_b.get(key):
            differences[key] = {"session_a": meta_a.get(key), "session_b": meta_b.get(key)}
    return differences


def _delta_reasons(
    *,
    trust_delta: float,
    reason_codes_added: list[str],
    reason_codes_removed: list[str],
    replay_metric_deltas: dict[str, dict[str, float]],
    benchmark_metric_deltas: dict[str, dict[str, float]],
) -> tuple[list[str], list[str]]:
    regression_reasons = []
    improvement_reasons = []
    if trust_delta <= -0.03:
        regression_reasons.append(f"trust_score dropped by {abs(trust_delta):.3f}")
    elif trust_delta >= 0.03:
        improvement_reasons.append(f"trust_score improved by {trust_delta:.3f}")
    if reason_codes_added:
        regression_reasons.append(f"new reason codes: {', '.join(reason_codes_added)}")
    if reason_codes_removed:
        improvement_reasons.append(f"removed reason codes: {', '.join(reason_codes_removed)}")
    regression_reasons.extend(_metric_direction_reasons(replay_metric_deltas, category="replay", mode="regression"))
    improvement_reasons.extend(_metric_direction_reasons(replay_metric_deltas, category="replay", mode="improvement"))
    regression_reasons.extend(_metric_direction_reasons(benchmark_metric_deltas, category="benchmark", mode="regression"))
    improvement_reasons.extend(_metric_direction_reasons(benchmark_metric_deltas, category="benchmark", mode="improvement"))
    return regression_reasons, improvement_reasons


def _metric_direction_reasons(metric_groups: dict[str, dict[str, float]], *, category: str, mode: str) -> list[str]:
    reasons = []
    for baseline, deltas in metric_groups.items():
        for metric, delta in deltas.items():
            direction = _metric_direction(metric)
            if direction == "lower_is_better" and delta > 0:
                statement = f"{category} {baseline} {metric} worsened by {delta:.3f}"
            elif direction == "higher_is_better" and delta < 0:
                statement = f"{category} {baseline} {metric} worsened by {abs(delta):.3f}"
            elif direction == "lower_is_better" and delta < 0:
                statement = f"{category} {baseline} {metric} improved by {abs(delta):.3f}"
            elif direction == "higher_is_better" and delta > 0:
                statement = f"{category} {baseline} {metric} improved by {delta:.3f}"
            else:
                continue
            if "worsened" in statement and mode == "regression":
                reasons.append(statement)
            if "improved" in statement and mode == "improvement":
                reasons.append(statement)
    return reasons


def _metric_direction(metric_name: str) -> str:
    normalized = metric_name.lower()
    if any(token in normalized for token in ("rmse", "drift", "error", "loss")):
        return "lower_is_better"
    if any(token in normalized for token in ("accuracy", "f1", "score", "ratio")):
        return "higher_is_better"
    return "unknown"


def _recommendation_summary(*, trust_delta: float, regression_reasons: list[str], improvement_reasons: list[str]) -> tuple[str, str]:
    if regression_reasons and not improvement_reasons:
        return "regressed", "Session B regressed relative to session A. Review the regression reasons before merging it into a QA baseline."
    if improvement_reasons and not regression_reasons:
        return "improved", "Session B looks healthier overall. The trust score and downstream evidence both moved in the right direction."
    if regression_reasons and improvement_reasons:
        return "mixed", "Session B shows mixed signals. Some quality indicators improved, but there are still regressions worth review."
    if trust_delta > 0:
        return "improved", "Session B edges out session A on trust score, but the deltas are small."
    if trust_delta < 0:
        return "regressed", "Session B lost trust score relative to session A, even though the secondary signals are limited."
    return "mixed", "Session A and B look effectively tied on the current compare signals."


def _render_compare_html(summary: CompareSummaryModel) -> str:
    trust_fig = go.Figure(
        go.Bar(
            x=["session_a", "session_b", "delta"],
            y=[summary.trust_score_a, summary.trust_score_b, summary.trust_score_delta],
            marker_color=["#0f766e", "#2563eb", "#dc2626"],
        )
    )
    trust_fig.update_layout(template="plotly_white", title="Trust score comparison", height=320, margin=dict(l=40, r=20, t=40, b=40))
    regression_rows = "".join(f"<li>{reason}</li>" for reason in summary.regression_reasons) or "<li>No regression reasons detected.</li>"
    improvement_rows = "".join(f"<li>{reason}</li>" for reason in summary.improvement_reasons) or "<li>No improvement reasons detected.</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>imuops compare report</title>
  <style>
    :root {{
      --bg: #f5f6ef;
      --panel: #ffffff;
      --ink: #102220;
      --muted: #556764;
      --line: #d4ddd6;
      --accent: #2563eb;
      --accent-2: #0f766e;
      --danger: #b91c1c;
    }}
    body {{ margin: 0; font-family: "Avenir Next", "Segoe UI", sans-serif; background:
      radial-gradient(circle at top left, #dbeafe 0, transparent 28%),
      radial-gradient(circle at bottom right, #dcfce7 0, transparent 25%),
      var(--bg); color: var(--ink); }}
    main {{ max-width: 1220px; margin: 0 auto; padding: 2rem; }}
    .hero {{ background: linear-gradient(135deg, #111827, #1d4ed8); color: white; border-radius: 24px; padding: 1.5rem 1.7rem; margin-bottom: 1rem; }}
    .hero p {{ color: #dbeafe; max-width: 60rem; }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 0.25rem 0.7rem; margin: 0 0.4rem 0.4rem 0; background: rgba(255,255,255,0.14); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1rem; }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 1rem 1.1rem; margin-bottom: 1rem; box-shadow: 0 14px 30px rgba(15, 23, 42, 0.05); }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 0.65rem 0.55rem; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; }}
    ul {{ margin: 0.5rem 0 0 1.25rem; padding: 0; }}
    pre {{ white-space: pre-wrap; background: #f8fafc; border-radius: 12px; padding: 0.8rem; overflow-x: auto; }}
  </style>
  <script type="text/javascript">{get_plotlyjs()}</script>
</head>
<body>
  <main>
    <section class="hero">
      <h1>imuops compare report</h1>
      <p>Use this view to decide whether a new IMU session, preprocessing revision, or firmware drop is healthier than the baseline it replaces.</p>
      <div>
        <span class="pill">status={summary.recommendation_status}</span>
        <span class="pill">trust_delta={summary.trust_score_delta:.3f}</span>
      </div>
      <p><strong>Recommendation:</strong> {summary.recommendation_summary}</p>
    </section>
    <section class="card">
      <h2>Session metadata</h2>
      <table>
        <tr><th></th><th>Session A</th><th>Session B</th></tr>
        <tr><th>Session ID</th><td>{summary.session_a.session_id}</td><td>{summary.session_b.session_id}</td></tr>
        <tr><th>Dataset</th><td>{summary.session_a.dataset}</td><td>{summary.session_b.dataset}</td></tr>
        <tr><th>Task</th><td>{summary.session_a.task}</td><td>{summary.session_b.task}</td></tr>
        <tr><th>Source path</th><td>{summary.session_a.source_path}</td><td>{summary.session_b.source_path}</td></tr>
        <tr><th>Subject ID</th><td>{summary.session_a.subject_id or '-'}</td><td>{summary.session_b.subject_id or '-'}</td></tr>
      </table>
    </section>
    <section class="card">{trust_fig.to_html(full_html=False, include_plotlyjs=False)}</section>
    <div class="grid">
      <section class="card">
        <h2>Why it regressed</h2>
        <ul>{regression_rows}</ul>
      </section>
      <section class="card">
        <h2>Why it improved</h2>
        <ul>{improvement_rows}</ul>
      </section>
    </div>
    <div class="grid">
      <section class="card">
        <h2>Reason-code delta</h2>
        <table>
          <tr><th>Added in session B</th><td>{", ".join(summary.reason_codes_added) or "-"}</td></tr>
          <tr><th>Removed in session B</th><td>{", ".join(summary.reason_codes_removed) or "-"}</td></tr>
        </table>
      </section>
      <section class="card">
        <h2>Metadata differences</h2>
        <pre>{summary.metadata_differences}</pre>
      </section>
    </div>
    <div class="grid">
      <section class="card">
        <h2>Replay metric deltas</h2>
        <pre>{summary.replay_metric_deltas}</pre>
      </section>
      <section class="card">
        <h2>Benchmark metric deltas</h2>
        <pre>{summary.benchmark_metric_deltas}</pre>
      </section>
    </div>
    <section class="card">
      <h2>Trust-score contract</h2>
      <pre>{summary.audit_formula}</pre>
    </section>
  </main>
</body>
</html>"""
