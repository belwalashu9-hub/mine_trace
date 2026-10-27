"""CLI script to initialize the SQLite database schema."""
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.logging import logger
from app.database.connection import init_db, settings

if __name__ == "__main__":
    logger.info(f"Initializing database at: {settings.database_url}")
    init_db()
    logger.info("Database initialization completed successfully.")
