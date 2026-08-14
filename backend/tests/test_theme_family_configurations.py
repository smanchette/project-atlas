from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.session import get_session
from app.main import app
from app.models import (
    Brand,
    Business,
    GeneratedPage,
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
    ProductionFormSubmissionPreflightInput,
    ThemeDraftBundleCreate,
    ThemeFamilyCreate,
    ThemeFamilyVersionCreate,
    WebsiteThemeComponentConfigurationCreate,
    WebsiteThemeComponentConfigurationRevisionCreate,
    WebsiteThemeConfigurationCreate,
    validate_component_payload,
)
from app.services import theme_configurations as theme_service
from app.services.form_submission_contracts import (
    FORM_SUBMISSION_PROVIDERS,
    FormProviderError,
    production_form_submission_readiness,
    require_submission_provider,
)
from app.services.theme_configurations import (
    ThemeConfigurationError,
    create_component_configuration,
    create_inactive_theme_draft_bundle,
    list_website_theme_configurations,
    read_theme_draft_preview,
    register_theme_family,
    register_theme_family_version,
    require_theme_configuration_export_eligible,
    revise_component_configuration,
    validate_theme_configuration_records,
)
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


def _website(session: Session, suffix: str) -> Website:
    business = Business(
        company_name=f"Company {suffix}",
        business_type="test",
        state="FL",
        phone="(407) 555-0100",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name=f"Brand {suffix}",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name=f"Website {suffix}",
        domain=f"{suffix.lower()}.example.test",
        public_url=f"https://{suffix.lower()}.example.test",
        status="active",
    )
    session.add(website)
    session.commit()
    session.refresh(website)
    return website


def _contract(component_key: str) -> dict:
    return next(
        deepcopy(item)
        for item in PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS
        if item["component_key"] == component_key
    )


