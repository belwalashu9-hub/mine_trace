"""Back up configured SQLite file before additive migrations."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from app.database.connection import init_db, settings
if __name__=='__main__':
    url=settings.database_url
    if not url.startswith('sqlite:///'):raise SystemExit('This migration supports SQLite only')
    path=Path(url.removeprefix('sqlite:///'))
    if path.exists():
        backup=path.with_name(path.name+'.backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        with sqlite3.connect(path) as src,sqlite3.connect(backup) as dst:src.backup(dst)
        print('Backup:',backup)
    init_db();print('Model 2 additive migration complete; Model 1 tables unchanged.')
