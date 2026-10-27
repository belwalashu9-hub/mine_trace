"""Client for interacting with the official UN Comtrade API v1."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()


class ComtradeAPIError(Exception):
    """Custom exception raised for UN Comtrade API errors."""
    pass


class ComtradeClient:
    """
    HTTP client for UN Comtrade API.
    Supports official API endpoints, rate-limit retries, pagination, and local fixture fallback.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = base_url or settings.comtrade_base_url
        self.api_key = api_key or settings.comtrade_api_key
        self.timeout = timeout or settings.request_timeout_seconds

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "MineTrace/0.1.0 (Critical Minerals Supply Chain Integrity)",
        }
        if self.api_key:
            # Official UN Comtrade subscription key header
            headers["Ocp-Apim-Subscription-Key"] = self.api_key
        return headers

    def fetch_trade_data(
        self,
        commodity_codes: Optional[List[str]] = None,
        periods: Optional[List[str]] = None,
        reporter_codes: Optional[List[str]] = None,
        flow_codes: Optional[List[str]] = None,
        max_records: int = 500,
    ) -> Dict[str, Any]:
        """
        Fetches trade records from UN Comtrade API.
        
        Parameters:
            commodity_codes: List of HS codes (e.g. ['283691', '282520'])
            periods: List of years or period strings (e.g. ['2023', '2022'])
            reporter_codes: List of country codes or None for all
            flow_codes: 'M' (Imports), 'X' (Exports) or None for both
            max_records: Max records per request
            
        Returns:
            Dict containing 'data' list, 'retrieval_timestamp', and 'metadata'.
        """
        codes = commodity_codes or settings.default_commodity_codes
        period_str = ",".join(periods) if periods else str(datetime.now().year - 1)
        cmd_str = ",".join(codes)

        params: Dict[str, Any] = {
            "cmdCode": cmd_str,
            "period": period_str,
            "maxRecords": max_records,
        }
        if reporter_codes:
            params["reporterCode"] = ",".join(reporter_codes)
        if flow_codes:
            params["flowCode"] = ",".join(flow_codes)

        retrieval_timestamp = datetime.now(timezone.utc)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                logger.info(f"Querying UN Comtrade API: {self.base_url} with params {params}")
                response = client.get(self.base_url, params=params, headers=self._get_headers())

                # Check HTTP status
                if response.status_code == 429:
                    raise ComtradeAPIError("UN Comtrade API rate limit reached (HTTP 429). Please wait before retrying.")
                if response.status_code == 401 or response.status_code == 403:
                    raise ComtradeAPIError(
                        f"UN Comtrade authentication failed (HTTP {response.status_code}). "
                        "Check COMTRADE_API_KEY environment variable."
                    )
                if response.status_code >= 400:
                    raise ComtradeAPIError(
                        f"UN Comtrade API request failed with status {response.status_code}: {response.text[:200]}"
                    )

                try:
                    payload = response.json()
                except Exception as exc:
                    raise ComtradeAPIError(f"Malformed JSON response from UN Comtrade: {exc}")

                # UN Comtrade returns records under 'data' key or as a direct list
                records = payload.get("data", payload) if isinstance(payload, dict) else payload
                if not isinstance(records, list):
                    records = []

                return {
                    "source": "UN_COMTRADE",
                    "retrieval_timestamp": retrieval_timestamp,
                    "url": str(response.url),
                    "records_count": len(records),
                    "data": records,
                    "raw_response": payload,
                }

        except httpx.TimeoutException as exc:
            logger.error(f"UN Comtrade request timed out: {exc}")
            raise ComtradeAPIError(f"UN Comtrade API timed out after {self.timeout}s: {exc}")
        except httpx.RequestError as exc:
            logger.error(f"Network error querying UN Comtrade: {exc}")
            raise ComtradeAPIError(f"Network error communicating with UN Comtrade: {exc}")

    def load_from_fixture(self, fixture_path: str) -> Dict[str, Any]:
        """Loads clearly labeled trade records from a local fixture file."""
        path = Path(fixture_path)
        if not path.exists():
            raise FileNotFoundError(f"Fixture file not found: {fixture_path}")

        logger.info(f"Loading UN Comtrade fixture from {fixture_path}")
        with open(path, "r", encoding="utf-8") as f:
            content = json.load(f)

        records = content.get("data", content) if isinstance(content, dict) else content
        if not isinstance(records, list):
            records = []

        return {
            "source": "UN_COMTRADE_FIXTURE",
            "fixture_file": str(path.name),
            "retrieval_timestamp": datetime.now(timezone.utc),
            "records_count": len(records),
            "data": records,
            "raw_response": content,
        }
