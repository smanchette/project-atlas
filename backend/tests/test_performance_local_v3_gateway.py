from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import form_submission_routes, theme_delivery_routes
from app.db import backup as backup_service
from app.db.backup import (
    BackupValidationError,
    export_backup,
    load_backup,
    restore_backup,
)
from app.db.session import get_session
from app.main import app
from app.middleware.form_submission_query_scrub import (
    FormSubmissionQueryScrubMiddleware,
)
from app.models import (
    Brand,
    Business,
    GeneratedPage,
    PageComposition,
    SitePlan,
    PlannedPage,
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
    CompactEstimateFormConfigurationV3,
    ConversionComponentGraphRevisionCreate,
    PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS,
    PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
    PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS,
    PERFORMANCE_LOCAL_V3_CONTRACT_FINGERPRINT,
    ThemeFamilyCreate,
    ThemeFamilyVersionCreate,
    WebsiteThemeComponentConfigurationCreate,
    WebsiteThemeComponentConfigurationRevisionCreate,
    WebsiteThemeConfigurationCreate,
    validate_component_payload,
)
from app.schemas.form_delivery import (
    OptionalFormFieldConfiguration,
    WebsiteFormDeliveryModeRevisionCreate,
)
from app.services import form_submission_gateway as gateway
from app.services.form_delivery_modes import create_form_delivery_mode_revision
from app.services import page_export
from app.services import page_qa as page_qa_service
from app.services.page_composition_history import (
    canonical_payload_hash,
    create_initial_composition_revision,
)
from app.services import theme_activation_rehearsal
from app.services import theme_configurations as theme_service
from app.services import theme_delivery
from app.services.page_export import build_theme_configured_page_export_package
from app.services.themes import DEFAULT_THEME_TOKENS, canonical_token_hash
from app.website_builder_core.contracts import UNIVERSAL_ESTIMATE_FORM_DEFINITION


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


def _gateway_definition_with_sixth(
    *,
    required: bool = False,
    maximum_length: int = 80,
):
    optional = OptionalFormFieldConfiguration.model_validate(
        {
            "field_key": "project_reference",
            "public_label": "Project reference",
            "accessibility_label": "Enter the project reference",
            "field_type": "short_text",
            "required": required,
            "display_order": 6,
            "maximum_length": maximum_length,
            "validation_contract": {
                "rule": "trimmed_text",
                "minimum_length": 1 if required else 0,
            },
            "choices": [],
            "provider_mapping_key": "project_reference",
            "help_text": "Use synthetic information only.",
            "definition_revision_identity": "project_reference_revision_1",
        }
    ).to_core()
    return UNIVERSAL_ESTIMATE_FORM_DEFINITION.with_optional_fields((optional,))


def _form_payload(state: str = "disabled_pending_provider_configuration") -> dict:
    base = {
        "submission_state": state,
        "fields": _fields(),
        "submit_label": "Request an Estimate",
        "preview_notice": "Synthetic test configuration; no external delivery.",
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
    test_only = state == "rehearsal_ready"
    return {
        **base,
        "provider": {
            "provider_key": (
                gateway.SYNTHETIC_PROVIDER_KEY if test_only else "approved-provider"
            ),
            "destination": (
                gateway.SYNTHETIC_PROVIDER_DESTINATION
                if test_only
                else "destination-ref://atlas/estimate-requests"
            ),
            "provider_secret_reference": "secret-ref://atlas/forms/estimate-provider",
            "test_only": test_only,
        },
        "privacy": {
            "policy_destination": (
                "http://localhost/privacy" if test_only else "/privacy-policy"
            ),
            "consent_mode": "not_required",
            "consent_text": None,
            "consent_text_version": None,
        },
        "retention": {
            "duration": "synthetic-policy-duration",
            "deletion_expiration_behavior": "discard-after-synthetic-result",
        },
        "spam": {
            "strategy": "synthetic_test" if test_only else "proof_of_work",
            "configuration_reference": (
                "synthetic-noop"
                if test_only
                else "spam-ref://atlas/forms/approved-abuse-policy"
            ),
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


def _seed_v3(
    session: Session,
    *,
    state: str = "disabled_pending_provider_configuration",
) -> SimpleNamespace:
    business = Business(
        company_name=f"V3 Test {state}",
        business_type="synthetic test",
        state="FL",
        phone="(407) 555-0100",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name=f"V3 Brand {state}",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name=f"V3 Website {state}",
        domain=f"{state.replace('_', '-')}.example.test",
        public_url=f"https://{state.replace('_', '-')}.example.test",
        status="active",
    )
    session.add(website)
    session.commit()

    family = theme_service.register_theme_family(
        session,
        ThemeFamilyCreate(
            family_key="performance-local",
            display_name="Performance Local",
            description="Synthetic V3 contract test family.",
            provider_source_identity="atlas-source:performance-local",
            created_by="V3 Test Operator",
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
            created_by="V3 Test Operator",
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
            created_by="V3 Test Operator",
            supersedes_theme_family_version_id=v2.id,
        ),
    )
    configuration = theme_service.create_website_theme_configuration(
        session,
        website.id,
        WebsiteThemeConfigurationCreate(
            theme_family_version_id=v3.id,
            configuration_key="performance-local-v3",
            created_by="V3 Test Operator",
            creation_rationale="Create a disposable V3 source-contract test draft.",
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
            configuration_payload=_form_payload(state),
            approval_identity="V3 Test Operator",
            created_by="V3 Test Operator",
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
                "approval_identity": "V3 Test Operator",
            },
            approval_identity="V3 Test Operator",
            created_by="V3 Test Operator",
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
            approval_identity="V3 Test Operator",
            created_by="V3 Test Operator",
            destination_component_configuration_id=form.id,
        ),
    )
    page = GeneratedPage(
        business_id=business.id,
        website_id=website.id,
        page_type="home",
        page_title="Synthetic V3 Page",
        page_slug=f"synthetic-v3-{state.replace('_', '-')}",
        status="draft",
    )
    session.add(page)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="v3-test",
        plan_name="V3 Test Plan",
        status="active",
    )
    session.add(plan)
    session.flush()
    planned = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="home",
        working_name="Synthetic V3 Page",
        intended_slug=page.page_slug,
        planning_status="planned",
        generated_page_id=page.id,
    )
    session.add(planned)
    session.commit()
    return SimpleNamespace(
        business=business,
        brand=brand,
        website=website,
        family=family,
        v2=v2,
        v3=v3,
        configuration=configuration,
        form=form,
        banner=banner,
        sticky=sticky,
        page=page,
        planned=planned,
    )


def _activate_production_graph(session: Session, graph: SimpleNamespace) -> None:
    now = datetime.now(UTC)
    graph.v3.lifecycle_status = "approved"
    graph.v3.production_ready = True
    graph.v3.updated_at = now
    graph.v3.integrity_fingerprint = theme_service._family_version_fingerprint_from_record(
        graph.v3
    )
    session.add(graph.v3)
    theme_service._append_audit(
        session,
        action_type="family_version_approved",
        actor="V3 Test Operator",
        rationale="Approve only inside a disposable unit-test database.",
        snapshot=theme_service._family_version_fingerprint_payload(graph.v3),
        theme_family_version_id=graph.v3.id,
    )
    theme = Theme(
        website_id=graph.website.id,
        business_id=graph.website.business_id,
        brand_id=graph.website.brand_id,
        theme_key="performance-local",
        theme_name="Performance Local V3 Test",
        version=1,
        token_contract_version=1,
        design_tokens=DEFAULT_THEME_TOKENS.model_dump(mode="json"),
        token_hash_sha256=canonical_token_hash(DEFAULT_THEME_TOKENS),
        lifecycle_status="available",
        approval_status="approved",
        created_by="V3 Test Operator",
        provenance_type="operator_configured",
        provenance_notes="Disposable V3 gateway test Theme.",
        approved_by="V3 Test Operator",
        approved_at=now,
    )
    session.add(theme)
    session.flush()
    selection = WebsiteThemeSelection(
        website_id=graph.website.id,
        theme_id=theme.id,
        version=1,
        status="active",
        selected_by="V3 Test Operator",
        rationale="Disposable V3 gateway test selection.",
    )
    session.add(selection)
    session.flush()
    configuration = graph.configuration
    configuration.lifecycle_status = "active"
    configuration.approved_by = "V3 Test Operator"
    configuration.approved_at = now
    configuration.activated_by = "V3 Test Operator"
    configuration.activated_at = now
    configuration.materialized_theme_id = theme.id
    configuration.website_theme_selection_id = selection.id
    configuration.updated_by = "V3 Test Operator"
    configuration.updated_at = now
    configuration.integrity_fingerprint = (
        theme_service._website_configuration_fingerprint_from_record(configuration)
    )
    session.add(configuration)
    for action in (
        "website_configuration_approved",
        "website_configuration_activated",
    ):
        theme_service._append_audit(
            session,
            action_type=action,
            actor="V3 Test Operator",
            rationale="Disposable exact V3 gateway lifecycle evidence.",
            snapshot=theme_service._website_configuration_fingerprint_payload(
                configuration
            ),
            website_theme_configuration_id=configuration.id,
        )
    for component in (graph.form, graph.banner, graph.sticky):
        component.activation_identity = "V3 Test Operator"
        component.activated_at = now
        component.updated_by = "V3 Test Operator"
        component.updated_at = now
        component.integrity_fingerprint = theme_service._component_fingerprint_from_record(
            component
        )
        session.add(component)
        theme_service._append_audit(
            session,
            action_type="component_activated",
            actor="V3 Test Operator",
            rationale="Disposable exact V3 component activation evidence.",
            snapshot=theme_service._component_fingerprint_payload(component),
            component_configuration_id=component.id,
        )
    session.commit()


