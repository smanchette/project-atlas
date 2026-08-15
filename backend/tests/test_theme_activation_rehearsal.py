from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Brand,
    Business,
    GeneratedPage,
    ImageMetadata,
    PageComposition,
    PlannedPage,
    SitePlan,
    Theme,
    ThemeConfigurationAudit,
    ThemeFamily,
    ThemeFamilyVersion,
    Website,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
    WebsiteThemeSelection,
)
from app.schemas.theme_families import (
    PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS,
    PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
    PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS,
    FormReadinessItemRead,
    ThemeActivationRehearsalCreate,
    ThemeActivationRehearsalRollbackCreate,
    ThemeDeliveryBlockerRead,
    ThemeFamilyCreate,
    ThemeFamilyVersionCreate,
    WebsiteThemeComponentConfigurationCreate,
    WebsiteThemeComponentConfigurationRead,
    WebsiteThemeConfigurationCreate,
)
from app.services import form_submission_gateway as gateway
from app.services import theme_activation_rehearsal as rehearsal
from app.services import theme_configurations as theme_service
from app.services.form_submission_gateway import evaluate_form_readiness
from app.services.themes import DEFAULT_THEME_TOKENS, canonical_token_hash


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


def _fields() -> list[dict]:
    definitions = [
        ("name", "Name", True, "input", "text", 1, "nonempty_text", 1, 100, "half", "name"),
        ("phone", "Phone", True, "input", "tel", 2, "phone", 7, 40, "half", "phone"),
        ("postal-code", "ZIP code", True, "input", "text", 3, "postal_code", 5, 12, "half", "postal_code"),
        ("requested-service", "Requested service", True, "input", "text", 4, "nonempty_text", 1, 160, "half", "requested_service"),
        ("message", "Optional message", False, "textarea", "text", 5, "free_text", 0, 2000, "full", "message"),
    ]
    return [
        {
            "field_key": key,
            "label": label,
            "required": required,
            "control": control,
            "input_type": input_type,
            "order": order,
            "accessibility_label": label,
            "autocomplete_policy": "off",
            "maximum_length": maximum,
            "validation_contract": {
                "rule": rule,
                "minimum_length": minimum,
                "maximum_length": maximum,
            },
            "responsive_layout": layout,
            "provider_mapping": mapping,
        }
        for (
            key,
            label,
            required,
            control,
            input_type,
            order,
            rule,
            minimum,
            maximum,
            layout,
            mapping,
        ) in definitions
    ]


def _form_payload(state: str) -> dict:
    base = {
        "submission_state": state,
        "fields": _fields(),
        "submit_label": "Request an Estimate",
        "preview_notice": "Disposable rehearsal only; no external delivery.",
    }
    if state == "disabled_pending_provider_configuration":
        return {
            **base,
            "provider": {
                "provider_key": None,
                "destination": None,
                "provider_secret_reference": None,
                "test_only": False,
            },
            "privacy": {
                "policy_destination": None,
                "consent_mode": None,
                "consent_text": None,
                "consent_text_version": None,
            },
            "retention": {
                "duration": None,
                "deletion_expiration_behavior": None,
            },
            "spam": {"strategy": None, "configuration_reference": None},
            "success_behavior": None,
            "failure_behavior": None,
            "security": {
                "same_origin_policy": None,
                "csrf_policy": None,
                "request_size_limit_bytes": None,
                "idempotency_strategy": None,
            },
            "audit_identity": None,
        }
    assert state == "rehearsal_ready"
    return {
        **base,
        "provider": {
            "provider_key": gateway.SYNTHETIC_PROVIDER_KEY,
            "destination": gateway.SYNTHETIC_PROVIDER_DESTINATION,
            "provider_secret_reference": "secret-ref://atlas/forms/estimate-provider",
            "test_only": True,
        },
        "privacy": {
            "policy_destination": "http://localhost/privacy",
            "consent_mode": "not_required",
            "consent_text": None,
            "consent_text_version": None,
        },
        "retention": {
            "duration": "synthetic-policy-duration",
            "deletion_expiration_behavior": "discard-after-synthetic-result",
        },
        "spam": {
            "strategy": "synthetic_test",
            "configuration_reference": "synthetic-noop",
        },
        "success_behavior": "Show a generic success state.",
        "failure_behavior": "Show a generic failure state.",
        "security": {
            "same_origin_policy": "exact_origin",
            "csrf_policy": "origin_and_token",
            "request_size_limit_bytes": 4096,
            "idempotency_strategy": "required_header",
        },
        "audit_identity": "performance-local-v3-synthetic-form-audit",
    }


