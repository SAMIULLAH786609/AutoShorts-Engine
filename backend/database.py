"""
AutoShorts Backend — SQLAlchemy Database Engine + Session.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import DATABASE_URL

# Bug 3 fixed: sslmode=require ONLY for remote/production databases (e.g. Supabase).
# Local PostgreSQL (localhost / 127.0.0.1) does not support SSL and will crash
# with "SSL connection is not supported" if sslmode=require is always set.
_is_local_db = any(
    host in DATABASE_URL
    for host in ("localhost", "127.0.0.1", "0.0.0.0")
)
_connect_args = {} if _is_local_db else {"sslmode": "require"}

# PostgreSQL engine
engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,      # reconnect if connection dropped
    pool_recycle=300,        # recycle connections every 5 min
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


def get_db():
    """FastAPI dependency — yields a database session and closes it after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (used at startup if migrations haven't run yet)."""
    # Import all models so Base knows about them
    import backend.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
