from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.schemas.canonical import DocumentType, ProviderExtractionResult


@dataclass(slots=True)
class DocumentExtractionContext:
    document_id: str
    case_id: str
    source_filename: str
    doc_type: DocumentType
    absolute_path: Path


class DocumentExtractionProvider(ABC):
    name: str

    @abstractmethod
    def extract(self, context: DocumentExtractionContext) -> ProviderExtractionResult:
        raise NotImplementedError
