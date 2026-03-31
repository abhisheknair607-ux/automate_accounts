from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pypdfium2 as pdfium
from PIL import Image, ImageOps

from app.core.config import Settings, get_settings
from app.schemas.canonical import (
    AuditMetadata,
    CanonicalInvoice,
    DeliveryDocket,
    DocumentType,
    FieldConfidence,
    InvoiceHeader,
    ProviderExtractionResult,
    Store,
    Supplier,
)
from app.services.extraction.providers.azure_stub import AzureDocumentIntelligenceProvider, ZERO
from app.services.extraction.providers.base import DocumentExtractionContext


DELIVERY_TABLE_HEADER = ["Qty", "Description", "SKU"]
LANDSCAPE_ROTATIONS = (0, 90, 270)
PORTRAIT_ROTATIONS = (0,)

EXPECTED_KEYWORDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.INVOICE: ("invoice", "account", "store", "total", "vat", "docket"),
    DocumentType.DELIVERY_DOCKET: ("deliver", "invoice to", "qty", "description", "date", "signed"),
    DocumentType.ACCOUNTING_TEMPLATE: ("report", "sales", "profit", "income"),
    DocumentType.UNKNOWN: (),
}


@dataclass(slots=True)
class OCRSpacePageResult:
    page_number: int
    rotation: int
    parsed_text: str
    parsed_result: dict[str, Any]
    score: float