def _activate_rehearsal_graph(session: Session, graph: SimpleNamespace) -> None:
    _activate_production_graph(session, graph)
    graph.v3.lifecycle_status = "preview_candidate"
    graph.v3.production_ready = False
    graph.v3.integrity_fingerprint = theme_service._family_version_fingerprint_from_record(
        graph.v3
    )
    session.add(graph.v3)
    session.commit()


def _raw_request(
    body_chunks: list[bytes],
    *,
    content_type: str = "application/json",
    content_length: int | None = None,
    origin: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[Request, dict[str, int]]:
    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(body_chunks) - 1,
        }
        for index, chunk in enumerate(body_chunks)
    ]
    calls = {"receive": 0}

    async def receive():
        calls["receive"] += 1
        if messages:
            return messages.pop(0)
        return {"type": "http.request", "body": b"", "more_body": False}

    headers = [(b"content-type", content_type.encode())]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    headers.extend(
        (key.lower().encode("ascii"), value.encode("ascii"))
        for key, value in (extra_headers or {}).items()
    )
    return (
        Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/form",
                "query_string": b"",
                "headers": headers,
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
                "scheme": "http",
                "http_version": "1.1",
            },
            receive,
        ),
        calls,
    )


def test_v3_contract_is_distinct_and_v2_canonical_identity_is_unchanged() -> None:
    v2_path = Path(__file__).parents[1] / "app" / "schemas" / "performance_local_v2_contract.json"
    v3_path = Path(__file__).parents[1] / "app" / "schemas" / "performance_local_v3_contract.json"
    v2 = json.loads(v2_path.read_text(encoding="utf-8"))
    v3 = json.loads(v3_path.read_text(encoding="utf-8"))
    canonical_v2 = json.dumps(v2, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    canonical_v3 = json.dumps(v3, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    import hashlib

    assert hashlib.sha256(canonical_v2.encode()).hexdigest() == (
        "0e2ebceb18c53ec8587a9d237326c7d3d91e7c633cb46eaa0d2efcadbaf3ff31"
    )
    assert hashlib.sha256(canonical_v3.encode()).hexdigest() == PERFORMANCE_LOCAL_V3_CONTRACT_FINGERPRINT
    assert len(v2) == len(v3) == 23
    assert all(item["contract_version"] == 2 for item in v2)
    assert all(item["contract_version"] == 3 for item in v3)
    assert next(item for item in v3 if item["component_key"] == "campaign_banner")["variant"] == "single_action_safe_strip"
    assert next(item for item in v3 if item["component_key"] == "compact_estimate_form")["variant"] == "provider_independent_gateway"


@pytest.mark.parametrize(
    ("field", "unsafe"),
    [
        ("destination", "https://user:secret@example.test/hook?token=literal"),
        ("destination", "javascript:alert(1)"),
        ("privacy", "javascript:alert(1)"),
        ("privacy", "https://user:secret@example.test/privacy"),
        ("privacy", "/privacy?submitted=value"),
        ("spam", "captcha-site-key-literal"),
    ],
)
def test_v3_form_rejects_credential_bearing_destination_and_unsafe_privacy(
    field: str,
    unsafe: str,
) -> None:
    payload = _form_payload("production_configured")
    if field == "destination":
        payload["provider"]["destination"] = unsafe
    elif field == "spam":
        payload["spam"]["configuration_reference"] = unsafe
    else:
        payload["privacy"]["policy_destination"] = unsafe
    with pytest.raises(ValidationError):
        CompactEstimateFormConfigurationV3.model_validate(payload)


def test_v3_form_rejects_literal_secret_keys_but_accepts_opaque_reference() -> None:
    payload = _form_payload("production_configured")
    assert validate_component_payload("compact_estimate_form", payload, 3)["provider"][
        "provider_secret_reference"
    ].startswith("secret-ref://")
    payload["provider"]["api_token"] = "literal-secret"
    with pytest.raises(ValueError, match="secret"):
        validate_component_payload("compact_estimate_form", payload, 3)


def test_atomic_v3_conversion_graph_revision_has_one_commit_boundary(
    session: Session,
) -> None:
    graph = _seed_v3(session)
    session.refresh(graph.v2)
    v2_before = graph.v2.model_dump(mode="python")
    audits_before = len(session.exec(select(ThemeConfigurationAudit)).all())
    payload = ConversionComponentGraphRevisionCreate(
        form_component_configuration_id=graph.form.id,
        banner_component_configuration_id=graph.banner.id,
        sticky_component_configuration_id=graph.sticky.id,
        form_revision=WebsiteThemeComponentConfigurationRevisionCreate(
            enabled=True,
            variant=graph.form.variant,
            placement=graph.form.placement,
            responsive_visibility=graph.form.responsive_visibility,
            configuration_payload=_form_payload("rehearsal_ready"),
            approval_identity="V3 Test Operator",
            updated_by="V3 Test Operator",
            revision_rationale="Revise the exact conversion graph atomically.",
        ),
        banner_revision=WebsiteThemeComponentConfigurationRevisionCreate(
            enabled=True,
            variant=graph.banner.variant,
            placement=graph.banner.placement,
            responsive_visibility=graph.banner.responsive_visibility,
            configuration_payload=deepcopy(graph.banner.configuration_payload),
            approval_identity="V3 Test Operator",
            updated_by="V3 Test Operator",
            revision_rationale="Revise the exact conversion graph atomically.",
            destination_component_configuration_id=graph.form.id,
        ),
        sticky_revision=WebsiteThemeComponentConfigurationRevisionCreate(
            enabled=True,
            variant=graph.sticky.variant,
            placement=graph.sticky.placement,
            responsive_visibility=graph.sticky.responsive_visibility,
            configuration_payload=deepcopy(graph.sticky.configuration_payload),
            approval_identity="V3 Test Operator",
            updated_by="V3 Test Operator",
            revision_rationale="Revise the exact conversion graph atomically.",
            destination_component_configuration_id=graph.form.id,
        ),
    )
    revised = theme_service.revise_conversion_component_graph(
        session,
        graph.website.id,
        graph.configuration.id,
        payload,
    )
    assert revised.form.revision == revised.banner.revision == revised.sticky.revision == 2
    assert revised.banner.destination_component_configuration_id == revised.form.id
    assert revised.sticky.destination_component_configuration_id == revised.form.id
    assert len(session.exec(select(ThemeConfigurationAudit)).all()) == audits_before + 6
    assert session.get(ThemeFamilyVersion, graph.v2.id).model_dump(mode="python") == v2_before


def test_disabled_gateway_returns_stable_503_without_entering_body_handler(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_v3(session)
    before_counts = {
        model.__name__: len(session.exec(select(model)).all())
        for model in (
            WebsiteThemeConfiguration,
            WebsiteThemeComponentConfiguration,
            ThemeConfigurationAudit,
        )
    }
    calls = 0

    async def forbidden_body_handler(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("disabled gateway consumed the request body")

    monkeypatch.setattr(
        gateway,
        "_read_bounded_json_body",
        forbidden_body_handler,
    )
    app.dependency_overrides[get_session] = lambda: session
    try:
        response = TestClient(app).post(
            f"/api/websites/{graph.website.id}/forms/{graph.form.id}/submissions?name=do-not-log",
            content=b'{"name":"do-not-reflect-customer-value"}',
            headers={"Content-Type": "application/json"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "form_delivery_mode_not_found",
        "message": "Form submission is not available.",
    }
    assert "do-not-reflect" not in response.text
    assert "do-not-log" not in response.text
    assert calls == 0
    assert gateway.PRODUCTION_SUBMISSION_PROVIDERS == {}
    assert before_counts == {
        model.__name__: len(session.exec(select(model)).all())
        for model in (
            WebsiteThemeConfiguration,
            WebsiteThemeComponentConfiguration,
            ThemeConfigurationAudit,
        )
    }


def test_form_query_is_scrubbed_before_routing_validation_and_method_rejection() -> None:
    observed: list[tuple[bytes, bool, str]] = []

    async def downstream(scope, _receive, send) -> None:
        observed.append(
            (
                scope.get("query_string", b""),
                bool(scope.get("atlas_form_query_was_present")),
                repr(scope),
            )
        )
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = FormSubmissionQueryScrubMiddleware(
        downstream,
        api_prefix="/api",
    )

    async def exercise(path: str, method: str) -> None:
        scope = {
            "type": "http",
            "path": path,
            "method": method,
            "query_string": b"name=Private+Customer",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(_message) -> None:
            return None

        await middleware(scope, receive, send)

    asyncio.run(
        exercise(
            "/api/websites/not-an-int/forms/1/submissions",
            "POST",
        )
    )
    asyncio.run(exercise("/api/websites/1/forms/1/submissions", "GET"))
    assert len(observed) == 2
    assert all(query == b"" and flagged for query, flagged, _scope in observed)
    assert all("Private+Customer" not in scope_text for _, _, scope_text in observed)

    client = TestClient(app)
    invalid = client.post(
        "/api/websites/not-an-int/forms/1/submissions?name=Private+Customer"
    )
    wrong_method = client.get(
        "/api/websites/1/forms/1/submissions?name=Private+Customer"
    )
    assert invalid.status_code == 422
    assert wrong_method.status_code == 405
    assert "Private+Customer" not in invalid.text
    assert "Private+Customer" not in wrong_method.text


def test_disabled_readiness_reports_each_governance_blocker_separately(
    session: Session,
) -> None:
    graph = _seed_v3(session)
    readiness = gateway.evaluate_form_readiness(
        graph.form,
        mode="inactive_draft_preview",
    )
    assert readiness.status == "blocked"
    assert readiness.can_submit is False
    codes = {item.code for item in readiness.blockers}
    assert {
        "submission_disabled",
        "missing_provider",
        "missing_provider_destination",
        "provider_adapter_unavailable",
        "missing_privacy_destination",
        "missing_consent_mode",
        "missing_retention_duration",
        "missing_deletion_behavior",
        "missing_spam_strategy",
        "missing_success_behavior",
        "missing_failure_behavior",
        "missing_secret_reference",
        "missing_same_origin_policy",
        "missing_csrf_policy",
        "missing_request_size_policy",
        "missing_idempotency_strategy",
        "missing_audit_identity",
    } <= codes


@pytest.mark.parametrize(
    ("delivery_mode", "expected_code"),
    (
        ("disabled", "form_submission_disabled"),
        ("atlas_email", "form_delivery_mode_unavailable"),
    ),
)
def test_explicit_website_mode_preempts_unchanged_provider_disabled_v3_gateway(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    delivery_mode: str,
    expected_code: str,
) -> None:
    graph = _seed_v3(session)
    assert graph.form.configuration_payload["submission_state"] == (
        "disabled_pending_provider_configuration"
    )
    now = datetime.now(UTC)
    atlas_email = delivery_mode == "atlas_email"
    create_form_delivery_mode_revision(
        session,
        graph.website.id,
        WebsiteFormDeliveryModeRevisionCreate(
            form_component_configuration_id=graph.form.id,
            form_instance_key=graph.form.component_instance_key,
            lifecycle_status="active",
            mode=delivery_mode,
            enabled=atlas_email,
            provider_key=(gateway.SYNTHETIC_PROVIDER_KEY if atlas_email else None),
            adapter_version=("test-v1" if atlas_email else None),
            destination_identity=(
                "recipient-set-ref://synthetic/recipients" if atlas_email else None
            ),
            configuration_payload=(
                {
                    "transport_key_reference": "synthetic-mail",
                    "transport_secret_reference": "secret-ref://synthetic/mail",
                    "notification_preference": "all_verified",
                    "consent_required": False,
                }
                if atlas_email
                else {}
            ),
            privacy_policy_reference=("/privacy" if atlas_email else None),
            retention_policy_reference=(
                "policy-ref://synthetic/retention" if atlas_email else None
            ),
            abuse_policy_reference=(
                "policy-ref://synthetic/abuse" if atlas_email else None
            ),
            success_behavior=("Show success." if atlas_email else None),
            failure_behavior=("Show failure." if atlas_email else None),
            idempotency_policy_reference=(
                "policy-ref://synthetic/idempotency" if atlas_email else None
            ),
            audit_identity=f"test-explicit-{delivery_mode}",
            approval_identity="test-approval",
            approved_at=now,
            activation_identity="test-activation",
            activated_at=now,
            created_by="test",
            updated_by="test",
            rationale="Prove Website-scoped mode authority over unchanged V3.",
        ),
    )

    def legacy_readiness_must_not_run(*_args, **_kwargs):
        raise AssertionError("legacy V3 readiness must not select an explicit mode")

    monkeypatch.setattr(
        gateway,
        "evaluate_form_readiness",
        legacy_readiness_must_not_run,
    )
    with pytest.raises(gateway.FormGatewayError) as error:
        gateway.preflight_form_gateway(
            session,
            graph.website.id,
            graph.form.id,
        )
    assert error.value.code == expected_code


def test_production_readiness_requires_independent_spam_control_adapter(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_v3(session, state="production_configured")
    monkeypatch.setattr(
        gateway,
        "PRODUCTION_SUBMISSION_PROVIDERS",
        {"approved-provider": object()},
    )
    monkeypatch.setattr(
        gateway,
        "PRODUCTION_IDEMPOTENCY_BOUNDARIES",
        {"required_header": gateway._SyntheticIdempotencyBoundary()},
    )

    class WrongReferenceSpamControl:
        strategy = "proof_of_work"

        def supports_reference(self, configuration_reference: str) -> bool:
            return configuration_reference == "spam-ref://different/form"

        def verify(self, _context, _envelope) -> None:
            raise AssertionError("mismatched spam control must never execute")

    monkeypatch.setattr(
        gateway,
        "PRODUCTION_SPAM_CONTROLS",
        {"proof_of_work": WrongReferenceSpamControl()},
    )

    readiness = gateway.evaluate_form_readiness(
        graph.form,
        mode="active",
        test_environment_allowed=False,
    )
    codes = {item.code for item in readiness.blockers}
    assert readiness.provider_state.adapter_registered is True
    assert readiness.spam.ready is False
    assert readiness.can_submit is False
    assert "spam_adapter_unavailable" in codes
    assert "provider_adapter_unavailable" not in codes
    assert "idempotency_boundary_unavailable" not in codes


def test_loopback_http_privacy_destination_is_rehearsal_only(
    session: Session,
) -> None:
    graph = _seed_v3(session, state="production_configured")
    payload = deepcopy(graph.form.configuration_payload)
    payload["privacy"]["policy_destination"] = "http://localhost/privacy"
    graph.form.configuration_payload = CompactEstimateFormConfigurationV3.model_validate(
        payload
    ).model_dump(mode="json")
    graph.form.integrity_fingerprint = theme_service._component_fingerprint_from_record(
        graph.form
    )

    active = gateway.evaluate_form_readiness(
        graph.form,
        mode="active",
        test_environment_allowed=False,
    )
    rehearsal = gateway.evaluate_form_readiness(
        graph.form,
        mode="activation_rehearsal",
        test_environment_allowed=True,
    )
    assert active.privacy.ready is False
    assert any(
        item.code == "loopback_privacy_destination_forbidden"
        for item in active.blockers
    )
    assert rehearsal.privacy.ready is True
    assert all(
        item.code != "loopback_privacy_destination_forbidden"
        for item in rehearsal.blockers
    )


@pytest.mark.parametrize(
    ("content_type", "body", "declared_length", "limit", "expected_code"),
    [
        ("multipart/form-data; boundary=x", b"file", 4, 4096, "unsupported_content_type"),
        ("text/plain", b"{}", 2, 4096, "unsupported_content_type"),
        ("application/json", b"{}", 4097, 4096, "request_too_large"),
        ("application/json", b'{"name":', 8, 4096, "malformed_json"),
    ],
)
def test_raw_gateway_rejects_content_type_size_and_malformed_json_safely(
    content_type: str,
    body: bytes,
    declared_length: int,
    limit: int,
    expected_code: str,
) -> None:
    request, calls = _raw_request(
        [body],
        content_type=content_type,
        content_length=declared_length,
    )
    with pytest.raises(gateway.FormGatewayError) as failure:
        asyncio.run(gateway._read_bounded_json_body(request, limit))
    assert failure.value.code == expected_code
    assert "name" not in failure.value.safe_message
    if expected_code in {"unsupported_content_type", "request_too_large"}:
        assert calls["receive"] == 0


@pytest.mark.parametrize("content_encoding", ["gzip", "br", "deflate", "gzip, br"])
def test_raw_gateway_rejects_non_identity_content_encoding_before_body_read(
    content_encoding: str,
) -> None:
    request, calls = _raw_request(
        [b'{"name":"must-not-be-read"}'],
        content_length=27,
        extra_headers={"content-encoding": content_encoding},
    )

    with pytest.raises(gateway.FormGatewayError) as failure:
        asyncio.run(gateway._read_bounded_json_body(request, 4096))

    assert failure.value.status_code == 415
    assert failure.value.code == "unsupported_content_encoding"
    assert "must-not-be-read" not in failure.value.safe_message
    assert calls["receive"] == 0


@pytest.mark.parametrize(
    "content_encodings",
    [
        [b"identity", b"gzip"],
        [b"identity", b"identity"],
    ],
)
def test_raw_gateway_rejects_duplicate_content_encoding_headers_before_body_read(
    content_encodings: list[bytes],
) -> None:
    request, calls = _raw_request([b'{"name":"must-not-be-read"}'], content_length=27)
    request.scope["headers"].extend(
        (b"content-encoding", value) for value in content_encodings
    )

    with pytest.raises(gateway.FormGatewayError) as failure:
        asyncio.run(gateway._read_bounded_json_body(request, 4096))

    assert failure.value.status_code == 415
    assert failure.value.code == "unsupported_content_encoding"
    assert "must-not-be-read" not in failure.value.safe_message
    assert calls["receive"] == 0


@pytest.mark.parametrize(
    ("header_name", "header_values", "expected_code"),
    [
        ("content-type", [b"application/json", b"text/plain"], "unsupported_content_type"),
        ("content-length", [b"27", b"4096"], "invalid_content_length"),
    ],
)
def test_raw_gateway_rejects_ambiguous_duplicate_entity_headers_before_body_read(
    header_name: str,
    header_values: list[bytes],
    expected_code: str,
) -> None:
    request, calls = _raw_request([b'{"name":"must-not-be-read"}'], content_length=None)
    request.scope["headers"] = [
        item for item in request.scope["headers"] if item[0] != header_name.encode("ascii")
    ]
    request.scope["headers"].extend(
        (header_name.encode("ascii"), value) for value in header_values
    )

    with pytest.raises(gateway.FormGatewayError) as failure:
        asyncio.run(gateway._read_bounded_json_body(request, 4096))

    assert failure.value.code == expected_code
    assert calls["receive"] == 0


def test_active_delivery_routes_hide_internal_resolution_errors(monkeypatch) -> None:
    sensitive = "Audit 91 fingerprint exposes provider-internal-sensitive-detail."

    def fail_delivery(_session, _page_id):
        raise theme_delivery.ThemeDeliveryError(
            sensitive,
            status_code=409,
            code="internal_scope_error",
        )

    monkeypatch.setattr(
        theme_delivery_routes,
        "read_active_performance_local_delivery",
        fail_delivery,
    )

    for route in (
        theme_delivery_routes.active_performance_local_delivery,
        theme_delivery_routes.active_performance_local_export,
    ):
        with pytest.raises(HTTPException) as failure:
            route(41, object())
        assert failure.value.status_code == 503
        assert failure.value.detail == {
            "code": "performance_local_delivery_unavailable",
            "message": "Performance Local delivery is unavailable.",
        }
        assert sensitive not in str(failure.value.detail)


def test_raw_gateway_enforces_stream_limit_without_trusting_content_length() -> None:
    request, calls = _raw_request([b"{" + b"x" * 20, b"y" * 20 + b"}"], content_length=None)
    with pytest.raises(gateway.FormGatewayError) as failure:
        asyncio.run(gateway._read_bounded_json_body(request, 32))
    assert failure.value.code == "request_too_large"
    assert calls["receive"] == 2


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: {**body, "unknown": "hidden-uncontrolled-field"},
        lambda body: {**body, "file": {"filename": "upload.txt"}},
        lambda body: {**body, "name": "Synthetic\x00Name"},
        lambda body: {**body, "requested_service": "Service\r\nBcc: value"},
        lambda body: {**body, "message": "<script>synthetic</script>"},
        lambda body: {**body, "phone": "+1 (407) 555-0100\nInjected"},
    ],
)
def test_submission_normalization_rejects_unknown_file_control_newline_and_html(
    mutation,
) -> None:
    contract = CompactEstimateFormConfigurationV3.model_validate(
        _form_payload("rehearsal_ready")
    )
    valid = {
        "name": "Synthetic Person",
        "phone": "+1 (407) 555-0100",
        "postal_code": "32801",
        "requested_service": "Synthetic Service",
        "message": None,
        "consent_accepted": None,
    }
    submitted = mutation(valid)
    with pytest.raises(gateway.FormGatewayError) as failure:
        gateway._normalize_submission(submitted, contract)
    assert failure.value.code in {"submission_invalid", "consent_required"}
    assert failure.value.safe_message in {
        "The submitted fields are invalid.",
        "Required consent was not accepted.",
    }
    for value in submitted.values():
        if isinstance(value, str) and value:
            assert value not in failure.value.safe_message


def test_normalization_is_unicode_safe_and_provider_neutral() -> None:
    contract = CompactEstimateFormConfigurationV3.model_validate(
        _form_payload("rehearsal_ready")
    )
    normalized = gateway._normalize_submission(
        {
            "name": "  Synthe\u0301tic Person  ",
            "phone": "+1 (407) 555-0100",
            "postal_code": "ab 12-cd",
            "requested_service": "Synthetic Service",
            "message": "Synthetic message",
            "consent_accepted": None,
        },
        contract,
    )
    assert normalized.name == "Synthétic Person"
    assert normalized.phone == "+14075550100"
    assert normalized.postal_code == "AB 12-CD"
    assert set(normalized.model_dump()) == {
        "name",
        "phone",
        "postal_code",
        "requested_service",
        "message",
        "consent_accepted",
        "optional_field",
    }
    assert normalized.optional_field is None


def test_gateway_accepts_one_governed_sixth_value_and_optional_omission() -> None:
    contract = _gateway_definition_with_sixth()
    base = {
        "name": "Synthetic Person",
        "phone": "+1 (407) 555-0100",
        "postal_code": "32801",
        "requested_service": "Synthetic Service",
        "message": None,
        "consent_accepted": None,
    }
    omitted = gateway._normalize_submission(base, contract)
    assert omitted.optional_field is None
    assert omitted.to_optional_envelope_binding(contract) == (
        "project_reference_revision_1",
        None,
    )

    normalized = gateway._normalize_submission(
        {
            **base,
            "optional_field": {
                "field_key": "Project Reference",
                "definition_revision_identity": "Project Reference Revision 1",
                "value": "  Synthetic reference  ",
            },
        },
        contract,
    )
    assert normalized.optional_field is not None
    assert normalized.optional_field.model_dump() == {
        "field_key": "project_reference",
        "definition_revision_identity": "project_reference_revision_1",
        "value": "Synthetic reference",
    }
    envelope_value = normalized.optional_field.to_envelope_value(
        contract.optional_fields[0]
    )
    assert envelope_value.provider_mapping_key == "project_reference"
    assert envelope_value.value == "Synthetic reference"
    assert normalized.to_optional_envelope_binding(contract) == (
        "project_reference_revision_1",
        envelope_value,
    )


@pytest.mark.parametrize(
    "optional_field",
    (
        {
            "field_key": "unknown_field",
            "definition_revision_identity": "project_reference_revision_1",
            "value": "Synthetic reference",
        },
        {
            "field_key": "project_reference",
            "definition_revision_identity": "wrong_revision",
            "value": "Synthetic reference",
        },
        {
            "field_key": "project_reference",
            "definition_revision_identity": "project_reference_revision_1",
            "value": "Synthetic reference",
            "provider_payload": "forbidden",
        },
    ),
)
def test_gateway_rejects_unknown_mismatched_or_extra_sixth_fields(
    optional_field: dict[str, object],
) -> None:
    body = {
        "name": "Synthetic Person",
        "phone": "+1 (407) 555-0100",
        "postal_code": "32801",
        "requested_service": "Synthetic Service",
        "message": None,
        "consent_accepted": None,
        "optional_field": optional_field,
    }
    with pytest.raises(gateway.FormGatewayError) as failure:
        gateway._normalize_submission(body, _gateway_definition_with_sixth())
    assert failure.value.code == "submission_invalid"
    assert failure.value.safe_message == "The submitted fields are invalid."


def test_gateway_rejects_required_omission_overlength_and_unconfigured_sixth() -> None:
    base = {
        "name": "Synthetic Person",
        "phone": "+1 (407) 555-0100",
        "postal_code": "32801",
        "requested_service": "Synthetic Service",
        "message": None,
        "consent_accepted": None,
    }
    with pytest.raises(gateway.FormGatewayError, match="submitted fields"):
        gateway._normalize_submission(
            base,
            _gateway_definition_with_sixth(required=True),
        )
    submitted = {
        **base,
        "optional_field": {
            "field_key": "project_reference",
            "definition_revision_identity": "project_reference_revision_1",
            "value": "x" * 11,
        },
    }
    with pytest.raises(gateway.FormGatewayError, match="submitted fields"):
        gateway._normalize_submission(
            submitted,
            _gateway_definition_with_sixth(maximum_length=10),
        )
    with pytest.raises(gateway.FormGatewayError, match="submitted fields"):
        gateway._normalize_submission(
            submitted,
            UNIVERSAL_ESTIMATE_FORM_DEFINITION,
        )


@pytest.mark.parametrize(
    ("runtime_mode", "database_url", "frontend_origin", "allowed"),
    [
        ("automated_test", "sqlite:///disposable-test.sqlite3", "http://localhost:5173", True),
        ("active_local", "sqlite:///disposable-test.sqlite3", "http://localhost:5173", False),
        ("activation_rehearsal", "sqlite:///atlas.db", "http://localhost:5173", False),
        ("activation_rehearsal", "postgresql://atlas@localhost/atlas", "http://localhost:5173", False),
        ("activation_rehearsal", "sqlite:///rehearsal-clone.sqlite3", "https://public.example", False),
    ],
)
def test_synthetic_provider_environment_guard_is_explicit_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    runtime_mode: str,
    database_url: str,
    frontend_origin: str,
    allowed: bool,
) -> None:
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: SimpleNamespace(
            atlas_runtime_mode=runtime_mode,
            database_url=database_url,
            frontend_origin=frontend_origin,
        ),
    )
    assert gateway.disposable_rehearsal_environment_allowed() is allowed


@pytest.mark.parametrize(
    "database_name",
    ["atlas_latest", "contest", "latest", "production-testimonials"],
)
def test_disposable_database_identity_rejects_incidental_marker_substrings(
    database_name: str,
) -> None:
    assert gateway.is_explicit_disposable_database_name(database_name) is False
    assert gateway._is_disposable_database(f"postgresql://atlas@localhost/{database_name}") is False


def test_rehearsal_gateway_refuses_non_disposable_actual_session_bind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'atlas.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: SimpleNamespace(
            atlas_runtime_mode="activation_rehearsal",
            database_url="sqlite:///performance-local-rehearsal.sqlite3",
            frontend_origin="http://localhost:5173",
        ),
    )
    with Session(engine) as active_named_session:
        graph = _seed_v3(active_named_session, state="rehearsal_ready")
        _activate_rehearsal_graph(active_named_session, graph)
        assert gateway._session_uses_explicit_disposable_database(active_named_session) is False
        with pytest.raises(gateway.FormGatewayError) as blocked:
            gateway.preflight_form_gateway(
                active_named_session,
                graph.website.id,
                graph.form.id,
            )
        assert (blocked.value.status_code, blocked.value.code) == (
            503,
            "form_delivery_mode_not_found",
        )


def test_active_gateway_rejects_malformed_expected_and_observed_origins() -> None:
    request, calls = _raw_request(
        [b'{"name":"must-not-be-read"}'],
        origin="not-an-origin",
    )
    preflight = SimpleNamespace(
        mode="active",
        website=SimpleNamespace(public_url="also-not-an-origin"),
    )

    with pytest.raises(gateway.FormGatewayError) as blocked:
        gateway._require_origin(request, preflight)

    assert (blocked.value.status_code, blocked.value.code) == (403, "origin_rejected")
    assert calls["receive"] == 0


def test_post_activation_rehearsal_gateway_requires_explicit_mode_before_body(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_v3(session, state="rehearsal_ready")
    _activate_rehearsal_graph(session, graph)
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: SimpleNamespace(
            atlas_runtime_mode="activation_rehearsal",
            database_url="sqlite:///performance-local-rehearsal.sqlite3",
            frontend_origin="http://localhost:5173",
        ),
    )
    provider_calls = 0

    class ForbiddenProvider:
        provider_key = gateway.SYNTHETIC_PROVIDER_KEY

        def submit(self, context, envelope):
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("legacy provider fallback must never run")

    monkeypatch.setattr(
        gateway,
        "TEST_ONLY_SUBMISSION_PROVIDERS",
        {gateway.SYNTHETIC_PROVIDER_KEY: ForbiddenProvider()},
    )
    with pytest.raises(gateway.FormGatewayError) as missing_mode:
        gateway.preflight_form_gateway(
            session,
            graph.website.id,
            graph.form.id,
        )
    assert (missing_mode.value.status_code, missing_mode.value.code) == (
        503,
        "form_delivery_mode_not_found",
    )
    assert provider_calls == 0


@pytest.mark.parametrize("scope_case", ["cross_page", "expired_override", "inactive"])
def test_form_gateway_rejects_non_default_or_inactive_form_scope_before_body(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    scope_case: str,
) -> None:
    graph = _seed_v3(session, state="rehearsal_ready")
    _activate_rehearsal_graph(session, graph)
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: SimpleNamespace(
            atlas_runtime_mode="activation_rehearsal",
            database_url="sqlite:///performance-local-rehearsal.sqlite3",
            frontend_origin="http://localhost:5173",
        ),
    )
    planned_page_id = graph.planned.id
    override_target_id = graph.banner.id
    if scope_case == "inactive":
        graph.form.lifecycle_status = "superseded"
    else:
        graph.form.scope_type = "page_override"
        graph.form.planned_page_id = planned_page_id
        graph.form.overrides_component_configuration_id = override_target_id
        if scope_case == "expired_override":
            graph.form.effective_at = datetime(2020, 1, 1, tzinfo=UTC)
            graph.form.expires_at = datetime(2020, 1, 2, tzinfo=UTC)
    graph.form.integrity_fingerprint = theme_service._component_fingerprint_from_record(
        graph.form
    )
    session.add(graph.form)
    session.commit()

    request, calls = _raw_request([b'{"name":"must-not-be-read"}'])
    with pytest.raises(HTTPException) as blocked:
        asyncio.run(
            form_submission_routes.submit_performance_local_form(
                graph.website.id,
                graph.form.id,
                request,
                session,
            )
        )
    assert (blocked.value.status_code, blocked.value.detail["code"]) == (
        503,
        "form_submission_unavailable",
    )
    assert calls["receive"] == 0


