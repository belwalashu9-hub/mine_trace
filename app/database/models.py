"""SQLAlchemy ORM models for MineTrace."""
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.database.connection import Base


def utc_now() -> datetime:
    """Returns current UTC datetime."""
    return datetime.now(timezone.utc)


class DataSourceMetadata(Base):
    """Tracks metadata and freshness for external data sources."""
    __tablename__ = "data_source_metadata"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    source_name = Column(String(64), unique=True, nullable=False, index=True)
    source_url = Column(String(512), nullable=False)
    description = Column(String(255), nullable=True)
    last_successful_retrieval = Column(DateTime, nullable=True)
    last_attempt_timestamp = Column(DateTime, nullable=True)
    last_status = Column(String(32), default="NEVER_RUN", nullable=False)
    total_records_ingested = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class IngestionRun(Base):
    """Audit log of every ingestion run."""
    __tablename__ = "ingestion_runs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    source_name = Column(String(64), nullable=False, index=True)
    run_type = Column(String(32), default="MANUAL", nullable=False)  # MANUAL, API, FIXTURE
    status = Column(String(32), default="RUNNING", nullable=False)  # RUNNING, COMPLETED, FAILED, PARTIAL
    started_at = Column(DateTime, default=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    raw_records_count = Column(Integer, default=0, nullable=False)
    clean_records_count = Column(Integer, default=0, nullable=False)
    error_count = Column(Integer, default=0, nullable=False)
    warning_count = Column(Integer, default=0, nullable=False)
    parameters = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Relationships
    raw_trade_records = relationship("RawTradeRecord", back_populates="ingestion_run", cascade="all, delete-orphan")
    quality_issues = relationship("DataQualityIssue", back_populates="ingestion_run", cascade="all, delete-orphan")


class RawTradeRecord(Base):
    """Raw, unaltered source records from UN Comtrade."""
    __tablename__ = "raw_trade_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ingestion_run_id = Column(Integer, ForeignKey("ingestion_runs.id"), nullable=True, index=True)
    source_record_id = Column(String(128), nullable=True, index=True)
    commodity_code = Column(String(32), nullable=True, index=True)
    period = Column(String(32), nullable=True, index=True)
    reporter_code = Column(String(32), nullable=True)
    partner_code = Column(String(32), nullable=True)
    raw_payload = Column(Text, nullable=False)  # Full JSON string of original source payload
    retrieval_timestamp = Column(DateTime, default=utc_now, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    ingestion_run = relationship("IngestionRun", back_populates="raw_trade_records")
    normalized_record = relationship("NormalizedTradeRecord", back_populates="raw_record", uselist=False)


class NormalizedTradeRecord(Base):
    """Cleaned, validated, and normalized trade records."""
    __tablename__ = "normalized_trade_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    raw_record_id = Column(Integer, ForeignKey("raw_trade_records.id"), nullable=True, unique=True)
    ingestion_run_id = Column(Integer, ForeignKey("ingestion_runs.id"), nullable=True, index=True)
    
    # Preserved source identifier
    source_record_id = Column(String(128), nullable=True, index=True)
    
    # Deduplication hash: SHA256 of canonical business keys
    record_hash = Column(String(64), unique=True, nullable=False, index=True)
    
    # Trade specifics
    commodity_code = Column(String(32), nullable=False, index=True)
    commodity_description = Column(String(255), nullable=True)
    mineral_type = Column(String(64), nullable=False, default="Unknown Mineral", index=True)
    
    # Flow: strictly 'IMPORT' or 'EXPORT'
    flow_type = Column(String(16), nullable=False, index=True)
    
    # Countries
    reporter_country_code = Column(String(16), nullable=False, index=True)
    reporter_country_name = Column(String(128), nullable=False, index=True)
    partner_country_code = Column(String(16), nullable=False, index=True)
    partner_country_name = Column(String(128), nullable=False, index=True)
    
    # Dates
    period = Column(String(32), nullable=False, index=True)  # e.g., '2023' or '2023-01'
    period_year = Column(Integer, nullable=False, index=True)
    period_month = Column(Integer, nullable=True)
    
    # Quantities & values: None if missing, NEVER default to 0
    trade_value_usd = Column(Float, nullable=True)
    currency = Column(String(8), default="USD", nullable=False)
    net_weight_kg = Column(Float, nullable=True)
    quantity = Column(Float, nullable=True)
    quantity_unit = Column(String(32), nullable=True)
    
    # Validation flags
    is_valid = Column(Boolean, default=True, nullable=False, index=True)
    has_warnings = Column(Boolean, default=False, nullable=False)
    
    # Timestamps
    retrieval_timestamp = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    raw_record = relationship("RawTradeRecord", back_populates="normalized_record")

    __table_args__ = (
        Index("idx_norm_trade_search", "commodity_code", "period_year", "flow_type"),
        Index("idx_norm_trade_countries", "reporter_country_code", "partner_country_code"),
    )


class OfacSanctionRecord(Base):
    """OFAC Sanctions List record (SDN / Consolidated)."""
    __tablename__ = "ofac_sanctions_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ingestion_run_id = Column(Integer, ForeignKey("ingestion_runs.id"), nullable=True, index=True)
    
    # OFAC unique record ID (e.g. Ent_num)
    source_record_id = Column(String(64), nullable=False, index=True)
    source_name = Column(String(64), default="OFAC_SDN", nullable=False)
    
    # Deduplication hash
    record_hash = Column(String(64), unique=True, nullable=False, index=True)
    
    entity_type = Column(String(32), nullable=True, index=True)  # individual, entity, vessel, aircraft
    primary_name = Column(String(255), nullable=False, index=True)
    aliases = Column(Text, nullable=True)
    programs = Column(String(255), nullable=True, index=True)
    country = Column(String(128), nullable=True, index=True)
    id_numbers = Column(Text, nullable=True)
    remarks = Column(Text, nullable=True)
    
    retrieval_timestamp = Column(DateTime, default=utc_now, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_ofac_name_country", "primary_name", "country"),
    )


class DataQualityIssue(Base):
    """Audit log of validation errors, missing fields, or quality warnings."""
    __tablename__ = "data_quality_issues"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ingestion_run_id = Column(Integer, ForeignKey("ingestion_runs.id"), nullable=True, index=True)
    source_record_id = Column(String(128), nullable=True, index=True)
    table_name = Column(String(64), nullable=False)
    severity = Column(String(16), nullable=False, index=True)  # ERROR, WARNING, INFO
    issue_type = Column(String(64), nullable=False, index=True)
    column_name = Column(String(64), nullable=True)
    raw_value = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    ingestion_run = relationship("IngestionRun", back_populates="quality_issues")


class RiskAnalysis(Base):
    """Stores the aggregated risk assessment run for a trade transaction or corridor."""
    __tablename__ = "risk_analyses"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    analysis_id = Column(String(36), unique=True, nullable=False, index=True)
    trade_record_id = Column(Integer, ForeignKey("normalized_trade_records.id"), nullable=True, index=True)
    commodity_code = Column(String(32), nullable=False, index=True)
    mineral_type = Column(String(64), nullable=True)
    reporter_country_code = Column(String(16), nullable=False, index=True)
    partner_country_code = Column(String(16), nullable=False, index=True)
    period = Column(String(32), nullable=False, index=True)
    
    combined_anomaly_score = Column(Float, nullable=False)
    score_completeness = Column(String(32), nullable=False, index=True)  # COMPLETE, PARTIAL, UNAVAILABLE
    evaluated_rules = Column(Text, nullable=False)    # JSON string list, e.g. ["R1", "R2"]
    insufficient_rules = Column(Text, nullable=False) # JSON string list
    flagged_rules = Column(Text, nullable=False)      # JSON string list
    
    sanctions_status = Column(String(32), nullable=False, default="UNKNOWN", index=True)
    sanctions_reference = Column(Text, nullable=True)

    # Phase 3: Risk Classification Engine
    classification = Column(String(32), nullable=True, index=True)  # GREEN, AMBER, RED, INSUFFICIENT_DATA
    flag_status = Column(String(32), nullable=True, index=True)     # FLAGGED, NOT_FLAGGED, INSUFFICIENT_DATA
    classification_explanation = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    trade_record = relationship("NormalizedTradeRecord")
    rule_results = relationship("RiskRuleResult", back_populates="analysis", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_risk_commodity_period", "commodity_code", "period"),
        Index("idx_risk_score_comp", "combined_anomaly_score", "score_completeness"),
        Index("idx_risk_classification", "classification", "flag_status"),
    )


class RiskRuleResult(Base):
    """Detailed rule-level evaluation audit record."""
    __tablename__ = "risk_rule_results"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    analysis_id = Column(String(36), ForeignKey("risk_analyses.analysis_id"), nullable=False, index=True)
    rule_id = Column(String(16), nullable=False, index=True)  # R1, R2, R3, R4, R5
    rule_name = Column(String(64), nullable=False)
    rule_version = Column(String(16), default="1.0", nullable=False)
    weight = Column(Integer, default=0, nullable=False)
    outcome = Column(String(32), nullable=False, index=True)  # FLAG, NOT_FLAGGED, INSUFFICIENT_DATA, etc.
    threshold = Column(String(128), nullable=False)
    formula = Column(String(255), nullable=False)
    calculated_value = Column(Float, nullable=True)
    input_values = Column(Text, nullable=False)  # JSON formatted inputs
    explanation = Column(Text, nullable=False)
    warnings = Column(Text, nullable=True)       # JSON formatted warnings
    created_at = Column(DateTime, default=utc_now, nullable=False)

    analysis = relationship("RiskAnalysis", back_populates="rule_results")


class RankingSnapshot(Base):
    """Point-in-time snapshot of trade risk rankings."""
    __tablename__ = "ranking_snapshots"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    snapshot_id = Column(String(36), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=True)
    description = Column(Text, nullable=True)
    policy_version = Column(String(16), default="1.0", nullable=False)
    filters_applied = Column(Text, nullable=True)  # JSON dictionary of filters
    total_eligible_count = Column(Integer, default=0, nullable=False)
    excluded_count = Column(Integer, default=0, nullable=False)
    exclusion_reasons = Column(Text, nullable=True)  # JSON breakdown
    created_at = Column(DateTime, default=utc_now, nullable=False)

    items = relationship("RankingSnapshotItem", back_populates="snapshot", cascade="all, delete-orphan")


class RankingSnapshotItem(Base):
    """Individual ranked item within a RankingSnapshot."""
    __tablename__ = "ranking_snapshot_items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    snapshot_id = Column(String(36), ForeignKey("ranking_snapshots.snapshot_id"), nullable=False, index=True)
    rank = Column(Integer, nullable=False, index=True)
    analysis_id = Column(String(36), ForeignKey("risk_analyses.analysis_id"), nullable=False, index=True)
    anomaly_score = Column(Float, nullable=False)
    classification = Column(String(32), nullable=True)
    flag_status = Column(String(32), nullable=True)
    commodity_code = Column(String(32), nullable=False)
    mineral_type = Column(String(64), nullable=True)
    reporter_country_code = Column(String(16), nullable=False)
    partner_country_code = Column(String(16), nullable=False)
    period = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    snapshot = relationship("RankingSnapshot", back_populates="items")
    analysis = relationship("RiskAnalysis")

    __table_args__ = (
        Index("idx_snapshot_item_rank", "snapshot_id", "rank"),
    )


class EvidenceSnapshot(Base):
    """Immutable evidence snapshot preserving all data inputs, rule outputs, and context for an analysis."""
    __tablename__ = "evidence_snapshots"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    evidence_id = Column(String(36), unique=True, nullable=False, index=True)
    analysis_id = Column(String(36), ForeignKey("risk_analyses.analysis_id"), unique=True, nullable=False, index=True)
    schema_version = Column(String(16), default="1.0", nullable=False)

    # Source dataset and record references
    trade_record_id = Column(Integer, ForeignKey("normalized_trade_records.id"), nullable=True, index=True)
    source_dataset_name = Column(String(64), nullable=False, default="UN Comtrade")
    source_record_id = Column(String(128), nullable=True, index=True)
    source_reference_url = Column(String(512), nullable=True)
    source_retrieval_timestamp = Column(DateTime, nullable=True)
    source_payload_snapshot = Column(Text, nullable=False)  # JSON snapshot of trade record fields

    # Analysis outputs snapshot
    analysis_timestamp = Column(DateTime, nullable=False)
    combined_anomaly_score = Column(Float, nullable=False)
    score_completeness = Column(String(32), nullable=False, index=True)
    evaluated_rules = Column(Text, nullable=False)    # JSON list
    insufficient_rules = Column(Text, nullable=False) # JSON list
    flagged_rules = Column(Text, nullable=False)      # JSON list
    sanctions_status = Column(String(32), default="UNKNOWN", nullable=False)
    sanctions_reference = Column(Text, nullable=True)

    # Phase 3 classification evidence snapshot
    classification = Column(String(32), nullable=True, index=True)
    flag_status = Column(String(32), nullable=True, index=True)
    classification_explanation = Column(Text, nullable=True)
    classification_policy_version = Column(String(16), default="1.0", nullable=False)
    classification_thresholds_applied = Column(Text, nullable=True)  # JSON dictionary

    # Phase 4 ranking context snapshot
    ranking_context = Column(Text, nullable=True)  # JSON dictionary

    # Rule-by-rule evaluations snapshot
    rule_evaluations_snapshot = Column(Text, nullable=False)  # JSON list of rule calculations

    # Data quality warnings
    data_quality_warnings = Column(Text, nullable=True)  # JSON list

    # Validation tracking
    validation_status = Column(String(32), default="UNVALIDATED", nullable=False, index=True)  # VALID, INVALID, WARNINGS, UNVALIDATED
    validation_report = Column(Text, nullable=True)  # JSON dictionary of validation checks
    last_validated_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)

    analysis = relationship("RiskAnalysis", backref="evidence_snapshot")
    trade_record = relationship("NormalizedTradeRecord")


class AuditEvent(Base):
    """Append-only audit log for backend operational events and evidence tracking."""
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    event_id = Column(String(36), unique=True, nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime, default=utc_now, nullable=False, index=True)
    related_record_id = Column(String(128), nullable=True, index=True)
    operation_status = Column(String(32), default="SUCCESS", nullable=False, index=True)  # SUCCESS, FAILED, WARNING
    event_metadata = Column(Text, nullable=True)  # JSON dictionary
    error_details = Column(Text, nullable=True)    # Safe sanitized string, no stack traces
    created_at = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_audit_type_time", "event_type", "timestamp"),
        Index("idx_audit_status_time", "operation_status", "timestamp"),
    )


