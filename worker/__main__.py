"""Run the local scheduler as exactly one long-lived process."""

from __future__ import annotations

import fcntl
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import get_settings
from db.setup import require_current_database
from services.telegram_service import TelegramService
from worker.jobs import tick


def acquire_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("A Pulse Coach worker is already running") from None
    handle.seek(0)
    handle.truncate()
    handle.write(str(__import__("os").getpid()))
    handle.flush()
    return handle


def main() -> None:
    settings = get_settings()
    require_current_database(settings.db_path)
    lock = acquire_lock(settings.db_path.with_suffix(".worker.lock"))
    stopped = False

    def stop(_signal: int, _frame: object) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    telegram = TelegramService(settings)
    try:
        while not stopped:
            try:
                tick(settings, datetime.now(ZoneInfo(settings.local_timezone)), telegram)
            except Exception as exc:
                print("Worker job error: " + telegram.redact(str(exc)), file=sys.stderr)
            for _ in range(60):
                if stopped:
                    break
                time.sleep(1)
    finally:
        lock.close()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
