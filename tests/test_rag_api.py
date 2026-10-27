"""Integration tests for Phase 6 Local RAG and Explainable AI API routes."""
from datetime import datetime, timezone
import json
import pytest

from app.database.models import RiskAnalysis, RiskRuleResult, NormalizedTradeRecord


def seed_analysis(db, analysis_id: str = "API-RAG-1"):
    trade = NormalizedTradeRecord(
        commodity_code="283691",
        commodity_description="Lithium carbonate",
        mineral_type="Lithium carbonate",
        reporter_country_code="CHL",
        reporter_country_name="Chile",
        partner_country_code="USA",
        partner_country_name="United States",
        period="2023",
        period_year=2023,
        flow_type="EXPORT",
        trade_value_usd=800000.0,
        net_weight_kg=40000.0,
        record_hash=f"hash-{analysis_id}",
        retrieval_timestamp=datetime.now(timezone.utc),
    )
    db.add(trade)
    db.commit()

    analysis = RiskAnalysis(
        analysis_id=analysis_id,
        trade_record_id=trade.id,
        commodity_code="283691",
        mineral_type="Lithium carbonate",
        reporter_country_code="CHL",
        partner_country_code="USA",
        period="2023",
        combined_anomaly_score=50.0,
        score_completeness="COMPLETE",
        evaluated_rules=json.dumps(["R1", "R2", "R3", "R4", "R5"]),
        insufficient_rules=json.dumps([]),
        flagged_rules=json.dumps(["R1", "R2"]),
        sanctions_status="NO_IDENTIFIED_MATCH",
        classification="RED",
        flag_status="FLAGGED",
        classification_explanation="Elevated multi-rule risk.",
        created_at=datetime.now(timezone.utc),
    )
    db.add(analysis)

    r1 = RiskRuleResult(
        analysis_id=analysis_id,
        rule_id="R1",
        rule_name="Mirror Trade Gap",
        rule_version="1.0",
        weight=30,
        outcome="FLAG",
        threshold="> 30.0%",
        formula="abs(export_value - import_value) / max(export_value, import_value) * 100",
        calculated_value=40.0,
        input_values=json.dumps({"export_value": 100000.0, "import_value": 60000.0}),
        explanation="Export-import mirror gap 40.0% is flagged.",
    )
    db.add(r1)
    db.commit()
    return analysis


@pytest.mark.asyncio
async def test_get_ai_status_endpoint(async_client):
    """GET /api/v1/ai/status returns complete RAG, ChromaDB, and model health."""
    resp = await async_client.get("/api/v1/ai/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["rag_service_available"] is True
    assert data["chromadb_available"] is True
    assert data["offline_mode"] is True
    assert "embedding_model" in data
    assert "ollama_model" in data


@pytest.mark.asyncio
async def test_documents_ingest_and_list_workflow(async_client):
    """POST /api/v1/ai/documents/ingest indexes local reference documents."""
    ingest_resp = await async_client.post("/api/v1/ai/documents/ingest")
    assert ingest_resp.status_code == 200
    ingest_data = ingest_resp.json()

    assert ingest_data["total_files_processed"] >= 1

    # List documents
    list_resp = await async_client.get("/api/v1/ai/documents")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    assert len(list_data["documents"]) >= 1

    doc_id = list_data["documents"][0]["document_id"]

    # Delete document
    del_resp = await async_client.delete(f"/api/v1/ai/documents/{doc_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_explain_specific_analysis_endpoint(async_client, test_db):
    """POST /api/v1/ai/explain with analysis_id returns evidence-grounded explanation."""
    seed_analysis(test_db, "API-EXPLAIN-1")

    payload = {
        "question": "Why is this lithium transaction classified as RED and what rules triggered?",
        "analysis_id": "API-EXPLAIN-1",
        "use_template_only": True,
    }
    resp = await async_client.post("/api/v1/ai/explain", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["analysis_id"] == "API-EXPLAIN-1"
    assert "RED" in data["answer"]
    assert "50.0" in data["answer"]
    assert "R1" in data["answer"]
    assert len(data["supporting_evidence_ids"]) >= 1
    assert data["validation_status"] in ["VALID", "WARNINGS"]
    assert "disclaimer" in data


@pytest.mark.asyncio
async def test_explain_general_methodology_question(async_client):
    """POST /api/v1/ai/explain without analysis_id answers general methodology queries."""
    payload = {
        "question": "What is the threshold for Rule R1 Mirror Trade Gap?",
        "use_template_only": True,
    }
    resp = await async_client.post("/api/v1/ai/explain", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["analysis_id"] is None
    assert len(data["answer"]) > 20
    assert data["generation_mode"] == "DETERMINISTIC_TEMPLATE"


@pytest.mark.asyncio
async def test_explain_missing_analysis_id_returns_404(async_client):
    """POST /api/v1/ai/explain returns 404 when requested analysis ID does not exist."""
    payload = {
        "question": "Explain this record",
        "analysis_id": "NON-EXISTENT-ANALYSIS-ID",
    }
    resp = await async_client.post("/api/v1/ai/explain", json=payload)
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()
