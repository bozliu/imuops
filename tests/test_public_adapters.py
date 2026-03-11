from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from imuops.adapters.oxiod import OxIODAdapter
from imuops.adapters.ronin import RoNINAdapter
from imuops.adapters.tabular import TabularAdapter
from imuops.adapters.wisdm import WISDMAdapter


def test_ronin_adapter_smoke(ronin_fixture_dir: Path, tmp_path: Path) -> None:
    bundle = RoNINAdapter.ingest(ronin_fixture_dir, tmp_path / "ronin_out", {})
    assert bundle.metadata.dataset == "ronin"
    assert bundle.metadata.task == "pdr"
    assert not bundle.ground_truth.empty
    assert len(bundle.imu) > 50


def test_oxiod_adapter_smoke(oxiod_fixture_file: Path, tmp_path: Path) -> None:
    bundle = OxIODAdapter.ingest(oxiod_fixture_file, tmp_path / "oxiod_out", {})
    assert bundle.metadata.dataset == "oxiod"
    assert bundle.metadata.task == "pdr"
    assert not bundle.ground_truth.empty
    assert len(bundle.imu) > 50


def test_wisdm_adapter_smoke(wisdm_fixture_file: Path, tmp_path: Path) -> None:
    bundle = WISDMAdapter.ingest(wisdm_fixture_file, tmp_path / "wisdm_out", {})
    assert bundle.metadata.dataset == "wisdm"
    assert bundle.metadata.task == "har"
    assert bundle.metadata.labels_available is True
    assert bundle.imu["activity_label"].notna().any()


def test_tabular_adapter_smoke(tabular_csv_fixture: tuple[Path, Path], tmp_path: Path) -> None:
    csv_path, yaml_path = tabular_csv_fixture
    bundle = TabularAdapter.ingest(csv_path, tmp_path / "tabular_out", {"adapter_config": yaml_path, "config": {"tabular": {"chunk_rows": 25}}})
    assert bundle.metadata.dataset == "customer_demo"
    assert bundle.metadata.session_id == "customer_demo_session"
    assert bundle.metadata.task == "pdr"
    assert bundle.metadata.reference_type == "trajectory"
    assert bundle.metadata.labels_available is True
    assert bundle.imu["pressure_pa"].iloc[0] == 101325.0
    assert bundle.imu["az"].iloc[0] == pytest.approx(9.80665, rel=1e-3)


def test_tabular_adapter_parquet_smoke(tabular_csv_fixture: tuple[Path, Path], tmp_path: Path) -> None:
    csv_path, yaml_path = tabular_csv_fixture
    parquet_path = tmp_path / "customer_session.parquet"
    pd.read_csv(csv_path).to_parquet(parquet_path, index=False)
    yaml_text = yaml_path.read_text(encoding="utf-8").replace("format: csv", "format: parquet")
    parquet_yaml = tmp_path / "customer_session_parquet.yaml"
    parquet_yaml.write_text(yaml_text, encoding="utf-8")
    bundle = TabularAdapter.ingest(parquet_path, tmp_path / "tabular_parquet_out", {"adapter_config": parquet_yaml, "config": {"tabular": {"chunk_rows": 10}}})
    assert len(bundle.imu) > 50
    assert bundle.metadata.dataset == "customer_demo"


def test_tabular_adapter_tsv_smoke(tabular_csv_fixture: tuple[Path, Path], tmp_path: Path) -> None:
    csv_path, yaml_path = tabular_csv_fixture
    tsv_path = tmp_path / "customer_session.tsv"
    pd.read_csv(csv_path).to_csv(tsv_path, sep="\t", index=False)
    yaml_text = yaml_path.read_text(encoding="utf-8").replace("format: csv", "format: tsv")
    tsv_yaml = tmp_path / "customer_session_tsv.yaml"
    tsv_yaml.write_text(yaml_text, encoding="utf-8")
    bundle = TabularAdapter.ingest(tsv_path, tmp_path / "tabular_tsv_out", {"adapter_config": tsv_yaml, "config": {"tabular": {"chunk_rows": 17}}})
    assert bundle.metadata.session_id == "customer_demo_session"


def test_tabular_adapter_missing_column_raises(tabular_csv_fixture: tuple[Path, Path], tmp_path: Path) -> None:
    csv_path, yaml_path = tabular_csv_fixture
    bad_yaml = tmp_path / "bad_tabular.yaml"
    bad_yaml.write_text(yaml_path.read_text(encoding="utf-8").replace("ax_g", "missing_ax"), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing required columns"):
        TabularAdapter.ingest(csv_path, tmp_path / "bad_out", {"adapter_config": bad_yaml, "config": {"tabular": {"chunk_rows": 25}}})
