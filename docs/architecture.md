# Architecture

`imuops` keeps each adapter thin and pushes the rest of the system onto one canonical session format. The pipeline is task-aware, but the product is intentionally **tabular-first**: benchmark adapters remain useful for reproducibility demos, while the main public-alpha path is customer-shaped CSV, TSV, and Parquet plus YAML mapping.

## Core flow

1. Adapter ingests source files into:
   - `session.json`
   - `imu.parquet`
   - `gps.parquet`
   - `ground_truth.parquet`
2. Audit reads the canonical session and writes:
   - `issues.json`
   - `audit_summary.json`
   - CI-friendly console summaries and exit codes
3. Replay reads the same session and writes one artifact pair per baseline:
   - `replay_<baseline>.parquet`
   - `replay_<baseline>_summary.json`
4. Benchmark runs task-aware baselines and writes:
   - `benchmark_summary.json`
   - `benchmark_<task>_<baseline>.json`
5. Corruption writes a second canonical session plus:
   - `corruption.json`
6. Report combines the session, audit output, benchmark summaries, replay artifacts, and corruption context into a single HTML file.

## Canonical metadata

`session.json` is validated with `pydantic` and includes:

- `schema_version`
- `trustscore_version`
- `dataset`
- `session_id`
- `task`
- `reference_type`
- `nominal_hz`
- `body_location`
- `device_pose`
- `label_namespace`
- `sensors`
- `ground_truth_available`
- `labels_available`

This lets the report and benchmark layers stay generic even when the source datasets have very different conventions.

## Canonical units

- `t_ms`: milliseconds from session start
- accelerometer: `m/s^2`
- gyroscope: `rad/s`
- magnetometer: `uT`
- pressure: `Pa`
- temperature: `C`

## Supported tasks and baselines

- `orientation`: `madgwick`, `mahony`
- `pdr`: step-heading dead reckoning baseline
- `har`: fixed-window hand-crafted features + random forest baseline

The replay layer is deliberately conservative. It exists to make QA and benchmarking reproducible, not to claim novelty.

## Core adapters vs contrib adapters

- Core:
  - `tabular`: CSV, TSV, and Parquet plus YAML mapping
  - `ronin`, `oxiod`, `wisdm`: benchmark/demo adapters validated on fixtures and demo flows
- Contrib:
  - `legacy_arduino`: historical Arduino/MPU9255 adapter kept for local regression only

The adapters intentionally stay tolerant enough for small local extracts and hand-curated samples, but only the `tabular` adapter is positioned as the default customer-data interface.
