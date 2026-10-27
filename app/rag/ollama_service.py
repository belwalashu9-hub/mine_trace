"""Ollama local language model client and deterministic explanation synthesizer."""
import socket
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse
import httpx

from app.core.config import get_settings
from app.core.logging import logger
from app.rag.rules import RAG_SYSTEM_PROMPT, DETERMINISTIC_FALLBACK_NOTICE

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


class OllamaService:
    """Interacts with local Ollama service and provides deterministic fallback explanations."""

    def __init__(self, base_url: Optional[str] = None, model_name: Optional[str] = None):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model_name = model_name or settings.ollama_model
        self.timeout = settings.rag_timeout_seconds

    def check_availability(self) -> Tuple[bool, bool, List[str]]:
        """
        Returns (ollama_reachable, model_available, available_models).
        """
        if not _is_service_port_open(self.base_url):
            return False, False, []

        try:
            with httpx.Client(timeout=1.5) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    models = [m.get("name", "") for m in resp.json().get("models", [])]
                    base_req = self.model_name.split(":")[0]
                    model_found = any(self.model_name == m or base_req in m for m in models)
                    return True, model_found, models
                return True, False, []
        except Exception:
            return False, False, []

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """Calls local Ollama API to generate text."""
        if not _is_service_port_open(self.base_url):
            return None
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "system": system_prompt or RAG_SYSTEM_PROMPT,
            "stream": False,
            "options": {
                "temperature": 0.1,  # Low temperature for factual fidelity
                "top_p": 0.9,
            },
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.base_url}/api/generate", json=payload)
                if resp.status_code == 200:
                    text = resp.json().get("response")
                    if text and text.strip():
                        return text.strip()
        except Exception as exc:
            logger.info(f"Local Ollama call failed or timed out ({exc}). Using deterministic fallback.")

        return None

    def generate_deterministic_explanation(
        self,
        question: str,
        structured_facts: Optional[Dict[str, Any]],
        retrieved_chunks: List[Dict[str, Any]],
    ) -> str:
        """
        Synthesizes a structured, evidence-grounded explanation without relying on external models.
        Strictly adheres to recorded trade facts, rule inputs, calculations, and methodology citations.
        """
        paragraphs = []

        if structured_facts:
            a_id = structured_facts["analysis_id"]
            e_id = structured_facts["evidence_id"]
            t = structured_facts["trade"]
            s = structured_facts["scoring"]
            c = structured_facts["classification"]
            rules = structured_facts["rules"]

            paragraphs.append(
                f"### Supply Chain Risk Assessment for Analysis {a_id}\n"
                f"This analysis evaluates trade flow data for **{t['mineral_type']}** (HS code `{t['commodity_code']}`) "
                f"between reporting country **{t['reporter_country_code']}** and partner **{t['partner_country_code']}** "
                f"for reporting period **{t['period']}** (Evidence Snapshot `{e_id}`)."
            )

            # Score & Classification
            paragraphs.append(
                f"**Overall Assessment & Classification:**\n"
                f"- **Anomaly Score**: **{s['combined_anomaly_score']:.1f} / 100.0** (Completeness status: `{s['score_completeness']}`).\n"
                f"- **Classification**: **{c['classification']}** (Anomaly Flag Status: `{c['flag_status']}`).\n"
                f"- **Sanctions Status**: `{s['sanctions_status']}` (Rule R5 screening)."
            )

            # Triggered Rules
            flagged = [r for r in rules if r["outcome"] == "FLAG"]
            not_flagged = [r for r in rules if r["outcome"] == "NOT_FLAGGED"]
            insufficient = [r for r in rules if r["outcome"] == "INSUFFICIENT_DATA"]

            if flagged:
                rule_desc = ["**Triggered Risk Anomalies:**"]
                for r in flagged:
                    calc_str = f"calculated at {r['calculated_value']:.2f}%" if r["calculated_value"] is not None else "evaluated"
                    rule_desc.append(
                        f"- **{r['rule_id']} ({r['rule_name']})**: {calc_str}, exceeding the threshold of `{r['threshold']}`. "
                        f"{r['explanation']}"
                    )
                paragraphs.append("\n".join(rule_desc))

            if not_flagged:
                nf_desc = ["**Evaluated Rules Within Normal Bounds:**"]
                for r in not_flagged:
                    calc_str = f"calculated at {r['calculated_value']:.2f}%" if r["calculated_value"] is not None else "within limits"
                    nf_desc.append(f"- **{r['rule_id']} ({r['rule_name']})**: {calc_str} (threshold `{r['threshold']}`).")
                paragraphs.append("\n".join(nf_desc))

            if insufficient:
                ins_desc = ["**Data Sufficiency Limitations:**"]
                for r in insufficient:
                    ins_desc.append(f"- **{r['rule_id']} ({r['rule_name']})**: Insufficient data available to evaluate rule.")
                paragraphs.append("\n".join(ins_desc))

        else:
            paragraphs.append(
                f"### MineTrace Methodology & Reference Intelligence\n"
                f"Addressing your inquiry regarding: *\"{question}\"*."
            )

        # Append relevant methodology passages from retrieved documents
        if retrieved_chunks:
            doc_lines = ["\n**Relevant Methodology Citations:**"]
            for idx, ch in enumerate(retrieved_chunks[:2]):
                fn = ch["metadata"].get("filename", "Reference Document")
                content = ch["content"].strip().replace("\n", " ")
                if len(content) > 200:
                    content = content[:200] + "..."
                doc_lines.append(f"> [{idx+1}] *{fn}*: \"{content}\"")
            paragraphs.append("\n".join(doc_lines))

        paragraphs.append(
            f"\n*{DETERMINISTIC_FALLBACK_NOTICE}*"
        )

        return "\n\n".join(paragraphs)
