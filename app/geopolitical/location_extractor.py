"""
Location extraction and geospatial entity normalization engine.
Distinguishes source publisher country from actual incident location.
Never assigns country centroid coordinates as incident coordinates.
"""
import re
from typing import Optional, Dict, Any, Tuple, List

# Known mineral mining hubs, major trade ports, and critical maritime chokepoints
KNOWN_INFRASTRUCTURE_COORDINATES: Dict[str, Dict[str, Any]] = {
    # DRC / Central Africa Cobalt Hubs
    "kolwezi": {"country": "Democratic Republic of the Congo", "lat": -10.7167, "lon": 25.4667, "infra": "Kolwezi Mining District"},
    "katanga": {"country": "Democratic Republic of the Congo", "lat": -11.6667, "lon": 27.4833, "infra": "Katanga Copper-Cobalt Belt"},
    "lubumbashi": {"country": "Democratic Republic of the Congo", "lat": -11.6609, "lon": 27.4794, "infra": "Lubumbashi Logistics Corridor"},
    "port of durban": {"country": "South Africa", "lat": -29.8587, "lon": 31.0218, "infra": "Port of Durban Terminal"},
    "durban": {"country": "South Africa", "lat": -29.8587, "lon": 31.0218, "infra": "Port of Durban"},
    "walvis bay": {"country": "Namibia", "lat": -22.9575, "lon": 14.5053, "infra": "Port of Walvis Bay"},
    "dar es salaam": {"country": "Tanzania", "lat": -6.7924, "lon": 39.2083, "infra": "Port of Dar es Salaam"},

    # Chile Lithium Corridors
    "salar de atacama": {"country": "Chile", "lat": -23.5000, "lon": -68.2500, "infra": "Salar de Atacama Brine Field"},
    "atacama": {"country": "Chile", "lat": -23.5000, "lon": -68.2500, "infra": "Atacama Mining Region"},
    "antofagasta": {"country": "Chile", "lat": -23.6500, "lon": -70.4000, "infra": "Port of Antofagasta"},
    "port of antofagasta": {"country": "Chile", "lat": -23.6500, "lon": -70.4000, "infra": "Port of Antofagasta Terminal"},
    "mejillones": {"country": "Chile", "lat": -23.1000, "lon": -70.4500, "infra": "Port of Mejillones"},

    # Indonesia Nickel Hubs
    "morowali": {"country": "Indonesia", "lat": -2.8250, "lon": 122.1550, "infra": "Indonesia Morowali Industrial Park (IMIP)"},
    "bahodopi": {"country": "Indonesia", "lat": -2.8000, "lon": 122.1400, "infra": "Port of Bahodopi Terminal"},
    "halmahera": {"country": "Indonesia", "lat": 0.6000, "lon": 127.9000, "infra": "Weda Bay Nickel Complex"},
    "weda bay": {"country": "Indonesia", "lat": 0.4800, "lon": 127.8500, "infra": "Weda Bay Industrial Park"},
    "jakarta": {"country": "Indonesia", "lat": -6.2088, "lon": 106.8456, "infra": "Port of Tanjung Priok"},

    # Mozambique Graphite Corridors
    "balama": {"country": "Mozambique", "lat": -13.3458, "lon": 38.5647, "infra": "Balama Graphite Mine"},
    "cabo delgado": {"country": "Mozambique", "lat": -12.5000, "lon": 39.5000, "infra": "Cabo Delgado Mineral Corridor"},
    "nacala": {"country": "Mozambique", "lat": -14.5428, "lon": 40.6728, "infra": "Deepwater Port of Nacala"},
    "port of nacala": {"country": "Mozambique", "lat": -14.5428, "lon": 40.6728, "infra": "Port of Nacala Terminal"},
    "pemba": {"country": "Mozambique", "lat": -12.9732, "lon": 40.5178, "infra": "Pemba Port Facility"},

    # Critical Maritime Mineral Chokepoints
    "red sea": {"country": "International Waters", "lat": 18.0000, "lon": 39.5000, "infra": "Red Sea Shipping Channel"},
    "bab el-mandeb": {"country": "Yemen", "lat": 12.5833, "lon": 43.3333, "infra": "Bab el-Mandeb Strait"},
    "bab-el-mandeb": {"country": "Yemen", "lat": 12.5833, "lon": 43.3333, "infra": "Bab el-Mandeb Strait"},
    "suez canal": {"country": "Egypt", "lat": 30.5852, "lon": 32.2654, "infra": "Suez Canal Transit Way"},
    "suez": {"country": "Egypt", "lat": 29.9668, "lon": 32.5498, "infra": "Port of Suez"},
    "strait of hormuz": {"country": "Oman", "lat": 26.5667, "lon": 56.2500, "infra": "Strait of Hormuz"},
    "strait of malacca": {"country": "Malaysia", "lat": 2.5000, "lon": 101.5000, "infra": "Strait of Malacca"},
    "shanghai": {"country": "China", "lat": 31.2304, "lon": 121.4737, "infra": "Port of Shanghai"},
    "ningbo": {"country": "China", "lat": 29.8683, "lon": 121.5440, "infra": "Port of Ningbo-Zhoushan"},
    "rotterdam": {"country": "Netherlands", "lat": 51.9244, "lon": 4.4777, "infra": "Port of Rotterdam"},
}

