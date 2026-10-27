"""Client for fetching and parsing official OFAC Sanctions List data."""
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()


class OfacAPIError(Exception):
    """Custom exception raised for OFAC data retrieval failures."""
    pass


class OfacClient:
    """
    Downloads and parses the official US Treasury OFAC SDN (Specially Designated Nationals)
    data in structured format, preserving local cached copies for offline-first resilience.
    """

    def __init__(
        self,
        sdn_url: Optional[str] = None,
        timeout: Optional[float] = None,
        cache_dir: Optional[Path] = None,
    ):
        self.sdn_url = sdn_url or settings.ofac_sdn_csv_url
        self.timeout = timeout or settings.request_timeout_seconds
        self.cache_dir = cache_dir or settings.raw_data_dir

    def _ensure_cache_dir(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir

    def fetch_sdn_list(self, custom_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Downloads official OFAC SDN CSV data.
        Saves a local copy into data/raw/sdn_latest.csv so offline queries work reliably.
        If network fails, falls back to previously cached local copy if available.
        """
        url = custom_url or self.sdn_url
        retrieval_timestamp = datetime.now(timezone.utc)
        cache_file = self._ensure_cache_dir() / "ofac_sdn_latest.csv"

        try:
            logger.info(f"Downloading official OFAC SDN data from {url}")
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.get(url, headers={"User-Agent": "MineTrace/0.1.0 (Compliance Data Ingestion)"})
                
                if response.status_code >= 400:
                    raise OfacAPIError(
                        f"OFAC download failed with status {response.status_code}: {response.text[:200]}"
                    )
                
                raw_csv_text = response.text
                
                # Persist locally for offline-first durability
                try:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        f.write(raw_csv_text)
                    logger.info(f"Saved latest OFAC SDN cache to {cache_file}")
                except Exception as save_err:
                    logger.warning(f"Failed to cache OFAC data locally: {save_err}")

                records = self.parse_sdn_csv(raw_csv_text)
                return {
                    "source": "OFAC_SDN_LIVE",
                    "url": url,
                    "retrieval_timestamp": retrieval_timestamp,
                    "records_count": len(records),
                    "data": records,
                    "is_cached": False,
                }

        except (httpx.RequestError, httpx.TimeoutException) as exc:
            logger.warning(f"Network error downloading OFAC SDN list: {exc}. Checking local cache...")
            if cache_file.exists():
                logger.info(f"Recovering OFAC records from local offline cache: {cache_file}")
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_text = f.read()
                records = self.parse_sdn_csv(cached_text)
                return {
                    "source": "OFAC_SDN_CACHED",
                    "url": url,
                    "retrieval_timestamp": retrieval_timestamp,
                    "records_count": len(records),
                    "data": records,
                    "is_cached": True,
                    "warning": "Data served from local offline cache due to network unavailability.",
                }
            raise OfacAPIError(
                f"OFAC server unavailable and no local offline cache found: {exc}"
            )

    def parse_sdn_csv(self, csv_content: str) -> List[Dict[str, Any]]:
        """
        Parses official OFAC SDN CSV format.
        Columns: Ent_num, SDN_Name, SDN_Type, Program, Title, Call_Sign, Vess_type, Tonnage, GRT, Vess_flag, Vess_owner, Remarks
        """
        if not csv_content.strip():
            return []

        # Check if first line has header names or is raw data
        reader = csv.reader(io.StringIO(csv_content))
        rows = list(reader)
        if not rows:
            return []

        records = []
        has_header = False
        first_row = [c.strip().lower() for c in rows[0]]
        if "ent_num" in first_row or "sdn_name" in first_row:
            has_header = True
            header_map = {col.strip(): idx for idx, col in enumerate(rows[0])}
            data_rows = rows[1:]
        else:
            # Official headerless format mapping standard column positions
            data_rows = rows
            header_map = {
                "Ent_num": 0,
                "SDN_Name": 1,
                "SDN_Type": 2,
                "Program": 3,
                "Title": 4,
                "Call_Sign": 5,
                "Vess_type": 6,
                "Tonnage": 7,
                "GRT": 8,
                "Vess_flag": 9,
                "Vess_owner": 10,
                "Remarks": 11,
            }

        for row in data_rows:
            if not row or len(row) < 2:
                continue
            
            record: Dict[str, Any] = {}
            for col_name, idx in header_map.items():
                if idx < len(row):
                    record[col_name] = row[idx].strip()
                else:
                    record[col_name] = None
                    
            records.append(record)

        return records

    def load_from_fixture(self, fixture_path: str) -> Dict[str, Any]:
        """Loads clearly labeled OFAC test fixture (CSV or JSON format)."""
        path = Path(fixture_path)
        if not path.exists():
            raise FileNotFoundError(f"Fixture file not found: {fixture_path}")

        logger.info(f"Loading OFAC fixture from {fixture_path}")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if path.suffix.lower() == ".json":
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    records = parsed.get("data", [])
                elif isinstance(parsed, list):
                    records = parsed
                else:
                    records = []
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSON in OFAC fixture '{fixture_path}': {exc}")
        else:
            records = self.parse_sdn_csv(content)

        return {
            "source": "OFAC_SDN_FIXTURE",
            "fixture_file": str(path.name),
            "retrieval_timestamp": datetime.now(timezone.utc),
            "records_count": len(records),
            "data": records,
            "is_cached": False,
        }
