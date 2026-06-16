# Security Policy

## Supported Versions

Security fixes are handled on the current main branch.

## Reporting A Vulnerability

Do not publish secrets, tokens, database contents, logs, Garmin exports, or
personal health/training data in a public issue.

If GitHub private vulnerability reporting is enabled for this repository, use
that channel. Otherwise, open a minimal public issue that describes the affected
area without sensitive details and ask for a private contact path.

Useful reports include:

- The affected file, command, or workflow.
- The impact and who can trigger it.
- Reproduction steps using mock data only.
- Whether secrets, credentials, personal data, or local files are exposed.

## Sensitive Data

Running Coach is local-first, but the app can handle Garmin credentials, access
tokens, SQLite databases, GPS routes, recovery metrics, and LLM prompts. Treat
all of those as private.
