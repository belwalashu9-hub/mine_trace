"""RAG package initialization."""
from app.rag.rules import (
    RAG_POLICY_VERSION,
    EVENT_DOCUMENT_INGESTED,
    EVENT_DOCUMENT_DELETED,
    EVENT_RAG_QUERY_EXECUTED,
    AI_EXPLANATION_DISCLAIMER,
)
from app.rag.service import RAGService
from app.rag.document_service import DocumentIngestionService
from app.rag.chroma_service import ChromaService
from app.rag.embedding_service import LocalEmbeddingService
from app.rag.ollama_service import OllamaService
from app.rag.claim_validator import ClaimValidator

__all__ = [
    "RAG_POLICY_VERSION",
    "EVENT_DOCUMENT_INGESTED",
    "EVENT_DOCUMENT_DELETED",
    "EVENT_RAG_QUERY_EXECUTED",
    "AI_EXPLANATION_DISCLAIMER",
    "RAGService",
    "DocumentIngestionService",
    "ChromaService",
    "LocalEmbeddingService",
    "OllamaService",
    "ClaimValidator",
]
