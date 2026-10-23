"""Migration safety checks use only synthetic databases under pytest's temp directory."""

import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db import migration_runner
from db.migration_runner import BASELINE, migration_config, upgrade_database
from db.models import Base
from db.repository import get_or_create_default_goal, get_or_create_default_user
from scripts.backup_db import backup_database

SCHEMA = Path(__file__).parents[1] / "db/migrations/baseline.sql"
HEAD = "0006_weekly_plan"


def tables(connection):
    return [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY name"
    )]


def snapshot(database):
    with closing(sqlite3.connect(database)) as connection:
        old_tables = [table for table in tables(connection) if table not in {
            "activity_coaching_opinion_history", "coach_chat_turns", "coach_llm_calls",
            "weekly_plans", "coach_plan_proposals", "coach_plan_changes", "coach_plan_undo",
        }]
        counts = {table: connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in old_tables}
        payloads = {}
        for table in old_tables:
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            for column in ("payload_json", "prompt_context_json"):
                if column in columns:
                    payloads[table, column] = connection.execute(f'SELECT id, {column} FROM "{table}" ORDER BY id').fetchall()
        body = {
            table: (
                connection.execute("SELECT type, name, sql FROM sqlite_master WHERE tbl_name=? ORDER BY type, name", (table,)).fetchall(),
                connection.execute(f'SELECT * FROM "{table}" ORDER BY id').fetchall(),
            ) for table in old_tables if table.startswith("body_scan")
        }
        return counts, payloads, body


def dump(database):
    with closing(sqlite3.connect(database)) as connection:
        return "\n".join(connection.iterdump())


@pytest.fixture(params=["old", "runtime"])
def legacy_copy(tmp_path, request):
    """Build invented data, then migrate a copy, never a checkout database."""
    source = tmp_path / "synthetic-old.db"
    with closing(sqlite3.connect(source)) as connection:
        connection.executescript(SCHEMA.read_text())
        # Populate every table so preservation checks are not vacuous.
        for table in tables(connection):
            values = {}
            for _, name, kind, _, _, _ in connection.execute(f'PRAGMA table_info("{table}")'):
                if name.endswith("_json"):
                    value = '{ "legacy": true, "items": [1, 2], "text": "keep spacing" }'
                elif "INT" in kind or "BOOL" in kind:
                    value = 1
                elif "FLOAT" in kind:
                    value = 42.5
                elif "DATE" in kind:
                    value = "2025-01-02" if kind == "DATE" else "2025-01-02 03:04:05"
                else:
                    value = "synthetic"
                values[name] = value
            columns = ", ".join(f'"{name}"' for name in values)
            placeholders = ", ".join("?" for _ in values)
            connection.execute(f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})', tuple(values.values()))
        connection.execute("UPDATE users SET marathon_goal_time='03:42:00', running_goal_time='04:15:00', running_date='2026-09-27'")
        connection.execute("UPDATE goals SET name='Primary Marathon Goal', goal_type='marathon_pb', notes='Default active goal created from app settings.'")
        for identifier, name, notes, goal_type in (
            (2, "My Berlin Marathon", "Default active goal created from app settings.", "marathon_pb"),
            (3, "Primary Marathon Goal", "User-created goal", "marathon_pb"),
            (4, "Primary Marathon Goal", "Default active goal created from app settings.", "5k_pb"),
            (5, "Primary Marathon Goal - edited", None, "marathon_pb"),
        ):
            connection.execute("""
                INSERT INTO goals SELECT ?, user_id, ?, ?, target_distance_km, target_time_minutes,
                target_date, priority, status, is_active, ?, created_at, updated_at FROM goals WHERE id=1
            """, (identifier, name, goal_type, notes))
        missing_columns = {
            "users": ["name", "training_days_per_week", "injury_notes", "running_goal_time", "running_date"],
            "activities": ["activity_name"],
            "activity_coaching_insights": ["updated_at"],
        }
        if request.param == "old":
            for table, columns in missing_columns.items():
                for column in columns:
                    connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        connection.execute("ALTER TABLE body_scans ADD COLUMN private_extension TEXT")
        connection.execute("UPDATE body_scans SET private_extension='keep this too'")
        connection.execute("CREATE INDEX custom_body_index ON body_scans(processor_name)")
        connection.commit()
    candidate = tmp_path / "candidate.db"
    shutil.copy2(source, candidate)
    return source, candidate


