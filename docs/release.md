# Public Alpha Release Checklist

`imuops` v0.4.0 is a truthful public alpha around IMU QA, reliability scoring, CI-friendly artifacts, and large-file-safe tabular workflows. This checklist is for release hardening, not for making deployment-grade claims.

## Already Prepared

- package metadata in `pyproject.toml`
- MIT license
- CLI entrypoints
- versioned canonical schema
- headless CI gate behavior for `audit`
- CI workflow for macOS and Linux
- coverage configuration with `pytest-cov`
- fetch helpers and dataset manifest
- HTML reporting templates
- compare, batch, export, action, and trust-score validation commands
- bundled offline sample data and config
- versioned machine-readable summary artifacts for compare, batch, export, and validation

## Clean-Machine Validation

Run the public-alpha path on:

- fresh macOS environment
- fresh Linux environment
- optional Windows smoke run if available

Minimum checks:

1. Create a new environment:
   - `python3.12 -m venv .venv`
   - `source .venv/bin/activate`
2. Install:
   - `pip install .`
3. Verify console entrypoint:
   - `imuops --help`
4. Verify bundled sample:
   - `imuops ingest tabular examples/sample_tabular_imu.csv --config examples/sample_tabular_config.yaml --out output/sample_tabular_demo`
   - `imuops audit output/sample_tabular_demo --summary-format markdown`
   - `imuops report output/sample_tabular_demo --out output/sample_tabular_demo/report.html`
5. Verify compare on clean vs corrupted sample:
   - `imuops corrupt output/sample_tabular_demo --preset packet_loss_5 --out output/sample_tabular_demo__packet_loss_5`
   - `imuops compare output/sample_tabular_demo output/sample_tabular_demo__packet_loss_5 --out output/sample_compare.html --json-out output/sample_compare.json --fail-on regression`
6. Verify batch outputs:
   - `imuops batch audit output --out output/batch_artifacts`
   - confirm `batch_summary.json`, `batch_audit_summary.json`, and `batch_rankings.csv`
7. Verify trust-score validation:
   - `imuops batch validate-trustscore output --out output/trustscore_batch`
8. Verify action script smoke path:
   - `python scripts/run_github_action.py --data-glob examples/sample_tabular_imu.csv --tabular-config examples/sample_tabular_config.yaml --report-dir output/action_review`

## Maintainer Validation (`dl`)

In this workspace, run release validation from the `dl` conda environment:

1. `conda activate dl`
2. `python -m imuops --help`
3. `pytest --cov=imuops --cov-report=term-missing --cov-report=xml`
4. `python -m build`

## Before First Public Push

1. Initialize the repo with git and connect the final GitHub remote.
2. Create the GitHub repo, enable Discussions, and prepare a pinned public-feedback issue.
3. Confirm all docs use repo-relative links and no local filesystem paths.
4. Publish the package if credentials are ready:
   - `python -m build`
   - `twine upload dist/*`
5. Tag and release:
   - tag `v0.4.0`
   - attach HTML/JSON validation artifacts and release screenshots or GIFs
6. Generate release assets:
   - sample audit summary
   - sample HTML report
   - sample compare report
   - machine-readable trust-score validation artifact
   - three GIFs for sample audit, report, and compare flows
7. Keep wording conservative:
   - `alpha` / `preview`
   - benchmark adapters are fixture/demo validated
   - no deployment-grade or market-readiness claims

## What This Release Is

- a tabular-first IMU QA workflow that installs cleanly and emits stable JSON artifacts
- an alpha release that is ready for outside-user feedback and CI integration
- a release with explicit trust-score evidence and known limitations

## What This Release Is Not

- a promise of universal calibration across every device class
- a promise that replay and benchmark are unbounded for arbitrarily large sessions
- a hosted service or enterprise deployment claim

## Public Claims To Avoid

- do not claim deployment readiness
- do not claim full upstream benchmark-layout support unless exercised
- do not imply PyPI availability before publishing
- do not imply support for Python older than 3.11

## Optional Next Steps

- collect external user feedback from 3 to 5 cold-start installs
- promote the reusable GitHub Action once the first design-partner workflows stabilize
- add hosted batch reporting later if the project moves toward open-core
