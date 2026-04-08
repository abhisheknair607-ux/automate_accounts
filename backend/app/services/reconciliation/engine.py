from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

from app.schemas.canonical import (
    CanonicalInvoice,
    DeliveryDocket,
    DeliveryLine,
    FieldConfidence,
    InvoiceLine,
    IssueSeverity,
    MatchOrigin,
    MatchStatus,
    ReasonCode,
    ReconciledLine,
    ReconciliationConfig,
    ReconciliationIssue,
    ReconciliationResult,
    ReconciliationTotals,
    TextMatchRule,
)


class ReconciliationEngine:
    def reconcile(
        self,
        invoice: CanonicalInvoice,
        docket: DeliveryDocket,
        config: ReconciliationConfig,
    ) -> ReconciliationResult:
        header_matches = self._build_header_matches(invoice, docket, config)
        issues = self._build_header_issues(invoice, docket, header_matches)

        reconciled_lines: list[ReconciledLine] = []
        unmatched_docket_indexes = set(range(len(docket.lines)))

        for invoice_line in invoice.lines:
            matched_index, docket_line = self._find_matching_docket_line(
                invoice_line=invoice_line,
                docket_lines=docket.lines,
                unmatched_indexes=unmatched_docket_indexes,
                config=config,
            )
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
                    self._build_unmatched_invoice_line(
                        invoice_line,
                        match_origin=MatchOrigin.AUTO,
                    )
                )
                continue

            unmatched_docket_indexes.discard(matched_index)
            reconciled_line, line_issues = self._compare_matched_lines(
                invoice_line=invoice_line,
                docket_line=docket_line,
                config=config,
                match_origin=MatchOrigin.AUTO,
                manual_pair_position=None,
            )
            reconciled_lines.append(reconciled_line)
            issues.extend(line_issues)

        for unmatched_index in sorted(unmatched_docket_indexes):
            extra_line = docket.lines[unmatched_index]
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
                self._build_unmatched_docket_line(
                    extra_line,
                    match_origin=MatchOrigin.AUTO,
                )
            )

        return self._finalize_result(
            invoice=invoice,
            docket=docket,
            config=config,
            header_matches=header_matches,
            reconciled_lines=reconciled_lines,
            issues=issues,
        )

    def reconcile_manual(
        self,
        invoice: CanonicalInvoice,
        docket: DeliveryDocket,
        config: ReconciliationConfig,
        *,
        pairs: list[tuple[int, int, int]],
        base_pairs: dict[int, int] | None = None,
    ) -> ReconciliationResult:
        header_matches = self._build_header_matches(invoice, docket, config)
        issues = self._build_header_issues(invoice, docket, header_matches)
        base_pairs = base_pairs or {}

        invoice_lookup = {line.line_number: line for line in invoice.lines}
        docket_lookup = {line.line_number: line for line in docket.lines}
        base_docket_pairs = set(base_pairs.values())

        paired_invoice_numbers: set[int] = set()
        paired_docket_numbers: set[int] = set()
        reconciled_lines: list[ReconciledLine] = []

        for invoice_line_number, docket_line_number, position in sorted(pairs, key=lambda item: item[2]):
            invoice_line = invoice_lookup[invoice_line_number]
            docket_line = docket_lookup[docket_line_number]
            paired_invoice_numbers.add(invoice_line_number)
            paired_docket_numbers.add(docket_line_number)

            match_origin = (
                MatchOrigin.AUTO
                if base_pairs.get(invoice_line_number) == docket_line_number
                else MatchOrigin.MANUAL
            )
            reconciled_line, line_issues = self._compare_matched_lines(
                invoice_line=invoice_line,
                docket_line=docket_line,
                config=config,
                match_origin=match_origin,
                manual_pair_position=position,
            )
            reconciled_lines.append(reconciled_line)
            issues.extend(line_issues)

        for invoice_line in invoice.lines:
            if invoice_line.line_number in paired_invoice_numbers:
                continue
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
                self._build_unmatched_invoice_line(
                    invoice_line,
                    match_origin=(
                        MatchOrigin.MANUAL
                        if invoice_line.line_number in base_pairs
                        else MatchOrigin.AUTO
                    ),
                )
            )

        for docket_line in docket.lines:
            if docket_line.line_number in paired_docket_numbers:
                continue
            issues.append(
                self._issue(
                    severity=IssueSeverity.WARNING,
                    reason_code=ReasonCode.LINE_ONLY_ON_DOCKET,
                    entity_type="delivery_line",
                    entity_identifier=str(docket_line.line_number),
                    field_name="product_code",
                    expected=None,
                    actual=docket_line.product_code or docket_line.description,
                    message="Delivery docket contains a line not present on the invoice.",
                )
            )
            reconciled_lines.append(
                self._build_unmatched_docket_line(
                    docket_line,
                    match_origin=(
                        MatchOrigin.MANUAL
                        if docket_line.line_number in base_docket_pairs
                        else MatchOrigin.AUTO
                    ),
                )
            )

        return self._finalize_result(
            invoice=invoice,
            docket=docket,
            config=config,
            header_matches=header_matches,
            reconciled_lines=reconciled_lines,
            issues=issues,
        )

    def _build_header_matches(
        self,
        invoice: CanonicalInvoice,
        docket: DeliveryDocket,
        config: ReconciliationConfig,
    ) -> dict[str, bool]:
        return {
            "invoice_number_valid": self._is_valid_invoice_number(invoice.header.invoice_number),
            "supplier_match": self._supplier_match(invoice, docket, config),
            "account_match": (invoice.header.account_number or "").strip()
            == (docket.account_number or "").strip(),
            "store_match": (invoice.header.store_number or "").strip()
            == (docket.store_number or "").strip(),
        }

    def _build_header_issues(
        self,
        invoice: CanonicalInvoice,
        docket: DeliveryDocket,
        header_matches: dict[str, bool],
    ) -> list[ReconciliationIssue]:
        issues: list[ReconciliationIssue] = []
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
        return issues

    def _compare_matched_lines(
        self,
        *,
        invoice_line: InvoiceLine,
        docket_line: DeliveryLine,
        config: ReconciliationConfig,
        match_origin: MatchOrigin,
        manual_pair_position: int | None,
    ) -> tuple[ReconciledLine, list[ReconciliationIssue]]:
        issues: list[ReconciliationIssue] = []
        variance_quantity = invoice_line.quantity - docket_line.quantity_delivered
        variance_amount = invoice_line.net_amount - (docket_line.extended_amount or Decimal("0.00"))
        line_reasons: list[ReasonCode] = []
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
            if status == MatchStatus.MATCHED:
                status = MatchStatus.REVIEW_REQUIRED

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
            if status == MatchStatus.MATCHED:
                status = MatchStatus.REVIEW_REQUIRED

        if not line_reasons and (
            abs(variance_quantity) > Decimal("0.00") or abs(variance_amount) > Decimal("0.00")
        ):
            status = MatchStatus.WITHIN_TOLERANCE

        reconciled_line = ReconciledLine(
            line_key=self._line_key(invoice_line.product_code or docket_line.product_code, invoice_line.description),
            invoice_line_number=invoice_line.line_number,
            docket_line_number=docket_line.line_number,
            product_code=invoice_line.product_code or docket_line.product_code,
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
            match_origin=match_origin,
            manual_pair_position=manual_pair_position,
        )
        return reconciled_line, issues

    def _build_unmatched_invoice_line(
        self,
        invoice_line: InvoiceLine,
        *,
        match_origin: MatchOrigin,
    ) -> ReconciledLine:
        return ReconciledLine(
            line_key=self._line_key(invoice_line.product_code, invoice_line.description),
            invoice_line_number=invoice_line.line_number,
            product_code=invoice_line.product_code,
            description=invoice_line.description,
            invoiced_quantity=invoice_line.quantity,
            unit_price=invoice_line.unit_price,
            invoice_net_amount=invoice_line.net_amount,
            status=MatchStatus.MISMATCH,
            reason_codes=[ReasonCode.LINE_MISSING_IN_DOCKET],
            match_origin=match_origin,
        )

    def _build_unmatched_docket_line(
        self,
        docket_line: DeliveryLine,
        *,
        match_origin: MatchOrigin,
    ) -> ReconciledLine:
        return ReconciledLine(
            line_key=self._line_key(docket_line.product_code, docket_line.description),
            docket_line_number=docket_line.line_number,
            product_code=docket_line.product_code,
            description=docket_line.description,
            delivered_quantity=docket_line.quantity_delivered,
            delivery_net_amount=docket_line.extended_amount,
            status=MatchStatus.REVIEW_REQUIRED,
            reason_codes=[ReasonCode.LINE_ONLY_ON_DOCKET],
            confidence_score=self._line_confidence({}, docket_line),
            match_origin=match_origin,
        )

    def _finalize_result(
        self,
        *,
        invoice: CanonicalInvoice,
        docket: DeliveryDocket,
        config: ReconciliationConfig,
        header_matches: dict[str, bool],
        reconciled_lines: list[ReconciledLine],
        issues: list[ReconciliationIssue],
    ) -> ReconciliationResult:
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
        self,
        fields: list[FieldConfidence],
        config: ReconciliationConfig,
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

    def _supplier_match(
        self,
        invoice: CanonicalInvoice,
        docket: DeliveryDocket,
        config: ReconciliationConfig,
    ) -> bool:
        return self._text_matches(
            invoice.supplier.legal_name or invoice.supplier.name,
            docket.supplier_name,
            config.supplier_match_rule,
        )

    def _normalize(self, value: str | None) -> str:
        return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

    def _line_key(self, product_code: str | None, description: str) -> str:
        if product_code:
            return self._normalize(product_code)
        return self._normalize(description)

    def _find_matching_docket_line(
        self,
        *,
        invoice_line: InvoiceLine,
        docket_lines: list[DeliveryLine],
        unmatched_indexes: set[int],
        config: ReconciliationConfig,
    ) -> tuple[int | None, DeliveryLine | None]:
        code_matches: list[tuple[int, DeliveryLine]] = []
        name_matches: list[tuple[int, DeliveryLine]] = []

        for index in unmatched_indexes:
            docket_line = docket_lines[index]
            code_match = False
            name_match = self._text_matches(
                invoice_line.description,
                docket_line.description,
                config.product_name_match_rule,
            )

            if invoice_line.product_code and docket_line.product_code:
                code_match = self._text_matches(
                    invoice_line.product_code,
                    docket_line.product_code,
                    config.product_code_match_rule,
                )

            if code_match:
                code_matches.append((index, docket_line))
            if name_match:
                name_matches.append((index, docket_line))

        if code_matches:
            for index, docket_line in code_matches:
                if any(index == name_index for name_index, _ in name_matches):
                    return index, docket_line
            return code_matches[0]

        if name_matches:
            return name_matches[0]

        return None, None

    def _text_matches(self, left: str | None, right: str | None, rule: TextMatchRule) -> bool:
        left_raw = (left or "").strip()
        right_raw = (right or "").strip()
        if not left_raw or not right_raw:
            return False
        if rule == TextMatchRule.EXACT:
            return left_raw.casefold() == right_raw.casefold()

        left_normalized = self._normalize(left_raw)
        right_normalized = self._normalize(right_raw)
        if rule == TextMatchRule.NORMALIZED:
            return left_normalized == right_normalized
        return left_normalized in right_normalized or right_normalized in left_normalized

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
