"""
AutoShorts Backend — SQLAlchemy Database Engine + Session.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import DATABASE_URL

# Bug 3 fixed: sslmode=require ONLY for remote/production databases (e.g. Supabase).
# Local PostgreSQL (localhost / 127.0.0.1) does not support SSL and will crash
# with "SSL connection is not supported" if sslmode=require is always set.
_database_url = make_url(DATABASE_URL)
if _database_url.drivername == "postgres":
    _database_url = _database_url.set(drivername="postgresql")
_is_local_db = _database_url.host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", None)
_connect_args = {}
if _database_url.get_backend_name() == "postgresql":
    _connect_args["connect_timeout"] = 15
    if not _is_local_db and "sslmode" not in _database_url.query:
        _connect_args["sslmode"] = "require"

# PostgreSQL engine
engine = create_engine(
    _database_url,
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
