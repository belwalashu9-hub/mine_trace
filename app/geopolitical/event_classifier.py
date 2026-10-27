"""
Multi-layer Geopolitical Event Classifier and Entity Extraction Engine.
Converts raw/normalized news articles into structured GeopoliticalEvent entities,
clusters related articles, and assigns evidence-backed verification statuses.
"""
import hashlib
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from app.schemas.events import EventTypeEnum, VerificationStatusEnum
from app.geopolitical.location_extractor import LocationExtractor
from app.geopolitical.mineral_detector import MineralDetector

EVENT_TYPE_PATTERNS = [
    (
        EventTypeEnum.MARITIME_SECURITY_INCIDENT,
        [
            r"houthi", r"missile", r"drone", r"ship struck", r"vessel struck", r"vessel targeted",
            r"struck by", r"hijack", r"piracy", r"gulf of aden", r"strait attack", r"maritime security",
            r"naval drone", r"fired upon", r"cargo vessel", r"vessel damaged",
        ],
    ),
    (
        EventTypeEnum.PORT_CLOSURE,
        [
            r"port closure", r"port closed", r"berth closure", r"harbor shutdown", r"terminal halt",
            r"dockers strike", r"vessel congestion", r"port blocked", r"harbour blocked",
        ],
    ),
    (
        EventTypeEnum.EXPORT_RESTRICTION,
        [
            r"export control", r"export ban", r"export restriction", r"export quota",
            r"export tariff", r"licensing requirement", r"mineral embargo", r"ban on export",
        ],
    ),
    (
        EventTypeEnum.SANCTIONS_ANNOUNCEMENT,
        [
            r"sanctions imposed", r"secondary sanctions", r"ofac", r"treasury sanctions",
            r"sanction list", r"asset freeze", r"sdn list", r"embargo",
        ],
    ),
    (
        EventTypeEnum.MINING_STRIKE,
        [
            r"mining strike", r"miners strike", r"miner walkout", r"union strike",
            r"union walkout", r"walkout", r"labor walkout", r"workers strike",
            r"mine strike", r"wage dispute halt",
        ],
    ),
    (
        EventTypeEnum.MINE_SHUTDOWN,
        [
            r"mine shutdown", r"mine closed", r"smelter halt", r"smelting halt", r"operations suspended",
            r"tailings dam collapse", r"extraction halted", r"processing plant closed",
        ],
    ),
    (
        EventTypeEnum.WAR,
        [
            r"\bwar\b", r"invasion", r"declaration of war", r"military campaign", r"cross-border attack",
        ],
    ),
    (
        EventTypeEnum.ARMED_CONFLICT,
        [
            r"armed conflict", r"clashes", r"rebel offensive", r"militia attack", r"insurgency",
            r"artillery strike", r"airstrike", r"hostilities", r"gunfire",
        ],
    ),
    (
        EventTypeEnum.NATURAL_DISASTER,
        [
            r"flooding", r"flood", r"earthquake", r"cyclone", r"typhoon", r"hurricane",
            r"landslide", r"drought", r"severe weather", r"tsunami",
        ],
    ),
    (
        EventTypeEnum.TRANSPORT_DISRUPTION,
        [
            r"rail derailment", r"bridge collapsed", r"corridor blocked", r"highway blocked",
            r"transport disruption", r"railway halt", r"trucking stoppage",
        ],
    ),
    (
        EventTypeEnum.POLITICAL_INSTABILITY,
        [
            r"coup", r"state of emergency", r"regime change", r"martial law", r"civil unrest",
            r"nationwide protest", r"government crisis",
        ],
    ),
]


class EventClassifier:
    """
    Classifies articles into structured geopolitical events,
    resolves locations, detects minerals, and assesses verification levels.
    """

    @classmethod
    def classify_article(cls, article_dict: Dict[str, Any]) -> Dict[str, Any]:
        title = article_dict.get("title") or ""
        url = article_dict.get("source_url") or article_dict.get("url") or ""
        source_country = article_dict.get("source_country")
        domain = article_dict.get("source_domain") or ""
        seen_date = article_dict.get("gdelt_seen_date")
        text = title.lower()

        # 1. Classify Event Type
        event_type = EventTypeEnum.UNKNOWN
        for candidate_type, patterns in EVENT_TYPE_PATTERNS:
            if any(re.search(pat, text) for pat in patterns):
                event_type = candidate_type
                break

        # Fallback to OTHER if headline contains meaningful disruption words but no exact match
        if event_type == EventTypeEnum.UNKNOWN:
            if any(w in text for w in ["disruption", "delay", "halt", "crisis", "dispute", "investigation"]):
                event_type = EventTypeEnum.OTHER

        # 2. Extract Location
        location_meta = LocationExtractor.extract_location(
            title=title,
            source_country=source_country,
        )

        # 3. Detect Mineral Relevance
        mineral_meta = MineralDetector.detect_relevance(
            title=title,
            location_meta=location_meta,
        )

        # 4. Assess Verification Status
        # Default single news source is REPORTED.
        # Check if officially confirmed by government or gazette
        verification_status = VerificationStatusEnum.REPORTED
        if any(term in text for term in ["official statement", "ministry confirmed", "gazette", "decree", "signed into law"]):
            verification_status = VerificationStatusEnum.REPORTED
        elif any(term in text for term in ["unconfirmed", "rumor", "alleged", "claimed without evidence"]):
            verification_status = VerificationStatusEnum.UNVERIFIED
        elif any(term in text for term in ["denied", "disputed", "contradicts"]):
            verification_status = VerificationStatusEnum.DISPUTED

        # 5. Generate Clusterable Deterministic Event ID
        # Group by: event_type + affected_country + location_name (if any) + time_bucket
        cluster_date_bucket = (
            seen_date.strftime("%Y-%m-%d")
            if isinstance(seen_date, datetime)
            else (str(seen_date)[:10] if seen_date else "nodate")
        )
        headline_key = " ".join(re.findall(r"[a-z0-9]+", title.lower()))
        cluster_key = f"{event_type.value}:{location_meta['affected_country']}:{location_meta['location_name'] or 'nohub'}:{cluster_date_bucket}:{headline_key}"
        event_hash = hashlib.sha256(cluster_key.encode("utf-8")).hexdigest()[:16]
        event_id = f"geo_{event_hash}"

        return {
            "event_id": event_id,
            "event_type": event_type.value,
            "title": title or "Geopolitical Alert",
            "summary": f"Reported {event_type.value.lower().replace('_', ' ')} affecting {location_meta['affected_country'] or 'international supply chains'}.",
            "affected_country": location_meta["affected_country"],
            "region": location_meta["region"],
            "location_name": location_meta["location_name"],
            "latitude": location_meta["latitude"],
            "longitude": location_meta["longitude"],
            "has_coordinates": location_meta["has_coordinates"],
            "event_date": None,  # Strictly distinct from publication date
            "publication_date": None,
            "mineral_relevance": mineral_meta["mineral"],
            "relevance_type": mineral_meta["relevance_type"],
            "affected_infrastructure": location_meta["affected_infrastructure"],
            "extraction_confidence": round((location_meta["extraction_confidence"] + mineral_meta["confidence"]) / 2, 2),
            "verification_status": verification_status.value,
            "cluster_key": cluster_key,
        }
