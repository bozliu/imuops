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
    fig = go.Figure(go.Bar(x=[row.session_id for row in rows], y=[row.trust_score for row in rows], marker_color="#1d4ed8"))
    fig.update_layout(template="plotly_white", title="Batch trust scores", height=320, margin=dict(l=40, r=20, t=40, b=40))
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
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>imuops batch report</title>
  <style>
    :root {{
      --bg: #f7f7f3;
      --panel: #ffffff;
      --ink: #102220;
      --muted: #51615f;
      --line: #d7ddd9;
      --accent: #1d4ed8;
      --accent-soft: #dbeafe;
      --warn: #b45309;
    }}
    body {{ font-family: "Avenir Next", "Segoe UI", sans-serif; margin: 0; background:
      radial-gradient(circle at top left, #fef3c7 0, transparent 32%),
      radial-gradient(circle at top right, #dbeafe 0, transparent 28%),
      var(--bg); color: var(--ink); }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
    .hero {{ background: linear-gradient(135deg, #0f172a, #134e4a); color: white; border-radius: 20px; padding: 1.4rem 1.6rem; margin-bottom: 1rem; }}
    .hero p {{ color: #dbeafe; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem; }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 1rem 1.1rem; margin-bottom: 1rem; box-shadow: 0 14px 30px rgba(15, 23, 42, 0.05); }}
    .pill {{ display: inline-block; background: var(--accent-soft); color: var(--accent); border-radius: 999px; padding: 0.25rem 0.7rem; margin: 0 0.4rem 0.4rem 0; font-size: 0.9rem; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 0.7rem 0.55rem; text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; }}
  </style>
  <script type="text/javascript">{get_plotlyjs()}</script>
</head>
<body>
  <main>
    <section class="hero">
      <h1>imuops batch report</h1>
      <p>Rank sessions by trust score, expose recurring failures, and hand CI a stable machine-readable summary.</p>
      <div>
        <span class="pill">sessions={summary.session_count}</span>
        <span class="pill">pass={summary.counts.get('pass', 0)}</span>
        <span class="pill">warning={summary.counts.get('warning', 0)}</span>
        <span class="pill">fail={summary.counts.get('fail', 0)}</span>
      </div>
    </section>
    <div class="grid">
      <section class="card">{fig.to_html(full_html=False, include_plotlyjs=False)}</section>
      <section class="card">
        <h2>Recurring failure reasons</h2>
        <table>
          <tr><th>Reason code</th><th>Count</th></tr>
          {trend_rows or '<tr><td colspan="2">No recurring failures detected.</td></tr>'}
        </table>
      </section>
    </div>
    <section class="card">
      <h2>Session ranking</h2>
      <table>
        <tr><th>Rank</th><th>Session</th><th>Dataset</th><th>Task</th><th>Status</th><th>Trust score</th><th>Reason codes</th></tr>
        {table_rows}
      </table>
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
