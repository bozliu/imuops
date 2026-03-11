# Public Alpha Release Checklist

`imuops` v0.4.1 is a truthful public alpha for tabular-first IMU QA, reliability scoring, CI-friendly artifacts, and large-file-safe workflows for team use. This checklist is for release hardening and public storytelling sync, not for making deployment-grade claims.

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
- bundled synthetic demo data and config
- versioned machine-readable summary artifacts for compare, batch, export, and validation

## Public Story Sync

Before promoting a release, make sure the public surfaces tell the same story:

- the top half of `README.md` answers what `imuops` is, why it matters, what is unique, and who it is for
- the README uses workflow visuals with captions, not an unlabeled screenshot gallery
- the GitHub repo description, release body, and pinned feedback issue all use the same B2B workflow framing
- README, `docs/datasets.md`, `SECURITY.md`, and `CHANGELOG.md` all describe the bundled sample as synthetic demo data
- release assets link to the full HTML or JSON artifacts so a first-time visitor can inspect them directly

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
   - `pip install imuops`
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
9. Verify data hygiene:
   - bundled sample contains no private GPS traces, names, source paths, or location metadata
   - public docs do not describe the bundled sample as raw real-world data
10. Generate refreshed release visuals:
   - `python scripts/generate_release_visuals.py --keep-work-dir`
   - confirm `workflow-hero.gif` runs for roughly 10 to 15 seconds and reads as motion, not a slideshow
   - confirm poster PNGs and the embedded hero GIF are readable without zooming

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
4. Sync the public story:
   - repo description
   - README visuals and captions
   - release body
   - pinned feedback issue copy
5. Publish the package if credentials are ready:
   - `python -m build`
   - `twine upload dist/*`
6. Tag and release:
   - tag `v0.4.1`
   - attach HTML/JSON validation artifacts and workflow GIFs
7. Generate release assets:
   - sample audit summary
   - sample HTML report
   - sample compare report
   - machine-readable trust-score validation artifact
   - one combined `workflow-hero.gif` plus poster PNGs for audit, report, and compare
8. Keep wording conservative:
   - `alpha` / `preview`
   - benchmark adapters are fixture/demo validated
   - no deployment-grade or market-readiness claims
9. Confirm README install instructions use `pip install imuops` only after PyPI returns the released version and a clean-venv smoke install succeeds.

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