def _form_fields() -> list[dict]:
    definitions = [
        ("name", "Name", True, "input", "text", 1, "nonempty_text", 1, 100, "half", "name"),
        ("phone", "Phone", True, "input", "tel", 2, "phone", 6, 40, "half", "phone"),
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


def _form_payload() -> dict:
    return {
        "submission_state": "disabled_pending_provider_configuration",
        "fields": _form_fields(),
        "submit_label": "Review request",
        "preview_notice": "Draft preview only. This form does not submit or store data.",
        "provider_key": None,
        "destination": None,
        "privacy_policy_destination": None,
        "consent_language": None,
        "data_retention_policy": None,
        "spam_strategy": None,
        "success_behavior": None,
        "failure_behavior": None,
        "audit_identity": None,
    }


def _component_spec(
    component_key: str,
    instance_key: str,
    configuration_payload: dict,
    *,
    destination_instance_key: str | None = None,
) -> dict:
    contract = _contract(component_key)
    return {
        "component_instance_key": instance_key,
        "component_key": component_key,
        "component_contract_version": contract["contract_version"],
        "scope_type": "website_default",
        "planned_page_id": None,
        "enabled": True,
        "variant": contract["variant"],
        "placement": contract["placement"],
        "responsive_visibility": contract["responsive_visibility"],
        "configuration_payload": configuration_payload,
        "effective_at": None,
        "expires_at": None,
        "approval_identity": "Theme Lab Operator",
        "created_by": "Theme Lab Operator",
        "destination_component_instance_key": destination_instance_key,
        "overrides_component_configuration_id": None,
    }


def _bundle_payload(*, configuration_key: str = "performance-local-v2") -> ThemeDraftBundleCreate:
    form_instance = "estimate-form-default"
    return ThemeDraftBundleCreate.model_validate(
        {
            "theme_family": {
                "family_key": "performance-local",
                "display_name": "Performance Local",
                "description": "Reusable local-service Website Theme Family.",
                "provider_source_identity": "Atlas source-defined Performance Local v2 registry",
                "created_by": "Theme Lab Operator",
            },
            "theme_version": {
                "version": 2,
                "lifecycle_status": "preview_candidate",
                "production_ready": False,
                "source_commit": theme_service.PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
                "supported_component_contracts": list(
                    PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS
                ),
                "created_by": "Theme Lab Operator",
                "supersedes_theme_family_version_id": None,
            },
            "website_configuration": {
                "configuration_key": configuration_key,
                "created_by": "Theme Lab Operator",
                "creation_rationale": "Create an inactive durable Theme Lab draft.",
            },
            "components": [
                _component_spec(
                    "campaign_banner",
                    "campaign-default",
                    {
                        "intent": "evergreen_conversion",
                        "message": "Request a service estimate.",
                        "cta_label": "Get an estimate",
                        "approval_identity": "Theme Lab Operator",
                    },
                    destination_instance_key=form_instance,
                ),
                _component_spec(
                    "sticky_mobile_action_bar",
                    "conversion-actions-default",
                    {
                        "call_source": "governed_website_identity",
                        "call_label": "Call",
                        "estimate_label": "Estimate",
                        "desktop_sticky_header": True,
                        "mobile_sticky_bottom": True,
                        "hide_while_hero_actions_visible": True,
                        "hide_while_navigation_open": True,
                        "protect_form_focus": True,
                        "safe_area_support": True,
                        "prevent_content_obstruction": True,
                    },
                    destination_instance_key=form_instance,
                ),
                _component_spec(
                    "compact_estimate_form",
                    form_instance,
                    _form_payload(),
                ),
            ],
        }
    )


def _current_components(session: Session) -> dict[str, WebsiteThemeComponentConfiguration]:
    rows = session.exec(
        select(WebsiteThemeComponentConfiguration).where(
            WebsiteThemeComponentConfiguration.lifecycle_status == "current"
        )
    ).all()
    return {item.component_instance_key: item for item in rows}


def _add_duplicate_enabled_component(
    session: Session,
    website: Website,
    configuration: WebsiteThemeConfiguration,
    component_key: str,
) -> WebsiteThemeComponentConfiguration:
    components = _current_components(session)
    original = next(
        item for item in components.values() if item.component_key == component_key
    )
    form = next(
        item
        for item in components.values()
        if item.component_key == "compact_estimate_form"
    )
    return create_component_configuration(
        session,
        website.id,
        configuration.id,
        WebsiteThemeComponentConfigurationCreate(
            component_instance_key=f"{original.component_instance_key}-duplicate",
            component_key=original.component_key,
            component_contract_version=original.component_contract_version,
            scope_type="website_default",
            enabled=True,
            variant=original.variant,
            placement=original.placement,
            responsive_visibility=original.responsive_visibility,
            configuration_payload=deepcopy(original.configuration_payload),
            effective_at=original.effective_at,
            expires_at=original.expires_at,
            approval_identity=original.approval_identity,
            created_by="Theme Lab Operator",
            destination_component_configuration_id=(
                form.id if component_key != "compact_estimate_form" else None
            ),
        ),
    )


def _activate_export_graph(
    session: Session,
    website: Website,
    configuration_id: int,
) -> tuple[
    WebsiteThemeConfiguration,
    ThemeFamilyVersion,
    GeneratedPage,
    PlannedPage,
    Theme,
    WebsiteThemeSelection,
]:
    configuration = session.get(WebsiteThemeConfiguration, configuration_id)
    assert configuration is not None
    version = session.get(
        ThemeFamilyVersion,
        configuration.theme_family_version_id,
    )
    assert version is not None

    generated = GeneratedPage(
        business_id=website.business_id,
        website_id=website.id,
        page_type="home",
        page_title="Export Test Page",
        page_slug="export-test",
        status="draft",
    )
    session.add(generated)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="export-test",
        plan_name="Export Test Plan",
        status="active",
    )
    session.add(plan)
    session.flush()
    planned = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="home",
        working_name="Export Test Page",
        intended_slug="export-test",
        planning_status="planned",
        generated_page_id=generated.id,
    )
    session.add(planned)
    session.flush()

    token_payload = DEFAULT_THEME_TOKENS.model_dump(mode="json")
    theme = Theme(
        website_id=website.id,
        business_id=website.business_id,
        brand_id=website.brand_id,
        theme_key="performance-local",
        theme_name="Performance Local",
        version=1,
        token_contract_version=1,
        design_tokens=token_payload,
        token_hash_sha256=canonical_token_hash(DEFAULT_THEME_TOKENS),
        lifecycle_status="available",
        approval_status="approved",
        created_by="Theme Test Operator",
        provenance_type="operator_configured",
        provenance_notes="Disposable export-guard test Theme.",
        approved_by="Theme Test Operator",
        approved_at=datetime.now(UTC),
    )
    session.add(theme)
    session.flush()
    selection = WebsiteThemeSelection(
        website_id=website.id,
        theme_id=theme.id,
        version=1,
        status="active",
        selected_by="Theme Test Operator",
        rationale="Disposable exact export selection.",
    )
    session.add(selection)
    session.flush()

    transitioned_at = datetime.now(UTC)
    version.lifecycle_status = "approved"
    version.production_ready = True
    version.updated_at = transitioned_at
    version.integrity_fingerprint = theme_service._family_version_fingerprint_from_record(
        version
    )
    session.add(version)
    theme_service._append_audit(
        session,
        action_type="family_version_approved",
        actor="Theme Test Operator",
        rationale="Disposable production-eligibility approval.",
        snapshot=theme_service._family_version_fingerprint_payload(version),
        theme_family_version_id=version.id,
    )

    configuration.lifecycle_status = "active"
    configuration.approved_by = "Theme Test Operator"
    configuration.approved_at = transitioned_at
    configuration.activated_by = "Theme Test Operator"
    configuration.activated_at = transitioned_at
    configuration.materialized_theme_id = theme.id
    configuration.website_theme_selection_id = selection.id
    configuration.updated_by = "Theme Test Operator"
    configuration.updated_at = transitioned_at
    configuration.integrity_fingerprint = (
        theme_service._website_configuration_fingerprint_from_record(configuration)
    )
    session.add(configuration)
    theme_service._append_audit(
        session,
        action_type="website_configuration_approved",
        actor="Theme Test Operator",
        rationale="Disposable exact Website Theme approval.",
        snapshot=theme_service._website_configuration_fingerprint_payload(configuration),
        website_theme_configuration_id=configuration.id,
    )
    theme_service._append_audit(
        session,
        action_type="website_configuration_activated",
        actor="Theme Test Operator",
        rationale="Disposable exact Website Theme activation.",
        snapshot=theme_service._website_configuration_fingerprint_payload(configuration),
        website_theme_configuration_id=configuration.id,
    )
    for component in _current_components(session).values():
        component.activation_identity = "Theme Test Operator"
        component.activated_at = transitioned_at
        component.updated_by = "Theme Test Operator"
        component.updated_at = transitioned_at
        component.integrity_fingerprint = (
            theme_service._component_fingerprint_from_record(component)
        )
        session.add(component)
        theme_service._append_audit(
            session,
            action_type="component_activated",
            actor="Theme Test Operator",
            rationale="Disposable exact component activation.",
            snapshot=theme_service._component_fingerprint_payload(component),
            component_configuration_id=component.id,
        )
    session.commit()
    return configuration, version, generated, planned, theme, selection


def test_atomic_bundle_is_inactive_audited_provider_disabled_and_export_blocked(
    session: Session,
) -> None:
    website = _website(session, "Primary")

    preview = create_inactive_theme_draft_bundle(
        session,
        website.id,
        _bundle_payload(),
    )

    components = _current_components(session)
    form = components["estimate-form-default"]
    assert preview.preview_label == "DRAFT PREVIEW — NOT ACTIVE"
    assert preview.theme_family.family_key == "performance-local"
    assert preview.theme_version.version == 2
    assert preview.theme_version.production_ready is False
    assert preview.website_configuration.lifecycle_status == "draft"
    assert preview.provider_state.model_dump() == {
        "submission_state": "disabled_pending_provider_configuration",
        "provider_key": None,
        "destination": None,
        "can_submit": False,
        "collects_data": False,
    }
    assert preview.privacy_status == "blocked_pending_privacy_configuration"
    assert preview.readiness.can_activate is False
    assert preview.export_eligible is False
    assert preview.governed_actions.call_destination == "tel:4075550100"
    assert preview.governed_actions.desktop_header_actions_enabled is True
    assert preview.governed_actions.mobile_sticky_actions_enabled is True
    assert (
        preview.governed_actions.desktop_header_estimate_destination_component_configuration_id
        == form.id
    )
    assert (
        preview.governed_actions.mobile_sticky_estimate_destination_component_configuration_id
        == form.id
    )
    assert preview.governed_actions.estimate_destination_component_configuration_id == form.id
    assert len(session.exec(select(ThemeFamily)).all()) == 1
    assert len(session.exec(select(ThemeFamilyVersion)).all()) == 1
    assert len(session.exec(select(WebsiteThemeConfiguration)).all()) == 1
    assert len(session.exec(select(WebsiteThemeComponentConfiguration)).all()) == 3
    assert len(session.exec(select(ThemeConfigurationAudit)).all()) == 6
    assert session.exec(select(Theme)).all() == []
    assert session.exec(select(WebsiteThemeSelection)).all() == []
    assert session.exec(select(PageComposition)).all() == []
    assert validate_theme_configuration_records(session) == {
        "theme_families": 1,
        "theme_family_versions": 1,
        "website_theme_configurations": 1,
        "website_theme_component_configurations": 3,
        "theme_configuration_audits": 6,
    }
    with pytest.raises(ThemeConfigurationError, match="not eligible for public export"):
        require_theme_configuration_export_eligible(
            session,
            website.id,
            preview.website_configuration.id,
            generated_page_id=1,
        )


