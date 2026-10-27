"""
Model 2 R6 Geopolitical Risk Engine.
Calculates Near-Real-Time Geopolitical Disruption Exposure strictly separate from Model 1 (R1-R5).
Provides transparent, auditable heuristic factors and operational impact assessments.
"""
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.risk.model2_policy import severity, thresholds

from app.database.models import (
    GeopoliticalEvent,
    TransportRoute,
    RouteExposureMatch,
    R6RiskAssessment,
    EventArticleEvidence,
    utc_now,
)

BASE_SEVERITY_WEIGHTS: Dict[str, float] = {
    "WAR": 35.0,
    "ARMED_CONFLICT": 35.0,
    "MARITIME_SECURITY_INCIDENT": 30.0,
    "PORT_CLOSURE": 30.0,
    "MINE_SHUTDOWN": 25.0,
    "EXPORT_RESTRICTION": 25.0,
    "MINING_STRIKE": 20.0,
    "TRANSPORT_DISRUPTION": 20.0,
    "SANCTIONS_ANNOUNCEMENT": 20.0,
    "NATURAL_DISASTER": 15.0,
    "POLITICAL_INSTABILITY": 15.0,
    "OTHER": 10.0,
    "UNKNOWN": 5.0,
}


class R6GeopoliticalRiskEngine:
    """
    Evaluates R6 near-real-time geopolitical exposure for a matched event and transport route.
    """

    def __init__(self, db: Session):
        self.db = db

    @classmethod
    def evaluate_risk(
        cls,
        event: GeopoliticalEvent,
        route: TransportRoute,
        match: RouteExposureMatch,
    ) -> Dict[str, Any]:
        """
        Computes deterministic R6 score, risk level, triggering factors,
        and operational impact indicators.
        """
        triggering_factors: List[str] = []

        # 1. Base Severity Score (0-35)
        severity_score = severity(event.event_type, BASE_SEVERITY_WEIGHTS)
        moderate_threshold, high_threshold, critical_threshold = thresholds()
        triggering_factors.append(f"Event type '{event.event_type}' assigned base severity weight: {severity_score}/35.0")

        # 2. Proximity & Exposure Score (0-35)
        proximity_score = 0.0
        if match.exposure_type == "PHYSICAL_ROUTE_EXPOSURE":
            if match.is_intersecting:
                proximity_score = 35.0
                triggering_factors.append("Direct intersection with route corridor (<5km): +35.0")
            elif match.distance_km is not None and match.impact_zone_km:
                ratio = max(0.0, 1.0 - (match.distance_km / match.impact_zone_km))
                proximity_score = round(20.0 + (15.0 * ratio), 1)
                triggering_factors.append(f"Proximity within impact zone ({match.distance_km}km / {match.impact_zone_km}km): +{proximity_score}")
            else:
                proximity_score = 25.0
                triggering_factors.append("Physical route proximity confirmed: +25.0")
        elif match.exposure_type == "INFRASTRUCTURE_EXPOSURE":
            proximity_score = 25.0
            triggering_factors.append(f"Direct match on critical transit hub/infrastructure ({event.affected_infrastructure}): +25.0")
        elif match.exposure_type == "COUNTRY_EXPOSURE":
            proximity_score = 10.0
            triggering_factors.append(f"Supply corridor traverses sovereign territory of {event.affected_country}: +10.0")

        # 3. Verification Score (0-15)
        verification_score = 5.0
        v_status = event.verification_status
        if v_status == "OFFICIALLY_CONFIRMED":
            verification_score = 15.0
            triggering_factors.append("Officially confirmed by authoritative public statement: +15.0")
        elif v_status == "CORROBORATED":
            verification_score = 12.0
            triggering_factors.append(f"Corroborated across {event.source_article_count} independent reports: +12.0")
        elif v_status == "REPORTED":
            verification_score = 8.0
            triggering_factors.append("Reported by single news outlet (pending independent corroboration): +8.0")
        elif v_status in ("UNVERIFIED", "DISPUTED"):
            verification_score = 3.0
            triggering_factors.append(f"Event status '{v_status}' (reduced weight applied): +3.0")

        # 4. Mineral Relevance Score (0-15)
        mineral_score = 0.0
        if event.relevance_type == "DIRECT":
            mineral_score = 15.0
            triggering_factors.append(f"Direct relevance to monitored critical mineral ({event.mineral_relevance}): +15.0")
        elif event.relevance_type == "INDIRECT":
            mineral_score = 10.0
            triggering_factors.append(f"Indirect relevance via mineral processing or logistics hub ({event.mineral_relevance}): +10.0")
        else:
            mineral_score = 0.0
            triggering_factors.append("Mineral relevance not established directly: +0.0")

        # Total Heuristic Score
        raw_score = severity_score + proximity_score + verification_score + mineral_score

        # Freshness Adjustment
        now = utc_now()
        seen = [e.article.gdelt_seen_date for e in event.article_evidence if e.article and e.article.gdelt_seen_date]
        pub_date = event.event_date or event.publication_date or (max(seen) if seen else event.created_at)
        if pub_date:
            pub_aware = pub_date.replace(tzinfo=timezone.utc) if pub_date.tzinfo is None else pub_date
            age_days = (now - pub_aware).total_seconds() / 86400.0
            if age_days <= 2.0:
                raw_score += 5.0
                triggering_factors.append("Fresh intelligence (<48 hours old): +5.0")
            elif age_days > 14.0:
                raw_score -= 10.0
                triggering_factors.append(f"Stale intelligence ({int(age_days)} days old): -10.0")

        heuristic_score = max(0.0, min(100.0, round(raw_score, 1)))

        # Assign Risk Level
        if (event.extraction_confidence or 0) < 0.25 or event.event_type == "UNKNOWN" or not match.exposure_type:
            risk_level = "UNKNOWN"
            data_confidence = "INSUFFICIENT_DATA"
        elif heuristic_score >= critical_threshold:
            risk_level = "CRITICAL"
            data_confidence = "HIGH" if v_status in ("CORROBORATED", "OFFICIALLY_CONFIRMED") else "MEDIUM"
        elif heuristic_score >= high_threshold:
            risk_level = "HIGH"
            data_confidence = "HIGH" if v_status in ("CORROBORATED", "OFFICIALLY_CONFIRMED") else "MEDIUM"
        elif heuristic_score >= moderate_threshold:
            risk_level = "MODERATE"
            data_confidence = "MEDIUM"
        else:
            risk_level = "LOW"
            data_confidence = "MEDIUM"

        # 5. Evaluate Operational Impacts (Strict Evidence Rules)
        # Confirmation of an event does not establish route-specific operational impact.
        is_official = False
        potential_impacts = {
            "SECURITY_EXPOSURE": (
                "CONFIRMED_IMPACT" if is_official and event.event_type in ("WAR", "MARITIME_SECURITY_INCIDENT")
                else ("POTENTIAL_IMPACT" if event.event_type in ("WAR", "ARMED_CONFLICT", "MARITIME_SECURITY_INCIDENT") else "NOT_ESTABLISHED")
            ),
            "PRODUCTION_INTERRUPTION": (
                "CONFIRMED_IMPACT" if is_official and event.event_type in ("MINE_SHUTDOWN", "MINING_STRIKE")
                else ("POTENTIAL_IMPACT" if event.event_type in ("MINE_SHUTDOWN", "MINING_STRIKE") else "NOT_ESTABLISHED")
            ),
            "TRANSPORT_DELAY_RISK": (
                "POTENTIAL_IMPACT" if match.exposure_type in ("PHYSICAL_ROUTE_EXPOSURE", "INFRASTRUCTURE_EXPOSURE") else "NOT_ESTABLISHED"
            ),
            "PORT_DISRUPTION": (
                "CONFIRMED_IMPACT" if is_official and event.event_type == "PORT_CLOSURE"
                else ("POTENTIAL_IMPACT" if event.event_type == "PORT_CLOSURE" or "port" in (event.affected_infrastructure or "").lower() else "NOT_ESTABLISHED")
            ),
            "BORDER_DISRUPTION": (
                "POTENTIAL_IMPACT" if "border" in (event.affected_infrastructure or "").lower() or event.event_type == "EXPORT_RESTRICTION" else "NOT_ESTABLISHED"
            ),
            "REROUTING_REQUIREMENT": (
                "POTENTIAL_IMPACT" if heuristic_score >= 50.0 and match.exposure_type == "PHYSICAL_ROUTE_EXPOSURE" else "NOT_ESTABLISHED"
            ),
            "TRADE_RESTRICTION": (
                "CONFIRMED_IMPACT" if is_official and event.event_type in ("EXPORT_RESTRICTION", "SANCTIONS_ANNOUNCEMENT")
                else ("POTENTIAL_IMPACT" if event.event_type in ("EXPORT_RESTRICTION", "SANCTIONS_ANNOUNCEMENT") else "NOT_ESTABLISHED")
            ),
            "LOGISTICS_COST_PRESSURE": (
                "POTENTIAL_IMPACT" if heuristic_score >= 35.0 else "NOT_ESTABLISHED"
            ),
        }

        explanation = (
            f"R6 Rule Evaluation: {risk_level} (Score {heuristic_score}/100). "
            f"Event '{event.title[:80]}' triggered {match.exposure_type} on candidate corridor '{route.name}'. "
            f"Verification is {v_status} with {event.relevance_type} relevance to {event.mineral_relevance}. "
            "Note: Assessment represents potential exposure, not confirmed cargo embargo."
        )

        return {
            "risk_level": risk_level,
            "heuristic_score": heuristic_score,
            "triggering_factors": triggering_factors,
            "calculation_explanation": explanation,
            "potential_impacts": potential_impacts,
            "data_confidence": data_confidence,
            "rule_version": "1.0",
        }

    def assess_all_exposure_matches(self) -> int:
        """
        Runs R6 evaluations for all established RouteExposureMatches and persists R6RiskAssessment records.
        """
        matches = self.db.query(RouteExposureMatch).all()
        assessed_count = 0

        for match in matches:
            event = match.event
            route = match.route
            if not event or not route or event.status != "ACTIVE":
                continue

            assessment_dict = self.evaluate_risk(event=event, route=route, match=match)

            # Retrieve supporting source URLs
            evidence_records = (
                self.db.query(EventArticleEvidence)
                .filter(EventArticleEvidence.event_id == event.id)
                .all()
            )
            source_urls = [e.source_url for e in evidence_records]

            # Check if assessment exists
            existing = (
                self.db.query(R6RiskAssessment)
                .filter(
                    R6RiskAssessment.event_id == event.id,
                    R6RiskAssessment.route_id == route.id,
                )
                .first()
            )

            if existing:
                existing.risk_level = assessment_dict["risk_level"]
                existing.heuristic_score = assessment_dict["heuristic_score"]
                existing.triggering_factors = json.dumps(assessment_dict["triggering_factors"])
                existing.calculation_explanation = assessment_dict["calculation_explanation"]
                existing.potential_impacts = json.dumps(assessment_dict["potential_impacts"])
                existing.source_evidence = json.dumps(source_urls)
                existing.data_confidence = assessment_dict["data_confidence"]
            else:
                record = R6RiskAssessment(
                    assessment_id=f"r6_{uuid.uuid4().hex[:12]}",
                    event_id=event.id,
                    route_id=route.id,
                    risk_level=assessment_dict["risk_level"],
                    heuristic_score=assessment_dict["heuristic_score"],
                    triggering_factors=json.dumps(assessment_dict["triggering_factors"]),
                    calculation_explanation=assessment_dict["calculation_explanation"],
                    potential_impacts=json.dumps(assessment_dict["potential_impacts"]),
                    source_evidence=json.dumps(source_urls),
                    data_confidence=assessment_dict["data_confidence"],
                    rule_version="1.0",
                    created_at=utc_now(),
                )
                self.db.add(record)

            assessed_count += 1

        if assessed_count > 0:
            self.db.commit()

        return assessed_count
