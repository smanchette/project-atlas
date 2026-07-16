from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import uuid

import pytest
from sqlalchemy import delete, inspect


TEST_RUN_ID = uuid.uuid4().hex
TEST_ROOT = Path(tempfile.mkdtemp(prefix=f"project-atlas-pytest-{TEST_RUN_ID}-"))
TEST_DB_PATH = TEST_ROOT / f"atlas-{TEST_RUN_ID}.sqlite3"
TEST_MEDIA_PATH = TEST_ROOT / "media"

# Set these before any application module is imported during collection.
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["MEDIA_ROOT"] = str(TEST_MEDIA_PATH)
os.environ["MEDIA_PUBLIC_URL"] = "http://testserver/media"


def remove_sqlite_database(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"), Path(f"{path}-journal")):
        candidate.unlink(missing_ok=True)


@pytest.fixture(scope="session", autouse=True)
def isolated_test_run() -> None:
    yield
    from app.db.session import engine

    engine.dispose(close=True)
    remove_sqlite_database(TEST_DB_PATH)
    shutil.rmtree(TEST_ROOT, ignore_errors=False)


@pytest.fixture(autouse=True)
def isolate_wordpress_audit_state() -> None:
    from sqlmodel import Session, select
    from app.db.session import engine
    from app.models import (
        WordPressDraftAudit, WordPressMediaSyncAudit, WordPressMetadataState,
        WordPressMetadataSyncAudit, WordPressPublishAudit, WordPressDeploymentAudit,
        WordPressDeploymentNonce, WordPressDeploymentTransition,
        WordPressHeadingCorrectionAudit,
        WordPressActivationAudit,
        WordPressPluginUpgradeAudit,
        WordPressBootstrapCleanupAudit,
        WordPressMetadataLifecycleAudit,
    )

    models = (
        WordPressMetadataLifecycleAudit, WordPressBootstrapCleanupAudit, WordPressPluginUpgradeAudit, WordPressDeploymentTransition, WordPressDeploymentNonce, WordPressDeploymentAudit,
        WordPressPublishAudit, WordPressMetadataSyncAudit, WordPressMetadataState,
        WordPressMediaSyncAudit, WordPressDraftAudit, WordPressHeadingCorrectionAudit,
        WordPressActivationAudit,
    )
    available = set(inspect(engine).get_table_names())
    with Session(engine) as session:
        for model in models:
            if model.__tablename__ in available:
                assert session.exec(select(model)).first() is None, f"Unexpected leaked {model.__name__} row at test start"
    yield
    available = set(inspect(engine).get_table_names())
    with Session(engine) as session:
        for model in models:
            if model.__tablename__ in available:
                session.exec(delete(model))
        session.commit()
