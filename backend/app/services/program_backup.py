from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.wordpress_deployment_release import DeploymentReleaseError, resolve_program_root

INCLUDED_DIRECTORIES = (
    "backend/app",
    "backend/alembic",
    "backend/tests",
    "backend/scripts",
    "frontend/src",
    "frontend/public",
)

INCLUDED_FILES = (
    "backend/Dockerfile",
    "backend/.dockerignore",
    "backend/alembic.ini",
    "backend/requirements.txt",
    "backend/pyproject.toml",
    "frontend/Dockerfile",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/index.html",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
    "docker-compose.yml",
    "README.md",
)

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".runtime",
    ".local-wp-integration",
    ".wordpress-integration",
    ".pytest_cache",
    "__pycache__",
    "backups",
    "dist",
    "media",
    "node_modules",
    "wordpress-volumes",
}

EXCLUDED_SUFFIXES = {
    ".bak",
    ".db",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".db-journal",
    ".db-shm",
    ".db-wal",
    ".sqlite-journal",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3-journal",
    ".sqlite3-shm",
    ".sqlite3-wal",
    ".swp",
    ".temp",
    ".tmp",
}
SECRET_MATERIAL_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"sk-[A-Za-z0-9]{20,}"),
    re.compile(rb"Bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
)


class ProgramBackupError(RuntimeError):
    pass


@dataclass
class ProgramBackupArchive:
    content: BytesIO
    file_name: str


def create_program_backup(*, timestamp: datetime | None = None) -> ProgramBackupArchive:
    try:
        project_root = resolve_program_root()
    except DeploymentReleaseError as exc:
        raise ProgramBackupError(f"Atlas program root is unavailable: {exc}") from exc
    files = _collect_program_files(project_root)
    if not files:
        raise ProgramBackupError("No Atlas program files were found for backup.")

    content = BytesIO()
    with ZipFile(content, mode="w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for source in files:
            archive.write(
                source,
                arcname=PurePosixPath(*source.relative_to(project_root).parts).as_posix(),
            )

    content.seek(0)
    created_at = timestamp or datetime.now().astimezone()
    return ProgramBackupArchive(
        content=content,
        file_name=f"atlas-program-backup-{created_at.strftime('%Y-%m-%d-%H%M%S')}.zip",
    )


def _collect_program_files(project_root: Path) -> list[Path]:
    collected: set[Path] = set()
    for relative_directory in INCLUDED_DIRECTORIES:
        source = project_root / relative_directory
        if not source.exists():
            continue
        if not source.is_dir():
            raise ProgramBackupError(f"Program backup source is not a directory: {source}")
        for item in source.rglob("*"):
            if item.is_symlink():
                raise ProgramBackupError(f"Program backup cannot include symbolic links: {item}")
            if item.is_file() and not _is_excluded(item.relative_to(project_root)):
                _reject_secret_material(item, project_root)
                collected.add(item.resolve())

    for relative_file in INCLUDED_FILES:
        source = project_root / relative_file
        if source.is_symlink():
            raise ProgramBackupError(f"Program backup cannot include symbolic links: {source}")
        if source.is_file() and not _is_excluded(source.relative_to(project_root)):
            _reject_secret_material(source, project_root)
            collected.add(source.resolve())

    return sorted(
        collected,
        key=lambda path: path.relative_to(project_root).as_posix().lower(),
    )


def _is_excluded(relative_path: Path) -> bool:
    lowered_parts = [part.lower() for part in relative_path.parts]
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in lowered_parts[:-1]):
        return True

    name = relative_path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    if (
        "secret" in name
        or "private_key" in name
        or name in {"id_ed25519", "id_rsa"}
        or name.startswith("atlas-backup-")
        or name.startswith("atlas-media-backup-")
        or name.startswith("atlas-program-backup-")
        or name.startswith("~")
    ):
        return True
    return relative_path.suffix.lower() in EXCLUDED_SUFFIXES or name.endswith(("-journal", "-shm", "-wal"))


def _reject_secret_material(source: Path, project_root: Path) -> None:
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise ProgramBackupError(f"Program backup could not safely inspect {source.relative_to(project_root)}.") from exc
    if any(pattern.search(content) for pattern in SECRET_MATERIAL_PATTERNS):
        raise ProgramBackupError(f"Program backup rejected possible secret material in {source.relative_to(project_root)}.")
