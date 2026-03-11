# Trust-Score Validation

`imuops` includes a reproducible trust-score validation path rather than treating the score as an unexplained heuristic.

## Goal

The validation tranche checks whether corruption that should make a session less trustworthy actually causes:

- non-improving `trust_score`
- baseline metric degradation or instability
- consistent reason-code activation

## Command

```bash
imuops validate-trustscore output/customer_session --out output/customer_session/trustscore_validation.json
```

The public alpha also ships a checked-in example artifact generated from the bundled synthetic demo flow:

- [docs/artifacts/trustscore_validation_summary.json](artifacts/trustscore_validation_summary.json)
- [docs/artifacts/trustscore_validation_release_summary.json](artifacts/trustscore_validation_release_summary.json)

The generated artifact records:

- clean trust score
- per-preset trust score
- trust-score delta
- whether the preset was non-improving
- replay / benchmark metric deltas when available
- metric correlation rows across numeric replay / benchmark deltas
- known limitations captured directly in the artifact

For multi-session release validation:

```bash
imuops batch validate-trustscore output --out output/trustscore_batch
```

## Presets

The built-in validation pass currently covers:

- `packet_loss_5`
- `timestamp_jitter_3ms`
- `axis_flip_x`
- `gyro_bias_small`
- `mag_bias_30ut`

## Interpretation

This validation layer does not claim formal statistical calibration yet. It is a reproducible hardening tool that helps answer:

- does the score move in the expected direction?
- do baseline metrics move with it?
- which corruption modes are currently under-detected?

What it proves in this alpha:

- the score path is explicit and reproducible
- built-in corruption presets do not improve the bundled sample score
- metric deltas can be inspected alongside trust-score deltas

What it does **not** prove yet:

- universal calibration across all devices
- production-grade thresholds for regulated workflows
- full task-specific causal attribution for every failure mode
