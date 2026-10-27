"""RAG pipeline coordinating SQLite evidence, ChromaDB retrieval, Ollama, and claim validation."""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.database.models import RiskAnalysis
from app.audit.service import AuditEventService
from app.rag.chroma_service import ChromaService
from app.rag.embedding_service import LocalEmbeddingService
from app.rag.document_service import DocumentIngestionService
from app.rag.evidence_builder import EvidenceBuilder
from app.rag.ollama_service import OllamaService
from app.rag.claim_validator import ClaimValidator
from app.rag.rules import (
    EVENT_RAG_QUERY_EXECUTED,
    RAG_SYSTEM_PROMPT,
    AI_EXPLANATION_DISCLAIMER,
)
from app.schemas.ai import (
    ExplainRequest,
    ExplainResponse,
    SupportingDocumentChunk,
    AIStatusResponse,
)

settings = get_settings()


class RAGService:
    """End-to-end Local RAG and Explainable AI pipeline."""

    def __init__(self, db: Session):
        self.db = db
        self.chroma = ChromaService()
        self.doc_service = DocumentIngestionService(self.chroma)
        self.evidence_builder = EvidenceBuilder(db)
        self.ollama = OllamaService()
        self.validator = ClaimValidator()
        self.audit = AuditEventService(db)

    def explain(self, request: ExplainRequest) -> ExplainResponse:
        """Executes the 10-step evidence-grounded RAG pipeline."""
        structured_facts: Optional[Dict[str, Any]] = None
        evidence_ids: List[str] = []

        # 1. Structured Evidence Retrieval (if analysis_id is provided)
        if request.analysis_id:
            a_id = request.analysis_id.strip()
            analysis = self.evidence_builder.get_analysis(a_id)
            if not analysis:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Target risk analysis '{a_id}' was not found in database.",
                )
            structured_facts = self.evidence_builder.build_structured_context(a_id)
            if structured_facts and "evidence_id" in structured_facts:
                evidence_ids.append(structured_facts["evidence_id"])

        # 2. ChromaDB Semantic Document Retrieval
        doc_chunks = self.chroma.query_similar(query_text=request.question, top_k=request.top_k)

        supporting_chunks = [
            SupportingDocumentChunk(
                document_id=c["metadata"].get("document_id", "unknown"),
                filename=c["metadata"].get("filename", "unknown"),
                chunk_id=c["chunk_id"],
                content=c["content"],
                relevance_score=c.get("similarity_score"),
            )
            for c in doc_chunks
        ]

        # 3. Model Inference or Deterministic Fallback
        answer: Optional[str] = None
        generation_mode = "DETERMINISTIC_TEMPLATE"
        model_name = None

        if not request.use_template_only:
            ollama_reachable, model_avail, _ = self.ollama.check_availability()
            if ollama_reachable and model_avail:
                prompt_parts = []
                if structured_facts:
                    facts_md = self.evidence_builder.format_facts_as_markdown(structured_facts)
                    prompt_parts.append(f"STRUCTURED ANALYSIS FACTS:\n{facts_md}\n")

                if doc_chunks:
                    docs_text = "\n\n".join([f"REFERENCE PASSAGE ({c['chunk_id']}):\n{c['content']}" for c in doc_chunks])
                    prompt_parts.append(f"METHODOLOGY REFERENCE PASSAGES:\n{docs_text}\n")

                prompt_parts.append(f"QUESTION: {request.question}")
                prompt_parts.append("Provide a clear, concise, factual explanation based ONLY on the evidence above:")
                full_prompt = "\n".join(prompt_parts)

                llm_output = self.ollama.generate(prompt=full_prompt, system_prompt=RAG_SYSTEM_PROMPT)
                if llm_output and len(llm_output.strip()) > 20:
                    answer = llm_output.strip()
                    generation_mode = "LOCAL_LLM"
                    model_name = self.ollama.model_name

        if not answer:
            answer = self.ollama.generate_deterministic_explanation(
                question=request.question,
                structured_facts=structured_facts,
                retrieved_chunks=doc_chunks,
            )
            generation_mode = "DETERMINISTIC_TEMPLATE"
            model_name = "Deterministic-Evidence-Synthesizer"

        # 4. Claim Validation
        val_status, claims, val_warnings = self.validator.validate_explanation(
            answer=answer,
            structured_facts=structured_facts,
            retrieved_chunks=doc_chunks,
        )

        # 5. Audit Event Recording
        try:
            self.audit.record_event(
                event_type=EVENT_RAG_QUERY_EXECUTED,
                related_record_id=request.analysis_id or "GENERAL_QUERY",
                operation_status="SUCCESS" if val_status != "INVALID" else "WARNING",
                metadata={
                    "generation_mode": generation_mode,
                    "validation_status": val_status,
                    "top_k_chunks": len(supporting_chunks),
                    "evidence_id": evidence_ids[0] if evidence_ids else None,
                },
            )
        except Exception:
            pass

        return ExplainResponse(
            question=request.question,
            analysis_id=request.analysis_id,
            answer=answer,
            generation_mode=generation_mode,
            model_name=model_name,
            supporting_evidence_ids=evidence_ids,
            supporting_document_chunks=supporting_chunks,
            numerical_claims=claims,
            validation_status=val_status,
            warnings=val_warnings,
            disclaimer=AI_EXPLANATION_DISCLAIMER,
        )

    def get_service_status(self) -> AIStatusResponse:
        """Checks and reports status across ChromaDB, local embeddings, and Ollama."""
        chroma_stats = self.chroma.get_stats()
        emb_avail = self.chroma.embedding_service.check_availability()
        ollama_reachable, model_avail, _ = self.ollama.check_availability()

        warnings = []
        instructions = None

        if not ollama_reachable:
            warnings.append(
                f"Ollama server is not reachable at {self.ollama.base_url}. "
                "RAG will automatically use the built-in deterministic evidence template engine."
            )
            instructions = (
                "To enable local LLM explanations: install Ollama (https://ollama.ai), "
                f"run 'ollama pull {settings.ollama_model}', and ensure 'ollama serve' is running."
            )
        elif not model_avail:
            warnings.append(f"Ollama is running, but model '{settings.ollama_model}' is not pulled.")
            instructions = f"Run 'ollama pull {settings.ollama_model}' in your terminal."

        return AIStatusResponse(
            rag_service_available=True,
            chromadb_available=True,
            chromadb_dir=chroma_stats["persist_dir"],
            indexed_documents_count=chroma_stats["indexed_documents_count"],
            indexed_chunks_count=chroma_stats["indexed_chunks_count"],
            embedding_model=settings.embedding_model,
            embedding_model_available=emb_avail,
            ollama_reachable=ollama_reachable,
            ollama_base_url=settings.ollama_base_url,
            ollama_model=settings.ollama_model,
            ollama_model_available=model_avail,
            offline_mode=True,
            warnings=warnings,
            setup_instructions=instructions,
        )
