from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base
from app.db.models import CaseRecord, DocumentRecord
from app.db.session import SessionLocal, engine
from app.services.export.service import export_service
from app.services.extraction.service import extraction_service
from app.services.ingestion.classifier import document_classifier
from app.services.reconciliation.service import reconciliation_service
from app.services.storage.local import local_storage_service


SAMPLE_FILES = [
    "Invoice_598527_Account_64876_Division_MRPI_Full_unlocked.pdf",
    "Delivery Docket.jpeg",
]


def seed() -> str:
    local_storage_service.ensure_directories()
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        case = CaseRecord(name="Seeded Musgrave sample", status="uploaded")
        db.add(case)
        db.flush()

        for filename in SAMPLE_FILES:
            source_path = settings.sample_source_root / filename
            if not source_path.exists():
                raise FileNotFoundError(f"Sample file not found: {source_path}")
            doc_type, confidence = document_classifier.classify(filename)
            stored = local_storage_service.register_existing_file(case.id, source_path, doc_type.value)
            db.add(
                DocumentRecord(
                    case_id=case.id,
                    doc_type=doc_type.value,
                    source_filename=filename,
                    original_path=stored.relative_path,
                    mime_type=stored.mime_type,
                    file_size_bytes=stored.file_size_bytes,
                    checksum_sha256=stored.checksum_sha256,
                    classification_confidence=confidence,
                    extraction_status="pending",
                    raw_metadata={"ingestion_mode": "seed_script"},
                )
            )

        db.commit()
        extraction_service.extract_case_documents(
            db, case_id=case.id, provider_name=settings.default_extraction_provider, force=True
        )
        reconciliation_service.run(db, case_id=case.id)
        export_service.create_export(db, case_id=case.id, export_format="reco_excel")
        export_service.create_export(db, case_id=case.id, export_format="ocr_html")
        export_service.create_export(db, case_id=case.id, export_format="pnl_csv")
        return case.id


if __name__ == "__main__":
    case_id = seed()
    print(f"Seeded sample case: {case_id}")
