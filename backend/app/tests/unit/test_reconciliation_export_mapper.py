from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.schemas.canonical import (
    CanonicalInvoice,
    DeliveryDocket,
    MatchStatus,
    ReasonCode,
    ReconciledLine,
    ReconciliationConfig,
    ReconciliationResult,
    ReconciliationTotals,
)
from app.services.export.reconciliation_mapper import reconciliation_export_mapper


def load_fixture(path: Path, filename: str):
    return json.loads((path / filename).read_text(encoding="utf-8"))


def test_reconciliation_export_mapper_builds_invoice_first_rows_with_comments(fixture_dir: Path):
    invoice_payload = load_fixture(fixture_dir, "invoice_mock_extraction.json")
    docket_payload = load_fixture(fixture_dir, "delivery_docket_mock_extraction.json")
    invoice = CanonicalInvoice.model_validate(invoice_payload["canonical_payload"])
    docket = DeliveryDocket.model_validate(docket_payload["canonical_payload"])

    invoice_lines = [invoice.lines[0], invoice.lines[2], invoice.lines[3]]
    docket_lines = [docket.lines[0], docket.lines[2], docket.lines[4]]
    invoice = invoice.model_copy(update={"lines": invoice_lines})
    docket = docket.model_copy(update={"lines": docket_lines})

    reconciliation = ReconciliationResult(
        status=MatchStatus.REVIEW_REQUIRED,
        approved=False,
        overall_score=0.72,
        header_matches={
            "invoice_number_valid": True,
            "supplier_match": True,
            "account_match": True,
            "store_match": True,
        },
        totals=ReconciliationTotals(
            invoice_subtotal=invoice.header.subtotal_amount,
            docket_subtotal=docket.subtotal_amount,
            invoice_tax_total=invoice.header.tax_total,
            docket_tax_total=docket.tax_total,
            invoice_gross_total=invoice.header.gross_total,
            docket_gross_total=docket.gross_total,
            subtotal_variance=invoice.header.subtotal_amount - docket.subtotal_amount,
            tax_variance=invoice.header.tax_total - docket.tax_total,
            gross_variance=invoice.header.gross_total - docket.gross_total,
        ),
        reconciled_lines=[
            ReconciledLine(
                line_key="matched-line",
                invoice_line_number=invoice_lines[0].line_number,
                docket_line_number=docket_lines[0].line_number,
                product_code=invoice_lines[0].product_code,
                description=invoice_lines[0].description,
                invoiced_quantity=invoice_lines[0].quantity,
                delivered_quantity=docket_lines[0].quantity_delivered,
                invoice_net_amount=invoice_lines[0].net_amount,
                delivery_net_amount=docket_lines[0].extended_amount,
                variance_quantity=invoice_lines[0].quantity - docket_lines[0].quantity_delivered,
                variance_amount=invoice_lines[0].net_amount - docket_lines[0].extended_amount,
                status=MatchStatus.MATCHED,
            ),
            ReconciledLine(
                line_key="mismatch-line",
                invoice_line_number=invoice_lines[1].line_number,
                docket_line_number=docket_lines[1].line_number,
                product_code=invoice_lines[1].product_code,
                description=invoice_lines[1].description,
                invoiced_quantity=invoice_lines[1].quantity,
                delivered_quantity=docket_lines[1].quantity_delivered,
                invoice_net_amount=invoice_lines[1].net_amount,
                delivery_net_amount=docket_lines[1].extended_amount,
                variance_quantity=invoice_lines[1].quantity - docket_lines[1].quantity_delivered,
                variance_amount=invoice_lines[1].net_amount - docket_lines[1].extended_amount,
                status=MatchStatus.MISMATCH,
                reason_codes=[ReasonCode.LINE_QTY_MISMATCH, ReasonCode.LINE_AMOUNT_MISMATCH],
            ),
            ReconciledLine(
                line_key="missing-line",
                invoice_line_number=invoice_lines[2].line_number,
                product_code=invoice_lines[2].product_code,
                description=invoice_lines[2].description,
                invoiced_quantity=invoice_lines[2].quantity,
                invoice_net_amount=invoice_lines[2].net_amount,
                status=MatchStatus.MISMATCH,
                reason_codes=[ReasonCode.LINE_MISSING_IN_DOCKET],
            ),
            ReconciledLine(
                line_key="docket-only-line",
                docket_line_number=docket_lines[2].line_number,
                product_code=docket_lines[2].product_code,
                description=docket_lines[2].description,
                delivered_quantity=docket_lines[2].quantity_delivered,
                delivery_net_amount=docket_lines[2].extended_amount,
                status=MatchStatus.REVIEW_REQUIRED,
                reason_codes=[ReasonCode.LINE_ONLY_ON_DOCKET],
            ),
        ],
        issues=[],
        applied_config=ReconciliationConfig(),
        created_at=datetime(2026, 3, 31, 12, 0, 0),
    )

    rows = reconciliation_export_mapper.map_rows(invoice, docket, reconciliation)

    assert len(rows) == 4
    assert rows[0].final_comment == "Matched"
    assert rows[1].final_comment == "Quantity mismatch; Amount mismatch"
    assert rows[2].final_comment == "Missing in docket"
    assert rows[3].final_comment == "Only on docket"
    assert rows[3].invoice_quantity is None
    assert rows[3].docket_quantity == docket_lines[2].quantity_delivered
