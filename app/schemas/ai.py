"""Pydantic schemas for Phase 6 Local RAG and Explainable AI."""
from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ConfigDict

AI_EXPLANATION_DISCLAIMER = (
    "AI explanations are generated locally from retrieved empirical trade evidence snapshots "
    "and methodology references. Risk anomaly scores and classifications are indicators of trade divergence "
    "and heuristics, not legal determinations of fraud, wrongdoing, or sanctions evasion."
)


class ExplainRequest(BaseModel):
    """Request payload for evidence-grounded AI explanation."""
    question: str = Field(min_length=3, description="User question or query about trade risk.")
    analysis_id: Optional[str] = Field(default=None, description="Optional UUID of a specific saved RiskAnalysis.")
    top_k: int = Field(default=3, ge=1, le=10, description="Max number of document chunks to retrieve.")
    use_template_only: bool = Field(default=False, description="If True, forces deterministic template explanation.")


class SupportingDocumentChunk(BaseModel):
    """Retrieved reference document chunk providing methodology context."""
    document_id: str
    filename: str
    chunk_id: str
    content: str
    relevance_score: Optional[float] = None


class NumericalClaimValidation(BaseModel):
    """Validation audit of numerical statements made in the explanation."""
    claim: str
    verified: bool
    expected_value: Optional[Any] = None
    notes: str


class ExplainResponse(BaseModel):
    """Comprehensive response containing the grounded explanation, citations, and claim validation."""
    question: str
    analysis_id: Optional[str] = None
    answer: str
    generation_mode: str = Field(description="'LOCAL_LLM' or 'DETERMINISTIC_TEMPLATE'")
    model_name: Optional[str] = None
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    supporting_document_chunks: List[SupportingDocumentChunk] = Field(default_factory=list)
    numerical_claims: List[NumericalClaimValidation] = Field(default_factory=list)
    validation_status: str = Field(description="'VALID', 'INVALID', or 'WARNINGS'")
    warnings: List[str] = Field(default_factory=list)
    disclaimer: str = AI_EXPLANATION_DISCLAIMER


class DocumentIngestResponse(BaseModel):
    """Response returned after processing and indexing local reference documents."""
    total_files_processed: int
    new_chunks_indexed: int
    skipped_duplicate_chunks: int
    documents_ingested: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class IndexedDocumentSummary(BaseModel):
    """Metadata summary of an indexed local reference document."""
    document_id: str
    filename: str
    chunk_count: int
    ingested_at: Optional[datetime] = None
    content_hash: Optional[str] = None
    file_type: Optional[str] = None


class IndexedDocumentListResponse(BaseModel):
    """Paginated list of indexed reference documents."""
    total: int
    page: int
    page_size: int
    documents: List[IndexedDocumentSummary] = Field(default_factory=list)


class AIStatusResponse(BaseModel):
    """Comprehensive status check for local RAG, ChromaDB, embeddings, and Ollama."""
    rag_service_available: bool
    chromadb_available: bool
    chromadb_dir: str
    indexed_documents_count: int
    indexed_chunks_count: int
    embedding_model: str
    embedding_model_available: bool
    ollama_reachable: bool
    ollama_base_url: str
    ollama_model: str
    ollama_model_available: bool
    offline_mode: bool = True
    warnings: List[str] = Field(default_factory=list)
    setup_instructions: Optional[str] = None
