"""Reusable HTTP client for the public GDELT DOC 2.0 API."""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()


# -------------------------------------------------------------
# Custom Exceptions
# -------------------------------------------------------------
class GdeltError(Exception):
    """Base exception for all GDELT client errors."""
    pass


class GdeltAPIError(GdeltError):
    """Raised when GDELT API returns an unhandled HTTP error status."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_text: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class GdeltRateLimitError(GdeltAPIError):
    """Raised when GDELT API rate limit is exceeded (HTTP 429)."""
    pass


class GdeltTimeoutError(GdeltError):
    """Raised when request to GDELT API times out."""
    pass


class GdeltConnectionError(GdeltError):
    """Raised on network failure or DNS resolution issue connecting to GDELT."""
    pass


class GdeltParseError(GdeltError):
    """Raised when GDELT response cannot be parsed as valid JSON."""
    pass


# -------------------------------------------------------------
# Rate Limiter for Polite Request Pacing
# -------------------------------------------------------------
class PoliteRateLimiter:
    """
    Enforces a mandatory minimum interval between consecutive outbound requests
    to comply with GDELT's documented rate limit policy (strictly <= 1 req per 5s).
    """

    def __init__(self, min_interval_seconds: float = 6.0):
        self.min_interval = min_interval_seconds
        self._last_request_time = 0.0
        self._lock = threading.Lock()

    def wait(self) -> float:
        """Blocks until the mandatory interval has elapsed since the last request."""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            sleep_needed = self.min_interval - elapsed
            if sleep_needed > 0:
                logger.debug(f"Polite pacing: waiting {sleep_needed:.2f}s before GDELT query...")
                time.sleep(sleep_needed)
            self._last_request_time = time.time()
            return max(0.0, sleep_needed)


# Global rate limiter shared across client instances to protect the IP
_GLOBAL_RATE_LIMITER = PoliteRateLimiter(min_interval_seconds=6.0)


# -------------------------------------------------------------
# GDELT Client
# -------------------------------------------------------------
class GdeltClient:
    """
    Client for interacting with the public GDELT DOC 2.0 API.
    Provides robust retry with exponential backoff, request pacing, and offline fixture support.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        rate_limiter: Optional[PoliteRateLimiter] = None,
    ):
        self.base_url = base_url or settings.gdelt_base_url
        self.timeout = timeout if timeout is not None else settings.gdelt_timeout
        self.max_retries = max_retries if max_retries is not None else settings.gdelt_max_retries
        self.rate_limiter = rate_limiter or _GLOBAL_RATE_LIMITER

    def _get_headers(self) -> Dict[str, str]:
        """Provides standard HTTP headers for polite API communication."""
        return {
            "Accept": "application/json",
            "User-Agent": "MineTrace/0.1.0 (Critical Minerals Supply Chain Integrity Research)",
        }

    def fetch_articles(
        self,
        query: str,
        timespan: str = "24h",
        max_records: int = 75,
        sort: str = "DateDesc",
        enforce_pacing: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes a query against GDELT DOC 2.0 API Article List mode.

        Parameters:
            query: GDELT query string (supports boolean operators and quotes)
            timespan: Lookback window (e.g. '24h', '2d', '7d')
            max_records: Max articles to return (1 to 250)
            sort: Sorting criteria ('DateDesc', 'HybridRel', etc.)
            enforce_pacing: Whether to enforce the 5.5s inter-request delay

        Returns:
            Dict containing 'articles' list and execution metadata.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty.")

        clamped_max_records = max(1, min(250, max_records))

        params = {
            "query": query.strip(),
            "mode": "ArtList",
            "format": "json",
            "timespan": timespan,
            "maxrecords": clamped_max_records,
            "sort": sort,
        }

        retrieval_timestamp = datetime.now(timezone.utc)
        attempt = 0
        last_exception = None

        while attempt <= self.max_retries:
            attempt += 1

            if enforce_pacing:
                self.rate_limiter.wait()

            try:
                logger.info(
                    f"Querying GDELT DOC 2.0 (attempt {attempt}/{self.max_retries + 1}): "
                    f"query='{query[:60]}...' timespan={timespan} maxrecords={clamped_max_records}"
                )

                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    response = client.get(
                        self.base_url,
                        params=params,
                        headers=self._get_headers(),
                    )

                status_code = response.status_code

                # Handle HTTP 429 Rate Limiting
                if status_code == 429 or "Please limit requests" in response.text:
                    err_msg = (
                        "GDELT DOC 2.0 rate limit reached (HTTP 429). "
                        "The public API requires >= 5s between consecutive queries."
                    )
                    logger.warning(f"{err_msg} (attempt {attempt})")
                    if attempt <= self.max_retries:
                        # Exponential backoff for rate limiting: 10s, 20s, 40s
                        backoff = 10.0 * (2 ** (attempt - 1))
                        logger.info(f"Backing off for {backoff:.1f}s before retry...")
                        time.sleep(backoff)
                        continue
                    raise GdeltRateLimitError(err_msg, status_code=429, response_text=response.text[:250])

                # Handle Server Errors (HTTP 5xx) with retry
                if 500 <= status_code < 600:
                    err_msg = f"GDELT server error (HTTP {status_code}): {response.text[:150]}"
                    logger.warning(f"{err_msg} (attempt {attempt})")
                    if attempt <= self.max_retries:
                        backoff = 2.0 * (2 ** (attempt - 1))
                        time.sleep(backoff)
                        continue
                    raise GdeltAPIError(err_msg, status_code=status_code, response_text=response.text[:250])

                # Handle Client Errors (HTTP 4xx other than 429)
                if 400 <= status_code < 500:
                    err_msg = f"GDELT client error (HTTP {status_code}): {response.text[:150]}"
                    raise GdeltAPIError(err_msg, status_code=status_code, response_text=response.text[:250])

                # Successful HTTP 200: Parse response content
                content_text = response.text.strip()

                # Handle completely empty response body
                if not content_text:
                    logger.info("GDELT returned empty response body (0 articles).")
                    return {
                        "articles": [],
                        "retrieval_timestamp": retrieval_timestamp,
                        "query": query,
                        "timespan": timespan,
                        "status_code": status_code,
                    }

                try:
                    payload = response.json()
                except Exception as json_err:
                    # GDELT occasionally returns plain text messages on empty search results
                    if "no matches" in content_text.lower() or "no records" in content_text.lower():
                        logger.info(f"GDELT reported no matches: '{content_text[:100]}'")
                        return {
                            "articles": [],
                            "retrieval_timestamp": retrieval_timestamp,
                            "query": query,
                            "timespan": timespan,
                            "status_code": status_code,
                        }
                    raise GdeltParseError(
                        f"Failed to parse GDELT JSON response: {json_err}. Raw start: '{content_text[:120]}'"
                    )

                if not isinstance(payload, dict):
                    return {
                        "articles": [],
                        "retrieval_timestamp": retrieval_timestamp,
                        "query": query,
                        "timespan": timespan,
                        "status_code": status_code,
                    }

                # Extract articles array from payload
                articles = payload.get("articles")
                if not isinstance(articles, list):
                    articles = []

                logger.info(f"GDELT query succeeded: retrieved {len(articles)} articles.")
                return {
                    "articles": articles,
                    "retrieval_timestamp": retrieval_timestamp,
                    "query": query,
                    "timespan": timespan,
                    "status_code": status_code,
                    "raw_response": payload,
                }

            except httpx.TimeoutException as exc:
                last_exception = exc
                logger.warning(f"GDELT request timed out after {self.timeout}s (attempt {attempt}): {exc}")
                if attempt <= self.max_retries:
                    backoff = 2.0 * (2 ** (attempt - 1))
                    time.sleep(backoff)
                    continue
                raise GdeltTimeoutError(
                    f"GDELT request timed out after {self.max_retries + 1} attempts ({self.timeout}s timeout): {exc}"
                )

            except httpx.ConnectError as exc:
                last_exception = exc
                logger.warning(f"GDELT connection failed (attempt {attempt}): {exc}")
                if attempt <= self.max_retries:
                    backoff = 2.0 * (2 ** (attempt - 1))
                    time.sleep(backoff)
                    continue
                raise GdeltConnectionError(f"Failed to connect to GDELT API: {exc}")

            except (GdeltRateLimitError, GdeltAPIError, GdeltParseError):
                raise

            except Exception as exc:
                last_exception = exc
                logger.error(f"Unexpected error querying GDELT API: {exc}")
                if attempt <= self.max_retries:
                    time.sleep(2.0)
                    continue
                raise GdeltAPIError(f"Unexpected error querying GDELT API: {exc}")

        if last_exception:
            raise GdeltAPIError(f"GDELT query failed after {self.max_retries + 1} attempts: {last_exception}")

        return {"articles": [], "retrieval_timestamp": retrieval_timestamp}

    def load_from_fixture(self, fixture_path: str) -> Dict[str, Any]:
        """
        Loads GDELT article data from a local JSON fixture file.
        Enables 100% offline testing with clearly labeled synthetic test data.
        """
        path = Path(fixture_path)
        if not path.is_file():
            raise FileNotFoundError(f"GDELT fixture file not found: {fixture_path}")

        logger.info(f"Loading GDELT test fixture from {fixture_path}")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        try:
            data = json.loads(content)
        except Exception as exc:
            raise GdeltParseError(f"Malformed JSON in GDELT fixture '{fixture_path}': {exc}")

        if isinstance(data, dict):
            articles = data.get("articles", data.get("data", []))
        elif isinstance(data, list):
            articles = data
        else:
            articles = []

        return {
            "source": "GDELT_TEST_FIXTURE",
            "fixture_file": str(path.name),
            "retrieval_timestamp": datetime.now(timezone.utc),
            "articles": articles,
            "status_code": 200,
            "raw_response": data,
        }
