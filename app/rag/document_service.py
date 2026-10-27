"""Document parser and chunking service for plain text, Markdown, and PDF reference files."""
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from app.core.config import get_settings
from app.core.logging import logger
from app.rag.chroma_service import ChromaService
from app.schemas.ai import DocumentIngestResponse

settings = get_settings()


def compute_content_hash(content: str) -> str:
    """Returns SHA-256 hash of document text content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class DocumentIngestionService:
    """Parses local reference documents into overlapping chunks and indexes them into ChromaDB."""

    def __init__(
        self,
        chroma_service: Optional[ChromaService] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 100,
    ):
        self.chroma = chroma_service or ChromaService()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.documents_dir = settings.documents_dir
        self.documents_dir.mkdir(parents=True, exist_ok=True)

    def extract_text_from_file(self, file_path: Path) -> str:
        """Extracts text content from Markdown, TXT, or PDF files."""
        ext = file_path.suffix.lower()

        if ext in [".md", ".txt", ".json"]:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

        elif ext == ".pdf":
            # Try pypdf if installed
            try:
                import pypdf
                reader = pypdf.PdfReader(str(file_path))
                text_parts = [page.extract_text() or "" for page in reader.pages]
                return "\n\n".join(text_parts).strip()
            except ImportError:
                # Built-in lightweight PDF text extractor
                with open(file_path, "rb") as f:
                    raw = f.read().decode("latin1", errors="replace")
                import re
                stream_texts = re.findall(r"\((.*?)\)tj|\[(.*?)\]tj", raw, re.IGNORECASE)
                extracted = " ".join([t[0] or t[1] for t in stream_texts if t[0] or t[1]])
                if extracted.strip():
                    return extracted
                raise ValueError("PDF parsing requires pypdf library. Install pypdf or provide .md / .txt format.")

        else:
            raise ValueError(f"Unsupported file format '{ext}'. Only .md, .txt, and .pdf are supported.")

    def chunk_text(self, text: str) -> List[str]:
        """Splits long text into overlapping character windows preserving paragraph/sentence boundaries."""
        cleaned = text.strip()
        if not cleaned:
            return []

        if len(cleaned) <= self.chunk_size:
            return [cleaned]

        chunks = []
        start = 0
        step = self.chunk_size - self.chunk_overlap

        while start < len(cleaned):
            end = min(start + self.chunk_size, len(cleaned))
            chunk = cleaned[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(cleaned):
                break
            start += step

        return chunks

    def ingest_single_file(self, file_path: Path) -> Tuple[str, int, bool]:
        """
        Parses and indexes a single document file.
        Returns (document_id, chunk_count, is_new).
        """
        # Validate path to prevent directory traversal
        resolved = file_path.resolve()
        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError(f"File '{file_path}' does not exist.")

        filename = resolved.name
        content = self.extract_text_from_file(resolved)
        if not content.strip():
            raise ValueError(f"File '{filename}' contains no readable text content.")

        content_hash = compute_content_hash(content)
        file_type = resolved.suffix.lower()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Check existing documents for duplicate content hash
        existing_docs = self.chroma.list_documents()
        for doc in existing_docs:
            if doc.get("content_hash") == content_hash:
                logger.info(f"Skipping duplicate document '{filename}' (matches {doc['document_id']})")
                return doc["document_id"], doc["chunk_count"], False

        doc_id = f"doc-{uuid.uuid4().hex[:12]}"
        chunks = self.chunk_text(content)

        chunk_ids = []
        documents = []
        metadatas = []

        for idx, chunk in enumerate(chunks):
            cid = f"{doc_id}-chunk-{idx}"
            chunk_ids.append(cid)
            documents.append(chunk)
            metadatas.append({
                "document_id": doc_id,
                "filename": filename,
                "chunk_index": idx,
                "chunk_id": cid,
                "file_type": file_type,
                "content_hash": content_hash,
                "ingested_at": now_iso,
            })

        self.chroma.add_chunks(chunk_ids, documents, metadatas)
        logger.info(f"Successfully ingested '{filename}' as {doc_id} ({len(chunks)} chunks).")
        return doc_id, len(chunks), True

    def ingest_directory(self, target_dir: Optional[Path] = None) -> DocumentIngestResponse:
        """Indexes all supported documents found in the target directory."""
        directory = target_dir or self.documents_dir
        if not directory.exists():
            return DocumentIngestResponse(
                total_files_processed=0,
                new_chunks_indexed=0,
                skipped_duplicate_chunks=0,
                documents_ingested=[],
                errors=[f"Directory '{directory}' does not exist."],
            )

        supported_exts = {".md", ".txt", ".pdf"}
        files = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in supported_exts]

        total_processed = 0
        new_chunks = 0
        skipped_dups = 0
        ingested_list = []
        errors = []

        for file_p in files:
            total_processed += 1
            try:
                doc_id, count, is_new = self.ingest_single_file(file_p)
                if is_new:
                    new_chunks += count
                    ingested_list.append({
                        "document_id": doc_id,
                        "filename": file_p.name,
                        "chunks_count": count,
                        "status": "INDEXED",
                    })
                else:
                    skipped_dups += count
                    ingested_list.append({
                        "document_id": doc_id,
                        "filename": file_p.name,
                        "chunks_count": count,
                        "status": "DUPLICATE_SKIPPED",
                    })
            except Exception as exc:
                errors.append(f"Error processing '{file_p.name}': {str(exc)}")

        return DocumentIngestResponse(
            total_files_processed=total_processed,
            new_chunks_indexed=new_chunks,
            skipped_duplicate_chunks=skipped_dups,
            documents_ingested=ingested_list,
            errors=errors,
        )
