"""Unit tests for Phase 4 Risk Ranking Engine."""
from datetime import datetime, timezone, timedelta
import json
import pytest

from app.database.models import RiskAnalysis
from app.ranking.service import RankingService
from app.ranking.rules import (
    RANKING_POLICY_VERSION,
    TIE_BREAKER_POLICY,
    SCOPE_GLOBAL,
    SCOPE_FILTERED,
    COMPLETENESS_COMPLETE,
    COMPLETENESS_PARTIAL,
    COMPLETENESS_UNAVAILABLE,
    EXCLUSION_PARTIAL,
    EXCLUSION_UNAVAILABLE,
    EXCLUSION_INVALID_SCORE,
)


def create_analysis_record(
    db,
    analysis_id: str,
    score: float,
    completeness: str = "COMPLETE",
    commodity_code: str = "283691",
    mineral_type: str = "Lithium carbonate",
    reporter: str = "CHL",
    partner: str = "USA",
    period: str = "2023",
    classification: str = "RED",
    flag_status: str = "FLAGGED",
    created_at: datetime = None,
):
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    analysis = RiskAnalysis(
        analysis_id=analysis_id,
        trade_record_id=None,
        commodity_code=commodity_code,
        mineral_type=mineral_type,
        reporter_country_code=reporter,
        partner_country_code=partner,
        period=period,
        combined_anomaly_score=score,
        score_completeness=completeness,
        evaluated_rules=json.dumps(["R1", "R2", "R3", "R4", "R5"]),
        insufficient_rules=json.dumps(["R2"]) if completeness == "PARTIAL" else json.dumps([]),
        flagged_rules=json.dumps(["R1", "R3"]) if flag_status == "FLAGGED" else json.dumps([]),
        sanctions_status="NO_IDENTIFIED_MATCH",
        classification=classification,
        flag_status=flag_status,
        classification_explanation="Test explanation",
        created_at=created_at,
    )
    db.add(analysis)
    db.commit()
    return analysis


def test_primary_ranking_order_descending(test_db):
    """Highest anomaly scores must be ranked first."""
    base_time = datetime.now(timezone.utc)
    create_analysis_record(test_db, "REC-LOW", 15.0, created_at=base_time, classification="GREEN")
    create_analysis_record(test_db, "REC-HIGH", 85.0, created_at=base_time, classification="RED")
    create_analysis_record(test_db, "REC-MED", 45.0, created_at=base_time, classification="AMBER")

    service = RankingService(test_db)
    res = service.get_primary_ranking()

    assert res.total_eligible == 3
    assert res.scope == SCOPE_GLOBAL
    assert len(res.rankings) == 3
    assert res.rankings[0].analysis_id == "REC-HIGH"
    assert res.rankings[0].rank == 1
    assert res.rankings[0].anomaly_score == 85.0
    assert res.rankings[0].classification == "RED"

    assert res.rankings[1].analysis_id == "REC-MED"
    assert res.rankings[1].rank == 2
    assert res.rankings[1].anomaly_score == 45.0
    assert res.rankings[1].classification == "AMBER"

    assert res.rankings[2].analysis_id == "REC-LOW"
    assert res.rankings[2].rank == 3
    assert res.rankings[2].anomaly_score == 15.0
    assert res.rankings[2].classification == "GREEN"


def test_tie_breaking_policy_newer_created_at_wins(test_db):
    """When scores are identical, more recent created_at takes precedence."""
    t_earlier = datetime.now(timezone.utc) - timedelta(hours=2)
    t_later = datetime.now(timezone.utc)

    create_analysis_record(test_db, "REC-OLDER", 50.0, created_at=t_earlier)
    create_analysis_record(test_db, "REC-NEWER", 50.0, created_at=t_later)

    service = RankingService(test_db)
    res = service.get_primary_ranking()

    assert res.total_eligible == 2
    assert res.rankings[0].analysis_id == "REC-NEWER"
    assert res.rankings[0].rank == 1
    assert res.rankings[1].analysis_id == "REC-OLDER"
    assert res.rankings[1].rank == 2


def test_tie_breaking_policy_uuid_lexicographical_fallback(test_db):
    """When scores and timestamps are identical, lexicographical analysis_id ASC breaks ties."""
    same_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    create_analysis_record(test_db, "UUID-Z", 50.0, created_at=same_time)
    create_analysis_record(test_db, "UUID-A", 50.0, created_at=same_time)
    create_analysis_record(test_db, "UUID-M", 50.0, created_at=same_time)

    service = RankingService(test_db)
    res = service.get_primary_ranking()

    assert res.total_eligible == 3
    assert [r.analysis_id for r in res.rankings] == ["UUID-A", "UUID-M", "UUID-Z"]
    assert [r.rank for r in res.rankings] == [1, 2, 3]


