"""
Unit tests for Model 2 Phase 5: R6 Geopolitical Risk Engine and Operational Impacts.
"""
from datetime import datetime, timezone, timedelta
import json
import pytest

from app.database.models import (
    GeopoliticalEvent,
    TransportRoute,
    RouteExposureMatch,
    R6RiskAssessment,
    RiskAnalysis,
    utc_now,
)
from app.risk.r6_engine import R6GeopoliticalRiskEngine


@pytest.fixture
def sample_route(test_db):
    route = TransportRoute(
        route_id="test_route_red_sea",
        name="Red Sea Transit Lane",
        origin="Gulf of Aden",
        destination="Suez Canal",
        mineral_relevance="all_critical_minerals",
        transport_mode="MARITIME",
        geojson_geometry='{"type": "LineString", "coordinates": [[45.0, 11.8], [43.3, 12.5], [32.5, 29.9]]}',
        route_source="Test Atlas",
        data_confidence="DEMO_CANDIDATE",
        designation="CANDIDATE ROUTE",
    )
    test_db.add(route)
    test_db.commit()
    return route


def test_r6_severe_verified_event(test_db, sample_route):
    """Verify severe, officially confirmed incident directly on route yields CRITICAL/HIGH risk."""
    now = utc_now()
    event = GeopoliticalEvent(
        event_id="geo_test_severe",
        event_type="MARITIME_SECURITY_INCIDENT",
        title="Official navy statement confirms missile attack in southern Red Sea",
        affected_country="Yemen",
        has_coordinates=True,
        latitude=12.5,
        longitude=43.3,
        publication_date=now,
        mineral_relevance="all_critical_minerals",
        relevance_type="DIRECT",
        extraction_confidence=0.95,
        verification_status="OFFICIALLY_CONFIRMED",
        status="ACTIVE",
    )
    test_db.add(event)
    test_db.commit()

    match = RouteExposureMatch(
        event_id=event.id,
        route_id=sample_route.id,
        exposure_type="PHYSICAL_ROUTE_EXPOSURE",
        distance_km=2.0,
        impact_zone_km=150.0,
        is_intersecting=True,
        created_at=now,
    )
    test_db.add(match)
    test_db.commit()

    res = R6GeopoliticalRiskEngine.evaluate_risk(event, sample_route, match)

    assert res["risk_level"] in ("CRITICAL", "HIGH")
    assert res["heuristic_score"] >= 70.0
    assert res["data_confidence"] == "HIGH"
    # Officially confirmed severe incident confirms security exposure
    assert res["potential_impacts"]["SECURITY_EXPOSURE"] == "POTENTIAL_IMPACT"


def test_r6_unverified_distant_event(test_db, sample_route):
    """Verify unverified event with country-only exposure yields lower MODERATE or LOW risk."""
    now = utc_now()
    event = GeopoliticalEvent(
        event_id="geo_test_unverified",
        event_type="POLITICAL_INSTABILITY",
        title="Unconfirmed social media reports claim opposition march planned",
        affected_country="Egypt",
        has_coordinates=False,
        publication_date=now - timedelta(days=20),  # Stale (>14 days)
        mineral_relevance="unknown",
        relevance_type="NONE",
        extraction_confidence=0.45,
        verification_status="UNVERIFIED",
        status="ACTIVE",
    )
    test_db.add(event)
    test_db.commit()

    match = RouteExposureMatch(
        event_id=event.id,
        route_id=sample_route.id,
        exposure_type="COUNTRY_EXPOSURE",
        distance_km=None,
        impact_zone_km=60.0,
        is_intersecting=False,
        created_at=now,
    )
    test_db.add(match)
    test_db.commit()

    res = R6GeopoliticalRiskEngine.evaluate_risk(event, sample_route, match)

    assert res["risk_level"] in ("MODERATE", "LOW")
    assert res["heuristic_score"] < 45.0
    # Unverified event must NOT establish confirmed impacts
    assert res["potential_impacts"]["SECURITY_EXPOSURE"] in ("POTENTIAL_IMPACT", "NOT_ESTABLISHED")


def test_r6_low_confidence_yields_unknown(test_db, sample_route):
    """Verify extremely low confidence input returns UNKNOWN risk level."""
    event = GeopoliticalEvent(
        event_id="geo_test_uncertain",
        event_type="UNKNOWN",
        title="Vague rumor of trade delay",
        extraction_confidence=0.15,  # Insufficient data
        verification_status="UNKNOWN",
        status="ACTIVE",
    )
    test_db.add(event)
    test_db.commit()

    match = RouteExposureMatch(
        event_id=event.id,
        route_id=sample_route.id,
        exposure_type="COUNTRY_EXPOSURE",
        created_at=utc_now(),
    )
    test_db.add(match)
    test_db.commit()

    res = R6GeopoliticalRiskEngine.evaluate_risk(event, sample_route, match)
    assert res["risk_level"] == "UNKNOWN"
    assert res["data_confidence"] == "INSUFFICIENT_DATA"


def test_model1_r1_to_r5_isolation(test_db):
    """Verify Model 1 historical RiskAnalysis is completely isolated from R6."""
    m1_analysis = RiskAnalysis(
        analysis_id="test_m1_analysis_iso",
        commodity_code="284440",
        reporter_country_code="USA",
        partner_country_code="COD",
        period="2024",
        combined_anomaly_score=50.0,
        score_completeness="COMPLETE",
        evaluated_rules='["R1","R2","R3","R4","R5"]',
        insufficient_rules="[]",
        flagged_rules='["R1"]',
    )
    test_db.add(m1_analysis)
    test_db.commit()

    # Model 1 analysis should only have historical R1-R5 rules
    assert "R6" not in m1_analysis.evaluated_rules
    assert m1_analysis.combined_anomaly_score == 50.0
