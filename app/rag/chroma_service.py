"""ChromaDB vector store adapter with persistent local storage and fallback support."""
import json
import math
from pathlib import Path
from typing import Dict, Any, List, Optional
import numpy as np

from app.core.config import get_settings
from app.core.logging import logger
from app.rag.embedding_service import LocalEmbeddingService

settings = get_settings()

try:
    import chromadb
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False


class ChromaService:
    """Manages persistent vector collection for methodology and reference documents."""

    def __init__(self, persist_dir: Optional[Path] = None):
        self.persist_dir = persist_dir or settings.chroma_persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = "minetrace_reference_docs"
        self.embedding_service = LocalEmbeddingService()
        self._native_client = None
        self._native_collection = None
        self._init_backend()

    def _init_backend(self) -> None:
        """Initializes native ChromaDB if installed, otherwise uses local persistent JSON index."""
        if HAS_CHROMADB:
            try:
                self._native_client = chromadb.PersistentClient(path=str(self.persist_dir))
                self._native_collection = self._native_client.get_or_create_collection(
                    name=self.collection_name,
                    metadata={"description": "MineTrace reference documents vector index"},
                )
                logger.info(f"Initialized native ChromaDB persistent storage at {self.persist_dir}")
                return
            except Exception as exc:
                logger.warning(f"Failed to initialize native ChromaDB client ({exc}), falling back to local persistent store.")

        # Fallback local index file
        self.index_file = self.persist_dir / "vector_index.json"
        if not self.index_file.exists():
            self._save_local_index({"chunks": {}, "documents": {}})

    def is_native_available(self) -> bool:
        """Returns True if native ChromaDB is initialized."""
        return HAS_CHROMADB and self._native_collection is not None

    def _load_local_index(self) -> Dict[str, Any]:
        """Loads persistent JSON index file."""
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"chunks": {}, "documents": {}}

    def _save_local_index(self, data: Dict[str, Any]) -> None:
        """Persists local index to disk."""
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def add_chunks(
        self,
        chunk_ids: List[str],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        embeddings: Optional[List[List[float]]] = None,
    ) -> int:
        """Adds text chunks with embeddings and metadata into persistent storage."""
        if not chunk_ids:
            return 0

        if embeddings is None:
            embeddings = self.embedding_service.embed_batch(documents)

        if self.is_native_available():
            try:
                self._native_collection.upsert(
                    ids=chunk_ids,
                    documents=documents,
                    metadatas=metadatas,
                    embeddings=embeddings,
                )
                return len(chunk_ids)
            except Exception as exc:
                logger.warning(f"Native ChromaDB upsert failed ({exc}), storing in local fallback.")

        # Local persistent fallback
        data = self._load_local_index()
        added_count = 0

        for cid, doc, meta, emb in zip(chunk_ids, documents, metadatas, embeddings):
            data["chunks"][cid] = {
                "id": cid,
                "document": doc,
                "metadata": meta,
                "embedding": emb,
            }
            doc_id = meta.get("document_id")
            if doc_id:
                if doc_id not in data["documents"]:
                    data["documents"][doc_id] = {
                        "document_id": doc_id,
                        "filename": meta.get("filename", "unknown"),
                        "chunk_ids": [],
                        "ingested_at": meta.get("ingested_at"),
                        "content_hash": meta.get("content_hash"),
                        "file_type": meta.get("file_type"),
                    }
                if cid not in data["documents"][doc_id]["chunk_ids"]:
                    data["documents"][doc_id]["chunk_ids"].append(cid)
            added_count += 1

        self._save_local_index(data)
        return added_count

    def query_similar(
        self,
        query_text: str,
        top_k: int = 3,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Finds most relevant document chunks for query text."""
        query_embedding = self.embedding_service.embed_text(query_text)

        if self.is_native_available():
            try:
                chroma_where = filter_metadata if filter_metadata else None
                results = self._native_collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                    where=chroma_where,
                )
                hits = []
                if results and results.get("ids") and results["ids"][0]:
                    ids = results["ids"][0]
                    docs = results["documents"][0] if results.get("documents") else []
                    metas = results["metadatas"][0] if results.get("metadatas") else []
                    distances = results["distances"][0] if results.get("distances") else []

                    for cid, doc, meta, dist in zip(ids, docs, metas, distances):
                        # Convert L2 distance or cosine distance to similarity score
                        score = max(0.0, 1.0 - (dist / 2.0)) if dist is not None else 1.0
                        hits.append({
                            "chunk_id": cid,
                            "content": doc,
                            "metadata": meta,
                            "similarity_score": round(score, 4),
                        })
                return hits
            except Exception as exc:
                logger.warning(f"Native ChromaDB query failed ({exc}), querying local fallback.")

        # Local persistent vector similarity
        data = self._load_local_index()
        chunks = data.get("chunks", {})
        if not chunks:
            return []

        q_vec = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)

        scored = []
        for cid, item in chunks.items():
            meta = item.get("metadata", {})
            # Check metadata filter
            if filter_metadata:
                match = all(meta.get(k) == v for k, v in filter_metadata.items())
                if not match:
                    continue

            d_vec = np.array(item["embedding"], dtype=np.float32)
            d_norm = np.linalg.norm(d_vec)

            sim = 0.0
            if q_norm > 0 and d_norm > 0:
                sim = float(np.dot(q_vec, d_vec) / (q_norm * d_norm))

            scored.append({
                "chunk_id": cid,
                "content": item["document"],
                "metadata": meta,
                "similarity_score": round(max(0.0, sim), 4),
            })

        scored.sort(key=lambda x: x["similarity_score"], reverse=True)
        return scored[:top_k]

    def list_documents(self) -> List[Dict[str, Any]]:
        """Returns metadata summaries for all indexed documents."""
        data = self._load_local_index()
        docs = data.get("documents", {})
        results = []
        for doc_id, doc_info in docs.items():
            results.append({
                "document_id": doc_id,
                "filename": doc_info.get("filename"),
                "chunk_count": len(doc_info.get("chunk_ids", [])),
                "ingested_at": doc_info.get("ingested_at"),
                "content_hash": doc_info.get("content_hash"),
                "file_type": doc_info.get("file_type"),
            })
        return results

    def delete_document(self, document_id: str) -> bool:
        """Removes a document and all its chunks from the vector store."""
        deleted = False

        if self.is_native_available():
            try:
                self._native_collection.delete(where={"document_id": document_id})
                deleted = True
            except Exception as exc:
                logger.warning(f"Native ChromaDB deletion failed: {exc}")

        data = self._load_local_index()
        doc_info = data.get("documents", {}).pop(document_id, None)
        if doc_info:
            chunk_ids = set(doc_info.get("chunk_ids", []))
            data["chunks"] = {k: v for k, v in data["chunks"].items() if k not in chunk_ids}
            self._save_local_index(data)
            deleted = True

        return deleted

    def get_stats(self) -> Dict[str, Any]:
        """Returns collection size and storage metrics."""
        data = self._load_local_index()
        chunk_count = len(data.get("chunks", {}))
        doc_count = len(data.get("documents", {}))
        return {
            "indexed_documents_count": doc_count,
            "indexed_chunks_count": chunk_count,
            "persist_dir": str(self.persist_dir),
            "native_chromadb_active": self.is_native_available(),
        }