def _contract(component_key: str) -> dict:
    return next(
        deepcopy(item)
        for item in PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS
        if item["component_key"] == component_key
    )


def _seed_graph(session: Session, *, form_state: str) -> SimpleNamespace:
    business = Business(
        company_name=f"Rehearsal {form_state}",
        business_type="synthetic test",
        state="FL",
        phone="(407) 555-0100",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name="Rehearsal Brand",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name="Disposable Rehearsal Website",
        domain=f"{form_state.replace('_', '-')}.example.test",
        public_url=f"https://{form_state.replace('_', '-')}.example.test",
        status="active",
    )
    session.add(website)
    session.flush()
    now = datetime.now(UTC)
    current_theme = Theme(
        website_id=website.id,
        business_id=business.id,
        brand_id=brand.id,
        theme_key="governed-current",
        theme_name="Governed Current Theme",
        version=1,
        token_contract_version=1,
        design_tokens=DEFAULT_THEME_TOKENS.model_dump(mode="json"),
        token_hash_sha256=canonical_token_hash(DEFAULT_THEME_TOKENS),
        lifecycle_status="available",
        approval_status="approved",
        created_by="Prior Operator",
        provenance_type="operator_configured",
        provenance_notes="Exact prior Theme for disposable rehearsal tests.",
        approved_by="Prior Operator",
        approved_at=now,
    )
    session.add(current_theme)
    session.flush()
    current_selection = WebsiteThemeSelection(
        website_id=website.id,
        theme_id=current_theme.id,
        version=1,
        status="active",
        selected_by="Prior Operator",
        rationale="Exact prior governed selection.",
        selected_at=now,
    )
    session.add(current_selection)
    session.commit()

    family = theme_service.register_theme_family(
        session,
        ThemeFamilyCreate(
            family_key="performance-local",
            display_name="Performance Local",
            description="Reusable Performance Local rehearsal family.",
            provider_source_identity="atlas-source:performance-local",
            created_by="Rehearsal Operator",
        ),
    )
    v2 = theme_service.register_theme_family_version(
        session,
        family.id,
        ThemeFamilyVersionCreate(
            version=2,
            source_commit=PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
            supported_component_contracts=list(
                PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS
            ),
            created_by="Rehearsal Operator",
        ),
    )
    v3 = theme_service.register_theme_family_version(
        session,
        family.id,
        ThemeFamilyVersionCreate(
            version=3,
            source_commit="3" * 40,
            supported_component_contracts=list(
                PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS
            ),
            created_by="Rehearsal Operator",
            supersedes_theme_family_version_id=v2.id,
        ),
    )
    configuration = theme_service.create_website_theme_configuration(
        session,
        website.id,
        WebsiteThemeConfigurationCreate(
            theme_family_version_id=v3.id,
            configuration_key="performance-local-v3",
            created_by="Rehearsal Operator",
            creation_rationale="Create the exact inactive V3 rehearsal draft.",
        ),
    )
    form_contract = _contract("compact_estimate_form")
    form = theme_service.create_component_configuration(
        session,
        website.id,
        configuration.id,
        WebsiteThemeComponentConfigurationCreate(
            component_instance_key="estimate-form-default",
            component_key="compact_estimate_form",
            component_contract_version=3,
            scope_type="website_default",
            enabled=True,
            variant=form_contract["variant"],
            placement=form_contract["placement"],
            responsive_visibility=form_contract["responsive_visibility"],
            configuration_payload=_form_payload(form_state),
            approval_identity="Rehearsal Operator",
            created_by="Rehearsal Operator",
        ),
    )
    banner_contract = _contract("campaign_banner")
    banner = theme_service.create_component_configuration(
        session,
        website.id,
        configuration.id,
        WebsiteThemeComponentConfigurationCreate(
            component_instance_key="campaign-default",
            component_key="campaign_banner",
            component_contract_version=3,
            scope_type="website_default",
            enabled=True,
            variant=banner_contract["variant"],
            placement=banner_contract["placement"],
            responsive_visibility=banner_contract["responsive_visibility"],
            configuration_payload={
                "intent": "evergreen_conversion",
                "message": "Request an Estimate",
                "cta_label": "Request an Estimate",
                "approval_identity": "Rehearsal Operator",
            },
            approval_identity="Rehearsal Operator",
            created_by="Rehearsal Operator",
            destination_component_configuration_id=form.id,
        ),
    )
    sticky_contract = _contract("sticky_mobile_action_bar")
    sticky = theme_service.create_component_configuration(
        session,
        website.id,
        configuration.id,
        WebsiteThemeComponentConfigurationCreate(
            component_instance_key="conversion-actions-default",
            component_key="sticky_mobile_action_bar",
            component_contract_version=3,
            scope_type="website_default",
            enabled=True,
            variant=sticky_contract["variant"],
            placement=sticky_contract["placement"],
            responsive_visibility=sticky_contract["responsive_visibility"],
            configuration_payload={
                "call_source": "governed_website_identity",
                "call_label": "Call",
                "estimate_label": "Request an Estimate",
                "desktop_sticky_header": True,
                "mobile_sticky_bottom": True,
                "hide_while_hero_actions_visible": True,
                "hide_while_navigation_open": True,
                "protect_form_focus": True,
                "safe_area_support": True,
                "prevent_content_obstruction": True,
            },
            approval_identity="Rehearsal Operator",
            created_by="Rehearsal Operator",
            destination_component_configuration_id=form.id,
        ),
    )
    return SimpleNamespace(
        website=website,
        family=family,
        v3=v3,
        configuration=configuration,
        form=form,
        banner=banner,
        sticky=sticky,
        current_theme=current_theme,
        current_selection=current_selection,
    )