def test_family_version_lineage_rejects_successor_before_predecessor_transition(
    session: Session,
) -> None:
    family = register_theme_family(
        session,
        ThemeFamilyCreate(
            family_key="chronology-family",
            display_name="Chronology Family",
            description="Disposable lineage chronology fixture.",
            provider_source_identity="test-only",
            created_by="Theme Test Operator",
        ),
    )
    contracts = list(PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS)
    predecessor_contracts = [
        {**deepcopy(item), "contract_version": 1} for item in contracts
    ]
    predecessor = register_theme_family_version(
        session,
        family.id,
        ThemeFamilyVersionCreate(
            version=1,
            source_commit="a" * 40,
            supported_component_contracts=predecessor_contracts,
            created_by="Theme Test Operator",
        ),
    )
    successor = register_theme_family_version(
        session,
        family.id,
        ThemeFamilyVersionCreate(
            version=2,
            source_commit="b" * 40,
            supported_component_contracts=contracts,
            created_by="Theme Test Operator",
            supersedes_theme_family_version_id=predecessor.id,
        ),
    )
    predecessor.updated_at = successor.created_at + timedelta(days=1)
    predecessor.integrity_fingerprint = (
        theme_service._family_version_fingerprint_from_record(predecessor)
    )
    session.add(predecessor)
    session.commit()

    with pytest.raises(ThemeConfigurationError, match="predates predecessor transition"):
        theme_service._validate_family_version(session, successor)


