"""Database session utilities."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings

settings = get_settings()
engine = create_engine(settings.db_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    """Provide one transactional session for the configured or supplied database."""

    session = _session_factory(database_url)()
    try:
        connection = session.connection()
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@lru_cache(maxsize=8)
def _session_factory(database_url: str | None) -> sessionmaker[Session]:
    if database_url is None or database_url == settings.db_url:
        return SessionLocal
    database_engine = create_engine(database_url, future=True)
    return sessionmaker(bind=database_engine, autoflush=False, autocommit=False, expire_on_commit=False)
