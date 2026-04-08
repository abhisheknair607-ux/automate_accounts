from __future__ import annotations

from app.schemas.canonical import (
    AccountingExportRow,
    AccountingTemplateDefinition,
    CanonicalInvoice,
    DeliveryDocket,
    MatchStatus,
    ReconciliationResult,
)


P_AND_L_DEPARTMENT_MAP = {
    "CHILL": {
        "section": "Cost of Sales",
        "line": "Purchases",
        "category": "Chilled & Dairy Purchases",
        "notes": "Chilled supplier purchases. Review chill discounts separately under other income headings.",
    },
    "BAKERY": {
        "section": "Cost of Sales",
        "line": "Purchases",
        "category": "Bakery Purchases",
        "notes": "Bakery stock purchases posted as direct cost of sales.",
    },
    "PRODUCE": {
        "section": "Cost of Sales",
        "line": "Purchases",
        "category": "Produce Purchases",
        "notes": "Produce purchases remain in the main purchases line unless stock adjustments are booked later.",
    },
    "GROCERY": {
        "section": "Cost of Sales",
        "line": "Purchases",
        "category": "Grocery Purchases",
        "notes": "Core ambient grocery purchasing line for the P&L workbook.",
    },
    "HOUSE": {
        "section": "Cost of Sales",
        "line": "Purchases",
        "category": "Household Purchases",
        "notes": "Household and cleaning lines stay in purchases until a separate stock-adjust entry is posted.",
    },
    "FROZEN": {
        "section": "Cost of Sales",
        "line": "Purchases",
        "category": "Frozen Purchases",
        "notes": "Frozen product purchases posted to the core purchases bucket.",
    },
    "BEV": {
        "section": "Cost of Sales",
        "line": "Purchases",
        "category": "Beverage Purchases",
        "notes": "Packaged beverage purchases only. Forecourt fuel remains a separate P&L section.",
    },
}


