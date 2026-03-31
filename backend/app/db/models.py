from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class CaseRecord(TimestampMixin, Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="normal", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    documents: Mapped[list["DocumentRecord"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    extraction_runs: Mapped[list["ExtractionRunRecord"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    invoices: Mapped[list["InvoiceRecord"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    delivery_dockets: Mapped[list["DeliveryDocketRecord"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    reconciliation_runs: Mapped[list["ReconciliationRunRecord"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    exports: Mapped[list["ExportRecord"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class DocumentRecord(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(64), default="unknown", nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    classification_confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    extraction_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    latest_provider: Mapped[str | None] = mapped_column(String(128))
    latest_extraction_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    low_confidence_fields: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    case: Mapped["CaseRecord"] = relationship(back_populates="documents")
    extraction_runs: Mapped[list["ExtractionRunRecord"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class ExtractionRunRecord(TimestampMixin, Base):
    __tablename__ = "extraction_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, index=True)
    provider_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    provider_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    normalized_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    low_confidence_fields: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    case: Mapped["CaseRecord"] = relationship(back_populates="extraction_runs")
    document: Mapped["DocumentRecord"] = relationship(back_populates="extraction_runs")


class InvoiceRecord(TimestampMixin, Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, unique=True)
    extraction_run_id: Mapped[str | None] = mapped_column(ForeignKey("extraction_runs.id"))
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    account_number: Mapped[str | None] = mapped_column(String(64))
    store_number: Mapped[str | None] = mapped_column(String(64))
    supplier_name: Mapped[str | None] = mapped_column(String(255))
    supplier_legal_name: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(8), default="EUR", nullable=False)
    subtotal_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    discount_total: Mapped[float | None] = mapped_column(Numeric(14, 2))
    tax_total: Mapped[float | None] = mapped_column(Numeric(14, 2))
    gross_total: Mapped[float | None] = mapped_column(Numeric(14, 2))
    confidence_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    canonical_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    case: Mapped["CaseRecord"] = relationship(back_populates="invoices")
    lines: Mapped[list["InvoiceLineRecord"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoiceLineRecord(TimestampMixin, Base):
    __tablename__ = "invoice_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    product_code: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    department_code: Mapped[str | None] = mapped_column(String(64))
    unit_of_measure: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    extended_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    discount_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    net_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    vat_rate: Mapped[float | None] = mapped_column(Numeric(8, 4))
    vat_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    gross_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    source_reference: Mapped[str | None] = mapped_column(String(255))
    confidence_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    invoice: Mapped["InvoiceRecord"] = relationship(back_populates="lines")


class DeliveryDocketRecord(TimestampMixin, Base):
    __tablename__ = "delivery_dockets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False, unique=True)
    extraction_run_id: Mapped[str | None] = mapped_column(ForeignKey("extraction_runs.id"))
    docket_number: Mapped[str | None] = mapped_column(String(64), index=True)
    docket_date: Mapped[date | None] = mapped_column(Date)
    account_number: Mapped[str | None] = mapped_column(String(64))
    store_number: Mapped[str | None] = mapped_column(String(64))
    supplier_name: Mapped[str | None] = mapped_column(String(255))
    invoice_reference: Mapped[str | None] = mapped_column(String(64))
    subtotal_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    tax_total: Mapped[float | None] = mapped_column(Numeric(14, 2))
    gross_total: Mapped[float | None] = mapped_column(Numeric(14, 2))
    confidence_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    canonical_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    case: Mapped["CaseRecord"] = relationship(back_populates="delivery_dockets")
    lines: Mapped[list["DeliveryLineRecord"]] = relationship(
        back_populates="delivery_docket", cascade="all, delete-orphan"
    )


class DeliveryLineRecord(TimestampMixin, Base):
    __tablename__ = "delivery_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    delivery_docket_id: Mapped[str] = mapped_column(
        ForeignKey("delivery_dockets.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    product_code: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    unit_of_measure: Mapped[str | None] = mapped_column(String(32))
    quantity_delivered: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    expected_unit_price: Mapped[float | None] = mapped_column(Numeric(14, 4))
    extended_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    source_reference: Mapped[str | None] = mapped_column(String(255))
    confidence_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    delivery_docket: Mapped["DeliveryDocketRecord"] = relationship(back_populates="lines")


class ReconciliationRunRecord(TimestampMixin, Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    delivery_docket_id: Mapped[str] = mapped_column(ForeignKey("delivery_dockets.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    case: Mapped["CaseRecord"] = relationship(back_populates="reconciliation_runs")
    issues: Mapped[list["ReconciliationIssueRecord"]] = relationship(
        back_populates="reconciliation_run", cascade="all, delete-orphan"
    )


class ReconciliationIssueRecord(TimestampMixin, Base):
    __tablename__ = "reconciliation_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    reconciliation_run_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_runs.id"), nullable=False, index=True
    )
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_identifier: Mapped[str | None] = mapped_column(String(128))
    field_name: Mapped[str | None] = mapped_column(String(128))
    expected_value: Mapped[str | None] = mapped_column(Text)
    actual_value: Mapped[str | None] = mapped_column(Text)
    variance_amount: Mapped[float | None] = mapped_column(Numeric(14, 4))
    variance_percent: Mapped[float | None] = mapped_column(Numeric(14, 4))
    confidence_score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    requires_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)

    reconciliation_run: Mapped["ReconciliationRunRecord"] = relationship(back_populates="issues")


class ExportRecord(TimestampMixin, Base):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    reconciliation_run_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_runs.id"), nullable=False
    )
    export_format: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    output_path: Mapped[str] = mapped_column(String(512), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    export_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    case: Mapped["CaseRecord"] = relationship(back_populates="exports")
