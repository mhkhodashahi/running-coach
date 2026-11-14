"""Performance checks assert bounded work and preserved data, not fragile timings."""

import asyncio
import sqlite3
from datetime import date

import pytest
from alembic import command
from sqlalchemy import create_engine

from db.migration_runner import migration_config, upgrade_database
from metrics.calculation_scope import calculation_scope, memoized_calculation


def test_calculation_scope_reuses_only_identical_inputs_and_discards_results():
    calls = []

    @memoized_calculation
    def compute(user_id, day):
        calls.append((user_id, day))
        return len(calls)

    assert compute(1, day="first") == 1
    assert compute(1, day="first") == 2
    with calculation_scope():
        assert compute(1, day="first") == 3
        with calculation_scope():
            assert compute(1, day="first") == 3
        assert compute(2, day="first") == 4
        assert compute(1, day="second") == 5
    with calculation_scope():
        assert compute(1, day="first") == 6


def test_scope_clears_on_exception_and_does_not_cache_failures():
    calls = []

    @memoized_calculation
    def compute():
        calls.append(True)
        if len(calls) < 2:
            raise ValueError("fixture")
        return len(calls)

    with pytest.raises(ValueError), calculation_scope():
        compute()
    with calculation_scope():
        assert compute() == compute() == 2
    assert compute() == 3


def test_concurrent_renders_do_not_share_cached_results():
    @memoized_calculation
    def compute():
        return object()

    async def render():
        with calculation_scope():
            first = compute()
            await asyncio.sleep(0)
            assert first is compute()
            return first

    async def run():
        return await asyncio.gather(render(), render())

    first, second = asyncio.run(run())
    assert first is not second


def test_index_migration_preserves_rows_and_uses_composite_indexes(tmp_path):
    path = tmp_path / "indexes.db"
    upgrade_database(path)
    engine = create_engine(f"sqlite:///{path}")
    config = migration_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0018_coach_memories")
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO users(id,max_hr,age,marathon_goal_time) VALUES(1,190,30,'04:00:00')")
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration) "
                           "VALUES(1,1,'2026-01-02','running',5,30)")
        connection.execute("INSERT INTO activity_track_points(activity_id,point_index,timestamp) "
                           "VALUES(1,0,'2026-01-02T08:00:00')")
        connection.execute("INSERT INTO coaching_decisions(user_id,decision_type,decision_date,summary,risk_level,"
                           "payload_json,created_at) VALUES(1,'daily_v2','2026-01-02','Fixture','low','{}','2026-01-02')")
        connection.commit()
        before = [line for line in connection.iterdump() if line.startswith("INSERT") and
                  '"alembic_version"' not in line]
    backup = upgrade_database(path)
    assert backup and backup.exists()
    with sqlite3.connect(path) as connection:
        after = [line for line in connection.iterdump() if line.startswith("INSERT") and
                 '"alembic_version"' not in line]
        assert before == after
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        queries = (
            ("SELECT id,date FROM activities WHERE user_id=1 ORDER BY date,id", "ix_activities_user_date"),
            ("SELECT MIN(timestamp) FROM activity_track_points WHERE activity_id=1",
             "ix_activity_track_points_activity_timestamp"),
            ("SELECT payload_json FROM coaching_decisions WHERE user_id=1 AND decision_type='daily_v2' "
             "AND decision_date='2026-01-02' ORDER BY id DESC LIMIT 1", "ix_coaching_decisions_user_type_date"),
        )
        for query, index in queries:
            plan = str(connection.execute("EXPLAIN QUERY PLAN " + query).fetchall())
            assert index in plan
            assert "TEMP B-TREE" not in plan
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0018_coach_memories")
    with sqlite3.connect(path) as connection:
        assert before == [line for line in connection.iterdump() if line.startswith("INSERT") and
                          '"alembic_version"' not in line]
        assert not connection.execute("SELECT name FROM sqlite_master WHERE name IN "
                                      "('ix_activities_user_date','ix_activity_track_points_activity_timestamp',"
                                      "'ix_coaching_decisions_user_type_date')").fetchall()
    engine.dispose()


def test_snapshot_reuse_is_scoped_by_date_and_user(monkeypatch, tmp_path):
    from metrics import reader

    calls = []

    def read(*args):
        calls.append(args)
        return args

    monkeypatch.setattr(reader, "read_inputs", read)
    monkeypatch.setattr(reader, "build_daily_snapshot", lambda *args: args)
    kwargs = {"database": tmp_path / "unused.db", "user_id": 1, "timezone": "UTC",
              "sleep_goal_hours": 8, "hr_zones": ()}
    with calculation_scope():
        first = reader.get_daily_snapshot(date(2026, 1, 2), **kwargs)
        assert reader.get_daily_snapshot(date(2026, 1, 2), **kwargs) is first
        reader.get_daily_snapshot(date(2026, 1, 3), **kwargs)
        reader.get_daily_snapshot(date(2026, 1, 2), **(kwargs | {"user_id": 2}))
    assert len(calls) == 3
    reader.get_daily_snapshot(date(2026, 1, 2), **kwargs)
    assert len(calls) == 4