COUNTRY_SYNONYMS: Dict[str, str] = {
    "drc": "Democratic Republic of the Congo",
    "dr congo": "Democratic Republic of the Congo",
    "congo-kinshasa": "Democratic Republic of the Congo",
    "congo": "Democratic Republic of the Congo",
    "chile": "Chile",
    "chilean": "Chile",
    "indonesia": "Indonesia",
    "indonesian": "Indonesia",
    "mozambique": "Mozambique",
    "south africa": "South Africa",
    "south african": "South Africa",
    "china": "China",
    "chinese": "China",
    "russia": "Russia",
    "russian": "Russia",
    "ukraine": "Ukraine",
    "ukrainian": "Ukraine",
    "yemen": "Yemen",
    "yemeni": "Yemen",
    "egypt": "Egypt",
    "egyptian": "Egypt",
    "namibia": "Namibia",
    "australia": "Australia",
    "australian": "Australia",
    "zambia": "Zambia",
    "zambian": "Zambia",
    "brazil": "Brazil",
    "brazilian": "Brazil",
    "united states": "United States",
    "us": "United States",
    "usa": "United States",
}


class LocationExtractor:
    """
    Extracts affected country and specific infrastructure location coordinates.
    Never assigns country centroid coordinates as incident coordinates.
    """

    @classmethod
    def extract_location(
        cls,
        title: Optional[str] = None,
        content: Optional[str] = None,
        source_country: Optional[str] = None,
    ) -> Dict[str, Any]:
        text = f"{title or ''} {content or ''}".lower()

        # 1. Search for specific verified infrastructure or maritime chokepoints
        for place_name, meta in KNOWN_INFRASTRUCTURE_COORDINATES.items():
            pattern = r"\b" + re.escape(place_name) + r"\b"
            if re.search(pattern, text):
                return {
                    "affected_country": meta["country"],
                    "region": meta["infra"],
                    "location_name": place_name.title(),
                    "latitude": meta["lat"],
                    "longitude": meta["lon"],
                    "has_coordinates": True,
                    "affected_infrastructure": meta["infra"],
                    "extraction_confidence": 0.85,
                }

        # 2. Search for explicit country mentions in the headline/content
        detected_country = None
        countries = set()
        for synonym, canonical in COUNTRY_SYNONYMS.items():
            pattern = r"\b" + re.escape(synonym) + r"\b"
            if re.search(pattern, text):
                countries.add(canonical)

        detected_country = next(iter(countries)) if len(countries) == 1 else None

        if detected_country:
            # We have an affected country, but NO specific verified incident coordinates!
            # Do NOT treat country centroid as exact incident coordinate!
            return {
                "affected_country": detected_country,
                "region": None,
                "location_name": detected_country,
                "latitude": None,
                "longitude": None,
                "has_coordinates": False,
                "affected_infrastructure": None,
                "extraction_confidence": 0.60,
            }

        # 4. Unknown location
        return {
            "affected_country": None,
            "region": None,
            "location_name": None,
            "latitude": None,
            "longitude": None,
            "has_coordinates": False,
            "affected_infrastructure": None,
            "extraction_confidence": 0.20,
        }