def test_fresh_upgrade_and_default_user(tmp_path):
    database = tmp_path / "fresh.db"
    assert upgrade_database(database) is None
    with closing(sqlite3.connect(database)) as connection:
        assert len(tables(connection)) == 22
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)
        columns = {row[1]: row for row in connection.execute("PRAGMA table_info(activity_coaching_insights)")}
        for name in ("schema_version", "prompt_version"):
            assert columns[name][3:5] == (0, None)
        assert columns["validation_notes"][3:5] == (0, None)
        assert "planned_intent" in {row[1] for row in connection.execute("PRAGMA table_info(activities)")}
        assert "activity_coaching_opinion_history" in tables(connection)
        assert "coach_chat_turns" in tables(connection)
        assert "coach_llm_calls" in tables(connection)
        for name in ("weekly_plans", "coach_plan_proposals", "coach_plan_changes", "coach_plan_undo"):
            assert name in tables(connection)
        assert "expected_revision" in {row[1] for row in connection.execute("PRAGMA table_info(coach_plan_undo)")}
        assert "after_json" in {row[1] for row in connection.execute("PRAGMA table_info(coach_plan_undo)")}
        assert {row[1] for row in connection.execute("PRAGMA table_info(coach_chat_turns)")} == {
            "id", "user_id", "question", "answer", "evidence_json", "activity_ids_json",
            "tool_calls_json", "model_provider", "model_name", "prompt_version", "created_at",
        }
        assert "marathon_goal_time" in {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    engine = create_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as session:
            user = get_or_create_default_user(session, 1)
            assert get_or_create_default_goal(session, user).name == "Primary Running Goal"
            session.commit()
    finally:
        engine.dispose()
    before = database.read_bytes()
    assert upgrade_database(database) is None
    assert database.read_bytes() == before


def test_existing_upgrade_preserves_data_and_body_tables(legacy_copy):
    source, database = legacy_copy
    before = snapshot(database)
    source_dump = dump(source)
    with closing(sqlite3.connect(source)) as connection:
        has_running_fields = "running_goal_time" in {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    expected_profile = ("04:15:00", "2026-09-27") if has_running_fields else ("03:59:59", "2025-01-02")
    backup = upgrade_database(database)
    assert backup is not None
    assert dump(backup) == source_dump
    assert snapshot(database) == before
    assert dump(source) == source_dump
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)
        assert connection.execute("SELECT schema_version, prompt_version FROM activity_coaching_insights").fetchall() == [(None, None)]
        assert connection.execute("SELECT validation_notes FROM activity_coaching_insights").fetchall() == [(None,)]
        assert connection.execute("SELECT planned_intent FROM activities").fetchall() == [(None,)]
        assert connection.execute("SELECT count(*) FROM activity_coaching_opinion_history").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM coach_chat_turns").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM coach_llm_calls").fetchone() == (0,)
        for name in ("weekly_plans", "coach_plan_proposals", "coach_plan_changes", "coach_plan_undo"):
            assert connection.execute(f"SELECT count(*) FROM {name}").fetchone() == (0,)
        assert connection.execute("SELECT running_goal_time, running_date FROM users").fetchone() == expected_profile
        assert connection.execute("SELECT name, goal_type FROM goals ORDER BY id").fetchall() == [
            ("Primary Running Goal", "running_pb"), ("My Berlin Marathon", "running_pb"),
            ("Primary Marathon Goal", "running_pb"), ("Primary Marathon Goal", "5k_pb"),
            ("Primary Marathon Goal - edited", "running_pb"),
        ]
        connection.execute("UPDATE users SET running_goal_time='04:00:00'")
        connection.commit()
    first_dump, first_bytes = dump(database), database.read_bytes()
    assert upgrade_database(database) is None
    assert dump(database) == first_dump
    assert database.read_bytes() == first_bytes


def test_stamp_does_not_touch_existing_application_schema_or_data(legacy_copy):
    _, database = legacy_copy
    before = snapshot(database)
    with closing(sqlite3.connect(database)) as connection:
        schema_before = connection.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.begin() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            command.stamp(config, BASELINE)
    finally:
        engine.dispose()
    assert snapshot(database) == before
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT name, sql FROM sqlite_master WHERE tbl_name != 'alembic_version' ORDER BY name").fetchall() == schema_before


