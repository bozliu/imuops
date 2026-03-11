# imuops

`imuops` is a public alpha for **IMU data QA, reliability scoring, and reproducibility**.

It is built around one core question:

> Is this IMU data trustworthy, why is it failing, and how does that affect baseline algorithms?

The product is intentionally **tabular-first**. The main path is customer-shaped `csv`, `tsv`, or `parquet` data plus a small YAML mapping file. Benchmark adapters stay in the repo for reproducibility demos, but they are secondary to the tabular workflow.

## Status

- alpha / preview release
- current release line: `v0.4.0`
- main product path: `tabular`
- benchmark/demo adapters: `ronin`, `oxiod`, `wisdm`
- local-only contrib adapter: `legacy_arduino`

Benchmark adapters are validated on fixtures and demo flows. They are not guaranteed across every upstream packaging or layout variant.

## Install

Requires Python 3.11+.

Primary public path:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install .
```

Use any Python 3.11+ interpreter available on your machine.

Optional `uv` path:

```bash
uv venv
source .venv/bin/activate
uv pip install .
```

Maintainer-side validation in this workspace uses the `dl` conda environment, but public users should still prefer a clean `venv` install path.

## Quickstart

After install, the offline first-run path is exactly three commands:

```bash
imuops ingest tabular examples/sample_tabular_imu.csv --config examples/sample_tabular_config.yaml --out output/sample_tabular_demo
imuops audit output/sample_tabular_demo --summary-format markdown
imuops report output/sample_tabular_demo --out output/sample_tabular_demo/report.html
```

You can also use the bundled demo wrapper:

```bash
bash examples/run_tabular_demo.sh
```

## What It Does

- normalizes messy IMU tables into one canonical session format
- audits timing, clipping, dropout, magnetic disturbance, bias drift, and related issues
- computes a versioned `trust_score` with explicit penalties, weights, and thresholds
- replays conservative baseline algorithms for orientation and PDR reproducibility
- benchmarks task-aware baselines where labels or trajectories exist
- compares clean vs corrupted or before vs after sessions
- batches QA over many sessions and writes machine-readable summaries for CI use
- streams tabular ingest and export through canonical Parquet so large sessions do not need to fit in RAM end to end

## Core Commands

```bash
imuops ingest tabular /path/to/session.csv --config /path/to/mapping.yaml --out output/session_a
imuops audit output/session_a --fail-below 0.80 --summary-format markdown
imuops export output/session_a --profile qa_filtered --format parquet --out output/session_a_clean
imuops compare output/session_a output/session_b --out output/compare.html --json-out output/compare.json --fail-on regression
imuops batch audit output --out output/batch_artifacts
imuops batch validate-trustscore output --out output/trustscore_batch
```

## GitHub Action

`imuops` now ships a reusable GitHub Action from this repo:

```yaml
- uses: OWNER/imuops@v0.4.0
  with:
    data_glob: data/**/*.csv
    tabular_config: examples/sample_tabular_config.yaml
    report_dir: output/pr_review
    comment_mode: summary
```

The action emits:

- `trust_score`
- `status`
- `summary_json`
- `report_html`
- `compare_json`
- `comment_markdown`

See [.github/workflows/pr_tabular_review.yml](.github/workflows/pr_tabular_review.yml) for a sample PR workflow.

## Included Adapters

### Market-facing default

- `tabular`: customer-shaped `csv`, `tsv`, and `parquet` sources with YAML mapping and unit conversion

### Benchmark/demo adapters

- `ronin`: clean inertial odometry benchmark sessions
- `oxiod`: clean handheld / phone inertial odometry benchmark sessions
- `wisdm`: lightweight HAR benchmark sessions

### Contrib/local regression

- `legacy_arduino`: historical Arduino/MPU9255 adapter kept only for local regression and examples

## Trust Score

`imuops` publishes the trust-score contract directly into artifacts and reports:

- per-window formula
- session aggregation formula
- penalty totals
- weight profile
- thresholds

That is documented in [docs/trustscore.md](docs/trustscore.md), and the current validation tranche is in [docs/trustscore_validation.md](docs/trustscore_validation.md).

## What This Release Is

- a tabular-first IMU QA tool that new users can install and run without hand-holding
- a machine-readable trust-score and compare/batch workflow for CI use
- an alpha release with release-level validation artifacts and explicit known limitations

## What This Release Is Not

- a claim of deployment-grade calibration across every device or dataset
- unbounded replay or benchmark support for arbitrarily large sessions
- a promise that every benchmark adapter variant in the wild is supported

## Docs

- [Architecture](docs/architecture.md)
- [Datasets](docs/datasets.md)
- [Trust Score](docs/trustscore.md)
- [Trust-Score Validation](docs/trustscore_validation.md)
- [Schema Compatibility](docs/schema_compatibility.md)
- [Release Checklist](docs/release.md)
- [Contributing](CONTRIBUTING.md)

## Public Alpha Notes

- This repo is a **truthful alpha**, not a commercial deployment claim.
- Reports support `--redact-source-path` and `--redact-subject-id` for safer sharing.
- Output quality is strongest for tabular customer data and fixture/demo benchmark layouts.

## License

[MIT](LICENSE)
