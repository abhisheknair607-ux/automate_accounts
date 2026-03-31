from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CanonicalBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DocumentType(str, Enum):
    INVOICE = "invoice"
    DELIVERY_DOCKET = "delivery_docket"
    ACCOUNTING_TEMPLATE = "accounting_template"
    UNKNOWN = "unknown"


class MatchStatus(str, Enum):
    MATCHED = "matched"
    WITHIN_TOLERANCE = "within_tolerance"
    MISMATCH = "mismatch"
    REVIEW_REQUIRED = "review_required"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ReasonCode(str, Enum):
    HEADER_INVOICE_NUMBER_INVALID = "header_invoice_number_invalid"
    HEADER_SUPPLIER_MISMATCH = "header_supplier_mismatch"
    HEADER_ACCOUNT_MISMATCH = "header_account_mismatch"
    HEADER_STORE_MISMATCH = "header_store_mismatch"
    HEADER_DATE_MISMATCH = "header_date_mismatch"
    LINE_MISSING_IN_DOCKET = "line_missing_in_docket"
    LINE_ONLY_ON_DOCKET = "line_only_on_docket"
    LINE_QTY_MISMATCH = "line_qty_mismatch"
    LINE_UNIT_PRICE_MISMATCH = "line_unit_price_mismatch"
    LINE_AMOUNT_MISMATCH = "line_amount_mismatch"
    VAT_TOTAL_MISMATCH = "vat_total_mismatch"
    GRAND_TOTAL_MISMATCH = "grand_total_mismatch"
    LOW_CONFIDENCE_FIELD = "low_confidence_field"


class FieldConfidence(CanonicalBaseModel):
    field_path: str
    score: float = Field(ge=0.0, le=1.0)
    value: Any | None = None
    requires_review: bool = False
    source_page: int | None = None
    comment: str | None = None


class AuditMetadata(CanonicalBaseModel):
    source_filename: str
    provider_name: str
    provider_version: str = "1.0"
    extracted_at: datetime
    page_count: int | None = None
    mock_data: bool = False
    notes: list[str] = Field(default_factory=list)


class Supplier(CanonicalBaseModel):
    supplier_code: str | None = None
    name: str
    legal_name: str | None = None
    account_number: str | None = None
    vat_number: str | None = None
    address: list[str] = Field(default_factory=list)
    confidence_scores: dict[str, float] = Field(default_factory=dict)


class Store(CanonicalBaseModel):
    store_number: str
    name: str | None = None
    division: str | None = None
    address: list[str] = Field(default_factory=list)
    confidence_scores: dict[str, float] = Field(default_factory=dict)


class InvoiceHeader(CanonicalBaseModel):
    invoice_number: str
    invoice_date: date
    account_number: str | None = None
    store_number: str | None = None
    supplier_name: str
    supplier_account_reference: str | None = None
    currency: str = "EUR"
    division_code: str | None = None
    payment_terms: str | None = None
    delivery_reference: str | None = None
    subtotal_amount: Decimal
    discount_total: Decimal = Decimal("0.00")
    tax_total: Decimal
    gross_total: Decimal
    confidence_scores: dict[str, float] = Field(default_factory=dict)


class InvoiceLine(CanonicalBaseModel):
    line_number: int
    page_number: int | None = None
    product_code: str | None = None
    description: str
    department_code: str | None = None
    department_name: str | None = None
    quantity: Decimal
    unit_of_measure: str | None = None
    unit_price: Decimal
    extended_amount: Decimal
    discount_amount: Decimal = Decimal("0.00")
    net_amount: Decimal
    vat_rate: Decimal = Decimal("0.00")
    vat_amount: Decimal = Decimal("0.00")
    gross_amount: Decimal = Decimal("0.00")
    delivery_reference: str | None = None
    source_reference: str | None = None
    confidence_scores: dict[str, float] = Field(default_factory=dict)


class TaxSummary(CanonicalBaseModel):
    tax_code: str
    vat_rate: Decimal
    net_amount: Decimal
    tax_amount: Decimal
    gross_amount: Decimal
    source_page: int | None = None


class DiscountSummary(CanonicalBaseModel):
    discount_type: str
    description: str
    amount: Decimal
    tax_treatment: str | None = None
    source_page: int | None = None


class DepartmentSummary(CanonicalBaseModel):
    department_code: str
    department_name: str
    net_amount: Decimal
    gross_amount: Decimal
    source_page: int | None = None


class DeliverySummary(CanonicalBaseModel):
    delivered_case_count: int
    delivered_line_count: int
    source_page: int | None = None


class CanonicalInvoice(CanonicalBaseModel):
    supplier: Supplier
    store: Store
    header: InvoiceHeader
    lines: list[InvoiceLine]
    tax_summaries: list[TaxSummary]
    discount_summaries: list[DiscountSummary]
    department_summaries: list[DepartmentSummary]
    delivery_summary: DeliverySummary | None = None
    low_confidence_fields: list[FieldConfidence] = Field(default_factory=list)
    audit: AuditMetadata


class DeliveryLine(CanonicalBaseModel):
    line_number: int
    page_number: int | None = None
    product_code: str | None = None
    description: str
    quantity_delivered: Decimal
    unit_of_measure: str | None = None
    expected_unit_price: Decimal | None = None
    extended_amount: Decimal | None = None
    source_reference: str | None = None
    confidence_scores: dict[str, float] = Field(default_factory=dict)


