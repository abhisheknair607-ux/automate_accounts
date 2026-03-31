from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook


def test_full_api_flow(client, upload_payloads):
    response = client.post("/api/cases/uploads", files=upload_payloads)
    assert response.status_code == 200
    case = response.json()
    case_id = case["id"]

    extract = client.post(
        f"/api/cases/{case_id}/extract",
        json={"provider_name": "mock", "force": True},
    )
    assert extract.status_code == 200
    assert len(extract.json()["runs"]) == 2

    reconcile = client.post(f"/api/cases/{case_id}/reconcile", json={})
    assert reconcile.status_code == 200
    assert reconcile.json()["status"] == "exceptions"

    reco_export = client.post(f"/api/exports/cases/{case_id}", json={"export_format": "reco_excel"})
    assert reco_export.status_code == 200
    reco_export_payload = reco_export.json()
    assert reco_export_payload["row_count"] == 8
    assert reco_export_payload["export_payload"]["sheet_names"] == ["reco", "invoice"]

    reco_download = client.get(f"/api/exports/{reco_export_payload['id']}/download")
    assert reco_download.status_code == 200
    workbook = load_workbook(BytesIO(reco_download.content))
    assert workbook.sheetnames == ["reco", "invoice"]
    reco_sheet = workbook["reco"]
    invoice_sheet = workbook["invoice"]
    assert reco_sheet["A1"].value == "Invoice Number"
    assert reco_sheet["O4"].value == "Quantity mismatch; Amount mismatch"
    assert invoice_sheet["A1"].value == "Source Document"
    assert invoice_sheet["A2"].value == "invoice"
    assert any(cell.value == "delivery_docket" for cell in invoice_sheet["A"])

    raw_ocr_export = client.post(f"/api/exports/cases/{case_id}", json={"export_format": "ocr_excel"})
    assert raw_ocr_export.status_code == 200
    raw_ocr_export_payload = raw_ocr_export.json()
    assert raw_ocr_export_payload["export_payload"]["sheet_names"] == ["invoice", "docket"]
    assert raw_ocr_export_payload["export_payload"]["sheet_row_counts"]["invoice"] > 0
    assert raw_ocr_export_payload["export_payload"]["sheet_row_counts"]["docket"] > 0

    raw_ocr_download = client.get(f"/api/exports/{raw_ocr_export_payload['id']}/download")
    assert raw_ocr_download.status_code == 200
    raw_workbook = load_workbook(BytesIO(raw_ocr_download.content))
    assert raw_workbook.sheetnames == ["invoice", "docket"]
    raw_invoice_sheet = raw_workbook["invoice"]
    raw_docket_sheet = raw_workbook["docket"]
    assert raw_invoice_sheet["A1"].value == "JSON Path"
    assert raw_docket_sheet["A1"].value == "JSON Path"

    invoice_values = {
        row[0]: row[1]
        for row in raw_invoice_sheet.iter_rows(min_row=2, values_only=True)
        if row[0]
    }
    docket_values = {
        row[0]: row[1]
        for row in raw_docket_sheet.iter_rows(min_row=2, values_only=True)
        if row[0]
    }
    assert invoice_values["source_filename"] == "Invoice_598527_Account_64876_Division_MRPI_Full_unlocked.pdf"
    assert docket_values["source_filename"] == "Delivery Docket.jpeg"
    assert "Mock OCR fixture" in invoice_values["notes[0]"]
    assert "Mock OCR fixture" in docket_values["notes[0]"]

    pnl_export = client.post(f"/api/exports/cases/{case_id}", json={"export_format": "pnl_csv"})
    assert pnl_export.status_code == 200
    pnl_export_payload = pnl_export.json()
    assert pnl_export_payload["row_count"] == 8
    assert pnl_export_payload["export_payload"]["template_name"] == "Built-in P&L Purchase Template"

    pnl_download = client.get(f"/api/exports/{pnl_export_payload['id']}/download")
    assert pnl_download.status_code == 200
    assert "P&L Section" in pnl_download.text
    assert "P&L Notes" in pnl_download.text
    assert "Final Comment" in pnl_download.text

    case_detail = client.get(f"/api/cases/{case_id}")
    assert case_detail.status_code == 200
    detail = case_detail.json()
    assert detail["document_count"] == 2
    assert detail["invoice"]["header"]["invoice_number"] == "598527"
    assert detail["delivery_docket"]["docket_number"] == "DD-240326-2064"