def test_atomic_bundle_rolls_back_every_row_when_third_component_fails(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website = _website(session, "Rollback")
    original = theme_service.create_component_configuration
    calls = 0

    def fail_on_third(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ThemeConfigurationError("Injected invalid third component")
        return original(*args, **kwargs)

    monkeypatch.setattr(theme_service, "create_component_configuration", fail_on_third)

    with pytest.raises(ThemeConfigurationError, match="invalid third component"):
        create_inactive_theme_draft_bundle(session, website.id, _bundle_payload())

    assert calls == 3
    assert session.exec(select(ThemeFamily)).all() == []
    assert session.exec(select(ThemeFamilyVersion)).all() == []
    assert session.exec(select(WebsiteThemeConfiguration)).all() == []
    assert session.exec(select(WebsiteThemeComponentConfiguration)).all() == []
    assert session.exec(select(ThemeConfigurationAudit)).all() == []


def test_missing_required_audit_blocks_preview_and_post_restore_validation(
    session: Session,
) -> None:
    website = _website(session, "Audit")
    preview = create_inactive_theme_draft_bundle(
        session,
        website.id,
        _bundle_payload(),
    )
    component = _current_components(session)["campaign-default"]
    audit = session.exec(
        select(ThemeConfigurationAudit).where(
            ThemeConfigurationAudit.component_configuration_id == component.id,
            ThemeConfigurationAudit.action_type == "component_created",
        )
    ).one()
    session.delete(audit)
    session.commit()

    with pytest.raises(ThemeConfigurationError, match="required immutable audit"):
        read_theme_draft_preview(
            session,
            website.id,
            preview.website_configuration.id,
        )
    with pytest.raises(ThemeConfigurationError, match="required immutable audit"):
        validate_theme_configuration_records(session)


def test_audit_created_at_is_hashed_and_transition_chronology_fails_closed(
    session: Session,
) -> None:
    website = _website(session, "AuditChronology")
    preview = create_inactive_theme_draft_bundle(session, website.id, _bundle_payload())
    component = _current_components(session)["campaign-default"]
    audit = session.exec(
        select(ThemeConfigurationAudit).where(
            ThemeConfigurationAudit.component_configuration_id == component.id,
            ThemeConfigurationAudit.action_type == "component_created",
        )
    ).one()
    audit.created_at = component.created_at - timedelta(seconds=1)
    audit.snapshot_hash = theme_service.canonical_json_hash(
        {
            "theme_family_id": audit.theme_family_id,
            "theme_family_version_id": audit.theme_family_version_id,
            "website_theme_configuration_id": audit.website_theme_configuration_id,
            "component_configuration_id": audit.component_configuration_id,
            "action_type": audit.action_type,
            "actor": audit.actor,
            "rationale": audit.rationale,
            "snapshot": audit.snapshot,
            "created_at": theme_service._datetime_value(audit.created_at),
        }
    )
    session.add(audit)
    session.commit()

    with pytest.raises(ThemeConfigurationError, match="chronology precedes"):
        read_theme_draft_preview(
            session,
            website.id,
            preview.website_configuration.id,
        )


def test_website_configuration_supersession_audits_exact_predecessor(
    session: Session,
) -> None:
    website = _website(session, "ConfigurationRevision")
    preview = create_inactive_theme_draft_bundle(session, website.id, _bundle_payload())
    predecessor = session.get(
        WebsiteThemeConfiguration,
        preview.website_configuration.id,
    )
    assert predecessor is not None

    successor = theme_service.create_website_theme_configuration(
        session,
        website.id,
        WebsiteThemeConfigurationCreate(
            theme_family_version_id=predecessor.theme_family_version_id,
            configuration_key=predecessor.configuration_key,
            created_by="Theme Lab Operator",
            creation_rationale="Create an exact inactive configuration successor.",
            supersedes_configuration_id=predecessor.id,
        ),
    )
    session.refresh(predecessor)

    assert predecessor.lifecycle_status == "superseded"
    assert successor.supersedes_configuration_id == predecessor.id
    transition = session.exec(
        select(ThemeConfigurationAudit).where(
            ThemeConfigurationAudit.website_theme_configuration_id == predecessor.id,
            ThemeConfigurationAudit.action_type == "website_configuration_superseded",
        )
    ).one()
    creation = session.exec(
        select(ThemeConfigurationAudit).where(
            ThemeConfigurationAudit.website_theme_configuration_id == successor.id,
            ThemeConfigurationAudit.action_type
            == "website_configuration_revision_created",
        )
    ).one()
    assert transition.website_theme_configuration_id == predecessor.id
    assert creation.website_theme_configuration_id == successor.id
    assert validate_theme_configuration_records(session)[
        "website_theme_configurations"
    ] == 2


def test_page_override_replaces_one_exact_instance_without_cross_page_leak(
    session: Session,
) -> None:
    website = _website(session, "Override")
    base_preview = create_inactive_theme_draft_bundle(
        session,
        website.id,
        _bundle_payload(),
    )
    configuration_id = base_preview.website_configuration.id
    components = _current_components(session)
    form = components["estimate-form-default"]
    first_campaign = components["campaign-default"]
    campaign_contract = _contract("campaign_banner")
    second_campaign = create_component_configuration(
        session,
        website.id,
        configuration_id,
        WebsiteThemeComponentConfigurationCreate(
            component_instance_key="campaign-secondary",
            component_key="campaign_banner",
            component_contract_version=2,
            scope_type="website_default",
            enabled=False,
            variant=campaign_contract["variant"],
            placement=campaign_contract["placement"],
            responsive_visibility=campaign_contract["responsive_visibility"],
            configuration_payload={
                "intent": "evergreen_conversion",
                "message": "Contact the team to discuss service options.",
                "cta_label": "Contact the team",
                "approval_identity": "Theme Lab Operator",
            },
            approval_identity="Theme Lab Operator",
            created_by="Theme Lab Operator",
            destination_component_configuration_id=form.id,
        ),
    )
    generated_one = GeneratedPage(
        business_id=website.business_id,
        website_id=website.id,
        page_type="informational",
        page_title="Page One",
        page_slug="page-one",
    )
    generated_two = GeneratedPage(
        business_id=website.business_id,
        website_id=website.id,
        page_type="informational",
        page_title="Page Two",
        page_slug="page-two",
    )
    session.add(generated_one)
    session.add(generated_two)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name="Primary",
    )
    session.add(plan)
    session.flush()
    page_one = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="informational",
        working_name="Page One",
        intended_slug="page-one",
        generated_page_id=generated_one.id,
    )
    page_two = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="informational",
        working_name="Page Two",
        intended_slug="page-two",
        generated_page_id=generated_two.id,
    )
    session.add(page_one)
    session.add(page_two)
    session.commit()
    session.refresh(page_one)
    session.refresh(page_two)
    override = create_component_configuration(
        session,
        website.id,
        configuration_id,
        WebsiteThemeComponentConfigurationCreate(
            component_instance_key="campaign-page-one",
            component_key="campaign_banner",
            component_contract_version=2,
            scope_type="page_override",
            planned_page_id=page_one.id,
            enabled=True,
            variant=campaign_contract["variant"],
            placement=campaign_contract["placement"],
            responsive_visibility=campaign_contract["responsive_visibility"],
            configuration_payload={
                "intent": "evergreen_conversion",
                "message": "Request information about this page.",
                "cta_label": "Request information",
                "approval_identity": "Theme Lab Operator",
            },
            approval_identity="Theme Lab Operator",
            created_by="Theme Lab Operator",
            destination_component_configuration_id=form.id,
            overrides_component_configuration_id=first_campaign.id,
        ),
    )

    first = read_theme_draft_preview(
        session,
        website.id,
        configuration_id,
        page_id=generated_one.id,
    )
    second = read_theme_draft_preview(
        session,
        website.id,
        configuration_id,
        page_id=generated_two.id,
    )
    first_ids = {item.id for item in first.components}
    second_ids = {item.id for item in second.components}
    assert override.id in first_ids
    assert first_campaign.id not in first_ids
    assert second_campaign.id in first_ids
    assert override.id not in second_ids
    assert first_campaign.id in second_ids
    assert second_campaign.id in second_ids


def test_website_scope_blocks_cross_website_read_create_and_revision(
    session: Session,
) -> None:
    first = _website(session, "ScopeOne")
    second = _website(session, "ScopeTwo")
    preview = create_inactive_theme_draft_bundle(
        session,
        first.id,
        _bundle_payload(),
    )
    components = _current_components(session)
    campaign = components["campaign-default"]
    form = components["estimate-form-default"]
    contract = _contract("campaign_banner")

    assert list_website_theme_configurations(session, second.id) == []
    with pytest.raises(ThemeConfigurationError, match="Website boundary"):
        read_theme_draft_preview(
            session,
            second.id,
            preview.website_configuration.id,
        )
    with pytest.raises(ThemeConfigurationError, match="Website boundary"):
        create_component_configuration(
            session,
            second.id,
            preview.website_configuration.id,
            WebsiteThemeComponentConfigurationCreate(
                component_instance_key="cross-website-campaign",
                component_key="campaign_banner",
                component_contract_version=2,
                scope_type="website_default",
                enabled=True,
                variant=contract["variant"],
                placement=contract["placement"],
                responsive_visibility=contract["responsive_visibility"],
                configuration_payload={
                    "intent": "evergreen_conversion",
                    "message": "Request information.",
                    "cta_label": "Request information",
                    "approval_identity": "Theme Lab Operator",
                },
                approval_identity="Theme Lab Operator",
                created_by="Theme Lab Operator",
                destination_component_configuration_id=form.id,
            ),
        )
    with pytest.raises(ThemeConfigurationError, match="Website boundary"):
        revise_component_configuration(
            session,
            second.id,
            preview.website_configuration.id,
            campaign.id,
            WebsiteThemeComponentConfigurationRevisionCreate(
                enabled=True,
                variant=contract["variant"],
                placement=contract["placement"],
                responsive_visibility=contract["responsive_visibility"],
                configuration_payload={
                    "intent": "evergreen_conversion",
                    "message": "Request updated information.",
                    "cta_label": "Request information",
                    "approval_identity": "Theme Lab Operator",
                },
                approval_identity="Theme Lab Operator",
                updated_by="Theme Lab Operator",
                revision_rationale="Invalid cross-Website revision attempt.",
                destination_component_configuration_id=form.id,
            ),
        )


