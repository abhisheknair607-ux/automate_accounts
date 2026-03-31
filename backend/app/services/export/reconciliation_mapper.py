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
        "Invoice Number",
        "Invoice Date",
        "Docket Number",
        "Invoice Line",
        "Docket Line",
        "SKU",
        "Description",
        "Invoice Quantity",
        "Invoice Amount",
        "Docket Quantity",
        "Docket Amount",
        "Quantity Variance",
        "Amount Variance",
        "Match Status",
        "Final Comment",
    ]

    def map_rows(
        self,
        invoice: CanonicalInvoice,
        docket: DeliveryDocket,
        reconciliation: ReconciliationResult,
    ) -> list[ReconciliationExportRow]:
        line_lookup = {
            line.invoice_line_number: line
            for line in reconciliation.reconciled_lines
            if line.invoice_line_number is not None
        }
        rows: list[ReconciliationExportRow] = []
        row_number = 1

        for invoice_line in invoice.lines:
            reconciled_line = line_lookup.get(invoice_line.line_number)
            if reconciled_line is None:
                rows.append(
                    ReconciliationExportRow(
                        row_number=row_number,
                        invoice_number=invoice.header.invoice_number,
                        invoice_date=invoice.header.invoice_date,
                        docket_number=docket.docket_number,
                        invoice_line_number=invoice_line.line_number,
                        product_code=invoice_line.product_code,
                        description=invoice_line.description,
                        invoice_quantity=invoice_line.quantity,
                        invoice_amount=invoice_line.net_amount,
                        match_status=MatchStatus.REVIEW_REQUIRED,
                        final_comment="Invoice line was not reconciled.",
                    )
                )
                row_number += 1
                continue

            rows.append(
                ReconciliationExportRow(
                    row_number=row_number,
                    invoice_number=invoice.header.invoice_number,
                    invoice_date=invoice.header.invoice_date,
                    docket_number=docket.docket_number,
                    invoice_line_number=invoice_line.line_number,
                    docket_line_number=reconciled_line.docket_line_number,
                    product_code=invoice_line.product_code or reconciled_line.product_code,
                    description=invoice_line.description,
                    invoice_quantity=invoice_line.quantity,
                    invoice_amount=invoice_line.net_amount,
                    docket_quantity=reconciled_line.delivered_quantity,
                    docket_amount=reconciled_line.delivery_net_amount,
                    quantity_variance=reconciled_line.variance_quantity,
                    amount_variance=reconciled_line.variance_amount,
                    match_status=reconciled_line.status,
                    final_comment=self._build_final_comment(reconciled_line),
                )
            )
            row_number += 1

        for reconciled_line in reconciliation.reconciled_lines:
            if reconciled_line.invoice_line_number is not None:
                continue

            rows.append(
                ReconciliationExportRow(
                    row_number=row_number,
                    invoice_number=invoice.header.invoice_number,
                    invoice_date=invoice.header.invoice_date,
                    docket_number=docket.docket_number,
                    docket_line_number=reconciled_line.docket_line_number,
                    product_code=reconciled_line.product_code,
                    description=reconciled_line.description,
                    docket_quantity=reconciled_line.delivered_quantity,
                    docket_amount=reconciled_line.delivery_net_amount,
                    quantity_variance=reconciled_line.variance_quantity,
                    amount_variance=reconciled_line.variance_amount,
                    match_status=reconciled_line.status,
                    final_comment=self._build_final_comment(reconciled_line),
                )
            )
            row_number += 1

        return rows

    def to_csv_row(self, row: ReconciliationExportRow) -> dict[str, str]:
        return {
            "Invoice Number": row.invoice_number,
            "Invoice Date": str(row.invoice_date),
            "Docket Number": row.docket_number or "",
            "Invoice Line": self._stringify(row.invoice_line_number),
            "Docket Line": self._stringify(row.docket_line_number),
            "SKU": row.product_code or "",
            "Description": row.description,
            "Invoice Quantity": self._stringify(row.invoice_quantity),
            "Invoice Amount": self._stringify(row.invoice_amount),
            "Docket Quantity": self._stringify(row.docket_quantity),
            "Docket Amount": self._stringify(row.docket_amount),
            "Quantity Variance": self._stringify(row.quantity_variance),
            "Amount Variance": self._stringify(row.amount_variance),
            "Match Status": row.match_status.value,
            "Final Comment": row.final_comment,
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


reconciliation_export_mapper = ReconciliationExportMapper()
