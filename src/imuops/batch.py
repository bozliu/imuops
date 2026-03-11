"""Batch audit and reporting helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.offline.offline import get_plotlyjs

from imuops.audit import run_audit
from imuops.models import BatchRowModel, BatchSummaryModel, ReasonCountModel
from imuops.reporting.theme import apply_chart_style, build_shell_css
from imuops.session import load_session
from imuops.utils import dump_json, iter_session_dirs, load_json


@dataclass
class BatchAuditResult:
    summary: BatchSummaryModel


def batch_audit_sessions(root: Path, out_dir: Path, config: dict[str, Any]) -> BatchAuditResult:
    session_dirs = iter_session_dirs(root)
    rows = []
    for session_dir in session_dirs:
        session = load_session(session_dir, lazy=True)
        audit_result = run_audit(session, config)
        dump_json(session_dir / "issues.json", audit_result.to_dict())
        dump_json(session_dir / "audit_summary.json", audit_result.summary)
        rows.append(
            {
                "session_dir": str(session_dir),
                "session_id": audit_result.summary.session_id,
                "dataset": audit_result.summary.dataset,
                "task": audit_result.summary.task,
                "trust_score": audit_result.summary.trust_score,
                "status": audit_result.summary.status,
                "reason_codes": audit_result.summary.reason_codes,
            }
        )
    rows.sort(key=lambda item: (item["trust_score"], item["session_id"]))
    counts = {"pass": 0, "warning": 0, "fail": 0}
    reason_counts: dict[str, int] = {}
    summary_rows: list[BatchRowModel] = []
    for index, row in enumerate(rows, start=1):
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        for code in row["reason_codes"]:
            reason_counts[code] = reason_counts.get(code, 0) + 1
        summary_rows.append(BatchRowModel(**row, rank=index))
    reason_rows = [
        ReasonCountModel(code=code, count=count)
        for code, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    summary = BatchSummaryModel(
        session_count=len(summary_rows),
        counts=counts,
        rows=summary_rows,
        top_reason_codes={row.code: row.count for row in reason_rows[:10]},
        reason_code_rows=reason_rows,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    dump_json(out_dir / "batch_summary.json", summary)
    dump_json(out_dir / "batch_audit_summary.json", summary)
    _write_batch_rankings_csv(summary, out_dir / "batch_rankings.csv")
    return BatchAuditResult(summary=summary)


def load_batch_summary(path: Path) -> BatchSummaryModel:
    return BatchSummaryModel.model_validate(load_json(path))


def build_batch_report(batch_summary: BatchAuditResult | BatchSummaryModel, out_path: Path) -> Path:
    summary = batch_summary.summary if isinstance(batch_summary, BatchAuditResult) else batch_summary
    rows = summary.rows
    best_row = rows[-1] if rows else None
    worst_row = rows[0] if rows else None
    top_reason = summary.reason_code_rows[0] if summary.reason_code_rows else None
    fig = go.Figure(go.Bar(x=[row.session_id for row in rows], y=[row.trust_score for row in rows], marker_color="#1d4ed8"))
    apply_chart_style(fig, title="Batch trust scores", height=320, xaxis_title="session", yaxis_title="trust score")
    table_rows = "".join(
        (
            f"<tr><td>{row.rank}</td><td>{row.session_id}</td><td>{row.dataset}</td><td>{row.task}</td>"
            f"<td>{row.status}</td><td>{row.trust_score:.3f}</td><td>{', '.join(row.reason_codes) or '-'}</td></tr>"
        )
        for row in rows
    )
    trend_rows = "".join(
        f"<tr><td>{reason.code}</td><td>{reason.count}</td></tr>"
        for reason in summary.reason_code_rows[:10]
    )
    shell_css = build_shell_css(
        hero_end="#134e4a",
        accent="#1d4ed8",
        accent_soft="#dbeafe",
        warm="#a87112",
        danger="#b63a3a",
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>imuops batch report</title>
  <style>
    {shell_css}
    .overview-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 0.9rem;
      margin-bottom: 1rem;
    }}
    .metric-label {{ color: var(--muted); text-transform: uppercase; letter-spacing: 0.09em; font-size: 0.76rem; font-weight: 700; margin-bottom: 0.45rem; }}
    .metric-value {{ font-size: 1.95rem; font-weight: 800; line-height: 1; margin-bottom: 0.35rem; }}
    .metric-note {{ color: var(--muted); font-size: 0.95rem; }}
  </style>
  <script type="text/javascript">{get_plotlyjs()}</script>
</head>
<body>
  <main>
    <section class="hero" id="batch-poster">
      <div class="hero-grid">
        <div class="hero-copy">
          <div class="hero-kicker">Fleet QA view</div>
          <h1>imuops batch report</h1>
          <p>Rank sessions by trust score, expose recurring failures, and hand CI a stable machine-readable summary.</p>
        </div>
        <div class="panel panel-strong">
          <div class="metric-label">Top recurring reason</div>
          <div class="metric-value">{top_reason.code if top_reason else 'None'}</div>
          <p class="metric-note">{top_reason.count if top_reason else 0} sessions surfaced the most common failure mode.</p>
        </div>
      </div>
    </section>

    <section class="overview-grid section">
      <div class="panel">
        <div class="metric-label">Sessions</div>
        <div class="metric-value">{summary.session_count}</div>
        <p class="metric-note">Total canonical sessions in this batch.</p>
      </div>
      <div class="panel">
        <div class="metric-label">Pass</div>
        <div class="metric-value">{summary.counts.get('pass', 0)}</div>
        <p class="metric-note">Healthy sessions ready for downstream work.</p>
      </div>
      <div class="panel">
        <div class="metric-label">Warning</div>
        <div class="metric-value">{summary.counts.get('warning', 0)}</div>
        <p class="metric-note">Sessions that need reviewer attention.</p>
      </div>
      <div class="panel">
        <div class="metric-label">Fail</div>
        <div class="metric-value">{summary.counts.get('fail', 0)}</div>
        <p class="metric-note">Sessions that should not become baselines yet.</p>
      </div>
    </section>

    <section class="decision-grid capture-poster" id="batch-overview">
      <section class="panel">
        {fig.to_html(full_html=False, include_plotlyjs=False)}
      </section>
      <section class="panel">
        <div class="section-label">Recurring failure reasons</div>
        <div class="table-shell">
        <table>
          <tr><th>Reason code</th><th>Count</th></tr>
          {trend_rows or '<tr><td colspan="2">No recurring failures detected.</td></tr>'}
        </table>
        </div>
        <div class="section-label" style="margin-top: 1rem;">Best and worst sessions</div>
        <div class="table-shell">
          <table>
            <tr><th></th><th>Session</th><th>Trust score</th><th>Status</th></tr>
            <tr><th>Worst</th><td>{worst_row.session_id if worst_row else '-'}</td><td>{f"{worst_row.trust_score:.3f}" if worst_row else '-'}</td><td>{worst_row.status if worst_row else '-'}</td></tr>
            <tr><th>Best</th><td>{best_row.session_id if best_row else '-'}</td><td>{f"{best_row.trust_score:.3f}" if best_row else '-'}</td><td>{best_row.status if best_row else '-'}</td></tr>
          </table>
        </div>
      </section>
    </section>
    <section class="panel section" id="batch-ranking">
      <div class="section-label">Session ranking</div>
      <div class="table-shell">
      <table>
        <tr><th>Rank</th><th>Session</th><th>Dataset</th><th>Task</th><th>Status</th><th>Trust score</th><th>Reason codes</th></tr>
        {table_rows}
      </table>
      </div>
    </section>
  </main>
</body>
</html>"""
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _write_batch_rankings_csv(summary: BatchSummaryModel, path: Path) -> None:
    frame = pd.DataFrame(
        [
            {
                "rank": row.rank,
                "session_id": row.session_id,
                "dataset": row.dataset,
                "task": row.task,
                "status": row.status,
                "trust_score": row.trust_score,
                "reason_codes": ",".join(row.reason_codes),
                "session_dir": row.session_dir,
            }
            for row in summary.rows
        ]
    )
    frame.to_csv(path, index=False)
