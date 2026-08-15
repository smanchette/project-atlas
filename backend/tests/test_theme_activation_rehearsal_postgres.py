from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.models import (
    ThemeConfigurationAudit,
    WebsiteThemeConfiguration,
    WebsiteThemeSelection,
)
from app.schemas.theme_families import ThemeActivationRehearsalRollbackCreate
from app.services import theme_activation_rehearsal as rehearsal
from tests.test_page_media_batch_assignment_postgres import (
    disposable_postgres_engine,
)
from tests.test_theme_activation_rehearsal import (
    _activation_payload,
    _seed_graph,
)


def test_real_postgresql_rollback_releases_unique_active_selection_slot(
    disposable_postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        rehearsal,
        "disposable_rehearsal_environment_allowed",
        lambda: True,
    )
    with Session(disposable_postgres_engine) as session:
        session.exec(
            text(
                "CREATE UNIQUE INDEX uq_websitethemeselection_active_website "
                "ON websitethemeselection (website_id) WHERE status = 'active'"
            )
        )
        session.commit()
        index_identity = session.exec(
            text(
                "SELECT index_record.indisunique, "
                "index_record.indpred IS NOT NULL "
                "FROM pg_index AS index_record "
                "JOIN pg_class AS index_class "
                "ON index_class.oid = index_record.indexrelid "
                "JOIN pg_namespace AS namespace "
                "ON namespace.oid = index_class.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "AND index_class.relname = "
                "'uq_websitethemeselection_active_website'"
            )
        ).one()
        assert tuple(index_identity) == (True, True)

        graph = _seed_graph(session, form_state="rehearsal_ready")
        initial_configuration_fingerprint = (
            graph.configuration.integrity_fingerprint
        )
        activated = rehearsal.activate_theme_configuration_rehearsal(
            session,
            graph.website.id,
            graph.configuration.id,
            _activation_payload(graph),
        )
        assert activated.prior_selection_id < activated.rehearsal_selection_id
        session.refresh(graph.configuration)

        rolled_back = rehearsal.rollback_theme_configuration_rehearsal(
            session,
            graph.website.id,
            graph.configuration.id,
            ThemeActivationRehearsalRollbackCreate(
                expected_configuration_fingerprint=(
                    graph.configuration.integrity_fingerprint
                ),
                expected_prior_selection_id=activated.prior_selection_id,
                expected_rehearsal_theme_id=activated.rehearsal_theme_id,
                expected_rehearsal_selection_id=(
                    activated.rehearsal_selection_id
                ),
                actor="Disposable Rollback Operator",
                confirmation=(
                    "ROLL BACK DISPOSABLE PERFORMANCE LOCAL V3 REHEARSAL"
                ),
            ),
        )

        configuration = session.get(
            WebsiteThemeConfiguration,
            graph.configuration.id,
        )
        active = list(
            session.exec(
                select(WebsiteThemeSelection).where(
                    WebsiteThemeSelection.website_id == graph.website.id,
                    WebsiteThemeSelection.status == "active",
                )
            ).all()
        )
        rehearsal_selection = session.get(
            WebsiteThemeSelection,
            activated.rehearsal_selection_id,
        )
        rollback_audits = list(
            session.exec(
                select(ThemeConfigurationAudit)
                .where(
                    ThemeConfigurationAudit.action_type.in_(
                        [
                            "component_rolled_back",
                            "website_configuration_rolled_back",
                        ]
                    )
                )
                .order_by(ThemeConfigurationAudit.id)
            ).all()
        )

        assert rolled_back.status == "rolled_back"
        assert rolled_back.active_selection_count == 1
        assert rolled_back.v3_active_selection_count == 0
        assert configuration is not None
        assert configuration.lifecycle_status == "draft"
        assert (
            configuration.integrity_fingerprint
            == initial_configuration_fingerprint
        )
        assert configuration.materialized_theme_id is None
        assert configuration.website_theme_selection_id is None
        assert [item.id for item in active] == [activated.prior_selection_id]
        assert rehearsal_selection is not None
        assert rehearsal_selection.status == "replaced"
        assert [item.action_type for item in rollback_audits] == [
            "component_rolled_back",
            "component_rolled_back",
            "component_rolled_back",
            "website_configuration_rolled_back",
        ]
