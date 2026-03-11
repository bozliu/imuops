#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMUOPS_BIN="${IMUOPS_BIN:-imuops}"

SOURCE_SESSION="${1:-$ROOT/output/sample_tabular_demo}"
PRESET="${2:-packet_loss_5}"
OUT_DIR="${3:-$ROOT/output/sample_tabular_demo__${PRESET}}"
COMPARE_OUT="${4:-$ROOT/output/sample_tabular_compare.html}"

if [[ ! -f "$SOURCE_SESSION/session.json" ]]; then
  echo "Source session not found at $SOURCE_SESSION. Run bash examples/run_tabular_demo.sh first." >&2
  exit 1
fi

"$IMUOPS_BIN" corrupt "$SOURCE_SESSION" --preset "$PRESET" --out "$OUT_DIR"
"$IMUOPS_BIN" audit "$OUT_DIR"
"$IMUOPS_BIN" report "$OUT_DIR" --out "$OUT_DIR/report.html"
"$IMUOPS_BIN" compare "$SOURCE_SESSION" "$OUT_DIR" --out "$COMPARE_OUT"

echo "Corruption report ready at $OUT_DIR/report.html"
echo "Compare report ready at $COMPARE_OUT"
