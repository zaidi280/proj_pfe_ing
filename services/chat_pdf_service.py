import base64
import re
from datetime import datetime, timezone
from typing import Any


class ChatPdfService:
    _PDF_INTENT_RE = re.compile(
        r"\b(pdf|export|telecharger|t[ée]l[ée]charger|download|imprimer|print)\b",
        re.IGNORECASE,
    )

    @classmethod
    def wants_pdf(cls, prompt: str) -> bool:
        return bool(cls._PDF_INTENT_RE.search(prompt or ""))

    @staticmethod
    def _safe_text(value: Any, fallback: str = "-") -> str:
        txt = str(value or "").strip()
        return txt if txt else fallback

    @classmethod
    def build_pdf_payload(cls, docs: list[dict], title: str) -> dict[str, Any]:
        """Generate PDF and return transport-friendly payload for API response."""
        try:
            from fpdf import FPDF  # type: ignore
        except Exception:
            return {
                "pdf_generated": False,
                "pdf_filename": "",
                "pdf_base64": "",
                "pdf_error": "fpdf2 is not installed in runtime environment",
            }

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, txt="Invoice Chat Recap", ln=1)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, txt=f"Prompt: {title}")
        pdf.ln(2)

        headers = ["Numero", "Vendeur", "Client", "Date", "TTC", "Devise", "Statut"]
        widths = [24, 32, 32, 24, 20, 16, 36]

        pdf.set_font("Helvetica", "B", 9)
        for h, w in zip(headers, widths):
            pdf.cell(w, 7, h, border=1)
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        for d in docs:
            inv = d.get("invoice", {}) if isinstance(d.get("invoice"), dict) else {}
            facture = inv.get("facture", {}) if isinstance(inv.get("facture"), dict) else {}
            vendeur = inv.get("vendeur", {}) if isinstance(inv.get("vendeur"), dict) else {}
            client = inv.get("client", {}) if isinstance(inv.get("client"), dict) else {}
            totaux = inv.get("totaux", {}) if isinstance(inv.get("totaux"), dict) else {}
            paiement = inv.get("paiement", {}) if isinstance(inv.get("paiement"), dict) else {}

            row = [
                cls._safe_text(facture.get("numero")),
                cls._safe_text(vendeur.get("nom")),
                cls._safe_text(client.get("nom")),
                cls._safe_text(facture.get("date")),
                cls._safe_text(totaux.get("total_ttc_normalized", totaux.get("total_ttc"))),
                cls._safe_text(totaux.get("devise"), "DT"),
                cls._safe_text(paiement.get("statu_paiement", paiement.get("statut_paiement"))),
            ]

            for value, w in zip(row, widths):
                pdf.cell(w, 6, value[:30], border=1)
            pdf.ln()

        try:
            out = pdf.output(dest="S")
            if isinstance(out, bytearray):
                pdf_bytes = bytes(out)
            elif isinstance(out, bytes):
                pdf_bytes = out
            else:
                pdf_bytes = out.encode("latin-1", errors="ignore")

            filename = f"invoice_recap_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pdf"
            return {
                "pdf_generated": True,
                "pdf_filename": filename,
                "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                "pdf_error": "",
            }
        except Exception as exc:
            return {
                "pdf_generated": False,
                "pdf_filename": "",
                "pdf_base64": "",
                "pdf_error": f"pdf generation failed: {exc}",
            }
