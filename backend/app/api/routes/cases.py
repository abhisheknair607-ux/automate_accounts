from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    CaseRecord,
    DeliveryDocketRecord,
    DocumentRecord,
    ExportRecord,
    InvoiceRecord,
    ReconciliationIssueRecord,
    ReconciliationRunRecord,
)
from app.db.session import get_db
from app.schemas.api import (
    CaseDetailResponse,
    CaseSummaryResponse,
    DocumentResponse,
    ExtractedDocumentResponse,
    ExtractionBatchResponse,
    ExtractionRequest,
    ReconciliationRequest,
    ReconciliationResponse,
)
from app.schemas.canonical import FieldConfidence
from app.services.extraction.service import extraction_service
from app.services.ingestion.classifier import document_classifier
from app.services.reconciliation.service import reconciliation_service
from app.services.storage.local import local_storage_service


router = APIRouter()


@router.get("", response_model=list[CaseSummaryResponse])
def list_cases(db: Session = Depends(get_db)) -> list[CaseSummaryResponse]:
    cases = db.scalars(select(CaseRecord).order_by(CaseRecord.created_at.desc())).all()
    response: list[CaseSummaryResponse] = []
    for case in cases:
        open_issue_count = db.scalar(
            select(func.count(ReconciliationIssueRecord.id))
            .join(
                ReconciliationRunRecord,
                ReconciliationIssueRecord.reconciliation_run_id == ReconciliationRunRecord.id,
            )
            .where(ReconciliationRunRecord.case_id == case.id, ReconciliationIssueRecord.status == "open")
        )
        latest_reconciliation = db.scalar(
            select(ReconciliationRunRecord)
            .where(ReconciliationRunRecord.case_id == case.id)
            .order_by(ReconciliationRunRecord.created_at.desc())
        )
        response.append(
            CaseSummaryResponse(
                **jsonable_encoder(case),
                document_count=len(case.documents),
                open_issue_count=open_issue_count or 0,
                latest_reconciliation_status=latest_reconciliation.status if latest_reconciliation else None,
            )
        )
    return response


@router.post("/uploads", response_model=CaseDetailResponse)
async def upload_case_documents(
    invoice: UploadFile | None = File(None),
    delivery_docket: UploadFile | None = File(None),
    template: UploadFile | None = File(None),
    db: Session = Depends(get_db),
) -> CaseDetailResponse:
    if invoice is None or delivery_docket is None:
        raise HTTPException(
            status_code=400,
            detail="Invoice and delivery docket are required. The P&L template is already bundled in the backend.",
        )

    case = CaseRecord(name="Retail invoice reconciliation", status="uploaded")
    db.add(case)
    db.flush()

    uploads = [
        (invoice, "invoice"),
        (delivery_docket, "delivery_docket"),
        (template, "accounting_template"),
    ]
    for upload, default_type in uploads:
        if upload is None:
            continue
        doc_type, confidence = document_classifier.classify(upload.filename or default_type, upload.content_type)
        stored = await local_storage_service.save_upload(case.id, upload, doc_type.value)
        db.add(
            DocumentRecord(
                case_id=case.id,
                doc_type=doc_type.value,
                source_filename=upload.filename or default_type,
                original_path=stored.relative_path,
                mime_type=upload.content_type or stored.mime_type,
                file_size_bytes=stored.file_size_bytes,
                checksum_sha256=stored.checksum_sha256,
                classification_confidence=confidence,
                extraction_status="pending",
                raw_metadata={"ingestion_mode": "upload"},
            )
        )

    db.commit()
    return _build_case_detail(db, case.id)


