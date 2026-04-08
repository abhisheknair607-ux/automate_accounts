from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from io import BytesIO
import mimetypes
import re
from decimal import Decimal
from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.canonical import (
    AuditMetadata,
    CanonicalInvoice,
    DeliveryDocket,
    DocumentType,
    InvoiceHeader,
    InvoiceLine,
    ProviderExtractionResult,
    Store,
    Supplier,
)
from app.services.extraction.providers.azure_stub import AzureDocumentIntelligenceProvider
from app.services.extraction.providers.base import DocumentExtractionContext


class GoogleDocumentAIExtractionProvider(AzureDocumentIntelligenceProvider):
    name = "google_document_ai"

    _INVOICE_FIELD_ALIASES: dict[str, str] = {
        "account_id": "CustomerId",
        "account_number": "CustomerId",
        "amount_due": "AmountDue",
        "billing_address": "VendorAddress",
        "customer_id": "CustomerId",
        "delivery_note": "DeliveryReference",
        "delivery_reference": "DeliveryReference",
        "document_id": "InvoiceId",
        "document_number": "InvoiceId",
        "due_date": "DueDate",
        "invoice_date": "InvoiceDate",
        "invoice_id": "InvoiceId",
        "invoice_number": "InvoiceId",
        "net_amount": "NetTotal",
        "payment_terms": "PaymentTerm",
        "po_number": "PurchaseOrder",
        "purchase_order": "PurchaseOrder",
        "sub_total": "SubTotal",
        "subtotal": "SubTotal",
        "supplier_address": "VendorAddress",
        "supplier_name": "VendorName",
        "supplier_tax_id": "VendorTaxId",
        "supplier_vat_id": "VendorTaxId",
        "tax": "TotalTax",
        "tax_amount": "TotalTax",
        "total_amount": "InvoiceTotal",
        "total_tax_amount": "TotalTax",
        "vat": "VatTotal",
        "vendor_address": "VendorAddress",
        "vendor_name": "VendorName",
        "vendor_tax_id": "VendorTaxId",
    }

    _LINE_ITEM_FIELD_ALIASES: dict[str, str] = {
        "amount": "Amount",
        "description": "Description",
        "discount": "Discount",
        "discount_amount": "Discount",
        "item_code": "ItemCode",
        "item_description": "Description",
        "line_amount": "Amount",
        "line_item_amount": "Amount",
        "name": "Name",
        "price": "Price",
        "product_code": "ProductCode",
        "quantity": "Quantity",
        "qty": "Qty",
        "sku": "ProductCode",
        "tax": "Tax",
        "tax_amount": "TaxAmount",
        "tax_rate": "TaxRate",
        "total_price": "TotalPrice",
        "unit": "Unit",
        "unit_of_measure": "UnitOfMeasure",
        "unit_price": "UnitPrice",
        "uom": "UnitOfMeasure",
        "vat_rate": "VatRate",
    }

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings=settings or get_settings())

    def _provider_display_name(self) -> str:
        return "Google Document AI"

    def _processed_with_note(self, model_id: str) -> str:
        return f"Processed with {self._provider_display_name()} processor '{model_id}'."

    def extract(self, context: DocumentExtractionContext) -> ProviderExtractionResult:
        self._ensure_configuration()
        model_id, analysis = self._analyze_with_google_document_ai(context)

        if context.doc_type == DocumentType.INVOICE:
            try:
                result = self._build_invoice_result(context, analysis, model_id)
            except ValueError:
                result = self._build_invoice_result_relaxed(context, analysis, model_id)
            return self._augment_invoice_result_with_layout(
                context,
                result,
                invoice_model_id=model_id,
            )
        if context.doc_type == DocumentType.DELIVERY_DOCKET:
            try:
                return self._build_delivery_docket_result(context, analysis, model_id)
            except ValueError:
                return self._build_delivery_docket_result_relaxed(context, analysis, model_id)
        if context.doc_type == DocumentType.ACCOUNTING_TEMPLATE:
            return self._build_accounting_template_result(context, analysis, model_id)
        return self._build_unknown_result(context, analysis, model_id)

    def _ensure_configuration(self) -> None:
        if not self._settings.google_document_ai_project_id:
            raise RuntimeError(
                "Google Document AI is selected but not configured. "
                "Set GOOGLE_DOCUMENT_AI_PROJECT_ID in your environment."
            )
        if (
            not self._settings.google_document_ai_invoice_processor_id
            and not self._settings.google_document_ai_layout_processor_id
        ):
            raise RuntimeError(
                "Google Document AI is selected but no processors are configured. "
                "Set GOOGLE_DOCUMENT_AI_INVOICE_PROCESSOR_ID and/or "
                "GOOGLE_DOCUMENT_AI_LAYOUT_PROCESSOR_ID in your environment."
            )

    def _analyze_with_google_document_ai(
        self, context: DocumentExtractionContext
    ) -> tuple[str, dict[str, Any]]:
        processor_id, processor_version = self._resolve_processor_for_doc_type(context.doc_type)
        return self._analyze_with_google_document_ai_processor(
            context,
            processor_id=processor_id,
            processor_version=processor_version,
        )

    def _analyze_with_google_document_ai_processor(
        self,
        context: DocumentExtractionContext,
        *,
        processor_id: str,
        processor_version: str | None,
    ) -> tuple[str, dict[str, Any]]:
        try:
            from google.api_core.client_options import ClientOptions
            from google.cloud import documentai
            from google.protobuf.json_format import MessageToDict
        except ImportError as exc:
            raise RuntimeError(
                "Google Document AI support requires the 'google-cloud-documentai' package. "
                "Install backend dependencies again after pulling this change."
            ) from exc

        project_id = self._settings.google_document_ai_project_id
        location = self._settings.google_document_ai_location
        client_options = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        client = documentai.DocumentProcessorServiceClient(client_options=client_options)

        if processor_version:
            name = client.processor_version_path(project_id, location, processor_id, processor_version)
            model_id = f"{processor_id}:{processor_version}"
        else:
            name = client.processor_path(project_id, location, processor_id)
            model_id = processor_id

        content, mime_type = self._prepare_document_input(context.absolute_path, processor_id)
        raw_document = documentai.RawDocument(content=content, mime_type=mime_type)

        request = documentai.ProcessRequest(name=name, raw_document=raw_document)
        result = client.process_document(
            request=request,
            timeout=self._settings.google_document_ai_timeout_seconds,
        )

        document_dict = MessageToDict(
            result.document._pb,
            preserving_proto_field_name=True,
        )
        analysis = self._document_to_analysis(context.doc_type, document_dict)
        return model_id, analysis

    def _resolve_processor_for_doc_type(self, doc_type: DocumentType) -> tuple[str, str | None]:
        if doc_type == DocumentType.INVOICE and self._settings.google_document_ai_invoice_processor_id:
            return (
                self._settings.google_document_ai_invoice_processor_id,
                self._settings.google_document_ai_invoice_processor_version,
            )
        if self._settings.google_document_ai_layout_processor_id:
            return (
                self._settings.google_document_ai_layout_processor_id,
                self._settings.google_document_ai_layout_processor_version,
            )
        if self._settings.google_document_ai_invoice_processor_id:
            return (
                self._settings.google_document_ai_invoice_processor_id,
                self._settings.google_document_ai_invoice_processor_version,
            )
        raise RuntimeError("No Google Document AI processor is configured for this document type.")

    def _guess_mime_type(self, path: str | Any) -> str:
        guess, _ = mimetypes.guess_type(str(path))
        return guess or "application/octet-stream"

    def _prepare_document_input(self, path: str | Any, processor_id: str) -> tuple[bytes, str]:
        file_path = path if hasattr(path, "read_bytes") else None
        mime_type = self._guess_mime_type(path)

        if (
            file_path is not None
            and isinstance(mime_type, str)
            and mime_type.startswith("image/")
            and processor_id == self._settings.google_document_ai_layout_processor_id
        ):
            return self._convert_image_to_pdf(file_path), "application/pdf"

        if file_path is not None:
            return file_path.read_bytes(), mime_type

        with open(path, "rb") as handle:
            return handle.read(), mime_type

    def _convert_image_to_pdf(self, path: Any) -> bytes:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "Google Document AI image conversion requires Pillow. "
                "Install backend dependencies again after pulling this change."
            ) from exc

        buffer = BytesIO()
        with Image.open(path) as image:
            pdf_image = image.convert("RGB")
            pdf_image.save(buffer, format="PDF")
        return buffer.getvalue()

    def _document_to_analysis(
        self,
        doc_type: DocumentType,
        document: dict[str, Any],
    ) -> dict[str, Any]:
        text = (document.get("text") or "").strip()
        pages = self._document_pages(document)
        if not text:
            text = self._document_layout_content(pages, document)

        analysis: dict[str, Any] = {
            "api_version": self._document_revision(document),
            "content": text,
            "pages": pages,
            "tables": self._document_tables(document),
            "documents": [],
            "metadata": {
                "provider": self.name,
                "page_count": len(pages),
                "entity_count": len(document.get("entities") or []),
            },
        }

        if doc_type == DocumentType.INVOICE:
            fields, confidence = self._document_invoice_fields(document)
            if fields:
                analysis["documents"] = [
                    {
                        "doc_type": "invoice",
                        "confidence": confidence,
                        "fields": fields,
                        "content": text,
                    }
                ]
        return analysis

    def _document_pages(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        if document.get("document_layout"):
            return self._document_layout_pages(document["document_layout"])

        text = document.get("text") or ""
        pages: list[dict[str, Any]] = []
        for index, page in enumerate(document.get("pages") or [], start=1):
            line_candidates = page.get("lines") or page.get("paragraphs") or page.get("tokens") or []
            lines: list[dict[str, Any]] = []
            for line in line_candidates:
                layout = line.get("layout") or line
                content = self._layout_text(text, layout).strip()
                if not content:
                    continue
                lines.append(
                    {
                        "content": content,
                        "bounding_regions": [{"page_number": index}],
                    }
                )
            pages.append({"page_number": index, "lines": lines})
        return pages

    def _document_tables(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        if document.get("document_layout"):
            return self._document_layout_tables(document["document_layout"])

        text = document.get("text") or ""
        tables: list[dict[str, Any]] = []
        table_index = 0
        for page_number, page in enumerate(document.get("pages") or [], start=1):
            for table in page.get("tables") or []:
                rows = self._table_rows(text, table)
                if not rows:
                    continue
                column_count = max((len(row) for row in rows), default=0)
                padded_rows = [row + [""] * (column_count - len(row)) for row in rows]
                cells: list[dict[str, Any]] = []
                for row_index, row in enumerate(padded_rows):
                    for column_index, content in enumerate(row):
                        cells.append(
                            {
                                "row_index": row_index,
                                "column_index": column_index,
                                "content": content,
                                "bounding_regions": [{"page_number": page_number}],
                            }
                        )
                tables.append(
                    {
                        "row_count": len(padded_rows),
                        "column_count": column_count,
                        "cells": cells,
                        "table_index": table_index,
                    }
                )
                table_index += 1
        return tables

    def _document_layout_pages(self, document_layout: dict[str, Any]) -> list[dict[str, Any]]:
        lines_by_page: dict[int, list[dict[str, Any]]] = {}

        for block in document_layout.get("blocks") or []:
            page_number = self._layout_block_page_number(block)
            for line in self._document_layout_block_lines(block):
                if not line:
                    continue
                lines_by_page.setdefault(page_number, []).append(
                    {
                        "content": line,
                        "bounding_regions": [{"page_number": page_number}],
                    }
                )

        return [
            {"page_number": page_number, "lines": lines}
            for page_number, lines in sorted(lines_by_page.items())
        ]

    def _document_layout_content(
        self,
        pages: list[dict[str, Any]],
        document: dict[str, Any],
    ) -> str:
        page_lines = [
            line.get("content", "").strip()
            for page in pages
            for line in page.get("lines") or []
            if isinstance(line.get("content"), str) and line.get("content", "").strip()
        ]
        if page_lines:
            return "\n".join(page_lines)

        layout = document.get("document_layout") or {}
        values: list[str] = []
        for block in layout.get("blocks") or []:
            values.extend(self._document_layout_block_lines(block))
        return "\n".join(value for value in values if value.strip())

    def _document_layout_tables(self, document_layout: dict[str, Any]) -> list[dict[str, Any]]:
        tables: list[dict[str, Any]] = []
        table_index = 0

        for block in document_layout.get("blocks") or []:
            table_block = block.get("table_block")
            if not isinstance(table_block, dict):
                continue

            rows = self._document_layout_block_rows(table_block)
            if not rows:
                continue

            column_count = max((len(row) for row in rows), default=0)
            padded_rows = [row + [""] * (column_count - len(row)) for row in rows]
            page_number = self._layout_block_page_number(block)
            cells: list[dict[str, Any]] = []
            for row_index, row in enumerate(padded_rows):
                for column_index, content in enumerate(row):
                    cells.append(
                        {
                            "row_index": row_index,
                            "column_index": column_index,
                            "content": content,
                            "bounding_regions": [{"page_number": page_number}],
                        }
                    )

            tables.append(
                {
                    "row_count": len(padded_rows),
                    "column_count": column_count,
                    "cells": cells,
                    "table_index": table_index,
                }
            )
            table_index += 1

        return tables

    def _document_layout_block_lines(self, block: dict[str, Any]) -> list[str]:
        table_block = block.get("table_block")
        if not isinstance(table_block, dict):
            return []

        lines: list[str] = []
        for row in table_block.get("body_rows") or []:
            values = [
                self._document_layout_cell_text(cell).strip()
                for cell in row.get("cells") or []
            ]
            joined = " ".join(value for value in values if value)
            if joined:
                lines.append(joined)
        return lines

    def _document_layout_block_rows(self, table_block: dict[str, Any]) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in table_block.get("header_rows") or []:
            values = [self._document_layout_cell_text(cell).strip() for cell in row.get("cells") or []]
            if any(values):
                rows.append(values)
        for row in table_block.get("body_rows") or []:
            values = [self._document_layout_cell_text(cell).strip() for cell in row.get("cells") or []]
            if any(values):
                rows.append(values)
        return rows

    def _document_layout_cell_text(self, cell: dict[str, Any]) -> str:
        parts: list[str] = []
        for block in cell.get("blocks") or []:
            text_block = block.get("text_block") or {}
            text = text_block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return " ".join(parts)

    def _layout_block_page_number(self, block: dict[str, Any]) -> int:
        page_span = block.get("page_span") or {}
        page_start = page_span.get("page_start")
        if page_start is None:
            return 1
        return int(page_start)

    def _table_rows(self, text: str, table: dict[str, Any]) -> list[list[str]]:
        rows: list[list[str]] = []
        for row in (table.get("header_rows") or []) + (table.get("body_rows") or []):
            values: list[str] = []
            for cell in row.get("cells") or []:
                cell_text = self._layout_text(text, cell.get("layout") or cell).strip()
                values.append(re.sub(r"\s+", " ", cell_text))
            if any(value for value in values):
                rows.append(values)
        return rows

    def _document_invoice_fields(self, document: dict[str, Any]) -> tuple[dict[str, Any], float]:
        fields: dict[str, Any] = {}
        confidences: list[float] = []

        for entity in document.get("entities") or []:
            normalized_type = self._normalize_entity_type(self._entity_type(entity))
            if "line_item" in normalized_type:
                continue

            field_name = self._INVOICE_FIELD_ALIASES.get(normalized_type)
            if field_name is None:
                continue

            field = self._entity_to_field(entity)
            if field is None:
                continue
            confidences.append(self._coerce_float(field.get("confidence")) or 0.0)
            self._assign_best_field(fields, field_name, field)

        line_items = self._document_invoice_line_items(document.get("entities") or [])
        if line_items:
            fields["Items"] = {
                "value_array": line_items,
                "confidence": self._average_confidence(
                    *(self._coerce_float(item.get("confidence")) for item in line_items)
                ),
            }

        confidence = self._average_confidence(*confidences) if confidences else 0.72
        return fields, confidence

    def _document_invoice_line_items(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for entity in entities:
            normalized_type = self._normalize_entity_type(self._entity_type(entity))
            if "line_item" not in normalized_type:
                continue

            properties: dict[str, Any] = {}
            for prop in entity.get("properties") or []:
                property_type = self._LINE_ITEM_FIELD_ALIASES.get(
                    self._normalize_entity_type(self._entity_type(prop))
                )
                if property_type is None:
                    continue
                field = self._entity_to_field(prop)
                if field is None:
                    continue
                self._assign_best_field(properties, property_type, field)

            if properties:
                items.append(
                    {
                        "value_object": properties,
                        "confidence": self._coerce_float(entity.get("confidence")) or 0.7,
                        "bounding_regions": [
                            {
                                "page_number": self._entity_page_number(entity),
                            }
                        ]
                        if self._entity_page_number(entity) is not None
                        else [],
                    }
                )
        return items

    def _augment_invoice_result_with_layout(
        self,
        context: DocumentExtractionContext,
        result: ProviderExtractionResult,
        *,
        invoice_model_id: str,
    ) -> ProviderExtractionResult:
        if not self._invoice_lines_need_layout_backfill(result):
            return result

        layout_processor_id = self._settings.google_document_ai_layout_processor_id
        layout_processor_version = self._settings.google_document_ai_layout_processor_version
        if not layout_processor_id:
            return result

        invoice_processor = (
            self._settings.google_document_ai_invoice_processor_id,
            self._settings.google_document_ai_invoice_processor_version,
        )
        layout_processor = (layout_processor_id, layout_processor_version)
        invoice = CanonicalInvoice.model_validate(result.canonical_payload)
        merged_lines = invoice.lines
        note: str | None = None
        raw_payload = dict(result.raw_payload)
        layout_low_confidence_fields: list[Any] = []

        text_lines = self._extract_invoice_line_identities_from_text(
            raw_payload.get("analysis_result") if isinstance(raw_payload.get("analysis_result"), dict) else {}
        )
        text_quantity_backfill_used = any(line.quantity != Decimal("0.00") for line in text_lines)
        candidate_lines = self._merge_invoice_lines(invoice.lines, text_lines)
        if self._count_meaningful_invoice_lines(candidate_lines) > self._count_meaningful_invoice_lines(
            invoice.lines
        ):
            merged_lines = candidate_lines
            note = (
                "Invoice line items were backfilled from Google Document AI OCR text because "
                "the invoice processor returned sparse row detail."
            )
            raw_payload["text_identity_backfill_used"] = True
            if text_quantity_backfill_used:
                raw_payload["text_quantity_backfill_used"] = True

        if (
            self._count_meaningful_invoice_lines(merged_lines) <= self._count_meaningful_invoice_lines(invoice.lines)
            and layout_processor != invoice_processor
        ):
            try:
                layout_model_id, layout_analysis = self._analyze_with_google_document_ai_processor(
                    context,
                    processor_id=layout_processor_id,
                    processor_version=layout_processor_version,
                )
            except Exception:
                layout_model_id = None
                layout_analysis = None
            else:
                layout_lines = self._extract_invoice_lines_from_tables(
                    layout_analysis,
                    low_confidence_fields=layout_low_confidence_fields,
                )
                candidate_lines = self._merge_invoice_lines(invoice.lines, layout_lines)
                if self._count_meaningful_invoice_lines(candidate_lines) > self._count_meaningful_invoice_lines(
                    invoice.lines
                ):
                    merged_lines = candidate_lines
                    note = (
                        "Invoice line items were backfilled from Google Document AI layout tables because "
                        "the invoice processor returned sparse row detail."
                    )
                    raw_payload["layout_backfill_used"] = True
                    raw_payload["layout_model_id"] = layout_model_id
                    raw_payload["layout_analysis_result"] = layout_analysis

        if self._count_meaningful_invoice_lines(merged_lines) <= self._count_meaningful_invoice_lines(
            invoice.lines
        ):
            return result

        invoice.lines = merged_lines
        invoice.header.discount_total = sum((line.discount_amount for line in merged_lines), start=Decimal("0.00"))
        invoice.tax_summaries = self._build_tax_summaries(merged_lines, invoice.header.tax_total)
        invoice.discount_summaries = self._build_discount_summaries(merged_lines)
        invoice.department_summaries = self._build_department_summaries(merged_lines)

        if note and note not in invoice.audit.notes:
            invoice.audit.notes.append(note)
        if raw_payload.get("text_quantity_backfill_used"):
            quantity_note = (
                "Invoice quantities were heuristically backfilled from the Google Document AI OCR text because "
                "the invoice processor did not return quantity values."
            )
            if quantity_note not in invoice.audit.notes:
                invoice.audit.notes.append(quantity_note)

        combined_low_confidence = invoice.low_confidence_fields + [
            field
            for field in layout_low_confidence_fields
            if field.field_path not in {existing.field_path for existing in invoice.low_confidence_fields}
        ]
        invoice.low_confidence_fields = combined_low_confidence

        raw_payload["invoice_model_id"] = invoice_model_id

        result.raw_payload = raw_payload
        result.canonical_payload = invoice.model_dump(mode="python")
        result.low_confidence_fields = invoice.low_confidence_fields
        return result

    def _invoice_lines_need_layout_backfill(self, result: ProviderExtractionResult) -> bool:
        payload = result.canonical_payload
        lines = payload.get("lines") if isinstance(payload, dict) else None
        if not isinstance(lines, list) or not lines:
            return True
        return self._count_meaningful_invoice_lines(lines) * 2 < len(lines)

    def _count_meaningful_invoice_lines(self, lines: list[InvoiceLine] | list[dict[str, Any]]) -> int:
        meaningful = 0
        for line in lines:
            if isinstance(line, InvoiceLine):
                product_code = (line.product_code or "").strip()
                description = line.description.strip()
            elif isinstance(line, dict):
                product_code = str(line.get("product_code") or "").strip()
                description = str(line.get("description") or "").strip()
            else:
                continue

            if product_code:
                meaningful += 1
                continue
            if description and not self._is_placeholder_invoice_description(description) and re.search(
                r"[A-Za-z]",
                description,
            ):
                meaningful += 1
        return meaningful

    def _is_placeholder_invoice_description(self, value: str) -> bool:
        return bool(re.fullmatch(r"Line\s+\d+", value.strip(), flags=re.IGNORECASE))

    def _merge_invoice_lines(
        self,
        primary_lines: list[InvoiceLine],
        layout_lines: list[InvoiceLine],
    ) -> list[InvoiceLine]:
        if not primary_lines:
            return layout_lines
        if len(primary_lines) != len(layout_lines):
            if self._count_meaningful_invoice_lines(layout_lines) > self._count_meaningful_invoice_lines(
                primary_lines
            ):
                return layout_lines
            return primary_lines

        zero = Decimal("0.00")
        merged: list[InvoiceLine] = []
        for index, (primary, layout) in enumerate(zip(primary_lines, layout_lines, strict=False), start=1):
            primary_description = primary.description.strip()
            use_layout_description = (
                not primary_description or self._is_placeholder_invoice_description(primary_description)
            )
            quantity = primary.quantity if primary.quantity != zero else layout.quantity
            unit_price = primary.unit_price if primary.unit_price != zero else layout.unit_price
            extended_amount = (
                primary.extended_amount if primary.extended_amount != zero else layout.extended_amount
            )
            discount_amount = (
                primary.discount_amount if primary.discount_amount != zero else layout.discount_amount
            )
            net_amount = primary.net_amount if primary.net_amount != zero else layout.net_amount
            vat_rate = primary.vat_rate if primary.vat_rate != zero else layout.vat_rate
            vat_amount = primary.vat_amount if primary.vat_amount != zero else layout.vat_amount
            gross_amount = primary.gross_amount if primary.gross_amount != zero else layout.gross_amount
            if unit_price == zero and net_amount != zero and quantity != zero:
                unit_price = (net_amount / quantity).quantize(Decimal("0.0001"))
            if extended_amount == zero and unit_price != zero and quantity != zero:
                extended_amount = unit_price * quantity
            if net_amount == zero and extended_amount != zero:
                net_amount = extended_amount
            if gross_amount == zero and net_amount != zero:
                gross_amount = net_amount + vat_amount
            merged.append(
                InvoiceLine(
                    line_number=index,
                    page_number=primary.page_number or layout.page_number,
                    product_code=(primary.product_code or layout.product_code or None),
                    description=layout.description if use_layout_description else primary.description,
                    department_code=primary.department_code or layout.department_code,
                    department_name=primary.department_name or layout.department_name,
                    quantity=quantity,
                    unit_of_measure=primary.unit_of_measure or layout.unit_of_measure,
                    unit_price=unit_price,
                    extended_amount=extended_amount,
                    discount_amount=discount_amount,
                    net_amount=net_amount,
                    vat_rate=vat_rate,
                    vat_amount=vat_amount,
                    gross_amount=gross_amount,
                    delivery_reference=primary.delivery_reference or layout.delivery_reference,
                    source_reference=primary.source_reference or layout.source_reference,
                    confidence_scores={**layout.confidence_scores, **primary.confidence_scores},
                )
            )
        return merged

    def _extract_invoice_lines_from_tables(
        self,
        analysis: dict[str, Any],
        *,
        low_confidence_fields: list[Any],
    ) -> list[InvoiceLine]:
        zero = Decimal("0.00")
        lines: list[InvoiceLine] = []
        for table in self._iter_table_matrices(analysis):
            rows = table.get("rows") or []
            header_index, header_map = self._invoice_table_header(rows)
            if header_index is None or not header_map:
                continue

            for row_index, row in enumerate(rows[header_index + 1 :], start=header_index + 1):
                if not any(cell.strip() for cell in row):
                    continue

                description = self._row_value(row, header_map, "description")
                product_code = self._row_value(row, header_map, "product_code") or self._find_row_product_code(row)
                if description and self._looks_like_total_row(description):
                    continue
                if not description and not product_code:
                    continue

                quantity = self._parse_decimal(self._row_value(row, header_map, "quantity")) or zero
                unit_price = self._parse_decimal(self._row_value(row, header_map, "unit_price"))
                net_amount = self._parse_decimal(self._row_value(row, header_map, "net_amount"))
                vat_amount = self._parse_decimal(self._row_value(row, header_map, "vat_amount")) or zero
                gross_amount = self._parse_decimal(self._row_value(row, header_map, "gross_amount"))

                if gross_amount is None and net_amount is not None:
                    gross_amount = net_amount + vat_amount
                if net_amount is None and gross_amount is not None:
                    net_amount = max(gross_amount - vat_amount, zero)
                if net_amount is None and unit_price is not None and quantity != zero:
                    net_amount = unit_price * quantity
                if unit_price is None and net_amount is not None and quantity != zero:
                    unit_price = net_amount / quantity

                if net_amount is None and gross_amount is None and unit_price is None:
                    continue

                description = re.sub(r"\s+", " ", (description or product_code or "").strip())
                if not description:
                    continue

                unit_price = unit_price or zero
                net_amount = net_amount or zero
                gross_amount = gross_amount or (net_amount + vat_amount)
                tax_rate = zero
                if net_amount != zero and vat_amount != zero:
                    tax_rate = self._normalize_rate((vat_amount / net_amount) * Decimal("100")) or zero

                page_number = table.get("page_number")
                line = InvoiceLine(
                    line_number=len(lines) + 1,
                    page_number=page_number,
                    product_code=product_code or None,
                    description=description,
                    department_code=None,
                    department_name=None,
                    quantity=quantity,
                    unit_of_measure=self._row_value(row, header_map, "unit_of_measure") or None,
                    unit_price=unit_price,
                    extended_amount=net_amount,
                    discount_amount=zero,
                    net_amount=net_amount,
                    vat_rate=tax_rate,
                    vat_amount=vat_amount,
                    gross_amount=gross_amount,
                    delivery_reference=None,
                    source_reference=f"google-layout-table-{table['table_index']}-row-{row_index}",
                    confidence_scores={},
                )
                if quantity == zero:
                    self._flag_if_low(
                        low_confidence_fields,
                        f"lines[{len(lines)}].quantity",
                        0.42,
                        str(quantity),
                        page_number,
                        comment="Quantity could not be parsed cleanly from the Google layout table row.",
                    )
                lines.append(line)
            if lines:
                break
        return lines

    def _extract_invoice_line_identities_from_text(
        self,
        analysis: dict[str, Any],
    ) -> list[InvoiceLine]:
        content = self._analysis_content(analysis)
        raw_lines = [re.sub(r"\s+", " ", line).strip() for line in content.splitlines() if line.strip()]
        if not raw_lines:
            return []

        codes: list[str] = []
        descriptions: list[str] = []
        start_index: int | None = None
        for index, raw_line in enumerate(raw_lines):
            if self._looks_like_product_code(raw_line):
                start_index = index
                break
        if start_index is None:
            return []

        cursor = start_index
        while cursor < len(raw_lines) and self._looks_like_product_code(raw_lines[cursor]):
            codes.append(raw_lines[cursor].strip().replace(" ", ""))
            cursor += 1

        while cursor < len(raw_lines):
            normalized = self._normalize_label(raw_lines[cursor])
            if normalized in {
                "pack size",
                "quantity",
                "unit cost",
                "dept code",
                "vat rate",
                "goods per",
                "drs",
                "charges",
                "vat code",
            }:
                break
            if self._looks_like_total_row(raw_lines[cursor]) or self._looks_like_product_code(raw_lines[cursor]):
                break
            if re.search(r"[A-Za-z]", raw_lines[cursor]):
                descriptions.append(raw_lines[cursor].strip())
            cursor += 1

        if not codes or len(codes) != len(descriptions):
            return []

        zero = Decimal("0.00")
        quantities = self._extract_invoice_quantities_from_text(raw_lines[cursor:], expected_count=len(codes))
        return [
            InvoiceLine(
                line_number=index,
                page_number=1,
                product_code=code,
                description=description,
                department_code=None,
                department_name=None,
                quantity=quantities[index - 1] if index - 1 < len(quantities) else zero,
                unit_of_measure=None,
                unit_price=zero,
                extended_amount=zero,
                discount_amount=zero,
                net_amount=zero,
                vat_rate=zero,
                vat_amount=zero,
                gross_amount=zero,
                delivery_reference=None,
                source_reference=f"google-text-line-{index}",
                confidence_scores={},
            )
            for index, (code, description) in enumerate(zip(codes, descriptions, strict=False), start=1)
        ]

    def _extract_invoice_quantities_from_text(
        self,
        trailing_lines: list[str],
        *,
        expected_count: int,
    ) -> list[Decimal]:
        if expected_count <= 0:
            return []

        normalized_lines = [self._normalize_label(line) for line in trailing_lines]
        if not any(normalized in {"quantity", "qty", "invoice qty", "invoiced qty"} for normalized in normalized_lines):
            return []

        quantity_candidates: list[Decimal] = []
        for raw_line in trailing_lines:
            compact = raw_line.strip().replace(" ", "")
            if not compact or len(compact) > 6:
                continue
            if not re.fullmatch(r"\d+(?:\.\d+)?", compact):
                continue
            quantity = self._parse_decimal(compact)
            if quantity is None or quantity <= Decimal("0.00") or quantity > Decimal("1000"):
                continue
            quantity_candidates.append(quantity)

        if len(quantity_candidates) == expected_count:
            return quantity_candidates
        if not quantity_candidates:
            return []

        dominant_quantity, dominant_count = Counter(quantity_candidates).most_common(1)[0]
        if dominant_count >= expected_count:
            return [dominant_quantity] * expected_count
        return []

    def _invoice_table_header(
        self,
        rows: list[list[str]],
    ) -> tuple[int | None, dict[str, int]]:
        best_index: int | None = None
        best_map: dict[str, int] = {}
        best_score = 0
        for index, row in enumerate(rows[:3]):
            header_map = self._invoice_table_header_map(row)
            score = len(header_map)
            if score > best_score and ("description" in header_map or "product_code" in header_map):
                best_index = index
                best_map = header_map
                best_score = score
        if best_score < 2:
            return None, {}
        return best_index, best_map

    def _invoice_table_header_map(self, header_row: list[str]) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for index, header in enumerate(header_row):
            normalized = self._normalize_label(header)
            if not normalized:
                continue
            if any(token in normalized for token in ("sku", "product code", "item code", "code")):
                mapping["product_code"] = index
                continue
            if any(token in normalized for token in ("qty", "quantity", "invoice qty", "invoiced qty")):
                mapping["quantity"] = index
                continue
            if "unit price" in normalized or normalized == "price":
                mapping["unit_price"] = index
                continue
            if any(token in normalized for token in ("vat amount", "tax amount", "vat", "tax")):
                mapping["vat_amount"] = index
                continue
            if any(
                token in normalized
                for token in ("gross", "line total", "total invoice", "gross amount", "amount incl", "inc vat")
            ) or normalized == "total":
                mapping["gross_amount"] = index
                continue
            if any(
                token in normalized
                for token in ("pre amount", "net c", "net amount", "net", "amount ex", "subtotal", "line amount")
            ) or normalized == "amount":
                mapping["net_amount"] = index
                continue
            if any(token in normalized for token in ("uom", "unit")) and "price" not in normalized:
                mapping["unit_of_measure"] = index
                continue
            if any(
                token in normalized
                for token in (
                    "description",
                    "item description",
                    "product description",
                    "product name",
                    "product",
                    "item",
                    "name",
                )
            ):
                mapping["description"] = index
        return mapping

    def _find_row_product_code(self, row: list[str]) -> str:
        for cell in row:
            if self._looks_like_product_code(cell):
                return cell.strip()
        return ""

    def _looks_like_product_code(self, value: str) -> bool:
        normalized = value.strip().replace(" ", "")
        return bool(re.fullmatch(r"[A-Z0-9]{3,20}", normalized) and re.search(r"\d", normalized))

    def _entity_to_field(self, entity: dict[str, Any]) -> dict[str, Any] | None:
        page_number = self._entity_page_number(entity)
        confidence = self._coerce_float(entity.get("confidence")) or 0.7
        mention_text = (entity.get("mention_text") or "").strip()
        normalized_value = entity.get("normalized_value") or {}

        date_value = self._entity_date_value(entity)
        if date_value is not None:
            field = {
                "value_date": date_value.isoformat(),
                "content": mention_text or date_value.isoformat(),
                "confidence": confidence,
            }
        else:
            money_value = self._entity_money_value(entity)
            if money_value is not None:
                amount, currency_code = money_value
                field = {
                    "value_currency": {
                        "amount": float(amount),
                        "currency_code": currency_code
                        or self._settings.azure_document_intelligence_default_currency,
                    },
                    "content": mention_text or str(amount),
                    "confidence": confidence,
                }
            else:
                number_value = self._entity_decimal_value(entity)
                if number_value is not None and self._looks_numeric_entity(self._entity_type(entity)):
                    field = {
                        "value_number": float(number_value),
                        "content": mention_text or str(number_value),
                        "confidence": confidence,
                    }
                else:
                    value = (
                        normalized_value.get("text")
                        or mention_text
                        or self._normalized_value_text(normalized_value)
                    )
                    if not isinstance(value, str) or not value.strip():
                        return None
                    field = {
                        "value_string": value.strip(),
                        "content": value.strip(),
                        "confidence": confidence,
                    }

        if page_number is not None:
            field["bounding_regions"] = [{"page_number": page_number}]
        return field

    def _assign_best_field(self, fields: dict[str, Any], key: str, field: dict[str, Any]) -> None:
        existing = fields.get(key)
        if existing is None:
            fields[key] = field
            return
        if (self._coerce_float(field.get("confidence")) or 0.0) >= (
            self._coerce_float(existing.get("confidence")) or 0.0
        ):
            fields[key] = field

    def _layout_text(self, document_text: str, layout: dict[str, Any]) -> str:
        return self._text_anchor_text(document_text, (layout.get("text_anchor") or {}))

    def _text_anchor_text(self, document_text: str, text_anchor: dict[str, Any]) -> str:
        segments = text_anchor.get("text_segments") or []
        if not segments:
            return ""
        parts: list[str] = []
        for segment in segments:
            start = int(segment.get("start_index") or 0)
            end = int(segment.get("end_index") or 0)
            if end <= start:
                continue
            parts.append(document_text[start:end])
        return "".join(parts)

    def _entity_page_number(self, entity: dict[str, Any]) -> int | None:
        page_anchor = entity.get("page_anchor") or {}
        page_refs = page_anchor.get("page_refs") or []
        if not page_refs:
            return None
        page_value = page_refs[0].get("page")
        if page_value is None:
            return 1
        return int(page_value) + 1

    def _entity_date_value(self, entity: dict[str, Any]):
        normalized_value = entity.get("normalized_value") or {}
        date_value = normalized_value.get("date_value") or {}
        if isinstance(date_value, dict) and date_value.get("year") and date_value.get("month") and date_value.get("day"):
            return self._parse_date(
                f"{int(date_value['year']):04d}-{int(date_value['month']):02d}-{int(date_value['day']):02d}"
            )
        normalized_text = normalized_value.get("text")
        if isinstance(normalized_text, str):
            return self._parse_date(normalized_text)
        mention_text = entity.get("mention_text")
        if isinstance(mention_text, str):
            return self._parse_date(mention_text)
        return None

    def _entity_money_value(self, entity: dict[str, Any]) -> tuple[Decimal, str | None] | None:
        normalized_value = entity.get("normalized_value") or {}
        money_value = normalized_value.get("money_value")
        if isinstance(money_value, dict) and (
            money_value.get("units") is not None
            or money_value.get("nanos") is not None
            or money_value.get("currency_code")
        ):
            units = Decimal(str(money_value.get("units") or 0))
            nanos = Decimal(str(money_value.get("nanos") or 0)) / Decimal("1000000000")
            return units + nanos, money_value.get("currency_code")
        return None

    def _entity_decimal_value(self, entity: dict[str, Any]) -> Decimal | None:
        normalized_value = entity.get("normalized_value") or {}
        for key in ("float_value", "integer_value", "text"):
            value = normalized_value.get(key)
            parsed = self._parse_decimal(value)
            if parsed is not None:
                return parsed
        return self._parse_decimal(entity.get("mention_text"))

    def _normalized_value_text(self, normalized_value: dict[str, Any]) -> str | None:
        for key in ("text", "boolean_value"):
            value = normalized_value.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _entity_type(self, entity: dict[str, Any]) -> str | None:
        entity_type = entity.get("type")
        if isinstance(entity_type, str) and entity_type.strip():
            return entity_type
        alternate_type = entity.get("type_")
        if isinstance(alternate_type, str) and alternate_type.strip():
            return alternate_type
        return None

    def _looks_numeric_entity(self, entity_type: str | None) -> bool:
        normalized = self._normalize_entity_type(entity_type)
        return any(
            token in normalized
            for token in ("amount", "price", "quantity", "qty", "tax", "rate", "subtotal", "total")
        )

    def _normalize_entity_type(self, value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")

    def _document_revision(self, document: dict[str, Any]) -> str:
        revisions = document.get("revisions") or []
        for revision in revisions:
            processor = revision.get("processor")
            if isinstance(processor, str) and processor.strip():
                return processor.strip()
        return "google-document-ai"

    def _build_invoice_result_relaxed(
        self,
        context: DocumentExtractionContext,
        analysis: dict[str, Any],
        model_id: str,
    ) -> ProviderExtractionResult:
        zero = Decimal("0.00")
        fields, document_confidence = self._first_document_fields(analysis)
        content = self._analysis_content(analysis)
        page_count = len(analysis.get("pages") or [])
        low_confidence_fields = []

        invoice_number, invoice_number_confidence, invoice_number_page = self._select_text(
            fields,
            candidates=("InvoiceId", "InvoiceNumber"),
            text_sources=((context.source_filename, 0.68), (content, 0.74)),
            regexes=(
                r"(?:invoice(?:\s*(?:number|no|#))?|inv\s*#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
                r"invoice[_\-\s]+([A-Z0-9][A-Z0-9\-/]{2,})",
            ),
        )
        if invoice_number and not self._is_probable_invoice_number(invoice_number):
            invoice_number = None
            invoice_number_confidence = None
            invoice_number_page = None
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
                r"(?:sub\s*total|subtotal|net\s*amount|net\s*total|total\s*ex\s*vat)\s*[:#-]?\s*[A-Z$Â£â‚¬€£]*\s*([0-9,]+\.\d{2})",
            ),
        )
        tax_total, tax_total_confidence, tax_total_page = self._select_decimal(
            fields,
            candidates=("TotalTax", "Tax", "VatTotal"),
            text_sources=((content, 0.72),),
            regexes=(
                r"(?:total\s*tax|tax\s*total|vat\s*total|vat|tax)\s*[:#-]?\s*[A-Z$Â£â‚¬€£]*\s*([0-9,]+\.\d{2})",
            ),
        )
        gross_total, gross_total_confidence, gross_total_page = self._select_decimal(
            fields,
            candidates=("InvoiceTotal", "TotalAmount", "AmountDue"),
            text_sources=((content, 0.74),),
            regexes=(
                r"(?:invoice\s*total|gross\s*total|grand\s*total|amount\s*due|total\s*due|balance\s*due)\s*[:#-]?\s*[A-Z$Â£â‚¬€£]*\s*([0-9,]+\.\d{2})",
            ),
        )

        if subtotal_amount is None:
            subtotal_amount, subtotal_confidence = self._best_amount_for_lines(
                content,
                ("subtotal", "sub total", "net total", "net amount", "total ex vat"),
                0.44,
            )
        if tax_total is None:
            tax_total, tax_total_confidence = self._best_amount_for_lines(content, ("vat", "tax"), 0.4)
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
            subtotal_amount = max(gross_total - tax_total, zero)
            subtotal_confidence = min(gross_total_confidence or 0.35, tax_total_confidence or 0.35)
        if tax_total is None and gross_total is not None and subtotal_amount is not None:
            tax_total = max(gross_total - subtotal_amount, zero)
            tax_total_confidence = min(gross_total_confidence or 0.35, subtotal_confidence or 0.35)

        if subtotal_amount is None and gross_total is not None:
            subtotal_amount = gross_total
            subtotal_confidence = 0.18
            tax_total = zero if tax_total is None else tax_total
            tax_total_confidence = tax_total_confidence or 0.18
        if gross_total is None and subtotal_amount is not None:
            tax_total = tax_total or zero
            tax_total_confidence = tax_total_confidence or 0.18
            gross_total = subtotal_amount + tax_total
            gross_total_confidence = min(subtotal_confidence or 0.18, tax_total_confidence)

        if subtotal_amount is None:
            subtotal_amount = zero
            subtotal_confidence = 0.12
        if tax_total is None:
            tax_total = zero
            tax_total_confidence = 0.12
        if gross_total is None:
            gross_total = subtotal_amount + tax_total
            gross_total_confidence = min(subtotal_confidence or 0.12, tax_total_confidence or 0.12)

        lines = self._extract_invoice_lines(
            fields.get("Items"),
            low_confidence_fields=low_confidence_fields,
        )
        if not lines and subtotal_amount == zero and gross_total == zero:
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
                comment=(
                    f"{self._provider_display_name()} could not confidently read the invoice number, "
                    "so a fallback identifier was used."
                ),
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
                comment=(
                    f"{self._provider_display_name()} could not confidently read the invoice date, "
                    "so a fallback date was used."
                ),
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
            comment=(
                f"{self._provider_display_name()} needed a fallback for the store number."
                if store_number == "UNKNOWN"
                else None
            ),
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
            comment=(
                f"Invoice subtotal was backfilled from {self._provider_display_name()} text heuristics."
                if subtotal_confidence is not None and subtotal_confidence < 0.5
                else None
            ),
        )
        self._flag_if_low(
            low_confidence_fields,
            "header.tax_total",
            tax_total_confidence,
            str(tax_total),
            tax_total_page,
            comment=(
                f"Invoice tax total was backfilled from {self._provider_display_name()} text heuristics."
                if tax_total_confidence is not None and tax_total_confidence < 0.5
                else None
            ),
        )
        self._flag_if_low(
            low_confidence_fields,
            "header.gross_total",
            gross_total_confidence,
            str(gross_total),
            gross_total_page,
            comment=(
                f"Invoice gross total was backfilled from {self._provider_display_name()} text heuristics."
                if gross_total_confidence is not None and gross_total_confidence < 0.5
                else None
            ),
        )

        notes = [self._processed_with_note(model_id)]
        if any(
            field.field_path in {"header.subtotal_amount", "header.tax_total", "header.gross_total"}
            for field in low_confidence_fields
        ):
            notes.append(
                f"Invoice totals were partially backfilled because {self._provider_display_name()} "
                "could not read them cleanly."
            )

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
                discount_total=sum((line.discount_amount for line in lines), start=zero),
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

    def _is_probable_invoice_number(self, value: str) -> bool:
        normalized = self._normalize_label(value)
        if normalized in {
            "date",
            "invoice",
            "number",
            "invoice_date",
            "invoice_number",
            "total",
            "subtotal",
            "amount",
            "due",
        }:
            return False
        compact = re.sub(r"[^A-Za-z0-9]", "", value)
        if len(compact) < 3:
            return False
        if any(char.isdigit() for char in value):
            return True
        return any(separator in value for separator in ("-", "/"))

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
            (r"(?:sub\s*total|subtotal|net\s*total)\s*[:#-]?\s*[A-Z$EURGBP£€]*\s*([0-9,]+\.\d{2})",),
            0.7,
        )
        tax_total, _ = self._regex_pick_decimal(
            content,
            (r"(?:tax\s*total|total\s*tax|vat\s*total|vat)\s*[:#-]?\s*[A-Z$EURGBP£€]*\s*([0-9,]+\.\d{2})",),
            0.68,
        )
        gross_total, _ = self._regex_pick_decimal(
            content,
            (r"(?:gross\s*total|grand\s*total|delivery\s*total|total)\s*[:#-]?\s*[A-Z$EURGBP£€]*\s*([0-9,]+\.\d{2})",),
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
                comment=(
                    f"{self._provider_display_name()} could not read a docket number, "
                    "so a synthetic identifier was created."
                ),
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
                comment=(
                    f"{self._provider_display_name()} could not read a docket date confidently, "
                    "so a fallback date was used."
                ),
            )

        if subtotal_amount == Decimal("0.00") and not lines:
            self._flag_if_low(
                low_confidence_fields,
                "subtotal_amount",
                0.18,
                "0.00",
                1 if page_count else None,
                comment="No readable totals were found on the uploaded docket.",
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

        notes = [self._processed_with_note(model_id)]
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