class OCRSpaceExtractionProvider(AzureDocumentIntelligenceProvider):
    name = "ocr_space"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _parse_date(self, value: Any):
        parsed = super()._parse_date(value)
        if parsed is not None or not isinstance(value, str):
            return parsed

        cleaned = value.strip()
        for pattern in ("%d/%m/%y", "%d-%m-%y", "%d.%m.%y"):
            try:
                return datetime.strptime(cleaned, pattern).date()
            except ValueError:
                continue
        return None

    def extract(self, context: DocumentExtractionContext) -> ProviderExtractionResult:
        self._ensure_configuration()
        analysis = self._analyze_with_ocr_space(context)
        model_id = f"ocr.space-engine-{self._settings.ocr_space_engine}"

        if context.doc_type == DocumentType.INVOICE:
            return self._build_invoice_result(context, analysis, model_id)
        if context.doc_type == DocumentType.DELIVERY_DOCKET:
            try:
                return super()._build_delivery_docket_result(context, analysis, model_id)
            except ValueError:
                return self._build_delivery_docket_result_relaxed(context, analysis, model_id)
        if context.doc_type == DocumentType.ACCOUNTING_TEMPLATE:
            return super()._build_accounting_template_result(context, analysis, model_id)
        return super()._build_unknown_result(context, analysis, model_id)

    def _build_invoice_result(
        self,
        context: DocumentExtractionContext,
        analysis: dict[str, Any],
        model_id: str,
    ) -> ProviderExtractionResult:
        try:
            return super()._build_invoice_result(context, analysis, model_id)
        except ValueError:
            return self._build_invoice_result_relaxed(context, analysis, model_id)

    def _ensure_configuration(self) -> None:
        if not self._settings.ocr_space_api_key:
            raise RuntimeError(
                "OCR.space is selected but not configured. "
                "Set OCR_SPACE_API_KEY in your environment."
            )

    def _analyze_with_ocr_space(self, context: DocumentExtractionContext) -> dict[str, Any]:
        page_images = self._load_document_images(context)
        page_results = [
            self._extract_best_page_result(context.doc_type, page_number, image)
            for page_number, image in page_images
        ]

        content = "\n".join(
            page.parsed_text.strip() for page in page_results if page.parsed_text.strip()
        ).strip()

        return {
            "api_version": f"ocr.space-{self._settings.ocr_space_engine}",
            "content": content,
            "pages": [self._analysis_page(page) for page in page_results],
            "tables": self._analysis_tables(context.doc_type, page_results),
            "documents": self._analysis_documents(context.doc_type, page_results, content),
            "metadata": {
                "provider": self.name,
                "page_count": len(page_results),
                "pages": [
                    {
                        "page_number": page.page_number,
                        "rotation": page.rotation,
                        "score": round(page.score, 3),
                    }
                    for page in page_results
                ],
            },
        }

    def _load_document_images(self, context: DocumentExtractionContext) -> list[tuple[int, Image.Image]]:
        path = context.absolute_path
        suffix = path.suffix.casefold()
        if suffix == ".pdf":
            return self._render_pdf_images(path, context.doc_type)

        with Image.open(path) as opened_image:
            image = ImageOps.exif_transpose(opened_image).convert("RGB")
        return [(1, image)]

    def _render_pdf_images(
        self,
        path: Path,
        doc_type: DocumentType,
    ) -> list[tuple[int, Image.Image]]:
        pdf = pdfium.PdfDocument(str(path))
        page_images: list[tuple[int, Image.Image]] = []
        scale = self._settings.ocr_space_pdf_render_dpi / 72
        try:
            page_indexes = self._pdf_page_indexes(len(pdf), doc_type)
            for page_number in page_indexes:
                page = pdf[page_number]
                pil_image = page.render(scale=scale).to_pil().convert("RGB")
                page_images.append((page_number + 1, pil_image))
        finally:
            pdf.close()
        return page_images

    def _pdf_page_indexes(self, page_count: int, doc_type: DocumentType) -> list[int]:
        if page_count <= 1:
            return [0]
        if doc_type == DocumentType.INVOICE:
            candidates = [0, 1, 2, max(page_count - 2, 0), page_count - 1]
            return list(dict.fromkeys(candidates))
        return list(range(page_count))

    def _extract_best_page_result(
        self,
        doc_type: DocumentType,
        page_number: int,
        image: Image.Image,
    ) -> OCRSpacePageResult:
        rotations = LANDSCAPE_ROTATIONS if image.width > image.height else PORTRAIT_ROTATIONS
        best_result: OCRSpacePageResult | None = None

        for rotation in rotations:
            candidate = image.rotate(rotation, expand=True) if rotation else image.copy()
            payload = self._encode_image(candidate)
            response = self._submit_ocr_request(payload, page_number)
            parsed_result = self._primary_result(response)
            parsed_text = (parsed_result.get("ParsedText") or "").strip()
            score = self._score_parsed_result(doc_type, parsed_result, parsed_text)
            page_result = OCRSpacePageResult(
                page_number=page_number,
                rotation=rotation,
                parsed_text=parsed_text,
                parsed_result=parsed_result,
                score=score,
            )
            if best_result is None or page_result.score > best_result.score:
                best_result = page_result

        if best_result is None or not best_result.parsed_text:
            raise RuntimeError(
                f"OCR.space did not return usable text for page {page_number}."
            )
        return best_result

    def _encode_image(self, image: Image.Image) -> bytes:
        working = ImageOps.exif_transpose(image).convert("RGB")
        max_side = self._settings.ocr_space_max_image_side
        if max(working.size) > max_side:
            working.thumbnail((max_side, max_side))

        max_bytes = self._settings.ocr_space_max_image_bytes
        quality = 88
        while True:
            buffer = io.BytesIO()
            working.save(buffer, format="JPEG", quality=quality, optimize=True)
            payload = buffer.getvalue()
            if len(payload) <= max_bytes:
                return payload

            if quality > 45:
                quality -= 8
                continue

            next_size = (max(int(working.width * 0.85), 640), max(int(working.height * 0.85), 640))
            if next_size == working.size:
                return payload
            working = working.resize(next_size)
            quality = 88

    def _submit_ocr_request(self, image_bytes: bytes, page_number: int) -> dict[str, Any]:
        data = {
            "language": self._settings.ocr_space_language,
            "isOverlayRequired": "true",
            "isTable": "true",
            "scale": "true",
            "OCREngine": str(self._settings.ocr_space_engine),
        }
        files = {
            "file": (f"page-{page_number}.jpg", image_bytes, "image/jpeg"),
        }
        headers = {"apikey": self._settings.ocr_space_api_key}

        with httpx.Client(timeout=self._settings.ocr_space_timeout_seconds) as client:
            response = client.post(
                self._settings.ocr_space_endpoint,
                headers=headers,
                data=data,
                files=files,
            )
            if response.status_code == 403:
                message = response.text.strip().strip('"')
                if "maximum 10 number of times within 600 seconds" in message:
                    raise RuntimeError(
                        "OCR.space rejected the shared 'helloworld' demo key because it hit "
                        "its public rate limit. Replace OCR_SPACE_API_KEY with your own free "
                        "OCR.space key to process the full sample invoice reliably."
                    )
                raise RuntimeError(f"OCR.space rejected the request: {message or '403 Forbidden'}")
            response.raise_for_status()
            payload = response.json()

        if payload.get("IsErroredOnProcessing"):
            message = payload.get("ErrorMessage") or payload.get("ErrorDetails") or "unknown OCR error"
            raise RuntimeError(f"OCR.space failed on page {page_number}: {message}")
        return payload

    def _primary_result(self, response: dict[str, Any]) -> dict[str, Any]:
        parsed_results = response.get("ParsedResults") or []
        if not parsed_results:
            return {}
        first = parsed_results[0]
        return first if isinstance(first, dict) else {}

    def _score_parsed_result(
        self,
        doc_type: DocumentType,
        parsed_result: dict[str, Any],
        parsed_text: str,
    ) -> float:
        if not parsed_text:
            return -1_000_000.0

        text_overlay = parsed_result.get("TextOverlay") or {}
        aspect_scores: list[float] = []
        horizontal_words = 0
        for line in text_overlay.get("Lines") or []:
            for word in line.get("Words") or []:
                width = self._coerce_float(word.get("Width")) or 0.0
                height = self._coerce_float(word.get("Height")) or 1.0
                ratio = width / max(height, 1.0)
                aspect_scores.append(min(ratio, 4.0))
                if ratio >= 1.1:
                    horizontal_words += 1

        keyword_hits = sum(
            1 for keyword in EXPECTED_KEYWORDS.get(doc_type, ()) if keyword in parsed_text.casefold()
        )
        tab_lines = sum(1 for line in parsed_text.splitlines() if "\t" in line)
        aspect_bonus = (sum(aspect_scores) / len(aspect_scores)) if aspect_scores else 0.0
        return (
            float(len(parsed_text))
            + keyword_hits * 40.0
            + tab_lines * 12.0
            + horizontal_words * 1.5
            + aspect_bonus * 30.0
        )

    def _analysis_page(self, page: OCRSpacePageResult) -> dict[str, Any]:
        overlay = page.parsed_result.get("TextOverlay") or {}
        analysis_lines: list[dict[str, Any]] = []
        for line in overlay.get("Lines") or []:
            text = (line.get("LineText") or "").strip()
            if not text:
                continue
            analysis_lines.append(
                {
                    "content": text,
                    "bounding_regions": [{"page_number": page.page_number}],
                }
            )

        if not analysis_lines:
            analysis_lines = [
                {
                    "content": text.strip(),
                    "bounding_regions": [{"page_number": page.page_number}],
                }
                for text in re.split(r"[\r\n]+", page.parsed_text)
                if text.strip()
            ]

        return {
            "page_number": page.page_number,
            "rotation": page.rotation,
            "lines": analysis_lines,
        }

    def _analysis_tables(
        self,
        doc_type: DocumentType,
        page_results: list[OCRSpacePageResult],
    ) -> list[dict[str, Any]]:
        if doc_type != DocumentType.DELIVERY_DOCKET:
            return []

        tables: list[dict[str, Any]] = []
        for page in page_results:
            table = self._build_delivery_table(page.page_number, page.parsed_text)
            if table is not None:
                tables.append(table)
        return tables

    def _analysis_documents(
        self,
        doc_type: DocumentType,
        page_results: list[OCRSpacePageResult],
        content: str,
    ) -> list[dict[str, Any]]:
        if doc_type != DocumentType.INVOICE:
            return []

        page_lines = {page.page_number: self._page_line_texts(page) for page in page_results}
        fields: dict[str, Any] = {}

        invoice_number, invoice_number_page = self._search_pages(
            page_results,
            (
                r"(?:invoice(?:\s*(?:number|no|#))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
            ),
        )
        invoice_date, invoice_date_page = self._search_pages(
            page_results,
            (
                r"(?:invoice\s*date|date)\s*[:#-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
                r"(?:invoice\s*date|date)\s*[:#-]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
            ),
        )
        account_number, account_number_page = self._search_pages(
            page_results,
            (r"(?:account(?:\s*(?:number|no|#))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",),
        )
        store_number, store_number_page = self._search_pages(
            page_results,
            (
                r"(?:store(?:\s*(?:number|no|#|id))?)\s*[:#-]?\s*(\d{2,})",
                r"\bCENTRA\s+(\d{3,})[-\s]",
            ),
        )
        vendor_name, vendor_name_page = self._next_line_after_label(page_lines, "From:")
        vendor_vat, vendor_vat_page = self._find_pattern_after_label(
            page_lines,
            "VAT Registration No.",
            r"([A-Z]{2}\s*[A-Z0-9]{6,})",
        )
        if vendor_vat:
            vendor_vat = vendor_vat.replace(" ", "")

        delivery_reference, delivery_reference_page = self._search_pages(
            page_results,
            (
                r"(?:docket(?:\s*(?:number|no|#))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
                r"(?:delivery(?:\s*(?:reference|ref|note))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
            ),
        )
        subtotal, subtotal_page = self._search_pages_decimal(
            page_results,
            (r"(?:sub\s*total|subtotal|net\s*amount)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",),
        )
        tax_total, tax_total_page = self._search_pages_decimal(
            page_results,
            (r"(?:total\s*tax|tax\s*total|vat\s*total|vat)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",),
        )
        gross_total, gross_total_page = self._search_pages_decimal(
            page_results,
            (
                r"(?:invoice\s*total|gross\s*total|grand\s*total|amount\s*due|total\s*due)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",
            ),
        )

        if invoice_number:
            fields["InvoiceId"] = self._string_field(invoice_number, 0.88, invoice_number_page)
        if invoice_date:
            parsed_date = self._parse_date(invoice_date)
            if parsed_date is not None:
                fields["InvoiceDate"] = self._date_field(parsed_date.isoformat(), 0.85, invoice_date_page)
        if account_number:
            fields["CustomerId"] = self._string_field(account_number, 0.83, account_number_page)
        if store_number:
            fields["StoreNumber"] = self._string_field(store_number, 0.78, store_number_page)
        if vendor_name:
            fields["VendorName"] = self._string_field(vendor_name, 0.76, vendor_name_page)
            fields["VendorLegalName"] = self._string_field(vendor_name, 0.72, vendor_name_page)
        if vendor_vat:
            fields["VendorTaxId"] = self._string_field(vendor_vat, 0.7, vendor_vat_page)
        if delivery_reference:
            fields["DeliveryReference"] = self._string_field(
                delivery_reference,
                0.68,
                delivery_reference_page,
            )
        if subtotal is not None:
            fields["SubTotal"] = self._currency_field(subtotal, 0.74, subtotal_page)
        if tax_total is not None:
            fields["TotalTax"] = self._currency_field(tax_total, 0.72, tax_total_page)
        if gross_total is not None:
            fields["InvoiceTotal"] = self._currency_field(gross_total, 0.74, gross_total_page)

        if not fields:
            return []

        return [{"doc_type": "invoice", "confidence": 0.72, "fields": fields, "content": content}]

    def _build_invoice_result_relaxed(
        self,
        context: DocumentExtractionContext,
        analysis: dict[str, Any],
        model_id: str,
    ) -> ProviderExtractionResult:
        fields, document_confidence = self._first_document_fields(analysis)
        content = self._analysis_content(analysis)
        page_count = len(analysis.get("pages") or [])
        low_confidence_fields: list[FieldConfidence] = []

        invoice_number, invoice_number_confidence, invoice_number_page = self._select_text(
            fields,
            candidates=("InvoiceId", "InvoiceNumber"),
            text_sources=((context.source_filename, 0.68), (content, 0.74)),
            regexes=(
                r"(?:invoice(?:\s*(?:number|no|#))?|inv\s*#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
                r"invoice[_\-\s]+([A-Z0-9][A-Z0-9\-/]{2,})",
            ),
        )
        invoice_date, invoice_date_confidence, invoice_date_page = self._select_date(
            fields,
            candidates=("InvoiceDate", "ServiceDate", "DueDate"),
            text_sources=((content, 0.72),),
            regexes=(
                r"(?:invoice\s*date|date)\s*[:#-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
                r"(?:invoice\s*date|date)\s*[:#-]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
            ),
        )
        account_number, account_number_confidence, account_number_page = self._select_text(
            fields,
            candidates=("CustomerId", "AccountNumber"),
            text_sources=((context.source_filename, 0.7), (content, 0.72)),
            regexes=(
                r"(?:account(?:\s*(?:number|no|#))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
                r"account[_\-\s]+([A-Z0-9][A-Z0-9\-/]{2,})",
            ),
        )
        store_number, store_number_confidence, store_number_page = self._select_text(
            fields,
            candidates=("StoreNumber", "StoreId"),
            text_sources=((content, 0.7),),
            regexes=(
                r"(?:store(?:\s*(?:number|no|#|id))?)\s*[:#-]?\s*(\d{2,})",
                r"\bCENTRA\s+(\d{3,})[-\s]",
            ),
        )
        supplier_name, supplier_name_confidence, supplier_name_page = self._select_text(
            fields,
            candidates=("VendorName", "SupplierName", "VendorContactName"),
            text_sources=((content, 0.62),),
            regexes=(r"(?:supplier|vendor)\s*[:#-]?\s*([^\n\r]+)",),
        )
        supplier_legal_name, legal_name_confidence, _ = self._select_text(
            fields,
            candidates=("VendorLegalName", "VendorName"),
        )
        supplier_vat, supplier_vat_confidence, _ = self._select_text(
            fields,
            candidates=("VendorTaxId", "SupplierTaxId"),
            text_sources=((content, 0.68),),
            regexes=(r"(?:vat(?:\s*(?:number|no|#))?)\s*[:#-]?\s*([A-Z0-9]{6,})",),
        )
        payment_terms, payment_terms_confidence, _ = self._select_text(
            fields,
            candidates=("PaymentTerm", "PaymentTerms"),
        )
        delivery_reference, delivery_reference_confidence, delivery_reference_page = self._select_text(
            fields,
            candidates=("PurchaseOrder", "DeliveryReference"),
            text_sources=((content, 0.64),),
            regexes=(
                r"(?:delivery(?:\s*(?:reference|ref|note))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
                r"\b(DD-[0-9]{6}-[0-9]{2,})\b",
            ),
        )
        division_code, division_confidence, _ = self._select_text(
            fields,
            candidates=("DivisionCode",),
            text_sources=((context.source_filename, 0.76), (content, 0.7)),
            regexes=(r"(?:division)\s*[_:\- ]\s*([A-Z0-9]{2,})",),
        )

        subtotal_amount, subtotal_confidence, subtotal_page = self._select_decimal(
            fields,
            candidates=("SubTotal", "Subtotal", "NetTotal"),
            text_sources=((content, 0.72),),
            regexes=(
                r"(?:sub\s*total|subtotal|net\s*amount|net\s*total|total\s*ex\s*vat)\s*[:#-]?\s*[A-Z$£€]*\s*([0-9,]+\.\d{2})",
            ),
        )
        tax_total, tax_total_confidence, tax_total_page = self._select_decimal(
            fields,
            candidates=("TotalTax", "Tax", "VatTotal"),
            text_sources=((content, 0.72),),
            regexes=(
                r"(?:total\s*tax|tax\s*total|vat\s*total|vat|tax)\s*[:#-]?\s*[A-Z$£€]*\s*([0-9,]+\.\d{2})",
            ),
        )
        gross_total, gross_total_confidence, gross_total_page = self._select_decimal(
            fields,
            candidates=("InvoiceTotal", "TotalAmount", "AmountDue"),
            text_sources=((content, 0.74),),
            regexes=(
                r"(?:invoice\s*total|gross\s*total|grand\s*total|amount\s*due|total\s*due|balance\s*due)\s*[:#-]?\s*[A-Z$£€]*\s*([0-9,]+\.\d{2})",
            ),
        )

        if subtotal_amount is None:
            subtotal_amount, subtotal_confidence = self._best_amount_for_lines(
                content,
                ("subtotal", "sub total", "net total", "net amount", "total ex vat"),
                0.44,
            )
        if tax_total is None:
            tax_total, tax_total_confidence = self._best_amount_for_lines(
                content,
                ("vat", "tax"),
                0.4,
            )
        if gross_total is None:
            gross_total, gross_total_confidence = self._best_amount_for_lines(
                content,
                ("invoice total", "gross total", "grand total", "amount due", "balance due", "total due"),
                0.44,
            )

        if gross_total is None and subtotal_amount is not None and tax_total is not None:
            gross_total = subtotal_amount + tax_total
            gross_total_confidence = min(subtotal_confidence or 0.4, tax_total_confidence or 0.4)
        if subtotal_amount is None and gross_total is not None and tax_total is not None:
            subtotal_amount = max(gross_total - tax_total, ZERO)
            subtotal_confidence = min(gross_total_confidence or 0.35, tax_total_confidence or 0.35)
        if tax_total is None and gross_total is not None and subtotal_amount is not None:
            tax_total = max(gross_total - subtotal_amount, ZERO)
            tax_total_confidence = min(gross_total_confidence or 0.35, subtotal_confidence or 0.35)

        if subtotal_amount is None and gross_total is not None:
            subtotal_amount = gross_total
            subtotal_confidence = 0.18
            tax_total = ZERO if tax_total is None else tax_total
            tax_total_confidence = tax_total_confidence or 0.18
        if gross_total is None and subtotal_amount is not None:
            tax_total = tax_total or ZERO
            tax_total_confidence = tax_total_confidence or 0.18
            gross_total = subtotal_amount + tax_total
            gross_total_confidence = min(subtotal_confidence or 0.18, tax_total_confidence)

        if subtotal_amount is None:
            subtotal_amount = ZERO
            subtotal_confidence = 0.12
        if tax_total is None:
            tax_total = ZERO
            tax_total_confidence = 0.12
        if gross_total is None:
            gross_total = subtotal_amount + tax_total
            gross_total_confidence = min(subtotal_confidence or 0.12, tax_total_confidence or 0.12)

        lines = self._extract_invoice_lines(
            fields.get("Items"),
            low_confidence_fields=low_confidence_fields,
        )
        if not lines and subtotal_amount == ZERO and gross_total == ZERO:
            amounts = self._amounts_from_text(content)
            if amounts:
                gross_total = max(amounts)
                gross_total_confidence = 0.16
                subtotal_amount = gross_total
                subtotal_confidence = 0.12

        if not store_number and delivery_reference:
            suffix_match = re.search(r"(\d{3,})$", delivery_reference)
            if suffix_match:
                store_number = suffix_match.group(1)
                store_number_confidence = 0.64
                store_number_page = delivery_reference_page

        if not invoice_number:
            invoice_number = self._search_patterns(
                context.source_filename,
                (
                    r"invoice[_\-\s]+([A-Z0-9][A-Z0-9\-/]{2,})",
                    r"\b([A-Z]{0,3}\d{4,})\b",
                ),
            ) or f"INV-{context.document_id[:8].upper()}"
            invoice_number_confidence = 0.18
            self._flag_if_low(
                low_confidence_fields,
                "header.invoice_number",
                invoice_number_confidence,
                invoice_number,
                invoice_number_page,
                comment="OCR.space could not confidently read the invoice number, so a fallback identifier was used.",
            )

        if invoice_date is None:
            fallback_date = self._search_patterns(
                content,
                (
                    r"([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
                    r"([0-9]{4}-[0-9]{2}-[0-9]{2})",
                ),
            )
            invoice_date = self._parse_date(fallback_date) or datetime.now(UTC).date()
            invoice_date_confidence = 0.18
            self._flag_if_low(
                low_confidence_fields,
                "header.invoice_date",
                invoice_date_confidence,
                invoice_date.isoformat(),
                invoice_date_page,
                comment="OCR.space could not confidently read the invoice date, so a fallback date was used.",
            )

        if supplier_name is None:
            supplier_name = self._first_meaningful_line(content) or "Unknown Supplier"
            supplier_name_confidence = 0.22
        supplier_legal_name = supplier_legal_name or supplier_name
        store_number = store_number or "UNKNOWN"
        store_number_confidence = store_number_confidence or 0.18

        currency = self._extract_currency_code(
            self._pick_field(fields, "InvoiceTotal", "TotalAmount", "AmountDue", "SubTotal", "Subtotal")
        )
        supplier_address = self._extract_address_lines(self._pick_field(fields, "VendorAddress"))

        self._flag_if_low(
            low_confidence_fields,
            "header.account_number",
            account_number_confidence,
            account_number,
            account_number_page,
        )
        self._flag_if_low(
            low_confidence_fields,
            "store.store_number",
            store_number_confidence,
            store_number,
            store_number_page,
            comment="OCR.space needed a fallback for the store number." if store_number == "UNKNOWN" else None,
        )
        self._flag_if_low(
            low_confidence_fields,
            "supplier.name",
            supplier_name_confidence,
            supplier_name,
            supplier_name_page,
        )
        self._flag_if_low(
            low_confidence_fields,
            "header.subtotal_amount",
            subtotal_confidence,
            str(subtotal_amount),
            subtotal_page,
            comment="Invoice subtotal was backfilled from OCR.space text heuristics."
            if subtotal_confidence is not None and subtotal_confidence < 0.5
            else None,
        )
        self._flag_if_low(
            low_confidence_fields,
            "header.tax_total",
            tax_total_confidence,
            str(tax_total),
            tax_total_page,
            comment="Invoice tax total was backfilled from OCR.space text heuristics."
            if tax_total_confidence is not None and tax_total_confidence < 0.5
            else None,
        )
        self._flag_if_low(
            low_confidence_fields,
            "header.gross_total",
            gross_total_confidence,
            str(gross_total),
            gross_total_page,
            comment="Invoice gross total was backfilled from OCR.space text heuristics."
            if gross_total_confidence is not None and gross_total_confidence < 0.5
            else None,
        )

        notes = [f"Processed with OCR.space engine '{model_id}'."]
        if any(
            field.field_path in {"header.subtotal_amount", "header.tax_total", "header.gross_total"}
            for field in low_confidence_fields
        ):
            notes.append("Invoice totals were partially backfilled because OCR.space could not read them cleanly.")

        invoice = CanonicalInvoice(
            supplier=Supplier(
                name=supplier_name,
                legal_name=supplier_legal_name,
                account_number=account_number,
                vat_number=supplier_vat,
                address=supplier_address,
                confidence_scores=self._confidence_map(
                    name=supplier_name_confidence,
                    legal_name=legal_name_confidence,
                    account_number=account_number_confidence,
                    vat_number=supplier_vat_confidence,
                ),
            ),
            store=Store(
                store_number=store_number,
                confidence_scores=self._confidence_map(store_number=store_number_confidence),
            ),
            header=InvoiceHeader(
                invoice_number=invoice_number,
                invoice_date=invoice_date,
                account_number=account_number,
                store_number=store_number,
                supplier_name=supplier_name,
                supplier_account_reference=account_number,
                currency=currency or self._settings.azure_document_intelligence_default_currency,
                division_code=division_code,
                payment_terms=payment_terms,
                delivery_reference=delivery_reference,
                subtotal_amount=subtotal_amount,
                discount_total=sum((line.discount_amount for line in lines), start=ZERO),
                tax_total=tax_total,
                gross_total=gross_total,
                confidence_scores=self._confidence_map(
                    invoice_number=invoice_number_confidence,
                    invoice_date=invoice_date_confidence,
                    account_number=account_number_confidence,
                    store_number=store_number_confidence,
                    supplier_name=supplier_name_confidence,
                    payment_terms=payment_terms_confidence,
                    delivery_reference=delivery_reference_confidence,
                    subtotal_amount=subtotal_confidence,
                    tax_total=tax_total_confidence,
                    gross_total=gross_total_confidence,
                    division_code=division_confidence,
                ),
            ),
            lines=lines,
            tax_summaries=self._build_tax_summaries(lines, tax_total),
            discount_summaries=self._build_discount_summaries(lines),
            department_summaries=self._build_department_summaries(lines),
            delivery_summary=None,
            low_confidence_fields=low_confidence_fields,
            audit=AuditMetadata(
                source_filename=context.source_filename,
                provider_name=self.name,
                provider_version=self._provider_version(analysis),
                extracted_at=datetime.now(UTC),
                page_count=page_count or None,
                mock_data=False,
                notes=notes,
            ),
        )

        return ProviderExtractionResult(
            document_type=DocumentType.INVOICE,
            provider_name=self.name,
            provider_version=self._provider_version(analysis),
            classification_confidence=self._average_confidence(
                document_confidence,
                invoice_number_confidence,
                invoice_date_confidence,
                subtotal_confidence,
                tax_total_confidence,
                gross_total_confidence,
            ),
            raw_payload={
                "source_filename": context.source_filename,
                "model_id": model_id,
                "analysis_result": analysis,
            },
            canonical_payload=invoice.model_dump(mode="python"),
            low_confidence_fields=low_confidence_fields,
            mock_data=False,
        )

    def _best_amount_for_lines(
        self,
        content: str,
        keywords: tuple[str, ...],
        confidence: float,
    ) -> tuple[Decimal | None, float | None]:
        matches: list[Decimal] = []
        for raw_line in content.splitlines():
            normalized = self._normalize_label(raw_line)
            if not normalized or not any(keyword in normalized for keyword in keywords):
                continue
            matches.extend(self._amounts_from_text(raw_line))
        if not matches:
            return None, None
        return matches[-1], confidence

    def _amounts_from_text(self, text: str) -> list[Decimal]:
        amounts: list[Decimal] = []
        for match in re.finditer(r"(?<!\d)([0-9][0-9,]*\.\d{2})(?!\d)", text):
            decimal_value = self._parse_decimal(match.group(1))
            if decimal_value is not None:
                amounts.append(decimal_value)
        return amounts

    def _build_delivery_table(self, page_number: int, parsed_text: str) -> dict[str, Any] | None:
        rows = self._split_tab_rows(parsed_text)
        header_index = None
        for index, row in enumerate(rows):
            normalized = [self._normalize_label(cell) for cell in row]
            if "qty" in normalized and "description" in normalized:
                header_index = index
                break

        if header_index is None:
            return None

        forward_rows = self._collect_delivery_rows(rows, header_index + 1, 1)
        backward_rows = self._collect_delivery_rows(rows, header_index - 1, -1)
        backward_rows.reverse()
        item_rows = forward_rows if len(forward_rows) >= len(backward_rows) else backward_rows

        if not item_rows:
            return None

        return self._rows_to_table(
            [DELIVERY_TABLE_HEADER, *item_rows],
            page_number=page_number,
        )

    def _collect_delivery_rows(
        self,
        rows: list[list[str]],
        start_index: int,
        step: int,
    ) -> list[list[str]]:
        collected: list[list[str]] = []
        index = start_index
        while 0 <= index < len(rows):
            parsed = self._parse_delivery_row(rows[index])
            if parsed is None:
                if collected:
                    break
                index += step
                continue
            collected.append(parsed)
            index += step
        return collected

    def _parse_delivery_row(self, row: list[str]) -> list[str] | None:
        cells = [cell.strip() for cell in row if cell.strip()]
        if not cells:
            return None
        if not any(re.search(r"[A-Za-z]", cell) for cell in cells):
            return None

        quantity = "1"
        if cells and self._looks_like_quantity(cells[0]):
            quantity = cells.pop(0)

        product_code = ""
        if cells and self._looks_like_product_code(cells[-1]):
            product_code = cells.pop()

        description = " ".join(cells).strip()
        if not description or not re.search(r"[A-Za-z]", description):
            return None
        normalized_description = self._normalize_label(description)
        if any(
            token in normalized_description
            for token in (
                "total",
                "vat",
                "signature",
                "signed",
                "customer",
                "date",
                "time",
                "billing",
                "deliver to",
                "invoice to",
            )
        ):
            return None

        return [quantity, description, product_code]

    def _looks_like_quantity(self, value: str) -> bool:
        normalized = value.replace(",", "").strip()
        if not re.fullmatch(r"\d+(?:\.\d+)?", normalized):
            return False
        try:
            numeric = Decimal(normalized)
        except Exception:
            return False
        return Decimal("0") < numeric <= Decimal("999")

    def _looks_like_product_code(self, value: str) -> bool:
        normalized = value.strip().replace(" ", "")
        return bool(re.fullmatch(r"[A-Z0-9]{3,20}", normalized) and re.search(r"\d", normalized))

    def _split_tab_rows(self, text: str) -> list[list[str]]:
        rows: list[list[str]] = []
        for raw_line in re.split(r"[\r\n]+", text):
            line = raw_line.strip()
            if not line or "\t" not in line:
                continue
            cells = [cell.strip() for cell in line.split("\t") if cell.strip()]
            if len(cells) >= 2:
                rows.append(cells)
        return rows

    def _rows_to_table(self, rows: list[list[str]], *, page_number: int) -> dict[str, Any]:
        column_count = max(len(row) for row in rows)
        cells: list[dict[str, Any]] = []
        for row_index, row in enumerate(rows):
            for column_index in range(column_count):
                value = row[column_index] if column_index < len(row) else ""
                cells.append(
                    {
                        "row_index": row_index,
                        "column_index": column_index,
                        "content": value,
                        "bounding_regions": [{"page_number": page_number}],
                    }
                )
        return {
            "row_count": len(rows),
            "column_count": column_count,
            "cells": cells,
        }

    def _page_line_texts(self, page: OCRSpacePageResult) -> list[str]:
        overlay = page.parsed_result.get("TextOverlay") or {}
        lines = [
            (line.get("LineText") or "").strip()
            for line in overlay.get("Lines") or []
            if (line.get("LineText") or "").strip()
        ]
        if lines:
            return lines
        return [line.strip() for line in re.split(r"[\r\n]+", page.parsed_text) if line.strip()]

    def _search_pages(
        self,
        page_results: list[OCRSpacePageResult],
        patterns: tuple[str, ...],
    ) -> tuple[str | None, int | None]:
        for page in page_results:
            value = self._search_patterns(page.parsed_text, patterns)
            if value:
                return value, page.page_number
        return None, None

    def _search_pages_decimal(
        self,
        page_results: list[OCRSpacePageResult],
        patterns: tuple[str, ...],
    ) -> tuple[Decimal | None, int | None]:
        for page in page_results:
            value = self._parse_decimal(self._search_patterns(page.parsed_text, patterns))
            if value is not None:
                return value, page.page_number
        return None, None

    def _next_line_after_label(
        self,
        page_lines: dict[int, list[str]],
        label: str,
    ) -> tuple[str | None, int | None]:
        normalized_label = self._normalize_label(label)
        for page_number, lines in page_lines.items():
            for index, line in enumerate(lines):
                if self._normalize_label(line) != normalized_label:
                    continue
                for candidate in lines[index + 1 : index + 4]:
                    text = candidate.strip()
                    if text and not text.endswith(":"):
                        return text, page_number
        return None, None

    def _find_pattern_after_label(
        self,
        page_lines: dict[int, list[str]],
        label: str,
        pattern: str,
    ) -> tuple[str | None, int | None]:
        normalized_label = self._normalize_label(label)
        for page_number, lines in page_lines.items():
            for index, line in enumerate(lines):
                if self._normalize_label(line) != normalized_label:
                    continue
                for candidate in lines[index + 1 : index + 5]:
                    match = re.search(pattern, candidate, re.IGNORECASE)
                    if match:
                        return match.group(1).strip(), page_number
        return None, None

    def _string_field(self, value: str, confidence: float, page_number: int | None) -> dict[str, Any]:
        field: dict[str, Any] = {
            "value_string": value,
            "content": value,
            "confidence": confidence,
        }
        if page_number is not None:
            field["bounding_regions"] = [{"page_number": page_number}]
        return field

    def _date_field(self, value: str, confidence: float, page_number: int | None) -> dict[str, Any]:
        field: dict[str, Any] = {
            "value_date": value,
            "content": value,
            "confidence": confidence,
        }
        if page_number is not None:
            field["bounding_regions"] = [{"page_number": page_number}]
        return field

    def _currency_field(
        self,
        value: Decimal,
        confidence: float,
        page_number: int | None,
    ) -> dict[str, Any]:
        field: dict[str, Any] = {
            "value_currency": {
                "amount": float(value),
                "currency_code": self._settings.azure_document_intelligence_default_currency,
            },
            "content": str(value),
            "confidence": confidence,
        }
        if page_number is not None:
            field["bounding_regions"] = [{"page_number": page_number}]
        return field

    def _build_delivery_docket_result_relaxed(
        self,
        context: DocumentExtractionContext,
        analysis: dict[str, Any],
        model_id: str,
    ) -> ProviderExtractionResult:
        content = self._analysis_content(analysis)
        page_count = len(analysis.get("pages") or [])
        low_confidence_fields = []
        lines = self._extract_delivery_lines_from_tables(
            analysis,
            low_confidence_fields=low_confidence_fields,
        )

        docket_number, docket_confidence = self._regex_pick(
            content,
            (
                r"(?:delivery\s*docket|docket(?:\s*(?:number|no|#))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{3,})",
                r"\b(DD-[0-9]{6}-[0-9]{2,})\b",
            ),
            0.68,
        )
        docket_date, date_confidence = self._regex_pick_date(
            content,
            (
                r"(?:docket\s*date|delivery\s*date|date)\s*[:#-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
                r"(?:docket\s*date|delivery\s*date|date)\s*[:#-]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
            ),
            0.72,
        )
        account_number, account_confidence = self._regex_pick(
            content,
            (
                r"(?:account(?:\s*(?:number|no|#))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
                r"(?:invoice\s*to|deliver\s*to)\s*[:#-]?\s*(\d{3,})",
            ),
            0.66,
        )
        store_number, store_confidence = self._regex_pick(
            content,
            (
                r"(?:store(?:\s*(?:number|no|#|id))?)\s*[:#-]?\s*(\d{2,})",
                r"\bCENTRA\s+(\d{3,})[-\s]",
            ),
            0.64,
        )
        supplier_name, supplier_confidence = self._regex_pick(
            content,
            (r"(?:supplier|vendor)\s*[:#-]?\s*([^\n\r]+)",),
            0.62,
        )
        supplier_name = (
            supplier_name
            or self._search_patterns(content, (r"(O\s*'?Hara's of Foxford Limited)",))
            or self._first_meaningful_line(content)
            or "Unknown Supplier"
        )
        if supplier_confidence is None:
            supplier_confidence = 0.45

        invoice_reference, _ = self._regex_pick(
            content,
            (r"(?:invoice(?:\s*(?:reference|ref|number|no|#))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",),
            0.62,
        )
        signed_by, signed_confidence = self._regex_pick(
            content,
            (r"(?:signed\s*by|received\s*by)\s*[:#-]?\s*([^\n\r]+)",),
            0.55,
        )

        subtotal_amount, _ = self._regex_pick_decimal(
            content,
            (r"(?:sub\s*total|subtotal|net\s*total)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",),
            0.7,
        )
        tax_total, _ = self._regex_pick_decimal(
            content,
            (r"(?:tax\s*total|total\s*tax|vat\s*total|vat)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",),
            0.68,
        )
        gross_total, _ = self._regex_pick_decimal(
            content,
            (r"(?:gross\s*total|grand\s*total|delivery\s*total|total)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",),
            0.7,
        )

        subtotal_amount = subtotal_amount or sum(
            (line.extended_amount or Decimal("0.00") for line in lines),
            start=Decimal("0.00"),
        )
        tax_total = tax_total or Decimal("0.00")
        gross_total = gross_total or (subtotal_amount + tax_total)

        if docket_number is None:
            if docket_date is not None and store_number:
                docket_number = f"DD-{docket_date.strftime('%Y%m%d')}-{store_number}"
            elif store_number:
                docket_number = f"DD-UNKNOWN-{store_number}"
            else:
                docket_number = f"DD-{context.document_id[:8].upper()}"
            docket_confidence = 0.18
            self._flag_if_low(
                low_confidence_fields,
                "docket_number",
                docket_confidence,
                docket_number,
                1 if page_count else None,
                comment="OCR.space could not read a docket number, so a synthetic identifier was created.",
            )

        if docket_date is None:
            fallback = self._search_patterns(content, (r"([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",))
            docket_date = self._parse_date(fallback) or datetime.now(UTC).date()
            date_confidence = 0.18
            self._flag_if_low(
                low_confidence_fields,
                "docket_date",
                date_confidence,
                docket_date.isoformat(),
                1 if page_count else None,
                comment="OCR.space could not read a docket date confidently, so a fallback date was used.",
            )

        if subtotal_amount == Decimal("0.00") and not lines:
            self._flag_if_low(
                low_confidence_fields,
                "subtotal_amount",
                0.18,
                "0.00",
                1 if page_count else None,
                comment="No readable totals were found on the scanned docket.",
            )

        self._flag_if_low(
            low_confidence_fields,
            "account_number",
            account_confidence,
            account_number,
            1 if page_count else None,
        )
        self._flag_if_low(
            low_confidence_fields,
            "store_number",
            store_confidence,
            store_number,
            1 if page_count else None,
        )
        self._flag_if_low(
            low_confidence_fields,
            "supplier_name",
            supplier_confidence,
            supplier_name,
            1 if page_count else None,
        )
        self._flag_if_low(
            low_confidence_fields,
            "signed_by",
            signed_confidence,
            signed_by,
            1 if page_count else None,
        )

        notes = [f"Processed with OCR.space engine '{model_id}'."]
        if any(field.field_path == "subtotal_amount" for field in low_confidence_fields):
            notes.append("Delivery totals were not clearly visible on the uploaded docket and were backfilled.")

        docket = DeliveryDocket(
            docket_number=docket_number,
            docket_date=docket_date,
            account_number=account_number,
            store_number=store_number,
            supplier_name=supplier_name,
            invoice_reference=invoice_reference,
            subtotal_amount=subtotal_amount,
            tax_total=tax_total,
            gross_total=gross_total,
            vehicle_reference=None,
            signed_by=signed_by,
            lines=lines,
            low_confidence_fields=low_confidence_fields,
            audit=AuditMetadata(
                source_filename=context.source_filename,
                provider_name=self.name,
                provider_version=self._provider_version(analysis),
                extracted_at=datetime.now(UTC),
                page_count=page_count or None,
                mock_data=False,
                notes=notes,
            ),
        )

        return ProviderExtractionResult(
            document_type=DocumentType.DELIVERY_DOCKET,
            provider_name=self.name,
            provider_version=self._provider_version(analysis),
            classification_confidence=self._average_confidence(
                docket_confidence,
                date_confidence,
                account_confidence,
                store_confidence,
                supplier_confidence,
            ),
            raw_payload={
                "source_filename": context.source_filename,
                "model_id": model_id,
                "analysis_result": analysis,
            },
            canonical_payload=docket.model_dump(mode="python"),
            low_confidence_fields=low_confidence_fields,
            mock_data=False,
        )