def test_missing_tables_are_created_without_adding_body_tables(tmp_path):
    database = tmp_path / "old-minimal.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, age INTEGER, gender VARCHAR(20), weight FLOAT, height FLOAT, max_hr INTEGER)")
    upgrade_database(database)
    with closing(sqlite3.connect(database)) as connection:
        assert len(tables(connection)) == 20
        assert "prediction_snapshots" in tables(connection)
        assert "garmin_sync_status" in tables(connection)


def test_planned_intent_database_constraint_on_fresh_upgrade(tmp_path):
    database = tmp_path / "intent-check.db"
    upgrade_database(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("INSERT INTO users (id, marathon_goal_time, running_goal_time) VALUES (1, '04:00:00', '04:00:00')")
        connection.execute("INSERT INTO activities (id, user_id, date, type, distance, duration, planned_intent) "
                           "VALUES (1, 1, '2026-05-22', 'running', 5, 30, 'easy')")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO activities (id, user_id, date, type, distance, duration, planned_intent) "
                               "VALUES (2, 1, '2026-05-23', 'running', 5, 30, 'sprint')")


def test_current_model_only_database_still_works(tmp_path):
    database = tmp_path / "model-only.db"
    engine = create_engine(f"sqlite:///{database}")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE activity_coaching_insights DROP COLUMN schema_version")
            connection.exec_driver_sql("ALTER TABLE activity_coaching_insights DROP COLUMN prompt_version")
        upgrade_database(database)
        with Session(engine) as session:
            assert get_or_create_default_user(session, 1).name == "Demo Athlete"
            session.commit()
    finally:
        engine.dispose()


def test_backup_failure_prevents_stamp_or_upgrade(legacy_copy, monkeypatch):
    _, database = legacy_copy
    before = dump(database)

    def fail(*args):
        raise OSError("backup disk full")

    monkeypatch.setattr(migration_runner, "backup_database", fail)
    with pytest.raises(OSError, match="backup disk full"):
        upgrade_database(database)
    assert dump(database) == before


def test_failed_upgrade_rolls_back_stamp_and_ddl(legacy_copy, monkeypatch):
    _, database = legacy_copy
    before = dump(database)

    def fail(config, target):
        config.attributes["connection"].exec_driver_sql("ALTER TABLE users ADD COLUMN should_rollback TEXT")
        raise RuntimeError("synthetic migration failure")

    monkeypatch.setattr(command, "upgrade", fail)
    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        upgrade_database(database)
    assert dump(database) == before


def test_backup_includes_committed_wal_and_keeps_exact_filename(tmp_path):
    database = tmp_path / "marathon_coach.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE example(value TEXT)")
        connection.execute("INSERT INTO example VALUES ('committed WAL data')")
        connection.commit()
        first = backup_database(database)
        second = backup_database(database)
        assert first != second
        assert first.stat().st_mode & 0o077 == 0
        assert dump(first) == dump(database)
        assert dump(second) == dump(database)
    assert not (tmp_path / "running_coach.db").exists()


def test_unknown_database_is_not_stamped(tmp_path):
    database = tmp_path / "unrelated.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE unrelated(id INTEGER)")
    before = dump(database)
    with pytest.raises(RuntimeError, match="Not a recognized"):
        upgrade_database(database)
    assert dump(database) == before


def test_baseline_matches_frozen_runtime_schema(tmp_path):
    database = tmp_path / "baseline.db"
    expected = tmp_path / "expected.db"
    with closing(sqlite3.connect(expected)) as connection:
        connection.executescript(SCHEMA.read_text())
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.begin() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, BASELINE)
    finally:
        engine.dispose()
    with closing(sqlite3.connect(expected)) as source, closing(sqlite3.connect(database)) as target:
        assert tables(source) == tables(target)
        for table in tables(source):
            assert source.execute(f'PRAGMA table_info("{table}")').fetchall() == target.execute(f'PRAGMA table_info("{table}")').fetchall()
            # Reflection can reorder constraints, but their column mappings must match.
            for pragma in ("foreign_key_list", "index_list"):
                old = [row[1:] for row in source.execute(f'PRAGMA {pragma}("{table}")')]
                new = [row[1:] for row in target.execute(f'PRAGMA {pragma}("{table}")')]
                assert sorted(old) == sorted(new)


def test_baseline_refuses_to_recreate_existing_database(legacy_copy):
    _, database = legacy_copy
    before = snapshot(database)
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.begin() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            with pytest.raises(RuntimeError, match="must be stamped"):
                command.upgrade(config, BASELINE)
    finally:
        engine.dispose()
    assert snapshot(database) == before


