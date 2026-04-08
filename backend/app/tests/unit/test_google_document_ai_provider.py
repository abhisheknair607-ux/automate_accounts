from pathlib import Path
from datetime import date
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.schemas.canonical import DocumentType
from app.services.extraction.registry import ExtractionProviderRegistry
from app.services.extraction.providers.google_document_ai_provider import (
    GoogleDocumentAIExtractionProvider,
)
from app.services.extraction.providers.base import DocumentExtractionContext


def make_provider() -> GoogleDocumentAIExtractionProvider:
    settings = Settings(
        _env_file=None,
        google_document_ai_project_id="demo-project",
        google_document_ai_location="us",
        google_document_ai_invoice_processor_id="invoice-processor",
        google_document_ai_layout_processor_id="layout-processor",
    )
    return GoogleDocumentAIExtractionProvider(settings=settings)


def test_registry_includes_google_document_ai_provider() -> None:
    registry = ExtractionProviderRegistry()

    assert isinstance(registry.get("google_document_ai"), GoogleDocumentAIExtractionProvider)


def test_google_document_ai_maps_invoice_entities_and_tables() -> None:
    provider = make_provider()
    analysis = provider._document_to_analysis(
        DocumentType.INVOICE,
        {
            "text": "Invoice Number: 598527\nInvoice Date: 24/03/2026\nSubtotal 706.70\n",
            "pages": [
                {
                    "lines": [
                        {
                            "layout": {
                                "text_anchor": {
                                    "text_segments": [{"start_index": "0", "end_index": "22"}]
                                }
                            }
                        }
                    ],
                    "tables": [
                        {
                            "header_rows": [
                                {
                                    "cells": [
                                        {
                                            "layout": {
                                                "text_anchor": {
                                                    "text_segments": [{"start_index": "0", "end_index": "14"}]
                                                }
                                            }
                                        }
                                    ]
                                }
                            ],
                            "body_rows": [],
                        }
                    ],
                }
            ],
            "entities": [
                {
                    "type_": "invoice_id",
                    "mention_text": "598527",
                    "confidence": 0.94,
                    "page_anchor": {"page_refs": [{}]},
                },
                {
                    "type_": "invoice_date",
                    "mention_text": "24/03/2026",
                    "normalized_value": {"text": "2026-03-24"},
                    "confidence": 0.91,
                    "page_anchor": {"page_refs": [{}]},
                },
                {
                    "type_": "total_amount",
                    "mention_text": "816.42",
                    "normalized_value": {
                        "money_value": {"units": "816", "nanos": 420000000, "currency_code": "EUR"}
                    },
                    "confidence": 0.88,
                    "page_anchor": {"page_refs": [{}]},
                },
                {
                    "type_": "line_item",
                    "confidence": 0.8,
                    "page_anchor": {"page_refs": [{}]},
                    "properties": [
                        {"type_": "description", "mention_text": "BRAN HI-FIBRE", "confidence": 0.82},
                        {"type_": "quantity", "mention_text": "2", "confidence": 0.81},
                        {"type_": "unit_price", "mention_text": "4.50", "confidence": 0.8},
                    ],
                },
            ],
            "revisions": [{"processor": "projects/demo/locations/us/processors/invoice-processor"}],
        },
    )

    assert analysis["api_version"] == "projects/demo/locations/us/processors/invoice-processor"
    assert analysis["pages"][0]["lines"][0]["content"] == "Invoice Number: 598527"
    assert analysis["tables"][0]["row_count"] == 1

    fields = analysis["documents"][0]["fields"]
    assert fields["InvoiceId"]["value_string"] == "598527"
    assert fields["InvoiceDate"]["value_date"] == "2026-03-24"
    assert fields["InvoiceTotal"]["value_currency"]["amount"] == 816.42
    assert fields["Items"]["value_array"][0]["value_object"]["Description"]["value_string"] == "BRAN HI-FIBRE"


def test_google_document_ai_maps_document_layout_tables_to_analysis() -> None:
    provider = make_provider()
    analysis = provider._document_to_analysis(
        DocumentType.DELIVERY_DOCKET,
        {
            "document_layout": {
                "blocks": [
                    {
                        "block_id": "1",
                        "page_span": {"page_start": 1, "page_end": 1},
                        "table_block": {
                            "body_rows": [
                                {
                                    "cells": [
                                        {"blocks": [{"text_block": {"text": "Product"}}]},
                                        {"blocks": [{"text_block": {"text": "QTY"}}]},
                                        {"blocks": [{"text_block": {"text": "NET C"}}]},
                                    ]
                                },
                                {
                                    "cells": [
                                        {"blocks": [{"text_block": {"text": "MAXI TWIST CUP"}}]},
                                        {"blocks": [{"text_block": {"text": "1"}}]},
                                        {"blocks": [{"text_block": {"text": "36.68"}}]},
                                    ]
                                },
                            ]
                        },
                    }
                ]
            }
        },
    )

    assert analysis["content"] == "Product QTY NET C\nMAXI TWIST CUP 1 36.68"
    assert analysis["pages"][0]["lines"][0]["content"] == "Product QTY NET C"
    assert analysis["tables"][0]["row_count"] == 2
    assert analysis["tables"][0]["cells"][0]["content"] == "Product"


