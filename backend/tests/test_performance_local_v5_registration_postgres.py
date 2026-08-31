from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlmodel import Session, select

from app.models import (
    Theme,
    ThemeConfigurationAudit,
    ThemeFamilyVersion,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
    WebsiteThemeSelection,
)
from app.services import theme_configurations as theme_service
from app.services.performance_local_v5_registration import (
    PERFORMANCE_LOCAL_V5_FAMILY_VERSION,
    PERFORMANCE_LOCAL_V5_THEME_KEY,
    PerformanceLocalV5RegistrationError,
    apply_performance_local_v5_registration,
    plan_performance_local_v5_registration,
)
from tests.test_performance_local_v5_payload_registration import (
    _seed_v3_graph,
    _v5_audit_natural_identities,
)


POSTGRES_ADMIN_URL_ENV = "ATLAS_DISPOSABLE_POSTGRES_ADMIN_URL"
POSTGRES_EXPECTED_HOST_ENV = "ATLAS_V5_REGISTRATION_POSTGRES_HOST"
DISPOSABLE_DATABASE_PREFIX = "atlas_v5_registration_test_"
LOCAL_POSTGRES_HOSTS = {"127.0.0.1", "localhost", "postgres"}
SEQUENCES = (
    "themefamilyversion_id_seq",
    "websitethemeconfiguration_id_seq",
    "websitethemecomponentconfiguration_id_seq",
    "themeconfigurationaudit_id_seq",
    "theme_id_seq",
    "websitethemeselection_id_seq",
)
INSERT_MODELS = (
    ThemeFamilyVersion,
    WebsiteThemeConfiguration,
    WebsiteThemeComponentConfiguration,
    ThemeConfigurationAudit,
    Theme,
    WebsiteThemeSelection,
)
TARGET_TABLES = {model.__tablename__ for model in INSERT_MODELS}
EXPECTED_AUDITS = [
    ("family_version", "family_version_registered"),
    ("configuration", "website_draft_created"),
    ("compact_estimate_form", "component_created"),
    ("campaign_banner", "component_created"),
    ("sticky_mobile_action_bar", "component_created"),
    ("family_version", "family_version_approved"),
    ("configuration", "website_configuration_approved"),
    ("configuration", "website_configuration_activated"),
    ("compact_estimate_form", "component_activated"),
    ("campaign_banner", "component_activated"),
    ("sticky_mobile_action_bar", "component_activated"),
]


@pytest.fixture()
def v5_registration_postgres_engine() -> Engine:
    admin_url_value = os.getenv(POSTGRES_ADMIN_URL_ENV)
    if not admin_url_value:
        pytest.skip(
            f"Set {POSTGRES_ADMIN_URL_ENV} to a task-owned disposable PostgreSQL "
            "administrative URL to run the V5 registration tests."
        )

    admin_url = make_url(admin_url_value)
    if admin_url.get_backend_name() != "postgresql":
        pytest.fail("The V5 registration integration tests require PostgreSQL.")
    expected_host = os.getenv(POSTGRES_EXPECTED_HOST_ENV)
    allowed_hosts = LOCAL_POSTGRES_HOSTS | ({expected_host} if expected_host else set())
    if (admin_url.host or "").lower() not in allowed_hosts:
        pytest.fail("The V5 registration tests refuse an unapproved PostgreSQL host.")
    if not admin_url.database or admin_url.database.lower() == "atlas":
        pytest.fail("The V5 registration tests refuse the active Atlas database.")

    database_name = f"{DISPOSABLE_DATABASE_PREFIX}{uuid4().hex}"
    target_url = admin_url.set(database=database_name)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    target_engine: Engine | None = None
    try:
        with admin_engine.connect() as connection:
            assert connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            ).scalar_one_or_none() is None
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

        backend_root = Path(__file__).resolve().parents[1]
        migration_environment = os.environ.copy()
        migration_environment["DATABASE_URL"] = target_url.render_as_string(
            hide_password=False
        )
        migration_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=backend_root,
            env=migration_environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if migration.returncode != 0:
            pytest.fail(
                "Disposable V5 registration migration failed:\n"
                + migration.stdout
                + migration.stderr
            )
        target_engine = create_engine(target_url, pool_pre_ping=True)
        yield target_engine
    finally:
        if target_engine is not None:
            target_engine.dispose(close=True)
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
            assert connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database_name},
            ).scalar_one_or_none() is None
        admin_engine.dispose(close=True)


