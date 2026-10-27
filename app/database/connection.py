"""SQLite Database connection and session management."""
import os
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()

def get_engine(db_url: str = None):
    url = db_url or settings.database_url
    
    # Ensure local directory exists for SQLite file paths
    if url.startswith("sqlite:///"):
        sqlite_path = url.replace("sqlite:///", "")
        db_file = Path(sqlite_path)
        if not db_file.is_absolute():
            db_file = Path.cwd() / db_file
        db_file.parent.mkdir(parents=True, exist_ok=True)
    
    eng = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        echo=False,
    )
    
    # Enable SQLite foreign key constraints and busy timeout
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
            
    return eng

engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db(target_engine=None) -> None:
    """Idempotently initialize database tables without overwriting existing data."""
    eng = target_engine or engine
    from app.database import models  # Ensure all models are registered on Base
    Base.metadata.create_all(bind=eng)

    # Safe schema migration for SQLite: add Phase 3 columns if missing in existing table
    try:
        inspector = inspect(eng)
        if "risk_analyses" in inspector.get_table_names():
            existing_cols = {c["name"] for c in inspector.get_columns("risk_analyses")}
            with eng.connect() as conn:
                if "classification" not in existing_cols:
                    conn.execute(text("ALTER TABLE risk_analyses ADD COLUMN classification VARCHAR(32)"))
                if "flag_status" not in existing_cols:
                    conn.execute(text("ALTER TABLE risk_analyses ADD COLUMN flag_status VARCHAR(32)"))
                if "classification_explanation" not in existing_cols:
                    conn.execute(text("ALTER TABLE risk_analyses ADD COLUMN classification_explanation TEXT"))
                conn.commit()
    except Exception as exc:
        logger.debug(f"Schema column check skipped or not needed: {exc}")

    from app.database.model2_migration import quarantine_legacy_fixtures
    quarantine_legacy_fixtures(eng)
    logger.info("Database schema verified and initialized.")


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for obtaining a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
