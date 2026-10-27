"""
Unit tests for Model 2 Phase 6: Route Feasibility and Alternative Route Engine.
"""
import pytest

from app.database.models import (
    TransportRoute,
    GeopoliticalEvent,
    RouteExposureMatch,
    R6RiskAssessment,
    RouteFeasibilityAssessment,
    utc_now,
)
from app.geospatial.routes_seed import seed_transport_routes
from app.routing.network_graph import TransportNetworkGraph
from app.routing.feasibility_engine import RouteFeasibilityEngine


def test_baseline_route_no_alerts(test_db):
    """An undisturbed candidate is commercially unconfirmed."""
    seed_transport_routes(test_db)
    engine = RouteFeasibilityEngine(db=test_db)

    route = test_db.query(TransportRoute).filter(TransportRoute.route_id == "route_chl_antofagasta_lithium").first()
    feas = engine.assess_route_feasibility(route)

    assert feas.operability_status == "NO_IDENTIFIED_ALERT"
    assert feas.regulatory_status == "UNKNOWN"
    assert feas.shipment_feasibility == "POTENTIALLY_POSSIBLE_UNCONFIRMED"
    assert feas.active_alert_count == 0


def test_route_at_risk_not_closed(test_db):
    """Verify route with active alert is AT_RISK and POTENTIALLY_POSSIBLE_UNCONFIRMED."""
    seed_transport_routes(test_db)
    engine = RouteFeasibilityEngine(db=test_db)

    route = test_db.query(TransportRoute).filter(TransportRoute.route_id == "route_cod_durban_cobalt").first()
    now = utc_now()

    event = GeopoliticalEvent(
        event_id="geo_durban_alert",
        event_type="MINING_STRIKE",
        title="Labor dispute reported along transit corridor",
        affected_country="South Africa",
        mineral_relevance="cobalt",
        verification_status="REPORTED",  # Single report, not confirmed closed
        status="ACTIVE",
    )
    test_db.add(event)
    test_db.commit()

    # R6 assessment: HIGH
    r6 = R6RiskAssessment(
        assessment_id="r6_test_high",
        event_id=event.id,
        route_id=route.id,
        risk_level="HIGH",
        heuristic_score=60.0,
        triggering_factors='["Mining strike near route"]',
        calculation_explanation="High exposure",
        potential_impacts='{"SECURITY_EXPOSURE": "POTENTIAL_IMPACT"}',
        source_evidence="[]",
        created_at=now,
    )
    test_db.add(r6)
    test_db.commit()

    feas = engine.assess_route_feasibility(route)
    assert feas.operability_status == "AT_RISK"
    assert feas.shipment_feasibility == "POTENTIALLY_POSSIBLE_UNCONFIRMED"
    assert feas.active_alert_count == 1


def test_official_headline_does_not_close_route(test_db):
    """Official event status alone is not a route-specific closure advisory."""
    seed_transport_routes(test_db)
    engine = RouteFeasibilityEngine(db=test_db)

    route = test_db.query(TransportRoute).filter(TransportRoute.route_id == "route_cod_durban_cobalt").first()
    now = utc_now()

    # Severe, officially confirmed port closure
    event = GeopoliticalEvent(
        event_id="geo_durban_official_close",
        event_type="PORT_CLOSURE",
        title="Official decree confirms indefinite closure of Port of Durban berths",
        affected_country="South Africa",
        affected_infrastructure="Port of Durban",
        location_name="durban_port",
        mineral_relevance="cobalt",
        verification_status="OFFICIALLY_CONFIRMED",
        status="ACTIVE",
    )
    test_db.add(event)
    test_db.commit()

    r6 = R6RiskAssessment(
        assessment_id="r6_test_critical",
        event_id=event.id,
        route_id=route.id,
        risk_level="CRITICAL",
        heuristic_score=90.0,
        triggering_factors='["Officially confirmed port closure"]',
        calculation_explanation="Critical exposure",
        potential_impacts='{"PORT_DISRUPTION": "CONFIRMED_IMPACT"}',
        source_evidence="[]",
        created_at=now,
    )
    test_db.add(r6)
    test_db.commit()

    feas = engine.assess_route_feasibility(route)
    assert feas.operability_status == "AT_RISK"
    assert feas.shipment_feasibility == "POTENTIALLY_POSSIBLE_UNCONFIRMED"

    # Verify candidate alternative was found bypassing Durban
    assert feas.alternative_route_id is None
    assert "CANDIDATE ALTERNATIVE — NOT CARRIER VERIFIED" in feas.alternative_designation
    # Different destination ports are not equivalent end-to-end routes.
    assert "carrier" in feas.limitations_disclaimer.lower()


def test_regulatory_review_trigger(test_db):
    """Verify export restriction triggers REVIEW_REQUIRED status."""
    seed_transport_routes(test_db)
    engine = RouteFeasibilityEngine(db=test_db)

    route = test_db.query(TransportRoute).filter(TransportRoute.route_id == "route_chl_antofagasta_lithium").first()
    now = utc_now()

    event = GeopoliticalEvent(
        event_id="geo_lithium_sanction",
        event_type="EXPORT_RESTRICTION",
        title="New export quotas announced for lithium compounds",
        affected_country="Chile",
        mineral_relevance="lithium",
        verification_status="REPORTED",
        status="ACTIVE",
    )
    test_db.add(event)
    test_db.commit()

    r6 = R6RiskAssessment(
        assessment_id="r6_test_sanction",
        event_id=event.id,
        route_id=route.id,
        risk_level="MODERATE",
        heuristic_score=35.0,
        triggering_factors='["Export quota rule"]',
        calculation_explanation="Regulatory exposure",
        potential_impacts='{"TRADE_RESTRICTION": "POTENTIAL_IMPACT"}',
        source_evidence="[]",
        created_at=now,
    )
    test_db.add(r6)
    test_db.commit()

    feas = engine.assess_route_feasibility(route)
    assert feas.regulatory_status == "REVIEW_REQUIRED"
    assert feas.shipment_feasibility == "POTENTIALLY_POSSIBLE_UNCONFIRMED"
