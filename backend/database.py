"""
AutoShorts Backend — SQLAlchemy Database Engine + Session.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import DATABASE_URL

# PostgreSQL engine — connect_args for SSL required by Supabase
engine = create_engine(
    DATABASE_URL,
    connect_args={"sslmode": "require"},
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
