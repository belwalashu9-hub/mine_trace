"""CLI verification tool for Model 2 Phase 1: GDELT DOC 2.0 Integration."""
import argparse
import json
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows consoles to support international news titles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.config import get_settings
from app.core.logging import logger
from app.geopolitical.gdelt_client import (
    GdeltClient,
    GdeltRateLimitError,
    GdeltTimeoutError,
    GdeltConnectionError,
    GdeltAPIError,
)
from app.geopolitical.queries import (
    CATEGORY_QUERIES,
    CATEGORY_METADATA,
    MINERAL_QUERIES,
    build_category_query,
    build_critical_minerals_disruption_query,
)
from app.geopolitical.service import GeopoliticalService
from app.schemas.geopolitical import GeopoliticalCategory, CriticalMineral

settings = get_settings()


def main():
    parser = argparse.ArgumentParser(
        description="MineTrace Model 2: GDELT DOC 2.0 Real-Time Geopolitical Risk Monitoring Test Script"
    )
    parser.add_argument(
        "--category",
        choices=[c.value for c in GeopoliticalCategory],
        default=None,
        help="Geopolitical risk category to query (e.g. mining_strikes, trade_restrictions, port_closures)",
    )
    parser.add_argument(
        "--mineral",
        choices=[m.value for m in CriticalMineral],
        default=None,
        help="Critical mineral to prioritize (cobalt, lithium, nickel, natural_graphite)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Custom GDELT DOC 2.0 search query (overrides --category)",
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
        default=5,
        help="Maximum articles to display (default: 5, max: 25)",
    )
    parser.add_argument(
        "--fixture",
        type=str,
        default=None,
        help="Path to synthetic JSON fixture file for offline testing",
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Output raw normalized JSON records",
    )

    args = parser.parse_args()

    clamped_records = max(1, min(25, args.max_records))

    print("=" * 80)
    print(" MineTrace — Model 2: Real-Time Geopolitical Risk Monitoring (Phase 1)")
    print(" GDELT DOC 2.0 API Integration & Connectivity Test")
    print("=" * 80)

    service = GeopoliticalService()

    # Mode A: Offline Test Fixture
    if args.fixture:
        fixture_path = Path(args.fixture)
        if not fixture_path.is_file():
            # Try relative to backend root
            fixture_path = PROJECT_ROOT / args.fixture
            if not fixture_path.is_file():
                print(f"\n[ERROR] Fixture file not found: {args.fixture}")
                sys.exit(1)

        print(f"\n[MODE: OFFLINE SYNTHETIC FIXTURE]")
        print(f"Loading fixture: {fixture_path.resolve()}")
        try:
            response = service.load_from_fixture(str(fixture_path))
        except Exception as exc:
            print(f"[ERROR] Failed to load fixture: {exc}")
            sys.exit(1)

    # Mode B: Live GDELT DOC 2.0 API Query
    else:
        print(f"\n[MODE: LIVE GDELT DOC 2.0 API]")
        print(f"Target Endpoint: {settings.gdelt_base_url}")
        print(f"Lookback Window: {args.lookback_hours} hours")

        cat_enum = GeopoliticalCategory(args.category) if args.category else None
        min_enum = CriticalMineral(args.mineral) if args.mineral else None

        if args.query:
            print(f"Custom Query   : {args.query}")
        elif cat_enum:
            meta = CATEGORY_METADATA.get(cat_enum, {})
            print(f"Category       : {meta.get('name', cat_enum.value)}")
            print(f"Mineral Focus  : {min_enum.value.capitalize() if min_enum else 'All 4 Critical Minerals'}")
        else:
            print(f"Query Mode     : Critical Mineral Supply Chain Disruptions (Default)")
            print(f"Mineral Focus  : {min_enum.value.capitalize() if min_enum else 'All 4 Critical Minerals'}")

        print(f"Max Articles   : {clamped_records}")
        print("\nPacing note: GDELT strictly enforces a 5-second interval between requests per IP.")
        print("Connecting to live GDELT DOC 2.0 API...")

        try:
            response = service.fetch_geopolitical_events(
                category=cat_enum,
                mineral=min_enum,
                custom_query=args.query,
                lookback_hours=args.lookback_hours,
                max_records=clamped_records,
                raise_on_error=True,
            )
        except GdeltRateLimitError as exc:
            print("\n" + "!" * 80)
            print(" [GDELT RATE LIMIT EXCEEDED - HTTP 429]")
            print(f" Details: {exc}")
            print(" GDELT enforces a strict limit of 1 query every 5 seconds per IP.")
            print(" Solution: Wait 10-15 seconds before running another live query,")
            print(" or test offline using: --fixture tests/fixtures/gdelt_sample.json")
            print("!" * 80)
            sys.exit(1)
        except GdeltTimeoutError as exc:
            print(f"\n[ERROR: TIMEOUT] GDELT API did not respond within {settings.gdelt_timeout}s: {exc}")
            sys.exit(1)
        except GdeltConnectionError as exc:
            print(f"\n[ERROR: CONNECTION FAILED] Unable to connect to GDELT API: {exc}")
            print("Verify internet connectivity or DNS settings.")
            sys.exit(1)
        except GdeltAPIError as exc:
            print(f"\n[ERROR: API ERROR] GDELT returned HTTP {exc.status_code}: {exc}")
            sys.exit(1)
        except Exception as exc:
            print(f"\n[ERROR: UNEXPECTED] {exc}")
            sys.exit(1)

    # -------------------------------------------------------------
    # Display Results
    # -------------------------------------------------------------
    print("-" * 80)
    print(f"Query Executed       : {response.query}")
    print(f"Provider             : {response.provider}")
    print(f"Total Raw Retrieved  : {response.total_retrieved}")
    print(f"Valid Normalized     : {response.valid_articles_count}")
    print(f"Retrieved At         : {response.retrieved_at}")
    print("-" * 80)

    if not response.events:
        print("\nNo matching articles found in this time window.")
        return

    display_events = response.events[:clamped_records]

    for idx, ev in enumerate(display_events, start=1):
        print(f"\n[{idx}] {ev.title or '(No Title Available)'}")
        print(f"    Event ID     : {ev.event_id}")
        print(f"    Source URL   : {ev.source_url}")
        print(f"    Domain       : {ev.source_domain or 'Unknown'}")
        print(f"    Source Nation: {ev.source_country or 'Not Reported'}")
        print(f"    GDELT Indexed: {ev.gdelt_seen_date or 'Not Available'}")
        print(f"    Status       : {ev.classification_status} (Phase 3 will classify)")

    print("\n" + "=" * 80)
    print(" Sample Normalized JSON Record:")
    print("=" * 80)
    sample_json = json.dumps(display_events[0].model_dump(), indent=2, ensure_ascii=False)
    print(sample_json)

    if args.json_output:
        print("\n" + "=" * 80)
        print(" Full JSON Output:")
        print("=" * 80)
        print(json.dumps([e.model_dump() for e in display_events], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