def test_google_document_ai_builds_relaxed_invoice_from_text_only_content() -> None:
    provider = make_provider()
    analysis = {
        "api_version": "google-document-ai",
        "content": "ACME Foods\nInvoice Date: 2026-04-01\nTotal Due 12.34",
        "pages": [{"page_number": 1, "lines": [{"content": "ACME Foods"}]}],
        "tables": [],
        "documents": [],
    }
    context = DocumentExtractionContext(
        document_id="abcd1234-0000-0000-0000-000000000000",
        case_id="case-1",
        source_filename="Invoice.pdf",
        doc_type=DocumentType.INVOICE,
        absolute_path=Path("Invoice.pdf"),
    )

    result = provider._build_invoice_result_relaxed(context, analysis, "invoice-processor")

    assert result.document_type == DocumentType.INVOICE
    assert result.canonical_payload["header"]["invoice_number"] == "INV-ABCD1234"
    assert result.canonical_payload["header"]["invoice_date"] == date(2026, 4, 1)
    assert result.canonical_payload["supplier"]["name"] == "ACME Foods"
    assert result.canonical_payload["header"]["gross_total"] == Decimal("12.34")


def test_google_document_ai_builds_relaxed_delivery_docket_from_layout_only_content() -> None:
    provider = make_provider()
    analysis = provider._document_to_analysis(
        DocumentType.DELIVERY_DOCKET,
        {
            "document_layout": {
                "blocks": [
                    {
                        "block_id": "1",
                        "page_span": {"page_start": 1, "page_end": 1},
                        "table_block": {
                            "body_rows": [
                                {
                                    "cells": [
                                        {"blocks": [{"text_block": {"text": "Product"}}]},
                                        {"blocks": [{"text_block": {"text": "QTY"}}]},
                                        {"blocks": [{"text_block": {"text": "NET C"}}]},
                                    ]
                                },
                                {
                                    "cells": [
                                        {"blocks": [{"text_block": {"text": "MAXI TWIST CUP"}}]},
                                        {"blocks": [{"text_block": {"text": "1"}}]},
                                        {"blocks": [{"text_block": {"text": "36.68"}}]},
                                    ]
                                },
                            ]
                        },
                    }
                ]
            }
        },
    )
    context = DocumentExtractionContext(
        document_id="abcd1234-0000-0000-0000-000000000000",
        case_id="case-1",
        source_filename="Delivery Docket - 3.jpeg",
        doc_type=DocumentType.DELIVERY_DOCKET,
        absolute_path=Path("Delivery Docket - 3.jpeg"),
    )

    result = provider._build_delivery_docket_result_relaxed(context, analysis, "layout-processor")

    assert result.document_type == DocumentType.DELIVERY_DOCKET
    assert result.canonical_payload["docket_number"] == "DD-ABCD1234"
    assert result.canonical_payload["supplier_name"] == "Unknown Supplier"
    assert result.canonical_payload["subtotal_amount"] == Decimal("36.68")
    assert result.canonical_payload["lines"][0]["description"] == "MAXI TWIST CUP"


