"""Local embedding service providing deterministic dense vector generation."""
import hashlib
import math
import socket
from typing import List, Optional
from urllib.parse import urlparse
import httpx
import numpy as np

from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()


def _is_service_port_open(url: str, timeout: float = 0.2) -> bool:
    """Rapid non-blocking port probe to avoid long HTTP connection hangs when service is offline."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        if host == "localhost":
            host = "127.0.0.1"
        port = parsed.port or 11434
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        return True
    except Exception:
        return False


class LocalEmbeddingService:
    """Provides local dense vector embeddings for RAG retrieval."""

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.embedding_model
        self.ollama_base_url = settings.ollama_base_url
        self.embedding_dimension = 384
        self._ollama_checked = False
        self._ollama_online = False

    def check_availability(self) -> bool:
        """Checks if local embedding service or Ollama embedding endpoint is available."""
        if not self._ollama_checked:
            if not _is_service_port_open(self.ollama_base_url):
                self._ollama_online = False
            else:
                try:
                    with httpx.Client(timeout=1.0) as client:
                        resp = client.get(f"{self.ollama_base_url}/api/tags")
                        if resp.status_code == 200:
                            models = [m.get("name", "") for m in resp.json().get("models", [])]
                            base_name = self.model_name.split(":")[0]
                            self._ollama_online = any(base_name in m for m in models)
                        else:
                            self._ollama_online = False
                except Exception:
                    self._ollama_online = False
            self._ollama_checked = True

        return True  # Fallback dense engine is always available

    def _is_ollama_reachable(self) -> bool:
        if not self._ollama_checked:
            self.check_availability()
        return self._ollama_online

    def _generate_dense_fallback(self, text: str) -> List[float]:
        """
        Generates a 384-dimensional normalized dense vector using deterministic token hashing.
        Guarantees reproducible vector arithmetic and cosine similarity without external dependencies.
        """
        if not text or not text.strip():
            return [0.0] * self.embedding_dimension

        vec = np.zeros(self.embedding_dimension, dtype=np.float32)
        words = text.lower().strip().split()

        for word in words:
            # Word-level hash features
            h = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
            idx1 = h % self.embedding_dimension
            vec[idx1] += 1.0

            # Character 3-gram features
            if len(word) >= 3:
                for i in range(len(word) - 2):
                    trigram = word[i:i+3]
                    th = int(hashlib.md5(trigram.encode("utf-8")).hexdigest(), 16)
                    idx2 = th % self.embedding_dimension
                    vec[idx2] += 0.5

        # L2 Normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return vec.tolist()

    def embed_text(self, text: str) -> List[float]:
        """Embeds a single text passage."""
        # Try Ollama endpoint if reachable
        if self._is_ollama_reachable():
            try:
                with httpx.Client(timeout=3.0) as client:
                    resp = client.post(
                        f"{self.ollama_base_url}/api/embeddings",
                        json={"model": self.model_name, "prompt": text},
                    )
                    if resp.status_code == 200:
                        emb = resp.json().get("embedding")
                        if emb and isinstance(emb, list):
                            return emb
            except Exception:
                pass

        return self._generate_dense_fallback(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch embedding of text passages."""
        return [self.embed_text(t) for t in texts]