def test_exclusion_of_incomplete_and_invalid_records(test_db):
    """PARTIAL, UNAVAILABLE, and out-of-bounds records must be excluded from primary ranking."""
    create_analysis_record(test_db, "REC-COMPLETE", 70.0, completeness="COMPLETE")
    create_analysis_record(test_db, "REC-PARTIAL", 60.0, completeness="PARTIAL")
    create_analysis_record(test_db, "REC-UNAVAILABLE", 0.0, completeness="UNAVAILABLE")
    create_analysis_record(test_db, "REC-CORRUPT-HIGH", 150.0, completeness="COMPLETE")
    create_analysis_record(test_db, "REC-CORRUPT-NEG", -10.0, completeness="COMPLETE")

    service = RankingService(test_db)
    primary = service.get_primary_ranking()

    # Only REC-COMPLETE is eligible
    assert primary.total_eligible == 1
    assert primary.rankings[0].analysis_id == "REC-COMPLETE"
    assert primary.rankings[0].rank == 1

    # Incomplete records must be retrievable via get_incomplete_records
    incomplete = service.get_incomplete_records()
    assert incomplete.total == 4
    excluded_ids = {r.analysis_id for r in incomplete.records}
    assert excluded_ids == {"REC-PARTIAL", "REC-UNAVAILABLE", "REC-CORRUPT-HIGH", "REC-CORRUPT-NEG"}

    # Verify explicit exclusion reasons
    partial_item = next(r for r in incomplete.records if r.analysis_id == "REC-PARTIAL")
    assert partial_item.exclusion_reason == EXCLUSION_PARTIAL
    assert partial_item.score_completeness == "PARTIAL"
    assert partial_item.anomaly_score == 60.0  # Original score preserved!

    unavail_item = next(r for r in incomplete.records if r.analysis_id == "REC-UNAVAILABLE")
    assert unavail_item.exclusion_reason == EXCLUSION_UNAVAILABLE

    corrupt_item = next(r for r in incomplete.records if r.analysis_id == "REC-CORRUPT-HIGH")
    assert corrupt_item.exclusion_reason == EXCLUSION_INVALID_SCORE


def test_domain_filtering_and_scope(test_db):
    """Filtering by commodity, country, period, classification, status, and score."""
    create_analysis_record(test_db, "REC-CHL-LITHIUM", 80.0, commodity_code="283691", reporter="CHL", partner="USA", period="2023", classification="RED", flag_status="FLAGGED")
    create_analysis_record(test_db, "REC-AUS-LITHIUM", 40.0, commodity_code="283691", reporter="AUS", partner="CHN", period="2023", classification="AMBER", flag_status="NOT_FLAGGED")
    create_analysis_record(test_db, "REC-COD-COBALT", 90.0, commodity_code="260500", mineral_type="Cobalt ores", reporter="COD", partner="CHN", period="2022", classification="RED", flag_status="FLAGGED")

    service = RankingService(test_db)

    # Filter by commodity
    res_comm = service.get_primary_ranking(commodity_code="283691")
    assert res_comm.total_eligible == 2
    assert res_comm.scope == SCOPE_FILTERED
    assert [r.analysis_id for r in res_comm.rankings] == ["REC-CHL-LITHIUM", "REC-AUS-LITHIUM"]
    assert res_comm.rankings[0].rank == 1
    assert res_comm.rankings[1].rank == 2

    # Filter by reporter country
    res_rep = service.get_primary_ranking(reporter_country_code="COD")
    assert res_rep.total_eligible == 1
    assert res_rep.rankings[0].analysis_id == "REC-COD-COBALT"

    # Filter by score range
    res_score = service.get_primary_ranking(min_score=50.0, max_score=100.0)
    assert res_score.total_eligible == 2
    assert [r.analysis_id for r in res_score.rankings] == ["REC-COD-COBALT", "REC-CHL-LITHIUM"]

    # Filter by classification
    res_amber = service.get_primary_ranking(classification="AMBER")
    assert res_amber.total_eligible == 1
    assert res_amber.rankings[0].analysis_id == "REC-AUS-LITHIUM"

    # Filter by period range
    res_period = service.get_primary_ranking(period_start="2023", period_end="2023")
    assert res_period.total_eligible == 2


