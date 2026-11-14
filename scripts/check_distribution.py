"""Offline installed-wheel smoke check, outside the source checkout."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REQUIRED = {
    "config.py", "coach/planning.py", "coach/load_model.py", "coach/week_rules.py",
    "worker/__main__.py", "web/app.py", "web/templates/today.html", "web/static/css/v2.css",
    "web/static/js/htmx.min.js", "web/static/fonts/OFL.txt", "db/migrations/baseline.sql",
    "data/mock_activities.csv", "data/mock_health_metrics.csv",
}

SMOKE = '''
import importlib
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
target = Path(sys.argv[1]).resolve()
for name in ("config", "coach.planning", "coach.week_rules", "services.coaching_workflow", "worker.jobs", "web.app"):
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve().is_relative_to(target), name
from config import get_settings
from db.migration_runner import upgrade_database
from db.session import session_scope
from db.repositories.compatibility import get_or_create_default_user
from fastapi.testclient import TestClient
from web.app import create_app
settings = get_settings()
upgrade_database(settings.db_path)
with session_scope(settings.db_url) as session:
    get_or_create_default_user(session, settings.default_user_id)
with TestClient(create_app(settings, password="")) as client:
    for path in ("/", "/activities", "/trends", "/insights/dashboard", "/coach", "/plan", "/settings", "/static/css/v2.css"):
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
print("Installed wheel: imports, fresh schema, pages and assets passed")
'''


def check_wheel(wheel: Path) -> None:
    wheel = wheel.resolve(strict=True)
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    missing = REQUIRED - names
    private = [name for name in names if Path(name).suffix in {".db", ".sqlite", ".sqlite3", ".lock"}
               or ".env" in Path(name).parts or "__pycache__" in Path(name).parts
               or name.startswith("docs/private/") or "couch_running_memory" in name]
    if missing or private:
        raise ValueError(f"Invalid distribution: missing={sorted(missing)}, private={private}")
    with tempfile.TemporaryDirectory(prefix="pulse-wheel-") as folder:
        root = Path(folder)
        target = root / "site"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--no-compile",
                        "--target", str(target), str(wheel)], check=True, cwd=root)
        env = {**os.environ, "PULSE_HOME": str(root), "DB_PATH": str(root / "db" / "smoke.db"),
               "LLM_PROVIDER": "none", "ALLOW_REMOTE_LLM": "false", "REMOTE_ATHLETE_DATA_APPROVED": "false",
               "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "", "GARMIN_EMAIL": "", "GARMIN_PASSWORD": "",
               "HR_ZONES": "", "OPENAI_API_KEY": "", "AUTO_OPINIONS": "false", "GOOGLE_MAPS_API_KEY": "",
               "DEFAULT_USER_ID": "1", "WEB_PASSWORD": "", "BACKUP_DIR": str(root / "backups")}
        subprocess.run([sys.executable, "-I", "-c", SMOKE, str(target)], check=True, cwd=root, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    check_wheel(parser.parse_args().wheel)


if __name__ == "__main__":
    main()
