from sqlalchemy import CheckConstraint

from app.db import session as db_session
from app.models.entities import (
    BrandAsset,
    Business,
    InternalLinkIntent,
    NavigationItem,
    NavigationSet,
    PageComposition,
    SemanticComponentDefinition,
    SiteConnectionPlanningRecord,
    TimezoneTimestampMixin,
    WebsiteCityCoverageDecision,
    WebsiteCountyCoverageDecision,
    WebsiteCoveragePlanningRecord,
    WebsiteDraftGenerationItem,
    WebsiteDraftGenerationRun,
    WebsiteIdentityAssetAssignment,
    WebsiteServiceCityCoverageDecision,
    WebsiteServiceCountyCoverageDecision,
    WebsiteServiceCoverageDecision,
)


UTC_TIMESTAMP_MODELS = (
    SiteConnectionPlanningRecord,
    NavigationSet,
    NavigationItem,
    InternalLinkIntent,
    WebsiteCoveragePlanningRecord,
    WebsiteServiceCoverageDecision,
    WebsiteCountyCoverageDecision,
    WebsiteCityCoverageDecision,
    WebsiteServiceCityCoverageDecision,
)


def _normalized(expression: object) -> str:
    return " ".join(str(expression).lower().split())


def _checks(model) -> dict[str, str]:
    return {
        constraint.name: _normalized(constraint.sqltext)
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }


def test_only_the_authorized_models_use_timezone_aware_timestamp_mixins():
    expected_tables = {model.__tablename__ for model in UTC_TIMESTAMP_MODELS}
    observed_created = {
        table.name
        for table in db_session.SQLModel.metadata.tables.values()
        if "created_at" in table.c and table.c.created_at.type.timezone is True
    }
    observed_updated = {
        table.name
        for table in db_session.SQLModel.metadata.tables.values()
        if "updated_at" in table.c and table.c.updated_at.type.timezone is True
    }

    assert observed_created == expected_tables
    assert observed_updated == expected_tables
    assert all(TimezoneTimestampMixin in model.__mro__ for model in UTC_TIMESTAMP_MODELS)
    assert TimezoneTimestampMixin not in Business.__mro__
    assert TimezoneTimestampMixin not in WebsiteServiceCountyCoverageDecision.__mro__
    assert Business.__table__.c.created_at.type.timezone is False
    assert (
        WebsiteServiceCountyCoverageDecision.__table__.c.created_at.type.timezone
        is False
    )


def test_authorized_generated_and_decision_timestamps_are_timezone_aware():
    assert SiteConnectionPlanningRecord.__table__.c.generated_at.type.timezone is True
    assert WebsiteCoveragePlanningRecord.__table__.c.generated_at.type.timezone is True
    for model in (
        NavigationSet,
        NavigationItem,
        InternalLinkIntent,
        WebsiteServiceCoverageDecision,
        WebsiteCountyCoverageDecision,
        WebsiteCityCoverageDecision,
        WebsiteServiceCityCoverageDecision,
    ):
        assert model.__table__.c.decided_at.type.timezone is True


def test_current_models_declare_all_ten_canonical_named_checks():
    expected = {
        BrandAsset: {
            "ck_brandasset_version": "version >= 1",
            "ck_brandasset_file_size": "file_size >= 1",
            "ck_brandasset_width": "width >= 1",
            "ck_brandasset_height": "height >= 1",
        },
        WebsiteIdentityAssetAssignment: {
            "ck_identityassetassignment_version": "version >= 1",
        },
        SemanticComponentDefinition: {
            "ck_semanticcomponentdefinition_version": "contract_version >= 1",
        },
        PageComposition: {
            "ck_pagecomposition_version": "composition_version >= 1",
        },
        WebsiteDraftGenerationRun: {
            "ck_websitedraftgenerationrun_counts": (
                "expected_count >= 0 and eligible_count >= 0 "
                "and generated_count >= 0 and already_drafted_count >= 0 "
                "and skipped_count >= 0 and blocked_count >= 0 "
                "and deferred_count >= 0 and excluded_count >= 0 "
                "and stale_count >= 0 and consolidation_count >= 0 "
                "and error_count >= 0 and processed_count >= 0"
            ),
            "ck_websitedraftgenerationrun_duration": (
                "duration_ms is null or duration_ms >= 0"
            ),
        },
        WebsiteDraftGenerationItem: {
            "ck_websitedraftgenerationitem_counts": (
                "ordinal >= 1 and attempt_count >= 0"
            ),
        },
    }

    assert sum(len(checks) for checks in expected.values()) == 10
    for model, expected_checks in expected.items():
        observed = _checks(model)
        for name, expression in expected_checks.items():
            assert observed[name] == expression


def test_normal_create_all_excludes_every_alembic_owned_table(monkeypatch):
    captured: list[set[str]] = []
    quality_review_ensures: list[bool] = []

    def capture_create_all(_engine, *, tables):
        captured.append({table.name for table in tables})

    monkeypatch.setattr(db_session.SQLModel.metadata, "create_all", capture_create_all)
    for helper_name in (
        "ensure_city_schema",
        "ensure_generated_page_schema",
        "ensure_image_metadata_schema",
        "ensure_page_image_assignment_schema",
    ):
        monkeypatch.setattr(db_session, helper_name, lambda: None)
    monkeypatch.setattr(
        db_session,
        "ensure_wordpress_quality_review_schema",
        lambda: quality_review_ensures.append(True),
    )

    db_session.create_db_and_tables()
    assert quality_review_ensures == []

    db_session.create_db_and_tables(include_alembic_owned=True)

    assert len(captured) == 2
    assert quality_review_ensures == [True]
    assert db_session.ALEMBIC_OWNED_TABLES.isdisjoint(captured[0])
    assert db_session.ALEMBIC_OWNED_TABLES <= captured[1]
    assert captured[1] == set(db_session.SQLModel.metadata.tables)
    assert db_session.ALEMBIC_OWNED_RUNTIME_TABLES == {
        "wordpressmetadatastate",
        "wordpressmetadatasyncaudit",
        "wordpressqualityreview",
    }
