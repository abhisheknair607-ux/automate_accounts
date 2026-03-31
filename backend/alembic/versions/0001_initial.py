"""Initial invoice reconciliation schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-03-24 20:40:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("case_id", sa.String(length=36), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("doc_type", sa.String(length=64), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("original_path", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("classification_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("extraction_status", sa.String(length=32), nullable=False),
        sa.Column("latest_provider", sa.String(length=128), nullable=True),
        sa.Column("latest_extraction_payload", sa.JSON(), nullable=True),
        sa.Column("low_confidence_fields", sa.JSON(), nullable=True),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_documents_case_id", "documents", ["case_id"])
    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("case_id", sa.String(length=36), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("provider_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_payload", sa.JSON(), nullable=True),
        sa.Column("normalized_payload", sa.JSON(), nullable=True),
        sa.Column("low_confidence_fields", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_extraction_runs_case_id", "extraction_runs", ["case_id"])
    op.create_index("ix_extraction_runs_document_id", "extraction_runs", ["document_id"])
    op.create_table(
        "invoices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("case_id", sa.String(length=36), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("extraction_run_id", sa.String(length=36), sa.ForeignKey("extraction_runs.id"), nullable=True),
        sa.Column("invoice_number", sa.String(length=64), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("account_number", sa.String(length=64), nullable=True),
        sa.Column("store_number", sa.String(length=64), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("supplier_legal_name", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("discount_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("tax_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("gross_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("confidence_scores", sa.JSON(), nullable=True),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index("ix_invoices_case_id", "invoices", ["case_id"])
    op.create_index("ix_invoices_invoice_number", "invoices", ["invoice_number"])
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("invoice_id", sa.String(length=36), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("product_code", sa.String(length=128), nullable=True),
        sa.Column("description", sa.String(length=512), nullable=False),
        sa.Column("department_code", sa.String(length=64), nullable=True),
        sa.Column("unit_of_measure", sa.String(length=32), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("extended_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("net_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("vat_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("vat_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("gross_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("confidence_scores", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"])
    op.create_table(
        "delivery_dockets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("case_id", sa.String(length=36), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("document_id", sa.String(length=36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("extraction_run_id", sa.String(length=36), sa.ForeignKey("extraction_runs.id"), nullable=True),
        sa.Column("docket_number", sa.String(length=64), nullable=True),
        sa.Column("docket_date", sa.Date(), nullable=True),
        sa.Column("account_number", sa.String(length=64), nullable=True),
        sa.Column("store_number", sa.String(length=64), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("invoice_reference", sa.String(length=64), nullable=True),
        sa.Column("subtotal_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("tax_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("gross_total", sa.Numeric(14, 2), nullable=True),
        sa.Column("confidence_scores", sa.JSON(), nullable=True),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index("ix_delivery_dockets_case_id", "delivery_dockets", ["case_id"])
    op.create_index("ix_delivery_dockets_docket_number", "delivery_dockets", ["docket_number"])
    op.create_table(
        "delivery_lines",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("delivery_docket_id", sa.String(length=36), sa.ForeignKey("delivery_dockets.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("product_code", sa.String(length=128), nullable=True),
        sa.Column("description", sa.String(length=512), nullable=False),
        sa.Column("unit_of_measure", sa.String(length=32), nullable=True),
        sa.Column("quantity_delivered", sa.Numeric(14, 3), nullable=False),
        sa.Column("expected_unit_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("extended_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("confidence_scores", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_delivery_lines_delivery_docket_id", "delivery_lines", ["delivery_docket_id"])
    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("case_id", sa.String(length=36), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("delivery_docket_id", sa.String(length=36), sa.ForeignKey("delivery_dockets.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("auto_approved", sa.Boolean(), nullable=False),
        sa.Column("overall_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("config_snapshot", sa.JSON(), nullable=True),
        sa.Column("result_payload", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_reconciliation_runs_case_id", "reconciliation_runs", ["case_id"])
    op.create_table(
        "reconciliation_issues",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("reconciliation_run_id", sa.String(length=36), sa.ForeignKey("reconciliation_runs.id"), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_identifier", sa.String(length=128), nullable=True),
        sa.Column("field_name", sa.String(length=128), nullable=True),
        sa.Column("expected_value", sa.Text(), nullable=True),
        sa.Column("actual_value", sa.Text(), nullable=True),
        sa.Column("variance_amount", sa.Numeric(14, 4), nullable=True),
        sa.Column("variance_percent", sa.Numeric(14, 4), nullable=True),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("requires_review", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_reconciliation_issues_reconciliation_run_id", "reconciliation_issues", ["reconciliation_run_id"])
    op.create_table(
        "exports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("case_id", sa.String(length=36), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("reconciliation_run_id", sa.String(length=36), sa.ForeignKey("reconciliation_runs.id"), nullable=False),
        sa.Column("export_format", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("output_path", sa.String(length=512), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("export_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_exports_case_id", "exports", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_exports_case_id", table_name="exports")
    op.drop_table("exports")
    op.drop_index("ix_reconciliation_issues_reconciliation_run_id", table_name="reconciliation_issues")
    op.drop_table("reconciliation_issues")
    op.drop_index("ix_reconciliation_runs_case_id", table_name="reconciliation_runs")
    op.drop_table("reconciliation_runs")
    op.drop_index("ix_delivery_lines_delivery_docket_id", table_name="delivery_lines")
    op.drop_table("delivery_lines")
    op.drop_index("ix_delivery_dockets_docket_number", table_name="delivery_dockets")
    op.drop_index("ix_delivery_dockets_case_id", table_name="delivery_dockets")
    op.drop_table("delivery_dockets")
    op.drop_index("ix_invoice_lines_invoice_id", table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index("ix_invoices_invoice_number", table_name="invoices")
    op.drop_index("ix_invoices_case_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_extraction_runs_document_id", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_case_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")
    op.drop_index("ix_documents_case_id", table_name="documents")
    op.drop_table("documents")
    op.drop_table("cases")
