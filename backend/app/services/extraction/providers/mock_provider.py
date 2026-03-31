from __future__ import annotations

import json
from pathlib import Path

from app.core.config import BACKEND_DIR
from app.schemas.canonical import DocumentType, ProviderExtractionResult
from app.services.extraction.providers.base import (
    DocumentExtractionContext,
    DocumentExtractionProvider,
)


FIXTURE_DIR = BACKEND_DIR / "app" / "sample_data" / "fixtures"


class MockExtractionProvider(DocumentExtractionProvider):
    name = "mock"

    def extract(self, context: DocumentExtractionContext) -> ProviderExtractionResult:
        fixture_path = self._select_fixture(context)
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        return ProviderExtractionResult.model_validate(payload)

    def _select_fixture(self, context: DocumentExtractionContext) -> Path:
        filename = context.source_filename.lower()
        if "invoice_598527" in filename or context.doc_type == DocumentType.INVOICE:
            return FIXTURE_DIR / "invoice_mock_extraction.json"
        if "docket" in filename or context.doc_type == DocumentType.DELIVERY_DOCKET:
            return FIXTURE_DIR / "delivery_docket_mock_extraction.json"
        if "template" in filename or context.doc_type == DocumentType.ACCOUNTING_TEMPLATE:
            return FIXTURE_DIR / "accounting_template_mock_extraction.json"
        return FIXTURE_DIR / "unknown_document_mock_extraction.json"
