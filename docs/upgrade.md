# Database Upgrades and Restore

Stop the web app, worker and Telegram polling before maintenance. Never migrate
the production file through a test or application startup.

```bash
python -m scripts.upgrade_db --db db/running_coach.db
```

This is the only application upgrade entry point. New databases are initialized;
an existing database is backed up before an upgrade. Already-current databases
are unchanged. Keep the printed backup path private and record it before restart.
For a different install, pass its absolute path explicitly. Check a disposable
copy first when upgrading an existing installation.

Revisions live in `db/migrations/versions/`. Startup refuses to run behind head.
Add a migration and preservation tests for each schema change; never use
`create_all` or fallback DDL in web, CLI or worker startup. Protected body-scan
tables, old marathon columns and unrelated database files must be preserved.

Daily backups use SQLite's online backup API and an integrity check. The worker
keeps dated files outside the repo in `BACKUP_DIR` (default `~/pulse-backups/`).
It retains the latest fourteen daily and eight Sunday backups.

To restore the default database, stop all processes and run:

```bash
python -m scripts.restore_db --from /private/path/to/backup.db
```

The command checks source integrity, refuses while the worker lock is held,
asks for `RESTORE`, and creates a safety backup before restoring
`PULSE_HOME/db/running_coach.db` (the current directory when PULSE_HOME is unset).
It never restores `db/marathon_coach.db`. Verify the restored schema before restart.
