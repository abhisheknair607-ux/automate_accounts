from pathlib import Path

from app.schemas.canonical import DocumentType


class DocumentClassifier:
    def classify(self, filename: str, mime_type: str | None = None) -> tuple[DocumentType, float]:
        name = filename.lower()
        suffix = Path(filename).suffix.lower()

        if "invoice" in name:
            return DocumentType.INVOICE, 0.99
        if "docket" in name or "delivery" in name:
            return DocumentType.DELIVERY_DOCKET, 0.98
        if "template" in name:
            return DocumentType.ACCOUNTING_TEMPLATE, 0.96
        if suffix == ".pdf":
            return DocumentType.INVOICE, 0.55
        if suffix in {".jpeg", ".jpg", ".png"}:
            return DocumentType.DELIVERY_DOCKET, 0.40
        return DocumentType.UNKNOWN, 0.10


document_classifier = DocumentClassifier()