def test_google_document_ai_backfills_sparse_invoice_lines_from_layout_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = make_provider()
    invoice_analysis = {
        "api_version": "invoice-processor",
        "content": "ACME Foods\nInvoice Date: 2026-04-01\nSubtotal 23.30\nVAT 0.00\nTotal Due 23.30",
        "pages": [{"page_number": 1, "lines": [{"content": "ACME Foods"}]}],
        "tables": [],
        "documents": [
            {
                "doc_type": "invoice",
                "confidence": 0.94,
                "fields": {
                    "InvoiceId": {"value_string": "598527", "content": "598527", "confidence": 0.94},
                    "InvoiceDate": {
                        "value_date": "2026-04-01",
                        "content": "2026-04-01",
                        "confidence": 0.91,
                    },
                    "VendorName": {
                        "value_string": "ACME Foods",
                        "content": "ACME Foods",
                        "confidence": 0.89,
                    },
                    "SubTotal": {
                        "value_currency": {"amount": 23.30, "currency_code": "EUR"},
                        "content": "23.30",
                        "confidence": 0.88,
                    },
                    "TotalTax": {
                        "value_currency": {"amount": 0.00, "currency_code": "EUR"},
                        "content": "0.00",
                        "confidence": 0.88,
                    },
                    "InvoiceTotal": {
                        "value_currency": {"amount": 23.30, "currency_code": "EUR"},
                        "content": "23.30",
                        "confidence": 0.88,
                    },
                    "Items": {
                        "value_array": [
                            {
                                "value_object": {
                                    "Amount": {
                                        "value_number": 23.30,
                                        "content": "23.30",
                                        "confidence": 0.91,
                                        "bounding_regions": [{"page_number": 1}],
                                    }
                                },
                                "confidence": 1.0,
                                "bounding_regions": [{"page_number": 1}],
                            }
                        ],
                        "confidence": 1.0,
                    },
                },
            }
        ],
    }
    layout_analysis = provider._document_to_analysis(
        DocumentType.DELIVERY_DOCKET,
        {
            "document_layout": {
                "blocks": [
                    {
                        "block_id": "1",
                        "page_span": {"page_start": 1, "page_end": 1},
                        "table_block": {
                            "body_rows": [
                                {
                                    "cells": [
                                        {"blocks": [{"text_block": {"text": "Product Code"}}]},
                                        {"blocks": [{"text_block": {"text": "Description"}}]},
                                        {"blocks": [{"text_block": {"text": "Qty"}}]},
                                        {"blocks": [{"text_block": {"text": "Net"}}]},
                                        {"blocks": [{"text_block": {"text": "VAT"}}]},
                                        {"blocks": [{"text_block": {"text": "Total"}}]},
                                    ]
                                },
                                {
                                    "cells": [
                                        {"blocks": [{"text_block": {"text": "ABC123"}}]},
                                        {"blocks": [{"text_block": {"text": "BRAN HI-FIBRE"}}]},
                                        {"blocks": [{"text_block": {"text": "2"}}]},
                                        {"blocks": [{"text_block": {"text": "23.30"}}]},
                                        {"blocks": [{"text_block": {"text": "0.00"}}]},
                                        {"blocks": [{"text_block": {"text": "23.30"}}]},
                                    ]
                                },
                            ]
                        },
                    }
                ]
            }
        },
    )

    monkeypatch.setattr(
        provider,
        "_analyze_with_google_document_ai",
        lambda context: ("invoice-processor", invoice_analysis),
    )
    monkeypatch.setattr(
        provider,
        "_analyze_with_google_document_ai_processor",
        lambda context, processor_id, processor_version: ("layout-processor", layout_analysis),
    )

    context = DocumentExtractionContext(
        document_id="abcd1234-0000-0000-0000-000000000000",
        case_id="case-1",
        source_filename="Invoice.pdf",
        doc_type=DocumentType.INVOICE,
        absolute_path=Path("Invoice.pdf"),
    )

    result = provider.extract(context)
    line = result.canonical_payload["lines"][0]

    assert line["product_code"] == "ABC123"
    assert line["description"] == "BRAN HI-FIBRE"
    assert line["quantity"] == Decimal("2")
    assert result.raw_payload["layout_backfill_used"] is True
    assert any("backfilled from Google Document AI layout tables" in note for note in result.canonical_payload["audit"]["notes"])


def test_google_document_ai_extracts_invoice_identities_from_text_blocks() -> None:
    provider = make_provider()
    analysis = {
        "content": "\n".join(
            [
                "Barcode",
                "Product Description",
                "08711327611436",
                "08721274803778",
                "HB 180ML MAXI TWIST X24X108DB",
                "TWISTER 50ML MINIPINEAPP CL1 6MPX6X",
                "Pack Size",
                "Quantity",
                "Unit Cost",
            ]
        ),
        "pages": [{"page_number": 1, "lines": []}],
        "tables": [],
        "documents": [],
    }

    lines = provider._extract_invoice_line_identities_from_text(analysis)

    assert len(lines) == 2
    assert lines[0].product_code == "08711327611436"
    assert lines[0].description == "HB 180ML MAXI TWIST X24X108DB"
    assert lines[1].product_code == "08721274803778"
    assert lines[1].description == "TWISTER 50ML MINIPINEAPP CL1 6MPX6X"


def test_google_document_ai_backfills_invoice_quantities_from_text_blocks() -> None:
    provider = make_provider()
    analysis = {
        "content": "\n".join(
            [
                "Barcode",
                "Product Description",
                "08711327611436",
                "08721274803778",
                "HB 180ML MAXI TWIST X24X108DB",
                "TWISTER 50ML MINIPINEAPP CL1 6MPX6X",
                "Pack Size",
                "Quantity",
                "Unit Cost",
                "Dept Code",
                "1",
                "CS",
                "1",
                "€36.68",
                "G038",
                "1",
                "CS",
                "1",
                "€14.51",
                "G038",
            ]
        ),
        "pages": [{"page_number": 1, "lines": []}],
        "tables": [],
        "documents": [],
    }

    lines = provider._extract_invoice_line_identities_from_text(analysis)

    assert len(lines) == 2
    assert lines[0].quantity == Decimal("1")
    assert lines[1].quantity == Decimal("1")