def test_preactivation_rehearsal_export_is_blocked_with_typed_delivery_blocker(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_v3(session, state="rehearsal_ready")
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: SimpleNamespace(
            atlas_runtime_mode="activation_rehearsal",
            database_url="sqlite:///performance-local-rehearsal.sqlite3",
            frontend_origin="http://localhost:5173",
        ),
    )
    monkeypatch.setattr(
        theme_delivery,
        "_composition",
        lambda _session, _page, **_kwargs: (
            {"fixture": "performance-local-v3"},
            [],
        ),
    )

    delivery = theme_delivery.read_performance_local_rehearsal_delivery(
        session,
        graph.configuration.id,
        graph.page.id,
    )
    blocker = next(
        item
        for item in delivery.blockers
        if item.code == "rehearsal_activation_audit_incomplete"
    )
    assert blocker.category == "export"
    assert delivery.export_eligibility.eligible is False
    assert delivery.export_eligibility.identity is None
    assert any(
        item.code == "rehearsal_activation_audit_incomplete"
        for item in delivery.export_eligibility.blockers
    )


def test_synthetic_provider_is_stateless_network_free_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = gateway.TEST_ONLY_SUBMISSION_PROVIDERS[gateway.SYNTHETIC_PROVIDER_KEY]
    context = gateway.ProviderDeliveryContext(
        provider_key=gateway.SYNTHETIC_PROVIDER_KEY,
        destination_reference=gateway.SYNTHETIC_PROVIDER_DESTINATION,
        secret_reference="secret-ref://atlas/forms/synthetic",
        audit_identity="synthetic-audit",
        privacy_policy_destination="http://localhost/privacy",
        consent_mode="not_required",
        consent_text_version=None,
        retention_duration="synthetic-policy-duration",
        deletion_expiration_behavior="discard-after-synthetic-result",
        spam_strategy="synthetic_test",
        spam_configuration_reference="synthetic-noop",
        success_behavior="Show a generic success state.",
        failure_behavior="Show a generic failure state.",
    )
    envelope = gateway.NormalizedSubmissionEnvelope(
        website_id=101,
        component_configuration_id=202,
        name="Synthetic Person",
        phone="+14075550100",
        postal_code="32801",
        requested_service="Synthetic Service",
        message=None,
        consent_accepted=None,
        audit_identity="synthetic-audit",
        idempotency_key="synthetic-idempotency-key-00000001",
    )

    def network_forbidden(*_args, **_kwargs):
        raise AssertionError("synthetic provider attempted a network operation")

    import socket

    monkeypatch.setattr(socket, "socket", network_forbidden)
    first = provider.submit(context, envelope)
    second = provider.submit(context, envelope)
    assert first == second
    assert first.provider_reference.startswith("synthetic-")
    assert getattr(provider, "__dict__", {}) == {}
    changed = provider.submit(
        context,
        gateway.NormalizedSubmissionEnvelope(
            **{
                **envelope.__dict__,
                "idempotency_key": "synthetic-idempotency-key-00000002",
            }
        )
    )
    assert changed.provider_reference != first.provider_reference
    alternate_context = gateway.ProviderDeliveryContext(
        **{
            **context.__dict__,
            "destination_reference": "memory://different-discard-scope",
        }
    )
    assert (
        provider.submit(alternate_context, envelope).provider_reference
        != first.provider_reference
    )


