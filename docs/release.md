# Public Release Checklist

Do not publish the current Git history until the owner has approved and verified
its cleanup. A historical running-memory file contains private athlete data.
Sanitizing HEAD and adding .gitignore do not remove old commits. Secret scanners
do not generally detect ordinary personal health information.

## Privacy Gate

- Keep a private, restricted backup before any approved history rewrite.
- Remove private blobs from every branch/tag being published, or publish a
  reviewed clean-history source repository. Coordinate changed commit IDs.
- Review historical prompts, fixtures, docs and deleted files for personal data;
  review refs and provider credentials separately. Never force-push automatically.
- Run `gitleaks git . --redact --no-banner` and manually review data privacy.
- Review wheel and source archives: no .env, tokens, DBs, lock files, personal
  memory, backups, logs or private screenshots. Never archive the whole local folder.

## Runtime Gate

```bash
poetry check --lock
python -m ruff check .
python -m compileall -q analytics coach db llm metrics scripts services utils web worker tests config.py
python -m pytest
poetry build
python -m scripts.check_distribution dist/<wheel>.whl
```

The distribution check installs into a temporary directory and verifies imports,
assets, a fresh migration and web responses outside the checkout, without live
providers. Check supported Python versions in CI. Windows is not currently
supported: worker/coach locks use POSIX fcntl.

Document the single-athlete, local-first alpha status, provider sharing approvals,
supported Garmin/CSV paths and the unresolved FIT status. Confirm remote access
uses HTTPS and a password. Confirm backup/restore on disposable data, not the live DB.
