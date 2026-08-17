from __future__ import annotations

import runpy
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings
from app.models import ScopedMediaAuthorization


BACKEND = Path(__file__).parents[1]
REVISION_0043 = "20260809_0043"
REVISION_0044 = "20260810_0044"
REVISION_0045 = "20260813_0045"
TABLE = "scopedmediaauthorization"
CURRENT_INDEX = "uq_scopedmediaauth_current_requirement"
REQUIREMENT_ONLY_INDEX = "uq_scopedmediaauth_current_requirement_only_asset"


STALE_INDEX_COLUMNS = {
    "ix_scopedmediaauthorization_website_id": "website_id",
    "ix_scopedmediaauthorization_site_plan_id": "site_plan_id",
    "ix_scopedmediaauthorization_planned_page_id": "planned_page_id",
    "ix_scopedmediaauthorization_generated_page_id": "generated_page_id",
    "ix_scopedmediaauthorization_media_requirement_id": "media_requirement_id",
    "ix_scopedmediaauthorization_placement_key": "placement_key",
    "ix_scopedmediaauthorization_image_metadata_id": "image_metadata_id",
    "ix_scopedmediaauthorization_page_image_assignment_id": (
        "page_image_assignment_id"
    ),
    "ix_scopedmediaauthorization_reuse_policy": "reuse_policy",
    "ix_scopedmediaauthorization_authorized_at": "authorized_at",
    "ix_scopedmediaauthorization_lifecycle_status": "lifecycle_status",
    "ix_scopedmediaauthorization_supersedes_authorization_id": (
        "supersedes_authorization_id"
    ),
}


def _config(monkeypatch: pytest.MonkeyPatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _recreate_model_table_with_ddl_change(
    engine,
    *,
    old: str,
    new: str,
) -> None:
    with engine.begin() as connection:
        ddl = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = :table"
            ),
            {"table": TABLE},
        ).scalar_one()
        assert ddl.count(old) == 1
        connection.execute(text(f"DROP TABLE {TABLE}"))
        connection.execute(text(ddl.replace(old, new, 1)))
    for index in sorted(
        ScopedMediaAuthorization.__table__.indexes,
        key=lambda candidate: candidate.name or "",
    ):
        index.create(bind=engine)


