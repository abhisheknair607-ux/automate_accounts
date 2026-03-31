from __future__ import annotations

from app.schemas.canonical import CanonicalInvoice, DeliveryDocket


class OCRExtractMapper:
    columns = [
        "Source Document",
        "Document Number",
        "Document Date",
        "Supplier",
        "Account Number",
        "Store Number",
        "Invoice Reference",
        "Line Number",
        "SKU",
        "Description",
        "Quantity",
        "Unit Price",
        "Net Amount",
        "VAT Rate",
        "VAT Amount",
        "Gross Amount",
        "Source Reference",
        "OCR Provider",
    ]

    def map_rows(self, invoice: CanonicalInvoice, docket: DeliveryDocket) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []

        for line in invoice.lines:
            rows.append(
                {
                    "Source Document": "invoice",
                    "Document Number": invoice.header.invoice_number,
                    "Document Date": str(invoice.header.invoice_date),
                    "Supplier": invoice.supplier.name,
                    "Account Number": invoice.header.account_number or "",
                    "Store Number": invoice.header.store_number or "",
                    "Invoice Reference": "",
                    "Line Number": str(line.line_number),
                    "SKU": line.product_code or "",
                    "Description": line.description,
                    "Quantity": str(line.quantity),
                    "Unit Price": str(line.unit_price),
                    "Net Amount": str(line.net_amount),
                    "VAT Rate": str(line.vat_rate),
                    "VAT Amount": str(line.vat_amount),
                    "Gross Amount": str(line.gross_amount),
                    "Source Reference": line.source_reference or "",
                    "OCR Provider": invoice.audit.provider_name,
                }
            )

        for line in docket.lines:
            rows.append(
                {
                    "Source Document": "delivery_docket",
                    "Document Number": docket.docket_number,
                    "Document Date": str(docket.docket_date),
                    "Supplier": docket.supplier_name,
                    "Account Number": docket.account_number or "",
                    "Store Number": docket.store_number or "",
                    "Invoice Reference": docket.invoice_reference or "",
                    "Line Number": str(line.line_number),
                    "SKU": line.product_code or "",
                    "Description": line.description,
                    "Quantity": str(line.quantity_delivered),
                    "Unit Price": "" if line.expected_unit_price is None else str(line.expected_unit_price),
                    "Net Amount": "" if line.extended_amount is None else str(line.extended_amount),
                    "VAT Rate": "",
                    "VAT Amount": "",
                    "Gross Amount": "",
                    "Source Reference": line.source_reference or "",
                    "OCR Provider": docket.audit.provider_name,
                }
            )

        return rows


ocr_extract_mapper = OCRExtractMapper()