def test_active_gateway_and_public_export_require_full_readiness_and_audits_before_build(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_v3(session, state="production_configured")
    _activate_production_graph(session, graph)
    called = False

    def forbidden_export(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("base export ran before the V3 readiness gate")

    monkeypatch.setattr(page_export, "build_page_export_package", forbidden_export)
    with pytest.raises(HTTPException) as failure:
        build_theme_configured_page_export_package(
            session,
            graph.page.id,
            graph.configuration.id,
        )
    assert failure.value.status_code == 409
    assert failure.value.detail["code"] == "theme_configuration_export_blocked"
    assert called is False
    with pytest.raises(gateway.FormGatewayError) as preflight_failure:
        gateway.preflight_form_gateway(session, graph.website.id, graph.form.id)
    assert preflight_failure.value.status_code == 503

    activation_audit = session.exec(
        select(ThemeConfigurationAudit).where(
            ThemeConfigurationAudit.component_configuration_id == graph.form.id,
            ThemeConfigurationAudit.action_type == "component_activated",
        )
    ).one()
    session.exec(delete(ThemeConfigurationAudit).where(ThemeConfigurationAudit.id == activation_audit.id))
    session.commit()
    with pytest.raises(gateway.FormGatewayError) as missing_audit:
        gateway.preflight_form_gateway(session, graph.website.id, graph.form.id)
    assert (missing_audit.value.status_code, missing_audit.value.code) == (
        503,
        "form_delivery_mode_not_found",
    )


def test_active_renderer_rejects_persisted_stale_composition(
    session: Session,
) -> None:
    graph = _seed_v3(session, state="production_configured")
    _activate_production_graph(session, graph)
    composition_snapshot = {
        "fixture": "stale-v3-composition",
        "draft_hash": canonical_payload_hash(graph.page.draft_content or {}),
    }
    composition = PageComposition(
            website_id=graph.website.id,
            site_plan_id=graph.planned.site_plan_id,
            planned_page_id=graph.planned.id,
            generated_page_id=graph.page.id,
            composition_version=1,
            generated_components=[],
            operator_decisions=[],
            source_snapshot=composition_snapshot,
            source_hash=canonical_payload_hash(composition_snapshot),
            status="stale",
    )
    session.add(composition)
    session.flush()
    create_initial_composition_revision(
        session,
        composition,
        recorded_by="test:performance-local-v3-gateway",
        record_source="test_fixture",
    )
    session.commit()

    with pytest.raises(theme_delivery.ThemeDeliveryError) as blocked:
        theme_delivery.read_active_performance_local_delivery(
            session,
            graph.page.id,
        )
    assert blocked.value.code == "page_composition_not_current"


def test_active_renderer_and_explicit_export_reject_noncurrent_qa_before_package(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_v3(session, state="production_configured")
    _activate_production_graph(session, graph)
    monkeypatch.setattr(
        theme_delivery,
        "_composition",
        lambda _session, _page, **_kwargs: ({"status": "current"}, []),
    )
    with pytest.raises(theme_delivery.ThemeDeliveryError) as blocked_renderer:
        theme_delivery.read_active_performance_local_delivery(
            session,
            graph.page.id,
        )
    assert blocked_renderer.value.code == "page_qa_not_ready"

    composition_snapshot = {
        "fixture": "current-v3-composition",
        "draft_hash": canonical_payload_hash(graph.page.draft_content or {}),
    }
    composition = PageComposition(
            website_id=graph.website.id,
            site_plan_id=graph.planned.site_plan_id,
            planned_page_id=graph.planned.id,
            generated_page_id=graph.page.id,
            composition_version=1,
            generated_components=[],
            operator_decisions=[],
            source_snapshot=composition_snapshot,
            source_hash=canonical_payload_hash(composition_snapshot),
            status="current",
    )
    session.add(composition)
    session.flush()
    create_initial_composition_revision(
        session,
        composition,
        recorded_by="test:performance-local-v3-gateway",
        record_source="test_fixture",
    )
    session.commit()
    from app.services import page_composition as composition_service

    monkeypatch.setattr(
        composition_service,
        "_read",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    package_called = False

    def forbidden_package(*_args, **_kwargs):
        nonlocal package_called
        package_called = True
        raise AssertionError("base export ran without exact current ready QA")

    monkeypatch.setattr(page_export, "build_page_export_package", forbidden_package)
    with pytest.raises(HTTPException) as blocked_export:
        build_theme_configured_page_export_package(
            session,
            graph.page.id,
            graph.configuration.id,
        )
    assert blocked_export.value.status_code == 409
    assert blocked_export.value.detail["code"] == "theme_configuration_export_blocked"
    assert package_called is False


def test_rehearsal_delivery_and_full_site_audit_record_current_blocked_qa(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_v3(session, state="rehearsal_ready")
    _activate_rehearsal_graph(session, graph)
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: SimpleNamespace(
            atlas_runtime_mode="activation_rehearsal",
            database_url="sqlite:///performance-local-rehearsal.sqlite3",
            frontend_origin="http://localhost:5173",
        ),
    )
    monkeypatch.setattr(
        theme_delivery,
        "_composition",
        lambda _session, _page, **_kwargs: (
            {
                "id": 1,
                "composition_version": 1,
                "source_hash": "c" * 64,
                "source_snapshot": {"page_media": {"requirements": [], "assignments": []}},
                "effective_components": [],
                "status": "current",
            },
            [],
        ),
    )
    saved = page_qa_service.save_page_qa(session, graph.page.id)
    state = page_qa_service.effective_page_qa_state(session, graph.page)
    assert state.current is True
    assert state.ready is False
    assert saved.readiness_status != "ready"

    delivery = theme_delivery.read_performance_local_rehearsal_delivery(
        session,
        graph.configuration.id,
        graph.page.id,
    )
    assert delivery.renderer_result.status == "blocked"
    assert delivery.export_eligibility.eligible is False
    assert any(
        item.category == "qa" and "current but not ready" in item.reason
        for item in delivery.blockers
    )

    report = theme_activation_rehearsal.audit_performance_local_full_site_rehearsal(
        session,
        graph.website.id,
        graph.configuration.id,
        expected_page_count=1,
    )
    assert report.evaluated_page_count == 1
    assert report.ready_count == 0
    assert report.blocked_count == 1
    assert report.pages[0].qa_readiness_result == saved.readiness_status
    assert any("page_qa_readiness" in item for item in report.pages[0].blockers)


def test_delivery_public_projection_recursively_redacts_provider_boundary(
    session: Session,
) -> None:
    graph = _seed_v3(session, state="rehearsal_ready")
    component_read = theme_delivery._public_component_read(graph.form)
    audit = session.exec(
        select(ThemeConfigurationAudit).where(
            ThemeConfigurationAudit.component_configuration_id == graph.form.id,
            ThemeConfigurationAudit.action_type == "component_created",
        )
    ).one()
    audit_read = theme_delivery._public_audit_read(audit)
    readiness = gateway.evaluate_form_readiness(
        graph.form,
        mode="activation_rehearsal",
        test_environment_allowed=True,
    )
    public_readiness = theme_delivery._public_form_readiness(readiness)
    serialized = json.dumps(
        {
            "component": component_read.model_dump(mode="json"),
            "audit": audit_read.model_dump(mode="json"),
            "readiness": public_readiness.model_dump(mode="json"),
        },
        sort_keys=True,
    )
    assert readiness.provider_state.provider_key == gateway.SYNTHETIC_PROVIDER_KEY
    assert public_readiness.provider_state.provider_key is None
    for forbidden in (
        gateway.SYNTHETIC_PROVIDER_KEY,
        gateway.SYNTHETIC_PROVIDER_DESTINATION,
        "secret-ref://atlas/forms/estimate-provider",
        "synthetic-noop",
    ):
        assert forbidden not in serialized


def test_malformed_origin_and_deep_json_return_stable_errors_before_delivery(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _seed_v3(session, state="rehearsal_ready")
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: SimpleNamespace(
            atlas_runtime_mode="automated_test",
            database_url="sqlite:///disposable-test.sqlite3",
            frontend_origin="http://localhost:5173",
        ),
    )
    preflight = SimpleNamespace(
        website=graph.website,
        component=graph.form,
        runtime_scope="contained_test",
    )
    receive_calls = 0

    async def receive_never():
        nonlocal receive_calls
        receive_calls += 1
        return {"type": "http.request", "body": b"{}", "more_body": False}

    malformed_origin_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/form",
            "query_string": b"",
            "headers": [(b"origin", b"http://[::1")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "http_version": "1.1",
        },
        receive_never,
    )
    with pytest.raises(gateway.FormGatewayError) as origin_error:
        gateway._require_origin(malformed_origin_request, preflight)
    assert origin_error.value.code == "origin_rejected"
    assert receive_calls == 0
    assert gateway._normalized_origin(
        "http://user:pass@localhost:5173/path?query=value#fragment"
    ) is None

    deeply_nested = ("[" * 1100 + "0" + "]" * 1100).encode()
    sent = False

    async def receive_deep():
        nonlocal sent
        assert sent is False
        sent = True
        return {
            "type": "http.request",
            "body": deeply_nested,
            "more_body": False,
        }

    deep_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/form",
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(deeply_nested)).encode()),
            ],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "http_version": "1.1",
        },
        receive_deep,
    )
    with pytest.raises(gateway.FormGatewayError) as json_error:
        asyncio.run(gateway._read_bounded_json_body(deep_request, 4096))
    assert json_error.value.code == "malformed_json"


