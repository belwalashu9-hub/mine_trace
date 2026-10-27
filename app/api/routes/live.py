"""
FastAPI REST router for Model 2: Real-Time Geopolitical Risk Monitoring.
Provides endpoints for live status, news feed, extracted events, physical routes,
R6 impact evaluations, operability feasibility, and candidate alternatives.
"""
import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.database.connection import get_db
from app.database.models import (
    GdeltArticle,
    GeopoliticalEvent,
    EventArticleEvidence,
    TransportRoute,
    RouteExposureMatch,
    R6RiskAssessment,
    RouteFeasibilityAssessment,
    GdeltIngestionRun,
)
from app.geopolitical.scheduler import Model2MonitoringScheduler
from app.geospatial.routes_seed import seed_transport_routes

router = APIRouter(prefix="/api/v1/live", tags=["Model 2: Live Geopolitical Risk Monitoring"])


# =============================================================================
# 1. Monitoring Status & Control
# =============================================================================

@router.get("/status")
def get_monitoring_status(db: Session = Depends(get_db)):
    """Returns real-time status of Model 2 monitoring service, last sync, and online/offline mode."""
    from app.database.models import Model2SyncStatus
    status = Model2MonitoringScheduler.get_status()
    latest = db.query(Model2SyncStatus).order_by(Model2SyncStatus.id.desc()).first()
    success = db.query(Model2SyncStatus).filter_by(source_mode="live", status="COMPLETED").order_by(Model2SyncStatus.id.desc()).first()
    if latest:
        status.update(last_sync_timestamp=latest.completed_at.isoformat(),last_sync_status=latest.status,last_metrics=json.loads(latest.metrics))
    status["last_successful_sync"] = success.completed_at.isoformat() if success else None
    status["coverage_notice"] = "News discovery is incomplete; no alert is not evidence of safe or available transport."
    return status


