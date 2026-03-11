"""Shared visual theme helpers for HTML reports and release captures."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go


def build_shell_css(
    *,
    hero_end: str,
    accent: str,
    accent_soft: str,
    warm: str,
    danger: str,
) -> str:
    return f"""
    :root {{
      --page: #e7ede7;
      --panel: rgba(252, 253, 249, 0.96);
      --panel-strong: #f6faf5;
      --ink: #132321;
      --muted: #55655f;
      --line: rgba(19, 35, 33, 0.1);
      --shadow: 0 18px 48px rgba(12, 20, 18, 0.08);
      --accent: {accent};
      --accent-soft: {accent_soft};
      --warm: {warm};
      --danger: {danger};
      --hero-start: #0f1f1c;
      --hero-end: {hero_end};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(37, 99, 235, 0.08) 0, transparent 28%),
        radial-gradient(circle at bottom right, rgba(15, 118, 110, 0.1) 0, transparent 30%),
        linear-gradient(180deg, #edf3ed 0%, #e7ede7 100%);
    }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }}
    h1, h2, h3 {{ margin: 0 0 0.6rem; color: var(--ink); line-height: 1.1; }}
    p {{ margin: 0 0 0.85rem; line-height: 1.6; }}
    code {{
      background: rgba(15, 118, 110, 0.08);
      color: #0f3f3b;
      padding: 0.15rem 0.38rem;
      border-radius: 6px;
      font-size: 0.95em;
    }}
    pre {{
      margin: 0;
      padding: 0.95rem 1rem;
      border-radius: 14px;
      background: #eef3ee;
      border: 1px solid rgba(19, 35, 33, 0.08);
      white-space: pre-wrap;
      overflow-x: auto;
      line-height: 1.5;
      font-size: 0.92rem;
    }}
    .hero {{
      background: linear-gradient(140deg, var(--hero-start), var(--hero-end));
      color: white;
      border-radius: 28px;
      padding: 1.5rem 1.6rem;
      margin-bottom: 1.1rem;
      box-shadow: 0 28px 60px rgba(15, 23, 42, 0.16);
    }}
    .hero h1 {{ color: white; font-size: 2rem; }}
    .hero .muted {{ color: rgba(233, 244, 240, 0.88); }}
    .hero-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.7fr) minmax(260px, 1fr);
      gap: 1rem;
      align-items: end;
    }}
    .hero-kicker {{
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.78rem;
      font-weight: 700;
      color: rgba(233, 244, 240, 0.7);
      margin-bottom: 0.5rem;
    }}
    .hero-copy {{ max-width: 50rem; }}
    .pill-row {{ display: flex; flex-wrap: wrap; gap: 0.5rem; }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      border-radius: 999px;
      padding: 0.34rem 0.72rem;
      background: rgba(255, 255, 255, 0.14);
      color: white;
      font-size: 0.92rem;
      font-weight: 600;
    }}
    .status-pill {{
      border-radius: 999px;
      padding: 0.28rem 0.72rem;
      font-size: 0.9rem;
      font-weight: 700;
      display: inline-flex;
      align-items: center;
    }}
    .status-pass {{ background: rgba(15, 118, 110, 0.14); color: #0f6c61; }}
    .status-warning {{ background: rgba(180, 83, 9, 0.14); color: #9a650d; }}
    .status-fail {{ background: rgba(185, 28, 28, 0.14); color: #a52929; }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 0.9rem;
      margin-bottom: 1rem;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      box-shadow: var(--shadow);
      padding: 1.15rem 1.2rem;
    }}
    .panel-strong {{ background: linear-gradient(180deg, rgba(252, 253, 249, 0.98), rgba(244, 248, 243, 0.98)); }}
    .metric-label {{
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.09em;
      font-size: 0.76rem;
      font-weight: 700;
      margin-bottom: 0.45rem;
    }}
    .metric-value {{
      font-size: 2rem;
      line-height: 1;
      font-weight: 800;
      margin-bottom: 0.35rem;
    }}
    .metric-note {{ color: var(--muted); font-size: 0.95rem; }}
    .metric-subvalue {{
      font-size: 1.05rem;
      font-weight: 700;
      color: var(--ink);
      margin-top: 0.35rem;
    }}
    .decision-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
      gap: 1rem;
      margin-bottom: 1rem;
    }}
    .decision-stack {{
      display: grid;
      gap: 0.9rem;
    }}
    .section-label {{
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.1em;
      font-size: 0.76rem;
      font-weight: 700;
      margin-bottom: 0.55rem;
    }}
    .reason-list, .compact-list {{
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 0.7rem;
    }}
    .reason-list li, .compact-list li {{
      padding: 0.8rem 0.9rem;
      border-radius: 16px;
      background: var(--panel-strong);
      border: 1px solid rgba(19, 35, 33, 0.08);
    }}
    .reason-title {{ font-weight: 700; margin-bottom: 0.25rem; }}
    .muted {{ color: var(--muted); }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
      gap: 1rem;
      margin-bottom: 1rem;
    }}
    .section {{
      margin-bottom: 1rem;
    }}
    .table-shell {{
      overflow-x: auto;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(249, 251, 247, 0.96);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: transparent;
      font-size: 0.97rem;
    }}
    th, td {{
      padding: 0.72rem 0.75rem;
      border-bottom: 1px solid rgba(19, 35, 33, 0.08);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 700;
      font-size: 0.9rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    .highlight {{
      color: var(--accent);
      font-weight: 700;
    }}
    .warning-text {{ color: var(--warm); font-weight: 700; }}
    .danger-text {{ color: var(--danger); font-weight: 700; }}
    details {{
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(250, 252, 248, 0.96);
      padding: 0.95rem 1rem;
    }}
    details[open] {{ box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5); }}
    summary {{
      cursor: pointer;
      font-weight: 700;
      color: var(--ink);
      list-style: none;
    }}
    summary::-webkit-details-marker {{ display: none; }}
    summary::after {{
      content: " +";
      color: var(--muted);
      font-weight: 600;
    }}
    details[open] summary::after {{ content: " -"; }}
    .details-body {{ margin-top: 0.85rem; display: grid; gap: 0.85rem; }}
    .capture-poster {{ margin-bottom: 1rem; }}
    @media (max-width: 900px) {{
      .hero-grid, .decision-grid {{ grid-template-columns: 1fr; }}
      .metric-value {{ font-size: 1.7rem; }}
      main {{ padding: 1rem 0.9rem 2rem; }}
    }}
    """


def apply_chart_style(
    fig: go.Figure,
    *,
    title: str,
    height: int = 320,
    xaxis_title: str | None = None,
    yaxis_title: str | None = None,
    yaxis: dict[str, Any] | None = None,
) -> go.Figure:
    axis_style = dict(
        gridcolor="#d6ded6",
        zerolinecolor="#c5d0c7",
        linecolor="#b9c6bd",
        tickfont=dict(size=12, color="#28413b"),
        title_font=dict(size=13, color="#28413b"),
    )
    fig.update_layout(
        template="plotly_white",
        title=dict(text=title, font=dict(size=20, color="#132321")),
        height=height,
        margin=dict(l=42, r=18, t=52, b=42),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#f4f7f2",
        font=dict(color="#132321", family='"Avenir Next", "Segoe UI", sans-serif'),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=12)),
    )
    fig.update_xaxes(title=xaxis_title, **axis_style)
    fig.update_yaxes(title=yaxis_title, **axis_style)
    if yaxis:
        fig.update_yaxes(**yaxis)
    return fig
