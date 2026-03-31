from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.canonical import (
    AccountingTemplateColumn,
    AccountingTemplateDefinition,
    AuditMetadata,
)


def load_builtin_pnl_template() -> AccountingTemplateDefinition:
    return AccountingTemplateDefinition(
        template_name="Built-in P&L Purchase Template",
        template_version="builtin-pnl-1.0",
        columns=[
            AccountingTemplateColumn(column_name="Report Name", source_field="report_name", required=True),
            AccountingTemplateColumn(column_name="P&L Section", source_field="pnl_section", required=True),
            AccountingTemplateColumn(column_name="P&L Line", source_field="pnl_line", required=True),
            AccountingTemplateColumn(column_name="P&L Category", source_field="pnl_category", required=True),
            AccountingTemplateColumn(column_name="P&L Notes", source_field="pnl_notes", required=False, default_value=""),
            AccountingTemplateColumn(column_name="Invoice Number", source_field="invoice_number", required=True),
            AccountingTemplateColumn(column_name="Invoice Date", source_field="invoice_date", required=True),
            AccountingTemplateColumn(column_name="Supplier", source_field="supplier_name", required=True),
            AccountingTemplateColumn(column_name="Supplier Account", source_field="account_number", required=False, default_value=""),
            AccountingTemplateColumn(column_name="Store Number", source_field="store_number", required=False, default_value=""),
            AccountingTemplateColumn(column_name="Docket Number", source_field="docket_number", required=False, default_value=""),
            AccountingTemplateColumn(column_name="SKU", source_field="product_code", required=False, default_value=""),
            AccountingTemplateColumn(column_name="Description", source_field="description", required=True),
            AccountingTemplateColumn(column_name="Department", source_field="department_code", required=False, default_value=""),
            AccountingTemplateColumn(column_name="Invoice Quantity", source_field="invoice_quantity", required=True, default_value="0"),
            AccountingTemplateColumn(column_name="Docket Quantity", source_field="docket_quantity", required=False, default_value="0"),
            AccountingTemplateColumn(column_name="Quantity Variance", source_field="quantity_variance", required=False, default_value="0"),
            AccountingTemplateColumn(column_name="Unit Price", source_field="unit_price", required=True, default_value="0.00"),
            AccountingTemplateColumn(column_name="Invoice Net", source_field="invoice_net_amount", required=True, default_value="0.00"),
            AccountingTemplateColumn(column_name="Docket Net", source_field="delivery_net_amount", required=False, default_value="0.00"),
            AccountingTemplateColumn(column_name="Amount Variance", source_field="amount_variance", required=False, default_value="0.00"),
            AccountingTemplateColumn(column_name="VAT Rate", source_field="vat_rate", required=False, default_value="0.00"),
            AccountingTemplateColumn(column_name="VAT Amount", source_field="vat_amount", required=False, default_value="0.00"),
            AccountingTemplateColumn(column_name="Gross Amount", source_field="gross_amount", required=False, default_value="0.00"),
            AccountingTemplateColumn(column_name="Match Status", source_field="match_status", required=True, default_value="review_required"),
            AccountingTemplateColumn(column_name="Final Comment", source_field="final_comment", required=True, default_value="Review required"),
            AccountingTemplateColumn(column_name="Reconciliation Notes", source_field="reconciliation_notes", required=False, default_value=""),
            AccountingTemplateColumn(column_name="Approval Status", source_field="approval_status", required=True, default_value="review_required"),
        ],
        notes=[
            "This template is bundled with the backend so users only upload the invoice and delivery docket.",
            "The structure is anchored to the constant 'P&L Account.xlsx' workbook in the project root.",
            "Department-driven lines default into Cost of Sales -> Purchases unless a more specific P&L mapping is available.",
            "Quantity and amount variances are kept in the export so finance reviewers can reconcile P&L posting against the delivery docket.",
            "Final Comment and Reconciliation Notes explain why a line is matched, within tolerance, or needs review before posting.",
            "Forecourt, rebates, chill discounts, and other income headings remain documented in the template notes even when the uploaded invoice only contains purchase lines.",
        ],
        audit=AuditMetadata(
            source_filename="P&L Account.xlsx",
            provider_name="system",
            provider_version="builtin-pnl-1.0",
            extracted_at=datetime.now(UTC).replace(tzinfo=None),
            mock_data=False,
            notes=[
                "Generated from the constant backend P&L template configuration.",
                "No user-uploaded accounting template is required for this export.",
            ],
        ),
    )
