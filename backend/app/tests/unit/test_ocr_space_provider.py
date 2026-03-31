from pathlib import Path

from decimal import Decimal

from app.schemas.canonical import CanonicalInvoice, DeliveryDocket, DocumentType
from app.services.extraction.providers.base import DocumentExtractionContext
from app.services.extraction.providers.ocr_space_provider import (
    OCRSpaceExtractionProvider,
    OCRSpacePageResult,
)


def make_context(doc_type: DocumentType, filename: str) -> DocumentExtractionContext:
    return DocumentExtractionContext(
        document_id="doc-ocr-space-1",
        case_id="case-ocr-space-1",
        source_filename=filename,
        doc_type=doc_type,
        absolute_path=Path(filename),
    )


def make_page_result(
    page_number: int,
    parsed_text: str,
    lines: list[str],
) -> OCRSpacePageResult:
    return OCRSpacePageResult(
        page_number=page_number,
        rotation=0,
        parsed_text=parsed_text,
        parsed_result={"TextOverlay": {"Lines": [{"LineText": line} for line in lines]}},
        score=100.0,
    )


def test_delivery_table_builds_rows_from_tabbed_text() -> None:
    provider = OCRSpaceExtractionProvider()
    table = provider._build_delivery_table(
        1,
        "\n".join(
            [
                "Qty\tDescription\tCode",
                "BRAN HI-FIBRE\t102",
                "1\tBARRELL BROWN\t117",
            ]
        ),
    )

    assert table is not None
    assert table["row_count"] == 3
    assert table["column_count"] == 3
    assert table["cells"][3]["content"] == "1"
    assert table["cells"][4]["content"] == "BRAN HI-FIBRE"
    assert table["cells"][5]["content"] == "102"


def test_invoice_pdf_page_selection_prefers_first_and_last_pages() -> None:
    provider = OCRSpaceExtractionProvider()

    assert provider._pdf_page_indexes(1, DocumentType.INVOICE) == [0]
    assert provider._pdf_page_indexes(13, DocumentType.INVOICE) == [0, 1, 2, 11, 12]


def test_invoice_analysis_documents_extracts_header_fields() -> None:
    provider = OCRSpaceExtractionProvider()
    page_one = make_page_result(
        1,
        "\n".join(
            [
                "Invoice Number: 598527",
                "Invoice Date: 24/03/2026",
                "Account Number\t64876",
                "Store Number\t2064",
            ]
        ),
        [
            "From:",
            "Musgrave Retail Partners Ireland",
            "VAT Registration No.",
            "IE6388047V",
        ],
    )
    page_two = make_page_result(
        2,
        "\n".join(
            [
                "Sub Total: 706.70",
                "VAT Total: 109.72",
                "Invoice Total: 816.42",
                "Docket: 391871",
            ]
        ),
        [],
    )

    documents = provider._analysis_documents(
        DocumentType.INVOICE,
        [page_one, page_two],
        "\n".join([page_one.parsed_text, page_two.parsed_text]),
    )

    assert len(documents) == 1
    fields = documents[0]["fields"]
    assert fields["InvoiceId"]["value_string"] == "598527"
    assert fields["InvoiceDate"]["value_date"] == "2026-03-24"
    assert fields["CustomerId"]["value_string"] == "64876"
    assert fields["StoreNumber"]["value_string"] == "2064"
    assert fields["VendorName"]["value_string"] == "Musgrave Retail Partners Ireland"
    assert fields["VendorTaxId"]["value_string"] == "IE6388047V"
    assert fields["SubTotal"]["value_currency"]["amount"] == 706.7
    assert fields["InvoiceTotal"]["value_currency"]["amount"] == 816.42


def test_relaxed_delivery_builder_synthesizes_missing_docket_number() -> None:
    provider = OCRSpaceExtractionProvider()
    context = make_context(DocumentType.DELIVERY_DOCKET, "Delivery Docket.jpeg")
    table = provider._build_delivery_table(
        1,
        "\n".join(
            [
                "QTY\tDESCRIPTION\tCODE",
                "BRAN HI-FIBRE\t102",
                "1\tBARRELL BROWN\t117",
            ]
        ),
    )
    analysis = {
        "api_version": "ocr.space-2",
        "content": "\n".join(
            [
                "Deliver to: 1888",
                "CENTRA 2056-DROMO",
                "Date: 16/03/26",
                "Signed by: Store Receiver",
            ]
        ),
        "pages": [{"page_number": 1}],
        "tables": [table] if table is not None else [],
    }

    result = provider._build_delivery_docket_result_relaxed(context, analysis, "ocr.space-engine-2")
    docket = DeliveryDocket.model_validate(result.canonical_payload)

    assert docket.docket_number == "DD-20260316-2056"
    assert docket.docket_date.isoformat() == "2026-03-16"
    assert docket.account_number == "1888"
    assert docket.store_number == "2056"
    assert len(docket.lines) == 2
    assert any(field.field_path == "docket_number" for field in result.low_confidence_fields)


def test_relaxed_invoice_builder_backfills_missing_totals() -> None:
    provider = OCRSpaceExtractionProvider()
    context = make_context(
        DocumentType.INVOICE,
        "Invoice_598527_Account_64876_Division_MRPI.pdf",
    )
    analysis = {
        "api_version": "ocr.space-2",
        "content": "\n".join(
            [
                "Invoice Number: 598527",
                "Date: 24/03/2026",
                "Account Number: 64876",
                "Store Number: 2064",
                "Musgrave Retail Partners Ireland",
                "Amount Due 816.42",
            ]
        ),
        "pages": [{"page_number": 1}],
        "documents": [
            {
                "doc_type": "invoice",
                "confidence": 0.72,
                "fields": {
                    "InvoiceId": {
                        "value_string": "598527",
                        "confidence": 0.88,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "InvoiceDate": {
                        "value_date": "2026-03-24",
                        "confidence": 0.85,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "CustomerId": {
                        "value_string": "64876",
                        "confidence": 0.83,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "StoreNumber": {
                        "value_string": "2064",
                        "confidence": 0.78,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "VendorName": {
                        "value_string": "Musgrave Retail Partners Ireland",
                        "confidence": 0.76,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "InvoiceTotal": {
                        "value_currency": {"amount": 816.42, "currency_code": "EUR"},
                        "confidence": 0.74,
                        "bounding_regions": [{"page_number": 1}],
                    },
                },
            }
        ],
    }

    result = provider._build_invoice_result(context, analysis, "ocr.space-engine-2")
    invoice = CanonicalInvoice.model_validate(result.canonical_payload)

    assert invoice.header.invoice_number == "598527"
    assert invoice.header.invoice_date.isoformat() == "2026-03-24"
    assert invoice.header.account_number == "64876"
    assert invoice.header.store_number == "2064"
    assert invoice.header.gross_total == Decimal("816.42")
    assert invoice.header.tax_total == Decimal("0.00")
    assert invoice.header.subtotal_amount == Decimal("816.42")
    assert any(field.field_path == "header.tax_total" for field in result.low_confidence_fields)