def _model_rows(session: Session, model: Any) -> list[dict[str, Any]]:
    return [
        deepcopy(item.model_dump())
        for item in session.exec(select(model).order_by(model.id)).all()
    ]


def _insert_counts(session: Session) -> dict[Any, int]:
    return {model: len(session.exec(select(model)).all()) for model in INSERT_MODELS}


def _sequence_state(session: Session) -> dict[str, tuple[int, bool]]:
    return {
        name: tuple(
            session.exec(text(f'SELECT last_value, is_called FROM "{name}"')).one()
        )
        for name in SEQUENCES
    }


def _non_target_table_fingerprints(engine: Engine) -> dict[str, tuple[int, str]]:
    fingerprints: dict[str, tuple[int, str]] = {}
    with engine.connect() as connection:
        tables = connection.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
        ).scalars()
        for table in tables:
            if table in TARGET_TABLES:
                continue
            quoted = engine.dialect.identifier_preparer.quote(table)
            count, digest = connection.execute(
                text(
                    "SELECT count(*), md5(COALESCE(string_agg(to_jsonb(row_value)::text, "
                    "E'\\n' ORDER BY to_jsonb(row_value)::text), '')) "
                    f"FROM {quoted} AS row_value"
                )
            ).one()
            fingerprints[table] = (count, digest)
    return fingerprints


def _assert_exact_apply(
    session: Session,
    *,
    website_id: int,
    counts_before: dict[Any, int],
) -> Any:
    planned = plan_performance_local_v5_registration(session, website_id)
    assert planned.status == "PLANNED"
    assert len(planned.actions) == 8
    assert planned.blockers == []

    applied = apply_performance_local_v5_registration(
        session,
        website_id,
        actor="Disposable PostgreSQL V5 Registration Test",
    )

    assert applied.status == "APPLIED"
    assert applied.identity.theme_family_version_id is not None
    assert applied.identity.website_theme_configuration_id is not None
    assert len(applied.identity.component_configuration_ids) == 3
    assert len(applied.audit_ids) == 6
    assert _v5_audit_natural_identities(
        session,
        version_id=applied.identity.theme_family_version_id,
        configuration_id=applied.identity.website_theme_configuration_id,
        component_ids=applied.identity.component_configuration_ids,
    ) == EXPECTED_AUDITS
    deltas = {
        model: count - counts_before[model]
        for model, count in _insert_counts(session).items()
    }
    assert deltas == {
        ThemeFamilyVersion: 1,
        WebsiteThemeConfiguration: 1,
        WebsiteThemeComponentConfiguration: 3,
        ThemeConfigurationAudit: 11,
        Theme: 1,
        WebsiteThemeSelection: 1,
    }
    assert sum(deltas.values()) == 18
    return applied


