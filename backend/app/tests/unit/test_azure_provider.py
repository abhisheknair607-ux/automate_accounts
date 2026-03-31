from pathlib import Path
from decimal import Decimal

from app.schemas.canonical import CanonicalInvoice, DeliveryDocket, DocumentType
from app.services.extraction.providers.azure_stub import AzureDocumentIntelligenceProvider
from app.services.extraction.providers.base import DocumentExtractionContext


def make_context(doc_type: DocumentType, filename: str) -> DocumentExtractionContext:
    return DocumentExtractionContext(
        document_id="doc-1",
        case_id="case-1",
        source_filename=filename,
        doc_type=doc_type,
        absolute_path=Path(filename),
    )


def test_invoice_mapping_builds_canonical_invoice() -> None:
    provider = AzureDocumentIntelligenceProvider()
    context = make_context(
        DocumentType.INVOICE,
        "Invoice_598527_Account_64876_Division_MRPI.pdf",
    )
    analysis = {
        "api_version": "2024-11-30",
        "content": "\n".join(
            [
                "Invoice Number: 598527",
                "Date: 24/03/2026",
                "Account Number: 64876",
                "Store Number: 2064",
                "Division: MRPI",
            ]
        ),
        "pages": [{"page_number": 1}],
        "documents": [
            {
                "doc_type": "invoice",
                "confidence": 0.98,
                "fields": {
                    "VendorName": {
                        "value_string": "Musgrave Retail Partners Ireland",
                        "confidence": 0.97,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "VendorTaxId": {
                        "value_string": "IE6388047V",
                        "confidence": 0.92,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "CustomerId": {
                        "value_string": "64876",
                        "confidence": 0.96,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "InvoiceId": {
                        "value_string": "598527",
                        "confidence": 0.99,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "InvoiceDate": {
                        "value_date": "2026-03-24",
                        "confidence": 0.99,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "SubTotal": {
                        "value_currency": {"amount": 706.70, "currency_code": "EUR"},
                        "confidence": 0.95,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "TotalTax": {
                        "value_currency": {"amount": 109.72, "currency_code": "EUR"},
                        "confidence": 0.94,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "InvoiceTotal": {
                        "value_currency": {"amount": 816.42, "currency_code": "EUR"},
                        "confidence": 0.95,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "PaymentTerm": {
                        "value_string": "30 days EOM",
                        "confidence": 0.91,
                        "bounding_regions": [{"page_number": 1}],
                    },
                    "Items": {
                        "value_array": [
                            {
                                "value_object": {
                                    "ProductCode": {
                                        "value_string": "100245",
                                        "confidence": 0.96,
                                        "bounding_regions": [{"page_number": 1}],
                                    },
                                    "Description": {
                                        "value_string": "Fresh Milk 2L",
                                        "confidence": 0.95,
                                        "bounding_regions": [{"page_number": 1}],
                                    },
                                    "Quantity": {
                                        "value_number": 48,
                                        "confidence": 0.82,
                                        "bounding_regions": [{"page_number": 1}],
                                    },
                                    "Unit": {
                                        "value_string": "CASE",
                                        "confidence": 0.93,
                                        "bounding_regions": [{"page_number": 1}],
                                    },
                                    "UnitPrice": {
                                        "value_number": 2.10,
                                        "confidence": 0.97,
                                        "bounding_regions": [{"page_number": 1}],
                                    },
                                    "Amount": {
                                        "value_number": 100.80,
                                        "confidence": 0.94,
                                        "bounding_regions": [{"page_number": 1}],
                                    },
                                    "TaxAmount": {
                                        "value_number": 13.61,
                                        "confidence": 0.91,
                                        "bounding_regions": [{"page_number": 1}],
                                    },
                                    "TaxRate": {
                                        "value_number": 13.5,
                                        "confidence": 0.9,
                                        "bounding_regions": [{"page_number": 1}],
                                    },
                                }
                            }
                        ]
                    },
                },
            }
        ],
    }

    result = provider._build_invoice_result(context, analysis, "prebuilt-invoice")
    invoice = CanonicalInvoice.model_validate(result.canonical_payload)

    assert result.document_type == DocumentType.INVOICE
    assert invoice.header.invoice_number == "598527"
    assert invoice.header.account_number == "64876"
    assert invoice.header.store_number == "2064"
    assert invoice.header.currency == "EUR"
    assert invoice.lines[0].product_code == "100245"
    assert invoice.lines[0].vat_rate == Decimal("0.135")
    assert any(field.field_path == "lines[0].quantity" for field in result.low_confidence_fields)


def test_delivery_docket_mapping_builds_canonical_docket() -> None:
    provider = AzureDocumentIntelligenceProvider()
    context = make_context(DocumentType.DELIVERY_DOCKET, "Delivery Docket.jpeg")
    analysis = {
        "api_version": "2024-11-30",
        "content": "\n".join(
            [
                "Delivery Docket: DD-240326-2064",
                "Date: 24/03/2026",
                "Supplier: Musgrave Retail Partners Ireland",
                "Account Number: 64876",
                "Store Number: 2064",
                "Invoice Reference: 598527",
                "Vehicle Reference: 07-C-41201",
                "Signed By: Store Receiver",
                "Subtotal: 181.80",
                "VAT: 13.61",
                "Gross Total: 195.41",
            ]
        ),
        "pages": [{"page_number": 1}],
        "tables": [
            {
                "row_count": 3,
                "column_count": 5,
                "cells": [
                    {"row_index": 0, "column_index": 0, "content": "SKU", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 0, "column_index": 1, "content": "Description", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 0, "column_index": 2, "content": "Qty", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 0, "column_index": 3, "content": "Unit Price", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 0, "column_index": 4, "content": "Amount", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 1, "column_index": 0, "content": "100245", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 1, "column_index": 1, "content": "Fresh Milk 2L", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 1, "column_index": 2, "content": "48", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 1, "column_index": 3, "content": "2.10", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 1, "column_index": 4, "content": "100.80", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 2, "column_index": 0, "content": "100310", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 2, "column_index": 1, "content": "White Loaf Bread", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 2, "column_index": 2, "content": "60", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 2, "column_index": 3, "content": "1.35", "bounding_regions": [{"page_number": 1}]},
                    {"row_index": 2, "column_index": 4, "content": "81.00", "bounding_regions": [{"page_number": 1}]},
                ],
            }
        ],
    }

    result = provider._build_delivery_docket_result(context, analysis, "prebuilt-layout")
    docket = DeliveryDocket.model_validate(result.canonical_payload)

    assert result.document_type == DocumentType.DELIVERY_DOCKET
    assert docket.docket_number == "DD-240326-2064"
    assert docket.account_number == "64876"
    assert docket.store_number == "2064"
    assert len(docket.lines) == 2
    assert docket.lines[0].product_code == "100245"
    assert any(field.field_path == "docket_number" for field in result.low_confidence_fields)
