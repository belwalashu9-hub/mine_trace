"""
Unit tests for Model 2 Phase 4: Critical Mineral Supply Chain & Physical Route Mapping.
"""
import json
import pytest

from app.database.models import GeopoliticalEvent, TransportRoute, RouteExposureMatch, utc_now
from app.geospatial.haversine import haversine_distance_km, point_to_linestring_distance_km
from app.geospatial.routes_seed import seed_transport_routes
from app.geospatial.matching_engine import GeographicMatchingEngine


def test_haversine_distance_accuracy():
    """Verify geodesic Haversine distance calculates physical km correctly on the sphere."""
    # Distance between London (51.5074, -0.1278) and Paris (48.8566, 2.3522) is approx 343 km
    d = haversine_distance_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert 340.0 < d < 350.0


def test_seed_transport_routes(test_db):
    """Verify candidate transport routes are seeded idempotently with DEMO_CANDIDATE labels."""
    count1 = seed_transport_routes(test_db)
    assert count1 == 5

    # Re-seed should be idempotent (0 new inserts)
    count2 = seed_transport_routes(test_db)
    assert count2 == 0

    routes = test_db.query(TransportRoute).all()
    assert len(routes) == 5
    for r in routes:
        assert r.data_confidence == "DEMO_CANDIDATE"
        assert "CANDIDATE ROUTE" in r.designation


def test_physical_route_exposure_near_and_crossing(test_db):
    """Verify an incident right on or near the Bab el-Mandeb channel registers PHYSICAL_ROUTE_EXPOSURE."""
    seed_transport_routes(test_db)
    engine = GeographicMatchingEngine(db=test_db)

    # Event in Bab el-Mandeb Strait (12.5833, 43.3333) right on the Red Sea route
    crossing_event = GeopoliticalEvent(
        event_id="geo_red_sea_missile_1",
        event_type="MARITIME_SECURITY_INCIDENT",
        title="Missile attack on cargo ship near Bab el-Mandeb",
        affected_country="Yemen",
        location_name="Bab el-Mandeb Strait",
        latitude=12.5833,
        longitude=43.3333,
        has_coordinates=True,
        mineral_relevance="all_critical_minerals",
        relevance_type="DIRECT",
        extraction_confidence=0.90,
        verification_status="REPORTED",
        status="ACTIVE",
    )
    test_db.add(crossing_event)
    test_db.commit()

    matches = engine.match_event_to_routes(crossing_event)
    assert len(matches) >= 1

    red_sea_match = next((m for m in matches if m.route.route_id == "route_red_sea_suez_minerals"), None)
    assert red_sea_match is not None
    assert red_sea_match.exposure_type == "PHYSICAL_ROUTE_EXPOSURE"
    assert red_sea_match.is_intersecting is True
    assert red_sea_match.distance_km < 5.0


def test_event_far_from_route(test_db):
    """Verify an incident far away does NOT register physical route exposure."""
    seed_transport_routes(test_db)
    engine = GeographicMatchingEngine(db=test_db)

    # Incident in Tokyo, Japan (35.6762, 139.6503)
    far_event = GeopoliticalEvent(
        event_id="geo_tokyo_incident",
        event_type="PORT_CLOSURE",
        title="Dock strike in Tokyo Harbor",
        affected_country="Japan",
        location_name="Tokyo",
        latitude=35.6762,
        longitude=139.6503,
        has_coordinates=True,
        mineral_relevance="unknown",
        relevance_type="NONE",
        extraction_confidence=0.80,
        verification_status="REPORTED",
        status="ACTIVE",
    )
    test_db.add(far_event)
    test_db.commit()

    matches = engine.match_event_to_routes(far_event)
    # Tokyo has no overlap with our 5 candidate mineral routes
    assert len(matches) == 0


def test_missing_coordinates_falls_back_to_country_exposure(test_db):
    """Verify events without coordinates fall back to COUNTRY_EXPOSURE without crashing."""
    seed_transport_routes(test_db)
    engine = GeographicMatchingEngine(db=test_db)

    no_coords_event = GeopoliticalEvent(
        event_id="geo_chile_reform_law",
        event_type="EXPORT_RESTRICTION",
        title="National Parliament reviews lithium royalty mechanism in Chile",
        affected_country="Chile",
        location_name="Chile",
        latitude=None,
        longitude=None,
        has_coordinates=False,
        mineral_relevance="lithium",
        relevance_type="DIRECT",
        extraction_confidence=0.65,
        verification_status="REPORTED",
        status="ACTIVE",
    )
    test_db.add(no_coords_event)
    test_db.commit()

    matches = engine.match_event_to_routes(no_coords_event)
    chile_match = next((m for m in matches if m.route.route_id == "route_chl_antofagasta_lithium"), None)
    assert chile_match is not None
    assert chile_match.exposure_type == "COUNTRY_EXPOSURE"
    assert chile_match.distance_km is None
    assert chile_match.is_intersecting is False


def test_infrastructure_exposure_by_named_hub(test_db):
    """Verify named hub without coordinates triggers INFRASTRUCTURE_EXPOSURE."""
    seed_transport_routes(test_db)
    engine = GeographicMatchingEngine(db=test_db)

    hub_event = GeopoliticalEvent(
        event_id="geo_durban_power_failure",
        event_type="TRANSPORT_DISRUPTION",
        title="Substation outage impairs crane operations at Port of Durban",
        affected_country="South Africa",
        affected_infrastructure="Port of Durban",
        location_name="Port of Durban",
        latitude=None,
        longitude=None,
        has_coordinates=False,
        mineral_relevance="cobalt",
        relevance_type="INDIRECT",
        extraction_confidence=0.75,
        verification_status="REPORTED",
        status="ACTIVE",
    )
    test_db.add(hub_event)
    test_db.commit()

    matches = engine.match_event_to_routes(hub_event)
    durban_match = next((m for m in matches if m.route.route_id == "route_cod_durban_cobalt"), None)
    assert durban_match is not None
    assert durban_match.exposure_type == "INFRASTRUCTURE_EXPOSURE"
