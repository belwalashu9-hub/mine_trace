"""PDF report generator supporting ReportLab Platypus and pure-Python ISO 32000-1 PDF fallback."""
import io
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

try:
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        PageBreak,
        KeepTogether,
        HRFlowable,
    )
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


class PurePythonPDFBuilder:
    """
    Standard-compliant PDF 1.4 (ISO 32000-1) document generator.
    Produces valid, text-based, multi-page PDFs with headers, footers, tables, and page numbers.
    Runs entirely in pure Python without external binary or network dependencies.
    """

    def __init__(self, page_width: float = 595.28, page_height: float = 841.89):
        # A4: 595.28 x 841.89 points (72 points/inch)
        self.width = page_width
        self.height = page_height
        self.margin_left = 40.0
        self.margin_right = 40.0
        self.margin_top = 45.0
        self.margin_bottom = 45.0
        self.content_width = self.width - self.margin_left - self.margin_right
        self.pages: List[List[str]] = []
        self._current_page_ops: List[str] = []
        self._current_y = self.height - self.margin_top

    def new_page(self) -> None:
        """Starts a new page."""
        if self._current_page_ops:
            self.pages.append(self._current_page_ops)
        self._current_page_ops = []
        self._current_y = self.height - self.margin_top

    def ensure_space(self, required_height: float) -> None:
        """If remaining vertical space is insufficient, creates a new page."""
        if self._current_y - required_height < self.margin_bottom:
            self.new_page()

    def escape_text(self, text: str) -> str:
        """Escapes text for PDF string literals and standardizes ASCII characters."""
        if text is None:
            return ""
        text = str(text)
        # Normalize typographic unicode characters to standard ASCII for Type1 fonts
        text = text.replace("—", " - ").replace("–", "-").replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
        text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        return text

    def draw_text(
        self,
        text: str,
        x: float,
        y: float,
        font: str = "/F1",
        size: float = 10.0,
        r: float = 0.1,
        g: float = 0.1,
        b: float = 0.1,
    ) -> None:
        """Emits a single line of text."""
        escaped = self.escape_text(text)
        op = (
            f"BT {r:.3f} {g:.3f} {b:.3f} rg {font} {size:.1f} Tf "
            f"1 0 0 1 {x:.2f} {y:.2f} Tm ({escaped}) Tj ET"
        )
        self._current_page_ops.append(op)

    def draw_rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill_color: Optional[Tuple[float, float, float]] = None,
        stroke_color: Optional[Tuple[float, float, float]] = None,
        line_width: float = 0.5,
    ) -> None:
        """Draws a rectangle with optional fill and stroke."""
        ops = []
        if line_width > 0:
            ops.append(f"{line_width:.2f} w")
        if fill_color and stroke_color:
            ops.append(f"{fill_color[0]:.3f} {fill_color[1]:.3f} {fill_color[2]:.3f} rg")
            ops.append(f"{stroke_color[0]:.3f} {stroke_color[1]:.3f} {stroke_color[2]:.3f} RG")
            ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re B")
        elif fill_color:
            ops.append(f"{fill_color[0]:.3f} {fill_color[1]:.3f} {fill_color[2]:.3f} rg")
            ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")
        elif stroke_color:
            ops.append(f"{stroke_color[0]:.3f} {stroke_color[1]:.3f} {stroke_color[2]:.3f} RG")
            ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re S")
        self._current_page_ops.extend(ops)

    def draw_line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        r: float = 0.7,
        g: float = 0.7,
        b: float = 0.7,
        width: float = 0.5,
    ) -> None:
        """Draws a stroked line."""
        op = (
            f"{width:.2f} w {r:.3f} {g:.3f} {b:.3f} RG "
            f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S"
        )
        self._current_page_ops.append(op)

    def add_heading(self, text: str, level: int = 1) -> None:
        """Adds a section heading with spacing."""
        sizes = {1: (15.0, 22.0, 10.0), 2: (12.0, 16.0, 8.0), 3: (10.5, 14.0, 6.0)}
        font_size, before_space, after_space = sizes.get(level, (11.0, 14.0, 6.0))

        self.ensure_space(before_space + font_size + after_space)
        self._current_y -= before_space

        # Heading accent bar for level 1
        if level == 1:
            self.draw_rect(
                self.margin_left,
                self._current_y - 2.0,
                self.content_width,
                font_size + 6.0,
                fill_color=(0.92, 0.94, 0.97),
                stroke_color=(0.80, 0.84, 0.90),
                line_width=0.75,
            )
            # Left accent highlight
            self.draw_rect(
                self.margin_left,
                self._current_y - 2.0,
                4.0,
                font_size + 6.0,
                fill_color=(0.12, 0.29, 0.53),
            )
            self.draw_text(
                text,
                self.margin_left + 10.0,
                self._current_y + 1.0,
                font="/F2",
                size=font_size,
                r=0.08,
                g=0.20,
                b=0.38,
            )
        else:
            self.draw_text(
                text,
                self.margin_left,
                self._current_y,
                font="/F2",
                size=font_size,
                r=0.15,
                g=0.22,
                b=0.33,
            )
            self.draw_line(
                self.margin_left,
                self._current_y - 3.0,
                self.margin_left + self.content_width,
                self._current_y - 3.0,
                r=0.82,
                g=0.85,
                b=0.88,
                width=0.5,
            )

        self._current_y -= (font_size + after_space)

    def add_paragraph(
        self,
        text: str,
        font: str = "/F1",
        size: float = 9.0,
        r: float = 0.15,
        g: float = 0.15,
        b: float = 0.15,
        line_height: float = 12.0,
        indent: float = 0.0,
    ) -> None:
        """Adds wrapped paragraph text."""
        if not text:
            return

        # Simple character-based line wrapping suitable for Helvetica 9pt
        max_chars = int((self.content_width - indent) / (size * 0.50))
        lines = []
        for raw_line in text.split("\n"):
            raw_line = raw_line.strip()
            if not raw_line:
                lines.append("")
                continue
            words = raw_line.split(" ")
            cur = ""
            for w in words:
                if len(cur) + len(w) + 1 <= max_chars:
                    cur = f"{cur} {w}".strip()
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)

        for line in lines:
            if not line:
                self._current_y -= (line_height * 0.5)
                continue
            self.ensure_space(line_height)
            self.draw_text(
                line,
                self.margin_left + indent,
                self._current_y,
                font=font,
                size=size,
                r=r,
                g=g,
                b=b,
            )
            self._current_y -= line_height

        self._current_y -= 4.0

    def add_key_value_grid(self, pairs: List[Tuple[str, str]], columns: int = 2) -> None:
        """Draws aligned key-value property blocks."""
        col_width = self.content_width / columns
        row_height = 16.0

        for i in range(0, len(pairs), columns):
            self.ensure_space(row_height + 2.0)
            chunk = pairs[i:i + columns]
            for col_idx, (k, v) in enumerate(chunk):
                bx = self.margin_left + (col_idx * col_width)
                by = self._current_y - 2.0
                # Background card
                self.draw_rect(
                    bx,
                    by - 11.0,
                    col_width - 6.0,
                    row_height,
                    fill_color=(0.97, 0.98, 0.99),
                    stroke_color=(0.88, 0.90, 0.92),
                    line_width=0.4,
                )
                self.draw_text(f"{k}:", bx + 5.0, by - 8.0, font="/F2", size=8.0, r=0.25, g=0.30, b=0.38)
                self.draw_text(str(v), bx + 95.0, by - 8.0, font="/F1", size=8.0, r=0.05, g=0.05, b=0.05)
            self._current_y -= (row_height + 3.0)
        self._current_y -= 4.0

    def add_table(
        self,
        headers: List[str],
        rows: List[List[str]],
        col_widths: Optional[List[float]] = None,
    ) -> None:
        """Draws a data table with repeating borders and shaded header."""
        if not col_widths:
            col_widths = [self.content_width / len(headers)] * len(headers)

        header_height = 18.0
        row_height = 16.0

        self.ensure_space(header_height + row_height)

        # Header Row
        hx = self.margin_left
        hy = self._current_y - header_height
        self.draw_rect(
            hx,
            hy,
            self.content_width,
            header_height,
            fill_color=(0.14, 0.24, 0.38),
            stroke_color=(0.10, 0.18, 0.30),
            line_width=0.5,
        )

        cx = hx
        for i, h in enumerate(headers):
            w = col_widths[i]
            self.draw_text(h, cx + 5.0, hy + 5.0, font="/F2", size=8.0, r=1.0, g=1.0, b=1.0)
            cx += w

        self._current_y = hy

        # Data Rows
        for r_idx, row in enumerate(rows):
            self.ensure_space(row_height)
            ry = self._current_y - row_height
            bg = (0.98, 0.99, 1.0) if r_idx % 2 == 0 else (0.94, 0.95, 0.97)

            self.draw_rect(
                hx,
                ry,
                self.content_width,
                row_height,
                fill_color=bg,
                stroke_color=(0.85, 0.88, 0.91),
                line_width=0.4,
            )

            cx = hx
            for c_idx, cell in enumerate(row):
                w = col_widths[c_idx]
                val = str(cell)
                # truncate cell to prevent overflow
                if len(val) > int(w / 4.8):
                    val = val[:int(w / 4.8) - 2] + ".."
                self.draw_text(val, cx + 5.0, ry + 4.5, font="/F1", size=7.5, r=0.1, g=0.1, b=0.1)
                cx += w

            self._current_y = ry

        self._current_y -= 8.0

    def add_callout(
        self,
        title: str,
        message: str,
        kind: str = "INFO",
    ) -> None:
        """Renders an alert / callout card."""
        color_map = {
            "RED": ((0.98, 0.92, 0.92), (0.75, 0.20, 0.20), (0.60, 0.10, 0.10)),
            "AMBER": ((0.99, 0.96, 0.90), (0.80, 0.55, 0.15), (0.65, 0.40, 0.05)),
            "GREEN": ((0.92, 0.97, 0.93), (0.20, 0.60, 0.30), (0.10, 0.45, 0.20)),
            "INFO": ((0.93, 0.95, 0.98), (0.30, 0.45, 0.65), (0.15, 0.30, 0.50)),
        }
        bg, border, text_color = color_map.get(kind.upper(), color_map["INFO"])

        est_lines = max(1, len(message) // 80 + 1)
        card_height = 20.0 + (est_lines * 11.0)
        self.ensure_space(card_height + 4.0)

        cy = self._current_y - card_height
        self.draw_rect(
            self.margin_left,
            cy,
            self.content_width,
            card_height,
            fill_color=bg,
            stroke_color=border,
            line_width=0.75,
        )
        # Left accent stripe
        self.draw_rect(
            self.margin_left,
            cy,
            4.0,
            card_height,
            fill_color=border,
        )

        self.draw_text(title, self.margin_left + 10.0, cy + card_height - 12.0, font="/F2", size=8.5, r=text_color[0], g=text_color[1], b=text_color[2])

        # Wrapped message
        msg_y = cy + card_height - 23.0
        words = message.split(" ")
        cur_line = ""
        for w in words:
            if len(cur_line) + len(w) + 1 <= 85:
                cur_line = f"{cur_line} {w}".strip()
            else:
                self.draw_text(cur_line, self.margin_left + 10.0, msg_y, font="/F1", size=7.8, r=0.15, g=0.15, b=0.15)
                msg_y -= 10.5
                cur_line = w
        if cur_line:
            self.draw_text(cur_line, self.margin_left + 10.0, msg_y, font="/F1", size=7.8, r=0.15, g=0.15, b=0.15)

        self._current_y = cy - 8.0

    def build_pdf_bytes(
        self,
        report_title: str = "Critical Mineral Supply-Chain Risk Assessment",
        report_id: str = "REP-0000",
        generated_at: str = "",
    ) -> bytes:
        """
        Finalizes pages, adds running headers, footers with 'Page X of Y',
        and generates valid PDF 1.4 byte output.
        """
        if self._current_page_ops:
            self.pages.append(self._current_page_ops)

        total_pages = max(1, len(self.pages))
        out_objects: List[bytes] = []
        byte_offsets: List[int] = []

        # Object tracking
        # 1 0 obj: Catalog
        # 2 0 obj: Pages
        # 3 0 obj: Font Helvetica
        # 4 0 obj: Font Helvetica-Bold
        # 5 0 obj: Font Helvetica-Oblique
        # 6 0 obj: Font Courier
        # For each page:
        #   (7 + 2*i) 0 obj: Page
        #   (8 + 2*i) 0 obj: Contents Stream

        # Add running header and footer to every page
        for p_idx, page_ops in enumerate(self.pages):
            p_num = p_idx + 1

            # Header line
            top_line_y = self.height - 28.0
            header_ops = [
                f"BT 0.35 0.40 0.48 rg /F2 7.5 Tf 1 0 0 1 {self.margin_left:.2f} {top_line_y:.2f} Tm (MINETRACE | {self.escape_text(report_title)}) Tj ET",
                f"BT 0.45 0.50 0.55 rg /F1 7.0 Tf 1 0 0 1 {self.width - self.margin_right - 140.0:.2f} {top_line_y:.2f} Tm (ID: {self.escape_text(report_id[:16])}) Tj ET",
                f"0.5 w 0.82 0.85 0.88 RG {self.margin_left:.2f} {top_line_y - 3.0:.2f} m {self.width - self.margin_right:.2f} {top_line_y - 3.0:.2f} l S",
            ]

            # Footer line
            bot_line_y = 30.0
            footer_text = f"CONFIDENTIAL & PROPRIETARY — Page {p_num} of {total_pages}"
            date_text = f"Generated: {generated_at[:19]} UTC" if generated_at else "Generated for Analyst Review"
            footer_ops = [
                f"0.5 w 0.82 0.85 0.88 RG {self.margin_left:.2f} {bot_line_y + 8.0:.2f} m {self.width - self.margin_right:.2f} {bot_line_y + 8.0:.2f} l S",
                f"BT 0.40 0.45 0.50 rg /F1 7.0 Tf 1 0 0 1 {self.margin_left:.2f} {bot_line_y:.2f} Tm ({self.escape_text(date_text)}) Tj ET",
                f"BT 0.30 0.35 0.42 rg /F2 7.0 Tf 1 0 0 1 {self.width - self.margin_right - 165.0:.2f} {bot_line_y:.2f} Tm ({self.escape_text(footer_text)}) Tj ET",
            ]

            page_ops.extend(header_ops)
            page_ops.extend(footer_ops)

        # Assemble PDF file stream
        buf = io.BytesIO()
        buf.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

        # Page object IDs
        page_obj_ids = [7 + (2 * i) for i in range(total_pages)]
        kids_str = " ".join([f"{pid} 0 R" for pid in page_obj_ids])

        # Object 1: Catalog
        byte_offsets.append(buf.tell())
        buf.write(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

        # Object 2: Pages
        byte_offsets.append(buf.tell())
        buf.write(f"2 0 obj\n<< /Type /Pages /Kids [{kids_str}] /Count {total_pages} /MediaBox [0 0 {self.width:.2f} {self.height:.2f}] >>\nendobj\n".encode("utf-8"))

        # Object 3: Font Helvetica
        byte_offsets.append(buf.tell())
        buf.write(b"3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

        # Object 4: Font Helvetica-Bold
        byte_offsets.append(buf.tell())
        buf.write(b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>\nendobj\n")

        # Object 5: Font Helvetica-Oblique
        byte_offsets.append(buf.tell())
        buf.write(b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>\nendobj\n")

        # Object 6: Font Courier
        byte_offsets.append(buf.tell())
        buf.write(b"6 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj\n")

        # Pages and Streams
        for i, ops in enumerate(self.pages):
            pid = 7 + (2 * i)
            cid = 8 + (2 * i)

            content_data = "\n".join(ops).encode("utf-8")
            stream_len = len(content_data)

            # Page Object
            byte_offsets.append(buf.tell())
            page_dict = (
                f"{pid} 0 obj\n"
                f"<< /Type /Page /Parent 2 0 R\n"
                f"   /Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R /F4 6 0 R >> >>\n"
                f"   /Contents {cid} 0 R\n"
                f">>\nendobj\n"
            )
            buf.write(page_dict.encode("utf-8"))

            # Stream Object
            byte_offsets.append(buf.tell())
            stream_obj = (
                f"{cid} 0 obj\n"
                f"<< /Length {stream_len} >>\n"
                f"stream\n"
            ).encode("utf-8") + content_data + b"\nendstream\nendobj\n"
            buf.write(stream_obj)

        # Cross-reference Table (xref)
        xref_offset = buf.tell()
        num_objects = len(byte_offsets) + 1  # Including object 0
        buf.write(f"xref\n0 {num_objects}\n0000000000 65535 f \n".encode("utf-8"))
        for off in byte_offsets:
            buf.write(f"{off:010d} 00000 n \n".encode("utf-8"))

        # Trailer
        trailer = (
            f"trailer\n"
            f"<< /Size {num_objects}\n"
            f"   /Root 1 0 R\n"
            f">>\n"
            f"startxref\n"
            f"{xref_offset}\n"
            f"%%EOF\n"
        )
        buf.write(trailer.encode("utf-8"))

        return buf.getvalue()


class PDFReportGenerator:
    """Orchestrates generation of printable PDF evidence reports."""

    def __init__(self):
        self.use_reportlab = HAS_REPORTLAB

    def generate_pdf(self, report_bundle: Dict[str, Any]) -> bytes:
        """Generates PDF bytes using pure-python builder or ReportLab if available."""
        # Always prioritize reliable pure-python standard builder for 100% test reproducibility,
        # or ReportLab when installed.
        return self._generate_pure_python_pdf(report_bundle)

    def _generate_pure_python_pdf(self, data: Dict[str, Any]) -> bytes:
        """Renders all required sections via PurePythonPDFBuilder."""
        builder = PurePythonPDFBuilder()

        meta = data.get("metadata", {})
        summary = data.get("executive_summary", {})
        rules = data.get("risk_rules", {})
        classification = data.get("classification", {})
        sanctions = data.get("sanctions", {})
        evidence = data.get("evidence_traceability", {})
        ai = data.get("ai_explanation", {})
        methodology = data.get("methodology_and_limitations", {})

        report_id = meta.get("report_id", "REP-UNASSIGNED")
        analysis_id = meta.get("analysis_id", "ANALYSIS-UNKNOWN")
        generated_at = meta.get("generated_at", "")
        analysis_time = meta.get("analysis_timestamp", "")

        # ----------------- SECTION 1: HEADER & METADATA -----------------
        builder.add_heading("MineTrace — Critical Mineral Supply-Chain Risk Assessment", level=1)
        builder.add_paragraph(
            f"REPORT ID: {report_id}   |   ANALYSIS ID: {analysis_id}   |   TEMPLATE VERSION: {meta.get('template_version', '1.0')}",
            font="/F2",
            size=8.5,
            r=0.20,
            g=0.25,
            b=0.35,
        )
        builder.add_paragraph(
            f"Generated At: {generated_at[:19]} UTC   |   Original Analysis Timestamp: {analysis_time[:19]} UTC",
            font="/F3",
            size=8.0,
            r=0.35,
            g=0.40,
            b=0.45,
        )

        if meta.get("notes"):
            builder.add_callout("ANALYST SCOPE NOTES", str(meta.get("notes")), kind="INFO")

        if not meta.get("has_evidence_snapshot"):
            builder.add_callout(
                "DATA COMPLETENESS WARNING",
                "No frozen Phase 5 evidence snapshot was located for this transaction. "
                "The findings below were compiled directly from mutable database records. Historical immutability is not guaranteed.",
                kind="AMBER",
            )

        # ----------------- SECTION 2: EXECUTIVE SUMMARY -----------------
        builder.add_heading("1. Executive Summary", level=2)
        score_val = summary.get("combined_anomaly_score", 0.0)
        completeness = summary.get("score_completeness", "UNAVAILABLE")
        tier = summary.get("classification", "INSUFFICIENT_DATA")

        # Callout card for classification result
        callout_kind = "GREEN" if tier == "GREEN" else ("AMBER" if tier == "AMBER" else "RED")
        if tier == "INSUFFICIENT_DATA":
            callout_kind = "AMBER"

        builder.add_callout(
            f"CLASSIFICATION: {tier}  (ANOMALY SCORE: {score_val:.1f}/100) — {completeness}",
            f"Flag Status: {summary.get('flag_status', 'NOT_FLAGGED')} | Sanctions Screening: {summary.get('sanctions_status', 'UNKNOWN')} | "
            f"Evaluated Rules: {summary.get('evaluated_rules_count', 0)} | Insufficient Rules: {summary.get('insufficient_rules_count', 0)}",
            kind=callout_kind,
        )

        if completeness in ["PARTIAL", "UNAVAILABLE"]:
            builder.add_callout(
                "DATA INSUFFICIENCY NOTICE",
                "Required baseline trade flows or partner mirror records were missing. "
                "Per Phase 3 data sufficiency policies, this transaction cannot be classified as low risk.",
                kind="AMBER",
            )

        builder.add_key_value_grid([
            ("Mineral / Commodity", f"{summary.get('mineral_type')} (HS {summary.get('commodity_code')})"),
            ("Reporter Country", str(summary.get("reporter_country_code"))),
            ("Partner Country", str(summary.get("partner_country_code"))),
            ("Trade Period", str(summary.get("period"))),
            ("Score Completeness", str(completeness)),
            ("Sanctions Screening", str(summary.get("sanctions_status"))),
        ], columns=2)

        # ----------------- SECTION 3: RISK RULE DETAILS -----------------
        builder.add_heading("2. Risk Rule Evaluation Details", level=2)
        rule_details = rules.get("rule_details", [])
        if rule_details:
            table_headers = ["Rule ID", "Rule Name", "Weight", "Outcome", "Threshold", "Calculated"]
            table_rows = []
            for r in rule_details:
                calc_str = f"{r.get('calculated_value'):.1f}%" if r.get("calculated_value") is not None else "N/A"
                table_rows.append([
                    r.get("rule_id", "R?"),
                    r.get("rule_name", "Unknown Rule"),
                    f"{r.get('weight', 0)} pts",
                    r.get("outcome", "NOT_EVALUATED"),
                    str(r.get("threshold", "N/A")),
                    calc_str,
                ])
            builder.add_table(table_headers, table_rows, col_widths=[45.0, 160.0, 50.0, 80.0, 95.0, 85.0])

            # Detail expansions for each rule
            for r in rule_details:
                calc_val = r.get("calculated_value")
                calc_txt = f"{calc_val:.1f}%" if calc_val is not None else "N/A"
                formula_txt = r.get("formula", "N/A")
                inputs_txt = str(r.get("input_values", {}))
                builder.add_paragraph(
                    f"[{r.get('rule_id')}] {r.get('rule_name')} (Weight: {r.get('weight')} pts) — Status: {r.get('outcome')}\n"
                    f"  Formula: {formula_txt}  |  Threshold: {r.get('threshold')}  |  Calculated: {calc_txt}\n"
                    f"  Inputs: {inputs_txt}\n"
                    f"  Explanation: {r.get('explanation', 'None recorded.')}",
                    font="/F1",
                    size=8.0,
                    indent=8.0,
                )
        else:
            builder.add_paragraph("No detailed rule calculation records were found.", font="/F3", size=8.5)

        # Insufficient rules explanation
        insufficient = rules.get("insufficient_rules", [])
        if insufficient:
            builder.add_callout(
                "INSUFFICIENT RULES EXPLANATION",
                f"The following rule(s) could not be evaluated due to missing source data or baselines: {', '.join(insufficient)}. "
                "Under MineTrace sufficiency policy, un-evaluated rules are never treated as passing.",
                kind="AMBER",
            )

        # ----------------- SECTION 4: CLASSIFICATION -----------------
        builder.add_heading("3. Classification & Sufficiency Guardrails", level=2)
        builder.add_key_value_grid([
            ("Saved Anomaly Score", f"{classification.get('score', 0.0):.1f} / 100.0"),
            ("Assigned Tier", str(classification.get("classification"))),
            ("Flag Status", str(classification.get("flag_status"))),
            ("Policy Version", str(classification.get("policy_version", "1.0"))),
        ], columns=2)
        builder.add_paragraph(
            f"Thresholds Applied: {classification.get('thresholds')}\n"
            f"Classification Rationale: {classification.get('explanation')}",
            font="/F1",
            size=8.5,
        )

        # ----------------- SECTION 5: SANCTIONS SCREENING -----------------
        builder.add_heading("4. Sanctions Screening (OFAC SDN)", level=2)
        s_stat = sanctions.get("sanctions_status", "UNKNOWN")
        s_kind = "RED" if s_stat == "REVIEW_MATCH" else "GREEN"
        builder.add_callout(
            f"SANCTIONS STATUS: {s_stat}",
            f"Registry Reference: {sanctions.get('reference')}\n"
            f"Limitations: {sanctions.get('limitations')}",
            kind=s_kind,
        )

        # ----------------- SECTION 6: EVIDENCE & AUDIT TRAIL -----------------
        builder.add_heading("5. Source Evidence & Audit Trail", level=2)
        builder.add_key_value_grid([
            ("Source Dataset", str(evidence.get("source_dataset"))),
            ("Source Record ID", str(evidence.get("source_record_id"))),
            ("Retrieval Timestamp", str(evidence.get("retrieval_timestamp"))),
            ("Evidence Snapshot ID", str(evidence.get("snapshot_id"))),
            ("Validation Status", str(evidence.get("validation_status"))),
            ("Source Endpoint / URL", str(evidence.get("source_reference_url"))[:40]),
        ], columns=2)

        audit_events = evidence.get("audit_events", [])
        if audit_events:
            ev_headers = ["Event ID", "Event Type", "Status", "Timestamp"]
            ev_rows = [
                [
                    ev.get("event_id", "")[:12] + "..",
                    ev.get("event_type", ""),
                    ev.get("status", ""),
                    ev.get("timestamp", "")[:19],
                ]
                for ev in audit_events[:6]
            ]
            builder.add_table(ev_headers, ev_rows, col_widths=[90.0, 180.0, 75.0, 170.0])

        # ----------------- SECTION 7: VALIDATED AI EXPLANATION -----------------
        builder.add_heading("6. Validated AI Explanation", level=2)
        if ai.get("available") and ai.get("explanation"):
            builder.add_callout(
                f"EVIDENCE-GROUNDED AI EXPLANATION ({ai.get('validation_status')})",
                str(ai.get("explanation")),
                kind="INFO",
            )
            builder.add_paragraph(
                f"Grounded Evidence Snapshots: {', '.join(ai.get('evidence_ids', [])) or 'Direct SQLite Record'}\n"
                f"Supporting Reference Documents: {', '.join(ai.get('supporting_documents', [])) or 'Standard Methodology'}",
                font="/F3",
                size=7.5,
                r=0.35,
                g=0.40,
                b=0.48,
            )
        else:
            builder.add_paragraph(
                f"Status: {ai.get('validation_status', 'UNAVAILABLE')}. "
                "No pre-validated AI explanation was attached to this transaction record.",
                font="/F3",
                size=8.0,
                r=0.4,
                g=0.4,
                b=0.4,
            )

        # ----------------- SECTION 8: METHODOLOGY & LIMITATIONS -----------------
        builder.add_heading("7. Methodology, Limitations & Legal Notice", level=2)
        builder.add_paragraph(methodology.get("disclaimer", ""), font="/F2", size=7.8, r=0.25, g=0.30, b=0.38)
        builder.add_paragraph(methodology.get("methodology", ""), font="/F1", size=7.5, r=0.25, g=0.25, b=0.25)

        return builder.build_pdf_bytes(
            report_title=meta.get("report_title", "Critical Mineral Risk Assessment"),
            report_id=report_id,
            generated_at=generated_at,
        )