class GeneratedReport(Base):
    """Metadata record for generated PDF evidence reports."""
    __tablename__ = "generated_reports"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    report_id = Column(String(36), unique=True, nullable=False, index=True)
    analysis_id = Column(String(36), ForeignKey("risk_analyses.analysis_id"), nullable=False, index=True)
    evidence_snapshot_id = Column(String(36), nullable=True, index=True)
    template_version = Column(String(16), default="1.0", nullable=False)
    report_title = Column(String(128), default="Critical Mineral Supply-Chain Risk Assessment", nullable=False)
    file_path = Column(String(512), nullable=False)
    file_size_bytes = Column(Integer, nullable=True)
    content_hash = Column(String(64), nullable=True)  # SHA-256 of generated PDF
    report_status = Column(String(32), default="COMPLETED", nullable=False, index=True)
    has_evidence_snapshot = Column(Boolean, default=True, nullable=False)
    has_validated_ai_explanation = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    metadata_snapshot = Column(Text, nullable=True)  # JSON summary
    created_at = Column(DateTime, default=utc_now, nullable=False, index=True)

    analysis = relationship("RiskAnalysis", backref="generated_reports")

    __table_args__ = (
        Index("idx_reports_analysis_time", "analysis_id", "created_at"),
    )


# =============================================================================
# Model 2: Real-Time Geopolitical Risk Monitoring (GDELT DOC 2.0)
# =============================================================================

