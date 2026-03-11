from __future__ import annotations

from imuops.adapters.wisdm import WISDMAdapter
from imuops.benchmark import run_benchmark
from imuops.config import load_defaults


def test_har_benchmark_runs(wisdm_fixture_file, tmp_path) -> None:
    bundle = WISDMAdapter.ingest(wisdm_fixture_file, tmp_path / "wisdm_out", {})
    result = run_benchmark(bundle, "har", load_defaults())
    assert result.summary.task == "har"
    assert result.summary.primary_metric_name == "macro_f1"
    assert result.summary.baselines[0].metrics["window_count"] >= 8