def test_component_revision_preserves_prior_evidence_and_appends_lineage(
    session: Session,
) -> None:
    website = _website(session, "Revision")
    preview = create_inactive_theme_draft_bundle(
        session,
        website.id,
        _bundle_payload(),
    )
    components = _current_components(session)
    current = components["campaign-default"]
    form = components["estimate-form-default"]
    contract = _contract("campaign_banner")
    original_payload = deepcopy(current.configuration_payload)
    original_fingerprint = current.integrity_fingerprint
    creation_audit = session.exec(
        select(ThemeConfigurationAudit).where(
            ThemeConfigurationAudit.component_configuration_id == current.id,
            ThemeConfigurationAudit.action_type == "component_created",
        )
    ).one()
    assert theme_service.canonical_json_hash(creation_audit.snapshot) == original_fingerprint

    replacement = revise_component_configuration(
        session,
        website.id,
        preview.website_configuration.id,
        current.id,
        WebsiteThemeComponentConfigurationRevisionCreate(
            enabled=True,
            variant=contract["variant"],
            placement=contract["placement"],
            responsive_visibility=contract["responsive_visibility"],
            configuration_payload={
                "intent": "evergreen_conversion",
                "message": "Contact the team for an estimate.",
                "cta_label": "Contact the team",
                "approval_identity": "Theme Lab Operator",
            },
            approval_identity="Theme Lab Operator",
            updated_by="Theme Lab Operator",
            revision_rationale="Replace the inactive draft campaign decision.",
            destination_component_configuration_id=form.id,
        ),
    )
    session.refresh(current)
    session.refresh(creation_audit)

    assert current.revision == 1
    assert current.lifecycle_status == "superseded"
    assert current.configuration_payload == original_payload
    assert theme_service.canonical_json_hash(creation_audit.snapshot) == original_fingerprint
    assert replacement.revision == 2
    assert replacement.lifecycle_status == "current"
    assert replacement.supersedes_component_configuration_id == current.id
    assert replacement.configuration_payload != original_payload
    predecessor_audit = session.exec(
        select(ThemeConfigurationAudit).where(
            ThemeConfigurationAudit.component_configuration_id == current.id,
            ThemeConfigurationAudit.action_type == "component_superseded",
        )
    ).one()
    revision_audit = session.exec(
        select(ThemeConfigurationAudit).where(
            ThemeConfigurationAudit.component_configuration_id == replacement.id,
            ThemeConfigurationAudit.action_type == "component_revision_created",
        )
    ).one()
    assert predecessor_audit.actor == "Theme Lab Operator"
    assert revision_audit.actor == "Theme Lab Operator"
    assert validate_theme_configuration_records(session)[
        "website_theme_component_configurations"
    ] == 4


def test_live_read_fails_closed_after_integrity_tamper(session: Session) -> None:
    website = _website(session, "Tamper")
    preview = create_inactive_theme_draft_bundle(
        session,
        website.id,
        _bundle_payload(),
    )
    campaign = _current_components(session)["campaign-default"]
    campaign.configuration_payload = {
        **campaign.configuration_payload,
        "message": "Tampered but structurally valid text.",
    }
    session.add(campaign)
    session.commit()

    with pytest.raises(ThemeConfigurationError, match="fingerprint does not match"):
        read_theme_draft_preview(
            session,
            website.id,
            preview.website_configuration.id,
        )


def test_recursive_secret_rejection_and_typed_campaign_validation() -> None:
    bad_form = _form_payload()
    bad_form["fields"][0]["nested"] = [{"apiKey": "must-not-be-read"}]
    with pytest.raises(ValueError, match="credentials or secrets"):
        validate_component_payload("compact_estimate_form", bad_form)

    bad_form = _form_payload()
    bad_form["fields"][0]["nested"] = [{"accessToken": "must-not-be-read"}]
    with pytest.raises(ValueError, match="credentials or secrets"):
        validate_component_payload("compact_estimate_form", bad_form)

    with pytest.raises(ValueError, match="promotional or unsupported"):
        validate_component_payload(
            "campaign_banner",
            {
                "intent": "evergreen_conversion",
                "message": "Limited-time special price",
                "cta_label": "Get an estimate",
                "approval_identity": "Theme Lab Operator",
            },
        )
    for unsafe_copy in (
        "$99 today",
        "Request service today",
        "Request service now",
        "Save $20 today",
        "Act now for service",
        "Get 10% off",
        "Get 50 off",
        "Half off service",
        "Save fifty dollars",
        "Free service",
        "Complimentary service",
        "No-cost service",
    ):
        with pytest.raises(ValueError, match="promotional or unsupported"):
            validate_component_payload(
                "campaign_banner",
                {
                    "intent": "evergreen_conversion",
                    "message": unsafe_copy,
                    "cta_label": "Get an estimate",
                    "approval_identity": "Theme Lab Operator",
                },
            )
    with pytest.raises(ValueError, match="end time must be after"):
        validate_component_payload(
            "campaign_banner",
            {
                "intent": "time_bound_campaign",
                "message": "Approved campaign",
                "cta_label": "Review details",
                "approved_offer_details": "Approved details",
                "terms_reference": "Approved terms record",
                "start_at": "2026-08-14T12:00:00Z",
                "end_at": "2026-08-13T12:00:00Z",
                "approval_identity": "Theme Lab Operator",
            },
        )

    contract = _contract("campaign_banner")
    base = {
        "component_instance_key": "campaign-schedule",
        "component_key": "campaign_banner",
        "component_contract_version": 2,
        "scope_type": "website_default",
        "enabled": True,
        "variant": contract["variant"],
        "placement": contract["placement"],
        "responsive_visibility": contract["responsive_visibility"],
        "approval_identity": "Theme Lab Operator",
        "created_by": "Theme Lab Operator",
        "destination_component_configuration_id": 1,
    }
    with pytest.raises(ValueError, match="Evergreen conversion.*effective dates"):
        WebsiteThemeComponentConfigurationCreate.model_validate(
            {
                **base,
                "configuration_payload": {
                    "intent": "evergreen_conversion",
                    "message": "Request a service estimate.",
                    "cta_label": "Get an estimate",
                    "approval_identity": "Theme Lab Operator",
                },
                "effective_at": "2026-08-14T12:00:00Z",
                "expires_at": None,
            }
        )
    time_bound = {
        "intent": "time_bound_campaign",
        "message": "Approved campaign",
        "cta_label": "Review details",
        "approved_offer_details": "Approved details",
        "terms_reference": "Approved terms record",
        "start_at": "2026-08-14T12:00:00Z",
        "end_at": "2026-08-15T12:00:00Z",
        "approval_identity": "Theme Lab Operator",
    }
    with pytest.raises(ValueError, match="requires exact effective and expiration"):
        WebsiteThemeComponentConfigurationCreate.model_validate(
            {**base, "configuration_payload": time_bound}
        )
    with pytest.raises(ValueError, match="must match its approved payload"):
        WebsiteThemeComponentConfigurationCreate.model_validate(
            {
                **base,
                "configuration_payload": time_bound,
                "effective_at": "2026-08-14T13:00:00Z",
                "expires_at": "2026-08-15T12:00:00Z",
            }
        )
    now = datetime.now(UTC)
    valid_time_bound = WebsiteThemeComponentConfigurationCreate.model_validate(
        {
            **base,
            "configuration_payload": {
                **time_bound,
                "start_at": now - timedelta(hours=1),
                "end_at": now + timedelta(hours=1),
            },
            "effective_at": now - timedelta(hours=1),
            "expires_at": now + timedelta(hours=1),
        }
    )
    assert valid_time_bound.configuration_payload["intent"] == "time_bound_campaign"


