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
    ReconciliationIssue,
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

        applied_config = self._resolve_config(config)

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

        self._close_prior_issues(db, case_id=case_id)
        result = reconciliation_engine.reconcile(invoice, docket, applied_config)
        self._persist_run(
            db,
            case=case,
            run=run,
            result=result,
            config_snapshot=applied_config.model_dump(mode="json"),
        )
        return run

    def run_manual(
        self,
        db: Session,
        *,
        case_id: str,
        base_reconciliation_run_id: str,
        pairs: list[tuple[int, int, int]],
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
        latest_run = db.scalar(
            select(ReconciliationRunRecord)
            .where(ReconciliationRunRecord.case_id == case_id)
            .order_by(ReconciliationRunRecord.created_at.desc())
        )
        if invoice_record is None or docket_record is None:
            raise ValueError("Both an extracted invoice and an extracted delivery docket are required.")
        if latest_run is None:
            raise ValueError("Reconciliation must be run before applying manual changes.")
        if latest_run.id != base_reconciliation_run_id:
            raise ValueError("Manual reconciliation is stale. Reload the latest reconciliation and try again.")

        invoice = CanonicalInvoice.model_validate(invoice_record.canonical_payload)
        docket = DeliveryDocket.model_validate(docket_record.canonical_payload)
        applied_config = self._resolve_config(
            config,
            fallback_result=ReconciliationResult.model_validate(latest_run.result_payload or {}),
        )
        sorted_pairs = sorted(pairs, key=lambda item: item[2])

        self._validate_manual_pairs(invoice, docket, sorted_pairs)

        base_result = ReconciliationResult.model_validate(latest_run.result_payload or {})
        base_pairs = {
            line.invoice_line_number: line.docket_line_number
            for line in base_result.reconciled_lines
            if line.invoice_line_number is not None and line.docket_line_number is not None
        }

        run = ReconciliationRunRecord(
            case_id=case_id,
            invoice_id=invoice_record.id,
            delivery_docket_id=docket_record.id,
            status="running",
            started_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.add(run)
        db.flush()

        self._close_prior_issues(db, case_id=case_id)
        result = reconciliation_engine.reconcile_manual(
            invoice,
            docket,
            applied_config,
            pairs=sorted_pairs,
            base_pairs=base_pairs,
        )
        self._persist_run(
            db,
            case=case,
            run=run,
            result=result,
            config_snapshot={
                **applied_config.model_dump(mode="json"),
                "reconciliation_mode": "manual",
                "base_reconciliation_run_id": base_reconciliation_run_id,
                "pairs": [
                    {
                        "invoice_line_number": invoice_line_number,
                        "docket_line_number": docket_line_number,
                        "position": position,
                    }
                    for invoice_line_number, docket_line_number, position in sorted_pairs
                ],
            },
        )
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

    def _resolve_config(
        self,
        config: ReconciliationConfig | None,
        fallback_result: ReconciliationResult | None = None,
    ) -> ReconciliationConfig:
        if config is not None:
            return config
        if fallback_result is not None:
            return fallback_result.applied_config
        return ReconciliationConfig(
            quantity_tolerance=str(settings.quantity_tolerance),
            unit_price_tolerance=str(settings.unit_price_tolerance),
            line_amount_tolerance=str(settings.line_amount_tolerance),
            tax_tolerance=str(settings.tax_tolerance),
            total_tolerance=str(settings.total_tolerance),
            low_confidence_threshold=settings.low_confidence_threshold,
        )

    def _close_prior_issues(self, db: Session, *, case_id: str) -> None:
        prior_issues = db.scalars(
            select(ReconciliationIssueRecord)
            .join(
                ReconciliationRunRecord,
                ReconciliationIssueRecord.reconciliation_run_id == ReconciliationRunRecord.id,
            )
            .where(ReconciliationRunRecord.case_id == case_id, ReconciliationIssueRecord.status == "open")
        ).all()
        for issue in prior_issues:
            issue.status = "closed"

    def _persist_run(
        self,
        db: Session,
        *,
        case: CaseRecord,
        run: ReconciliationRunRecord,
        result: ReconciliationResult,
        config_snapshot: dict[str, object],
    ) -> None:
        run.status = "approved" if result.approved else "exceptions"
        run.auto_approved = result.approved
        run.overall_score = result.overall_score
        run.config_snapshot = jsonable_encoder(config_snapshot)
        run.result_payload = jsonable_encoder(result.model_dump(mode="json"))
        run.completed_at = datetime.now(UTC).replace(tzinfo=None)

        for issue in result.issues:
            self._persist_issue(db, reconciliation_run_id=run.id, issue=issue)

        case.status = "approved" if result.approved else "exceptions"
        db.commit()
        db.refresh(run)

    def _persist_issue(
        self,
        db: Session,
        *,
        reconciliation_run_id: str,
        issue: ReconciliationIssue,
    ) -> None:
        db.add(
            ReconciliationIssueRecord(
                reconciliation_run_id=reconciliation_run_id,
                severity=issue.severity.value,
                reason_code=issue.reason_code.value,
                entity_type=issue.entity_type,
                entity_identifier=issue.entity_identifier,
                field_name=issue.field_name,
                expected_value=issue.expected_value,
                actual_value=issue.actual_value,
                variance_amount=float(issue.variance_amount) if issue.variance_amount is not None else None,
                variance_percent=float(issue.variance_percent) if issue.variance_percent is not None else None,
                confidence_score=issue.confidence_score,
                requires_review=issue.requires_review,
                status="open",
            )
        )

    def _validate_manual_pairs(
        self,
        invoice: CanonicalInvoice,
        docket: DeliveryDocket,
        pairs: list[tuple[int, int, int]],
    ) -> None:
        invoice_line_numbers = {line.line_number for line in invoice.lines}
        docket_line_numbers = {line.line_number for line in docket.lines}

        seen_invoice_lines: set[int] = set()
        seen_docket_lines: set[int] = set()
        for invoice_line_number, docket_line_number, _ in pairs:
            if invoice_line_number not in invoice_line_numbers:
                raise ValueError(f"Invoice line {invoice_line_number} was not found in the latest invoice.")
            if docket_line_number not in docket_line_numbers:
                raise ValueError(f"Docket line {docket_line_number} was not found in the latest docket.")
            if invoice_line_number in seen_invoice_lines:
                raise ValueError(f"Invoice line {invoice_line_number} cannot be paired more than once.")
            if docket_line_number in seen_docket_lines:
                raise ValueError(f"Docket line {docket_line_number} cannot be paired more than once.")
            seen_invoice_lines.add(invoice_line_number)
            seen_docket_lines.add(docket_line_number)


reconciliation_service = ReconciliationService()
