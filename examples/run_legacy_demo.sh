#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python}"
IMUOPS_BIN="${IMUOPS_BIN:-imuops}"
SOURCE_LOG="${1:-$ROOT/../Research/Code/test_data/TEST1.TXT}"
SESSION_DIR="${2:-$ROOT/output/legacy_test1}"

mkdir -p "$ROOT/output"

echo "Running local contrib demo for legacy_arduino. This path is not part of the public alpha quickstart."

"$PYTHON" - <<PY
from pathlib import Path
from imuops.config import load_defaults
from imuops.contrib import LegacyArduinoAdapter
from imuops.session import save_session

source = Path(r"$SOURCE_LOG")
out_dir = Path(r"$SESSION_DIR")
bundle = LegacyArduinoAdapter.ingest(source, out_dir, {"config": load_defaults()})
save_session(bundle, out_dir)
PY

"$IMUOPS_BIN" audit "$SESSION_DIR"
"$IMUOPS_BIN" replay "$SESSION_DIR" --baseline madgwick
"$IMUOPS_BIN" replay "$SESSION_DIR" --baseline pdr
"$IMUOPS_BIN" benchmark "$SESSION_DIR" --task pdr
"$IMUOPS_BIN" report "$SESSION_DIR" --out "$SESSION_DIR/report.html"

echo "Report ready at $SESSION_DIR/report.html"
