#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMUOPS_BIN="${IMUOPS_BIN:-imuops}"

INPUT_PATH="${1:-}"
if [[ -z "$INPUT_PATH" ]]; then
  echo "Usage: bash examples/run_wisdm_demo.sh /path/to/WISDM_raw.txt [out_dir]" >&2
  exit 1
fi

SESSION_DIR="${2:-$ROOT/output/wisdm_demo}"

"$IMUOPS_BIN" ingest wisdm "$INPUT_PATH" --out "$SESSION_DIR"
"$IMUOPS_BIN" audit "$SESSION_DIR"
"$IMUOPS_BIN" benchmark "$SESSION_DIR" --task har
"$IMUOPS_BIN" report "$SESSION_DIR" --out "$SESSION_DIR/report.html"

echo "Report ready at $SESSION_DIR/report.html"
