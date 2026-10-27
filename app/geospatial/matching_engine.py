"""
Geospatial matching engine connecting classified GeopoliticalEvents to TransportRoutes.
Evaluates PHYSICAL_ROUTE_EXPOSURE, INFRASTRUCTURE_EXPOSURE, and COUNTRY_EXPOSURE.
"""
import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.database.models import (
    GeopoliticalEvent,
    TransportRoute,
    RouteExposureMatch,
    utc_now,
)
from app.geospatial.haversine import point_to_linestring_distance_km, point_to_segment_distance_km

EVENT_IMPACT_ZONES_KM: Dict[str, float] = {
    "MARITIME_SECURITY_INCIDENT": 150.0,
    "WAR": 120.0,
    "ARMED_CONFLICT": 100.0,
    "NATURAL_DISASTER": 75.0,
    "PORT_CLOSURE": 50.0,
    "TRANSPORT_DISRUPTION": 50.0,
    "MINE_SHUTDOWN": 40.0,
    "MINING_STRIKE": 30.0,
    "EXPORT_RESTRICTION": 50.0,
    "POLITICAL_INSTABILITY": 60.0,
    "SANCTIONS_ANNOUNCEMENT": 50.0,
}

ROUTE_COUNTRY_ASSOCIATIONS: Dict[str, List[str]] = {
    "route_cod_durban_cobalt": ["Democratic Republic of the Congo", "Zambia", "Zimbabwe", "South Africa"],
    "route_chl_antofagasta_lithium": ["Chile"],
    "route_idn_morowali_nickel": ["Indonesia", "China"],
    "route_moz_nacala_graphite": ["Mozambique"],
    "route_red_sea_suez_minerals": ["Yemen", "Egypt", "Saudi Arabia", "Sudan", "Eritrea", "Djibouti", "International Waters"],
}


class GeographicMatchingEngine:
    """
    Performs geodesic proximity, geometry intersection, and exposure categorization
    between GeopoliticalEvents and physical TransportRoutes.
    """

    def __init__(self, db: Session):
        self.db = db

    @classmethod
    def get_impact_zone_km(cls, event_type: str) -> float:
        return EVENT_IMPACT_ZONES_KM.get(event_type, 50.0)

    def match_event_to_routes(self, event: GeopoliticalEvent) -> List[RouteExposureMatch]:
        """
        Evaluates a single GeopoliticalEvent against all active candidate transport routes.
        Persists exposure match records and returns list of created/updated matches.
        """
        routes = self.db.query(TransportRoute).filter(TransportRoute.is_active == True).all()
        created_matches: List[RouteExposureMatch] = []
        impact_zone = self.get_impact_zone_km(event.event_type)

        for route in routes:
            exposure_type = None
            distance_km = None
            is_intersecting = False
            exposed_segment = None
            calc_details: Dict[str, Any] = {}

            # Parse route geometry
            try:
                geom = json.loads(route.geojson_geometry)
                coords = geom.get("coordinates", [])
            except Exception:
                coords = []

            # Parse primary hubs
            try:
                hubs = json.loads(route.primary_hubs) if route.primary_hubs else []
            except Exception:
                hubs = []

            # 1. Coordinate-based Physical Exposure Check
            if event.has_coordinates and event.latitude is not None and event.longitude is not None and coords:
                # Validate coordinate ranges
                if -90.0 <= event.latitude <= 90.0 and -180.0 <= event.longitude <= 180.0:
                    try:
                        distance_km = point_to_linestring_distance_km(event.latitude, event.longitude, coords)
                        distances = [point_to_segment_distance_km(event.latitude, event.longitude, a[1], a[0], b[1], b[0]) for a,b in zip(coords, coords[1:])]
                        calc_details["segment_index"] = distances.index(min(distances))
                        calc_details["location_uncertainty"] = "Headline geocoding is an infrastructure reference, not a precise incident fix."
                    except (ValueError, TypeError, IndexError):
                        continue
                    calc_details["calculated_geodesic_distance_km"] = round(distance_km, 2)
                    calc_details["impact_zone_threshold_km"] = impact_zone

                    if distance_km <= impact_zone:
                        exposure_type = "PHYSICAL_ROUTE_EXPOSURE"
                        is_intersecting = distance_km <= 5.0
                        exposed_segment = f"Within {round(distance_km, 1)}km of {route.name} transit path"

            # 2. Infrastructure-level Exposure Check
            if not exposure_type and event.affected_infrastructure:
                infra_lower = event.affected_infrastructure.lower()
                for hub in hubs:
                    if hub.lower() in infra_lower or (event.location_name and hub.lower() in event.location_name.lower()):
                        exposure_type = "INFRASTRUCTURE_EXPOSURE"
                        exposed_segment = f"Identified infrastructure hub: {hub}"
                        calc_details["matched_hub"] = hub
                        break

            # 3. Country-level Supply Chain Exposure Check
            if not exposure_type and event.affected_country:
                route_countries = ROUTE_COUNTRY_ASSOCIATIONS.get(route.route_id, [])
                if any(c.lower() == event.affected_country.lower() for c in route_countries):
                    exposure_type = "COUNTRY_EXPOSURE"
                    exposed_segment = f"National territory of {event.affected_country} intersected by supply corridor"
                    calc_details["matched_country"] = event.affected_country

            if exposure_type:
                # Check for existing match
                existing = (
                    self.db.query(RouteExposureMatch)
                    .filter(
                        RouteExposureMatch.event_id == event.id,
                        RouteExposureMatch.route_id == route.id,
                    )
                    .first()
                )

                if existing:
                    existing.exposure_type = exposure_type
                    existing.distance_km = round(distance_km, 2) if distance_km is not None else None
                    existing.impact_zone_km = impact_zone
                    existing.is_intersecting = is_intersecting
                    existing.exposed_segment = exposed_segment
                    existing.calculation_details = json.dumps(calc_details)
                    created_matches.append(existing)
                else:
                    match_record = RouteExposureMatch(
                        event_id=event.id,
                        route_id=route.id,
                        exposure_type=exposure_type,
                        distance_km=round(distance_km, 2) if distance_km is not None else None,
                        impact_zone_km=impact_zone,
                        is_intersecting=is_intersecting,
                        exposed_segment=exposed_segment,
                        calculation_details=json.dumps(calc_details),
                        created_at=utc_now(),
                    )
                    self.db.add(match_record)
                    created_matches.append(match_record)

        if created_matches:
            self.db.commit()

        return created_matches

    def evaluate_all_active_events(self) -> int:
        """
        Evaluates all active GeopoliticalEvents against all transport routes.
        Returns total exposure matches established.
        """
        from app.database.models import R6RiskAssessment
        for item in self.db.query(R6RiskAssessment).all(): self.db.delete(item)
        for item in self.db.query(RouteExposureMatch).all(): self.db.delete(item)
        self.db.flush()
        events = self.db.query(GeopoliticalEvent).filter(GeopoliticalEvent.status == "ACTIVE").all()
        total_matches = 0
        for ev in events:
            matches = self.match_event_to_routes(ev)
            total_matches += len(matches)
        self.db.commit()
        return total_matches
