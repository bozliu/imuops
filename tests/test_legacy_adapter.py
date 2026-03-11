from __future__ import annotations

from pathlib import Path

import pytest

from imuops.contrib.legacy_arduino import LegacyArduinoAdapter


def test_legacy_adapter_parses_real_log_if_available(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    real_log = repo_root.parent / "Research" / "Code" / "test_data" / "TEST1.TXT"
    if not real_log.exists():
        pytest.skip("Historical TEST1.TXT not available in this workspace.")
    bundle = LegacyArduinoAdapter.ingest(real_log, tmp_path / "out", {})
    assert bundle.metadata.dataset == "legacy_arduino"
    assert bundle.metadata.task == "pdr"
    assert len(bundle.imu) > 1000
    assert bundle.metadata.nominal_hz > 50.0
    assert bundle.metadata.reference_type == "gps"


def test_legacy_adapter_handles_embedded_gps_and_mixed_columns(tmp_path: Path) -> None:
    fixture_root = tmp_path / "legacy"
    (fixture_root / "test_data").mkdir(parents=True)
    (fixture_root / "Extracted GPS data").mkdir(parents=True)
    log_path = fixture_root / "test_data" / "TESTX.TXT"
    log_path.write_text(
        "\n".join(
            [
                "Raw mag calibration values: 179\t181\t169",
                "0\t16384\t0\t0\t0\t0\t0\t10\t10\t10",
                "10\t16384\t0\t0\t0\t0\t0\t10\t10\t10\t30.0\t100000.0",
                "GPS Data:\t$GPRMC,165509.00,A,2948.20448,N,12133.39414,E,1.600,,230618,,,A",
                "$GPVTG,,,,,,,,,N*30",
                "20\t16384\t0\t0\t0\t0\t0\t10\t10\t10",
            ]
        ),
        encoding="utf-8",
    )
    bundle = LegacyArduinoAdapter.ingest(log_path, tmp_path / "out", {})
    assert list(bundle.imu.columns)[:4] == ["t_ms", "ax", "ay", "az"]
    assert len(bundle.gps) == 1
    assert bool(bundle.gps.iloc[0]["valid"]) is True
    assert pytest.approx(bundle.imu.iloc[0]["ax"], rel=1e-3) == 9.80665