def test_expired_time_bound_campaign_is_hidden_without_blocking_preview(
    session: Session,
) -> None:
    website = _website(session, "Expired")
    base_preview = create_inactive_theme_draft_bundle(
        session,
        website.id,
        _bundle_payload(),
    )
    components = _current_components(session)
    form = components["estimate-form-default"]
    contract = _contract("campaign_banner")
    start = datetime.now(UTC) - timedelta(days=2)
    end = datetime.now(UTC) - timedelta(days=1)
    expired = create_component_configuration(
        session,
        website.id,
        base_preview.website_configuration.id,
        WebsiteThemeComponentConfigurationCreate(
            component_instance_key="campaign-expired",
            component_key="campaign_banner",
            component_contract_version=2,
            scope_type="website_default",
            enabled=True,
            variant=contract["variant"],
            placement=contract["placement"],
            responsive_visibility=contract["responsive_visibility"],
            configuration_payload={
                "intent": "time_bound_campaign",
                "message": "Approved campaign",
                "cta_label": "Review details",
                "approved_offer_details": "Approved details",
                "terms_reference": "Approved terms record",
                "start_at": start,
                "end_at": end,
                "approval_identity": "Theme Lab Operator",
            },
            effective_at=start,
            expires_at=end,
            approval_identity="Theme Lab Operator",
            created_by="Theme Lab Operator",
            destination_component_configuration_id=form.id,
        ),
    )

    preview = read_theme_draft_preview(
        session,
        website.id,
        base_preview.website_configuration.id,
    )
    assert expired.id not in {item.id for item in preview.components}
    assert "campaign-default" in {
        item.component_instance_key for item in preview.components
    }


@pytest.mark.parametrize(
    ("component_key", "message"),
    (
        ("compact_estimate_form", "exactly one enabled compact estimate form"),
        ("sticky_mobile_action_bar", "exactly one enabled sticky conversion-action policy"),
        ("campaign_banner", "at most one enabled effective campaign banner"),
    ),
)
@pytest.mark.parametrize("consumer", ("preview", "export"))
def test_page_scoped_conversion_graph_rejects_duplicate_enabled_singletons(
    session: Session,
    component_key: str,
    message: str,
    consumer: str,
) -> None:
    website = _website(session, f"Singleton-{consumer}-{component_key}")
    preview = create_inactive_theme_draft_bundle(
        session,
        website.id,
        _bundle_payload(),
    )
    configuration = session.get(
        WebsiteThemeConfiguration,
        preview.website_configuration.id,
    )
    assert configuration is not None
    _add_duplicate_enabled_component(
        session,
        website,
        configuration,
        component_key,
    )

    if consumer == "preview":
        with pytest.raises(ThemeConfigurationError, match=message):
            read_theme_draft_preview(session, website.id, configuration.id)
        return

    configuration, _version, generated, _planned, _theme, _selection = (
        _activate_export_graph(session, website, configuration.id)
    )
    with pytest.raises(ThemeConfigurationError, match=message):
        require_theme_configuration_export_eligible(
            session,
            website.id,
            configuration.id,
            generated_page_id=generated.id,
        )


def test_live_validation_rejects_rehashed_source_and_lifecycle_tampering(
    session: Session,
) -> None:
    website = _website(session, "Live-Tamper")
    preview = create_inactive_theme_draft_bundle(session, website.id, _bundle_payload())
    version = session.get(ThemeFamilyVersion, preview.theme_version.id)
    configuration = session.get(
        WebsiteThemeConfiguration,
        preview.website_configuration.id,
    )
    assert version is not None
    assert configuration is not None

    version.source_commit = "f" * 40
    version.integrity_fingerprint = theme_service._family_version_fingerprint_from_record(
        version
    )
    session.add(version)
    session.commit()
    with pytest.raises(ThemeConfigurationError, match="exact canonical source commit"):
        read_theme_draft_preview(session, website.id, configuration.id)

    version.source_commit = theme_service.PERFORMANCE_LOCAL_V2_SOURCE_COMMIT
    version.integrity_fingerprint = theme_service._family_version_fingerprint_from_record(
        version
    )
    tampered_at = datetime.now(UTC)
    configuration.rollback_by = "Forged Operator"
    configuration.rollback_at = tampered_at
    configuration.integrity_fingerprint = (
        theme_service._website_configuration_fingerprint_from_record(configuration)
    )
    session.add(version)
    session.add(configuration)
    session.commit()
    with pytest.raises(ThemeConfigurationError, match="later lifecycle evidence"):
        read_theme_draft_preview(session, website.id, configuration.id)