def _create_exact_stale_scaffold(engine) -> None:
    """Reproduce the exact empty 25-column task-local scaffold contract."""

    ddl = f"""
    CREATE TABLE {TABLE} (
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        id INTEGER NOT NULL,
        website_id INTEGER NOT NULL,
        site_plan_id INTEGER NOT NULL,
        planned_page_id INTEGER NOT NULL,
        generated_page_id INTEGER NOT NULL,
        media_requirement_id INTEGER NOT NULL,
        requirement_version INTEGER NOT NULL,
        placement_key VARCHAR(120) NOT NULL,
        placement_contract_version INTEGER NOT NULL,
        image_metadata_id INTEGER NOT NULL,
        media_version INTEGER NOT NULL,
        asset_checksum_sha256 VARCHAR(64) NOT NULL,
        approval_version INTEGER NOT NULL,
        page_image_assignment_id INTEGER NOT NULL,
        assignment_version INTEGER NOT NULL,
        reuse_policy VARCHAR(40) NOT NULL,
        authorized_by VARCHAR(160) NOT NULL,
        authorization_rationale VARCHAR NOT NULL,
        authorized_at DATETIME NOT NULL,
        authorization_version INTEGER NOT NULL,
        authorization_fingerprint VARCHAR(64) NOT NULL,
        lifecycle_status VARCHAR(24) NOT NULL,
        supersedes_authorization_id INTEGER,
        CONSTRAINT ck_scopedmediaauth_reuse_policy CHECK (
            reuse_policy IN (
                'contract_default','requirement_only','page_only',
                'website_limited','explicitly_reusable'
            )
        ),
        CONSTRAINT ck_scopedmediaauth_lifecycle CHECK (
            lifecycle_status IN ('current','superseded')
        ),
        CONSTRAINT ck_scopedmediaauth_versions CHECK (
            requirement_version >= 1
            AND placement_contract_version >= 1
            AND media_version >= 1
            AND approval_version >= 1
            AND assignment_version >= 1
            AND authorization_version >= 1
        ),
        CONSTRAINT ck_scopedmediaauth_required_text CHECK (
            length(trim(placement_key)) > 0
            AND length(trim(authorized_by)) > 0
            AND length(trim(authorization_rationale)) > 0
        ),
        CONSTRAINT ck_scopedmediaauth_fingerprints CHECK (
            length(asset_checksum_sha256) = 64
            AND asset_checksum_sha256 = lower(asset_checksum_sha256)
            AND length(authorization_fingerprint) = 64
            AND authorization_fingerprint = lower(authorization_fingerprint)
        ),
        CONSTRAINT ck_scopedmediaauth_lineage CHECK (
            (authorization_version = 1 AND supersedes_authorization_id IS NULL)
            OR (authorization_version > 1 AND supersedes_authorization_id IS NOT NULL)
        ),
        CONSTRAINT ck_scopedmediaauth_not_self CHECK (
            supersedes_authorization_id IS NULL
            OR supersedes_authorization_id != id
        ),
        CONSTRAINT fk_scopedmediaauth_website_id
            FOREIGN KEY (website_id) REFERENCES website (id),
        CONSTRAINT fk_scopedmediaauth_site_plan_id
            FOREIGN KEY (site_plan_id) REFERENCES siteplan (id),
        CONSTRAINT fk_scopedmediaauth_planned_page_id
            FOREIGN KEY (planned_page_id) REFERENCES plannedpage (id),
        CONSTRAINT fk_scopedmediaauth_generated_page_id
            FOREIGN KEY (generated_page_id) REFERENCES generatedpage (id),
        CONSTRAINT fk_scopedmediaauth_media_requirement_id
            FOREIGN KEY (media_requirement_id)
            REFERENCES plannedpagemediarequirement (id),
        CONSTRAINT fk_scopedmediaauth_image_metadata_id
            FOREIGN KEY (image_metadata_id) REFERENCES imagemetadata (id),
        CONSTRAINT fk_scopedmediaauth_assignment_id
            FOREIGN KEY (page_image_assignment_id) REFERENCES pageimageassignment (id),
        CONSTRAINT fk_scopedmediaauth_supersedes_id
            FOREIGN KEY (supersedes_authorization_id)
            REFERENCES scopedmediaauthorization (id),
        PRIMARY KEY (id),
        CONSTRAINT uq_scopedmediaauth_requirement_version UNIQUE (media_requirement_id, authorization_version),
        CONSTRAINT uq_scopedmediaauth_fingerprint UNIQUE (authorization_fingerprint)
    )
    """
    with engine.begin() as connection:
        connection.execute(text(ddl))
        for name, column in STALE_INDEX_COLUMNS.items():
            connection.execute(
                text(f"CREATE INDEX {name} ON {TABLE} ({column})")
            )
        connection.execute(
            text(
                f"CREATE UNIQUE INDEX {CURRENT_INDEX} ON {TABLE} "
                "(media_requirement_id) WHERE lifecycle_status = 'current'"
            )
        )


def _seed_legacy_image(engine) -> int:
    now = datetime(2026, 8, 10, 12, 0)
    with engine.begin() as connection:
        business_id = connection.execute(
            text(
                "INSERT INTO business "
                "(created_at, updated_at, company_name, business_type, state) "
                "VALUES (:now, :now, '0044 migration business', 'local', 'FL')"
            ),
            {"now": now},
        ).lastrowid
        image_id = connection.execute(
            text(
                "INSERT INTO imagemetadata "
                "(created_at, updated_at, business_id, file_name, exif_status) "
                "VALUES (:now, :now, :business_id, 'legacy.webp', 'pending')"
            ),
            {"now": now, "business_id": business_id},
        ).lastrowid
    assert isinstance(image_id, int)
    return image_id