@router.post("/sync")
def trigger_manual_sync(
    background_tasks: BackgroundTasks,
    source: str = Query("live", pattern="^(live|offline)$"),
    category: Optional[str] = Query(None),
    max_records: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Triggers an on-demand synchronization run of the complete Model 2 pipeline."""
    result = Model2MonitoringScheduler.execute_full_pipeline(
        source=source,
        category=category,
        max_records=max_records,
        db=db,
    )
    return {
        "message": "Synchronization completed",
        "result": result,
    }


# =============================================================================
# 2. Raw & Normalized News Articles
# =============================================================================

@router.get("/news")
def get_recent_news(
    category: Optional[str] = Query(None),
    classification_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Returns paginated recent geopolitical news articles indexed from GDELT."""
    q = db.query(GdeltArticle).filter(GdeltArticle.provider != "synthetic_fixture")
    if classification_status:
        q = q.filter(GdeltArticle.classification_status == classification_status)
    if category:
        q = q.join(GdeltArticle.categories).filter(func.lower(GdeltArticle.categories.property.mapper.class_.category) == category.lower())

    total = q.count()
    articles = q.order_by(desc(GdeltArticle.id)).offset(offset).limit(limit).all()

    items = []
    for a in articles:
        cats = [c.category for c in a.categories] if hasattr(a, "categories") else []
        items.append({
            "id": a.id,
            "event_id": a.event_id,
            "title": a.title,
            "source_url": a.source_url,
            "canonical_url": a.canonical_url,
            "source_domain": a.source_domain,
            "source_country": a.source_country,
            "gdelt_seen_date": a.gdelt_seen_date.strftime("%Y-%m-%dT%H:%M:%SZ") if a.gdelt_seen_date else None,
            "first_seen_at": a.first_seen_at.strftime("%Y-%m-%dT%H:%M:%SZ") if a.first_seen_at else None,
            "last_seen_at": a.last_seen_at.strftime("%Y-%m-%dT%H:%M:%SZ") if a.last_seen_at else None,
            "classification_status": a.classification_status,
            "categories": cats,
            "provider": a.provider,
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


# =============================================================================
# 3. Classified Geopolitical Events
# =============================================================================

@router.get("/events")
def get_classified_events(
    country: Optional[str] = Query(None),
    mineral: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    verification_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Returns structured, classified geopolitical events with location and mineral relevance."""
    q = db.query(GeopoliticalEvent).filter(GeopoliticalEvent.status == "ACTIVE")

    if country:
        q = q.filter(func.lower(GeopoliticalEvent.affected_country) == country.lower())
    if mineral:
        q = q.filter(func.lower(GeopoliticalEvent.mineral_relevance) == mineral.lower())
    if event_type:
        q = q.filter(GeopoliticalEvent.event_type == event_type.upper())
    if verification_status:
        q = q.filter(GeopoliticalEvent.verification_status == verification_status.upper())

    total = q.count()
    events = q.order_by(desc(GeopoliticalEvent.id)).offset(offset).limit(limit).all()

    items = []
    for ev in events:
        evidence = [
            {"source_url": e.source_url, "article_title": e.article_title}
            for e in ev.article_evidence
        ]
        items.append({
            "id": ev.id,
            "event_id": ev.event_id,
            "synthetic": any(e.article and e.article.provider == "synthetic_fixture" for e in ev.article_evidence),
            "event_type": ev.event_type,
            "title": ev.title,
            "summary": ev.summary,
            "affected_country": ev.affected_country,
            "region": ev.region,
            "location_name": ev.location_name,
            "latitude": ev.latitude,
            "longitude": ev.longitude,
            "has_coordinates": ev.has_coordinates,
            "coordinate_basis": "Headline place-name reference; incident position unverified",
            "event_date": ev.event_date.isoformat() if ev.event_date else None,
            "gdelt_seen_dates": [e.article.gdelt_seen_date.isoformat() for e in ev.article_evidence if e.article and e.article.gdelt_seen_date],
            "publication_date": ev.publication_date.strftime("%Y-%m-%dT%H:%M:%SZ") if ev.publication_date else None,
            "mineral_relevance": ev.mineral_relevance,
            "relevance_type": ev.relevance_type,
            "affected_infrastructure": ev.affected_infrastructure,
            "extraction_confidence": ev.extraction_confidence,
            "verification_status": ev.verification_status,
            "source_article_count": ev.source_article_count,
            "evidence": evidence,
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get("/events/{event_id}")
def get_event_detail(event_id: str, db: Session = Depends(get_db)):
    """Retrieves full details of a specific geopolitical event including supporting evidence links."""
    ev = db.query(GeopoliticalEvent).filter(GeopoliticalEvent.event_id == event_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail=f"Geopolitical event '{event_id}' not found.")

    evidence = [
        {"source_url": e.source_url, "article_title": e.article_title, "relevance_reason": e.relevance_reason}
        for e in ev.article_evidence
    ]

    exposed_routes = [
        {"route_id": m.route.route_id, "name": m.route.name, "exposure_type": m.exposure_type, "distance_km": m.distance_km}
        for m in ev.route_matches
    ]

    return {
        "id": ev.id,
        "event_id": ev.event_id,
            "synthetic": any(e.article and e.article.provider == "synthetic_fixture" for e in ev.article_evidence),
        "event_type": ev.event_type,
        "title": ev.title,
        "summary": ev.summary,
        "affected_country": ev.affected_country,
        "region": ev.region,
        "location_name": ev.location_name,
        "latitude": ev.latitude,
        "longitude": ev.longitude,
        "has_coordinates": ev.has_coordinates,
            "coordinate_basis": "Headline place-name reference; incident position unverified",
            "event_date": ev.event_date.isoformat() if ev.event_date else None,
            "gdelt_seen_dates": [e.article.gdelt_seen_date.isoformat() for e in ev.article_evidence if e.article and e.article.gdelt_seen_date],
        "publication_date": ev.publication_date.strftime("%Y-%m-%dT%H:%M:%SZ") if ev.publication_date else None,
        "mineral_relevance": ev.mineral_relevance,
        "relevance_type": ev.relevance_type,
        "affected_infrastructure": ev.affected_infrastructure,
        "extraction_confidence": ev.extraction_confidence,
        "verification_status": ev.verification_status,
        "source_article_count": ev.source_article_count,
        "evidence": evidence,
        "exposed_routes": exposed_routes,
    }


# =============================================================================
# 4. Supply Chain & Country Exposure
# =============================================================================

@router.get("/affected-countries")
def get_affected_countries(db: Session = Depends(get_db)):
    """Returns aggregated exposure metrics across mineral producing/transit countries."""
    events = db.query(GeopoliticalEvent).filter(GeopoliticalEvent.status == "ACTIVE").all()
    country_map: Dict[str, Dict[str, Any]] = {}

    for ev in events:
        c = ev.affected_country or "UNKNOWN"
        if c not in country_map:
            country_map[c] = {
                "country": c,
                "event_count": 0,
                "minerals_exposed": set(),
                "event_types": set(),
                "highest_verification": "REPORTED",
            }
        country_map[c]["event_count"] += 1
        if ev.mineral_relevance and ev.mineral_relevance != "unknown":
            country_map[c]["minerals_exposed"].add(ev.mineral_relevance)
        country_map[c]["event_types"].add(ev.event_type)

    result = [
        {
            "country": v["country"],
            "event_count": v["event_count"],
            "minerals_exposed": list(v["minerals_exposed"]),
            "event_types": list(v["event_types"]),
        }
        for v in country_map.values()
    ]
    result.sort(key=lambda x: x["event_count"], reverse=True)
    return {"countries": result}


# =============================================================================
# 5. Physical Candidate Transport Routes & Geospatial
# =============================================================================

@router.get("/routes")
def list_transport_routes(
    mineral: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Lists stored candidate physical critical-mineral transport routes with GeoJSON geometries."""
    # Ensure routes seeded
    seed_transport_routes(db)
    q = db.query(TransportRoute).filter(TransportRoute.is_active == True)
    if mineral:
        q = q.filter(func.lower(TransportRoute.mineral_relevance) == mineral.lower())

    routes = q.all()
    items = []
    for r in routes:
        geom = json.loads(r.geojson_geometry) if r.geojson_geometry else None
        hubs = json.loads(r.primary_hubs) if r.primary_hubs else []
        feas = r.feasibility
        items.append({
            "id": r.id,
            "route_id": r.route_id,
            "name": r.name,
            "origin": r.origin,
            "destination": r.destination,
            "mineral_relevance": r.mineral_relevance,
            "transport_mode": r.transport_mode,
            "primary_hubs": hubs,
            "geometry": geom,
            "data_confidence": r.data_confidence,
            "designation": r.designation,
            "operability_status": feas.operability_status if feas else "NO_IDENTIFIED_ALERT",
            "shipment_feasibility": feas.shipment_feasibility if feas else "UNKNOWN",
            "active_alert_count": feas.active_alert_count if feas else 0,
        })
    return {"routes": items}


@router.get("/routes/{route_id}")
def get_route_detail(route_id: str, db: Session = Depends(get_db)):
    """Retrieves single transport route detail, ordered segments, and active alerts."""
    seed_transport_routes(db)
    r = db.query(TransportRoute).filter(TransportRoute.route_id == route_id).first()
    if not r:
        raise HTTPException(status_code=404, detail=f"Transport route '{route_id}' not found.")

    geom = json.loads(r.geojson_geometry) if r.geojson_geometry else None
    hubs = json.loads(r.primary_hubs) if r.primary_hubs else []
    segments = json.loads(r.ordered_segments) if r.ordered_segments else []
    feas = r.feasibility

    return {
        "id": r.id,
        "route_id": r.route_id,
        "name": r.name,
        "origin": r.origin,
        "destination": r.destination,
        "mineral_relevance": r.mineral_relevance,
        "transport_mode": r.transport_mode,
        "primary_hubs": hubs,
        "ordered_segments": segments,
        "geometry": geom,
        "data_confidence": r.data_confidence,
        "designation": r.designation,
        "operability_status": feas.operability_status if feas else "NO_IDENTIFIED_ALERT",
        "regulatory_status": feas.regulatory_status if feas else "NO_IDENTIFIED_RESTRICTION",
        "shipment_feasibility": feas.shipment_feasibility if feas else "UNKNOWN",
        "active_alert_count": feas.active_alert_count if feas else 0,
    }


@router.get("/affected-routes")
def get_affected_routes(db: Session = Depends(get_db)):
    """Returns candidate routes currently under active geopolitical risk alert."""
    seed_transport_routes(db)
    feasibilities = (
        db.query(RouteFeasibilityAssessment)
        .filter(RouteFeasibilityAssessment.operability_status != "NO_IDENTIFIED_ALERT")
        .all()
    )

    items = []
    for f in feasibilities:
        r = f.route
        items.append({
            "route_id": r.route_id,
            "name": r.name,
            "mineral": r.mineral_relevance,
            "operability_status": f.operability_status,
            "highest_risk_level": f.highest_risk_level,
            "active_alert_count": f.active_alert_count,
            "shipment_feasibility": f.shipment_feasibility,
            "alternative_route_name": f.alternative_route_name,
        })
    return {"affected_routes": items}


# =============================================================================
# 6. R6 Impact & Operational Consequences
# =============================================================================

@router.get("/routes/{route_id}/impact")
def get_route_r6_impact(route_id: str, db: Session = Depends(get_db)):
    """Returns R6 Near-Real-Time Geopolitical Disruption Exposure assessments for a candidate route."""
    seed_transport_routes(db)
    route = db.query(TransportRoute).filter(TransportRoute.route_id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail=f"Transport route '{route_id}' not found.")

    assessments = db.query(R6RiskAssessment).filter(R6RiskAssessment.route_id == route.id).all()

    items = []
    for a in assessments:
        ev = a.event
        impacts = json.loads(a.potential_impacts) if a.potential_impacts else {}
        factors = json.loads(a.triggering_factors) if a.triggering_factors else []
        evidence = json.loads(a.source_evidence) if a.source_evidence else []

        items.append({
            "assessment_id": a.assessment_id,
            "event_id": ev.event_id if ev else None,
            "event_title": ev.title if ev else None,
            "event_type": ev.event_type if ev else None,
            "verification_status": ev.verification_status if ev else None,
            "risk_level": a.risk_level,
            "heuristic_score": a.heuristic_score,
            "triggering_factors": factors,
            "potential_impacts": impacts,
            "source_evidence": evidence,
            "data_confidence": a.data_confidence,
            "calculation_explanation": a.calculation_explanation,
            "rule_version": a.rule_version,
            "evaluated_at": a.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    return {
        "route_id": route.route_id,
        "name": route.name,
        "assessments_count": len(items),
        "assessments": items,
    }


# =============================================================================
# 7. Operability, Feasibility & Candidate Alternatives
# =============================================================================

@router.get("/routes/{route_id}/feasibility")
def get_route_feasibility(route_id: str, db: Session = Depends(get_db)):
    """
    Evaluates whether trade and transportation remain potentially possible along mineral corridors.
    Strictly provides evidence-backed assessments with candidate alternative disclaimers.
    """
    seed_transport_routes(db)
    route = db.query(TransportRoute).filter(TransportRoute.route_id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail=f"Transport route '{route_id}' not found.")

    from app.routing.feasibility_engine import RouteFeasibilityEngine
    feas = RouteFeasibilityEngine(db).assess_route_feasibility(route)

    return {
        "route_id": route.route_id,
        "name": route.name,
        "mineral": route.mineral_relevance,
        "operability_status": feas.operability_status,
        "regulatory_status": feas.regulatory_status,
        "shipment_feasibility": feas.shipment_feasibility,
        "active_alert_count": feas.active_alert_count,
        "highest_risk_level": feas.highest_risk_level,
        "candidate_alternative": {
            "alternative_route_id": feas.alternative_route_id,
            "alternative_route_name": feas.alternative_route_name,
            "designation": feas.alternative_designation,
            "comparison_summary": feas.comparison_summary,
        } if feas.alternative_route_id else None,
        "limitations_disclaimer": feas.limitations_disclaimer,
        "updated_at": feas.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@router.get("/routes/{route_id}/alternatives")
def get_route_alternatives(route_id: str, db: Session = Depends(get_db)):
    """Returns candidate alternative corridors via transport network graph search."""
    seed_transport_routes(db)
    route = db.query(TransportRoute).filter(TransportRoute.route_id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail=f"Transport route '{route_id}' not found.")

    from app.routing.feasibility_engine import RouteFeasibilityEngine
    feas = RouteFeasibilityEngine(db).assess_route_feasibility(route)
    return {"route_id": route_id, "has_candidate_alternative": bool(feas.alternative_route_id),
            "candidate_alternative": {"route_id": feas.alternative_route_id, "name": feas.alternative_route_name,
                "designation": feas.alternative_designation, "explanation": feas.comparison_summary} if feas.alternative_route_id else None,
            "limitations": feas.limitations_disclaimer}


# =============================================================================
# 8. High-Level Dashboard Summary
# =============================================================================

@router.get("/dashboard/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    """Aggregates high-level telemetry and status cards for UI dashboard."""
    seed_transport_routes(db)

    total_articles = db.query(GdeltArticle).count()
    pending_articles = db.query(GdeltArticle).filter(GdeltArticle.classification_status == "pending").count()
    total_events = db.query(GeopoliticalEvent).filter(GeopoliticalEvent.status == "ACTIVE").count()
    critical_events = db.query(GeopoliticalEvent).filter(
        GeopoliticalEvent.status == "ACTIVE",
        GeopoliticalEvent.event_type.in_(["WAR", "MARITIME_SECURITY_INCIDENT", "PORT_CLOSURE", "MINE_SHUTDOWN"])
    ).count()

    total_routes = db.query(TransportRoute).filter(TransportRoute.is_active == True).count()
    at_risk_routes = db.query(RouteFeasibilityAssessment).filter(
        RouteFeasibilityAssessment.operability_status.in_(["AT_RISK", "CONFIRMED_CLOSED"])
    ).count()

    return {
        "overview": {
            "total_articles_indexed": total_articles,
            "pending_classification": pending_articles,
            "active_geopolitical_events": total_events,
            "critical_disruption_events": critical_events,
            "monitored_routes": total_routes,
            "routes_under_alert": at_risk_routes,
        },
        "system_status": get_monitoring_status(db),
    }