@router.post("/{case_id}/extract", response_model=ExtractionBatchResponse)
def extract_case_documents(
    case_id: str,
    request: ExtractionRequest,
    db: Session = Depends(get_db),
) -> ExtractionBatchResponse:
    try:
        runs = extraction_service.extract_case_documents(
            db,
            case_id=case_id,
            provider_name=request.provider_name,
            force=request.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ExtractionBatchResponse(case_id=case_id, provider_name=request.provider_name, runs=runs)


@router.post("/{case_id}/reconcile", response_model=ReconciliationResponse)
def reconcile_case(
    case_id: str,
    request: ReconciliationRequest,
    db: Session = Depends(get_db),
) -> ReconciliationResponse:
    try:
        run = reconciliation_service.run(db, case_id=case_id, config=request.config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    issues = db.scalars(
        select(ReconciliationIssueRecord).where(ReconciliationIssueRecord.reconciliation_run_id == run.id)
    ).all()
    return ReconciliationResponse(**jsonable_encoder(run), issues=issues)


@router.get("/{case_id}", response_model=CaseDetailResponse)
def get_case(case_id: str, db: Session = Depends(get_db)) -> CaseDetailResponse:
    return _build_case_detail(db, case_id)


@router.get("/{case_id}/invoice", response_model=ExtractedDocumentResponse)
def get_invoice(case_id: str, db: Session = Depends(get_db)) -> ExtractedDocumentResponse:
    document = db.scalar(
        select(DocumentRecord)
        .where(DocumentRecord.case_id == case_id, DocumentRecord.doc_type == "invoice")
        .order_by(DocumentRecord.created_at.desc())
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Invoice document not found.")
    return ExtractedDocumentResponse(
        document=document,
        payload=document.latest_extraction_payload,
        low_confidence_fields=[FieldConfidence.model_validate(item) for item in document.low_confidence_fields or []],
    )


@router.get("/{case_id}/delivery-docket", response_model=ExtractedDocumentResponse)
def get_delivery_docket(case_id: str, db: Session = Depends(get_db)) -> ExtractedDocumentResponse:
    document = db.scalar(
        select(DocumentRecord)
        .where(DocumentRecord.case_id == case_id, DocumentRecord.doc_type == "delivery_docket")
        .order_by(DocumentRecord.created_at.desc())
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Delivery docket document not found.")
    return ExtractedDocumentResponse(
        document=document,
        payload=document.latest_extraction_payload,
        low_confidence_fields=[FieldConfidence.model_validate(item) for item in document.low_confidence_fields or []],
    )


@router.get("/{case_id}/reconciliation", response_model=ReconciliationResponse)
def get_reconciliation(case_id: str, db: Session = Depends(get_db)) -> ReconciliationResponse:
    run = db.scalar(
        select(ReconciliationRunRecord)
        .where(ReconciliationRunRecord.case_id == case_id)
        .order_by(ReconciliationRunRecord.created_at.desc())
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation has not been run.")
    issues = db.scalars(
        select(ReconciliationIssueRecord).where(ReconciliationIssueRecord.reconciliation_run_id == run.id)
    ).all()
    return ReconciliationResponse(**jsonable_encoder(run), issues=issues)


@router.get("/{case_id}/exceptions")
def get_exception_case(case_id: str, db: Session = Depends(get_db)) -> dict:
    run = db.scalar(
        select(ReconciliationRunRecord)
        .where(ReconciliationRunRecord.case_id == case_id)
        .order_by(ReconciliationRunRecord.created_at.desc())
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Reconciliation has not been run.")
    issues = db.scalars(
        select(ReconciliationIssueRecord).where(ReconciliationIssueRecord.reconciliation_run_id == run.id)
    ).all()
    payload = reconciliation_service.build_exception_case(run)
    return {"payload": payload.model_dump(mode="json"), "issues": [jsonable_encoder(issue) for issue in issues]}


@router.get("/{case_id}/exports")
def list_case_exports(case_id: str, db: Session = Depends(get_db)) -> list[dict]:
    exports = db.scalars(
        select(ExportRecord).where(ExportRecord.case_id == case_id).order_by(ExportRecord.created_at.desc())
    ).all()
    return [jsonable_encoder(item) for item in exports]


def _build_case_detail(db: Session, case_id: str) -> CaseDetailResponse:
    case = db.get(CaseRecord, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")

    invoice = db.scalar(
        select(InvoiceRecord).where(InvoiceRecord.case_id == case_id).order_by(InvoiceRecord.created_at.desc())
    )
    docket = db.scalar(
        select(DeliveryDocketRecord)
        .where(DeliveryDocketRecord.case_id == case_id)
        .order_by(DeliveryDocketRecord.created_at.desc())
    )
    reconciliation = db.scalar(
        select(ReconciliationRunRecord)
        .where(ReconciliationRunRecord.case_id == case_id)
        .order_by(ReconciliationRunRecord.created_at.desc())
    )
    exports = db.scalars(
        select(ExportRecord).where(ExportRecord.case_id == case_id).order_by(ExportRecord.created_at.desc())
    ).all()
    open_issue_count = db.scalar(
        select(func.count(ReconciliationIssueRecord.id))
        .join(
            ReconciliationRunRecord,
            ReconciliationIssueRecord.reconciliation_run_id == ReconciliationRunRecord.id,
        )
        .where(ReconciliationRunRecord.case_id == case_id, ReconciliationIssueRecord.status == "open")
    )
    latest_exception_case = (
        reconciliation_service.build_exception_case(reconciliation).model_dump(mode="json")
        if reconciliation
        else None
    )

    return CaseDetailResponse(
        **jsonable_encoder(case),
        document_count=len(case.documents),
        open_issue_count=open_issue_count or 0,
        latest_reconciliation_status=reconciliation.status if reconciliation else None,
        documents=[DocumentResponse.model_validate(document) for document in case.documents],
        invoice=invoice.canonical_payload if invoice else None,
        delivery_docket=docket.canonical_payload if docket else None,
        latest_reconciliation=reconciliation.result_payload if reconciliation else None,
        latest_exception_case=latest_exception_case,
        exports=[jsonable_encoder(export_record) for export_record in exports],
    )
