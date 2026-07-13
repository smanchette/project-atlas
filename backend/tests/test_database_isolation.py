from __future__ import annotations

import os
from pathlib import Path

from sqlmodel import create_engine
from sqlmodel import Session, select

from conftest import TEST_DB_PATH, TEST_ROOT, TEST_RUN_ID, remove_sqlite_database


def test_database_url_is_unique_temporary_and_not_development() -> None:
    database_url = os.environ["DATABASE_URL"]
    assert TEST_RUN_ID in database_url
    assert TEST_ROOT in TEST_DB_PATH.parents
    assert TEST_DB_PATH.name != "atlas.db"
    assert TEST_DB_PATH.name != "test_atlas.db"
    assert Path(database_url.removeprefix("sqlite:///")) == TEST_DB_PATH


def test_engine_disposal_allows_database_and_sidecar_cleanup(tmp_path: Path) -> None:
    database = tmp_path / "cleanup.sqlite3"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    for suffix in ("-wal", "-shm", "-journal"):
        Path(f"{database}{suffix}").touch()
    engine.dispose(close=True)
    remove_sqlite_database(database)
    assert not any(Path(f"{database}{suffix}").exists() for suffix in ("", "-wal", "-shm", "-journal"))


def test_suite_starts_without_prior_wordpress_draft_audits() -> None:
    from app.db.session import create_db_and_tables, engine
    from app.models import WordPressDraftAudit

    create_db_and_tables()
    with Session(engine) as session:
        assert session.exec(select(WordPressDraftAudit)).all() == []
