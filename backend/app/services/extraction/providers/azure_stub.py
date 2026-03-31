from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.config import Settings, get_settings
from app.schemas.canonical import (
    AccountingTemplateColumn,
    AccountingTemplateDefinition,
    AuditMetadata,
    CanonicalInvoice,
    DeliveryDocket,
    DeliveryLine,
    DeliverySummary,
    DepartmentSummary,
    DiscountSummary,
    DocumentType,
    FieldConfidence,
    InvoiceHeader,
    InvoiceLine,
    ProviderExtractionResult,
    Store,
    Supplier,
    TaxSummary,
)
from app.services.extraction.providers.base import (
    DocumentExtractionContext,
    DocumentExtractionProvider,
)


ZERO = Decimal("0.00")
ONE_HUNDRED = Decimal("100")

DEFAULT_TEMPLATE_COLUMNS: list[tuple[str, str | None, bool, str | None]] = [
    ("Document Number", "invoice_number", True, None),
    ("Document Date", "invoice_date", True, None),
    ("Supplier", "supplier_name", True, None),
    ("Supplier Account", "account_number", True, None),
    ("Store Number", "store_number", True, None),
    ("Docket Number", "docket_number", False, ""),
    ("SKU", "product_code", False, ""),
    ("Description", "description", True, None),
    ("Department", "department_code", False, ""),
    ("Invoiced Qty", "invoiced_quantity", True, "0"),
    ("Delivered Qty", "delivered_quantity", False, "0"),
    ("Unit Price", "unit_price", True, "0.00"),
    ("Invoice Net", "invoice_net_amount", True, "0.00"),
    ("Delivery Net", "delivery_net_amount", False, "0.00"),
    ("VAT Rate", "vat_rate", True, "0.00"),
    ("VAT Amount", "vat_amount", True, "0.00"),
    ("Gross Amount", "gross_amount", True, "0.00"),
    ("Match Status", "match_status", True, "review_required"),
    ("Exception Reasons", "exception_reasons", False, ""),
    ("Approval Status", "approval_status", True, "review_required"),
]

TEMPLATE_FIELD_ALIASES: list[tuple[tuple[str, ...], str]] = [
    (("document number", "invoice number", "document no", "invoice id"), "invoice_number"),
    (("document date", "invoice date", "posting date"), "invoice_date"),
    (("supplier", "vendor"), "supplier_name"),
    (("supplier account", "account number", "vendor account"), "account_number"),
    (("store", "store number", "branch", "branch number"), "store_number"),
    (("docket", "docket number", "delivery docket"), "docket_number"),
    (("sku", "product code", "item code", "product"), "product_code"),
    (("description", "item description", "product description"), "description"),
    (("department", "dept", "department code"), "department_code"),
    (("invoiced qty", "invoice qty", "qty invoiced"), "invoiced_quantity"),
    (("delivered qty", "delivery qty", "qty delivered"), "delivered_quantity"),
    (("unit price", "price per unit", "price"), "unit_price"),
    (("invoice net", "net amount", "net"), "invoice_net_amount"),
    (("delivery net",), "delivery_net_amount"),
    (("vat rate", "tax rate"), "vat_rate"),
    (("vat amount", "tax amount"), "vat_amount"),
    (("gross amount", "gross", "total amount"), "gross_amount"),
    (("match status",), "match_status"),
    (("exception reasons", "exceptions"), "exception_reasons"),
    (("approval status", "approval"), "approval_status"),
]


