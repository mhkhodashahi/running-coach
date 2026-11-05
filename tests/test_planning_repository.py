"""Planning persistence queries are scoped and bounded on disposable databases."""

import json
import sqlite3
from datetime import date
from pathlib import Path

from db.migration_runner import upgrade_database
from db.repositories.planning import PlanningRepository
from db.session import session_scope


def _database(path: Path) -> Path:
    upgrade_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO users(id,name,max_hr,age,marathon_goal_time,running_goal_time) "
            "VALUES(1,'Fixture',180,30,'04:00:00','04:00:00')"
        )
        connection.execute(
            "INSERT INTO users(id,name,max_hr,age,marathon_goal_time,running_goal_time) "
            "VALUES(2,'Other fixture',175,35,'04:00:00','04:00:00')"
        )
        connection.execute(
            "INSERT INTO activities(id,user_id,date,type,distance,duration,planned_intent) VALUES "
            "(10,1,'2026-10-01','running',5,30,'easy'),"
            "(11,1,'2026-10-20','running',6,34,'tempo'),"
            "(12,2,'2026-10-20','gym',0,40,NULL)"
        )
        connection.execute(
            "INSERT INTO goals(id,user_id,name,goal_type,target_distance_km,target_time_minutes,"
            "priority,status,is_active,created_at,updated_at) "
            "VALUES(1,1,'Fixture goal','10k_pb',10,50,'A','active',1,'2026-10-01','2026-10-01')"
        )
        connection.execute(
            "INSERT INTO activity_laps(id,activity_id,lap_index,distance,duration,pace,avg_hr) "
            "VALUES(1,10,1,1,6,6,140),(2,11,1,1,5,5,155)"
        )
        connection.execute(
            "INSERT INTO plan_sessions(id,user_id,date,sport,intent,duration_min,origin,status,workout_json,"
            "created_at,updated_at) VALUES(20,1,'2026-10-20','running','tempo',40,'coach','planned',?,"
            "'2026-10-20','2026-10-20')",
            (json.dumps({"type": "tempo", "steps": [{"reps": 4}]}),),
        )
        connection.execute(
            "INSERT INTO coaching_decisions(id,user_id,decision_type,decision_date,summary,risk_level,payload_json,"
            "created_at) VALUES(30,1,'daily_v2','2026-10-20','Fixture decision','low',?,'2026-10-20')",
            (json.dumps({"athlete_choice": "easy"}),),
        )
        connection.execute(
            "INSERT INTO coach_proposals(id,user_id,kind,base_version,status,summary,facts_json,created_at) "
            "VALUES(40,1,'change',3,'pending',?, '[]','2026-10-20')",
            ("Review today's session (2026-10-20)",),
        )
    return path


def test_habit_and_intent_reads_are_date_and_user_scoped(tmp_path):
    database = _database(tmp_path / "planning.db")
    with session_scope(f"sqlite:///{database}") as session:
        repository = PlanningRepository(session)
        rows = repository.habit_activities(1, date(2026, 10, 1), date(2026, 10, 20))
        intents = repository.planned_intents(1, date(2026, 10, 20))
    assert [row["date"] for row in rows] == ["2026-10-01"]
    assert intents == {10: "easy", 11: "tempo"}


def test_week_history_returns_profile_goal_flag_and_bounded_activities(tmp_path):
    database = _database(tmp_path / "planning.db")
    with session_scope(f"sqlite:///{database}") as session:
        history = PlanningRepository(session).week_history(1, date(2026, 10, 20), 7)
    assert history.profile == {"max_hr": 180, "age": 30}
    assert history.has_running_goal
    assert history.recent_activities == [{"type": "running", "duration": 34.0, "date": "2026-10-20"}]
    with session_scope(f"sqlite:///{database}") as session:
        other = PlanningRepository(session).week_history(2, date(2026, 10, 20), 7)
    assert not other.has_running_goal
    assert [row["type"] for row in other.recent_activities] == ["gym"]


def test_workout_history_returns_recent_inputs_and_previous_workout_json(tmp_path):
    database = _database(tmp_path / "planning.db")
    with session_scope(f"sqlite:///{database}") as session:
        history = PlanningRepository(session).workout_history(1, date(2026, 10, 26))
    assert history.profile == {"max_hr": 180, "age": 30}
    assert history.goal["target_distance_km"] == 10
    assert history.laps[0]["pace"] == 6
    assert history.activities[0]["distance"] == 5
    assert json.loads(history.previous_workouts[0])["type"] == "tempo"


def test_daily_choice_and_proposal_duplicate_checks_are_scoped(tmp_path):
    database = _database(tmp_path / "planning.db")
    with session_scope(f"sqlite:///{database}") as session:
        repository = PlanningRepository(session)
        assert repository.logged_activity_types(1, date(2026, 10, 20)) == ["running"]
        assert repository.athlete_choice(1, date(2026, 10, 20)) == '{"athlete_choice": "easy"}'
        assert repository.athlete_choice(2, date(2026, 10, 20)) is None
        assert repository.has_daily_conflict_proposal(
            1, 3, "Review today's session (2026-10-20)"
        )
        assert not repository.has_daily_conflict_proposal(
            2, 3, "Review today's session (2026-10-20)"
        )
