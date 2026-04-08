from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.schemas.canonical import FieldConfidence, ReconciliationConfig


class ApiBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ExtractionRequest(ApiBaseModel):
    provider_name: str = Field(default_factory=lambda: settings.default_extraction_provider)
    force: bool = False


class ReconciliationRequest(ApiBaseModel):
    config: ReconciliationConfig | None = None


class ManualReconciliationPair(ApiBaseModel):
    invoice_line_number: int
    docket_line_number: int
    position: int = Field(ge=0)


class ManualReconciliationRequest(ApiBaseModel):
    base_reconciliation_run_id: str
    config: ReconciliationConfig | None = None
    pairs: list[ManualReconciliationPair] = Field(default_factory=list)


class ExportRequest(ApiBaseModel):
    export_format: Literal["csv", "json", "reco_csv", "reco_excel", "ocr_excel", "pnl_csv"] = "csv"


class DocumentResponse(ApiBaseModel):
    id: str
    case_id: str
    doc_type: str
    source_filename: str
    mime_type: str | None = None
    file_size_bytes: int
    classification_confidence: float | None = None
    extraction_status: str
    latest_provider: str | None = None
    low_confidence_fields: list[dict[str, Any]] | None = None
    created_at: datetime
    updated_at: datetime


class CaseSummaryResponse(ApiBaseModel):
    id: str
    name: str | None = None
    status: str
    priority: str
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    open_issue_count: int = 0
    latest_reconciliation_status: str | None = None


class CaseDetailResponse(CaseSummaryResponse):
    documents: list[DocumentResponse] = Field(default_factory=list)
    invoice: dict[str, Any] | None = None
    delivery_docket: dict[str, Any] | None = None
    latest_reconciliation: dict[str, Any] | None = None
    latest_exception_case: dict[str, Any] | None = None
    exports: list[dict[str, Any]] = Field(default_factory=list)


class ExtractionRunResponse(ApiBaseModel):
    id: str
    case_id: str
    document_id: str
    provider_name: str
    status: str
    low_confidence_fields: list[dict[str, Any]] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExtractionBatchResponse(ApiBaseModel):
    case_id: str
    provider_name: str
    runs: list[ExtractionRunResponse]


class ExtractedDocumentResponse(ApiBaseModel):
    document: DocumentResponse
    payload: dict[str, Any] | None = None
    low_confidence_fields: list[FieldConfidence] = Field(default_factory=list)


class EditableInvoiceRow(ApiBaseModel):
    supplier: str = ""
    product_code: str | None = None
    product_name: str = ""
    quantity_invoice: str = ""
    pre_amount_invoice: str = ""
    vat_invoice: str = ""
    total_invoice: str = ""


class UpdateInvoiceRequest(ApiBaseModel):
    rows: list[EditableInvoiceRow] = Field(default_factory=list)


class EditableDocketRow(ApiBaseModel):
    supplier: str = ""
    product_code: str | None = None
    product_name: str = ""
    quantity_docket: str = ""
    amount_docket: str = ""


class UpdateDocketRequest(ApiBaseModel):
    rows: list[EditableDocketRow] = Field(default_factory=list)


class ReconciliationIssueResponse(ApiBaseModel):
    severity: str
    reason_code: str
    entity_type: str
    entity_identifier: str | None = None
    field_name: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    variance_amount: float | None = None
    variance_percent: float | None = None
    confidence_score: float | None = None
    requires_review: bool
    status: str


class ReconciliationResponse(ApiBaseModel):
    id: str
    case_id: str
    invoice_id: str
    delivery_docket_id: str
    status: str
    auto_approved: bool
    overall_score: float | None = None
    result_payload: dict[str, Any] | None = None
    issues: list[ReconciliationIssueResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ExportResponse(ApiBaseModel):
    id: str
    case_id: str
    reconciliation_run_id: str
    export_format: str
    status: str
    content_type: str
    output_path: str
    row_count: int
    export_payload: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
