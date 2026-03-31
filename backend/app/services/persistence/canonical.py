from __future__ import annotations

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    DeliveryDocketRecord,
    DeliveryLineRecord,
    DocumentRecord,
    ExtractionRunRecord,
    InvoiceLineRecord,
    InvoiceRecord,
)
from app.schemas.canonical import AccountingTemplateDefinition, CanonicalInvoice, DeliveryDocket


class CanonicalPersistenceService:
    def persist_invoice(
        self,
        db: Session,
        *,
        case_id: str,
        document: DocumentRecord,
        extraction_run: ExtractionRunRecord,
        invoice: CanonicalInvoice,
    ) -> InvoiceRecord:
        existing = db.scalar(select(InvoiceRecord).where(InvoiceRecord.document_id == document.id))
        if existing is None:
            existing = InvoiceRecord(case_id=case_id, document_id=document.id)
            db.add(existing)

        existing.extraction_run_id = extraction_run.id
        existing.invoice_number = invoice.header.invoice_number
        existing.invoice_date = invoice.header.invoice_date
        existing.account_number = invoice.header.account_number
        existing.store_number = invoice.header.store_number
        existing.supplier_name = invoice.supplier.name
        existing.supplier_legal_name = invoice.supplier.legal_name
        existing.currency = invoice.header.currency
        existing.subtotal_amount = float(invoice.header.subtotal_amount)
        existing.discount_total = float(invoice.header.discount_total)
        existing.tax_total = float(invoice.header.tax_total)
        existing.gross_total = float(invoice.header.gross_total)
        existing.confidence_scores = invoice.header.confidence_scores
        existing.canonical_payload = jsonable_encoder(invoice.model_dump(mode="json"))

        db.execute(delete(InvoiceLineRecord).where(InvoiceLineRecord.invoice_id == existing.id))
        db.flush()
        for line in invoice.lines:
            db.add(
                InvoiceLineRecord(
                    invoice_id=existing.id,
                    line_number=line.line_number,
                    page_number=line.page_number,
                    product_code=line.product_code,
                    description=line.description,
                    department_code=line.department_code,
                    unit_of_measure=line.unit_of_measure,
                    quantity=float(line.quantity),
                    unit_price=float(line.unit_price),
                    extended_amount=float(line.extended_amount),
                    discount_amount=float(line.discount_amount),
                    net_amount=float(line.net_amount),
                    vat_rate=float(line.vat_rate),
                    vat_amount=float(line.vat_amount),
                    gross_amount=float(line.gross_amount),
                    source_reference=line.source_reference,
                    confidence_scores=line.confidence_scores,
                )
            )
        return existing

    def persist_delivery_docket(
        self,
        db: Session,
        *,
        case_id: str,
        document: DocumentRecord,
        extraction_run: ExtractionRunRecord,
        docket: DeliveryDocket,
    ) -> DeliveryDocketRecord:
        existing = db.scalar(
            select(DeliveryDocketRecord).where(DeliveryDocketRecord.document_id == document.id)
        )
        if existing is None:
            existing = DeliveryDocketRecord(case_id=case_id, document_id=document.id)
            db.add(existing)

        existing.extraction_run_id = extraction_run.id
        existing.docket_number = docket.docket_number
        existing.docket_date = docket.docket_date
        existing.account_number = docket.account_number
        existing.store_number = docket.store_number
        existing.supplier_name = docket.supplier_name
        existing.invoice_reference = docket.invoice_reference
        existing.subtotal_amount = float(docket.subtotal_amount)
        existing.tax_total = float(docket.tax_total)
        existing.gross_total = float(docket.gross_total)
        existing.confidence_scores = {}
        existing.canonical_payload = jsonable_encoder(docket.model_dump(mode="json"))

        db.execute(delete(DeliveryLineRecord).where(DeliveryLineRecord.delivery_docket_id == existing.id))
        db.flush()
        for line in docket.lines:
            db.add(
                DeliveryLineRecord(
                    delivery_docket_id=existing.id,
                    line_number=line.line_number,
                    page_number=line.page_number,
                    product_code=line.product_code,
                    description=line.description,
                    unit_of_measure=line.unit_of_measure,
                    quantity_delivered=float(line.quantity_delivered),
                    expected_unit_price=float(line.expected_unit_price)
                    if line.expected_unit_price is not None
                    else None,
                    extended_amount=float(line.extended_amount)
                    if line.extended_amount is not None
                    else None,
                    source_reference=line.source_reference,
                    confidence_scores=line.confidence_scores,
                )
            )
        return existing

    def persist_template(
        self,
        *,
        document: DocumentRecord,
        template: AccountingTemplateDefinition,
    ) -> None:
        document.latest_extraction_payload = jsonable_encoder(template.model_dump(mode="json"))


canonical_persistence_service = CanonicalPersistenceService()
