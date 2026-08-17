from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import re

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
from sqlmodel import Session

from app.core.config import get_settings
from app.models import (
    Brand,
    Business,
    FormDeliveryAttempt,
    FormDeliveryConfigurationAudit,
    FormDeliveryOutbox,
    FormSubmissionEnvelope,
    Website,
    WebsiteFormDeliveryModeRevision,
    WebsiteFormRecipientRevision,
)


BACKEND = Path(__file__).parents[1]
FORM_DELIVERY_TABLES = {
    "websiteformdeliverymoderevision",
    "websiteformrecipientrevision",
    "formsubmissionenvelope",
    "formdeliveryoutbox",
    "formdeliveryattempt",
    "formdeliveryconfigurationaudit",
}
FORM_DELIVERY_MODELS = {
    "websiteformdeliverymoderevision": WebsiteFormDeliveryModeRevision,
    "websiteformrecipientrevision": WebsiteFormRecipientRevision,
    "formsubmissionenvelope": FormSubmissionEnvelope,
    "formdeliveryoutbox": FormDeliveryOutbox,
    "formdeliveryattempt": FormDeliveryAttempt,
    "formdeliveryconfigurationaudit": FormDeliveryConfigurationAudit,
}
INDEX_COLUMNS = {
    "websiteformdeliverymoderevision": (
        "website_id",
        "form_component_configuration_id",
        "form_instance_key",
        "supersedes_delivery_mode_revision_id",
        "lifecycle_status",
        "mode",
        "provider_key",
        "integrity_fingerprint",
    ),
    "websiteformrecipientrevision": (
        "delivery_mode_revision_id",
        "website_id",
        "form_component_configuration_id",
        "form_instance_key",
        "recipient_key",
        "supersedes_recipient_revision_id",
        "normalized_email",
        "recipient_role",
        "verification_status",
        "integrity_fingerprint",
    ),
    "formsubmissionenvelope": (
        "website_id",
        "form_component_configuration_id",
        "delivery_mode_revision_id",
        "idempotency_digest",
        "received_at",
        "destination_adapter_key",
        "expires_at",
        "integrity_fingerprint",
    ),
    "formdeliveryoutbox": (
        "envelope_id",
        "delivery_mode_revision_id",
        "adapter_key",
        "status",
        "next_attempt_at",
    ),
    "formdeliveryattempt": (
        "outbox_id",
        "outcome",
        "integrity_fingerprint",
    ),
    "formdeliveryconfigurationaudit": (
        "delivery_mode_revision_id",
        "recipient_revision_id",
        "action_type",
        "snapshot_hash",
        "created_at",
    ),
}


