from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
BACKEND_MEDIA_DIR = BACKEND_ROOT / "media"
FRONTEND_MEDIA_DIR = PROJECT_ROOT / "frontend" / "public" / "media"


class MediaBackupError(RuntimeError):
    pass


@dataclass
class MediaBackupArchive:
    content: BytesIO
    file_name: str


def create_media_backup(*, timestamp: datetime | None = None) -> MediaBackupArchive:
    sources = (
        (BACKEND_MEDIA_DIR, PurePosixPath("backend/media")),
        (FRONTEND_MEDIA_DIR, PurePosixPath("frontend/public/media")),
    )
    missing = [str(source) for source, _ in sources if not source.is_dir()]
    if missing:
        raise MediaBackupError(f"Media backup requires both media folders. Missing: {', '.join(missing)}")

    content = BytesIO()
    with ZipFile(content, mode="w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for source, archive_root in sources:
            _add_media_tree(archive, source, archive_root)

    content.seek(0)
    created_at = timestamp or datetime.now().astimezone()
    return MediaBackupArchive(
        content=content,
        file_name=f"atlas-media-backup-{created_at.strftime('%Y-%m-%d-%H%M%S')}.zip",
    )


def _add_media_tree(archive: ZipFile, source: Path, archive_root: PurePosixPath) -> None:
    _write_directory_entry(archive, archive_root)
    for item in sorted(source.rglob("*"), key=lambda path: path.as_posix().lower()):
        if item.is_symlink():
            raise MediaBackupError(f"Media backup cannot include symbolic links: {item}")

        relative = item.relative_to(source)
        archive_path = PurePosixPath(archive_root, *relative.parts)
        if item.is_dir():
            _write_directory_entry(archive, archive_path)
        elif item.is_file():
            archive.write(item, arcname=archive_path.as_posix())


def _write_directory_entry(archive: ZipFile, archive_path: PurePosixPath) -> None:
    entry = ZipInfo(f"{archive_path.as_posix().rstrip('/')}/")
    entry.external_attr = 0o40775 << 16
    archive.writestr(entry, b"")