def _counts(session: Session) -> dict[str, int]:
    models = (
        Theme,
        WebsiteThemeSelection,
        ThemeFamily,
        ThemeFamilyVersion,
        WebsiteThemeConfiguration,
        WebsiteThemeComponentConfiguration,
        ThemeConfigurationAudit,
        PageComposition,
    )
    return {
        model.__name__: len(session.exec(select(model)).all()) for model in models
    }


def _activation_payload(graph: SimpleNamespace) -> ThemeActivationRehearsalCreate:
    return ThemeActivationRehearsalCreate(
        expected_configuration_fingerprint=graph.configuration.integrity_fingerprint,
        expected_current_selection_id=graph.current_selection.id,
        actor="Disposable Rehearsal Operator",
        confirmation="DISPOSABLE PERFORMANCE LOCAL V3 REHEARSAL",
    )


def test_activation_planner_is_zero_write_and_reports_disabled_form_blockers(
    session: Session,
) -> None:
    graph = _seed_graph(
        session,
        form_state="disabled_pending_provider_configuration",
    )
    before = _counts(session)
    plan = rehearsal.plan_theme_activation_rehearsal(
        session,
        graph.website.id,
        graph.configuration.id,
    )

    assert plan.write_count == 0
    assert plan.current_selection_id == graph.current_selection.id
    assert plan.target_theme_family_version_id == graph.v3.id
    assert plan.component_configuration_ids == [
        graph.banner.id,
        graph.sticky.id,
        graph.form.id,
    ]
    assert [item.component_configuration_id for item in plan.component_revision_graph] == (
        plan.component_configuration_ids
    )
    assert all(item.integrity_fingerprint for item in plan.component_revision_graph)
    assert plan.expected_export_state == "blocked"
    assert {item.code for item in plan.form_blockers} >= {
        "submission_disabled",
        "missing_provider",
        "missing_privacy_destination",
        "missing_retention_duration",
        "missing_spam_strategy",
    }
    assert plan.privacy_blockers
    assert plan.publication_blockers
    assert [item.sequence for item in plan.mutation_ledger] == list(
        range(1, len(plan.mutation_ledger) + 1)
    )
    assert _counts(session) == before
    assert not session.new and not session.dirty and not session.deleted


