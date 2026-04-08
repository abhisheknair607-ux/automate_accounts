from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.schemas.canonical import (
    CanonicalInvoice,
    DeliveryDocket,
    MatchOrigin,
    ReasonCode,
    ReconciliationConfig,
    TextMatchRule,
)
from app.services.reconciliation.engine import reconciliation_engine


def load_fixture(path: Path, filename: str):
    return json.loads((path / filename).read_text(encoding="utf-8"))


def test_reconciliation_detects_quantity_and_total_issues(fixture_dir: Path):
    invoice_payload = load_fixture(fixture_dir, "invoice_mock_extraction.json")
    docket_payload = load_fixture(fixture_dir, "delivery_docket_mock_extraction.json")
    invoice = CanonicalInvoice.model_validate(invoice_payload["canonical_payload"])
    docket = DeliveryDocket.model_validate(docket_payload["canonical_payload"])

    result = reconciliation_engine.reconcile(
        invoice,
        docket,
        ReconciliationConfig(
            supplier_match_rule=TextMatchRule.CONTAINS,
            product_code_match_rule=TextMatchRule.NORMALIZED,
            product_name_match_rule=TextMatchRule.CONTAINS,
            quantity_tolerance=Decimal("0.00"),
            unit_price_tolerance=Decimal("0.02"),
            pre_amount_tolerance=Decimal("0.50"),
            vat_tolerance=Decimal("0.50"),
            total_tolerance=Decimal("0.50"),
            low_confidence_threshold=0.85,
        ),
    )

    reason_codes = {issue.reason_code for issue in result.issues}
    assert result.approved is False
    assert ReasonCode.LINE_QTY_MISMATCH in reason_codes
    assert ReasonCode.GRAND_TOTAL_MISMATCH in reason_codes
    assert result.totals.gross_variance == Decimal("6.51")


def test_reconciliation_supports_strict_supplier_rule(fixture_dir: Path):
    invoice_payload = load_fixture(fixture_dir, "invoice_mock_extraction.json")
    docket_payload = load_fixture(fixture_dir, "delivery_docket_mock_extraction.json")
    invoice = CanonicalInvoice.model_validate(invoice_payload["canonical_payload"])
    docket = DeliveryDocket.model_validate(docket_payload["canonical_payload"])

    invoice.supplier.name = "MUSGRAVE"
    invoice.supplier.legal_name = "MUSGRAVE"
    docket.supplier_name = "Musgrave Processing Hub"

    strict_result = reconciliation_engine.reconcile(
        invoice,
        docket,
        ReconciliationConfig(supplier_match_rule=TextMatchRule.EXACT),
    )
    loose_result = reconciliation_engine.reconcile(
        invoice,
        docket,
        ReconciliationConfig(supplier_match_rule=TextMatchRule.CONTAINS),
    )

    strict_reasons = {issue.reason_code for issue in strict_result.issues}
    loose_reasons = {issue.reason_code for issue in loose_result.issues}
    assert ReasonCode.HEADER_SUPPLIER_MISMATCH in strict_reasons
    assert ReasonCode.HEADER_SUPPLIER_MISMATCH not in loose_reasons


def test_manual_reconciliation_preserves_order_and_origin_for_unchanged_pairs(fixture_dir: Path):
    invoice_payload = load_fixture(fixture_dir, "invoice_mock_extraction.json")
    docket_payload = load_fixture(fixture_dir, "delivery_docket_mock_extraction.json")
    invoice = CanonicalInvoice.model_validate(invoice_payload["canonical_payload"])
    docket = DeliveryDocket.model_validate(docket_payload["canonical_payload"])
    config = ReconciliationConfig()

    auto_result = reconciliation_engine.reconcile(invoice, docket, config)
    base_pairs = {
        line.invoice_line_number: line.docket_line_number
        for line in auto_result.reconciled_lines
        if line.invoice_line_number is not None and line.docket_line_number is not None
    }

    manual_result = reconciliation_engine.reconcile_manual(
        invoice,
        docket,
        config,
        pairs=[(2, 2, 0), (1, 1, 1)],
        base_pairs=base_pairs,
    )

    merged_lines = [
        line
        for line in manual_result.reconciled_lines
        if line.invoice_line_number is not None and line.docket_line_number is not None
    ]
    assert merged_lines[0].invoice_line_number == 2
    assert merged_lines[0].manual_pair_position == 0
    assert merged_lines[0].match_origin == MatchOrigin.AUTO