class AzureDocumentIntelligenceProvider(DocumentExtractionProvider):
    name = "azure_document_intelligence"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def extract(self, context: DocumentExtractionContext) -> ProviderExtractionResult:
        self._ensure_configuration()
        model_id, analysis = self._analyze_with_azure(context)

        if context.doc_type == DocumentType.INVOICE:
            return self._build_invoice_result(context, analysis, model_id)
        if context.doc_type == DocumentType.DELIVERY_DOCKET:
            return self._build_delivery_docket_result(context, analysis, model_id)
        if context.doc_type == DocumentType.ACCOUNTING_TEMPLATE:
            return self._build_accounting_template_result(context, analysis, model_id)
        return self._build_unknown_result(context, analysis, model_id)

    def _ensure_configuration(self) -> None:
        if (
            not self._settings.azure_document_intelligence_endpoint
            or not self._settings.azure_document_intelligence_key
        ):
            raise RuntimeError(
                "Azure Document Intelligence is selected but not configured. "
                "Set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and "
                "AZURE_DOCUMENT_INTELLIGENCE_KEY in your environment."
            )

    def _analyze_with_azure(
        self, context: DocumentExtractionContext
    ) -> tuple[str, dict[str, Any]]:
        try:
            from azure.ai.documentintelligence import DocumentIntelligenceClient
            from azure.core.credentials import AzureKeyCredential
        except ImportError as exc:
            raise RuntimeError(
                "Azure Document Intelligence support requires the "
                "'azure-ai-documentintelligence' package. "
                "Install backend dependencies again after pulling this change."
            ) from exc

        client = DocumentIntelligenceClient(
            endpoint=self._settings.azure_document_intelligence_endpoint,
            credential=AzureKeyCredential(self._settings.azure_document_intelligence_key),
        )
        model_id = self._resolve_model_id(context.doc_type)
        with context.absolute_path.open("rb") as handle:
            poller = client.begin_analyze_document(model_id=model_id, body=handle)
            result = poller.result()
        return model_id, self._to_plain_data(result)

    def _resolve_model_id(self, doc_type: DocumentType) -> str:
        if doc_type == DocumentType.INVOICE:
            return self._settings.azure_document_intelligence_invoice_model_id
        return self._settings.azure_document_intelligence_layout_model_id

    def _build_invoice_result(
        self,
        context: DocumentExtractionContext,
        analysis: dict[str, Any],
        model_id: str,
    ) -> ProviderExtractionResult:
        fields, document_confidence = self._first_document_fields(analysis)
        content = self._analysis_content(analysis)
        low_confidence_fields: list[FieldConfidence] = []
        page_count = len(analysis.get("pages") or [])

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
            regexes=(r"(?:store(?:\s*(?:number|no|#|id))?)\s*[:#-]?\s*(\d{2,})",),
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
            regexes=(r"(?:sub\s*total|subtotal|net\s*amount)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",),
        )
        tax_total, tax_total_confidence, tax_total_page = self._select_decimal(
            fields,
            candidates=("TotalTax", "Tax", "VatTotal"),
            text_sources=((content, 0.72),),
            regexes=(r"(?:total\s*tax|tax\s*total|vat\s*total|vat)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",),
        )
        gross_total, gross_total_confidence, gross_total_page = self._select_decimal(
            fields,
            candidates=("InvoiceTotal", "TotalAmount", "AmountDue"),
            text_sources=((content, 0.74),),
            regexes=(
                r"(?:invoice\s*total|gross\s*total|grand\s*total|amount\s*due|total\s*due)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",
            ),
        )

        lines = self._extract_invoice_lines(
            fields.get("Items"),
            low_confidence_fields=low_confidence_fields,
        )
        if subtotal_amount is None and lines:
            subtotal_amount = sum((line.net_amount for line in lines), start=ZERO)
            subtotal_confidence = 0.6
        if tax_total is None and lines:
            tax_total = sum((line.vat_amount for line in lines), start=ZERO)
            tax_total_confidence = 0.6
        if gross_total is None and subtotal_amount is not None and tax_total is not None:
            gross_total = subtotal_amount + tax_total
            gross_total_confidence = min(subtotal_confidence or 0.6, tax_total_confidence or 0.6)

        if not store_number and delivery_reference:
            suffix_match = re.search(r"(\d{3,})$", delivery_reference)
            if suffix_match:
                store_number = suffix_match.group(1)
                store_number_confidence = 0.64
                store_number_page = delivery_reference_page

        if not invoice_number:
            raise ValueError("Azure Document Intelligence could not extract an invoice number.")
        if invoice_date is None:
            raise ValueError("Azure Document Intelligence could not extract an invoice date.")
        if subtotal_amount is None or tax_total is None or gross_total is None:
            raise ValueError("Azure Document Intelligence could not extract invoice totals.")

        supplier_name = supplier_name or "Unknown Supplier"
        if not supplier_name_confidence:
            supplier_name_confidence = 0.2
        store_number = store_number or "UNKNOWN"
        if not store_number_confidence:
            store_number_confidence = 0.2

        currency = self._extract_currency_code(
            self._pick_field(fields, "InvoiceTotal", "TotalAmount", "AmountDue", "SubTotal", "Subtotal")
        )
        supplier_address = self._extract_address_lines(self._pick_field(fields, "VendorAddress"))

        self._flag_if_low(
            low_confidence_fields,
            "header.invoice_number",
            invoice_number_confidence,
            invoice_number,
            invoice_number_page,
        )
        self._flag_if_low(
            low_confidence_fields,
            "header.invoice_date",
            invoice_date_confidence,
            invoice_date.isoformat(),
            invoice_date_page,
        )
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
        )
        self._flag_if_low(
            low_confidence_fields,
            "header.tax_total",
            tax_total_confidence,
            str(tax_total),
            tax_total_page,
        )
        self._flag_if_low(
            low_confidence_fields,
            "header.gross_total",
            gross_total_confidence,
            str(gross_total),
            gross_total_page,
        )

        invoice = CanonicalInvoice(
            supplier=Supplier(
                name=supplier_name,
                legal_name=supplier_legal_name or supplier_name,
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
            delivery_summary=DeliverySummary(
                delivered_case_count=0,
                delivered_line_count=len(lines),
                source_page=1 if page_count else None,
            )
            if lines
            else None,
            low_confidence_fields=low_confidence_fields,
            audit=AuditMetadata(
                source_filename=context.source_filename,
                provider_name=self.name,
                provider_version=self._provider_version(analysis),
                extracted_at=datetime.now(UTC),
                page_count=page_count or None,
                mock_data=False,
                notes=[f"Processed with Azure model '{model_id}'."],
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

    def _build_delivery_docket_result(
        self,
        context: DocumentExtractionContext,
        analysis: dict[str, Any],
        model_id: str,
    ) -> ProviderExtractionResult:
        content = self._analysis_content(analysis)
        page_count = len(analysis.get("pages") or [])
        low_confidence_fields: list[FieldConfidence] = []
        lines = self._extract_delivery_lines_from_tables(
            analysis,
            low_confidence_fields=low_confidence_fields,
        )

        docket_number, docket_number_confidence = self._regex_pick(
            content,
            (
                r"(?:delivery\s*docket|docket(?:\s*(?:number|no|#))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{3,})",
                r"\b(DD-[0-9]{6}-[0-9]{2,})\b",
            ),
            0.76,
        )
        docket_date, docket_date_confidence = self._regex_pick_date(
            content,
            (
                r"(?:docket\s*date|delivery\s*date|date)\s*[:#-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
                r"(?:docket\s*date|delivery\s*date|date)\s*[:#-]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
            ),
            0.72,
        )
        account_number, account_number_confidence = self._regex_pick(
            content,
            (r"(?:account(?:\s*(?:number|no|#))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",),
            0.72,
        )
        store_number, store_number_confidence = self._regex_pick(
            content,
            (r"(?:store(?:\s*(?:number|no|#|id))?)\s*[:#-]?\s*(\d{2,})",),
            0.72,
        )
        invoice_reference, invoice_reference_confidence = self._regex_pick(
            content,
            (
                r"(?:invoice(?:\s*(?:reference|ref|number|no|#))?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-/]{2,})",
                r"\b(?:invoice|inv)\s*#\s*([A-Z0-9][A-Z0-9\-/]{2,})",
            ),
            0.7,
        )
        supplier_name, supplier_name_confidence = self._regex_pick(
            content,
            (r"(?:supplier|vendor)\s*[:#-]?\s*([^\n\r]+)",),
            0.66,
        )
        supplier_name = supplier_name or self._first_meaningful_line(content) or "Unknown Supplier"
        vehicle_reference, vehicle_reference_confidence = self._regex_pick(
            content,
            (r"(?:vehicle(?:\s*(?:reference|reg|registration))?)\s*[:#-]?\s*([A-Z0-9\-]{4,})",),
            0.66,
        )
        signed_by, signed_by_confidence = self._regex_pick(
            content,
            (r"(?:signed\s*by|received\s*by)\s*[:#-]?\s*([^\n\r]+)",),
            0.6,
        )
        subtotal_amount, subtotal_confidence = self._regex_pick_decimal(
            content,
            (r"(?:sub\s*total|subtotal|net\s*total)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",),
            0.74,
        )
        tax_total, tax_confidence = self._regex_pick_decimal(
            content,
            (r"(?:tax\s*total|total\s*tax|vat\s*total|vat)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",),
            0.72,
        )
        gross_total, gross_confidence = self._regex_pick_decimal(
            content,
            (
                r"(?:gross\s*total|grand\s*total|delivery\s*total|total)\s*[:#-]?\s*[A-Z$€£]*\s*([0-9,]+\.\d{2})",
            ),
            0.74,
        )

        if not store_number and docket_number:
            suffix_match = re.search(r"(\d{3,})$", docket_number)
            if suffix_match:
                store_number = suffix_match.group(1)
                store_number_confidence = 0.62

        if subtotal_amount is None and lines:
            subtotal_amount = sum(
                (line.extended_amount or ZERO for line in lines),
                start=ZERO,
            )
            subtotal_confidence = 0.6
        if gross_total is None and subtotal_amount is not None and tax_total is not None:
            gross_total = subtotal_amount + tax_total
            gross_confidence = min(subtotal_confidence or 0.6, tax_confidence or 0.6)

        if not docket_number:
            raise ValueError("Azure layout extraction could not determine a delivery docket number.")
        if docket_date is None:
            raise ValueError("Azure layout extraction could not determine a delivery docket date.")

        subtotal_amount = subtotal_amount or ZERO
        tax_total = tax_total or ZERO
        gross_total = gross_total or (subtotal_amount + tax_total)

        self._flag_if_low(
            low_confidence_fields,
            "docket_number",
            docket_number_confidence,
            docket_number,
            1 if page_count else None,
        )
        self._flag_if_low(
            low_confidence_fields,
            "docket_date",
            docket_date_confidence,
            docket_date.isoformat(),
            1 if page_count else None,
        )
        self._flag_if_low(
            low_confidence_fields,
            "account_number",
            account_number_confidence,
            account_number,
            1 if page_count else None,
        )
        self._flag_if_low(
            low_confidence_fields,
            "store_number",
            store_number_confidence,
            store_number,
            1 if page_count else None,
        )
        self._flag_if_low(
            low_confidence_fields,
            "supplier_name",
            supplier_name_confidence,
            supplier_name,
            1 if page_count else None,
        )
        self._flag_if_low(
            low_confidence_fields,
            "signed_by",
            signed_by_confidence,
            signed_by,
            1 if page_count else None,
        )

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
            vehicle_reference=vehicle_reference,
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
                notes=[f"Processed with Azure model '{model_id}'."],
            ),
        )
        return ProviderExtractionResult(
            document_type=DocumentType.DELIVERY_DOCKET,
            provider_name=self.name,
            provider_version=self._provider_version(analysis),
            classification_confidence=self._average_confidence(
                docket_number_confidence,
                docket_date_confidence,
                account_number_confidence,
                store_number_confidence,
                gross_confidence,
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

    def _build_accounting_template_result(
        self,
        context: DocumentExtractionContext,
        analysis: dict[str, Any],
        model_id: str,
    ) -> ProviderExtractionResult:
        low_confidence_fields: list[FieldConfidence] = []
        page_count = len(analysis.get("pages") or [])
        notes = [f"Processed with Azure model '{model_id}'."]

        detected_headers = self._extract_template_headers(analysis)
        columns: list[AccountingTemplateColumn] = []
        seen_names: set[str] = set()

        for name in detected_headers:
            normalized = name.strip()
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen_names:
                continue
            seen_names.add(key)
            source_field = self._map_template_source_field(normalized)
            columns.append(
                AccountingTemplateColumn(
                    column_name=normalized,
                    source_field=source_field,
                    required=self._template_required(source_field),
                    default_value=self._template_default(source_field),
                )
            )
            if source_field is None:
                self._flag_if_low(
                    low_confidence_fields,
                    f"columns[{len(columns) - 1}].source_field",
                    0.58,
                    normalized,
                    1 if page_count else None,
                    comment="Column was detected but could not be mapped automatically.",
                )

        if not columns:
            notes.append(
                "Azure layout did not expose a reliable header row, so the accounting export "
                "mapping fell back to the default template schema."
            )
            columns = [
                AccountingTemplateColumn(
                    column_name=column_name,
                    source_field=source_field,
                    required=required,
                    default_value=default_value,
                )
                for column_name, source_field, required, default_value in DEFAULT_TEMPLATE_COLUMNS
            ]
            self._flag_if_low(
                low_confidence_fields,
                "columns",
                0.35,
                "fallback_default_columns",
                1 if page_count else None,
                comment="No reliable template headers were detected from the uploaded file.",
            )

        template = AccountingTemplateDefinition(
            template_name=context.absolute_path.stem or "Accounting Template",
            template_version="azure-layout-1.0",
            columns=columns,
            notes=notes,
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
        confidence = 0.84 if detected_headers else 0.45
        return ProviderExtractionResult(
            document_type=DocumentType.ACCOUNTING_TEMPLATE,
            provider_name=self.name,
            provider_version=self._provider_version(analysis),
            classification_confidence=confidence,
            raw_payload={
                "source_filename": context.source_filename,
                "model_id": model_id,
                "analysis_result": analysis,
            },
            canonical_payload=template.model_dump(mode="python"),
            low_confidence_fields=low_confidence_fields,
            mock_data=False,
        )

    def _build_unknown_result(
        self,
        context: DocumentExtractionContext,
        analysis: dict[str, Any],
        model_id: str,
    ) -> ProviderExtractionResult:
        content = self._analysis_content(analysis)
        return ProviderExtractionResult(
            document_type=DocumentType.UNKNOWN,
            provider_name=self.name,
            provider_version=self._provider_version(analysis),
            classification_confidence=0.25,
            raw_payload={
                "source_filename": context.source_filename,
                "model_id": model_id,
                "analysis_result": analysis,
            },
            canonical_payload={"content": content},
            low_confidence_fields=[],
            mock_data=False,
        )

    def _extract_invoice_lines(
        self,
        items_field: dict[str, Any] | None,
        *,
        low_confidence_fields: list[FieldConfidence],
    ) -> list[InvoiceLine]:
        item_entries = self._field_array(items_field)
        lines: list[InvoiceLine] = []
        for index, item in enumerate(item_entries, start=1):
            item_fields = self._field_object(item)
            description_field = self._pick_field(
                item_fields,
                "Description",
                "Name",
                "ItemDescription",
            )
            quantity_field = self._pick_field(item_fields, "Quantity", "Qty")
            unit_price_field = self._pick_field(item_fields, "UnitPrice", "Price")
            amount_field = self._pick_field(item_fields, "Amount", "NetAmount", "TotalPrice")
            tax_field = self._pick_field(item_fields, "Tax", "TaxAmount")
            tax_rate_field = self._pick_field(item_fields, "TaxRate", "VatRate")
            discount_field = self._pick_field(item_fields, "Discount")

            description = self._field_text(description_field) or f"Line {index}"
            quantity = self._field_decimal(quantity_field) or ZERO
            unit_price = self._field_decimal(unit_price_field)
            amount = self._field_decimal(amount_field)
            discount_amount = self._field_decimal(discount_field) or ZERO
            tax_amount = self._field_decimal(tax_field) or ZERO
            tax_rate = self._normalize_rate(self._field_decimal(tax_rate_field)) or ZERO

            if unit_price is None and amount is not None and quantity not in {ZERO}:
                unit_price = amount / quantity
            if amount is None and unit_price is not None:
                amount = unit_price * quantity

            unit_price = unit_price or ZERO
            amount = amount or ZERO
            net_amount = amount - discount_amount if discount_amount else amount
            page_number = self._first_page_number(
                description_field,
                quantity_field,
                unit_price_field,
                amount_field,
            )
            line = InvoiceLine(
                line_number=index,
                page_number=page_number,
                product_code=self._field_text(self._pick_field(item_fields, "ProductCode", "ItemCode")),
                description=description,
                department_code=None,
                department_name=None,
                quantity=quantity,
                unit_of_measure=self._field_text(self._pick_field(item_fields, "Unit", "UnitOfMeasure")),
                unit_price=unit_price,
                extended_amount=amount,
                discount_amount=discount_amount,
                net_amount=net_amount,
                vat_rate=tax_rate,
                vat_amount=tax_amount,
                gross_amount=net_amount + tax_amount,
                delivery_reference=None,
                source_reference=f"azure-line-{index}",
                confidence_scores=self._confidence_map(
                    product_code=self._field_confidence(self._pick_field(item_fields, "ProductCode", "ItemCode")),
                    description=self._field_confidence(description_field),
                    quantity=self._field_confidence(quantity_field),
                    unit_price=self._field_confidence(unit_price_field),
                ),
            )
            self._flag_if_low(
                low_confidence_fields,
                f"lines[{index - 1}].description",
                self._field_confidence(description_field),
                description,
                page_number,
            )
            self._flag_if_low(
                low_confidence_fields,
                f"lines[{index - 1}].quantity",
                self._field_confidence(quantity_field),
                str(quantity),
                page_number,
            )
            self._flag_if_low(
                low_confidence_fields,
                f"lines[{index - 1}].unit_price",
                self._field_confidence(unit_price_field),
                str(unit_price),
                page_number,
            )
            lines.append(line)
        return lines

    def _extract_delivery_lines_from_tables(
        self,
        analysis: dict[str, Any],
        *,
        low_confidence_fields: list[FieldConfidence],
    ) -> list[DeliveryLine]:
        lines: list[DeliveryLine] = []
        for table in self._iter_table_matrices(analysis):
            header_map = self._delivery_table_header_map(table["rows"][0] if table["rows"] else [])
            if "description" not in header_map or "quantity" not in header_map:
                continue
            for row_index, row in enumerate(table["rows"][1:], start=1):
                if not any(cell.strip() for cell in row):
                    continue
                description = row[header_map["description"]].strip()
                if not description or self._looks_like_total_row(description):
                    continue

                quantity = self._parse_decimal(row[header_map["quantity"]]) or ZERO
                product_code = self._row_value(row, header_map, "product_code")
                unit_of_measure = self._row_value(row, header_map, "unit_of_measure")
                expected_unit_price = self._parse_decimal(self._row_value(row, header_map, "unit_price"))
                extended_amount = self._parse_decimal(self._row_value(row, header_map, "amount"))
                page_number = table["page_number"]

                if expected_unit_price is None and extended_amount is not None and quantity not in {ZERO}:
                    expected_unit_price = extended_amount / quantity

                line = DeliveryLine(
                    line_number=len(lines) + 1,
                    page_number=page_number,
                    product_code=product_code,
                    description=description,
                    quantity_delivered=quantity,
                    unit_of_measure=unit_of_measure,
                    expected_unit_price=expected_unit_price,
                    extended_amount=extended_amount,
                    source_reference=f"table-{table['table_index']}-row-{row_index}",
                    confidence_scores={},
                )
                if quantity == ZERO:
                    self._flag_if_low(
                        low_confidence_fields,
                        f"lines[{len(lines)}].quantity_delivered",
                        0.4,
                        str(quantity),
                        page_number,
                        comment="Quantity could not be parsed cleanly from the table row.",
                    )
                lines.append(line)
            if lines:
                break
        return lines

    def _extract_template_headers(self, analysis: dict[str, Any]) -> list[str]:
        headers: list[str] = []
        for table in self._iter_table_matrices(analysis):
            rows = table["rows"]
            if not rows:
                continue
            candidate_row = max(rows[:2], key=lambda row: sum(bool(cell.strip()) for cell in row))
            non_empty = [cell.strip() for cell in candidate_row if cell.strip()]
            if len(non_empty) >= 3:
                headers.extend(non_empty)
                break
        return headers

    def _iter_table_matrices(self, analysis: dict[str, Any]) -> list[dict[str, Any]]:
        matrices: list[dict[str, Any]] = []
        for table_index, table in enumerate(analysis.get("tables") or []):
            row_count = int(table.get("row_count") or 0)
            column_count = int(table.get("column_count") or 0)
            if row_count <= 0 or column_count <= 0:
                continue
            rows = [["" for _ in range(column_count)] for _ in range(row_count)]
            page_number = None
            for cell in table.get("cells") or []:
                row_index = int(cell.get("row_index") or 0)
                column_index = int(cell.get("column_index") or 0)
                if row_index >= row_count or column_index >= column_count:
                    continue
                content = (cell.get("content") or "").strip()
                rows[row_index][column_index] = content
                if page_number is None:
                    regions = cell.get("bounding_regions") or []
                    if regions:
                        page_number = regions[0].get("page_number")
            matrices.append(
                {
                    "table_index": table_index,
                    "rows": rows,
                    "page_number": page_number,
                }
            )
        return matrices

    def _delivery_table_header_map(self, header_row: list[str]) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for index, header in enumerate(header_row):
            normalized = self._normalize_label(header)
            if not normalized:
                continue
            if any(token in normalized for token in ("description", "item description", "product description")):
                mapping["description"] = index
                continue
            if any(token in normalized for token in ("qty", "quantity")):
                mapping["quantity"] = index
                continue
            if any(token in normalized for token in ("sku", "product code", "item code", "code")):
                mapping["product_code"] = index
                continue
            if any(token in normalized for token in ("uom", "unit")) and "price" not in normalized:
                mapping["unit_of_measure"] = index
                continue
            if "unit price" in normalized or normalized == "price":
                mapping["unit_price"] = index
                continue
            if any(token in normalized for token in ("amount", "net", "line total", "total")):
                mapping["amount"] = index
        return mapping

    def _row_value(self, row: list[str], header_map: dict[str, int], key: str) -> str:
        if key not in header_map:
            return ""
        index = header_map[key]
        if index >= len(row):
            return ""
        return row[index].strip()

    def _build_tax_summaries(
        self,
        lines: list[InvoiceLine],
        tax_total: Decimal,
    ) -> list[TaxSummary]:
        if not lines:
            return []
        grouped: dict[Decimal, dict[str, Decimal]] = {}
        for line in lines:
            bucket = grouped.setdefault(line.vat_rate, {"net": ZERO, "tax": ZERO, "gross": ZERO})
            bucket["net"] += line.net_amount
            bucket["tax"] += line.vat_amount
            bucket["gross"] += line.gross_amount
        return [
            TaxSummary(
                tax_code=f"VAT-{str(rate)}",
                vat_rate=rate,
                net_amount=values["net"],
                tax_amount=values["tax"],
                gross_amount=values["gross"],
            )
            for rate, values in sorted(grouped.items(), key=lambda item: item[0])
        ]

    def _build_discount_summaries(self, lines: list[InvoiceLine]) -> list[DiscountSummary]:
        total_discount = sum((line.discount_amount for line in lines), start=ZERO)
        if total_discount == ZERO:
            return []
        return [
            DiscountSummary(
                discount_type="line_item",
                description="Extracted line-item discounts",
                amount=total_discount,
            )
        ]

    def _build_department_summaries(self, lines: list[InvoiceLine]) -> list[DepartmentSummary]:
        grouped: dict[str, dict[str, Decimal | str]] = {}
        for line in lines:
            if not line.department_code or not line.department_name:
                continue
            bucket = grouped.setdefault(
                line.department_code,
                {"gross": ZERO, "net": ZERO, "name": line.department_name},
            )
            bucket["net"] = Decimal(bucket["net"]) + line.net_amount
            bucket["gross"] = Decimal(bucket["gross"]) + line.gross_amount
        return [
            DepartmentSummary(
                department_code=department_code,
                department_name=str(values["name"]),
                net_amount=Decimal(values["net"]),
                gross_amount=Decimal(values["gross"]),
            )
            for department_code, values in grouped.items()
        ]

    def _map_template_source_field(self, column_name: str) -> str | None:
        normalized = self._normalize_label(column_name)
        for aliases, source_field in TEMPLATE_FIELD_ALIASES:
            if any(alias in normalized for alias in aliases):
                return source_field
        return None

    def _template_required(self, source_field: str | None) -> bool:
        optional_fields = {
            "docket_number",
            "product_code",
            "department_code",
            "delivered_quantity",
            "delivery_net_amount",
            "exception_reasons",
        }
        return source_field not in optional_fields

    def _template_default(self, source_field: str | None) -> str | None:
        defaults = {
            "docket_number": "",
            "product_code": "",
            "department_code": "",
            "invoiced_quantity": "0",
            "delivered_quantity": "0",
            "unit_price": "0.00",
            "invoice_net_amount": "0.00",
            "delivery_net_amount": "0.00",
            "vat_rate": "0.00",
            "vat_amount": "0.00",
            "gross_amount": "0.00",
            "match_status": "review_required",
            "exception_reasons": "",
            "approval_status": "review_required",
        }
        return defaults.get(source_field)

    def _provider_version(self, analysis: dict[str, Any]) -> str:
        return str(analysis.get("api_version") or "1.0.0")

    def _first_document_fields(self, analysis: dict[str, Any]) -> tuple[dict[str, Any], float | None]:
        documents = analysis.get("documents") or []
        if not documents:
            return {}, None
        document = documents[0]
        return document.get("fields") or {}, self._coerce_float(document.get("confidence"))

    def _select_text(
        self,
        fields: dict[str, Any],
        *,
        candidates: tuple[str, ...],
        text_sources: tuple[tuple[str, float], ...] = (),
        regexes: tuple[str, ...] = (),
    ) -> tuple[str | None, float | None, int | None]:
        field = self._pick_field(fields, *candidates)
        value = self._field_text(field)
        if value:
            return value, self._field_confidence(field), self._field_page(field)
        for text, confidence in text_sources:
            match = self._search_patterns(text, regexes)
            if match:
                return match, confidence, None
        return None, None, None

    def _select_decimal(
        self,
        fields: dict[str, Any],
        *,
        candidates: tuple[str, ...],
        text_sources: tuple[tuple[str, float], ...] = (),
        regexes: tuple[str, ...] = (),
    ) -> tuple[Decimal | None, float | None, int | None]:
        field = self._pick_field(fields, *candidates)
        value = self._field_decimal(field)
        if value is not None:
            return value, self._field_confidence(field), self._field_page(field)
        for text, confidence in text_sources:
            match = self._search_patterns(text, regexes)
            decimal_value = self._parse_decimal(match)
            if decimal_value is not None:
                return decimal_value, confidence, None
        return None, None, None

    def _select_date(
        self,
        fields: dict[str, Any],
        *,
        candidates: tuple[str, ...],
        text_sources: tuple[tuple[str, float], ...] = (),
        regexes: tuple[str, ...] = (),
    ) -> tuple[date | None, float | None, int | None]:
        field = self._pick_field(fields, *candidates)
        value = self._field_date(field)
        if value is not None:
            return value, self._field_confidence(field), self._field_page(field)
        for text, confidence in text_sources:
            match = self._search_patterns(text, regexes)
            parsed = self._parse_date(match)
            if parsed is not None:
                return parsed, confidence, None
        return None, None, None

    def _regex_pick(
        self,
        text: str,
        patterns: tuple[str, ...],
        confidence: float,
    ) -> tuple[str | None, float | None]:
        value = self._search_patterns(text, patterns)
        return value, confidence if value else None

    def _regex_pick_decimal(
        self,
        text: str,
        patterns: tuple[str, ...],
        confidence: float,
    ) -> tuple[Decimal | None, float | None]:
        value = self._parse_decimal(self._search_patterns(text, patterns))
        return value, confidence if value is not None else None

    def _regex_pick_date(
        self,
        text: str,
        patterns: tuple[str, ...],
        confidence: float,
    ) -> tuple[date | None, float | None]:
        value = self._parse_date(self._search_patterns(text, patterns))
        return value, confidence if value is not None else None

    def _search_patterns(self, text: str | None, patterns: tuple[str, ...]) -> str | None:
        if not text:
            return None
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _pick_field(self, fields: dict[str, Any], *candidates: str) -> dict[str, Any] | None:
        if not fields:
            return None
        by_lower = {key.casefold(): value for key, value in fields.items()}
        for candidate in candidates:
            value = fields.get(candidate)
            if value is not None:
                return value
            value = by_lower.get(candidate.casefold())
            if value is not None:
                return value
        return None

    def _field_text(self, field: dict[str, Any] | None) -> str | None:
        if not field:
            return None
        for key in (
            "value_string",
            "value_phone_number",
            "value_country_region",
            "value_selection_mark",
            "content",
        ):
            value = field.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        date_value = self._field_date(field)
        if date_value is not None:
            return date_value.isoformat()
        decimal_value = self._field_decimal(field)
        if decimal_value is not None:
            return str(decimal_value)
        address = self._extract_address_lines(field)
        if address:
            return ", ".join(address)
        return None

    def _field_decimal(self, field: dict[str, Any] | None) -> Decimal | None:
        if not field:
            return None
        currency_value = field.get("value_currency")
        if isinstance(currency_value, dict):
            return self._parse_decimal(currency_value.get("amount"))
        for key in ("value_number", "value_integer", "value_string", "content"):
            value = field.get(key)
            decimal_value = self._parse_decimal(value)
            if decimal_value is not None:
                return decimal_value
        return None

    def _field_date(self, field: dict[str, Any] | None) -> date | None:
        if not field:
            return None
        return self._parse_date(field.get("value_date") or field.get("content"))

    def _field_array(self, field: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not field:
            return []
        value = field.get("value_array")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def _field_object(self, field: dict[str, Any] | None) -> dict[str, Any]:
        if not field:
            return {}
        value = field.get("value_object")
        if isinstance(value, dict):
            return value
        return {}

    def _field_confidence(self, field: dict[str, Any] | None) -> float | None:
        if not field:
            return None
        return self._coerce_float(field.get("confidence"))

    def _field_page(self, field: dict[str, Any] | None) -> int | None:
        if not field:
            return None
        regions = field.get("bounding_regions") or []
        if not regions:
            return None
        page_number = regions[0].get("page_number")
        return int(page_number) if page_number is not None else None

    def _first_page_number(self, *fields: dict[str, Any] | None) -> int | None:
        for field in fields:
            page_number = self._field_page(field)
            if page_number is not None:
                return page_number
        return None

    def _extract_currency_code(self, field: dict[str, Any] | None) -> str | None:
        if not field:
            return None
        currency_value = field.get("value_currency")
        if isinstance(currency_value, dict):
            currency_code = currency_value.get("currency_code")
            if isinstance(currency_code, str) and currency_code.strip():
                return currency_code.strip().upper()
        return None

    def _extract_address_lines(self, field: dict[str, Any] | None) -> list[str]:
        if not field:
            return []
        address_value = field.get("value_address")
        if isinstance(address_value, dict):
            lines = []
            for key in (
                "street_address",
                "unit",
                "city",
                "state",
                "postal_code",
                "country_region",
            ):
                value = address_value.get(key)
                if isinstance(value, str) and value.strip():
                    lines.append(value.strip())
            return lines
        content = field.get("content")
        if isinstance(content, str) and content.strip():
            return [part.strip() for part in re.split(r"[\r\n]+", content) if part.strip()]
        return []

    def _analysis_content(self, analysis: dict[str, Any]) -> str:
        content = analysis.get("content")
        if isinstance(content, str) and content.strip():
            return content
        lines: list[str] = []
        for page in analysis.get("pages") or []:
            for line in page.get("lines") or []:
                text = line.get("content")
                if isinstance(text, str) and text.strip():
                    lines.append(text.strip())
        return "\n".join(lines)

    def _flag_if_low(
        self,
        low_confidence_fields: list[FieldConfidence],
        field_path: str,
        confidence: float | None,
        value: Any,
        source_page: int | None,
        *,
        comment: str | None = None,
    ) -> None:
        if value in (None, ""):
            return
        if confidence is None or confidence >= self._settings.low_confidence_threshold:
            return
        low_confidence_fields.append(
            FieldConfidence(
                field_path=field_path,
                score=confidence,
                value=value,
                requires_review=True,
                source_page=source_page,
                comment=comment,
            )
        )

    def _average_confidence(self, *values: float | None) -> float:
        present = [value for value in values if value is not None]
        if not present:
            return 0.5
        return max(0.0, min(1.0, sum(present) / len(present)))

    def _normalize_rate(self, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if value > Decimal("1"):
            return value / ONE_HUNDRED
        return value

    def _parse_decimal(self, value: Any) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            cleaned = re.sub(r"[^0-9,\.\-]", "", cleaned)
            if cleaned.count(",") > 0 and cleaned.count(".") > 0:
                cleaned = cleaned.replace(",", "")
            elif cleaned.count(",") == 1 and cleaned.count(".") == 0:
                cleaned = cleaned.replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
            try:
                return Decimal(cleaned)
            except InvalidOperation:
                return None
        return None

    def _parse_date(self, value: Any) -> date | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(cleaned, pattern).date()
            except ValueError:
                continue
        return None

    def _first_meaningful_line(self, content: str) -> str | None:
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            normalized = self._normalize_label(line)
            if any(token in normalized for token in ("invoice", "docket", "date", "page")):
                continue
            if len(line) >= 4:
                return line
        return None

    def _looks_like_total_row(self, description: str) -> bool:
        normalized = self._normalize_label(description)
        return any(token in normalized for token in ("subtotal", "total", "vat", "tax"))

    def _normalize_label(self, value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.casefold())).strip()

    def _confidence_map(self, **values: float | None) -> dict[str, float]:
        return {key: value for key, value in values.items() if value is not None}

    def _coerce_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_plain_data(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool, Decimal, date, datetime)):
            return value
        if isinstance(value, dict):
            return {key: self._to_plain_data(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._to_plain_data(item) for item in value]
        for method_name in ("as_dict", "to_dict", "model_dump"):
            method = getattr(value, method_name, None)
            if callable(method):
                return self._to_plain_data(method())
        if hasattr(value, "__dict__"):
            return {
                key: self._to_plain_data(item)
                for key, item in vars(value).items()
                if not key.startswith("_")
            }
        return value


AzureDocumentIntelligenceStubProvider = AzureDocumentIntelligenceProvider