def test_provider_disabled_real_draft_cannot_activate(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_graph(
        session,
        form_state="disabled_pending_provider_configuration",
    )
    monkeypatch.setattr(
        rehearsal,
        "disposable_rehearsal_environment_allowed",
        lambda: True,
    )
    before = _counts(session)
    with pytest.raises(
        rehearsal.ThemeActivationRehearsalError,
        match="provider-disabled",
    ) as captured:
        rehearsal.activate_theme_configuration_rehearsal(
            session,
            graph.website.id,
            graph.configuration.id,
            _activation_payload(graph),
        )
    assert captured.value.code == "rehearsal_form_readiness_blocked"
    assert _counts(session) == before
    assert graph.configuration.lifecycle_status == "draft"
    assert graph.current_selection.status == "active"


def test_rehearsal_mutations_refuse_a_non_disposable_runtime(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_graph(session, form_state="rehearsal_ready")
    monkeypatch.setattr(
        rehearsal,
        "disposable_rehearsal_environment_allowed",
        lambda: False,
    )
    with pytest.raises(rehearsal.ThemeActivationRehearsalError) as captured:
        rehearsal.activate_theme_configuration_rehearsal(
            session,
            graph.website.id,
            graph.configuration.id,
            _activation_payload(graph),
        )
    assert captured.value.status_code == 404
    assert captured.value.code == "rehearsal_route_unavailable"


def test_activation_rejects_valid_component_graph_drift_after_planning(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_graph(session, form_state="rehearsal_ready")
    planned = rehearsal.plan_theme_activation_rehearsal(
        session,
        graph.website.id,
        graph.configuration.id,
    )
    graph.banner.updated_by = "Concurrent Rehearsal Operator"
    graph.banner.updated_at = datetime.now(UTC)
    graph.banner.integrity_fingerprint = (
        theme_service._component_fingerprint_from_record(graph.banner)
    )
    session.add(graph.banner)
    session.commit()
    monkeypatch.setattr(
        rehearsal,
        "disposable_rehearsal_environment_allowed",
        lambda: True,
    )
    monkeypatch.setattr(
        rehearsal,
        "plan_theme_activation_rehearsal",
        lambda *_args, **_kwargs: planned,
    )
    before = _counts(session)

    with pytest.raises(rehearsal.ThemeActivationRehearsalError) as captured:
        rehearsal.activate_theme_configuration_rehearsal(
            session,
            graph.website.id,
            graph.configuration.id,
            _activation_payload(graph),
        )

    assert captured.value.code == "rehearsal_component_graph_precondition_failed"
    assert _counts(session) == before
    assert graph.configuration.lifecycle_status == "draft"
    assert graph.current_selection.status == "active"


def test_synthetic_disposable_activation_and_rollback_restore_exact_prior_selection(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_graph(session, form_state="rehearsal_ready")
    monkeypatch.setattr(
        rehearsal,
        "disposable_rehearsal_environment_allowed",
        lambda: True,
    )
    initial_configuration_fingerprint = graph.configuration.integrity_fingerprint
    initial_component_fingerprints = {
        item.id: item.integrity_fingerprint
        for item in (graph.form, graph.banner, graph.sticky)
    }
    initial_selection_updated_at = graph.current_selection.updated_at
    version_identity = (
        graph.v3.lifecycle_status,
        graph.v3.production_ready,
        graph.v3.integrity_fingerprint,
    )

    activated = rehearsal.activate_theme_configuration_rehearsal(
        session,
        graph.website.id,
        graph.configuration.id,
        _activation_payload(graph),
    )
    session.refresh(graph.configuration)
    session.refresh(graph.v3)
    assert activated.status == "activated"
    assert activated.active_selection_count == 1
    assert activated.v3_active_selection_count == 1
    assert graph.configuration.lifecycle_status == "active"
    assert (
        graph.v3.lifecycle_status,
        graph.v3.production_ready,
        graph.v3.integrity_fingerprint,
    ) == version_identity
    active = session.exec(
        select(WebsiteThemeSelection).where(
            WebsiteThemeSelection.website_id == graph.website.id,
            WebsiteThemeSelection.status == "active",
        )
    ).all()
    assert [item.id for item in active] == [activated.rehearsal_selection_id]

    rolled_back = rehearsal.rollback_theme_configuration_rehearsal(
        session,
        graph.website.id,
        graph.configuration.id,
        ThemeActivationRehearsalRollbackCreate(
            expected_configuration_fingerprint=graph.configuration.integrity_fingerprint,
            expected_prior_selection_id=activated.prior_selection_id,
            expected_rehearsal_theme_id=activated.rehearsal_theme_id,
            expected_rehearsal_selection_id=activated.rehearsal_selection_id,
            actor="Disposable Rollback Operator",
            confirmation="ROLL BACK DISPOSABLE PERFORMANCE LOCAL V3 REHEARSAL",
        ),
    )
    session.refresh(graph.configuration)
    session.refresh(graph.current_selection)
    session.refresh(graph.v3)
    for component in (graph.form, graph.banner, graph.sticky):
        session.refresh(component)

    assert rolled_back.status == "rolled_back"
    assert rolled_back.active_selection_count == 1
    assert rolled_back.v3_active_selection_count == 0
    assert graph.current_selection.status == "active"
    assert graph.current_selection.replaced_at is None
    assert graph.current_selection.updated_at == initial_selection_updated_at
    assert graph.configuration.lifecycle_status == "draft"
    assert graph.configuration.integrity_fingerprint == initial_configuration_fingerprint
    assert graph.configuration.materialized_theme_id is None
    assert graph.configuration.website_theme_selection_id is None
    assert {
        item.id: item.integrity_fingerprint
        for item in (graph.form, graph.banner, graph.sticky)
    } == initial_component_fingerprints
    assert all(
        item.activation_identity is None and item.rollback_identity is None
        for item in (graph.form, graph.banner, graph.sticky)
    )
    assert (
        graph.v3.lifecycle_status,
        graph.v3.production_ready,
        graph.v3.integrity_fingerprint,
    ) == version_identity
    active = session.exec(
        select(WebsiteThemeSelection).where(
            WebsiteThemeSelection.website_id == graph.website.id,
            WebsiteThemeSelection.status == "active",
        )
    ).all()
    assert [item.id for item in active] == [graph.current_selection.id]
    actions = [
        item.action_type
        for item in session.exec(
            select(ThemeConfigurationAudit).order_by(ThemeConfigurationAudit.id)
        ).all()
    ]
    assert actions.count("website_configuration_approved") == 1
    assert actions.count("website_configuration_activated") == 1
    assert actions.count("component_activated") == 3
    assert actions.count("component_rolled_back") == 3
    assert actions.count("website_configuration_rolled_back") == 1
    assert [item.sequence for item in rolled_back.mutation_ledger] == list(
        range(1, len(rolled_back.mutation_ledger) + 1)
    )


def test_rollback_releases_active_selection_slot_before_restoring_prior(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_graph(session, form_state="rehearsal_ready")
    monkeypatch.setattr(
        rehearsal,
        "disposable_rehearsal_environment_allowed",
        lambda: True,
    )
    activated = rehearsal.activate_theme_configuration_rehearsal(
        session,
        graph.website.id,
        graph.configuration.id,
        _activation_payload(graph),
    )
    session.refresh(graph.configuration)
    rehearsal_selection = session.get(
        WebsiteThemeSelection,
        activated.rehearsal_selection_id,
    )
    assert rehearsal_selection is not None

    ordered_flushes: list[tuple[int, str, int, str]] = []
    commit_count = 0
    original_flush = session.flush
    original_commit = session.commit

    def observing_flush(objects=None) -> None:  # type: ignore[no-untyped-def]
        values = list(objects) if objects is not None else []
        if len(values) == 1 and values[0] is rehearsal_selection:
            ordered_flushes.append(
                (
                    rehearsal_selection.id,
                    rehearsal_selection.status,
                    graph.current_selection.id,
                    graph.current_selection.status,
                )
            )
        original_flush(objects)

    def observing_commit() -> None:
        nonlocal commit_count
        commit_count += 1
        original_commit()

    monkeypatch.setattr(session, "flush", observing_flush)
    monkeypatch.setattr(session, "commit", observing_commit)

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
            expected_rehearsal_selection_id=activated.rehearsal_selection_id,
            actor="Disposable Rollback Operator",
            confirmation=(
                "ROLL BACK DISPOSABLE PERFORMANCE LOCAL V3 REHEARSAL"
            ),
        ),
    )

    assert rolled_back.status == "rolled_back"
    assert ordered_flushes == [
        (
            activated.rehearsal_selection_id,
            "replaced",
            activated.prior_selection_id,
            "replaced",
        )
    ]
    assert commit_count == 1


def test_rollback_selection_flush_remains_inside_atomic_service_transaction(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_graph(session, form_state="rehearsal_ready")
    monkeypatch.setattr(
        rehearsal,
        "disposable_rehearsal_environment_allowed",
        lambda: True,
    )
    activated = rehearsal.activate_theme_configuration_rehearsal(
        session,
        graph.website.id,
        graph.configuration.id,
        _activation_payload(graph),
    )
    session.refresh(graph.configuration)
    activated_fingerprint = graph.configuration.integrity_fingerprint
    payload = ThemeActivationRehearsalRollbackCreate(
        expected_configuration_fingerprint=activated_fingerprint,
        expected_prior_selection_id=activated.prior_selection_id,
        expected_rehearsal_theme_id=activated.rehearsal_theme_id,
        expected_rehearsal_selection_id=activated.rehearsal_selection_id,
        actor="Disposable Rollback Operator",
        confirmation="ROLL BACK DISPOSABLE PERFORMANCE LOCAL V3 REHEARSAL",
    )
    original_refresh = rehearsal._refresh_stale_compositions_and_qa

    def fail_after_selection_restore(*_args, **_kwargs) -> None:
        raise RuntimeError("forced post-selection rollback failure")

    monkeypatch.setattr(
        rehearsal,
        "_refresh_stale_compositions_and_qa",
        fail_after_selection_restore,
    )
    with pytest.raises(
        RuntimeError,
        match="forced post-selection rollback failure",
    ):
        rehearsal.rollback_theme_configuration_rehearsal(
            session,
            graph.website.id,
            graph.configuration.id,
            payload,
        )

    session.expire_all()
    configuration = session.get(
        WebsiteThemeConfiguration,
        graph.configuration.id,
    )
    prior_selection = session.get(
        WebsiteThemeSelection,
        activated.prior_selection_id,
    )
    rehearsal_selection = session.get(
        WebsiteThemeSelection,
        activated.rehearsal_selection_id,
    )
    rehearsal_theme = session.get(Theme, activated.rehearsal_theme_id)
    rollback_audits = list(
        session.exec(
            select(ThemeConfigurationAudit).where(
                ThemeConfigurationAudit.action_type.in_(
                    [
                        "component_rolled_back",
                        "website_configuration_rolled_back",
                    ]
                )
            )
        ).all()
    )
    assert configuration is not None
    assert configuration.lifecycle_status == "active"
    assert configuration.integrity_fingerprint == activated_fingerprint
    assert prior_selection is not None and prior_selection.status == "replaced"
    assert rehearsal_selection is not None and rehearsal_selection.status == "active"
    assert rehearsal_theme is not None and rehearsal_theme.lifecycle_status == "available"
    assert rollback_audits == []

    monkeypatch.setattr(
        rehearsal,
        "_refresh_stale_compositions_and_qa",
        original_refresh,
    )
    rolled_back = rehearsal.rollback_theme_configuration_rehearsal(
        session,
        graph.website.id,
        graph.configuration.id,
        payload,
    )
    assert rolled_back.status == "rolled_back"
    assert rolled_back.active_selection_count == 1
    assert rolled_back.v3_active_selection_count == 0


def test_full_site_audit_types_65_pages_and_exposes_page_media_evidence(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_graph(session, form_state="rehearsal_ready")
    monkeypatch.setattr(
        rehearsal,
        "disposable_rehearsal_environment_allowed",
        lambda: True,
    )
    activated = rehearsal.activate_theme_configuration_rehearsal(
        session,
        graph.website.id,
        graph.configuration.id,
        _activation_payload(graph),
    )
    page_types = [
        "home",
        "service",
        "city_service",
        "county",
        "about",
        "contact",
        "faq",
    ]
    plan = SitePlan(
        website_id=graph.website.id,
        plan_key="full-site-rehearsal",
        plan_name="Full-site Rehearsal",
        status="active",
    )
    session.add(plan)
    session.flush()
    for index in range(1, 66):
        page = GeneratedPage(
            business_id=graph.website.business_id,
            website_id=graph.website.id,
            page_type=page_types[(index - 1) % len(page_types)],
            page_title=f"Rehearsal Page {index}",
            page_slug=f"rehearsal-page-{index}",
            qa_status="ready",
            status="draft",
        )
        session.add(page)
        session.flush()
        planned = PlannedPage(
            website_id=graph.website.id,
            site_plan_id=plan.id,
            page_type=page.page_type,
            working_name=page.page_title,
            intended_slug=page.page_slug,
            planning_status="planned",
            generated_page_id=page.id,
        )
        session.add(planned)
        session.flush()
        session.add(
            PageComposition(
                website_id=graph.website.id,
                site_plan_id=plan.id,
                planned_page_id=planned.id,
                generated_page_id=page.id,
                composition_version=1,
                generated_components=[],
                source_snapshot={},
                source_hash=f"{index:064x}",
                status="current",
            )
        )
        if page.id != 7:
            session.add(
                ImageMetadata(
                    id=1000 + page.id,
                    business_id=graph.website.business_id,
                    file_name=f"synthetic-rehearsal-{page.id}.jpg",
                    wordpress_media_id=31 if page.id == 41 else 2000 + page.id,
                )
            )
            if page.id == 41:
                session.add_all(
                    [
                        ImageMetadata(
                            id=extra_id,
                            business_id=graph.website.business_id,
                            file_name=f"synthetic-rehearsal-{extra_id}.jpg",
                            wordpress_media_id=None,
                        )
                        for extra_id in (3041, 4041, 5041)
                    ]
                )
    session.commit()
    components = [
        WebsiteThemeComponentConfigurationRead.model_validate(item)
        for item in (graph.banner, graph.form, graph.sticky)
    ]
    readiness = evaluate_form_readiness(
        graph.form,
        mode="activation_rehearsal",
        test_environment_allowed=True,
    )

    def fake_delivery(_session, configuration_id: int, page_id: int):
        planned = _session.exec(
            select(PlannedPage).where(PlannedPage.generated_page_id == page_id)
        ).one()
        composition = _session.exec(
            select(PageComposition).where(
                PageComposition.generated_page_id == page_id
            )
        ).one()
        missing = page_id == 7
        media_id = 1000 + page_id
        source_snapshot = {
            "media_assignments": (
                [
                    {"image_metadata_id": extra_id}
                    for extra_id in (3041, 4041, 5041)
                ]
                if page_id == 41
                else []
            ),
            "page_media": {
                "requirements": [
                    {"id": page_id, "requirement_state": "required"}
                ],
                "assignments": [
                    {
                        "requirement_id": page_id,
                        "asset_id": None if missing else media_id,
                    }
                ],
            }
        }
        blockers = (
            [
                ThemeDeliveryBlockerRead(
                    code="missing_governed_media",
                    category="media",
                    reason="Required governed media is not assigned.",
                )
            ]
            if missing
            else []
        )
        return SimpleNamespace(
            composition={
                "id": composition.id,
                "composition_version": composition.composition_version,
                "source_hash": composition.source_hash,
                "source_snapshot": source_snapshot,
                "effective_components": [],
            },
            components=components,
            theme_family=SimpleNamespace(id=graph.family.id, family_key="performance-local"),
            theme_version=SimpleNamespace(id=graph.v3.id, version=3),
            website_configuration=SimpleNamespace(id=configuration_id),
            form_readiness=readiness,
            renderer_result=SimpleNamespace(
                status="blocked" if missing else "ready",
                result_code=(
                    "renderer_blocked_by_governed_readiness"
                    if missing
                    else "renderer_ready"
                ),
            ),
            export_eligibility=SimpleNamespace(eligible=not missing),
            page={"qa_status": "blocked" if missing else "ready"},
            blockers=blockers,
        )

    monkeypatch.setattr(
        rehearsal,
        "read_performance_local_rehearsal_delivery",
        fake_delivery,
    )
    report = rehearsal.audit_performance_local_full_site_rehearsal(
        session,
        graph.website.id,
        graph.configuration.id,
        expected_page_count=65,
    )

    assert report.evaluated_page_count == 65
    assert report.ready_count == 64
    assert report.blocked_count == 1
    assert {item.page_type for item in report.pages} >= set(page_types)
    page_41 = next(item for item in report.pages if item.generated_page_id == 41)
    assert page_41.theme_version == 3
    assert page_41.media_reference_ids == [1041, 3041, 4041, 5041]
    assert page_41.wordpress_media_reference_ids == [31]
    assert page_41.local_only_media_reference_ids == [3041, 4041, 5041]
    assert page_41.media_fallback_used is False
    assert page_41.scope_integrity == "exact"
    assert all(32 not in item.wordpress_media_reference_ids for item in report.pages)
    missing = next(item for item in report.pages if item.generated_page_id == 7)
    assert missing.required_media_state == "blocked_missing_required_media"
    assert missing.export_eligible is False
    assert any("missing_governed_media|media|" in item for item in missing.blockers)
    assert activated.rehearsal_selection_id == graph.configuration.website_theme_selection_id


def test_wordpress_media_evidence_blocks_missing_and_duplicate_mappings(
    session: Session,
) -> None:
    business = Business(
        company_name="Synthetic Media Evidence",
        business_type="synthetic test",
        state="FL",
    )
    session.add(business)
    session.flush()
    session.add_all(
        [
            ImageMetadata(
                id=901,
                business_id=business.id,
                file_name="first.jpg",
                wordpress_media_id=31,
            ),
            ImageMetadata(
                id=902,
                business_id=business.id,
                file_name="duplicate.jpg",
                wordpress_media_id=31,
            ),
            ImageMetadata(
                id=903,
                business_id=business.id,
                file_name="unresolved.jpg",
                wordpress_media_id=None,
            ),
        ]
    )
    session.commit()

    wordpress_ids, local_only_ids, blockers = rehearsal._wordpress_media_evidence(
        session,
        [901, 902, 903, 999],
    )

    assert wordpress_ids == [31]
    assert local_only_ids == [903]
    assert sum("media_identity_unresolved|media|" in item for item in blockers) == 1
    assert all("903" not in item for item in blockers)
    assert any("media_identity_duplicated|media|" in item for item in blockers)