def _revise_v3_conversion_graph(
    session: Session,
    graph: SimpleNamespace,
) -> SimpleNamespace:
    revised = theme_service.revise_conversion_component_graph(
        session,
        graph.website.id,
        graph.configuration.id,
        ConversionComponentGraphRevisionCreate(
            form_component_configuration_id=graph.form.id,
            banner_component_configuration_id=graph.banner.id,
            sticky_component_configuration_id=graph.sticky.id,
            form_revision=WebsiteThemeComponentConfigurationRevisionCreate(
                enabled=True,
                variant=graph.form.variant,
                placement=graph.form.placement,
                responsive_visibility=graph.form.responsive_visibility,
                configuration_payload=_form_payload("rehearsal_ready"),
                approval_identity="V3 Test Operator",
                updated_by="V3 Test Operator",
                revision_rationale="Exercise portable V3 component lineage.",
            ),
            banner_revision=WebsiteThemeComponentConfigurationRevisionCreate(
                enabled=True,
                variant=graph.banner.variant,
                placement=graph.banner.placement,
                responsive_visibility=graph.banner.responsive_visibility,
                configuration_payload=deepcopy(graph.banner.configuration_payload),
                approval_identity="V3 Test Operator",
                updated_by="V3 Test Operator",
                revision_rationale="Exercise portable V3 component lineage.",
                destination_component_configuration_id=graph.form.id,
            ),
            sticky_revision=WebsiteThemeComponentConfigurationRevisionCreate(
                enabled=True,
                variant=graph.sticky.variant,
                placement=graph.sticky.placement,
                responsive_visibility=graph.sticky.responsive_visibility,
                configuration_payload=deepcopy(graph.sticky.configuration_payload),
                approval_identity="V3 Test Operator",
                updated_by="V3 Test Operator",
                revision_rationale="Exercise portable V3 component lineage.",
                destination_component_configuration_id=graph.form.id,
            ),
        ),
    )
    return SimpleNamespace(
        form=revised.form,
        banner=revised.banner,
        sticky=revised.sticky,
    )


