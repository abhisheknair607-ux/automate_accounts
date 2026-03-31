from __future__ import annotations

from app.schemas.canonical import (
    AccountingTemplateDefinition,
    CanonicalInvoice,
    DeliveryDocket,
    DocumentType,
    ProviderExtractionResult,
)


class ExtractionNormalizer:
    def normalize(self, result: ProviderExtractionResult):
        if result.document_type == DocumentType.INVOICE:
            return CanonicalInvoice.model_validate(result.canonical_payload)
        if result.document_type == DocumentType.DELIVERY_DOCKET:
            return DeliveryDocket.model_validate(result.canonical_payload)
        if result.document_type == DocumentType.ACCOUNTING_TEMPLATE:
            return AccountingTemplateDefinition.model_validate(result.canonical_payload)
        return result.canonical_payload


extraction_normalizer = ExtractionNormalizer()
