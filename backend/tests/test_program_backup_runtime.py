from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.services import program_backup
from app.services.wordpress_deployment_release import DeploymentReleaseError, resolve_program_root


def project(root: Path) -> Path:
    included = {
        "backend/app/main.py": "print('atlas')\n",
        "backend/alembic/env.py": "# migrations\n",
        "backend/tests/test_app.py": "def test_placeholder(): pass\n",
        "backend/scripts/generate.py": "print('generate')\n",
        "backend/Dockerfile": "FROM python:3.12\n",
        "backend/.dockerignore": "__pycache__\n",
        "backend/alembic.ini": "[alembic]\n",
        "backend/requirements.txt": "fastapi\n",
        "frontend/src/main.tsx": "export {};\n",
        "frontend/public/robots.txt": "User-agent: *\n",
        "frontend/Dockerfile": "FROM node:20\n",
        "frontend/package.json": '{"name":"atlas"}\n',
        "frontend/package-lock.json": '{"name":"atlas"}\n',
        "frontend/index.html": "<div id=\"root\"></div>\n",
        "frontend/tsconfig.json": "{}\n",
        "frontend/vite.config.ts": "export default {};\n",
        "docker-compose.yml": "services: {}\n",
        "README.md": "# Atlas\n",
    }
    excluded = {
        ".git/config": "git metadata\n",
        ".runtime/atlas-release.json": "runtime identity\n",
        ".env": "LOCAL=value\n",
        "backend/.env": "DATABASE_URL=private\n",
        "backend/backups/atlas-backup-old.json": "backup\n",
        "backend/media/originals/image.jpg": "protected media\n",
        "backend/app/cache.sqlite": "database\n",
        "backend/app/cache.sqlite-wal": "sidecar\n",
        "backend/app/cache.sqlite-shm": "sidecar\n",
        "backend/app/cache.sqlite-journal": "sidecar\n",
        "backend/app/__pycache__/main.pyc": "cache\n",
        "backend/tests/.pytest_cache/state": "cache\n",
        "backend/tests/atlas-program-backup-old.zip": "recursive archive\n",
        "frontend/node_modules/pkg/index.js": "dependency\n",
        "frontend/dist/index.html": "generated\n",
        "frontend/public/media/hero.png": "protected media\n",
        ".local-wp-integration/compose.yaml": "temporary wordpress\n",
        "wordpress-volumes/database/data": "temporary wordpress\n",
    }
    for relative, content in {**included, **excluded}.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def snapshot(root: Path) -> dict[str, tuple[int, str]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in root.rglob("*") if path.is_file()
    }


def test_program_backup_is_nonempty_portable_and_read_only(monkeypatch, tmp_path):
    root = project(tmp_path / "project")
    before = snapshot(root)
    monkeypatch.setattr(program_backup, "resolve_program_root", lambda: root)
    archive = program_backup.create_program_backup(timestamp=datetime(2026, 7, 13, 19, 1, 2, tzinfo=timezone.utc))
    assert archive.file_name == "atlas-program-backup-2026-07-13-190102.zip"
    assert len(archive.content.getvalue()) > 0
    with ZipFile(BytesIO(archive.content.getvalue())) as opened:
        names = set(opened.namelist())
        assert opened.testzip() is None
    expected = {
        "backend/app/main.py", "backend/alembic/env.py", "backend/tests/test_app.py",
        "backend/scripts/generate.py", "backend/Dockerfile", "backend/.dockerignore",
        "backend/requirements.txt", "frontend/src/main.tsx", "frontend/public/robots.txt",
        "frontend/package.json", "frontend/package-lock.json", "docker-compose.yml", "README.md",
    }
    assert expected <= names
    forbidden = (".git/", ".runtime/", "backups/", "media/", "node_modules/", "dist/", "__pycache__/", ".pytest_cache/", ".local-wp-integration/", "wordpress-volumes/")
    assert not any(fragment in name for name in names for fragment in forbidden)
    assert not any(Path(name).name.lower() == ".env" or Path(name).name.lower().startswith(".env.") for name in names)
    assert not any(Path(name).name.lower().endswith(("-wal", "-shm", "-journal")) for name in names)
    assert snapshot(root) == before


def test_program_backup_fails_safely_when_root_is_missing(monkeypatch):
    monkeypatch.setattr(program_backup, "resolve_program_root", lambda: (_ for _ in ()).throw(DeploymentReleaseError("missing mount")))
    with pytest.raises(program_backup.ProgramBackupError, match="program root is unavailable"):
        program_backup.create_program_backup()


def test_program_root_rejects_filesystem_root_and_unapproved_layout(tmp_path):
    with pytest.raises(DeploymentReleaseError):
        resolve_program_root({"ATLAS_PROGRAM_ROOT": "/"}, container_root="/__missing__")
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(DeploymentReleaseError):
        resolve_program_root({"ATLAS_PROGRAM_ROOT": str(outside)}, container_root="/__missing__")


def test_program_backup_rejects_secret_material(monkeypatch, tmp_path):
    root = project(tmp_path / "project")
    marker = b"-----BEGIN " + b"PRIVATE KEY-----"
    (root / "backend/app/settings.txt").write_bytes(marker)
    monkeypatch.setattr(program_backup, "resolve_program_root", lambda: root)
    with pytest.raises(program_backup.ProgramBackupError, match="possible secret material"):
        program_backup.create_program_backup()


def test_compose_program_source_mounts_are_granular_and_read_only():
    compose = (Path(__file__).parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./:/atlas-program" not in compose and ".git:/atlas-program" not in compose
    required = (
        "./wordpress:/atlas-program/wordpress:ro",
        "./backend/app:/atlas-program/backend/app:ro",
        "./backend/alembic:/atlas-program/backend/alembic:ro",
        "./backend/tests:/atlas-program/backend/tests:ro",
        "./backend/scripts:/atlas-program/backend/scripts:ro",
        "./frontend/src:/atlas-program/frontend/src:ro",
        "./docker-compose.yml:/atlas-program/docker-compose.yml:ro",
        "./README.md:/atlas-program/README.md:ro",
    )
    assert all(item in compose for item in required)
    assert "/atlas-program/backend/backups" not in compose
    assert "/atlas-program/backend/media" not in compose
    assert "/atlas-program/frontend/public/media" not in compose
