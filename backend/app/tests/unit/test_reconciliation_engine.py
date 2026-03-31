from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.schemas.canonical import CanonicalInvoice, DeliveryDocket, ReasonCode, ReconciliationConfig
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
            quantity_tolerance=Decimal("0.00"),
            unit_price_tolerance=Decimal("0.02"),
            line_amount_tolerance=Decimal("0.50"),
            tax_tolerance=Decimal("0.50"),
            total_tolerance=Decimal("0.50"),
            low_confidence_threshold=0.85,
        ),
    )

    reason_codes = {issue.reason_code for issue in result.issues}
    assert result.approved is False
    assert ReasonCode.LINE_QTY_MISMATCH in reason_codes
    assert ReasonCode.GRAND_TOTAL_MISMATCH in reason_codes
    assert result.totals.gross_variance == Decimal("6.51")
