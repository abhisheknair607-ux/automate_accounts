from __future__ import annotations

import json
from pathlib import Path

from app.schemas.canonical import CanonicalInvoice, DeliveryDocket
from app.services.export.ocr_extract_mapper import ocr_extract_mapper


def load_fixture(path: Path, filename: str):
    return json.loads((path / filename).read_text(encoding="utf-8"))


def test_ocr_extract_mapper_builds_rows_for_invoice_and_docket(fixture_dir: Path):
    invoice_payload = load_fixture(fixture_dir, "invoice_mock_extraction.json")
    docket_payload = load_fixture(fixture_dir, "delivery_docket_mock_extraction.json")
    invoice = CanonicalInvoice.model_validate(invoice_payload["canonical_payload"])
    docket = DeliveryDocket.model_validate(docket_payload["canonical_payload"])

    rows = ocr_extract_mapper.map_rows(invoice, docket)

    assert len(rows) == len(invoice.lines) + len(docket.lines)
    assert rows[0]["Source Document"] == "invoice"
    assert any(row["Source Document"] == "delivery_docket" for row in rows)
    assert any(row["Document Number"] == docket.docket_number for row in rows if row["Source Document"] == "delivery_docket")
