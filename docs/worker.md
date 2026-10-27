# Local worker

Upgrade a stopped installation first: `python -m scripts.upgrade_db --db db/running_coach.db`.
The upgrade makes a backup before applying revision 0011. Start the worker with
`python -m worker` in the repository environment. A second worker exits rather
than running duplicate jobs. Send SIGTERM or press Ctrl-C to stop it.

The worker uses `LOCAL_TIMEZONE` for all schedule dates. `SYNC_INTERVAL_HOURS`
defaults to 2. It also tries Garmin every 20 minutes from 05:30 until today's
sleep and HRV are present or the configured latest morning time is reached.
Messages are held during quiet hours. The morning call defaults to 10:00 at
the latest, day review to 17:00 and weekly review to Sunday at 18:00. Edit
these times and per-job AI opt-ins in Settings. `AUTO_OPINIONS=true` enables
automatic opinions for new runs; it is off by default. Remote AI still needs
the separate athlete-data approval flags.

Decisions use at most easy intensity when the latest complete sleep and HRV day
is older than yesterday. A provisional morning call is followed by one short
update only if new data changes the intensity. Scheduled messages use Telegram
HTML for a bold heading, with plain text if Telegram explicitly rejects the
markup. Rating and proposal actions use inline keyboards.

`PUBLIC_URL` is the optional public HTTPS base address for Telegram link buttons.
Leave it empty for a local-only install; localhost links are never sent. The bot process (`python -m utils.telegram_chat_cli`)
must also be running for commands and buttons. Keep one bot process and one
worker process. Both use the existing Telegram recipient allowlist.

The worker writes status, errors and sent message text to `job_runs`. View the
last results in Settings and sent messages in Coach. A failed or timed-out
Telegram request is marked uncertain and is *not* automatically resent:
Telegram does not accept a caller-supplied idempotency key, so resending could
duplicate it. Inspect Telegram and `job_runs` before manually retrying.
Garmin retries transient failures with short backoff inside the claimed sync
slot. Telegram retries only explicit 429 rejections, where no message was
accepted; timeouts and server errors remain uncertain and are not retried.
Do not put bot tokens or credentials in launchd arguments or logs.

The template `docs/worker.launchd.plist` uses placeholders. Copy it outside
the repo, replace placeholders, then `launchctl bootstrap gui/$(id -u) PATH`.
Use `launchctl bootout gui/$(id -u) PATH` to stop it. Logs go to the two
paths configured in that private plist.
