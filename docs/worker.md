# Worker Operations

Run commands from the application directory, or set `PULSE_HOME` explicitly:

```bash
python -m worker
```

One worker owns the database's `.worker.lock`; a second exits. Stop with Ctrl-C
or SIGTERM. Do not delete a held lock file. Its presence alone does not mean the
worker is running. Settings shows the lock/heartbeat state and recent job errors.

Jobs use LOCAL_TIMEZONE. Sync runs periodically; morning waits for sleep/HRV
until the configured latest time; day and weekly reviews use Messages settings.
Automatic AI is opt-in per job and respects provider approvals and call limits.
Quiet hours and pause delay scheduled messages. Claims in job_runs prevent
repeated delivery; an uncertain send is not retried blindly.

Telegram delivery requires both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. Polling
commands/callbacks run separately with `python -m utils.telegram_chat_cli`.
Set PUBLIC_URL to an HTTPS app address for message links. Never publish tokens,
GPS, database contents or logs. Do not share the worker's private runtime files.

## macOS

Copy [the launchd template](pulse-worker.plist.example) outside the repository,
replace every placeholder with your install's absolute paths and load it with
`launchctl bootstrap gui/$(id -u) /path/to/your.plist`. Stop it with
`launchctl bootout gui/$(id -u) /path/to/your.plist`. KeepAlive restarts crashes;
RunAtLoad starts it when the user's agent is loaded, normally at login.
The web server and Telegram polling need their own process supervision.

## Troubleshooting

- Schema error: stop jobs and use the backup-first upgrade runner.
- Old Garmin data: open Garmin Connect, check login and run `python -m utils.garmin_sync_cli`.
- Missing messages: check Telegram settings, pause, quiet hours and job history.
- Backup errors: ensure BACKUP_DIR is private, writable and outside the application directory.