class GdeltArticle(Base):
    """
    Stores normalized news articles indexed from GDELT DOC 2.0 API.
    Forms the source repository of geopolitical events for Model 2.
    """
    __tablename__ = "gdelt_articles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    event_id = Column(String(36), unique=True, nullable=False, index=True)
    title = Column(String(512), nullable=True)
    source_url = Column(Text, nullable=False)
    canonical_url = Column(Text, nullable=False, index=True)
    source_domain = Column(String(128), nullable=True, index=True)
    source_country = Column(String(128), nullable=True, index=True)

    # Disruption context fields (populated in Phase 3)
    affected_country = Column(String(128), nullable=True, default=None)
    mineral = Column(String(64), nullable=True, default=None)
    event_type = Column(String(64), nullable=True, default=None)
    event_date = Column(DateTime, nullable=True, default=None)
    publication_date = Column(DateTime, nullable=True, default=None)

    # Ingestion & GDELT timestamps
    gdelt_seen_date = Column(DateTime, nullable=True, index=True)
    retrieved_at = Column(DateTime, nullable=False)
    first_seen_at = Column(DateTime, default=utc_now, nullable=False)
    last_seen_at = Column(DateTime, default=utc_now, nullable=False)

    # Lifecycle & origin
    classification_status = Column(String(32), default="pending", nullable=False, index=True)
    provider = Column(String(32), default="gdelt_doc_2", nullable=False)
    language = Column(String(32), nullable=True)
    raw_metadata = Column(Text, nullable=True)  # JSON-encoded raw provider metadata

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    categories = relationship(
        "GdeltArticleCategory",
        back_populates="article",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_gdelt_seen_status", "gdelt_seen_date", "classification_status"),
        Index("idx_gdelt_source_country", "source_country"),
    )


