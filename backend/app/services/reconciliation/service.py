from __future__ import annotations

from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    CaseRecord,
    DeliveryDocketRecord,
    InvoiceRecord,
    ReconciliationIssueRecord,
    ReconciliationRunRecord,
)
from app.schemas.canonical import (
    CanonicalInvoice,
    DeliveryDocket,
    ExceptionCase,
    IssueSeverity,
    ReasonCode,
    ReconciliationConfig,
    ReconciliationResult,
)
from app.services.reconciliation.engine import reconciliation_engine


class ReconciliationService:
    def run(
        self,
        db: Session,
        *,
        case_id: str,
        config: ReconciliationConfig | None = None,
    ) -> ReconciliationRunRecord:
        case = db.get(CaseRecord, case_id)
        if case is None:
            raise ValueError(f"Case '{case_id}' not found.")

        invoice_record = db.scalar(
            select(InvoiceRecord).where(InvoiceRecord.case_id == case_id).order_by(InvoiceRecord.created_at.desc())
        )
        docket_record = db.scalar(
            select(DeliveryDocketRecord)
            .where(DeliveryDocketRecord.case_id == case_id)
            .order_by(DeliveryDocketRecord.created_at.desc())
        )
        if invoice_record is None or docket_record is None:
            raise ValueError("Both an extracted invoice and an extracted delivery docket are required.")

        applied_config = config or ReconciliationConfig(
            quantity_tolerance=str(settings.quantity_tolerance),
            unit_price_tolerance=str(settings.unit_price_tolerance),
            line_amount_tolerance=str(settings.line_amount_tolerance),
            tax_tolerance=str(settings.tax_tolerance),
            total_tolerance=str(settings.total_tolerance),
            low_confidence_threshold=settings.low_confidence_threshold,
        )

        invoice = CanonicalInvoice.model_validate(invoice_record.canonical_payload)
        docket = DeliveryDocket.model_validate(docket_record.canonical_payload)

        run = ReconciliationRunRecord(
            case_id=case_id,
            invoice_id=invoice_record.id,
            delivery_docket_id=docket_record.id,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.add(run)
        db.flush()

        result = reconciliation_engine.reconcile(invoice, docket, applied_config)
        run.status = "approved" if result.approved else "exceptions"
        run.auto_approved = result.approved
        run.overall_score = result.overall_score
        run.config_snapshot = jsonable_encoder(applied_config.model_dump(mode="json"))
        run.result_payload = jsonable_encoder(result.model_dump(mode="json"))
        run.completed_at = datetime.now(UTC).replace(tzinfo=None)

        for issue in result.issues:
            db.add(
                ReconciliationIssueRecord(
                    reconciliation_run_id=run.id,
                    severity=issue.severity.value,
                    reason_code=issue.reason_code.value,
                    entity_type=issue.entity_type,
                    entity_identifier=issue.entity_identifier,
                    field_name=issue.field_name,
                    expected_value=issue.expected_value,
                    actual_value=issue.actual_value,
                    variance_amount=float(issue.variance_amount)
                    if issue.variance_amount is not None
                    else None,
                    variance_percent=float(issue.variance_percent)
                    if issue.variance_percent is not None
                    else None,
                    confidence_score=issue.confidence_score,
                    requires_review=issue.requires_review,
                    status="open",
                )
            )

        case.status = "approved" if result.approved else "exceptions"
        db.commit()
        db.refresh(run)
        return run

    def build_exception_case(self, run: ReconciliationRunRecord) -> ExceptionCase:
        result = ReconciliationResult.model_validate(run.result_payload or {})
        reasons = list(dict.fromkeys(issue.reason_code for issue in result.issues))
        blocking_issue_count = len(
            [issue for issue in result.issues if issue.severity in {IssueSeverity.ERROR, IssueSeverity.CRITICAL}]
        )
        low_confidence_issue_count = len(
            [issue for issue in result.issues if issue.reason_code == ReasonCode.LOW_CONFIDENCE_FIELD]
        )
        suggestions = [
            "Review the extracted header fields with low confidence before posting.",
            "Check invoice lines with quantity or amount mismatches against the delivery docket.",
            "Only export once all blocking issues are resolved or explicitly approved.",
        ]
        return ExceptionCase(
            case_id=run.case_id,
            reconciliation_run_id=run.id,
            status=run.status,
            issue_count=len(result.issues),
            blocking_issue_count=blocking_issue_count,
            low_confidence_issue_count=low_confidence_issue_count,
            reasons=reasons,
            suggested_actions=suggestions,
        )


reconciliation_service = ReconciliationService()
