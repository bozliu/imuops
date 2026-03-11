# Datasets and Provenance

Transparent data provenance matters for `imuops` because users need to know what the public demo path is based on, what is safe to redistribute, and which datasets remain under third-party terms.

## Bundled Sample Data

The public quickstart uses:

- [examples/sample_tabular_imu.csv](../examples/sample_tabular_imu.csv)
- [examples/sample_tabular_config.yaml](../examples/sample_tabular_config.yaml)

This bundled sample is a synthetic demo dataset created for the public ingest, audit, and report workflow. It is safe to redistribute and is not presented as raw real-world sensor data.

For the bundled sample:

- trajectory and activity values are simplified public demo values
- exact source paths, names, GPS traces, and private identifiers are not included
- the file exists to demonstrate the tabular workflow, not to document a specific collection event

The first public path is:

```bash
imuops ingest tabular examples/sample_tabular_imu.csv --config examples/sample_tabular_config.yaml --out output/sample_tabular_demo
imuops audit output/sample_tabular_demo --summary-format markdown
imuops report output/sample_tabular_demo --out output/sample_tabular_demo/report.html
```

The YAML mapping controls:

- timestamp column and time unit
- accel, gyro, and mag column names and units
- optional temperature, pressure, and label columns
- optional ground-truth position and heading columns
- metadata such as task, body location, and device pose

## Supported Public Benchmarks

Benchmark adapters are included for reproducibility demos and public validation, but the repo does not vendor the full upstream datasets. Users must obtain the data from the original sources and comply with their licenses, citations, and usage terms.

### RoNIN

- Adapter: `ronin`
- Purpose: inertial odometry benchmark and reproducibility demo
- Official project and dataset: [RoNIN: Robust Neural Inertial Navigation](https://ronin.cs.sfu.ca/)
- Citation requested by source: Herath, Yan, and Furukawa, ICRA 2020

```bash
python scripts/fetch_ronin_sample.py --zip-path /path/to/ronin_sample.zip --out downloads/ronin
imuops ingest ronin downloads/ronin/<session_dir> --out output/ronin_demo
```

### OxIOD

- Adapter: `oxiod`
- Purpose: handheld and phone inertial odometry benchmark demo
- Official project and dataset: [Oxford Inertial Odometry Dataset](https://deepio.cs.ox.ac.uk/)
- Citation requested by source: Chen et al., "Deep Learning based Pedestrian Inertial Navigation: Methods, Dataset and On-Device Inference"

```bash
python scripts/fetch_oxiod_sample.py --zip-path /path/to/oxiod_sample.zip --out downloads/oxiod
imuops ingest oxiod downloads/oxiod/<session_dir>/imu1.csv --out output/oxiod_demo
```

### WISDM

- Adapter: `wisdm`
- Purpose: lightweight HAR benchmark demo
- Official dataset page: [WISDM Activity Prediction Dataset](https://www.cis.fordham.edu/wisdm/dataset.php)
- Citation requested by source: Kwapisz, Weiss, and Moore, KDD Cup Workshop 2010

```bash
python scripts/fetch_wisdm_sample.py --zip-path /path/to/wisdm_sample.zip --out downloads/wisdm
imuops ingest wisdm downloads/wisdm/WISDM_ar_v1.1_raw.txt --out output/wisdm_demo
```

## Local Legacy Data

The `legacy_arduino` adapter is intentionally non-core and intentionally local:

- it exists for local parser regression and historical mixed-log experiments
- it is available via `imuops.contrib`
- it is not part of the public quickstart
- its source data is not distributed with this repository
- it is not required for public usage of `imuops`

You can verify that the adapter is present with:

```bash
python -c "from imuops.contrib import LegacyArduinoAdapter; print(LegacyArduinoAdapter.name)"
```

## Redistribution and Privacy Policy

- this repository does not redistribute the full RoNIN, OxIOD, or WISDM datasets
- users are responsible for obtaining benchmark data from the original sources and following their terms
- `session.json` and generated reports may contain `source_path` or `subject_id` unless redaction flags are used
- shared reports should typically be generated with `--redact-source-path --redact-subject-id`
- do not publish private raw GPS traces, names, or identifying location metadata in public artifacts unless you have clear permission to do so

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
