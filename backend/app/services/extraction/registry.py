from app.services.extraction.providers.azure_stub import AzureDocumentIntelligenceStubProvider
from app.services.extraction.providers.base import DocumentExtractionProvider
from app.services.extraction.providers.google_document_ai_provider import GoogleDocumentAIExtractionProvider
from app.services.extraction.providers.mock_provider import MockExtractionProvider
from app.services.extraction.providers.ocr_space_provider import OCRSpaceExtractionProvider
from app.services.extraction.providers.tesseract_provider import TesseractExtractionProvider


class ExtractionProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, DocumentExtractionProvider] = {
            "mock": MockExtractionProvider(),
            "azure_document_intelligence": AzureDocumentIntelligenceStubProvider(),
            "google_document_ai": GoogleDocumentAIExtractionProvider(),
            "ocr_space": OCRSpaceExtractionProvider(),
            "tesseract": TesseractExtractionProvider(),
        }

    def get(self, provider_name: str) -> DocumentExtractionProvider:
        try:
            return self._providers[provider_name]
        except KeyError as exc:
            available = ", ".join(sorted(self._providers))
            raise ValueError(f"Unknown extraction provider '{provider_name}'. Available: {available}") from exc


extraction_provider_registry = ExtractionProviderRegistry()
