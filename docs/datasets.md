# Datasets

`imuops` is designed to mix customer-shaped tabular IMU data with benchmark sessions. In this public alpha, the default product entrypoint is the config-driven `tabular` adapter.

## Adapter Matrix

| Adapter | Task | Expected source | Reference | Notes |
| --- | --- | --- | --- | --- |
| `tabular` | `orientation` / `pdr` / `har` | `csv`, `tsv`, or `parquet` plus YAML config | optional labels / ground truth | Main customer-data path |
| `ronin` | `pdr` | `info.json` + `data.hdf5` session dir | trajectory | Benchmark/demo adapter validated on fixtures and demo flows |
| `oxiod` | `pdr` | `imu*.csv` file with matching `vi*.csv` | trajectory | Benchmark/demo adapter validated on fixtures and demo flows |
| `wisdm` | `har` | WISDM-style `txt` or `csv` | activity labels | Benchmark/demo adapter validated on fixtures and demo flows |

The machine-readable source registry lives in [datasets/manifest.toml](../datasets/manifest.toml).

## Tabular Customer Data

The recommended public workflow is a tabular file plus a YAML mapping file. The repo bundles a small offline sample in [examples/sample_tabular_imu.csv](../examples/sample_tabular_imu.csv) and [examples/sample_tabular_config.yaml](../examples/sample_tabular_config.yaml).

The first public-alpha path is:

```bash
imuops ingest tabular examples/sample_tabular_imu.csv --config examples/sample_tabular_config.yaml --out output/sample_tabular_demo
imuops audit output/sample_tabular_demo --summary-format markdown
imuops report output/sample_tabular_demo --out output/sample_tabular_demo/report.html
```

The YAML mapping controls:

- timestamp column and time unit
- accel / gyro / mag column names and units
- optional temperature, pressure, and label columns
- optional ground-truth position and heading columns
- metadata such as task, body location, and device pose

## Contrib / Local Regression

The legacy adapter is intentionally non-core and intentionally local:

- it is available via `imuops.contrib`
- it is not part of the public quickstart
- it is useful only for local regression on the historical workspace

You can verify that it is present with:

```bash
python -c "from imuops.contrib import LegacyArduinoAdapter; print(LegacyArduinoAdapter.name)"
```

## Public Sample Fetch Helpers

The fetch scripts do not vendor datasets into the repo. They either download a public archive you specify or unpack a local archive you already obtained.

## Privacy and Sharing Notes

- benchmark fetch helpers assume the user is responsible for dataset license compliance
- `session.json` may contain `source_path` and `subject_id`
- shared reports should typically be generated with `--redact-source-path --redact-subject-id`

### RoNIN

```bash
python scripts/fetch_ronin_sample.py --zip-path /path/to/ronin_sample.zip --out downloads/ronin
imuops ingest ronin downloads/ronin/<session_dir> --out output/ronin_demo
```

### OxIOD

```bash
python scripts/fetch_oxiod_sample.py --zip-path /path/to/oxiod_sample.zip --out downloads/oxiod
imuops ingest oxiod downloads/oxiod/<session_dir>/imu1.csv --out output/oxiod_demo
```

### WISDM

```bash
python scripts/fetch_wisdm_sample.py --zip-path /path/to/wisdm_sample.zip --out downloads/wisdm
imuops ingest wisdm downloads/wisdm/WISDM_ar_v1.1_raw.txt --out output/wisdm_demo
```

## Demo Commands

### Customer-shaped tabular data

```bash
imuops ingest tabular /path/to/customer_session.csv --config examples/tabular_config.example.yaml --out output/customer_session
imuops audit output/customer_session --fail-below 0.80
imuops export output/customer_session --profile qa_filtered --format parquet --out output/customer_session_clean
imuops report output/customer_session --out output/customer_session/report.html
```

### Clean navigation

```bash
imuops audit output/ronin_demo
imuops replay output/ronin_demo --baseline madgwick
imuops benchmark output/ronin_demo --task orientation
imuops report output/ronin_demo --out output/ronin_demo/report.html
```

### Clean HAR

```bash
imuops audit output/wisdm_demo
imuops benchmark output/wisdm_demo --task har
imuops report output/wisdm_demo --out output/wisdm_demo/report.html
```

### Robustness regression

```bash
imuops corrupt output/ronin_demo --preset packet_loss_5 --out output/ronin_demo_packet_loss
imuops audit output/ronin_demo_packet_loss
imuops report output/ronin_demo_packet_loss --out output/ronin_demo_packet_loss/report.html
imuops compare output/ronin_demo output/ronin_demo_packet_loss --out output/ronin_compare.html
```

Benchmark adapters are useful for demos and reproducibility, but they are secondary to the tabular customer-data path.
