from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.models import ExportRecord
from app.db.session import get_db
from app.schemas.api import ExportRequest, ExportResponse
from app.services.export.service import export_service
from app.services.storage.local import local_storage_service


router = APIRouter()


@router.post("/cases/{case_id}", response_model=ExportResponse)
def create_export(case_id: str, request: ExportRequest, db: Session = Depends(get_db)) -> ExportResponse:
    try:
        export_record = export_service.create_export(db, case_id=case_id, export_format=request.export_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return export_record


@router.get("/{export_id}/download")
def download_export(export_id: str, db: Session = Depends(get_db)) -> FileResponse:
    export_record = db.get(ExportRecord, export_id)
    if export_record is None:
        raise HTTPException(status_code=404, detail="Export not found.")
    output_path = local_storage_service.resolve(export_record.output_path)
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Export file is missing on disk.")
    return FileResponse(
        Path(output_path),
        media_type=export_record.content_type,
        filename=Path(output_path).name,
    )