class DeliveryDocket(CanonicalBaseModel):
    docket_number: str
    docket_date: date
    account_number: str | None = None
    store_number: str | None = None
    supplier_name: str
    invoice_reference: str | None = None
    subtotal_amount: Decimal
    tax_total: Decimal
    gross_total: Decimal
    vehicle_reference: str | None = None
    signed_by: str | None = None
    lines: list[DeliveryLine]
    low_confidence_fields: list[FieldConfidence] = Field(default_factory=list)
    audit: AuditMetadata


class ReconciledLine(CanonicalBaseModel):
    line_key: str
    invoice_line_number: int | None = None
    docket_line_number: int | None = None
    product_code: str | None = None
    description: str
    invoiced_quantity: Decimal | None = None
    delivered_quantity: Decimal | None = None
    unit_price: Decimal | None = None
    delivery_unit_price: Decimal | None = None
    invoice_net_amount: Decimal | None = None
    delivery_net_amount: Decimal | None = None
    variance_quantity: Decimal | None = None
    variance_amount: Decimal | None = None
    status: MatchStatus
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    confidence_score: float | None = None


class ReconciliationIssue(CanonicalBaseModel):
    severity: IssueSeverity
    reason_code: ReasonCode
    entity_type: str
    entity_identifier: str | None = None
    field_name: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    variance_amount: Decimal | None = None
    variance_percent: Decimal | None = None
    confidence_score: float | None = None
    requires_review: bool = True
    message: str


class ReconciliationTotals(CanonicalBaseModel):
    invoice_subtotal: Decimal
    docket_subtotal: Decimal
    invoice_tax_total: Decimal
    docket_tax_total: Decimal
    invoice_gross_total: Decimal
    docket_gross_total: Decimal
    subtotal_variance: Decimal
    tax_variance: Decimal
    gross_variance: Decimal


class ReconciliationConfig(CanonicalBaseModel):
    quantity_tolerance: Decimal = Decimal("0.00")
    unit_price_tolerance: Decimal = Decimal("0.02")
    line_amount_tolerance: Decimal = Decimal("0.50")
    tax_tolerance: Decimal = Decimal("0.50")
    total_tolerance: Decimal = Decimal("0.50")
    low_confidence_threshold: float = 0.85


class ReconciliationResult(CanonicalBaseModel):
    status: MatchStatus
    approved: bool
    overall_score: float = Field(ge=0.0, le=1.0)
    header_matches: dict[str, bool]
    totals: ReconciliationTotals
    reconciled_lines: list[ReconciledLine]
    issues: list[ReconciliationIssue]
    applied_config: ReconciliationConfig
    created_at: datetime


class AccountingTemplateColumn(CanonicalBaseModel):
    column_name: str
    source_field: str | None = None
    required: bool = True
    default_value: str | None = None


class AccountingTemplateDefinition(CanonicalBaseModel):
    template_name: str
    template_version: str = "mock-1.0"
    columns: list[AccountingTemplateColumn]
    notes: list[str] = Field(default_factory=list)
    low_confidence_fields: list[FieldConfidence] = Field(default_factory=list)
    audit: AuditMetadata


class AccountingExportRow(CanonicalBaseModel):
    row_number: int
    invoice_number: str
    invoice_date: date
    supplier_name: str
    account_number: str | None = None
    store_number: str | None = None
    docket_number: str | None = None
    product_code: str | None = None
    description: str
    department_code: str | None = None
    invoiced_quantity: Decimal | None = None
    delivered_quantity: Decimal | None = None
    unit_price: Decimal | None = None
    invoice_net_amount: Decimal | None = None
    delivery_net_amount: Decimal | None = None
    vat_rate: Decimal | None = None
    vat_amount: Decimal | None = None
    gross_amount: Decimal | None = None
    match_status: MatchStatus
    exception_reasons: list[ReasonCode] = Field(default_factory=list)
    approval_status: str
    template_values: dict[str, Any] = Field(default_factory=dict)


class ReconciliationExportRow(CanonicalBaseModel):
    row_number: int
    invoice_number: str
    invoice_date: date
    docket_number: str | None = None
    invoice_line_number: int | None = None
    docket_line_number: int | None = None
    product_code: str | None = None
    description: str
    invoice_quantity: Decimal | None = None
    invoice_amount: Decimal | None = None
    docket_quantity: Decimal | None = None
    docket_amount: Decimal | None = None
    quantity_variance: Decimal | None = None
    amount_variance: Decimal | None = None
    match_status: MatchStatus
    final_comment: str


class ExceptionCase(CanonicalBaseModel):
    case_id: str
    reconciliation_run_id: str
    status: str
    issue_count: int
    blocking_issue_count: int
    low_confidence_issue_count: int
    reasons: list[ReasonCode]
    suggested_actions: list[str] = Field(default_factory=list)


class ProviderExtractionResult(CanonicalBaseModel):
    document_type: DocumentType
    provider_name: str
    provider_version: str = "1.0"
    classification_confidence: float = Field(ge=0.0, le=1.0)
    raw_payload: dict[str, Any]
    canonical_payload: dict[str, Any]
    low_confidence_fields: list[FieldConfidence] = Field(default_factory=list)
    mock_data: bool = False