class GdeltArticleCategory(Base):
    """
    Association table tracking matched geopolitical query categories for an article.
    Allows a single article to be associated with multiple search categories.
    """
    __tablename__ = "gdelt_article_categories"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("gdelt_articles.id"), nullable=False, index=True)
    category = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    article = relationship("GdeltArticle", back_populates="categories")

    __table_args__ = (
        UniqueConstraint("article_id", "category", name="uq_article_category"),
    )


class GdeltIngestionRun(Base):
    """
    Audit log of GDELT news ingestion runs, tracking execution metrics,
    query parameters, and error statuses.
    """
    __tablename__ = "gdelt_ingestion_runs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    run_type = Column(String(32), default="LIVE", nullable=False)  # LIVE, FIXTURE
    status = Column(String(32), default="RUNNING", nullable=False)  # RUNNING, COMPLETED, FAILED, PARTIAL
    query_category = Column(String(64), nullable=True)
    query_string = Column(Text, nullable=True)
    lookback_window = Column(String(32), nullable=True)
    started_at = Column(DateTime, default=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    fetched_count = Column(Integer, default=0, nullable=False)
    valid_count = Column(Integer, default=0, nullable=False)
    inserted_count = Column(Integer, default=0, nullable=False)
    updated_count = Column(Integer, default=0, nullable=False)
    duplicate_count = Column(Integer, default=0, nullable=False)
    failed_count = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_gdelt_run_status", "status", "started_at"),
    )


