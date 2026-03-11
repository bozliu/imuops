# Changelog

## Unreleased

- refreshed the public README story around B2B IMU QA, workflow visuals, and team value
- aligned dataset provenance language across docs, release notes, and security guidance
- standardized the bundled sample wording as synthetic demo data and kept legacy logs local-only

## 0.4.0 - 2026-03-11

- added versioned compare, batch, export, and trust-score validation artifact schemas
- upgraded `compare` with explicit JSON output paths, stdout summary formats, and regression gating
- upgraded `batch` with `batch_summary.json`, `batch_rankings.csv`, and batch trust-score validation
- streamed tabular ingest to canonical Parquet with preflight estimates and row-count artifacts
- hardened lazy-session audit and export flows for larger tabular sessions
- refreshed report, compare, and batch HTML outputs for clearer sharing and release assets
- added a reusable GitHub Action plus a sample PR workflow for tabular data review

## 0.3.1 - 2026-03-11

- hardened the repo as a truthful public alpha instead of a market-ready claim
- restored a tabular-first README with a clean `venv` install path and offline three-command quickstart
- bundled synthetic demo sample data in `examples/sample_tabular_imu.csv` and `examples/sample_tabular_config.yaml`
- removed hardcoded local Python paths from example scripts
- improved compare output with metadata diffs and a recommendation summary
- improved batch reporting with ranked sessions and clearer CI-oriented summaries
- added community files, issue templates, and public release checklist updates
- added a checked-in trust-score validation artifact for the bundled sample flow

## 0.3.0 - 2026-03-11

- narrowed `imuops` around tabular-first QA, reliability scoring, export, compare, batch audit/report, and trust-score validation
- demoted `legacy_arduino` from the default adapter registry to contrib/local-regression framing
- added the config-driven `tabular` adapter for customer-shaped IMU data