def _migration_module():
    path = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260817_0047_universal_form_delivery_modes.py"
    )
    spec = spec_from_file_location("atlas_migration_0047", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def _config(monkeypatch: pytest.MonkeyPatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_0047_is_one_linear_additive_revision_with_safe_identifiers() -> None:
    migration, path = _migration_module()
    assert migration.revision == "20260817_0047"
    assert migration.down_revision == "20260815_0046"
    assert set(migration.TABLES) == FORM_DELIVERY_TABLES
    source = path.read_text(encoding="utf-8")
    identifiers = {
        match[0] or match[1]
        for match in re.findall(
            r'(?:name\s*=\s*"([^"]+)"|op\.create_index\(\s*"([^"]+)")',
            source,
        )
    }
    assert identifiers
    assert all(len(identifier.encode("utf-8")) <= 63 for identifier in identifiers)
    generated = {
        migration._index_identifier(table, column)
        for table, columns in INDEX_COLUMNS.items()
        for column in columns
    }
    assert all(len(identifier.encode("utf-8")) <= 63 for identifier in generated)
    for table, model in FORM_DELIVERY_MODELS.items():
        expected = {
            migration._index_identifier(table, column)
            for column in INDEX_COLUMNS[table]
        }
        assert {index.name for index in model.__table__.indexes} == expected


def _form_schema_snapshot(engine) -> dict[str, dict[str, object]]:
    inspector = inspect(engine)
    result: dict[str, dict[str, object]] = {}
    for table in sorted(FORM_DELIVERY_TABLES):
        result[table] = {
            "columns": tuple(
                (
                    item["name"],
                    str(item["type"]),
                    bool(item["nullable"]),
                    bool(item.get("primary_key")),
                    item.get("default"),
                    item.get("identity"),
                    item.get("computed"),
                )
                for item in inspector.get_columns(table)
            ),
            "foreign_keys": tuple(
                sorted(
                    (
                        item["name"],
                        tuple(item["constrained_columns"]),
                        item["referred_table"],
                        tuple(item["referred_columns"]),
                        tuple(sorted((item.get("options") or {}).items())),
                    )
                    for item in inspector.get_foreign_keys(table)
                )
            ),
            "checks": tuple(
                sorted(
                    (item["name"], str(item.get("sqltext") or ""))
                    for item in inspector.get_check_constraints(table)
                )
            ),
            "uniques": tuple(
                sorted(item["name"] for item in inspector.get_unique_constraints(table))
            ),
            "indexes": tuple(
                sorted(
                    (
                        item["name"],
                        tuple(item["column_names"]),
                        bool(item["unique"]),
                        str(
                            (item.get("dialect_options") or {}).get("sqlite_where")
                            or ""
                        ),
                    )
                    for item in inspector.get_indexes(table)
                )
            ),
        }
    return result


def _assert_schema_matches_models(engine) -> None:
    migration, _ = _migration_module()
    with engine.connect() as connection:
        migration._assert_exact_owned_shape(connection)
    inspector = inspect(engine)
    for table, model in FORM_DELIVERY_MODELS.items():
        observed_columns = inspector.get_columns(table)
        assert tuple(item["name"] for item in observed_columns) == tuple(
            column.name for column in model.__table__.columns
        ) == migration._EXPECTED_COLUMNS[table]
        assert tuple(
            (
                str(item["type"]),
                bool(item["nullable"]),
                bool(item.get("primary_key")),
            )
            for item in observed_columns
        ) == tuple(
            (
                str(column.type),
                bool(column.nullable),
                bool(column.primary_key),
            )
            for column in model.__table__.columns
        )
        observed_fks = {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
                tuple(sorted((item.get("options") or {}).items())),
            )
            for item in inspector.get_foreign_keys(table)
        }
        expected_fks = {
            (
                tuple(column.name for column in constraint.columns),
                tuple(constraint.elements)[0].column.table.name,
                tuple(element.column.name for element in constraint.elements),
                (),
            )
            for constraint in model.__table__.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        }
        assert observed_fks == expected_fks
        model_fk_names = {
            (
                tuple(column.name for column in constraint.columns),
                tuple(constraint.elements)[0].column.table.name,
                tuple(element.column.name for element in constraint.elements),
            ): constraint.name
            for constraint in model.__table__.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        }
        assert model_fk_names == migration._EXPECTED_FOREIGN_KEY_NAMES[table]
        for item in inspector.get_foreign_keys(table):
            key = (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
            )
            if item.get("name") is not None:
                assert item["name"] == model_fk_names[key]
        expected_checks = {
            constraint.name: str(constraint.sqltext)
            for constraint in model.__table__.constraints
            if isinstance(constraint, CheckConstraint)
        }
        observed_checks = {
            item["name"]: str(item.get("sqltext") or "")
            for item in inspector.get_check_constraints(table)
        }
        assert set(observed_checks) == set(expected_checks)
        for name, expected_sql in expected_checks.items():
            text_columns = frozenset(migration._STRING_LENGTHS[table])
            boolean_columns = frozenset(migration._BOOLEAN_COLUMNS[table])
            assert migration._check_contract_ast(
                observed_checks[name],
                text_columns=text_columns,
                boolean_columns=boolean_columns,
            ) == migration._check_contract_ast(
                expected_sql,
                text_columns=text_columns,
                boolean_columns=boolean_columns,
            )
        expected_uniques = {
            constraint.name: tuple(column.name for column in constraint.columns)
            for constraint in model.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        assert {
            item["name"]: tuple(item["column_names"])
            for item in inspector.get_unique_constraints(table)
        } == expected_uniques
        observed_index_contracts = {
            item["name"]: (
                tuple(item.get("column_names") or ()),
                bool(item["unique"]),
                migration._normalized_index_predicate(
                    item,
                    text_columns=frozenset(migration._STRING_LENGTHS[table]),
                    boolean_columns=frozenset(migration._BOOLEAN_COLUMNS[table]),
                ),
                tuple(sorted((item.get("column_sorting") or {}).items())),
            )
            for item in inspector.get_indexes(table)
        }
        model_index_contracts = {
            index.name: (
                tuple(column.name for column in index.columns),
                bool(index.unique),
                None,
                (),
            )
            for index in model.__table__.indexes
        }
        assert observed_index_contracts == model_index_contracts


def test_0047_expression_contract_is_literal_cast_and_token_boundary_safe() -> None:
    migration, _ = _migration_module()
    text_columns = frozenset({"lifecycle_status"})
    canonical = migration._check_contract_ast(
        "lifecycle_status IN ('draft','active') AND revision >= 1",
        text_columns=text_columns,
    )
    assert canonical == migration._check_contract_ast(
        "(((lifecycle_status)::text = ANY ((ARRAY['draft'::character varying,"
        "'active'::character varying])::text[])) AND (revision >= 1))",
        text_columns=text_columns,
    )
    assert canonical == migration._check_contract_ast(
        "lifecycle_status::text = ANY (ARRAY['draft'::character varying, "
        "'active'::character varying]::text[]) AND revision >= 1",
        text_columns=text_columns,
    )
    expected_evidence = migration._check_contract_ast(
        "lifecycle_status NOT IN ('approved','active') OR "
        "(approval_identity IS NOT NULL AND approved_at IS NOT NULL)",
        text_columns=text_columns,
    )
    assert expected_evidence == migration._check_contract_ast(
        "(lifecycle_status::text <> ALL (ARRAY['approved'::character varying, "
        "'active'::character varying]::text[])) OR "
        "(approval_identity IS NOT NULL AND approved_at IS NOT NULL)",
        text_columns=text_columns,
    )
    for altered in (
        "lifecycle_status IN ('DRAFT','active') AND revision >= 1",
        '"lifecycle_status" IN (\'draft\',\'active\') AND revision >= 1',
        "lifecycle_status IN ('draft','active') AND revision::bigint >= 1",
        "lifecycle_status IN ('draft','active') AND revision::integer >= 1",
        "lifecycle_status IN ('draft','active') AND revisionisnull",
    ):
        assert migration._check_contract_ast(
            altered,
            text_columns=text_columns,
        ) != canonical
    assert migration._check_contract_ast(
        "'draft'",
        text_columns=text_columns,
    ) != migration._check_contract_ast(
        "__atlas_0047_literal_27647261667427__",
        text_columns=text_columns,
    )
    assert migration._check_contract_ast(
        "lifecycle_status IN ('draft')",
        text_columns=text_columns,
    ) != migration._check_contract_ast(
        "__atlas_0047_membership_lifecycle_status_in_27647261667427__",
        text_columns=text_columns,
    )
    assert migration._check_contract_ast(
        "a NOT IN ('x')",
        text_columns=frozenset({"a", "a_not"}),
    ) != migration._check_contract_ast(
        "a_not IN ('x')",
        text_columns=frozenset({"a", "a_not"}),
    )


def test_0047_creates_exact_tables_and_empty_downgrade_is_reversible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "universal-form-delivery.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260815_0046")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    before = set(inspect(engine).get_table_names())
    with Session(engine) as session:
        business = Business(
            company_name="Preserved Form Migration Company",
            business_type="test",
            state="FL",
        )
        session.add(business)
        session.flush()
        brand = Brand(
            business_id=business.id,
            brand_name="Preserved Form Migration Brand",
            status="active",
        )
        session.add(brand)
        session.flush()
        website = Website(
            business_id=business.id,
            brand_id=brand.id,
            website_name="Preserved Form Migration Website",
            domain="preserved-form-migration.example.test",
            public_url="https://preserved-form-migration.example.test",
            status="active",
        )
        session.add(website)
        session.commit()
        website_id = website.id
    engine.dispose()

    command.upgrade(config, "20260817_0047")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == before | FORM_DELIVERY_TABLES
    _assert_schema_matches_models(engine)
    first_0047_schema = _form_schema_snapshot(engine)
    envelope_columns = {item["name"] for item in inspector.get_columns("formsubmissionenvelope")}
    assert {
        "name",
        "phone",
        "postal_code",
        "requested_service",
        "message",
        "raw_body",
        "recipient_list",
        "payload",
    }.isdisjoint(envelope_columns)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260817_0047"
        assert connection.execute(
            text("SELECT website_name FROM website WHERE id = :id"),
            {"id": website_id},
        ).scalar_one() == "Preserved Form Migration Website"
        for table in FORM_DELIVERY_TABLES:
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
    engine.dispose()

    command.downgrade(config, "20260815_0046")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert set(inspect(engine).get_table_names()) == before
    engine.dispose()
    command.upgrade(config, "20260817_0047")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert FORM_DELIVERY_TABLES <= set(inspect(engine).get_table_names())
    assert _form_schema_snapshot(engine) == first_0047_schema
    engine.dispose()
    get_settings.cache_clear()


@pytest.mark.parametrize("precreated_table", sorted(FORM_DELIVERY_TABLES))
def test_0047_refuses_any_precreated_governed_table_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    precreated_table: str,
) -> None:
    database = tmp_path / f"universal-form-precreated-{precreated_table}.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260815_0046")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text(f"CREATE TABLE {precreated_table} (id INTEGER PRIMARY KEY)"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="refuses pre-created"):
        command.upgrade(config, "20260817_0047")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    tables = set(inspect(engine).get_table_names())
    assert tables.intersection(FORM_DELIVERY_TABLES) == {precreated_table}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260815_0046"
    engine.dispose()
    get_settings.cache_clear()