def test_0044_canonicalizes_all_postgresql_trim_and_btrim_renderings() -> None:
    migration = runpy.run_path(
        str(
            BACKEND
            / "alembic"
            / "versions"
            / "20260810_0044_scoped_media_authorizations.py"
        )
    )
    normalize = migration["_normalized_check_sql"]
    canonical_trim = normalize("trim(BOTH FROM placement_key)")
    for rendered in (
        "trim(BOTH FROM (placement_key)::text)",
        "trim(BOTH FROM placement_key::text)",
        "btrim((placement_key)::text)",
        "btrim(placement_key::text)",
    ):
        assert normalize(rendered) == canonical_trim

    rendered_contract = (
        "length(btrim((placement_key)::text)) > 0 AND "
        "length(btrim((asset_approved_by)::text)) > 0 AND "
        "length(btrim((authorized_by)::text)) > 0 AND "
        "length(btrim((authorization_rationale)::text)) > 0"
    )
    assert migration["_check_contract_ast"](rendered_contract) == migration[
        "_check_contract_ast"
    ](migration["REQUIRED_TEXT_CHECK"])


def test_0044_clean_upgrade_backfills_asset_mode_and_creates_exact_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped-media-clean.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0043)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    image_id = _seed_legacy_image(engine)
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    columns = {item["name"]: item for item in inspector.get_columns(TABLE)}
    assert set(columns) == {
        "created_at",
        "updated_at",
        "id",
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "media_requirement_id",
        "requirement_version",
        "placement_key",
        "placement_contract_version",
        "image_metadata_id",
        "media_version",
        "asset_checksum_sha256",
        "approval_version",
        "asset_approved_by",
        "asset_approved_at",
        "approval_fingerprint",
        "page_image_assignment_id",
        "assignment_version",
        "reuse_policy",
        "authorization_terms",
        "authorized_by",
        "authorization_rationale",
        "authorized_at",
        "authorization_version",
        "authorization_fingerprint",
        "lifecycle_status",
        "supersedes_authorization_id",
    }
    assert columns["generated_page_id"]["nullable"] is True
    assert columns["page_image_assignment_id"]["nullable"] is True
    assert columns["assignment_version"]["nullable"] is True
    assert columns["authorization_terms"]["nullable"] is False
    assert {item["name"] for item in inspector.get_check_constraints(TABLE)} == {
        "ck_scopedmediaauth_reuse_policy",
        "ck_scopedmediaauth_lifecycle",
        "ck_scopedmediaauth_versions",
        "ck_scopedmediaauth_assignment_pair",
        "ck_scopedmediaauth_required_text",
        "ck_scopedmediaauth_fingerprints",
        "ck_scopedmediaauth_lineage",
        "ck_scopedmediaauth_not_self",
    }
    unique = {
        item["name"]: tuple(item["column_names"])
        for item in inspector.get_unique_constraints(TABLE)
    }
    assert unique == {
        "uq_scopedmediaauth_requirement_version": (
            "media_requirement_id",
            "authorization_version",
        ),
        "uq_scopedmediaauth_fingerprint": ("authorization_fingerprint",),
        "uq_scopedmediaauth_successor": ("supersedes_authorization_id",),
    }
    foreign_keys = inspector.get_foreign_keys(TABLE)
    assert len(foreign_keys) == 8
    assert all(not (item.get("options") or {}) for item in foreign_keys)
    indexes = {item["name"]: item for item in inspector.get_indexes(TABLE)}
    current = indexes[CURRENT_INDEX]
    assert bool(current["unique"]) is True
    assert tuple(current["column_names"]) == ("media_requirement_id",)
    assert str(current["dialect_options"]["sqlite_where"]) == (
        "lifecycle_status = 'current'"
    )
    requirement_only = indexes[REQUIREMENT_ONLY_INDEX]
    assert bool(requirement_only["unique"]) is True
    assert tuple(requirement_only["column_names"]) == ("image_metadata_id",)
    assert str(requirement_only["dialect_options"]["sqlite_where"]) == (
        "lifecycle_status = 'current' AND reuse_policy = 'requirement_only'"
    )
    image_columns = {
        item["name"]: item for item in inspector.get_columns("imagemetadata")
    }
    assert image_columns["usage_authorization_mode"]["nullable"] is False
    assert "contract_default" in str(
        image_columns["usage_authorization_mode"]["default"]
    )
    assert image_columns["required_authorization_terms"]["nullable"] is False
    assert "[]" in str(
        image_columns["required_authorization_terms"]["default"]
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260817_0047"
        assert connection.execute(
            text(
                "SELECT usage_authorization_mode, required_authorization_terms "
                "FROM imagemetadata WHERE id = :id"
            ),
            {"id": image_id},
        ).one() == ("contract_default", "[]")
    engine.dispose()
    get_settings.cache_clear()


def test_0044_adopts_only_the_exact_empty_model_created_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped-media-adoption.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0043)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    ScopedMediaAuthorization.__table__.create(engine)
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260817_0047"
        assert connection.execute(
            text(f"SELECT COUNT(*) FROM {TABLE}")
        ).scalar_one() == 0
    engine.dispose()
    get_settings.cache_clear()