# =============================================================================
# Model 2 Phase 3: Geopolitical Event Classification & Entity Extraction
# =============================================================================

class GeopoliticalEvent(Base):
    """
    Extracted and classified geopolitical disruption event.
    Represents an actionable, verified incident potentially impacting mineral supply chains.
    """
    __tablename__ = "geopolitical_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    event_id = Column(String(36), unique=True, nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    summary = Column(Text, nullable=True)

    # Location specifics (strict distinction between publisher source and event location)
    affected_country = Column(String(128), nullable=True, index=True)
    region = Column(String(128), nullable=True)
    location_name = Column(String(128), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    has_coordinates = Column(Boolean, default=False, nullable=False)

    # Occurrence vs publication dates
    event_date = Column(DateTime, nullable=True)
    publication_date = Column(DateTime, nullable=True)

    # Mineral Relevance
    mineral_relevance = Column(String(64), default="unknown", nullable=False, index=True)
    relevance_type = Column(String(32), default="UNKNOWN", nullable=False)
    affected_infrastructure = Column(String(255), nullable=True)

    # Analytical confidence and source verification
    extraction_confidence = Column(Float, default=0.5, nullable=False)
    verification_status = Column(String(32), default="REPORTED", nullable=False, index=True)
    source_article_count = Column(Integer, default=1, nullable=False)
    status = Column(String(32), default="ACTIVE", nullable=False, index=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    article_evidence = relationship("EventArticleEvidence", back_populates="event", cascade="all, delete-orphan")
    route_matches = relationship("RouteExposureMatch", back_populates="event", cascade="all, delete-orphan")
    r6_assessments = relationship("R6RiskAssessment", back_populates="event", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_geo_country_type", "affected_country", "event_type"),
        Index("idx_geo_mineral_status", "mineral_relevance", "verification_status"),
    )


class EventArticleEvidence(Base):
    """
    Evidence link associating an extracted GeopoliticalEvent to its supporting GDELT articles.
    """
    __tablename__ = "event_article_evidence"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("geopolitical_events.id"), nullable=False, index=True)
    article_id = Column(Integer, ForeignKey("gdelt_articles.id"), nullable=True, index=True)
    source_url = Column(Text, nullable=False)
    article_title = Column(String(512), nullable=True)
    relevance_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    event = relationship("GeopoliticalEvent", back_populates="article_evidence")
    article = relationship("GdeltArticle")


class EventClassificationHistory(Base):
    """
    Audit log of classification and event extraction batch runs.
    """
    __tablename__ = "event_classification_history"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    run_id = Column(String(36), unique=True, nullable=False, index=True)
    articles_processed = Column(Integer, default=0, nullable=False)
    events_extracted = Column(Integer, default=0, nullable=False)
    events_clustered = Column(Integer, default=0, nullable=False)
    method = Column(String(64), default="DETERMINISTIC_RULES", nullable=False)
    status = Column(String(32), default="COMPLETED", nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


# =============================================================================
# Model 2 Phase 4: Critical Mineral Supply Chain & Physical Transport Routes
# =============================================================================

class TransportRoute(Base):
    """
    Candidate physical critical-mineral transport route corridor.
    Stores GeoJSON geometries, ordered multimodal segments, and primary transit hubs.
    """
    __tablename__ = "transport_routes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    route_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    origin = Column(String(128), nullable=False)
    destination = Column(String(128), nullable=False)
    mineral_relevance = Column(String(64), nullable=False, index=True)
    transport_mode = Column(String(32), default="MULTIMODAL", nullable=False)
    geojson_geometry = Column(Text, nullable=False)
    ordered_segments = Column(Text, nullable=True)
    primary_hubs = Column(Text, nullable=True)
    route_source = Column(String(128), default="MineTrace Supply Chain Atlas", nullable=False)
    data_confidence = Column(String(32), default="DEMO_CANDIDATE", nullable=False)
    designation = Column(String(128), default="CANDIDATE ROUTE — NOT CONFIRMED COMMERCIAL SCHEDULE", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    exposure_matches = relationship("RouteExposureMatch", back_populates="route", cascade="all, delete-orphan")
    r6_assessments = relationship("R6RiskAssessment", back_populates="route", cascade="all, delete-orphan")
    feasibility = relationship("RouteFeasibilityAssessment", back_populates="route", uselist=False, cascade="all, delete-orphan")


class RouteExposureMatch(Base):
    """
    Geographic matching record linking a geopolitical event to an exposed route corridor.
    """
    __tablename__ = "route_exposure_matches"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("geopolitical_events.id"), nullable=False, index=True)
    route_id = Column(Integer, ForeignKey("transport_routes.id"), nullable=False, index=True)
    exposure_type = Column(String(32), nullable=False, index=True)
    distance_km = Column(Float, nullable=True)
    impact_zone_km = Column(Float, default=50.0, nullable=False)
    is_intersecting = Column(Boolean, default=False, nullable=False)
    exposed_segment = Column(String(255), nullable=True)
    calculation_details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    event = relationship("GeopoliticalEvent", back_populates="route_matches")
    route = relationship("TransportRoute", back_populates="exposure_matches")

    __table_args__ = (
        Index("idx_exposure_event_route", "event_id", "route_id"),
    )


# =============================================================================
# Model 2 Phase 5: R6 Geopolitical Risk Engine & Operational Impacts
# =============================================================================

class R6RiskAssessment(Base):
    """
    R6 Near-Real-Time Geopolitical Disruption Exposure assessment record.
    Evaluates multi-factor heuristic exposure and maps potential operational impacts.
    """
    __tablename__ = "r6_risk_assessments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    assessment_id = Column(String(36), unique=True, nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("geopolitical_events.id"), nullable=False, index=True)
    route_id = Column(Integer, ForeignKey("transport_routes.id"), nullable=False, index=True)
    risk_level = Column(String(32), nullable=False, index=True)
    heuristic_score = Column(Float, nullable=False)
    triggering_factors = Column(Text, nullable=False)
    calculation_explanation = Column(Text, nullable=False)
    potential_impacts = Column(Text, nullable=False)
    source_evidence = Column(Text, nullable=False)
    data_confidence = Column(String(32), default="MEDIUM", nullable=False)
    rule_version = Column(String(16), default="1.0", nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    event = relationship("GeopoliticalEvent", back_populates="r6_assessments")
    route = relationship("TransportRoute", back_populates="r6_assessments")

    __table_args__ = (
        Index("idx_r6_route_risk", "route_id", "risk_level"),
    )


# =============================================================================
# Model 2 Phase 6: Route Feasibility & Candidate Alternative Routing
# =============================================================================

class RouteFeasibilityAssessment(Base):
    """
    Operability, legal/regulatory status, and shipment feasibility evaluation for a route.
    Tracks candidate alternative paths via transport graph search.
    """
    __tablename__ = "route_feasibility_assessments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    route_id = Column(Integer, ForeignKey("transport_routes.id"), unique=True, nullable=False, index=True)
    operability_status = Column(String(32), default="NO_IDENTIFIED_ALERT", nullable=False, index=True)
    regulatory_status = Column(String(32), default="NO_IDENTIFIED_RESTRICTION", nullable=False, index=True)
    shipment_feasibility = Column(String(32), default="UNKNOWN", nullable=False, index=True)
    active_alert_count = Column(Integer, default=0, nullable=False)
    highest_risk_level = Column(String(32), default="LOW", nullable=False)
    alternative_route_id = Column(String(64), nullable=True)
    alternative_route_name = Column(String(255), nullable=True)
    alternative_designation = Column(String(128), default="CANDIDATE ALTERNATIVE — NOT CARRIER VERIFIED", nullable=False)
    comparison_summary = Column(Text, nullable=True)
    limitations_disclaimer = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    route = relationship("TransportRoute", back_populates="feasibility")






class RouteOperationalEvidence(Base):
    """Manually reviewed, route-specific authority advisory; never inferred from headlines."""
    __tablename__ = "route_operational_evidence"
    id = Column(Integer, primary_key=True)
    route_id = Column(Integer, ForeignKey("transport_routes.id"), nullable=False, index=True)
    source_url = Column(Text, nullable=False)
    authority = Column(String(255), nullable=False)
    statement = Column(Text, nullable=False)
    status = Column(String(32), nullable=False)
    affected_hubs = Column(Text, nullable=False, default="[]")
    verified_by = Column(String(128), nullable=False)
    valid_until = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

class MonitoringLease(Base):
    __tablename__ = "model2_monitoring_lease"
    name = Column(String(64), primary_key=True)
    owner = Column(String(64), nullable=False)
    expires_at = Column(Float, nullable=False)

class Model2SyncStatus(Base):
    __tablename__ = "model2_sync_status"
    id = Column(Integer, primary_key=True)
    source_mode = Column(String(16), nullable=False)
    status = Column(String(32), nullable=False)
    metrics = Column(Text, nullable=False)
    completed_at = Column(DateTime, default=utc_now, nullable=False, index=True)