def _supersede_v3_configuration(
    session: Session,
    graph: SimpleNamespace,
) -> WebsiteThemeConfiguration:
    return theme_service.create_website_theme_configuration(
        session,
        graph.website.id,
        WebsiteThemeConfigurationCreate(
            theme_family_version_id=graph.v3.id,
            configuration_key=graph.configuration.configuration_key,
            created_by="V3 Test Operator",
            creation_rationale="Exercise portable V3 configuration lineage.",
            supersedes_configuration_id=graph.configuration.id,
        ),
    )


def _seed_nonempty_theme_target(session: Session) -> SimpleNamespace:
    business = Business(
        company_name="Portable Restore Sentinel",
        business_type="synthetic test",
        state="FL",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name="Portable Restore Sentinel Brand",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name="Portable Restore Sentinel Website",
        domain="portable-restore-sentinel.example.test",
        public_url="https://portable-restore-sentinel.example.test",
        status="active",
    )
    session.add(website)
    session.commit()

    family = theme_service.register_theme_family(
        session,
        ThemeFamilyCreate(
            family_key="portable-restore-sentinel",
            display_name="Portable Restore Sentinel",
            description="Unrelated durable Theme identity used to force ID remapping.",
            provider_source_identity="atlas-source:portable-restore-sentinel",
            created_by="Portable Restore Test Operator",
        ),
    )
    form_contract = next(
        deepcopy(item)
        for item in PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS
        if item["component_key"] == "compact_estimate_form"
    )
    version = theme_service.register_theme_family_version(
        session,
        family.id,
        ThemeFamilyVersionCreate(
            version=2,
            source_commit="f" * 40,
            supported_component_contracts=[form_contract],
            created_by="Portable Restore Test Operator",
        ),
    )
    configuration = theme_service.create_website_theme_configuration(
        session,
        website.id,
        WebsiteThemeConfigurationCreate(
            theme_family_version_id=version.id,
            configuration_key="portable-restore-sentinel",
            created_by="Portable Restore Test Operator",
            creation_rationale="Force every durable Theme table to remap source IDs.",
        ),
    )
    fields = deepcopy(_fields())
    fields[1]["validation_contract"]["minimum_length"] = 6
    component = theme_service.create_component_configuration(
        session,
        website.id,
        configuration.id,
        WebsiteThemeComponentConfigurationCreate(
            component_instance_key="sentinel-form",
            component_key="compact_estimate_form",
            component_contract_version=2,
            scope_type="website_default",
            enabled=True,
            variant=form_contract["variant"],
            placement=form_contract["placement"],
            responsive_visibility=form_contract["responsive_visibility"],
            configuration_payload={
                "submission_state": "disabled_pending_provider_configuration",
                "fields": fields,
                "submit_label": "Review request",
                "preview_notice": "Synthetic provider-disabled sentinel only.",
                "provider_key": None,
                "destination": None,
                "privacy_policy_destination": None,
                "consent_language": None,
                "data_retention_policy": None,
                "spam_strategy": None,
                "success_behavior": None,
                "failure_behavior": None,
                "audit_identity": None,
            },
            approval_identity="Portable Restore Test Operator",
            created_by="Portable Restore Test Operator",
        ),
    )
    return SimpleNamespace(
        family=family,
        version=version,
        configuration=configuration,
        component=component,
    )


