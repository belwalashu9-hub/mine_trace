"""
Mineral relevance detection engine for critical mineral supply chain monitoring.
Distinguishes DIRECT commodity relevance from INDIRECT infrastructure relevance.
"""
import re
from typing import Dict, Any, Optional

DIRECT_MINERAL_KEYWORDS = {
    "cobalt": [
        "cobalt", "cobalt hydroxide", "cobalt carbonate", "cobalt ore", "cobalt concentrate", "cathodes"
    ],
    "lithium": [
        "lithium", "spodumene", "lithium carbonate", "lithium hydroxide", "brine", "salars", "battery grade lithium"
    ],
    "nickel": [
        "nickel", "ferronickel", "nickel pig iron", "npi", "nickel matte", "mhp", "nickel sulfate"
    ],
    "natural_graphite": [
        "graphite", "flake graphite", "natural graphite", "spherical graphite", "anode material", "graphite concentrate"
    ],
}

INDIRECT_INFRASTRUCTURE_ASSOCIATIONS = {
    "kolwezi": "cobalt",
    "katanga": "cobalt",
    "salar de atacama": "lithium",
    "antofagasta": "lithium",
    "morowali": "nickel",
    "weda bay": "nickel",
    "balama": "natural_graphite",
    "nacala": "natural_graphite",
    "durban": "cobalt",
}


class MineralDetector:
    """
    Detects mineral relevance and categorizes into DIRECT, INDIRECT, UNKNOWN, or NONE.
    """

    @classmethod
    def detect_relevance(
        cls,
        title: Optional[str] = None,
        content: Optional[str] = None,
        location_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        text = f"{title or ''} {content or ''}".lower()

        # 1. Check for DIRECT mineral keywords
        matched_minerals = []
        for mineral, keywords in DIRECT_MINERAL_KEYWORDS.items():
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", text):
                    matched_minerals.append(mineral)
                    break

        if len(matched_minerals) == 1:
            return {
                "mineral": matched_minerals[0],
                "relevance_type": "DIRECT",
                "confidence": 0.95,
            }
        elif len(matched_minerals) > 1:
            return {
                "mineral": "all_critical_minerals",
                "relevance_type": "DIRECT",
                "confidence": 0.90,
            }

        # 2. Check for INDIRECT mineral associations via recognized specialized infrastructure
        if location_meta:
            infra = (location_meta.get("affected_infrastructure") or location_meta.get("location_name") or "").lower()
            for place, mineral in INDIRECT_INFRASTRUCTURE_ASSOCIATIONS.items():
                if place in infra or place in text:
                    return {
                        "mineral": mineral,
                        "relevance_type": "INDIRECT",
                        "confidence": 0.70,
                    }

        # 3. Check for general critical mineral keywords
        if any(term in text for term in ["critical mineral", "battery metal", "raw material", "mining supply"]):
            return {
                "mineral": "all_critical_minerals",
                "relevance_type": "INDIRECT",
                "confidence": 0.60,
            }

        # 4. Unknown or None
        return {
            "mineral": "unknown",
            "relevance_type": "NONE",
            "confidence": 0.30,
        }
