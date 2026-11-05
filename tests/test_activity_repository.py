"""Activity persistence API tests against disposable migrated databases."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from db.migration_runner import upgrade_database
from db.repositories.activity import ActivityRepository
from db.session import session_scope


def _database(path: Path) -> Path:
    upgrade_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO users(id,name,max_hr,age,marathon_goal_time,running_goal_time) "
                           "VALUES(1,'Fixture',180,30,'04:00:00','04:00:00')")
        connection.execute("INSERT INTO users(id,name,max_hr,age,marathon_goal_time,running_goal_time) "
                           "VALUES(2,'Other fixture',180,30,'04:00:00','04:00:00')")
        connection.execute("INSERT INTO activities(id,user_id,date,type,distance,duration) "
                           "VALUES(10,1,'2026-10-20','running',5,30),(11,1,'2026-10-21','running',6,34),"
                           "(12,2,'2026-10-21','running',7,38)")
        connection.execute("INSERT INTO activity_efforts(activity_id,rpe,rated_at,source) "
                           "VALUES(10,6,'2026-10-20 08:00:00','web')")
        connection.execute("INSERT INTO activity_laps(activity_id,lap_index,distance,duration) "
                           "VALUES(10,1,1,6),(10,2,1,6)")
        connection.execute("INSERT INTO activity_track_points(activity_id,point_index,elapsed_seconds,"
                           "heart_rate,latitude,longitude) VALUES(10,0,0,110,52.0,13.0),"
                           "(10,1,10,120,52.1,13.1)")
    return path


def test_list_rows_applies_user_and_date_scope_and_joins_effort(tmp_path):
    database = _database(tmp_path / "activities.db")
    with session_scope(f"sqlite:///{database}") as session:
        rows = ActivityRepository(session).list_rows(1, date(2026, 10, 21), date(2026, 10, 21))
    assert [row["id"] for row in rows] == [11]
    with session_scope(f"sqlite:///{database}") as session:
        rows = ActivityRepository(session).list_rows(1, None, None)
    assert [row["id"] for row in rows] == [11, 10]
    assert rows[1]["rpe"] == 6


def test_detail_returns_related_activity_data_and_adjacent_ids(tmp_path):
    database = _database(tmp_path / "activities.db")
    with session_scope(f"sqlite:///{database}") as session:
        detail = ActivityRepository(session).detail(1, 10, date(2026, 10, 21))
    assert detail is not None
    assert detail.activity["rpe"] == 6
    assert len(detail.laps) == 2
    assert [point["heart_rate"] for point in detail.heart_rate_points] == [110, 120]
    assert detail.previous_id is None
    assert detail.next_id == 11
    assert detail.athlete == {"max_hr": 180, "age": 30}
    with session_scope(f"sqlite:///{database}") as session:
        assert ActivityRepository(session).detail(2, 10, date(2026, 10, 21)) is None


def test_intent_mutation_is_user_scoped_and_session_scope_commits(tmp_path):
    database = _database(tmp_path / "activities.db")
    with session_scope(f"sqlite:///{database}") as session:
        assert not ActivityRepository(session).set_planned_intent(2, 10, "tempo")
    with session_scope(f"sqlite:///{database}") as session:
        assert ActivityRepository(session).set_planned_intent(1, 10, "tempo")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT planned_intent FROM activities WHERE id=10").fetchone()[0] == "tempo"


def test_session_scope_rolls_back_on_error(tmp_path):
    database = _database(tmp_path / "activities.db")
    with pytest.raises(RuntimeError, match="abort transaction"):
        with session_scope(f"sqlite:///{database}") as session:
            session.execute(text("UPDATE activities SET planned_intent='race' WHERE id=10"))
            raise RuntimeError("abort transaction")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT planned_intent FROM activities WHERE id=10").fetchone()[0] is None
