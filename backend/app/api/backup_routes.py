from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.db.backup import BackupValidationError, export_backup, list_backups
from app.db.session import get_session
from app.services.media_backup import MediaBackupError, create_media_backup

router = APIRouter(prefix="/backups", tags=["backups"])


@router.get("")
def get_backups() -> list[dict]:
    return list_backups()


@router.post("/export", status_code=201)
def create_backup(session: Session = Depends(get_session)) -> dict:
    try:
        return export_backup(session)
    except (BackupValidationError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/media")
def download_media_backup() -> StreamingResponse:
    try:
        backup = create_media_backup()
    except (MediaBackupError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return StreamingResponse(
        backup.content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{backup.file_name}"'},
    )
