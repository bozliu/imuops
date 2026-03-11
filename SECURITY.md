# Security Policy

## Scope

`imuops` is a local data-processing tool. Security issues are most relevant when they affect:

- installation or dependency safety
- arbitrary file access beyond documented behavior
- report generation that unexpectedly leaks private data
- malformed input files that cause unsafe execution

## Reporting

If you find a security issue, please open a private report instead of posting full details in a public issue.

Until a dedicated security contact is configured, include:

- affected version
- operating system and Python version
- minimal reproduction steps
- impact assessment

## Sensitive Data

Reports can contain `source_path`, `subject_id`, GPS traces, and other identifying metadata. For shared artifacts, prefer:

- `imuops report ... --redact-source-path --redact-subject-id`
- sanitized demo data for screenshots and tutorials

This alpha does not guarantee compliance for regulated workflows by itself.
