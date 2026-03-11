#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMUOPS_BIN="${IMUOPS_BIN:-imuops}"

INPUT_PATH="${1:-$ROOT/examples/sample_tabular_imu.csv}"
CONFIG_PATH="${2:-$ROOT/examples/sample_tabular_config.yaml}"
SESSION_DIR="${3:-$ROOT/output/sample_tabular_demo}"

"$IMUOPS_BIN" ingest tabular "$INPUT_PATH" --config "$CONFIG_PATH" --out "$SESSION_DIR"
"$IMUOPS_BIN" audit "$SESSION_DIR" --summary-format markdown
"$IMUOPS_BIN" report "$SESSION_DIR" --out "$SESSION_DIR/report.html"

echo "Tabular report ready at $SESSION_DIR/report.html"