def test_0047_populated_downgrade_fails_before_any_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "universal-form-populated-downgrade.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260817_0047")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO websiteformdeliverymoderevision ("
                "created_at, updated_at, website_id, form_component_configuration_id, "
                "form_instance_key, revision, supersedes_delivery_mode_revision_id, "
                "lifecycle_status, mode, enabled, provider_key, adapter_version, "
                "destination_identity, configuration_payload, privacy_policy_reference, "
                "consent_policy_reference, retention_policy_reference, "
                "abuse_policy_reference, success_behavior, failure_behavior, "
                "idempotency_policy_reference, audit_identity, approval_identity, "
                "approved_at, activation_identity, activated_at, created_by, updated_by, "
                "integrity_fingerprint) VALUES (CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, "
                "999, 999, 'synthetic-form', 1, NULL, 'draft', 'disabled', 0, NULL, "
                "NULL, NULL, '{}', NULL, NULL, NULL, NULL, NULL, NULL, NULL, "
                "'synthetic-audit', NULL, NULL, NULL, NULL, 'test', 'test', :fingerprint)"
            ),
            {"fingerprint": "0" * 64},
        )
    before_schema = _form_schema_snapshot(engine)
    with engine.connect() as connection:
        before_counts = {
            table: connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in FORM_DELIVERY_TABLES
        }
    engine.dispose()

    with pytest.raises(RuntimeError, match="governed records exist"):
        command.downgrade(config, "20260815_0046")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert _form_schema_snapshot(engine) == before_schema
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260817_0047"
        assert {
            table: connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in FORM_DELIVERY_TABLES
        } == before_counts
    engine.dispose()
    get_settings.cache_clear()


def test_0047_downgrade_refuses_partial_owned_table_set_before_drop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "universal-form-partial-downgrade.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260817_0047")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE formdeliveryattempt"))
    before_tables = set(inspect(engine).get_table_names())
    engine.dispose()

    with pytest.raises(RuntimeError, match="partial or missing"):
        command.downgrade(config, "20260815_0046")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert set(inspect(engine).get_table_names()) == before_tables
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260817_0047"
    engine.dispose()
    get_settings.cache_clear()


def test_0047_downgrade_refuses_same_count_unknown_index_shape_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = tmp_path / "universal-form-mutated-shape.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260817_0047")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ix_fdo_status"))
        connection.execute(
            text("CREATE INDEX ix_fdo_status ON formdeliveryoutbox(adapter_key)")
        )
    with engine.connect() as connection:
        before_schema = tuple(
            connection.execute(
                text(
                    "SELECT type, name, tbl_name, sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
                )
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="does not match the exact 0047 contract"):
        command.downgrade(config, "20260815_0046")

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        after_schema = tuple(
            connection.execute(
                text(
                    "SELECT type, name, tbl_name, sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
                )
            )
        )
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "20260817_0047"
    assert after_schema == before_schema
    engine.dispose()
    get_settings.cache_clear()