def test_0044_upgrades_the_exact_empty_task_local_scaffold_in_place(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped-media-stale-scaffold.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0043)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    _create_exact_stale_scaffold(engine)
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    columns = {item["name"]: item for item in inspector.get_columns(TABLE)}
    assert len(columns) == 29
    assert columns["generated_page_id"]["nullable"] is True
    assert columns["page_image_assignment_id"]["nullable"] is True
    assert columns["assignment_version"]["nullable"] is True
    assert columns["asset_approved_by"]["nullable"] is False
    assert columns["asset_approved_at"]["nullable"] is False
    assert columns["approval_fingerprint"]["nullable"] is False
    assert columns["authorization_terms"]["nullable"] is False
    assert {item["name"] for item in inspector.get_check_constraints(TABLE)} == {
        "ck_scopedmediaauth_reuse_policy",
        "ck_scopedmediaauth_lifecycle",
        "ck_scopedmediaauth_versions",
        "ck_scopedmediaauth_assignment_pair",
        "ck_scopedmediaauth_required_text",
        "ck_scopedmediaauth_fingerprints",
        "ck_scopedmediaauth_lineage",
        "ck_scopedmediaauth_not_self",
    }
    assert {
        item["name"]: tuple(item["column_names"])
        for item in inspector.get_unique_constraints(TABLE)
    } == {
        "uq_scopedmediaauth_requirement_version": (
            "media_requirement_id",
            "authorization_version",
        ),
        "uq_scopedmediaauth_fingerprint": ("authorization_fingerprint",),
        "uq_scopedmediaauth_successor": ("supersedes_authorization_id",),
    }
    assert REQUIREMENT_ONLY_INDEX in {
        item["name"] for item in inspector.get_indexes(TABLE)
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260817_0047"
        assert connection.execute(
            text(f"SELECT COUNT(*) FROM {TABLE}")
        ).scalar_one() == 0
    engine.dispose()
    get_settings.cache_clear()


def test_0044_rejects_a_near_miss_empty_task_local_scaffold_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped-media-stale-near-miss.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0043)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    _create_exact_stale_scaffold(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE INDEX ix_scopedmediaauth_unexpected "
                f"ON {TABLE} (authorization_version)"
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="unexpected indexes"):
        command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0043
    assert "usage_authorization_mode" not in {
        item["name"] for item in inspector.get_columns("imagemetadata")
    }
    assert len(inspector.get_columns(TABLE)) == 25
    engine.dispose()
    get_settings.cache_clear()


def test_0044_rejects_a_populated_exact_task_local_scaffold_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped-media-stale-populated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0043)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    _create_exact_stale_scaffold(engine)
    now = datetime(2026, 8, 10, 13, 0)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {TABLE} ("
                "created_at, updated_at, id, website_id, site_plan_id, "
                "planned_page_id, generated_page_id, media_requirement_id, "
                "requirement_version, placement_key, placement_contract_version, "
                "image_metadata_id, media_version, asset_checksum_sha256, "
                "approval_version, page_image_assignment_id, assignment_version, "
                "reuse_policy, authorized_by, authorization_rationale, "
                "authorized_at, authorization_version, authorization_fingerprint, "
                "lifecycle_status, supersedes_authorization_id"
                ") VALUES ("
                ":now, :now, 1, 1, 1, 1, 1, 1, 1, 'hero', 1, 1, 1, :asset, "
                "1, 1, 1, 'contract_default', 'operator', 'known scaffold row', "
                ":now, 1, :authorization, 'current', NULL)"
            ),
            {"now": now, "asset": "a" * 64, "authorization": "b" * 64},
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="must be empty for adoption"):
        command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0043
        assert connection.execute(
            text(f"SELECT COUNT(*) FROM {TABLE}")
        ).scalar_one() == 1
    assert "usage_authorization_mode" not in {
        item["name"] for item in inspector.get_columns("imagemetadata")
    }
    assert len(inspector.get_columns(TABLE)) == 25
    engine.dispose()
    get_settings.cache_clear()