def test_live_validation_rejects_rehashed_out_of_order_approval(
    session: Session,
) -> None:
    website = _website(session, "Chronology-Tamper")
    preview = create_inactive_theme_draft_bundle(session, website.id, _bundle_payload())
    configuration = session.get(
        WebsiteThemeConfiguration,
        preview.website_configuration.id,
    )
    assert configuration is not None
    configuration.lifecycle_status = "approved"
    configuration.approved_by = "Forged Operator"
    configuration.approved_at = configuration.created_at - timedelta(days=1)
    configuration.integrity_fingerprint = (
        theme_service._website_configuration_fingerprint_from_record(configuration)
    )
    session.add(configuration)
    session.commit()
    with pytest.raises(ThemeConfigurationError, match="approval precedes its creation"):
        theme_service._validate_website_configuration(session, configuration)


def test_live_validation_rejects_rehashed_blank_updater_and_controlled_audit_actor(
    session: Session,
) -> None:
    website = _website(session, "Stored-Text-Tamper")
    preview = create_inactive_theme_draft_bundle(session, website.id, _bundle_payload())
    configuration = session.get(
        WebsiteThemeConfiguration,
        preview.website_configuration.id,
    )
    assert configuration is not None
    configuration.updated_by = " "
    configuration.integrity_fingerprint = (
        theme_service._website_configuration_fingerprint_from_record(configuration)
    )
    session.add(configuration)
    session.commit()
    with pytest.raises(ThemeConfigurationError, match="configuration updater"):
        theme_service._validate_website_configuration(session, configuration)

    audit = session.exec(select(ThemeConfigurationAudit).order_by(ThemeConfigurationAudit.id)).first()
    assert audit is not None
    audit.actor = "Forged\nActor"
    audit.snapshot_hash = theme_service.canonical_json_hash(
        {
            "theme_family_id": audit.theme_family_id,
            "theme_family_version_id": audit.theme_family_version_id,
            "website_theme_configuration_id": audit.website_theme_configuration_id,
            "component_configuration_id": audit.component_configuration_id,
            "action_type": audit.action_type,
            "actor": audit.actor,
            "rationale": audit.rationale,
            "snapshot": audit.snapshot,
            "created_at": theme_service._datetime_value(audit.created_at),
        }
    )
    session.add(audit)
    session.commit()
    with pytest.raises(ThemeConfigurationError, match="audit actor"):
        theme_service._validate_audit(audit)


def test_live_validation_rejects_rehashed_family_and_version_creator_tampering(
    session: Session,
) -> None:
    website = _website(session, "Creator-Tamper")
    preview = create_inactive_theme_draft_bundle(session, website.id, _bundle_payload())
    family = session.get(ThemeFamily, preview.theme_family.id)
    version = session.get(ThemeFamilyVersion, preview.theme_version.id)
    assert family is not None
    assert version is not None

    family.created_by = " "
    family.integrity_fingerprint = theme_service._family_fingerprint_from_record(family)
    with pytest.raises(ThemeConfigurationError, match="Theme Family creator"):
        theme_service._validate_family(family)

    family.created_by = "Theme Lab Operator"
    family.integrity_fingerprint = theme_service._family_fingerprint_from_record(family)
    version.created_by = "Forged\nOperator"
    version.integrity_fingerprint = theme_service._family_version_fingerprint_from_record(
        version
    )
    with pytest.raises(ThemeConfigurationError, match="Theme Version creator"):
        theme_service._validate_family_version(session, version)


def test_live_validation_rejects_rehashed_invalid_stable_creation_fields(
    session: Session,
) -> None:
    website = _website(session, "Stable-Field-Tamper")
    preview = create_inactive_theme_draft_bundle(session, website.id, _bundle_payload())
    family = session.get(ThemeFamily, preview.theme_family.id)
    configuration = session.get(
        WebsiteThemeConfiguration,
        preview.website_configuration.id,
    )
    assert family is not None
    assert configuration is not None

    family.display_name = "Forged\nFamily"
    family.integrity_fingerprint = theme_service._family_fingerprint_from_record(family)
    with pytest.raises(ThemeConfigurationError, match="immutable creation identity"):
        theme_service._validate_family(family)

    family.display_name = "Performance Local"
    family.integrity_fingerprint = theme_service._family_fingerprint_from_record(family)
    configuration.configuration_key = "INVALID KEY"
    configuration.integrity_fingerprint = (
        theme_service._website_configuration_fingerprint_from_record(configuration)
    )
    with pytest.raises(ThemeConfigurationError, match="immutable creation identity"):
        theme_service._validate_website_configuration(session, configuration)


def test_canonical_performance_local_contract_is_one_exact_serialized_source() -> None:
    path = Path(__file__).parents[1] / "app" / "schemas" / "performance_local_v2_contract.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == list(PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS)
    assert len(raw) == 23
    assert next(item for item in raw if item["component_key"] == "campaign_banner")[
        "required_configuration"
    ][-7:] == [
        "campaign_label",
        "cta_label",
        "cta_destination",
        "start_date",
        "end_date",
        "terms_reference",
        "approval_identity",
    ]


