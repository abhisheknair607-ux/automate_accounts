from __future__ import annotations

import json
from pathlib import Path
from decimal import Decimal

from app.schemas.canonical import AccountingTemplateDefinition, CanonicalInvoice, DeliveryDocket
from app.services.export.pnl_template import load_builtin_pnl_template


def test_invoice_fixture_validates(fixture_dir: Path):
    payload = json.loads((fixture_dir / "invoice_mock_extraction.json").read_text(encoding="utf-8"))
    invoice = CanonicalInvoice.model_validate(payload["canonical_payload"])
    assert invoice.header.invoice_number == "598527"
    assert len(invoice.lines) == 8
    assert invoice.header.gross_total == Decimal("816.42")


def test_docket_fixture_validates(fixture_dir: Path):
    payload = json.loads((fixture_dir / "delivery_docket_mock_extraction.json").read_text(encoding="utf-8"))
    docket = DeliveryDocket.model_validate(payload["canonical_payload"])
    assert docket.invoice_reference == "598527"
    assert len(docket.lines) == 8
    assert docket.gross_total == Decimal("809.91")


def test_template_fixture_validates(fixture_dir: Path):
    payload = json.loads((fixture_dir / "accounting_template_mock_extraction.json").read_text(encoding="utf-8"))
    template = AccountingTemplateDefinition.model_validate(payload["canonical_payload"])
    assert template.template_name == "Retail AP Import Template"
    assert any(column.column_name == "Approval Status" for column in template.columns)


def test_builtin_pnl_template_validates():
    template = load_builtin_pnl_template()
    assert template.template_name == "Built-in P&L Purchase Template"
    assert any(column.column_name == "P&L Section" for column in template.columns)
    assert any(column.column_name == "Final Comment" for column in template.columns)
    assert len(template.notes) >= 3
