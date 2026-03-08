from __future__ import annotations

from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session, sessionmaker
from sqlalchemy.pool import NullPool

from alphaagent.db.models import Base

_engine: Optional[Engine] = None
_SessionLocal = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        from alphaagent.config import settings
        _engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            poolclass=NullPool,
        )
    return _engine


def _get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal


def create_tables() -> None:
    """Idempotent: creates all tables if they don't exist."""
    Base.metadata.create_all(bind=_get_engine())


@contextmanager
def get_db():
    """Yield a database session; commit on success, rollback on exception."""
    factory = _get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
