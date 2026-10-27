"""Quarantine exactly identified legacy synthetic fixtures without deleting records."""
import json
from pathlib import Path
from sqlalchemy import text
from app.geopolitical.normalizer import canonicalize_url

def quarantine_legacy_fixtures(engine):
    fixture=Path(__file__).resolve().parents[2]/'tests/fixtures/gdelt_sample.json'
    if not fixture.exists():return
    urls=[canonicalize_url(a.get('url')) for a in json.loads(fixture.read_text())['articles']]
    with engine.begin() as conn:
        for url in urls:
            conn.execute(text("UPDATE gdelt_articles SET provider='synthetic_fixture' WHERE canonical_url=:url"),{'url':url})
