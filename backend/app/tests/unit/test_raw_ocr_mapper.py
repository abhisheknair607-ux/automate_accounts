from __future__ import annotations

import json
from pathlib import Path

from app.services.export.raw_ocr_mapper import raw_ocr_export_mapper


def test_raw_ocr_mapper_flattens_nested_provider_payload(fixture_dir: Path):
    payload = json.loads((fixture_dir / "invoice_mock_extraction.json").read_text(encoding="utf-8"))["raw_payload"]

    rows = raw_ocr_export_mapper.map_rows(payload)
    values_by_path = {row["JSON Path"]: row["Value"] for row in rows}

    assert values_by_path["source_filename"] == "Invoice_598527_Account_64876_Division_MRPI_Full_unlocked.pdf"
    assert values_by_path["page_count"] == "13"
    assert values_by_path["notes[0]"] == "Mock OCR fixture anchored to the supplied Musgrave invoice sample."
