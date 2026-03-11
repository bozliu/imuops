# Schema Compatibility

`imuops` keeps a lightweight but explicit schema-compatibility policy.

## Version Fields

Each canonical session stores:

- `schema_version`
- `trustscore_version`

These are written into `session.json` and propagated into audit outputs and reports.

Machine-readable release artifacts also store:

- `artifact_type`
- `artifact_schema_version`

That currently applies to:

- `compare` JSON summaries
- `export_summary.json`
- `batch_summary.json`
- trust-score validation summaries

## Compatibility Rules

- patch and minor changes should preserve existing field names when possible
- new optional fields may be added without breaking old readers
- breaking field or semantic changes must bump `schema_version`
- trust-score formula changes must bump `trustscore_version`

## Current Migration Policy

`imuops` v0.3 does not ship a full `migrate` CLI yet. The short-term policy is:

1. document the schema change in this file
2. keep readers tolerant to missing optional fields when safe
3. add regression fixtures covering the old and new payloads where practical

This is intentionally modest, but it makes compatibility an explicit contract instead of an implied hope.

## Batch Artifact Naming

`imuops` v0.4 keeps `batch_audit_summary.json` as a deprecated compatibility alias, but new integrations should read `batch_summary.json`.
