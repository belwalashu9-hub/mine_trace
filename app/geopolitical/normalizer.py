"""Normalization engine for GDELT DOC 2.0 article responses."""
import hashlib
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from app.schemas.geopolitical import NormalizedGeopoliticalEvent


TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "ref", "source", "_hsenc", "_hsmi",
}


def canonicalize_url(url: Optional[str]) -> str:
    """
    Produces a clean, normalized canonical URL by:
    - Stripping leading/trailing whitespace
    - Lowercasing scheme and hostname
    - Removing tracking query parameters (utm_*, fbclid, etc.)
    - Stripping URL fragments and trailing slashes
    """
    if not url or not str(url).strip():
        return ""

    url_str = str(url).strip()
    try:
        parsed = urlparse(url_str)
        if not parsed.scheme or not parsed.netloc:
            return url_str

        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        path = parsed.path.rstrip("/") if parsed.path != "/" else "/"

        # Filter out tracking query parameters
        filtered_queries = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in TRACKING_PARAMS
        ]
        query = urlencode(filtered_queries)

        clean_parts = (scheme, netloc, path, parsed.params, query, "")
        return urlunparse(clean_parts)
    except Exception:
        return url_str


def generate_event_id(canonical_url: str, title: Optional[str] = None, seendate: Optional[str] = None) -> str:
    """
    Generates a deterministic, reproducible SHA-256 stable identifier for the article.
    Prioritizes canonical URL; falls back to title + seendate if URL is absent.
    """
    if canonical_url:
        key = f"url:{canonical_url}"
    else:
        key = f"title:{title or ''}|seen:{seendate or ''}"

    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"evt_{digest[:24]}"


def parse_gdelt_seendate(raw_date: Optional[str]) -> Optional[str]:
    """
    Parses GDELT's seendate format (YYYYMMDDTHHMMSSZ or YYYYMMDDHHMMSS)
    into standard ISO-8601 UTC representation (YYYY-MM-DDTHH:MM:SSZ).
    Returns None if date is absent or malformed.
    """
    if not raw_date or not str(raw_date).strip():
        return None

    s = str(raw_date).strip()

    # Format 1: 20261027T123000Z
    try:
        dt = datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        pass

    # Format 2: 20261027123000
    try:
        dt = datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        pass

    # Format 3: Standard ISO string (already formatted)
    if "T" in s and (s.endswith("Z") or "+" in s):
        try:
            # Validate ISO parsing
            datetime.fromisoformat(s.replace("Z", "+00:00"))
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass

    return None


def extract_source_domain(domain_field: Optional[str], canonical_url: str) -> Optional[str]:
    """Extracts publisher domain from GDELT field or parses hostname from canonical URL."""
    if domain_field and str(domain_field).strip():
        dom = str(domain_field).strip().lower()
        if dom.startswith("www."):
            dom = dom[4:]
        return dom

    if canonical_url:
        try:
            parsed = urlparse(canonical_url)
            host = (parsed.netloc or "").lower()
            if host.startswith("www."):
                host = host[4:]
            return host or None
        except Exception:
            return None

    return None


def normalize_gdelt_article(
    raw_article: Dict[str, Any],
    retrieved_at: Optional[datetime] = None,
) -> Optional[NormalizedGeopoliticalEvent]:
    """
    Transforms a raw GDELT DOC 2.0 article record into the standard MineTrace
    NormalizedGeopoliticalEvent schema.

    Strict rules applied:
    - Generates stable, deterministic event_id from canonical URL.
    - Preserves source_country; keeps affected_country null (no source vs affected confusion).
    - Preserves gdelt_seen_date; keeps event_date null (no indexing vs event confusion).
    - Keeps mineral and event_type as null (Phase 3 handles classification).
    - Status set to 'pending'.
    - Preserves raw metadata for evidence auditing.
    """
    if not isinstance(raw_article, dict):
        return None

    raw_url = raw_article.get("url") or raw_article.get("url_mobile") or ""
    canon_url = canonicalize_url(raw_url)

    if canon_url and (urlparse(canon_url).scheme not in ("http", "https") or not urlparse(canon_url).hostname):
        return None

    raw_title = raw_article.get("title")
    title = str(raw_title).strip() if raw_title is not None else None

    # An article must have at least a URL or a title to be meaningful
    if not canon_url and not title:
        return None

    raw_seendate = raw_article.get("seendate")
    parsed_seendate = parse_gdelt_seendate(raw_seendate)
    event_id = generate_event_id(canonical_url=canon_url, title=title, seendate=raw_seendate)

    domain = extract_source_domain(raw_article.get("domain"), canon_url)

    source_country = raw_article.get("sourcecountry")
    source_country_str = str(source_country).strip() if source_country and str(source_country).strip() != "-0-" else None

    retrieval_dt = retrieved_at or datetime.now(timezone.utc)
    retrieved_at_iso = retrieval_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Preserve extra metadata for future verification
    raw_metadata = {
        "language": raw_article.get("language"),
        "socialimage": raw_article.get("socialimage"),
        "url_mobile": raw_article.get("url_mobile"),
        "raw_seendate": raw_seendate,
    }
    # Exclude None values from metadata
    raw_metadata = {k: v for k, v in raw_metadata.items() if v is not None}

    return NormalizedGeopoliticalEvent(
        event_id=event_id,
        title=title,
        source_url=canon_url or raw_url,
        source_domain=domain,
        source_country=source_country_str,
        affected_country=None,      # Not inferred in Phase 1
        mineral=None,               # Kept null until Phase 3
        event_type=None,            # Kept null until Phase 3
        event_date=None,            # GDELT seen date != event date
        publication_date=None,      # Only if verifiable in later phases
        gdelt_seen_date=parsed_seendate,
        retrieved_at=retrieved_at_iso,
        classification_status="pending",
        provider="gdelt_doc_2",
        raw_metadata=raw_metadata,
    )