def test_cli_upgrade_backs_up_before_changes(legacy_copy):
    source, database = legacy_copy
    result = subprocess.run(
        [sys.executable, "-m", "scripts.upgrade_db", "--db", str(database)],
        check=True, capture_output=True, text=True,
    )
    assert "Pre-upgrade backup:" in result.stdout
    backups = list((database.parent / "backups").glob("*.db"))
    assert len(backups) == 1
    assert dump(backups[0]) == dump(source)


@pytest.mark.parametrize("state", ["missing", "unversioned", "baseline", "head"])
def test_startup_only_checks_revision_on_temporary_database(tmp_path, monkeypatch, state):
    from db import setup

    database = tmp_path / "startup.db"
    if state == "unversioned":
        with closing(sqlite3.connect(database)) as connection:
            connection.executescript(SCHEMA.read_text())
    elif state in {"baseline", "head"}:
        upgrade_database(database)
        if state == "baseline":
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("UPDATE alembic_version SET version_num=?", (BASELINE,))
                connection.commit()
    engine = create_engine(f"sqlite:///{database}")
    monkeypatch.setattr(setup, "engine", engine)
    before = database.read_bytes() if database.exists() else None
    try:
        if state == "head":
            setup.init_db()
        else:
            with pytest.raises(RuntimeError) as error:
                setup.init_db()
            assert str(error.value) == (
                "Database needs an upgrade. Stop all jobs, then run:\n"
                f"python -m scripts.upgrade_db --db {database}"
            )
        assert (database.read_bytes() if database.exists() else None) == before
        assert not (tmp_path / "backups").exists()
    finally:
        engine.dispose()


def test_raw_alembic_upgrade_cannot_bypass_backup_runner():
    with pytest.raises(RuntimeError, match="automatic backup required"):
        command.upgrade(migration_config(), "head")


def test_legacy_profile_backfill_only_fills_null_fields(tmp_path):
    database = tmp_path / "nullable-profile.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("""CREATE TABLE users (
            id INTEGER PRIMARY KEY, marathon_goal_time VARCHAR(16), marathon_date DATE,
            running_goal_time VARCHAR(16), running_date DATE
        )""")
        connection.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?)", [
            (1, "03:42:00", "2025-01-02", "04:15:00", "2026-09-27"),
            (2, "03:42:00", "2025-01-02", None, None),
            (3, None, None, None, None),
            (4, "03:42:00", "2025-01-02", "", ""),
            (5, "03:42:00", "2025-01-02", "04:15:00", None),
            (6, "03:42:00", "2025-01-02", None, "2026-09-27"),
        ])
        connection.commit()
    upgrade_database(database)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT running_goal_time, running_date FROM users ORDER BY id").fetchall() == [
            ("04:15:00", "2026-09-27"), ("03:42:00", "2025-01-02"),
            (None, None), ("", ""), ("04:15:00", "2025-01-02"), ("03:42:00", "2026-09-27"),
        ]


@pytest.mark.parametrize("entrypoint", ["streamlit", "telegram", "sync", "digest"])
def test_app_entrypoints_stop_before_work_when_database_is_behind(tmp_path, monkeypatch, entrypoint):
    from unittest.mock import Mock

    from db import setup
    from services.telegram_chatbot import TelegramTrainingChatBot
    from services.training_context_service import AppBootstrapService
    from utils import daily_digest_cli, garmin_sync_cli

    database = tmp_path / "behind.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(SCHEMA.read_text())
    before = database.read_bytes()
    engine = create_engine(f"sqlite:///{database}")
    monkeypatch.setattr(setup, "engine", engine)
    monkeypatch.setattr(sys, "argv", ["test"])
    work = Mock(side_effect=AssertionError("Work must not start before the schema check"))
    if entrypoint == "streamlit":
        start = AppBootstrapService(session_scope_factory=work).initialize_default_user
    elif entrypoint == "telegram":
        telegram = Mock()
        telegram.get_updates = work
        start = TelegramTrainingChatBot(telegram_service=telegram, chat_service=Mock()).run_polling
    else:
        module = garmin_sync_cli if entrypoint == "sync" else daily_digest_cli
        monkeypatch.setattr(module, "session_scope", work)
        start = module.main
    try:
        with pytest.raises(RuntimeError, match="Database needs an upgrade"):
            start()
        work.assert_not_called()
        assert database.read_bytes() == before
        assert not (tmp_path / "backups").exists()
    finally:
        engine.dispose()
