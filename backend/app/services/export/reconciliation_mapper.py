from __future__ import annotations

from app.schemas.canonical import (
    CanonicalInvoice,
    DeliveryDocket,
    MatchStatus,
    ReasonCode,
    ReconciledLine,
    ReconciliationExportRow,
    ReconciliationResult,
)


class ReconciliationExportMapper:
    columns = [
        "Product Code",
        "Product name",
        "Quantity - Invoice",
        "Quantity - Docket",
        "Amount - Invoice",
        "Amount - Docket",
        "Mismatch (Yes/No)",
        "Comment on the Mismatch",
    ]

    def map_rows(
        self,
        invoice: CanonicalInvoice,
        docket: DeliveryDocket,
        reconciliation: ReconciliationResult,
    ) -> list[ReconciliationExportRow]:
        invoice_line_lookup = {line.line_number: line for line in invoice.lines}
        docket_line_lookup = {line.line_number: line for line in docket.lines}
        rows: list[ReconciliationExportRow] = []
        for row_number, reconciled_line in enumerate(reconciliation.reconciled_lines, start=1):
            invoice_line = (
                invoice_line_lookup.get(reconciled_line.invoice_line_number)
                if reconciled_line.invoice_line_number is not None
                else None
            )
            docket_line = (
                docket_line_lookup.get(reconciled_line.docket_line_number)
                if reconciled_line.docket_line_number is not None
                else None
            )
            rows.append(
                ReconciliationExportRow(
                    row_number=row_number,
                    invoice_number=invoice.header.invoice_number,
                    invoice_date=invoice.header.invoice_date,
                    docket_number=docket.docket_number,
                    invoice_line_number=reconciled_line.invoice_line_number,
                    docket_line_number=reconciled_line.docket_line_number,
                    product_code=(
                        invoice_line.product_code
                        if invoice_line is not None
                        else docket_line.product_code
                        if docket_line is not None
                        else reconciled_line.product_code
                    ),
                    description=(
                        invoice_line.description
                        if invoice_line is not None
                        else docket_line.description
                        if docket_line is not None
                        else reconciled_line.description
                    ),
                    invoice_quantity=invoice_line.quantity if invoice_line is not None else None,
                    invoice_amount=invoice_line.net_amount if invoice_line is not None else None,
                    docket_quantity=(
                        docket_line.quantity_delivered
                        if docket_line is not None
                        else reconciled_line.delivered_quantity
                    ),
                    docket_amount=(
                        docket_line.extended_amount
                        if docket_line is not None
                        else reconciled_line.delivery_net_amount
                    ),
                    quantity_variance=reconciled_line.variance_quantity,
                    amount_variance=reconciled_line.variance_amount,
                    match_status=reconciled_line.status,
                    final_comment=self._build_final_comment(reconciled_line),
                )
            )

        return rows

    def to_csv_row(self, row: ReconciliationExportRow) -> dict[str, str]:
        mismatch = self._is_mismatch(row.match_status)
        return {
            "Product Code": row.product_code or "",
            "Product name": row.description,
            "Quantity - Invoice": self._stringify(row.invoice_quantity),
            "Quantity - Docket": self._stringify(row.docket_quantity),
            "Amount - Invoice": self._stringify(row.invoice_amount),
            "Amount - Docket": self._stringify(row.docket_amount),
            "Mismatch (Yes/No)": "Yes" if mismatch else "No",
            "Comment on the Mismatch": row.final_comment if mismatch else "",
        }

    def _build_final_comment(self, line: ReconciledLine) -> str:
        reason_messages = {
            ReasonCode.LINE_MISSING_IN_DOCKET: "Missing in docket",
            ReasonCode.LINE_ONLY_ON_DOCKET: "Only on docket",
            ReasonCode.LINE_QTY_MISMATCH: "Quantity mismatch",
            ReasonCode.LINE_UNIT_PRICE_MISMATCH: "Unit price mismatch",
            ReasonCode.LINE_AMOUNT_MISMATCH: "Amount mismatch",
        }
        comments = [reason_messages[reason] for reason in line.reason_codes if reason in reason_messages]
        if comments:
            return "; ".join(dict.fromkeys(comments))
        if line.status == MatchStatus.MATCHED:
            return "Matched"
        if line.status == MatchStatus.WITHIN_TOLERANCE:
            return "Within tolerance"
        if line.status == MatchStatus.MISMATCH:
            return "Mismatch"
        return "Review required"

    def _stringify(self, value: object | None) -> str:
        return "" if value is None else str(value)

    def _is_mismatch(self, status: MatchStatus) -> bool:
        return status in {MatchStatus.MISMATCH, MatchStatus.REVIEW_REQUIRED}


reconciliation_export_mapper = ReconciliationExportMapper()
