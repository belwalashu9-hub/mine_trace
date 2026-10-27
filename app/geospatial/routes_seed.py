"""
Seed data definitions and seeding utility for Model 2 candidate physical transport routes.
All records are explicitly labeled DEMO_CANDIDATE.
"""
import json
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from app.database.models import TransportRoute, utc_now

DEMO_ROUTES: List[Dict[str, Any]] = [
    {
        "route_id": "route_cod_durban_cobalt",
        "name": "DRC-Durban Cobalt Export Corridor",
        "origin": "Kolwezi, Democratic Republic of the Congo",
        "destination": "Port of Durban, South Africa",
        "mineral_relevance": "cobalt",
        "transport_mode": "MULTIMODAL",
        "primary_hubs": ["Kolwezi", "Lubumbashi", "Kasumbalesa Border", "Ndola", "Lusaka", "Port of Durban"],
        "ordered_segments": [
            "Kolwezi extraction loading terminal (DRC)",
            "Lubumbashi road corridor to Kasumbalesa border crossing",
            "Zambia north-south highway (Ndola to Lusaka)",
            "Chirundu/Beitbridge transit corridor to South Africa",
            "Gauteng intermodal logistics hub to Port of Durban berths",
        ],
        "geojson_geometry": {
            "type": "LineString",
            "coordinates": [
                [25.4667, -10.7167],  # Kolwezi
                [27.4794, -11.6609],  # Lubumbashi
                [27.8000, -12.2500],  # Kasumbalesa
                [28.6333, -12.9667],  # Ndola
                [28.2833, -15.4167],  # Lusaka
                [29.9833, -22.2167],  # Beitbridge
                [28.0500, -26.2000],  # Johannesburg
                [31.0218, -29.8587],  # Port of Durban
            ],
        },
        "route_source": "MineTrace Southern Africa Minerals Logistics Model",
        "data_confidence": "DEMO_CANDIDATE",
        "designation": "CANDIDATE ROUTE — NOT CONFIRMED COMMERCIAL SCHEDULE",
    },
    {
        "route_id": "route_chl_antofagasta_lithium",
        "name": "Atacama-Antofagasta Lithium Export Route",
        "origin": "Salar de Atacama, Chile",
        "destination": "Port of Antofagasta, Chile",
        "mineral_relevance": "lithium",
        "transport_mode": "ROAD",
        "primary_hubs": ["Salar de Atacama", "San Pedro de Atacama", "Baquedano Intermodal", "Port of Antofagasta"],
        "ordered_segments": [
            "Salar de Atacama extraction brine ponds",
            "Route 23 highway to Calama / Baquedano junction",
            "Route 5 Pan-American Highway to coastal junction",
            "Port of Antofagasta specialized mineral export docks",
        ],
        "geojson_geometry": {
            "type": "LineString",
            "coordinates": [
                [-68.2500, -23.5000],  # Salar de Atacama
                [-68.2000, -22.9167],  # San Pedro de Atacama
                [-69.8333, -23.3333],  # Baquedano
                [-70.4000, -23.6500],  # Port of Antofagasta
            ],
        },
        "route_source": "MineTrace Andean Lithium Supply Chain Atlas",
        "data_confidence": "DEMO_CANDIDATE",
        "designation": "CANDIDATE ROUTE — NOT CONFIRMED COMMERCIAL SCHEDULE",
    },
    {
        "route_id": "route_idn_morowali_nickel",
        "name": "Indonesia Morowali Nickel Shipping Lane",
        "origin": "Morowali Industrial Park, Indonesia",
        "destination": "Port of Bahodopi to Ningbo Maritime Corridor",
        "mineral_relevance": "nickel",
        "transport_mode": "MARITIME",
        "primary_hubs": ["IMIP Smelting Complex", "Port of Bahodopi", "Makassar Strait", "Ningbo Terminal"],
        "ordered_segments": [
            "IMIP processing terminal conveyor to Bahodopi bulk dock",
            "Tolo Gulf coastal passage to Salabangka Strait",
            "Makassar Strait northbound deepwater shipping corridor",
            "Celebes Sea to East China Sea transit to Ningbo-Zhoushan",
        ],
        "geojson_geometry": {
            "type": "LineString",
            "coordinates": [
                [122.1550, -2.8250],   # Morowali (IMIP)
                [122.1400, -2.8000],   # Port of Bahodopi
                [123.5000, -1.5000],   # Tolo Gulf exit
                [120.0000, 1.0000],    # Makassar Strait north
                [123.0000, 10.0000],   # Philippine Sea lane
                [121.5440, 29.8683],   # Port of Ningbo
            ],
        },
        "route_source": "MineTrace Southeast Asia Maritime Nickel Intelligence",
        "data_confidence": "DEMO_CANDIDATE",
        "designation": "CANDIDATE ROUTE — NOT CONFIRMED COMMERCIAL SCHEDULE",
    },
    {
        "route_id": "route_moz_nacala_graphite",
        "name": "Balama-Nacala Graphite Export Corridor",
        "origin": "Balama Graphite Mine, Mozambique",
        "destination": "Deepwater Port of Nacala, Mozambique",
        "mineral_relevance": "natural_graphite",
        "transport_mode": "ROAD",
        "primary_hubs": ["Balama Mine", "Montepuez Hub", "Nampula Logistics Center", "Port of Nacala"],
        "ordered_segments": [
            "Balama mine loading facility",
            "R242 highway corridor across Cabo Delgado to Montepuez",
            "N1 trunk route to Nampula regional staging depot",
            "Nampula-Nacala heavy freight highway to Port of Nacala berths",
        ],
        "geojson_geometry": {
            "type": "LineString",
            "coordinates": [
                [38.5647, -13.3458],  # Balama
                [39.0000, -13.1250],  # Montepuez
                [39.2667, -15.1167],  # Nampula
                [40.6728, -14.5428],  # Port of Nacala
            ],
        },
        "route_source": "MineTrace East Africa Mineral Transport Survey",
        "data_confidence": "DEMO_CANDIDATE",
        "designation": "CANDIDATE ROUTE — NOT CONFIRMED COMMERCIAL SCHEDULE",
    },
    {
        "route_id": "route_red_sea_suez_minerals",
        "name": "Red Sea-Suez International Mineral Maritime Lane",
        "origin": "Gulf of Aden / Bab el-Mandeb",
        "destination": "Suez Canal / Mediterranean Refineries",
        "mineral_relevance": "all_critical_minerals",
        "transport_mode": "MARITIME",
        "primary_hubs": ["Bab el-Mandeb Strait", "Southern Red Sea Shipping Channel", "Port of Suez", "Suez Canal"],
        "ordered_segments": [
            "Gulf of Aden westbound international shipping corridor",
            "Bab el-Mandeb Strait transit bottleneck",
            "Southern Red Sea traffic separation scheme",
            "Northern Red Sea approach to Gulf of Suez",
            "Port of Suez southern entrance to Mediterranean canal transit",
        ],
        "geojson_geometry": {
            "type": "LineString",
            "coordinates": [
                [45.0000, 11.8000],  # Gulf of Aden
                [43.3333, 12.5833],  # Bab el-Mandeb Strait
                [41.5000, 15.5000],  # Southern Red Sea
                [37.5000, 22.0000],  # Central Red Sea
                [33.5000, 27.5000],  # Gulf of Suez entry
                [32.5498, 29.9668],  # Port of Suez
                [32.2654, 30.5852],  # Suez Canal
            ],
        },
        "route_source": "MineTrace Global Maritime Chokepoint Observatory",
        "data_confidence": "DEMO_CANDIDATE",
        "designation": "CANDIDATE ROUTE — NOT CONFIRMED COMMERCIAL SCHEDULE",
    },
]


def seed_transport_routes(db: Session) -> int:
    """
    Idempotently seeds the 5 candidate critical-mineral transport routes into the SQLite database.
    Returns count of newly inserted routes.
    """
    inserted = 0
    for r_data in DEMO_ROUTES:
        existing = db.query(TransportRoute).filter(TransportRoute.route_id == r_data["route_id"]).first()
        if not existing:
            route = TransportRoute(
                route_id=r_data["route_id"],
                name=r_data["name"],
                origin=r_data["origin"],
                destination=r_data["destination"],
                mineral_relevance=r_data["mineral_relevance"],
                transport_mode=r_data["transport_mode"],
                geojson_geometry=json.dumps(r_data["geojson_geometry"]),
                ordered_segments=json.dumps(r_data["ordered_segments"]),
                primary_hubs=json.dumps(r_data["primary_hubs"]),
                route_source=r_data["route_source"],
                data_confidence=r_data["data_confidence"],
                designation=r_data["designation"],
                is_active=True,
            )
            db.add(route)
            inserted += 1

    if inserted > 0:
        db.commit()

    return inserted
