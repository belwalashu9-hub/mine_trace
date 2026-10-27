"""CLI script to run data ingestion for UN Comtrade and OFAC Sanctions."""
import argparse
import sys
from pathlib import Path
from typing import Optional, List

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.logging import logger
from app.database.connection import SessionLocal, init_db
from app.ingestion.service import IngestionService


def resolve_fixture_path(
    path_str: Optional[str],
    label: str,
    default_candidates: List[str],
    parser: argparse.ArgumentParser,
) -> Optional[str]:
    """
    Resolves fixture path across CWD, project root, and tests/fixtures directory.
    Validates file existence and provides clear, actionable error messages if missing.
    """
    if not path_str:
        return None

    path_str = path_str.strip()
    if not path_str:
        return None

    p = Path(path_str)

    # 1. Direct path as specified (relative to CWD or absolute)
    if p.is_file():
        return str(p.resolve())

    # 2. Relative to PROJECT_ROOT
    p_proj = PROJECT_ROOT / path_str
    if p_proj.is_file():
        return str(p_proj.resolve())

    # 3. Inside PROJECT_ROOT/tests/fixtures
    p_fix = PROJECT_ROOT / "tests" / "fixtures" / p.name
    if p_fix.is_file():
        return str(p_fix.resolve())

    # If file cannot be found, provide helpful error with available fixtures
    available: List[str] = []
    fixtures_dir = PROJECT_ROOT / "tests" / "fixtures"
    if fixtures_dir.is_dir():
        for cand in fixtures_dir.iterdir():
            if cand.is_file() and not cand.name.startswith("."):
                available.append(f"tests/fixtures/{cand.name}")

    avail_info = (
        f"\n  Available fixtures in tests/fixtures/:\n    " + "\n    ".join(available)
        if available
        else ""
    )
    parser.error(
        f"{label} fixture file not found: '{path_str}'.{avail_info}\n"
        f"  Please provide a valid file path or use the default fixture."
    )
    return None


def main():
    parser = argparse.ArgumentParser(
        description="MineTrace Data Ingestion CLI — Ingest UN Comtrade trade data and OFAC Sanctions into local SQLite."
    )
    parser.add_argument(
        "--source",
        choices=["trade", "sanctions", "all"],
        default="all",
        help="Data source to ingest (trade, sanctions, or all). Default: all",
    )
    parser.add_argument(
        "--trade-fixture",
        type=str,
        nargs="?",
        const="tests/fixtures/comtrade_sample.json",
        default=None,
        help=(
            "Path to UN Comtrade JSON fixture file. "
            "If flag is passed without argument, defaults to 'tests/fixtures/comtrade_sample.json'."
        ),
    )
    parser.add_argument(
        "--sanctions-fixture",
        type=str,
        nargs="?",
        const="tests/fixtures/ofac_sample.csv",
        default=None,
        help=(
            "Path to OFAC sanctions fixture file (.csv or .json). "
            "If flag is passed without argument, defaults to 'tests/fixtures/ofac_sample.csv'."
        ),
    )
    parser.add_argument(
        "--commodity-codes",
        type=str,
        default=None,
        help="Comma-separated HS commodity codes (e.g. 283691,282520)",
    )
    parser.add_argument(
        "--periods",
        type=str,
        default=None,
        help="Comma-separated years or periods (e.g. 2023,2024)",
    )

    args = parser.parse_args()

    # Resolve and validate fixture paths early with helpful messages
    trade_fixture_resolved = None
    if args.trade_fixture is not None:
        trade_fixture_resolved = resolve_fixture_path(
            args.trade_fixture,
            "UN Comtrade",
            ["tests/fixtures/comtrade_sample.json"],
            parser,
        )

    sanctions_fixture_resolved = None
    if args.sanctions_fixture is not None:
        sanctions_fixture_resolved = resolve_fixture_path(
            args.sanctions_fixture,
            "OFAC Sanctions",
            ["tests/fixtures/ofac_sample.csv", "tests/fixtures/ofac_sample.json"],
            parser,
        )

    # Ensure DB schema is initialized
    init_db()

    db = SessionLocal()
    service = IngestionService(db)

    try:
        # Run trade ingestion
        if args.source in ("trade", "all"):
            codes = [c.strip() for c in args.commodity_codes.split(",")] if args.commodity_codes else None
            periods = [p.strip() for p in args.periods.split(",")] if args.periods else None
            
            logger.info("Starting UN Comtrade trade data ingestion...")
            trade_res = service.ingest_trade_data(
                commodity_codes=codes,
                periods=periods,
                fixture_path=trade_fixture_resolved,
            )
            logger.info(f"Trade ingestion result: {trade_res['message']}")

        # Run sanctions ingestion
        if args.source in ("sanctions", "all"):
            logger.info("Starting OFAC sanctions data ingestion...")
            sanctions_res = service.ingest_sanctions_data(
                fixture_path=sanctions_fixture_resolved,
            )
            logger.info(f"Sanctions ingestion result: {sanctions_res['message']}")

        logger.info("All requested ingestion tasks completed successfully.")

    except Exception as exc:
        logger.error(f"Ingestion failed: {exc}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
