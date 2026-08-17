from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from app.core.config import get_settings


def test_or_disposable_runtime_allowed() -> bool:
    """Recognize pytest or an explicit loopback/disposable Atlas runtime."""

    settings = get_settings()
    pytest_runtime = "PYTEST_CURRENT_TEST" in os.environ
    if not pytest_runtime and settings.atlas_runtime_mode not in {
        "automated_test",
        "activation_rehearsal",
    }:
        return False
    try:
        origin = urlsplit(str(settings.frontend_origin).strip())
        origin_is_loopback = bool(
            origin.scheme in {"http", "https"}
            and origin.hostname in {"localhost", "127.0.0.1", "::1"}
            and origin.username is None
            and origin.password is None
            and origin.path in {"", "/"}
            and not origin.query
            and not origin.fragment
        )
    except (TypeError, ValueError):
        origin_is_loopback = False
    normalized_database_url = settings.database_url.strip().lower().replace("\\", "/")
    try:
        database_path = urlsplit(normalized_database_url).path
    except (TypeError, ValueError):
        database_path = ""
    database_segments = {
        item for item in re.split(r"[^a-z0-9]+", database_path) if item
    }
    database_is_disposable = database_path.rstrip("/").endswith(":memory:") or bool(
        database_segments
        & {
            "test",
            "tests",
            "testing",
            "pytest",
            "rehearsal",
            "clone",
            "disposable",
        }
    )
    return origin_is_loopback and database_is_disposable


def session_uses_disposable_database(session: object) -> bool:
    """Bind-level containment: global test settings cannot bless an active DB."""

    try:
        bind = session.get_bind()  # type: ignore[attr-defined]
        database_name = str(getattr(bind.url, "database", "") or "").lower()
        exact_sqlite_memory = (
            getattr(bind.dialect, "name", "") == "sqlite"
            and database_name in {"", ":memory:"}
            and str(bind.url) in {"sqlite://", "sqlite:///:memory:"}
        )
    except Exception:
        return False
    segments = {
        item for item in re.split(r"[^a-z0-9]+", database_name) if item
    }
    return database_name != "atlas" and bool(
        exact_sqlite_memory
        or segments
        & {
            "test",
            "tests",
            "testing",
            "pytest",
            "rehearsal",
            "clone",
            "disposable",
        }
    )
