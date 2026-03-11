from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

from imuops.utils import slugify


def main() -> int:
    parser = argparse.ArgumentParser(description="Run imuops tabular review from a GitHub Action.")
    parser.add_argument("--data-glob", required=True)
    parser.add_argument("--tabular-config", required=True)
    parser.add_argument("--fail-below", type=float, default=None)
    parser.add_argument("--compare-baseline", default=None)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--comment-mode", default="summary")
    args = parser.parse_args()

    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    data_files = _resolve_data_files(args.data_glob)
    if not data_files:
        raise SystemExit("No input files matched data_glob.")

    session_rows = []
    for data_path in data_files:
        session_slug = slugify(data_path.stem)
        session_dir = report_dir / session_slug
        report_html = session_dir / "report.html"
        _run(
            [
                sys.executable,
                "-m",
                "imuops",
                "ingest",
                "tabular",
                str(data_path),
                "--config",
                str(Path(args.tabular_config).resolve()),
                "--out",
                str(session_dir),
            ]
        )
        audit_cmd = [sys.executable, "-m", "imuops", "audit", str(session_dir), "--summary-format", "json"]
        if args.fail_below is not None:
            audit_cmd.extend(["--fail-below", str(args.fail_below)])
        _run(audit_cmd)
        _run([sys.executable, "-m", "imuops", "report", str(session_dir), "--out", str(report_html)])
        audit_summary = json.loads((session_dir / "audit_summary.json").read_text(encoding="utf-8"))
        session_rows.append(
            {
                "data_path": str(data_path),
                "session_dir": str(session_dir),
                "session_id": audit_summary["session_id"],
                "trust_score": audit_summary["trust_score"],
                "status": audit_summary["status"],
                "reason_codes": audit_summary.get("reason_codes", []),
                "report_html": str(report_html),
                "audit_summary": str(session_dir / "audit_summary.json"),
            }
        )

    session_rows.sort(key=lambda row: (row["trust_score"], row["session_id"]))
    worst = session_rows[0]
    compare_json = ""
    if args.compare_baseline:
        compare_baseline = Path(args.compare_baseline).resolve()
        compare_html = report_dir / "compare.html"
        compare_json_path = report_dir / "compare.json"
        _run(
            [
                sys.executable,
                "-m",
                "imuops",
                "compare",
                str(compare_baseline),
                worst["session_dir"],
                "--out",
                str(compare_html),
                "--json-out",
                str(compare_json_path),
                "--summary-format",
                "json",
            ]
        )
        compare_json = str(compare_json_path)

    summary_path = report_dir / "action_summary.json"
    payload = {
        "sessions": session_rows,
        "worst_session": worst,
        "compare_json": compare_json,
    }
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    comment_markdown = _comment_markdown(session_rows, compare_json=compare_json, comment_mode=args.comment_mode)
    _set_output("trust_score", f"{worst['trust_score']:.3f}")
    _set_output("status", worst["status"])
    _set_output("summary_json", str(summary_path))
    _set_output("report_html", worst["report_html"])
    _set_output("compare_json", compare_json)
    _set_output("comment_markdown", comment_markdown)
    return 0


def _resolve_data_files(pattern_expr: str) -> list[Path]:
    matches = []
    for raw_pattern in pattern_expr.replace("\r", "\n").split("\n"):
        for pattern in raw_pattern.split("|"):
            normalized = pattern.strip()
            if not normalized:
                continue
            candidate = Path(normalized)
            if candidate.exists():
                matches.append(candidate.resolve())
                continue
            matches.extend(Path(path).resolve() for path in glob.glob(normalized, recursive=True))
    deduped = []
    seen = set()
    for match in sorted(matches):
        if match in seen or not match.is_file():
            continue
        seen.add(match)
        deduped.append(match)
    return deduped


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


def _comment_markdown(session_rows: list[dict[str, object]], *, compare_json: str, comment_mode: str) -> str:
    if comment_mode == "off":
        return ""
    lines = [
        "## imuops PR review",
        "",
        "| session | trust_score | status | reason_codes | report |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for row in session_rows:
        lines.append(
            f"| `{row['session_id']}` | `{row['trust_score']:.3f}` | `{row['status']}` | "
            f"`{', '.join(row['reason_codes']) or '-'}` | `{Path(str(row['report_html'])).name}` |"
        )
    if compare_json:
        lines.extend(["", f"Compare artifact: `{Path(compare_json).name}`"])
    if comment_mode == "full":
        lines.extend(["", "Artifacts are uploaded in the workflow run for HTML and JSON review."])
    return "\n".join(lines)


def _set_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    delimiter = f"imuops_{name}"
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


if __name__ == "__main__":
    raise SystemExit(main())