def test_0044_rejects_malformed_precreated_asset_required_terms_column(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped-media-malformed-required-terms.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0043)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE imagemetadata ADD COLUMN "
                "required_authorization_terms VARCHAR(20) "
                "DEFAULT '[]' NOT NULL"
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="required_authorization_terms.*incompatible"):
        command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0043
    engine.dispose()
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("old", "new", "error"),
    (
        (
            "generated_page_id INTEGER",
            "generated_page_id VARCHAR(20)",
            "generated_page_id column",
        ),
        (
            "generated_page_id INTEGER",
            "generated_page_id INTEGER NOT NULL",
            "generated_page_id column",
        ),
        (
            "requirement_version INTEGER NOT NULL",
            "requirement_version INTEGER DEFAULT 1 NOT NULL",
            "requirement_version column",
        ),
        (
            "assignment_version IS NOT NULL AND assignment_version >= 1",
            "assignment_version IS NOT NULL AND assignment_version >= 0",
            "malformed ck_scopedmediaauth_assignment_pair CHECK",
        ),
        (
            "FOREIGN KEY(generated_page_id) REFERENCES generatedpage (id)",
            (
                "FOREIGN KEY(generated_page_id) REFERENCES generatedpage (id) "
                "ON DELETE CASCADE"
            ),
            "incompatible foreign key contract",
        ),
        (
            (
                "CONSTRAINT uq_scopedmediaauth_successor "
                "UNIQUE (supersedes_authorization_id)"
            ),
            (
                "CONSTRAINT uq_scopedmediaauth_successor "
                "UNIQUE (authorization_version)"
            ),
            "incompatible unique contract",
        ),
    ),
)
def test_0044_rejects_same_named_or_shape_changed_adoption_contracts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    old: str,
    new: str,
    error: str,
) -> None:
    database = tmp_path / f"scoped-media-malformed-{abs(hash(new))}.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0043)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    ScopedMediaAuthorization.__table__.create(engine)
    _recreate_model_table_with_ddl_change(engine, old=old, new=new)
    engine.dispose()

    with pytest.raises(RuntimeError, match=error):
        command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0043
    engine.dispose()
    get_settings.cache_clear()


def test_0044_rejects_malformed_partial_current_index(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped-media-malformed-current.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0043)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    ScopedMediaAuthorization.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(text(f"DROP INDEX {CURRENT_INDEX}"))
        connection.execute(
            text(
                f"CREATE UNIQUE INDEX {CURRENT_INDEX} ON {TABLE} "
                "(media_requirement_id) WHERE lifecycle_status = 'superseded'"
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match=f"malformed {CURRENT_INDEX} index"):
        command.upgrade(config, "head")
    get_settings.cache_clear()


def test_0044_downgrade_is_reversible_only_for_default_asset_modes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "scoped-media-downgrade.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, REVISION_0043)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    image_id = _seed_legacy_image(engine)
    engine.dispose()
    command.upgrade(config, REVISION_0045)

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE imagemetadata SET usage_authorization_mode = "
                "'scoped_required', required_authorization_terms = "
                "'[\"no_reuse\",\"requirement_only_usage\"]' WHERE id = :id"
            ),
            {"id": image_id},
        )
    engine.dispose()
    with pytest.raises(RuntimeError, match="scoped-required Image Metadata"):
        command.downgrade(config, REVISION_0043)

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE imagemetadata SET usage_authorization_mode = "
                "'contract_default', required_authorization_terms = '[]' "
                "WHERE id = :id"
            ),
            {"id": image_id},
        )
    engine.dispose()
    command.downgrade(config, REVISION_0043)
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert TABLE not in inspector.get_table_names()
    assert "usage_authorization_mode" not in {
        item["name"] for item in inspector.get_columns("imagemetadata")
    }
    assert "required_authorization_terms" not in {
        item["name"] for item in inspector.get_columns("imagemetadata")
    }
    engine.dispose()
    get_settings.cache_clear()