def _theme_backup_projection(session: Session) -> dict[str, list[dict]]:
    return {
        model.__tablename__: [
            record.model_dump(mode="json")
            for record in session.exec(select(model).order_by(model.id)).all()
        ]
        for model in (
            ThemeFamily,
            ThemeFamilyVersion,
            WebsiteThemeConfiguration,
            WebsiteThemeComponentConfiguration,
            ThemeConfigurationAudit,
        )
    }


def _write_backup_payload(tmp_path: Path, payload: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return path


def _rehash_theme_backup(
    payload: dict,
    *,
    refresh_audit_snapshots: bool = True,
) -> None:
    data = payload["data"]
    families = {record["id"]: record for record in data["theme_families"]}
    versions = {record["id"]: record for record in data["theme_family_versions"]}
    configurations = {
        record["id"]: record for record in data["website_theme_configurations"]
    }
    components = {
        record["id"]: record
        for record in data["website_theme_component_configurations"]
    }
    for record in families.values():
        record["integrity_fingerprint"] = backup_service._canonical_json_hash(
            backup_service._theme_family_fingerprint_payload(record)
        )
    for record in versions.values():
        family = families[record["theme_family_id"]]
        record["compatibility_identity"] = backup_service._canonical_json_hash(
            {
                "family_key": family["family_key"],
                "version": record["version"],
                "supported_component_contracts": record[
                    "supported_component_contracts"
                ],
            }
        )
        record["integrity_fingerprint"] = backup_service._canonical_json_hash(
            backup_service._theme_family_version_fingerprint_payload(record)
        )
    for record in configurations.values():
        record["integrity_fingerprint"] = backup_service._canonical_json_hash(
            backup_service._website_theme_configuration_fingerprint_payload(record)
        )
    for record in components.values():
        record["integrity_fingerprint"] = backup_service._canonical_json_hash(
            backup_service._theme_component_configuration_fingerprint_payload(record)
        )

    target_groups = (
        (
            "theme_family_id",
            families,
            backup_service._theme_family_fingerprint_payload,
        ),
        (
            "theme_family_version_id",
            versions,
            backup_service._theme_family_version_fingerprint_payload,
        ),
        (
            "website_theme_configuration_id",
            configurations,
            backup_service._website_theme_configuration_fingerprint_payload,
        ),
        (
            "component_configuration_id",
            components,
            backup_service._theme_component_configuration_fingerprint_payload,
        ),
    )
    for audit in data["theme_configuration_audits"]:
        if refresh_audit_snapshots:
            populated = [
                (field, records, projector)
                for field, records, projector in target_groups
                if audit.get(field) is not None
            ]
            assert len(populated) == 1
            field, records, projector = populated[0]
            audit["snapshot"] = projector(records[audit[field]])
        audit["snapshot_hash"] = backup_service._canonical_json_hash(
            backup_service._theme_configuration_audit_hash_payload(audit)
        )


def test_backup_057_round_trips_canonical_v3_draft_graph(
    session: Session,
    tmp_path: Path,
) -> None:
    graph = _seed_v3(session, state="rehearsal_ready")
    exported = export_backup(session, backup_dir=tmp_path)
    loaded = load_backup(Path(exported["path"]))
    assert loaded["metadata"]["version"] == "0.59"
    assert loaded["metadata"]["table_counts"]["theme_family_versions"] == 2

    target_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as target:
        result = restore_backup(target, exported["path"])
        assert result["status"] == "restored"
        restored_v3 = target.exec(
            select(ThemeFamilyVersion).where(ThemeFamilyVersion.version == 3)
        ).one()
        assert restored_v3.lifecycle_status == "preview_candidate"
        assert restored_v3.production_ready is False
        assert restored_v3.supported_component_contracts == list(
            PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS
        )
        restored_configuration = target.exec(
            select(WebsiteThemeConfiguration).where(
                WebsiteThemeConfiguration.configuration_key
                == graph.configuration.configuration_key
            )
        ).one()
        assert restored_configuration.lifecycle_status == "draft"


def test_backup_057_v3_repeated_restore_is_exactly_idempotent(
    session: Session,
    tmp_path: Path,
) -> None:
    graph = _seed_v3(session, state="rehearsal_ready")
    _revise_v3_conversion_graph(session, graph)
    _supersede_v3_configuration(session, graph)
    exported = export_backup(session, backup_dir=tmp_path)

    target_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as target:
        first = restore_backup(target, exported["path"])
        first_projection = _theme_backup_projection(target)
        first_counts = theme_service.validate_theme_configuration_records(target)

        second = restore_backup(target, exported["path"])
        second_projection = _theme_backup_projection(target)
        second_counts = theme_service.validate_theme_configuration_records(target)

    assert first["status"] == second["status"] == "restored"
    assert first["records_processed"] == second["records_processed"]
    assert first_projection == second_projection
    assert first_counts == second_counts == {
        "theme_families": 1,
        "theme_family_versions": 2,
        "website_theme_configurations": 2,
        "website_theme_component_configurations": 6,
        "theme_configuration_audits": 15,
    }


def test_backup_057_v3_nonempty_restore_remaps_exact_lineage_destinations_and_audits(
    session: Session,
    tmp_path: Path,
) -> None:
    graph = _seed_v3(session, state="rehearsal_ready")
    revised = _revise_v3_conversion_graph(session, graph)
    successor = _supersede_v3_configuration(session, graph)
    source_ids = {
        "family": graph.family.id,
        "v2": graph.v2.id,
        "v3": graph.v3.id,
        "configuration_v1": graph.configuration.id,
        "configuration_v2": successor.id,
        "form_v1": graph.form.id,
        "banner_v1": graph.banner.id,
        "sticky_v1": graph.sticky.id,
        "form_v2": revised.form.id,
        "banner_v2": revised.banner.id,
        "sticky_v2": revised.sticky.id,
    }
    source_audit_count = len(session.exec(select(ThemeConfigurationAudit)).all())
    exported = export_backup(session, backup_dir=tmp_path)

    target_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as target:
        sentinel = _seed_nonempty_theme_target(target)
        sentinel_audit_count = len(
            target.exec(select(ThemeConfigurationAudit)).all()
        )
        result = restore_backup(target, exported["path"])

        family = target.exec(
            select(ThemeFamily).where(
                ThemeFamily.family_key == "performance-local"
            )
        ).one()
        v2 = target.exec(
            select(ThemeFamilyVersion).where(
                ThemeFamilyVersion.theme_family_id == family.id,
                ThemeFamilyVersion.version == 2,
            )
        ).one()
        v3 = target.exec(
            select(ThemeFamilyVersion).where(
                ThemeFamilyVersion.theme_family_id == family.id,
                ThemeFamilyVersion.version == 3,
            )
        ).one()
        configurations = target.exec(
            select(WebsiteThemeConfiguration).where(
                WebsiteThemeConfiguration.theme_family_version_id == v3.id,
                WebsiteThemeConfiguration.configuration_key
                == graph.configuration.configuration_key,
            )
        ).all()
        by_configuration_version = {
            record.version: record for record in configurations
        }
        configuration_v1 = by_configuration_version[1]
        configuration_v2 = by_configuration_version[2]
        components = target.exec(
            select(WebsiteThemeComponentConfiguration).where(
                WebsiteThemeComponentConfiguration.website_theme_configuration_id
                == configuration_v1.id
            )
        ).all()
        by_component_revision = {
            (record.component_instance_key, record.revision): record
            for record in components
        }
        form_v1 = by_component_revision[("estimate-form-default", 1)]
        banner_v1 = by_component_revision[("campaign-default", 1)]
        sticky_v1 = by_component_revision[("conversion-actions-default", 1)]
        form_v2 = by_component_revision[("estimate-form-default", 2)]
        banner_v2 = by_component_revision[("campaign-default", 2)]
        sticky_v2 = by_component_revision[("conversion-actions-default", 2)]

        target_ids = {
            "theme_family_id": {family.id},
            "theme_family_version_id": {v2.id, v3.id},
            "website_theme_configuration_id": {
                configuration_v1.id,
                configuration_v2.id,
            },
            "component_configuration_id": {
                form_v1.id,
                banner_v1.id,
                sticky_v1.id,
                form_v2.id,
                banner_v2.id,
                sticky_v2.id,
            },
        }
        imported_audits = [
            audit
            for audit in target.exec(select(ThemeConfigurationAudit)).all()
            if any(
                getattr(audit, field) in identifiers
                for field, identifiers in target_ids.items()
            )
        ]
        validation_counts = theme_service.validate_theme_configuration_records(
            target
        )

        v3_registration = next(
            audit
            for audit in imported_audits
            if audit.theme_family_version_id == v3.id
            and audit.action_type == "family_version_registered"
        )
        configuration_revision = next(
            audit
            for audit in imported_audits
            if audit.website_theme_configuration_id == configuration_v2.id
            and audit.action_type == "website_configuration_revision_created"
        )
        banner_revision = next(
            audit
            for audit in imported_audits
            if audit.component_configuration_id == banner_v2.id
            and audit.action_type == "component_revision_created"
        )

        assert result["status"] == "restored"
        assert sentinel.family.id == source_ids["family"]
        restored_ids = {
            "family": family.id,
            "v2": v2.id,
            "v3": v3.id,
            "configuration_v1": configuration_v1.id,
            "configuration_v2": configuration_v2.id,
            "form_v1": form_v1.id,
            "banner_v1": banner_v1.id,
            "sticky_v1": sticky_v1.id,
            "form_v2": form_v2.id,
            "banner_v2": banner_v2.id,
            "sticky_v2": sticky_v2.id,
        }
        assert all(
            restored_ids[key] != source_id
            for key, source_id in source_ids.items()
        )
        assert v3.supersedes_theme_family_version_id == v2.id
        assert configuration_v2.supersedes_configuration_id == configuration_v1.id
        assert form_v2.supersedes_component_configuration_id == form_v1.id
        assert banner_v2.supersedes_component_configuration_id == banner_v1.id
        assert sticky_v2.supersedes_component_configuration_id == sticky_v1.id
        assert banner_v1.destination_component_configuration_id == form_v1.id
        assert sticky_v1.destination_component_configuration_id == form_v1.id
        assert banner_v2.destination_component_configuration_id == form_v2.id
        assert sticky_v2.destination_component_configuration_id == form_v2.id
        assert len(imported_audits) == source_audit_count
        assert v3_registration.snapshot[
            "supersedes_theme_family_version_id"
        ] == v2.id
        assert configuration_revision.snapshot[
            "supersedes_configuration_id"
        ] == configuration_v1.id
        assert banner_revision.snapshot[
            "destination_component_configuration_id"
        ] == form_v2.id
        assert all(
            audit.snapshot_hash
            == backup_service._canonical_json_hash(
                backup_service._theme_configuration_audit_hash_payload(
                    audit.model_dump(mode="json")
                )
            )
            for audit in imported_audits
        )
        assert validation_counts == {
            "theme_families": 2,
            "theme_family_versions": 3,
            "website_theme_configurations": 3,
            "website_theme_component_configurations": 7,
            "theme_configuration_audits": (
                source_audit_count + sentinel_audit_count
            ),
        }


@pytest.mark.parametrize(
    ("tamper", "expected"),
    [
        ("canonical_contract", "v3 backup contract is not canonical"),
        ("exact_predecessor", "requires its exact v2 predecessor"),
        ("provider_ready_payload", "invalid durable Theme configuration data"),
        ("audit_snapshot", "audit snapshot crosses its exact target"),
    ],
)
def test_backup_057_rejects_rehashed_v3_identity_payload_and_audit_tampering(
    session: Session,
    tmp_path: Path,
    tamper: str,
    expected: str,
) -> None:
    _seed_v3(session, state="production_configured")
    exported = export_backup(session, backup_dir=tmp_path)
    payload = load_backup(Path(exported["path"]))
    family = next(
        record
        for record in payload["data"]["theme_families"]
        if record["family_key"] == "performance-local"
    )
    v2 = next(
        record
        for record in payload["data"]["theme_family_versions"]
        if record["theme_family_id"] == family["id"] and record["version"] == 2
    )
    v3 = next(
        record
        for record in payload["data"]["theme_family_versions"]
        if record["theme_family_id"] == family["id"] and record["version"] == 3
    )
    canonical_v2 = deepcopy(v2)

    if tamper == "canonical_contract":
        v3["supported_component_contracts"][0][
            "diagnostic_label"
        ] = "Rehashed forged V3 diagnostic identity"
    elif tamper == "exact_predecessor":
        v3["supersedes_theme_family_version_id"] = None
    elif tamper == "provider_ready_payload":
        form = next(
            record
            for record in payload["data"][
                "website_theme_component_configurations"
            ]
            if record["component_key"] == "compact_estimate_form"
        )
        form["configuration_payload"]["provider"]["destination"] = (
            "https://user:literal-secret@example.test/form-delivery"
        )
    else:
        registration_audit = next(
            record
            for record in payload["data"]["theme_configuration_audits"]
            if record["theme_family_version_id"] == v3["id"]
            and record["action_type"] == "family_version_registered"
        )
        registration_audit["snapshot"]["version"] = 99

    _rehash_theme_backup(
        payload,
        refresh_audit_snapshots=tamper != "audit_snapshot",
    )
    assert v2 == canonical_v2
    tampered_path = _write_backup_payload(
        tmp_path,
        payload,
        f"v3-{tamper}-rehashed.json",
    )
    with pytest.raises(BackupValidationError, match=expected):
        load_backup(tampered_path)
