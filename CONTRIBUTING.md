# Contributing

Thanks for helping improve `imuops`.

## Local Setup

The recommended local environment on this machine is the `dl` conda env:

```bash
conda activate dl
python -m pip install -e '.[dev]'
```

## Development Workflow

1. Add or update tests with every behavior change.
2. Keep adapters tolerant but deterministic.
3. Preserve the canonical session schema.
4. Do not vendor large public datasets into the repo.
5. Prefer small fixtures and download scripts for dataset coverage.
6. Keep `legacy_arduino` in contrib/experimental space; do not let the market-facing docs or default adapter registry drift back toward it.

## Test Commands

```bash
pytest -q
pytest --cov=imuops --cov-report=term-missing
```

## Scope Guardrails

- `imuops` is a data QA, benchmark, and reliability toolchain.
- `imuops` is tabular-first from a product perspective.
- New baselines should improve reproducibility, not chase leaderboard novelty by default.
- Corruption presets should stay config-driven and named.
- Report artifacts should remain self-contained and portable.

## Pull Request Checklist

- tests pass locally
- README or docs updated when behavior changes
- new adapters document their expected input layout
- new reason codes or thresholds are reflected in `docs/trustscore.md`
