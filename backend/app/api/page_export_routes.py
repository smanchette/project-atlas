from datetime import datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.page_export import (
    BulkExportPreview,
    BulkExportRequest,
    PageExportPackage,
)
from app.services.page_export import (
    build_page_export_package,
    build_selected_packages,
    package_json,
    preview_bulk_export,
)

router = APIRouter(prefix="/generated-pages", tags=["page export"])


@router.post("/export/bulk-preview", response_model=BulkExportPreview)
def bulk_export_preview(
    payload: BulkExportRequest,
    session: Session = Depends(get_session),
) -> BulkExportPreview:
    return preview_bulk_export(session, payload.page_ids)


@router.post("/export/bulk")
def download_bulk_export(
    payload: BulkExportRequest,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    packages = build_selected_packages(session, payload.page_ids)
    content = BytesIO()
    used_names: set[str] = set()
    with ZipFile(content, mode="w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for package in packages:
            file_name = f"{package.url_slug}.json"
            if file_name in used_names:
                file_name = f"{package.url_slug}-page-{package.page_id}.json"
            used_names.add(file_name)
            archive.writestr(file_name, package_json(package))
    content.seek(0)
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d-%H%M%S")
    return StreamingResponse(
        content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="atlas-page-exports-{timestamp}.zip"'
        },
    )


@router.get("/{page_id}/export-package", response_model=PageExportPackage)
def read_export_package(
    page_id: int,
    session: Session = Depends(get_session),
) -> PageExportPackage:
    return build_page_export_package(session, page_id)


@router.get("/{page_id}/export-package/download")
def download_export_package(
    page_id: int,
    session: Session = Depends(get_session),
) -> Response:
    package = build_page_export_package(session, page_id)
    return Response(
        content=package_json(package),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="atlas-page-export-{package.url_slug}.json"'
            )
        },
    )
