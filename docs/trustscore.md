# Trust Score

`imuops` v0.3.1 alpha ships a deterministic, versioned reliability engine. The active score version is stored in both `session.json` and `audit_summary.json` so results are comparable across runs.

## Reason Taxonomy

The default reason codes are:

- `timing_bad`
- `dropout`
- `clipping`
- `gyro_bias_drift`
- `mag_disturbed`
- `gps_unreliable`
- `insufficient_static_segment`
- `pressure_unstable`
- `orientation_inconsistent`

## What Gets Measured

The audit pass computes:

- nominal sample rate and timestamp jitter
- missing-gap / dropout behavior
- long zero-value freeze behavior
- clipping against configured sensor full-scale assumptions
- gyro bias drift and availability of static windows
- magnetic norm instability
- pressure stability and floor-change candidates
- GPS validity ratio and alignment sanity when GPS exists
- orientation consistency against gravity and heading continuity

## Score Structure

The final `trust_score` is a weighted aggregate of per-window penalties:

- each audit window gets a `trust_score`
- each window stores its own `reason_codes`
- each window stores `penalties` by reason
- the session summary stores:
  - `penalty_totals`
  - `weight_profile`
  - `warning_threshold`
  - `fail_threshold`
  - `window_formula`
  - `session_formula`

This lets downstream users answer both “what was the score?” and “why did it drop?”

## Current Formula

`imuops` publishes the formulas directly into the artifacts:

- `window_trust_score = clamp(1 - sum(active_penalties), 0, 1)`
- `session_trust_score = clamp(mean(window_trust_score) - sum(session_penalty_totals) / max(window_count, 1), 0, 1)`

Where:

- `active_penalties` are the penalties triggered inside one audit window
- `session_penalty_totals` are post-window penalties such as insufficient static coverage or accumulated bias drift
- `clamp(x, 0, 1)` limits the score to the `[0, 1]` range

## Config

The default thresholds and weights live in [src/imuops/config/defaults.toml](../src/imuops/config/defaults.toml). The design goal is for users to tune thresholds by device family or dataset, while keeping the reason taxonomy stable.

The bundled sample validation artifact is in [docs/artifacts/trustscore_validation_summary.json](artifacts/trustscore_validation_summary.json).

## Intended Use

`trust_score` is meant to support:

- session triage before model training
- data collection QA
- corrupted-vs-clean regression tests
- acceptance checks for new device pipelines
- benchmark explainability when a baseline fails on only some sessions
