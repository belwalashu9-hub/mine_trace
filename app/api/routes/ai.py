"""FastAPI router for Phase 6 Local RAG and Explainable AI."""
import math
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.rag.service import RAGService
from app.rag.chroma_service import ChromaService
from app.rag.document_service import DocumentIngestionService
from app.audit.service import AuditEventService
from app.rag.rules import EVENT_DOCUMENT_INGESTED, EVENT_DOCUMENT_DELETED
from app.schemas.ai import (
    ExplainRequest,
    ExplainResponse,
    DocumentIngestResponse,
    IndexedDocumentListResponse,
    IndexedDocumentSummary,
    AIStatusResponse,
)

router = APIRouter(prefix="/api/v1/ai", tags=["Local RAG & Explainable AI"])


@router.post(
    "/explain",
    response_model=ExplainResponse,
    summary="Generate evidence-grounded AI explanation for a risk query",
    description=(
        "Retrieves authoritative structured facts from SQLite and relevant reference document passages "
        "from ChromaDB to generate an evidence-grounded explanation via local Ollama or a deterministic template. "
        "Includes claim verification and disclaimers."
    ),
)
def explain_risk_query(
    payload: ExplainRequest,
    db: Session = Depends(get_db),
):
    service = RAGService(db)
    return service.explain(payload)


@router.post(
    "/documents/ingest",
    response_model=DocumentIngestResponse,
    summary="Ingest local reference documents into vector storage",
    description=(
        "Scans the configured documents directory for Markdown, TXT, and PDF files, "
        "chunks text with overlap, computes SHA-256 deduplication hashes, and indexes into ChromaDB."
    ),
)
def ingest_reference_documents(
    db: Session = Depends(get_db),
):
    chroma = ChromaService()
    doc_service = DocumentIngestionService(chroma)
    result = doc_service.ingest_directory()

    # Log audit event
    try:
        audit = AuditEventService(db)
        audit.record_event(
            event_type=EVENT_DOCUMENT_INGESTED,
            related_record_id=f"FILES-{result.total_files_processed}",
            operation_status="SUCCESS" if not result.errors else "WARNING",
            metadata={
                "files_processed": result.total_files_processed,
                "new_chunks": result.new_chunks_indexed,
                "duplicates_skipped": result.skipped_duplicate_chunks,
            },
        )
    except Exception:
        pass

    return result


@router.get(
    "/status",
    response_model=AIStatusResponse,
    summary="Check local RAG, ChromaDB, and Ollama service health",
    description="Returns connectivity and availability status across ChromaDB, local embeddings, and Ollama.",
)
def get_ai_service_status(
    db: Session = Depends(get_db),
):
    service = RAGService(db)
    return service.get_service_status()


@router.get(
    "/documents",
    response_model=IndexedDocumentListResponse,
    summary="List indexed reference documents",
    description="Returns a paginated list of documents currently stored in the vector index with metadata.",
)
def list_indexed_documents(
    page: int = Query(default=1, ge=1, description="Page number."),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page."),
):
    chroma = ChromaService()
    all_docs = chroma.list_documents()

    total = len(all_docs)
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    offset = (page - 1) * page_size
    sliced = all_docs[offset:offset + page_size]

    summaries = [
        IndexedDocumentSummary(
            document_id=d["document_id"],
            filename=d["filename"],
            chunk_count=d["chunk_count"],
            ingested_at=d.get("ingested_at"),
            content_hash=d.get("content_hash"),
            file_type=d.get("file_type"),
        )
        for d in sliced
    ]

    return IndexedDocumentListResponse(
        total=total,
        page=page,
        page_size=page_size,
        documents=summaries,
    )


@router.delete(
    "/documents/{document_id}",
    summary="Delete an indexed document from vector storage",
    description="Removes a document and all its chunks from the vector index safely without modifying SQLite trade records.",
)
def delete_indexed_document(
    document_id: str,
    db: Session = Depends(get_db),
):
    chroma = ChromaService()
    deleted = chroma.delete_document(document_id.strip())
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Indexed document with ID '{document_id}' was not found.",
        )

    # Log audit event
    try:
        audit = AuditEventService(db)
        audit.record_event(
            event_type=EVENT_DOCUMENT_DELETED,
            related_record_id=document_id.strip(),
            operation_status="SUCCESS",
        )
    except Exception:
        pass

    return {
        "status": "SUCCESS",
        "message": f"Document '{document_id}' and all associated chunks were successfully deleted from vector index.",
    }
