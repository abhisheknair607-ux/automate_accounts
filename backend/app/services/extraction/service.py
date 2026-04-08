from __future__ import annotations

from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CaseRecord, DocumentRecord, ExtractionRunRecord
from app.schemas.canonical import (
    AccountingTemplateDefinition,
    CanonicalInvoice,
    DeliveryDocket,
    DocumentType,
)
from app.services.extraction.normalizer import extraction_normalizer
from app.services.extraction.providers.base import DocumentExtractionContext
from app.services.extraction.registry import extraction_provider_registry
from app.services.persistence.canonical import canonical_persistence_service
from app.services.storage.local import local_storage_service


class ExtractionService:
    def extract_case_documents(
        self,
        db: Session,
        *,
        case_id: str,
        provider_name: str,
        force: bool = False,
    ) -> list[ExtractionRunRecord]:
        case = db.get(CaseRecord, case_id)
        if case is None:
            raise ValueError(f"Case '{case_id}' not found.")

        documents = db.scalars(select(DocumentRecord).where(DocumentRecord.case_id == case_id)).all()
        provider = extraction_provider_registry.get(provider_name)
        runs: list[ExtractionRunRecord] = []

        for document in documents:
            if document.extraction_status == "completed" and not force:
                continue

            extraction_run = ExtractionRunRecord(
                case_id=case_id,
                document_id=document.id,
                provider_name=provider_name,
                status="running",
                started_at=datetime.now(UTC).replace(tzinfo=None),
            )
            db.add(extraction_run)
            db.flush()

            try:
                original_doc_type = DocumentType(document.doc_type)
                original_classification_confidence = document.classification_confidence
                context = DocumentExtractionContext(
                    document_id=document.id,
                    case_id=case_id,
                    source_filename=document.source_filename,
                    doc_type=original_doc_type,
                    absolute_path=local_storage_service.resolve(document.original_path),
                )
                result = provider.extract(context)
                normalized = extraction_normalizer.normalize(result)

                extraction_run.status = "completed"
                extraction_run.provider_name = result.provider_name
                extraction_run.provider_payload = jsonable_encoder(result.raw_payload)
                extraction_run.normalized_payload = jsonable_encoder(
                    normalized.model_dump(mode="json")
                    if hasattr(normalized, "model_dump")
                    else normalized
                )
                extraction_run.low_confidence_fields = jsonable_encoder(
                    [field.model_dump(mode="json") for field in result.low_confidence_fields]
                )
                extraction_run.completed_at = datetime.now(UTC).replace(tzinfo=None)

                if result.document_type == DocumentType.UNKNOWN and original_doc_type != DocumentType.UNKNOWN:
                    document.doc_type = original_doc_type.value
                    document.classification_confidence = original_classification_confidence
                else:
                    document.doc_type = result.document_type.value
                    document.classification_confidence = result.classification_confidence
                document.extraction_status = "completed"
                document.latest_provider = result.provider_name
                document.low_confidence_fields = extraction_run.low_confidence_fields
                document.latest_extraction_payload = extraction_run.normalized_payload

                self._persist_canonical(
                    db=db,
                    case_id=case_id,
                    document=document,
                    extraction_run=extraction_run,
                    normalized=normalized,
                )
                runs.append(extraction_run)
            except Exception as exc:
                extraction_run.status = "failed"
                extraction_run.error_message = str(exc)
                extraction_run.completed_at = datetime.now(UTC).replace(tzinfo=None)
                document.extraction_status = "failed"
                document.raw_metadata = {"error": str(exc)}
                runs.append(extraction_run)

        case.status = self._derive_case_status(case, documents)
        db.commit()
        for run in runs:
            db.refresh(run)
        return runs

    def _persist_canonical(
        self,
        *,
        db: Session,
        case_id: str,
        document: DocumentRecord,
        extraction_run: ExtractionRunRecord,
        normalized: CanonicalInvoice | DeliveryDocket | AccountingTemplateDefinition | dict,
    ) -> None:
        if isinstance(normalized, CanonicalInvoice):
            canonical_persistence_service.persist_invoice(
                db,
                case_id=case_id,
                document=document,
                extraction_run=extraction_run,
                invoice=normalized,
            )
            return
        if isinstance(normalized, DeliveryDocket):
            canonical_persistence_service.persist_delivery_docket(
                db,
                case_id=case_id,
                document=document,
                extraction_run=extraction_run,
                docket=normalized,
            )
            return
        if isinstance(normalized, AccountingTemplateDefinition):
            canonical_persistence_service.persist_template(document=document, template=normalized)

    def _derive_case_status(self, case: CaseRecord, documents: list[DocumentRecord]) -> str:
        if any(doc.extraction_status == "failed" for doc in documents):
            return "extraction_failed"
        if documents and all(doc.extraction_status == "completed" for doc in documents):
            return "extracted"
        return case.status


extraction_service = ExtractionService()
