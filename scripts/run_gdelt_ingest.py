"""
CLI Ingestion Command for Model 2 Phase 2: GDELT News Ingestion, Deduplication & SQLite Persistence.

Usage:
  python scripts/run_gdelt_ingest.py --fixture tests/fixtures/gdelt_sample.json
  python scripts/run_gdelt_ingest.py --category mining_strikes --lookback-hours 24 --max-records 10
  python scripts/run_gdelt_ingest.py --category port_closures --mineral cobalt --max-records 5
"""
import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows consoles to support international headlines
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.config import get_settings
from app.core.logging import logger
from app.database.connection import get_engine, init_db, SessionLocal
from app.geopolitical.gdelt_client import (
    GdeltClient,
    GdeltRateLimitError,
    GdeltTimeoutError,
    GdeltConnectionError,
    GdeltAPIError,
)
from app.geopolitical.ingestion_service import GDELTIngestionService
from app.geopolitical.retrieval_service import GDELTRetrievalService
from app.schemas.geopolitical import GeopoliticalCategory, CriticalMineral

settings = get_settings()


def main():
    parser = argparse.ArgumentParser(
        description="MineTrace Model 2 Phase 2: GDELT News Ingestion & SQLite Persistence"
    )
    parser.add_argument(
        "--category",
        choices=[c.value for c in GeopoliticalCategory],
        default=None,
        help="Geopolitical risk category to query (e.g. mining_strikes, port_closures, trade_restrictions)",
    )
    parser.add_argument(
        "--mineral",
        choices=[m.value for m in CriticalMineral],
        default=None,
        help="Critical mineral to focus query (cobalt, lithium, nickel, natural_graphite)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Custom GDELT search query (overrides --category)",
    )
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=24,
        help="Lookback window in hours (default: 24)",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=10,
        help="Maximum articles to fetch (default: 10, max: 25)",
    )
    parser.add_argument(
        "--fixture",
        type=str,
        default=None,
        help="Path to synthetic JSON fixture file for offline ingestion",
    )
    parser.add_argument(
        "--source",
        choices=["live", "fixture"],
        default=None,
        help="Explicit source selection ('live' or 'fixture'). Inferred from --fixture if not set.",
    )
    parser.add_argument(
        "--sample-count",
        type=int,
        default=3,
        help="Number of sample stored records to display after ingestion (default: 3)",
    )

    args = parser.parse_args()

    clamped_records = max(1, min(25, args.max_records))
    source_mode = args.source or ("fixture" if args.fixture else "live")

    print("=" * 80)
    print(" MineTrace — Model 2: Real-Time Geopolitical Risk Monitoring (Phase 2)")
    print(" GDELT News Ingestion, Deduplication & SQLite Persistence Pipeline")
    print("=" * 80)
    print(f" Source Mode:       {source_mode.upper()}")
    print(f" Database Target:   {settings.database_url}")
    if source_mode == "fixture":
        print(f" Fixture Path:      {args.fixture}")
    else:
        print(f" Category:          {args.category or 'ALL (disruptions query)'}")
        print(f" Mineral:           {args.mineral or 'ALL critical minerals'}")
        print(f" Lookback Hours:    {args.lookback_hours}h")
        print(f" Max Articles:      {clamped_records}")
    print("-" * 80)

    # 1. Initialize SQLite database schema idempotently
    try:
        init_db()
        print(" [OK] Database schema initialized and verified.")
    except Exception as exc:
        print(f" [ERROR] Failed to initialize database: {exc}")
        sys.exit(1)

    # 2. Execute Ingestion Pipeline
    session = SessionLocal()
    try:
        ingestion_service = GDELTIngestionService(db=session)
        retrieval_service = GDELTRetrievalService(db=session)

        if source_mode == "fixture":
            fixture_path = Path(args.fixture)
            if not fixture_path.is_file():
                # Try relative to project root
                fixture_path = PROJECT_ROOT / args.fixture
                if not fixture_path.is_file():
                    print(f" [ERROR] Synthetic fixture file not found at: {args.fixture}")
                    sys.exit(1)

            print(f" Loading and ingesting records from synthetic fixture: {fixture_path.name}...")
            summary = ingestion_service.ingest_from_fixture(
                fixture_path=str(fixture_path),
                category=args.category,
                raise_on_error=False,
            )
        else:
            print(" Querying GDELT DOC 2.0 API (respecting rate limiter pacing)...")
            summary = ingestion_service.ingest_from_live(
                category=args.category,
                mineral=args.mineral,
                custom_query=args.query,
                lookback_hours=args.lookback_hours,
                max_records=clamped_records,
                enforce_pacing=True,
                raise_on_error=False,
            )

        # 3. Print Ingestion Metrics
        print("-" * 80)
        print(" INGESTION RUN SUMMARY")
        print("-" * 80)
        print(f" Run ID:            {summary.run_id}")
        print(f" Status:            {summary.status}")
        print(f" Provider:          {summary.provider}")
        print(f" Query Category:    {summary.query_category or 'N/A'}")
        print(f" Window:            {summary.lookback_window or 'N/A'}")
        print(f" Fetched Count:     {summary.fetched_count}")
        print(f" Valid Count:       {summary.valid_count}")
        print(f" Inserted Count:    {summary.inserted_count}")
        print(f" Updated Count:     {summary.updated_count}")
        print(f" Duplicate Count:   {summary.duplicate_count}")
        print(f" Failed Count:      {summary.failed_count}")
        if summary.error_message:
            print(f" Error Message:     {summary.error_message}")
        print("-" * 80)

        # 4. Display Sample Stored Records
        stored_articles = retrieval_service.list_articles(
            category=args.category,
            limit=args.sample_count,
        )

        total_in_db = retrieval_service.count_articles()
        pending_in_db = retrieval_service.count_articles(classification_status="pending")

        print(f" Database Status: {total_in_db} total articles stored ({pending_in_db} pending Phase 3 classification)")
        print(f" Displaying {len(stored_articles)} sample record(s):")
        print("-" * 80)

        for idx, art in enumerate(stored_articles, 1):
            cats = retrieval_service.get_article_categories(art.id)
            seen_str = art.gdelt_seen_date.strftime("%Y-%m-%d %H:%M:%S UTC") if art.gdelt_seen_date else "N/A"
            first_str = art.first_seen_at.strftime("%Y-%m-%d %H:%M:%S UTC") if art.first_seen_at else "N/A"
            last_str = art.last_seen_at.strftime("%Y-%m-%d %H:%M:%S UTC") if art.last_seen_at else "N/A"

            print(f" [{idx}] Event ID:        {art.event_id}")
            print(f"     Title:           {art.title or 'N/A'}")
            print(f"     Source Country:  {art.source_country or 'N/A'}")
            print(f"     Domain:          {art.source_domain or 'N/A'}")
            print(f"     GDELT Seen:      {seen_str}")
            print(f"     First Seen:      {first_str}")
            print(f"     Last Seen:       {last_str}")
            print(f"     Categories:      {', '.join(cats) if cats else 'None'}")
            print(f"     Classification:  {art.classification_status} (Phase 3 pending)")
            print(f"     Canonical URL:   {art.canonical_url[:75]}...")
            print()

        print("=" * 80)
        print(" Ingestion execution finished.")
        print("=" * 80)

    except Exception as exc:
        print(f" [CRITICAL ERROR] Pipeline execution encountered an unhandled error: {exc}")
        logger.exception("run_gdelt_ingest CLI error")
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