class AccountingExportMapper:
    def map_rows(
        self,
        invoice: CanonicalInvoice,
        docket: DeliveryDocket,
        reconciliation: ReconciliationResult,
        template: AccountingTemplateDefinition,
    ) -> list[AccountingExportRow]:
        invoice_line_lookup = {line.line_number: line for line in invoice.lines}
        docket_line_lookup = {line.line_number: line for line in docket.lines}
        rows: list[AccountingExportRow] = []

        for idx, reconciled_line in enumerate(reconciliation.reconciled_lines, start=1):
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
            department_code = invoice_line.department_code if invoice_line is not None else None
            description = (
                invoice_line.description
                if invoice_line is not None
                else docket_line.description
                if docket_line is not None
                else reconciled_line.description
            )
            pnl_mapping = self._pnl_mapping(department_code, description)
            final_comment = self._final_comment(reconciled_line)
            reconciliation_notes = self._reconciliation_notes(reconciled_line)
            template_values = {
                "Report Name": template.template_name,
                "P&L Section": pnl_mapping["section"],
                "P&L Line": pnl_mapping["line"],
                "P&L Category": pnl_mapping["category"],
                "P&L Notes": pnl_mapping["notes"],
                "Document Number": invoice.header.invoice_number,
                "Document Date": str(invoice.header.invoice_date),
                "Invoice Number": invoice.header.invoice_number,
                "Invoice Date": str(invoice.header.invoice_date),
                "Supplier": invoice.supplier.name,
                "Supplier Account": invoice.header.account_number,
                "Store Number": invoice.header.store_number,
                "Docket Number": docket.docket_number,
                "SKU": (
                    invoice_line.product_code
                    if invoice_line is not None
                    else docket_line.product_code
                    if docket_line is not None
                    else reconciled_line.product_code
                ),
                "Description": description,
                "Department": department_code,
                "Invoiced Qty": str(invoice_line.quantity) if invoice_line is not None else "",
                "Invoice Quantity": str(invoice_line.quantity) if invoice_line is not None else "",
                "Delivered Qty": str(reconciled_line.delivered_quantity)
                if reconciled_line and reconciled_line.delivered_quantity is not None
                else "",
                "Docket Quantity": str(reconciled_line.delivered_quantity)
                if reconciled_line and reconciled_line.delivered_quantity is not None
                else "",
                "Quantity Variance": str(reconciled_line.variance_quantity)
                if reconciled_line and reconciled_line.variance_quantity is not None
                else "",
                "Unit Price": str(invoice_line.unit_price) if invoice_line is not None else "",
                "Invoice Net": str(invoice_line.net_amount) if invoice_line is not None else "",
                "Delivery Net": str(reconciled_line.delivery_net_amount)
                if reconciled_line and reconciled_line.delivery_net_amount is not None
                else "",
                "Docket Net": str(reconciled_line.delivery_net_amount)
                if reconciled_line and reconciled_line.delivery_net_amount is not None
                else "",
                "Amount Variance": str(reconciled_line.variance_amount)
                if reconciled_line and reconciled_line.variance_amount is not None
                else "",
                "VAT Rate": str(invoice_line.vat_rate) if invoice_line is not None else "",
                "VAT Amount": str(invoice_line.vat_amount) if invoice_line is not None else "",
                "Gross Amount": str(invoice_line.gross_amount) if invoice_line is not None else "",
                "Match Status": reconciled_line.status.value,
                "Exception Reasons": ",".join(reason.value for reason in reconciled_line.reason_codes),
                "Final Comment": final_comment,
                "Reconciliation Notes": reconciliation_notes,
                "Approval Status": "approved" if reconciliation.approved else "review_required",
            }

            rows.append(
                AccountingExportRow(
                    row_number=idx,
                    invoice_number=invoice.header.invoice_number,
                    invoice_date=invoice.header.invoice_date,
                    supplier_name=invoice.supplier.name,
                    account_number=invoice.header.account_number,
                    store_number=invoice.header.store_number,
                    docket_number=docket.docket_number,
                    product_code=template_values["SKU"] or None,
                    description=description,
                    department_code=department_code,
                    invoiced_quantity=invoice_line.quantity if invoice_line is not None else None,
                    delivered_quantity=reconciled_line.delivered_quantity,
                    unit_price=invoice_line.unit_price if invoice_line is not None else None,
                    invoice_net_amount=invoice_line.net_amount if invoice_line is not None else None,
                    delivery_net_amount=reconciled_line.delivery_net_amount,
                    vat_rate=invoice_line.vat_rate if invoice_line is not None else None,
                    vat_amount=invoice_line.vat_amount if invoice_line is not None else None,
                    gross_amount=invoice_line.gross_amount if invoice_line is not None else None,
                    match_status=reconciled_line.status,
                    exception_reasons=reconciled_line.reason_codes,
                    approval_status="approved" if reconciliation.approved else "review_required",
                    template_values={
                        column.column_name: template_values.get(column.column_name, column.default_value or "")
                        for column in template.columns
                    },
                )
            )

        return rows

    def _pnl_mapping(self, department_code: str | None, description: str) -> dict[str, str]:
        if department_code:
            mapping = P_AND_L_DEPARTMENT_MAP.get(department_code.upper())
            if mapping:
                return mapping

        return {
            "section": "Cost of Sales",
            "line": "Purchases",
            "category": "Unmapped Purchase Review",
            "notes": f"No fixed department mapping exists for '{description}'. Review before posting to P&L.",
        }

    def _final_comment(self, reconciled_line) -> str:
        if reconciled_line is None:
            return "Review required"

        if not reconciled_line.reason_codes:
            if reconciled_line.status == MatchStatus.MATCHED:
                return "Matched"
            if reconciled_line.status == MatchStatus.WITHIN_TOLERANCE:
                return "Within tolerance"
            if reconciled_line.status == MatchStatus.MISMATCH:
                return "Mismatch"
            return "Review required"

        reason_labels = {
            "line_missing_in_docket": "Missing in docket",
            "line_only_on_docket": "Only on docket",
            "line_qty_mismatch": "Quantity mismatch",
            "line_unit_price_mismatch": "Unit price mismatch",
            "line_amount_mismatch": "Amount mismatch",
        }
        comments = [reason_labels.get(reason.value, reason.value.replace("_", " ")) for reason in reconciled_line.reason_codes]
        return "; ".join(dict.fromkeys(comments))

    def _reconciliation_notes(self, reconciled_line) -> str:
        if reconciled_line is None:
            return "No matched docket line was found for this invoice row."
        if not reconciled_line.reason_codes:
            return "Line reconciled without blocking exceptions."
        return ", ".join(reason.value for reason in reconciled_line.reason_codes)


accounting_export_mapper = AccountingExportMapper()
