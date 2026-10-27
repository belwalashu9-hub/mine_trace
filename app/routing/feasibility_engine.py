"""
Route Feasibility Assessment and Alternative Corridor Engine (Model 2 Phase 6).
Evaluates operational status, regulatory review requirements, shipment feasibility,
and candidate alternative corridors with mandatory disclaimers.
"""
import json
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.database.models import (
    TransportRoute,
    R6RiskAssessment,
    RouteFeasibilityAssessment,
    GeopoliticalEvent,
    utc_now,
    RouteOperationalEvidence,
)
from app.routing.network_graph import TransportNetworkGraph


class RouteFeasibilityEngine:
    """
    Evaluates whether trade and transportation remain potentially possible along mineral corridors.
    Strictly prohibits unsupported YES/NO guarantees.
    """

    MANDATORY_DISCLAIMER = (
        "CANDIDATE ALTERNATIVE — NOT CARRIER VERIFIED. Physical route viability indicates geographic connectivity only. "
        "Commercial availability, freight booking, carrier acceptance, marine insurance premiums, transit tariffs, "
        "and customs clearance must be verified independently with certified logistics providers."
    )

    def __init__(self, db: Session):
        self.db = db
        self.network_graph = TransportNetworkGraph()

    def assess_route_feasibility(self, route: TransportRoute) -> RouteFeasibilityAssessment:
        """
        Assesses operability, regulatory review status, shipment feasibility,
        and alternative candidate corridors for a specific route.
        """
        # 1. Fetch active R6 risk assessments for this route
        r6_assessments = (
            self.db.query(R6RiskAssessment)
            .filter(R6RiskAssessment.route_id == route.id)
            .all()
        )

        r6_assessments = [r for r in r6_assessments if r.event and r.event.status == "ACTIVE"]
        active_count = len(r6_assessments)
        highest_risk = "UNKNOWN"
        risk_rank = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "LOW": 1, "UNKNOWN": 0}

        blocked_hubs: List[str] = []
        penalized_hubs: List[str] = []

        is_confirmed_closed = False
        requires_regulatory_review = False

        for r6 in r6_assessments:
            curr_rank = risk_rank.get(r6.risk_level, 0)
            if curr_rank > risk_rank.get(highest_risk, 0):
                highest_risk = r6.risk_level

            event = r6.event
            if event:
                if event.event_type in ("SANCTIONS_ANNOUNCEMENT", "EXPORT_RESTRICTION"):
                    requires_regulatory_review = True

                if False:  # Closures require separate current route-specific advisories.
                    pass
                elif r6.risk_level in ("HIGH", "CRITICAL"):
                    if event.affected_infrastructure:
                        penalized_hubs.append(event.affected_infrastructure)
                    if event.location_name:
                        penalized_hubs.append(event.location_name)

        advisory = (self.db.query(RouteOperationalEvidence)
                    .filter(RouteOperationalEvidence.route_id == route.id,
                            RouteOperationalEvidence.valid_until > utc_now())
                    .order_by(RouteOperationalEvidence.created_at.desc()).first())
        is_confirmed_closed = bool(advisory and advisory.status == "CLOSED")
        if is_confirmed_closed:
            blocked_hubs.extend(json.loads(advisory.affected_hubs or "[]"))

        # 2. Determine Operability Status
        if is_confirmed_closed:
            operability = "CONFIRMED_CLOSED"
        elif active_count > 0 and highest_risk in ("CRITICAL", "HIGH", "MODERATE"):
            operability = "AT_RISK"
        elif active_count == 0:
            operability = "NO_IDENTIFIED_ALERT"
        else:
            operability = "UNKNOWN"

        # 3. Determine Regulatory Review Status
        regulatory_status = "REVIEW_REQUIRED" if requires_regulatory_review else "UNKNOWN"

        # 4. Search for Candidate Alternative Corridor via Graph
        alt_data = None
        if operability in ("CONFIRMED_CLOSED", "AT_RISK"):
            alt_data = self.network_graph.find_candidate_alternative(
                route_id=route.route_id,
                blocked_hubs=blocked_hubs,
                penalized_hubs=penalized_hubs,
            )

        # 5. Determine Shipment Feasibility
        if operability == "CONFIRMED_CLOSED":
            if alt_data:
                feasibility = "POTENTIALLY_POSSIBLE_UNCONFIRMED"
            else:
                feasibility = "NO_SUPPORTED_OPTION_IDENTIFIED"
        elif operability == "AT_RISK" or regulatory_status == "REVIEW_REQUIRED":
            feasibility = "POTENTIALLY_POSSIBLE_UNCONFIRMED"
        elif operability == "NO_IDENTIFIED_ALERT":
            feasibility = "POTENTIALLY_POSSIBLE_UNCONFIRMED"
        else:
            feasibility = "UNKNOWN"

        # 6. Comparison Summary
        if alt_data:
            comparison_summary = (
                f"Candidate alternative corridor identified: '{alt_data['alternative_route_name']}' "
                f"({alt_data['estimated_distance_km']} km). "
                f"Justification: {alt_data['justification']}"
            )
            alt_route_id = alt_data["alternative_route_id"]
            alt_route_name = alt_data["alternative_route_name"]
            alt_designation = alt_data["designation"]
        else:
            comparison_summary = "No candidate alternative corridor identified in currently mapped routing network."
            alt_route_id = None
            alt_route_name = None
            alt_designation = "CANDIDATE ALTERNATIVE — NOT CARRIER VERIFIED"

        # 7. Persist or Update RouteFeasibilityAssessment
        existing = (
            self.db.query(RouteFeasibilityAssessment)
            .filter(RouteFeasibilityAssessment.route_id == route.id)
            .first()
        )

        now = utc_now()
        if existing:
            existing.operability_status = operability
            existing.regulatory_status = regulatory_status
            existing.shipment_feasibility = feasibility
            existing.active_alert_count = active_count
            existing.highest_risk_level = highest_risk
            existing.alternative_route_id = alt_route_id
            existing.alternative_route_name = alt_route_name
            existing.alternative_designation = alt_designation
            existing.comparison_summary = comparison_summary
            existing.limitations_disclaimer = self.MANDATORY_DISCLAIMER
            existing.updated_at = now
            record = existing
        else:
            record = RouteFeasibilityAssessment(
                route_id=route.id,
                operability_status=operability,
                regulatory_status=regulatory_status,
                shipment_feasibility=feasibility,
                active_alert_count=active_count,
                highest_risk_level=highest_risk,
                alternative_route_id=alt_route_id,
                alternative_route_name=alt_route_name,
                alternative_designation=alt_designation,
                comparison_summary=comparison_summary,
                limitations_disclaimer=self.MANDATORY_DISCLAIMER,
                created_at=now,
                updated_at=now,
            )
            self.db.add(record)

        self.db.commit()
        return record

    def assess_all_routes(self) -> int:
        """Evaluates feasibility for all active candidate transport routes."""
        routes = self.db.query(TransportRoute).filter(TransportRoute.is_active == True).all()
        count = 0
        for r in routes:
            self.assess_route_feasibility(r)
            count += 1
        return count