def _assert_write_free_replay(
    engine: Engine,
    *,
    website_id: int,
    expected_identity: Any,
) -> None:
    statements: list[str] = []

    def capture(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    with Session(engine) as session:
        sequence_before = _sequence_state(session)
        session.rollback()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            planned = plan_performance_local_v5_registration(session, website_id)
            repeated = apply_performance_local_v5_registration(
                session,
                website_id,
                actor="Disposable PostgreSQL V5 Registration Test",
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert planned.status == "UNCHANGED"
        assert repeated.status == "UNCHANGED"
        assert repeated.identity == expected_identity
        assert repeated.audit_ids == []
        assert not session.new and not session.dirty and not session.deleted
        session.rollback()
        assert _sequence_state(session) == sequence_before
        session.rollback()

    normalized = [statement.lstrip().upper() for statement in statements]
    assert not any(
        statement.startswith(("INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE"))
        or "NEXTVAL(" in statement
        or "SETVAL(" in statement
        for statement in normalized
    )


def test_postgres_original_sequences_apply_and_replay_are_exact(
    v5_registration_postgres_engine: Engine,
) -> None:
    engine = v5_registration_postgres_engine
    with Session(engine) as session:
        website_id, v2_id, v3_id = _seed_v3_graph(session)
        counts_before = _insert_counts(session)
        non_target_before = _non_target_table_fingerprints(engine)
        preserved_versions = {
            item.id: deepcopy(item.model_dump())
            for item in session.exec(
                select(ThemeFamilyVersion).where(
                    ThemeFamilyVersion.id.in_([v2_id, v3_id])
                )
            ).all()
        }
        preserved_v3_configuration = session.exec(
            select(WebsiteThemeConfiguration).where(
                WebsiteThemeConfiguration.configuration_key == "performance-local-v3"
            )
        ).one()
        preserved_v3_configuration_dump = deepcopy(
            preserved_v3_configuration.model_dump()
        )
        preserved_v3_components = {
            item.id: deepcopy(item.model_dump())
            for item in session.exec(
                select(WebsiteThemeComponentConfiguration).where(
                    WebsiteThemeComponentConfiguration.component_contract_version == 3
                )
            ).all()
        }
        source_theme = session.exec(
            select(Theme).where(Theme.theme_key == "flo-zone-default")
        ).one()
        source_theme_dump = deepcopy(source_theme.model_dump())
        prior_selection = session.exec(
            select(WebsiteThemeSelection).where(
                WebsiteThemeSelection.status == "active"
            )
        ).one()

        applied = _assert_exact_apply(
            session,
            website_id=website_id,
            counts_before=counts_before,
        )

        session.expire_all()
        assert {
            item.id: item.model_dump()
            for item in session.exec(
                select(ThemeFamilyVersion).where(
                    ThemeFamilyVersion.id.in_([v2_id, v3_id])
                )
            ).all()
        } == preserved_versions
        assert session.get(
            WebsiteThemeConfiguration, preserved_v3_configuration.id
        ).model_dump() == preserved_v3_configuration_dump
        assert {
            item.id: item.model_dump()
            for item in session.exec(
                select(WebsiteThemeComponentConfiguration).where(
                    WebsiteThemeComponentConfiguration.component_contract_version == 3
                )
            ).all()
        } == preserved_v3_components
        assert session.get(Theme, source_theme.id).model_dump() == source_theme_dump
        historical_selection = session.get(WebsiteThemeSelection, prior_selection.id)
        assert historical_selection is not None
        assert historical_selection.id == 1
        assert historical_selection.version == 1
        assert historical_selection.status == "replaced"
        active = session.exec(
            select(WebsiteThemeSelection).where(
                WebsiteThemeSelection.website_id == website_id,
                WebsiteThemeSelection.status == "active",
            )
        ).all()
        assert [item.id for item in active] == [
            applied.identity.website_theme_selection_id
        ]
        session.rollback()

    assert _non_target_table_fingerprints(engine) == non_target_before
    _assert_write_free_replay(
        engine,
        website_id=website_id,
        expected_identity=applied.identity,
    )


def test_postgres_deliberate_sequence_gaps_use_actual_ids_and_replay_cleanly(
    v5_registration_postgres_engine: Engine,
) -> None:
    engine = v5_registration_postgres_engine
    with Session(engine) as session:
        website_id, _, _ = _seed_v3_graph(session)
        counts_before = _insert_counts(session)
        non_target_before = _non_target_table_fingerprints(engine)
        original_sequences = _sequence_state(session)
        gapped_last_values = {
            name: last_value + 37 + (index * 11)
            for index, (name, (last_value, _)) in enumerate(
                original_sequences.items()
            )
        }
        for name, value in gapped_last_values.items():
            session.exec(
                text(f'SELECT setval(\'{name}\', :value, true)'),
                params={"value": value},
            )
        session.commit()
        stale_next_ids = {
            ThemeFamilyVersion: max(item.id for item in session.exec(select(ThemeFamilyVersion)))
            + 1,
            WebsiteThemeConfiguration: max(
                item.id for item in session.exec(select(WebsiteThemeConfiguration))
            )
            + 1,
            WebsiteThemeComponentConfiguration: max(
                item.id
                for item in session.exec(select(WebsiteThemeComponentConfiguration))
            )
            + 1,
            ThemeConfigurationAudit: max(
                item.id for item in session.exec(select(ThemeConfigurationAudit))
            )
            + 1,
            Theme: max(item.id for item in session.exec(select(Theme))) + 1,
            WebsiteThemeSelection: max(
                item.id for item in session.exec(select(WebsiteThemeSelection))
            )
            + 1,
        }

        applied = _assert_exact_apply(
            session,
            website_id=website_id,
            counts_before=counts_before,
        )

        actual_ids = {
            ThemeFamilyVersion: applied.identity.theme_family_version_id,
            WebsiteThemeConfiguration: applied.identity.website_theme_configuration_id,
            WebsiteThemeComponentConfiguration: min(
                applied.identity.component_configuration_ids
            ),
            ThemeConfigurationAudit: min(
                audit.id
                for audit in session.exec(
                    select(ThemeConfigurationAudit).where(
                        ThemeConfigurationAudit.theme_family_version_id
                        == applied.identity.theme_family_version_id
                    )
                ).all()
            ),
            Theme: applied.identity.materialized_theme_id,
            WebsiteThemeSelection: applied.identity.website_theme_selection_id,
        }
        assert all(
            actual_ids[model] != stale_next_ids[model] for model in stale_next_ids
        )
        assert actual_ids == {
            ThemeFamilyVersion: gapped_last_values["themefamilyversion_id_seq"] + 1,
            WebsiteThemeConfiguration: gapped_last_values[
                "websitethemeconfiguration_id_seq"
            ]
            + 1,
            WebsiteThemeComponentConfiguration: gapped_last_values[
                "websitethemecomponentconfiguration_id_seq"
            ]
            + 1,
            ThemeConfigurationAudit: gapped_last_values[
                "themeconfigurationaudit_id_seq"
            ]
            + 1,
            Theme: gapped_last_values["theme_id_seq"] + 1,
            WebsiteThemeSelection: gapped_last_values[
                "websitethemeselection_id_seq"
            ]
            + 1,
        }
        session.rollback()

    assert _non_target_table_fingerprints(engine) == non_target_before
    _assert_write_free_replay(
        engine,
        website_id=website_id,
        expected_identity=applied.identity,
    )


def test_postgres_genuine_audit_mismatch_rolls_back_without_sequence_reset(
    v5_registration_postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = v5_registration_postgres_engine
    with Session(engine) as session:
        website_id, _, _ = _seed_v3_graph(session)
        durable_before = {model: _model_rows(session, model) for model in INSERT_MODELS}
        non_target_before = _non_target_table_fingerprints(engine)
        sequence_before = _sequence_state(session)
        append_audit = theme_service._append_audit

        def append_one_wrong_action(
            *args: object, **kwargs: object
        ) -> ThemeConfigurationAudit:
            snapshot = kwargs.get("snapshot")
            if (
                kwargs.get("action_type") == "component_activated"
                and isinstance(snapshot, dict)
                and snapshot.get("component_key") == "campaign_banner"
            ):
                kwargs["action_type"] = "component_created"
            return append_audit(*args, **kwargs)  # type: ignore[arg-type]

        statements: list[str] = []

        def capture(
            _connection: Any,
            _cursor: Any,
            statement: str,
            _parameters: Any,
            _context: Any,
            _executemany: bool,
        ) -> None:
            statements.append(statement)

        monkeypatch.setattr(theme_service, "_append_audit", append_one_wrong_action)
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with pytest.raises(
                PerformanceLocalV5RegistrationError,
                match="V5 audit graph is not exact",
            ):
                apply_performance_local_v5_registration(
                    session,
                    website_id,
                    actor="Disposable PostgreSQL V5 Registration Test",
                )
        finally:
            event.remove(engine, "before_cursor_execute", capture)

        assert {model: _model_rows(session, model) for model in INSERT_MODELS} == (
            durable_before
        )
        assert _non_target_table_fingerprints(engine) == non_target_before
        sequence_after = _sequence_state(session)
        assert {
            name: sequence_after[name][0] - sequence_before[name][0]
            for name in SEQUENCES
        } == {
            "themefamilyversion_id_seq": 1,
            "websitethemeconfiguration_id_seq": 1,
            "websitethemecomponentconfiguration_id_seq": 3,
            "themeconfigurationaudit_id_seq": 11,
            "theme_id_seq": 1,
            "websitethemeselection_id_seq": 1,
        }
        assert not any("SETVAL(" in statement.upper() for statement in statements)
        assert not session.exec(
            select(ThemeFamilyVersion).where(
                ThemeFamilyVersion.version == PERFORMANCE_LOCAL_V5_FAMILY_VERSION
            )
        ).all()
        assert not session.exec(
            select(Theme).where(Theme.theme_key == PERFORMANCE_LOCAL_V5_THEME_KEY)
        ).all()
