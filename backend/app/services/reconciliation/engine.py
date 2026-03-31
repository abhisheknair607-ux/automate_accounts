from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

from app.schemas.canonical import (
    CanonicalInvoice,
    DeliveryDocket,
    DeliveryLine,
    FieldConfidence,
    IssueSeverity,
    MatchStatus,
    ReasonCode,
    ReconciledLine,
    ReconciliationConfig,
    ReconciliationIssue,
    ReconciliationResult,
    ReconciliationTotals,
)


class ReconciliationEngine:
    def reconcile(
        self,
        invoice: CanonicalInvoice,
        docket: DeliveryDocket,
        config: ReconciliationConfig,
    ) -> ReconciliationResult:
        issues: list[ReconciliationIssue] = []
        header_matches = {
            "invoice_number_valid": self._is_valid_invoice_number(invoice.header.invoice_number),
            "supplier_match": self._supplier_match(invoice, docket),
            "account_match": (invoice.header.account_number or "").strip()
            == (docket.account_number or "").strip(),
            "store_match": (invoice.header.store_number or "").strip()
            == (docket.store_number or "").strip(),
        }

        if not header_matches["invoice_number_valid"]:
            issues.append(
                self._issue(
                    severity=IssueSeverity.ERROR,
                    reason_code=ReasonCode.HEADER_INVOICE_NUMBER_INVALID,
                    entity_type="invoice_header",
                    field_name="invoice_number",
                    expected=invoice.header.invoice_number,
                    actual=invoice.header.invoice_number,
                    message="Invoice number failed validation.",
                )
            )
        if not header_matches["supplier_match"]:
            issues.append(
                self._issue(
                    severity=IssueSeverity.ERROR,
                    reason_code=ReasonCode.HEADER_SUPPLIER_MISMATCH,
                    entity_type="invoice_header",
                    field_name="supplier_name",
                    expected=invoice.supplier.legal_name or invoice.supplier.name,
                    actual=docket.supplier_name,
                    message="Supplier on invoice does not match delivery docket.",
                )
            )
        if not header_matches["account_match"]:
            issues.append(
                self._issue(
                    severity=IssueSeverity.ERROR,
                    reason_code=ReasonCode.HEADER_ACCOUNT_MISMATCH,
                    entity_type="invoice_header",
                    field_name="account_number",
                    expected=invoice.header.account_number,
                    actual=docket.account_number,
                    message="Account number mismatch between invoice and delivery docket.",
                )
            )
        if not header_matches["store_match"]:
            issues.append(
                self._issue(
                    severity=IssueSeverity.ERROR,
                    reason_code=ReasonCode.HEADER_STORE_MISMATCH,
                    entity_type="invoice_header",
                    field_name="store_number",
                    expected=invoice.header.store_number,
                    actual=docket.store_number,
                    message="Store number mismatch between invoice and delivery docket.",
                )
            )

        docket_lookup = {self._line_key(line.product_code, line.description): line for line in docket.lines}
        reconciled_lines: list[ReconciledLine] = []
        unmatched_docket = set(docket_lookup)

        for invoice_line in invoice.lines:
            key = self._line_key(invoice_line.product_code, invoice_line.description)
            docket_line = docket_lookup.get(key)

            if docket_line is None:
                issues.append(
                    self._issue(
                        severity=IssueSeverity.ERROR,
                        reason_code=ReasonCode.LINE_MISSING_IN_DOCKET,
                        entity_type="invoice_line",
                        entity_identifier=str(invoice_line.line_number),
                        field_name="product_code",
                        expected=invoice_line.product_code or invoice_line.description,
                        actual=None,
                        message="Invoice line is missing from delivery docket.",
                    )
                )
                reconciled_lines.append(
                    ReconciledLine(
                        line_key=key,
                        invoice_line_number=invoice_line.line_number,
                        product_code=invoice_line.product_code,
                        description=invoice_line.description,
                        invoiced_quantity=invoice_line.quantity,
                        unit_price=invoice_line.unit_price,
                        invoice_net_amount=invoice_line.net_amount,
                        status=MatchStatus.MISMATCH,
                        reason_codes=[ReasonCode.LINE_MISSING_IN_DOCKET],
                    )
                )
                continue

            unmatched_docket.discard(key)
            line_reasons: list[ReasonCode] = []
            variance_quantity = invoice_line.quantity - docket_line.quantity_delivered
            variance_amount = invoice_line.net_amount - (docket_line.extended_amount or Decimal("0.00"))
            status = MatchStatus.MATCHED

            if abs(variance_quantity) > config.quantity_tolerance:
                line_reasons.append(ReasonCode.LINE_QTY_MISMATCH)
                issues.append(
                    self._issue(
                        severity=IssueSeverity.ERROR,
                        reason_code=ReasonCode.LINE_QTY_MISMATCH,
                        entity_type="invoice_line",
                        entity_identifier=str(invoice_line.line_number),
                        field_name="quantity",
                        expected=str(invoice_line.quantity),
                        actual=str(docket_line.quantity_delivered),
                        variance_amount=variance_quantity,
                        message="Quantity mismatch exceeds configured tolerance.",
                    )
                )
                status = MatchStatus.MISMATCH

            if (
                docket_line.expected_unit_price is not None
                and abs(invoice_line.unit_price - docket_line.expected_unit_price)
                > config.unit_price_tolerance
            ):
                line_reasons.append(ReasonCode.LINE_UNIT_PRICE_MISMATCH)
                issues.append(
                    self._issue(
                        severity=IssueSeverity.WARNING,
                        reason_code=ReasonCode.LINE_UNIT_PRICE_MISMATCH,
                        entity_type="invoice_line",
                        entity_identifier=str(invoice_line.line_number),
                        field_name="unit_price",
                        expected=str(invoice_line.unit_price),
                        actual=str(docket_line.expected_unit_price),
                        variance_amount=invoice_line.unit_price - docket_line.expected_unit_price,
                        message="Unit price mismatch exceeds tolerance.",
                    )
                )
                status = MatchStatus.REVIEW_REQUIRED if status == MatchStatus.MATCHED else status

            if docket_line.extended_amount is not None and abs(variance_amount) > config.line_amount_tolerance:
                line_reasons.append(ReasonCode.LINE_AMOUNT_MISMATCH)
                issues.append(
                    self._issue(
                        severity=IssueSeverity.WARNING,
                        reason_code=ReasonCode.LINE_AMOUNT_MISMATCH,
                        entity_type="invoice_line",
                        entity_identifier=str(invoice_line.line_number),
                        field_name="net_amount",
                        expected=str(invoice_line.net_amount),
                        actual=str(docket_line.extended_amount),
                        variance_amount=variance_amount,
                        message="Net amount mismatch exceeds tolerance.",
                    )
                )
                status = MatchStatus.REVIEW_REQUIRED if status == MatchStatus.MATCHED else status

            if not line_reasons and (
                abs(variance_quantity) > Decimal("0.00") or abs(variance_amount) > Decimal("0.00")
            ):
                status = MatchStatus.WITHIN_TOLERANCE

            reconciled_lines.append(
                ReconciledLine(
                    line_key=key,
                    invoice_line_number=invoice_line.line_number,
                    docket_line_number=docket_line.line_number,
                    product_code=invoice_line.product_code,
                    description=invoice_line.description,
                    invoiced_quantity=invoice_line.quantity,
                    delivered_quantity=docket_line.quantity_delivered,
                    unit_price=invoice_line.unit_price,
                    delivery_unit_price=docket_line.expected_unit_price,
                    invoice_net_amount=invoice_line.net_amount,
                    delivery_net_amount=docket_line.extended_amount,
                    variance_quantity=variance_quantity,
                    variance_amount=variance_amount,
                    status=status,
                    reason_codes=line_reasons,
                    confidence_score=self._line_confidence(invoice_line.confidence_scores, docket_line),
                )
            )

        for key in unmatched_docket:
            extra_line = docket_lookup[key]
            issues.append(
                self._issue(
                    severity=IssueSeverity.WARNING,
                    reason_code=ReasonCode.LINE_ONLY_ON_DOCKET,
                    entity_type="delivery_line",
                    entity_identifier=str(extra_line.line_number),
                    field_name="product_code",
                    expected=None,
                    actual=extra_line.product_code or extra_line.description,
                    message="Delivery docket contains a line not present on the invoice.",
                )
            )
            reconciled_lines.append(
                ReconciledLine(
                    line_key=key,
                    docket_line_number=extra_line.line_number,
                    product_code=extra_line.product_code,
                    description=extra_line.description,
                    delivered_quantity=extra_line.quantity_delivered,
                    delivery_net_amount=extra_line.extended_amount,
                    status=MatchStatus.REVIEW_REQUIRED,
                    reason_codes=[ReasonCode.LINE_ONLY_ON_DOCKET],
                    confidence_score=self._line_confidence({}, extra_line),
                )
            )

        totals = self._compare_totals(invoice, docket)
        if abs(totals.tax_variance) > config.tax_tolerance:
            issues.append(
                self._issue(
                    severity=IssueSeverity.WARNING,
                    reason_code=ReasonCode.VAT_TOTAL_MISMATCH,
                    entity_type="totals",
                    field_name="tax_total",
                    expected=str(invoice.header.tax_total),
                    actual=str(docket.tax_total),
                    variance_amount=totals.tax_variance,
                    message="VAT totals differ beyond the configured tolerance.",
                )
            )
        if abs(totals.gross_variance) > config.total_tolerance:
            issues.append(
                self._issue(
                    severity=IssueSeverity.ERROR,
                    reason_code=ReasonCode.GRAND_TOTAL_MISMATCH,
                    entity_type="totals",
                    field_name="gross_total",
                    expected=str(invoice.header.gross_total),
                    actual=str(docket.gross_total),
                    variance_amount=totals.gross_variance,
                    message="Gross totals differ beyond the configured tolerance.",
                )
            )

        issues.extend(self._low_confidence_issues(invoice.low_confidence_fields, config))
        issues.extend(self._low_confidence_issues(docket.low_confidence_fields, config))

        overall_score = self._score(issues, len(reconciled_lines))
        blocking_issues = [issue for issue in issues if issue.severity in {IssueSeverity.ERROR, IssueSeverity.CRITICAL}]
        approved = not blocking_issues
        status = MatchStatus.MATCHED if approved and not issues else MatchStatus.REVIEW_REQUIRED
        if blocking_issues:
            status = MatchStatus.MISMATCH

        return ReconciliationResult(
            status=status,
            approved=approved,
            overall_score=overall_score,
            header_matches=header_matches,
            totals=totals,
            reconciled_lines=reconciled_lines,
            issues=issues,
            applied_config=config,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )

    def _compare_totals(self, invoice: CanonicalInvoice, docket: DeliveryDocket) -> ReconciliationTotals:
        subtotal_variance = invoice.header.subtotal_amount - docket.subtotal_amount
        tax_variance = invoice.header.tax_total - docket.tax_total
        gross_variance = invoice.header.gross_total - docket.gross_total
        return ReconciliationTotals(
            invoice_subtotal=invoice.header.subtotal_amount,
            docket_subtotal=docket.subtotal_amount,
            invoice_tax_total=invoice.header.tax_total,
            docket_tax_total=docket.tax_total,
            invoice_gross_total=invoice.header.gross_total,
            docket_gross_total=docket.gross_total,
            subtotal_variance=subtotal_variance,
            tax_variance=tax_variance,
            gross_variance=gross_variance,
        )

    def _low_confidence_issues(
        self, fields: list[FieldConfidence], config: ReconciliationConfig
    ) -> list[ReconciliationIssue]:
        issues: list[ReconciliationIssue] = []
        for field in fields:
            if field.score < config.low_confidence_threshold:
                issues.append(
                    self._issue(
                        severity=IssueSeverity.WARNING,
                        reason_code=ReasonCode.LOW_CONFIDENCE_FIELD,
                        entity_type="extraction_field",
                        entity_identifier=field.field_path,
                        field_name=field.field_path,
                        actual=str(field.value) if field.value is not None else None,
                        confidence_score=field.score,
                        message=f"Field '{field.field_path}' is below the confidence threshold.",
                    )
                )
        return issues

    def _score(self, issues: list[ReconciliationIssue], line_count: int) -> float:
        penalty = Decimal("0.00")
        weights = {
            IssueSeverity.INFO: Decimal("0.01"),
            IssueSeverity.WARNING: Decimal("0.05"),
            IssueSeverity.ERROR: Decimal("0.15"),
            IssueSeverity.CRITICAL: Decimal("0.25"),
        }
        for issue in issues:
            penalty += weights[issue.severity]
        if line_count:
            penalty = penalty / Decimal(max(1, line_count // 2))
        score = max(Decimal("0.00"), Decimal("1.00") - penalty)
        return float(round(score, 4))

    def _is_valid_invoice_number(self, invoice_number: str) -> bool:
        return bool(re.fullmatch(r"\d{6,}", invoice_number or ""))

    def _supplier_match(self, invoice: CanonicalInvoice, docket: DeliveryDocket) -> bool:
        invoice_name = self._normalize(invoice.supplier.legal_name or invoice.supplier.name)
        docket_name = self._normalize(docket.supplier_name)
        return invoice_name in docket_name or docket_name in invoice_name

    def _normalize(self, value: str | None) -> str:
        return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

    def _line_key(self, product_code: str | None, description: str) -> str:
        if product_code:
            return self._normalize(product_code)
        return self._normalize(description)

    def _line_confidence(self, invoice_confidence: dict[str, float], docket_line: DeliveryLine) -> float:
        values = list(invoice_confidence.values()) + list(docket_line.confidence_scores.values())
        return round(sum(values) / len(values), 4) if values else 1.0

    def _issue(
        self,
        *,
        severity: IssueSeverity,
        reason_code: ReasonCode,
        entity_type: str,
        message: str,
        entity_identifier: str | None = None,
        field_name: str | None = None,
        expected: str | None = None,
        actual: str | None = None,
        variance_amount: Decimal | None = None,
        variance_percent: Decimal | None = None,
        confidence_score: float | None = None,
    ) -> ReconciliationIssue:
        return ReconciliationIssue(
            severity=severity,
            reason_code=reason_code,
            entity_type=entity_type,
            entity_identifier=entity_identifier,
            field_name=field_name,
            expected_value=expected,
            actual_value=actual,
            variance_amount=variance_amount,
            variance_percent=variance_percent,
            confidence_score=confidence_score,
            requires_review=severity != IssueSeverity.INFO,
            message=message,
        )


reconciliation_engine = ReconciliationEngine()