def test_pagination(test_db):
    """Pagination must assign proper 1-based ranks across multiple pages."""
    for i in range(1, 6):
        create_analysis_record(test_db, f"REC-{i}", float(i * 10))

    service = RankingService(test_db)

    # Page 1, size 2
    p1 = service.get_primary_ranking(page=1, page_size=2)
    assert p1.total_eligible == 5
    assert p1.total_pages == 3
    assert p1.has_next is True
    assert p1.has_prev is False
    assert len(p1.rankings) == 2
    assert p1.rankings[0].rank == 1
    assert p1.rankings[0].anomaly_score == 50.0
    assert p1.rankings[1].rank == 2
    assert p1.rankings[1].anomaly_score == 40.0

    # Page 2, size 2
    p2 = service.get_primary_ranking(page=2, page_size=2)
    assert p2.has_next is True
    assert p2.has_prev is True
    assert len(p2.rankings) == 2
    assert p2.rankings[0].rank == 3
    assert p2.rankings[0].anomaly_score == 30.0
    assert p2.rankings[1].rank == 4
    assert p2.rankings[1].anomaly_score == 20.0

    # Page 3, size 2
    p3 = service.get_primary_ranking(page=3, page_size=2)
    assert p3.has_next is False
    assert p3.has_prev is True
    assert len(p3.rankings) == 1
    assert p3.rankings[0].rank == 5
    assert p3.rankings[0].anomaly_score == 10.0


def test_record_rank_lookup(test_db):
    """Specific analysis ID lookup must report its rank or exclusion reason."""
    create_analysis_record(test_db, "REC-1", 90.0)
    create_analysis_record(test_db, "REC-2", 70.0)
    create_analysis_record(test_db, "REC-3", 50.0)
    create_analysis_record(test_db, "REC-PARTIAL", 40.0, completeness="PARTIAL")

    service = RankingService(test_db)

    # Eligible lookup
    lookup2 = service.get_record_rank("REC-2")
    assert lookup2 is not None
    assert lookup2.is_eligible is True
    assert lookup2.rank == 2
    assert lookup2.total_eligible == 3
    assert lookup2.exclusion_reason is None

    # Excluded lookup
    lookup_partial = service.get_record_rank("REC-PARTIAL")
    assert lookup_partial is not None
    assert lookup_partial.is_eligible is False
    assert lookup_partial.rank is None
    assert lookup_partial.exclusion_reason == EXCLUSION_PARTIAL

    # Non-existent lookup
    lookup_none = service.get_record_rank("DOES-NOT-EXIST")
    assert lookup_none is None


def test_ranking_summary(test_db):
    """Summary metrics must correctly aggregate complete and incomplete counts."""
    create_analysis_record(test_db, "R1", 80.0, completeness="COMPLETE", classification="RED", flag_status="FLAGGED")
    create_analysis_record(test_db, "R2", 40.0, completeness="COMPLETE", classification="AMBER", flag_status="NOT_FLAGGED")
    create_analysis_record(test_db, "R3", 20.0, completeness="PARTIAL", classification="INSUFFICIENT_DATA", flag_status="INSUFFICIENT_DATA")

    service = RankingService(test_db)
    summary = service.get_ranking_summary()

    assert summary.total_analyses == 3
    assert summary.eligible_complete_count == 2
    assert summary.partial_excluded_count == 1
    assert summary.highest_score == 80.0
    assert summary.lowest_score == 40.0
    assert summary.average_score == 60.0
    assert summary.classification_breakdown.get("RED") == 1
    assert summary.classification_breakdown.get("AMBER") == 1
    assert summary.classification_breakdown.get("INSUFFICIENT_DATA") == 1


def test_ranking_snapshot_creation_and_retrieval(test_db):
    """Snapshot must capture point-in-time rankings and allow subsequent retrieval."""
    create_analysis_record(test_db, "R1", 80.0)
    create_analysis_record(test_db, "R2", 60.0)
    create_analysis_record(test_db, "R-PART", 30.0, completeness="PARTIAL")

    service = RankingService(test_db)
    snap = service.create_ranking_snapshot(name="Q1 Baseline", description="Test snapshot")

    assert snap.snapshot_id is not None
    assert snap.name == "Q1 Baseline"
    assert snap.total_eligible_count == 2
    assert snap.excluded_count == 1
    assert len(snap.items) == 2
    assert snap.items[0].rank == 1
    assert snap.items[0].analysis_id == "R1"
    assert snap.items[1].rank == 2
    assert snap.items[1].analysis_id == "R2"

    # Retrieve snapshot by ID
    retrieved = service.get_snapshot(snap.snapshot_id)
    assert retrieved is not None
    assert retrieved.snapshot_id == snap.snapshot_id
    assert retrieved.total_eligible_count == 2
    assert len(retrieved.items) == 2

    # List snapshots
    s_list = service.list_snapshots()
    assert s_list.total >= 1
    assert s_list.snapshots[0].snapshot_id == snap.snapshot_id