def test_production_form_preflight_is_complete_but_never_delivers() -> None:
    missing_provider = production_form_submission_readiness(
        ProductionFormSubmissionPreflightInput()
    )
    assert missing_provider.can_submit is False
    assert missing_provider.delivery_attempted is False
    assert "missing_provider" in {item.code for item in missing_provider.blockers}

    missing_privacy = production_form_submission_readiness(
        ProductionFormSubmissionPreflightInput(
            provider_key="approved-provider",
            destination="governed-destination",
        )
    )
    assert "missing_privacy_policy_destination" in {
        item.code for item in missing_privacy.blockers
    }

    missing_consent = production_form_submission_readiness(
        ProductionFormSubmissionPreflightInput(
            provider_key="approved-provider",
            destination="governed-destination",
            privacy_policy_destination="/privacy/",
            consent_required=True,
        )
    )
    assert "missing_consent_language" in {item.code for item in missing_consent.blockers}

    complete = production_form_submission_readiness(
        ProductionFormSubmissionPreflightInput(
            provider_key="approved-provider",
            destination="governed-destination",
            privacy_policy_destination="/privacy/",
            consent_required=True,
            consent_language="I agree to the approved contact terms.",
            data_retention_policy="Approved retention policy identity.",
            spam_strategy="Approved abuse-control strategy identity.",
            success_behavior="Show the approved local success state.",
            failure_behavior="Show the approved local failure state.",
            audit_identity="Approved submission audit contract.",
            secret_handling_policy="external_secret_manager_reference_only",
        )
    )
    assert complete.contract_complete is True
    assert complete.contract is not None
    assert complete.contract.provider_key == "approved-provider"
    assert [item.code for item in complete.blockers] == [
        "provider_adapter_unavailable"
    ]
    assert complete.provider_adapter_registered is False
    assert complete.can_submit is False
    assert complete.delivery_attempted is False


def test_export_guard_returns_exact_page_scoped_typed_identity(
    session: Session,
) -> None:
    website = _website(session, "Export")
    preview = create_inactive_theme_draft_bundle(session, website.id, _bundle_payload())
    configuration, _version, generated, planned, _theme, _selection = (
        _activate_export_graph(
            session,
            website,
            preview.website_configuration.id,
        )
    )

    identity = require_theme_configuration_export_eligible(
        session,
        website.id,
        configuration.id,
        generated_page_id=generated.id,
    )
    assert identity.website_id == website.id
    assert identity.generated_page_id == generated.id
    assert identity.planned_page_id == planned.id
    assert identity.configuration_lifecycle_status == "active"
    assert identity.family_version == 2
    assert _theme.version == 1
    assert len(identity.effective_components) == 3
    assert {
        item.component_configuration_id for item in identity.effective_components
    } == {
        item.id for item in _current_components(session).values()
    }
    assert identity.audit_snapshot_hashes == sorted(identity.audit_snapshot_hashes)
    assert len(identity.audit_snapshot_hashes) == 12


@pytest.mark.parametrize(
    "mismatch",
    ("business", "brand", "family_key", "selection_theme"),
)
def test_export_guard_rejects_exact_materialized_theme_binding_mismatch(
    session: Session,
    mismatch: str,
) -> None:
    website = _website(session, f"Binding-{mismatch}")
    preview = create_inactive_theme_draft_bundle(session, website.id, _bundle_payload())
    configuration, _version, generated, _planned, theme, selection = (
        _activate_export_graph(
            session,
            website,
            preview.website_configuration.id,
        )
    )
    if mismatch in {"business", "brand"}:
        other = _website(session, f"Other-{mismatch}")
        if mismatch == "business":
            theme.business_id = other.business_id
        else:
            theme.brand_id = other.brand_id
        session.add(theme)
    elif mismatch == "family_key":
        theme.theme_key = "forged-family"
        session.add(theme)
    else:
        other_theme = Theme(
            website_id=website.id,
            business_id=website.business_id,
            brand_id=website.brand_id,
            theme_key="forged-selection-theme",
            theme_name="Forged Selection Theme",
            version=1,
            token_contract_version=1,
            design_tokens=DEFAULT_THEME_TOKENS.model_dump(mode="json"),
            token_hash_sha256=canonical_token_hash(DEFAULT_THEME_TOKENS),
            lifecycle_status="available",
            approval_status="approved",
            created_by="Theme Test Operator",
            provenance_type="operator_configured",
            provenance_notes="Disposable mismatch Theme.",
            approved_by="Theme Test Operator",
            approved_at=datetime.now(UTC),
        )
        session.add(other_theme)
        session.flush()
        selection.theme_id = other_theme.id
        session.add(selection)
    session.commit()

    with pytest.raises(
        ThemeConfigurationError,
        match="exact governed Theme-selection identity",
    ):
        require_theme_configuration_export_eligible(
            session,
            website.id,
            configuration.id,
            generated_page_id=generated.id,
        )


@pytest.mark.parametrize("tamper", ("missing_activation", "rolled_back"))
def test_export_guard_rejects_enabled_component_without_current_activation(
    session: Session,
    tamper: str,
) -> None:
    website = _website(session, f"Component-{tamper}")
    preview = create_inactive_theme_draft_bundle(session, website.id, _bundle_payload())
    configuration, _version, generated, _planned, _theme, _selection = (
        _activate_export_graph(
            session,
            website,
            preview.website_configuration.id,
        )
    )
    component = _current_components(session)["campaign-default"]
    if tamper == "missing_activation":
        component.activation_identity = None
        component.activated_at = None
    else:
        component.rollback_identity = "Theme Test Operator"
        component.rollback_at = datetime.now(UTC) + timedelta(seconds=1)
    component.integrity_fingerprint = theme_service._component_fingerprint_from_record(
        component
    )
    session.add(component)
    session.commit()

    with pytest.raises(
        ThemeConfigurationError,
        match="every enabled effective Theme component",
    ):
        require_theme_configuration_export_eligible(
            session,
            website.id,
            configuration.id,
            generated_page_id=generated.id,
        )


def test_provider_registry_and_routes_remain_fail_closed(session: Session) -> None:
    website = _website(session, "Routes")
    assert FORM_SUBMISSION_PROVIDERS == {}
    with pytest.raises(FormProviderError, match="disabled pending provider configuration"):
        require_submission_provider(None)

    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        created = client.post(
            f"/api/websites/{website.id}/theme-configurations/draft-bundle",
            json=_bundle_payload().model_dump(mode="json"),
        )
        assert created.status_code == 201, created.text
        configuration_id = created.json()["website_configuration"]["id"]
        response = client.get(
            f"/api/websites/{website.id}/theme-configurations/draft-preview",
            params={
                "family_key": "performance-local",
                "family_version": 2,
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["website_configuration"]["id"] == configuration_id
    assert response.json()["preview_label"] == "DRAFT PREVIEW — NOT ACTIVE"
    durable_paths = {
        route.path
        for route in app.routes
        if "theme-configurations" in route.path
    }
    assert not any(
        forbidden in path
        for path in durable_paths
        for forbidden in ("/activate", "/submit", "/publish", "/deploy")
    )
