"""Read the frozen schema snapshot without importing mutable application models."""

import sqlite3
from pathlib import Path

from sqlalchemy import MetaData, create_engine


def baseline_metadata() -> MetaData:
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            raw: sqlite3.Connection = connection.connection.driver_connection
            raw.executescript(Path(__file__).with_name("baseline.sql").read_text())
            metadata = MetaData()
            metadata.reflect(bind=connection)
            return metadata
    finally:
        engine.dispose()
