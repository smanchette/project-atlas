from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4
import socket
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Business,
    FormDeliveryAttempt,
    FormDeliveryConfigurationAudit,
    FormDeliveryOutbox,
    FormSubmissionEnvelope,
    ThemeFamily,
    ThemeFamilyVersion,
    Website,
    WebsiteFormDeliveryModeRevision,
    WebsiteFormRecipientRevision,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
)
from app.schemas.form_delivery import (
    WebsiteFormDeliveryModeRevisionCreate,
    WebsiteFormRecipientRevisionCreate,
)
from app.services.form_delivery_modes import (
    FormDeliveryConfigurationError,
    FORM_DELIVERY_TABLES,
    create_form_delivery_mode_revision,
    create_form_recipient_revision,
    form_delivery_readiness,
    form_recipient_fingerprint,
    read_form_delivery_mode_history,
    resolve_delivery_adapter_context,
    resolve_current_form_delivery_mode,
    resolve_provider_owned_presentation,
    validate_form_delivery_records,
)
from app.services.form_delivery_outbox import (
    FormDeliveryIdempotencyConflict,
    FormDeliveryOutboxError,
    enqueue_form_delivery,
    expire_form_delivery_payload,
    process_form_delivery_outbox,
)
from app.services.form_delivery_registry import (
    FORM_DELIVERY_PROVIDER_REGISTRY,
    SYNTHETIC_ATLASOPS360_KEY,
    SYNTHETIC_EMAIL_PROVIDER_KEY,
    SYNTHETIC_PROVIDER_OWNED_KEY,
)
from app.services import form_submission_gateway
from app.services.form_payload_store import (
    InMemoryTestPayloadStore,
    UnavailableProductionPayloadStore,
)
from app.website_builder_core.contracts import (
    DeliveryAttemptResult,
    NormalizedSubmissionEnvelope,
)
from app.website_builder_core.registry import ProviderDescriptor, ProviderRegistration


@pytest.fixture()
def isolated_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _utc_value(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _seed_form_component(session: Session, *, website_name: str = "Test"):
    token = uuid4().hex
    business = Business(
        company_name=f"{website_name} Company {token}",
        business_type="test",
        state="FL",
    )
    session.add(business)
    session.flush()
    website = Website(
        business_id=business.id,
        website_name=f"{website_name} Website",
        domain=f"{token}.example.test",
        public_url=f"https://{token}.example.test",
        status="active",
    )
    session.add(website)
    session.flush()
    family = ThemeFamily(
        family_key=f"test-{token}",
        display_name="Test family",
        description="Synthetic test family",
        provider_source_identity="test-source",
        lifecycle_status="registered",
        created_by="test",
        integrity_fingerprint="a" * 64,
    )
    session.add(family)
    session.flush()
    version = ThemeFamilyVersion(
        theme_family_id=family.id,
        version=3,
        lifecycle_status="preview_candidate",
        production_ready=False,
        source_commit="b" * 40,
        compatibility_identity=token.ljust(64, "0")[:64],
        supported_component_contracts=[],
        created_by="test",
        integrity_fingerprint="c" * 64,
    )
    session.add(version)
    session.flush()
    configuration = WebsiteThemeConfiguration(
        website_id=website.id,
        business_id=business.id,
        theme_family_version_id=version.id,
        configuration_key="test-configuration",
        version=1,
        lifecycle_status="draft",
        created_by="test",
        updated_by="test",
        creation_rationale="Synthetic form delivery test.",
        integrity_fingerprint="d" * 64,
    )
    session.add(configuration)
    session.flush()
    component = WebsiteThemeComponentConfiguration(
        website_theme_configuration_id=configuration.id,
        website_id=website.id,
        theme_family_version_id=version.id,
        component_instance_key="compact-estimate-form:website",
        component_key="compact_estimate_form",
        component_contract_version=3,
        revision=1,
        scope_type="website_default",
        lifecycle_status="current",
        enabled=True,
        variant="compact-estimate-form",
        placement="final-cta",
        responsive_visibility={"desktop": True, "tablet": True, "mobile": True},
        configuration_payload={},
        created_by="test",
        updated_by="test",
        integrity_fingerprint="e" * 64,
    )
    session.add(component)
    session.commit()
    return website, component


def _active_evidence() -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "lifecycle_status": "active",
        "approval_identity": "test-approval",
        "approved_at": now,
        "activation_identity": "test-activation",
        "activated_at": now,
    }


def _disabled_payload(component: WebsiteThemeComponentConfiguration):
    return WebsiteFormDeliveryModeRevisionCreate(
        form_component_configuration_id=component.id,
        form_instance_key=component.component_instance_key,
        mode="disabled",
        enabled=False,
        configuration_payload={},
        audit_identity="test-disabled-audit",
        created_by="test",
        updated_by="test",
        rationale="Test intentional disabled decision.",
        **_active_evidence(),
    )


def _email_payload(
    component: WebsiteThemeComponentConfiguration,
    predecessor_id: int,
):
    return WebsiteFormDeliveryModeRevisionCreate(
        form_component_configuration_id=component.id,
        form_instance_key=component.component_instance_key,
        supersedes_delivery_mode_revision_id=predecessor_id,
        mode="atlas_email",
        enabled=True,
        provider_key=SYNTHETIC_EMAIL_PROVIDER_KEY,
        adapter_version="test-v1",
        destination_identity="recipient-set-ref://synthetic/test-recipients",
        configuration_payload={
            "transport_key_reference": "synthetic-mail",
            "transport_secret_reference": "secret-ref://synthetic/mail-transport",
            "notification_preference": "all_verified",
            "consent_required": False,
        },
        privacy_policy_reference="/privacy",
        retention_policy_reference="policy-ref://synthetic/retention",
        abuse_policy_reference="policy-ref://synthetic/abuse",
        success_behavior="Show a generic success message.",
        failure_behavior="Show a generic failure message.",
        idempotency_policy_reference="policy-ref://synthetic/idempotency",
        audit_identity="test-email-audit",
        created_by="test",
        updated_by="test",
        rationale="Test Atlas email decision.",
        **_active_evidence(),
    )


def _provider_owned_payload(
    component: WebsiteThemeComponentConfiguration,
    predecessor_id: int,
    *,
    adapter_version: str = "test-v1",
    presentation_strategy: str = "hosted_route",
    approved_origin: str = "https://forms.example.com",
    sandbox_policy: str | None = None,
    referrer_policy: str | None = None,
    privacy_policy_reference: str | None = "/provider-privacy",
) -> WebsiteFormDeliveryModeRevisionCreate:
    configuration: dict[str, object] = {
        "presentation_strategy": presentation_strategy,
        "approved_https_destination": "https://forms.example.com/estimate",
        "approved_origin": approved_origin,
        "accessibility_title": "Request an estimate",
        "ownership_disclosure": "Example Forms operates this form.",
        "destination_verified_by": "test-verifier",
        "destination_verified_at": "2026-08-17T12:00:00Z",
    }
    if sandbox_policy is not None:
        configuration["sandbox_policy"] = sandbox_policy
    if referrer_policy is not None:
        configuration["referrer_policy"] = referrer_policy
    return WebsiteFormDeliveryModeRevisionCreate(
        form_component_configuration_id=component.id,
        form_instance_key=component.component_instance_key,
        supersedes_delivery_mode_revision_id=predecessor_id,
        mode="provider_owned",
        enabled=True,
        provider_key=SYNTHETIC_PROVIDER_OWNED_KEY,
        adapter_version=adapter_version,
        destination_identity="https://forms.example.com/estimate",
        configuration_payload=configuration,
        privacy_policy_reference=privacy_policy_reference,
        audit_identity="test-provider-owned-audit",
        created_by="test",
        updated_by="test",
        rationale="Synthetic provider-owned presentation decision.",
        **_active_evidence(),
    )


def _seed_ready_email_mode(session: Session):
    website, component = _seed_form_component(session)
    disabled = create_form_delivery_mode_revision(
        session,
        website.id,
        _disabled_payload(component),
    )
    original = disabled.model_dump(mode="json")
    email = create_form_delivery_mode_revision(
        session,
        website.id,
        _email_payload(component, disabled.id),
    )
    persisted_disabled = session.get(WebsiteFormDeliveryModeRevision, disabled.id)
    assert persisted_disabled is not None
    assert persisted_disabled.model_dump(mode="json") == original
    recipient = create_form_recipient_revision(
        session,
        website.id,
        WebsiteFormRecipientRevisionCreate(
            delivery_mode_revision_id=email.id,
            recipient_key="primary-office",
            email="Synthetic.Recipient@Example.com",
            label="Synthetic primary",
            recipient_role="primary",
            enabled=True,
            verification_status="verified",
            verified_at=datetime.now(UTC),
            verified_by="test-verifier",
            verification_method="synthetic_test",
            created_by="test",
            updated_by="test",
            rationale="Synthetic recipient verification.",
        ),
    )
    return website, component, disabled, email, recipient


def _normalized_submission(
    website: Website,
    component: WebsiteThemeComponentConfiguration,
    email: WebsiteFormDeliveryModeRevision,
    *,
    idempotency_key: str = "synthetic-idempotency-key-00000001",
    request_identity: str = "a" * 64,
    received_at: datetime | None = None,
) -> NormalizedSubmissionEnvelope:
    return NormalizedSubmissionEnvelope(
        website_id=website.id,
        component_configuration_id=component.id,
        component_revision=component.revision,
        delivery_mode_revision_id=email.id,
        submission_contract_version=3,
        name="Synthetic Person",
        phone="+14075550100",
        postal_code="32801",
        requested_service="Synthetic service",
        message="Synthetic message",
        consent_accepted=None,
        audit_identity=email.audit_identity,
        idempotency_key=idempotency_key,
        privacy_policy_identity=email.privacy_policy_reference,
        retention_policy_identity=email.retention_policy_reference,
        abuse_policy_identity=email.abuse_policy_reference,
        anti_spam_decision="synthetic_allow",
        request_identity=request_identity,
        destination_adapter_key=email.provider_key,
        received_at=received_at or datetime.now(UTC),
    )


def _test_delivery_adapter():
    registration = FORM_DELIVERY_PROVIDER_REGISTRY.registration(
        SYNTHETIC_EMAIL_PROVIDER_KEY,
        allow_test_only=True,
    )
    assert registration is not None and registration.delivery_adapter is not None
    return registration.delivery_adapter


def test_operator_history_response_redacts_secret_references(
    isolated_session: Session,
) -> None:
    website, component, _disabled, _email, _recipient = _seed_ready_email_mode(
        isolated_session
    )
    history = read_form_delivery_mode_history(
        isolated_session,
        website.id,
        component.id,
    )
    serialized = "\n".join(item.model_dump_json() for item in history)
    assert "secret-ref://synthetic/mail-transport" not in serialized
    email_revision = next(item for item in history if item.mode == "atlas_email")
    assert email_revision.configuration_payload[
        "transport_secret_reference_configured"
    ] is True
    assert "transport_secret_reference" not in email_revision.configuration_payload


def test_mode_switch_is_append_only_explicit_and_exactly_one_head(
    isolated_session: Session,
) -> None:
    website, component, disabled, email, recipient = _seed_ready_email_mode(
        isolated_session
    )
    current = resolve_current_form_delivery_mode(
        isolated_session,
        website.id,
        component.id,
    )
    assert current.id == email.id
    assert current.mode == "atlas_email"
    assert disabled.mode == "disabled"
    assert (disabled.revision, email.revision) == (1, 2)
    assert email.supersedes_delivery_mode_revision_id == disabled.id
    assert recipient.normalized_email == "synthetic.recipient@example.com"
    assert validate_form_delivery_records(isolated_session) == {
        "website_form_delivery_mode_revisions": 2,
        "website_form_recipient_revisions": 1,
        "form_submission_envelopes": 0,
        "form_delivery_outbox_records": 0,
        "form_delivery_attempts": 0,
        "form_delivery_configuration_audits": 3,
    }


def test_provider_owned_presentation_is_resolved_by_adapter_without_atlas_ledger(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component = _seed_form_component(isolated_session)
    disabled = create_form_delivery_mode_revision(
        isolated_session, website.id, _disabled_payload(component)
    )
    revision = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _provider_owned_payload(component, disabled.id),
    )

    def network_forbidden(*_args, **_kwargs):
        raise AssertionError("Provider-owned presentation attempted an Atlas request")

    monkeypatch.setattr(socket.socket, "connect", network_forbidden)
    presentation = resolve_provider_owned_presentation(
        isolated_session,
        revision,
        allow_test_only=True,
    )
    assert presentation.kind == "hosted_route"
    assert presentation.destination == "https://forms.example.com/estimate"
    assert presentation.approved_origin == "https://forms.example.com"
    assert presentation.title == "Request an estimate"
    assert presentation.ownership_disclosure == "Example Forms operates this form."
    assert presentation.sandbox_policy is None
    assert presentation.referrer_policy is None
    readiness = form_delivery_readiness(
        isolated_session,
        revision,
        allow_test_only=True,
    )
    assert readiness.can_present is True
    assert readiness.can_submit is False
    with pytest.raises(form_submission_gateway.FormGatewayError) as bypass:
        form_submission_gateway.preflight_form_gateway(
            isolated_session,
            website.id,
            component.id,
        )
    assert bypass.value.code == "atlas_gateway_not_used"
    assert isolated_session.exec(select(FormSubmissionEnvelope)).all() == []
    assert isolated_session.exec(select(FormDeliveryOutbox)).all() == []


def test_provider_owned_resolver_rejects_tamper_incompatibility_and_unsafe_config(
    isolated_session: Session,
) -> None:
    website, component = _seed_form_component(isolated_session)
    disabled = create_form_delivery_mode_revision(
        isolated_session, website.id, _disabled_payload(component)
    )
    incompatible = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _provider_owned_payload(
            component,
            disabled.id,
            adapter_version="future-v1",
        ),
    )
    with pytest.raises(FormDeliveryConfigurationError, match="incompatible"):
        resolve_provider_owned_presentation(
            isolated_session,
            incompatible,
            allow_test_only=True,
        )
    incompatible.integrity_fingerprint = "0" * 64
    with pytest.raises(FormDeliveryConfigurationError):
        resolve_provider_owned_presentation(
            isolated_session,
            incompatible,
            allow_test_only=True,
        )
    with pytest.raises(ValueError):
        _provider_owned_payload(
            component,
            disabled.id,
            approved_origin="https://unknown.example.com",
        )
    with pytest.raises(ValueError):
        _provider_owned_payload(
            component,
            disabled.id,
            presentation_strategy="sandboxed_iframe",
        )
    with pytest.raises(ValueError):
        _provider_owned_payload(
            component,
            disabled.id,
            privacy_policy_reference=None,
        )


def test_gateway_requires_explicit_mode_and_does_not_depend_on_theme_family(
    isolated_session: Session,
) -> None:
    website, component = _seed_form_component(isolated_session)
    with pytest.raises(form_submission_gateway.FormGatewayError) as missing:
        form_submission_gateway.preflight_form_gateway(
            isolated_session,
            website.id,
            component.id,
        )
    assert missing.value.code == "form_delivery_mode_not_found"
    with pytest.raises(FormDeliveryConfigurationError) as history_missing:
        read_form_delivery_mode_history(
            isolated_session,
            website.id,
            component.id,
        )
    assert history_missing.value.code == "form_delivery_mode_not_found"

    create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _disabled_payload(component),
    )
    with pytest.raises(form_submission_gateway.FormGatewayError) as disabled:
        form_submission_gateway.preflight_form_gateway(
            isolated_session,
            website.id,
            component.id,
        )
    assert disabled.value.code == "form_submission_disabled"


def test_gateway_on_known_0046_schema_fails_closed_without_querying_0047(
    isolated_session: Session,
) -> None:
    website, component = _seed_form_component(isolated_session)
    for table in reversed(FORM_DELIVERY_TABLES):
        isolated_session.exec(text(f"DROP TABLE {table}"))
    isolated_session.commit()

    with pytest.raises(form_submission_gateway.FormGatewayError) as missing:
        form_submission_gateway.preflight_form_gateway(
            isolated_session,
            website.id,
            component.id,
        )
    assert missing.value.code == "form_delivery_mode_not_found"
    with pytest.raises(FormDeliveryConfigurationError) as history_missing:
        read_form_delivery_mode_history(
            isolated_session,
            website.id,
            component.id,
        )
    assert history_missing.value.code == "form_delivery_mode_not_found"


def test_email_readiness_blocks_without_secure_store_then_passes_in_test(
    isolated_session: Session,
) -> None:
    _, _, _, email, _ = _seed_ready_email_mode(isolated_session)
    blocked = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=False,
    )
    assert blocked.can_submit is False
    assert "secure_payload_store_unavailable" in {
        item.code for item in blocked.blockers
    }
    ready = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    assert ready.status == "ready"
    assert ready.can_submit is True


def test_standalone_email_mode_is_ready_without_atlasops_registration(
    isolated_session: Session,
) -> None:
    _website, _component, _disabled, email, _recipient = _seed_ready_email_mode(
        isolated_session
    )
    assert FORM_DELIVERY_PROVIDER_REGISTRY.registration(
        SYNTHETIC_ATLASOPS360_KEY,
        allow_test_only=False,
    ) is None
    assert all(not name.startswith("atlasops360") for name in sys.modules)
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    assert readiness.status == "ready"
    assert readiness.can_submit is True


def test_mode_and_recipient_cross_website_scope_fail_closed(
    isolated_session: Session,
) -> None:
    website, component = _seed_form_component(isolated_session, website_name="One")
    other_website, other_component = _seed_form_component(
        isolated_session, website_name="Two"
    )
    predecessor = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _disabled_payload(component),
    )
    with pytest.raises(FormDeliveryConfigurationError):
        create_form_delivery_mode_revision(
            isolated_session,
            other_website.id,
            WebsiteFormDeliveryModeRevisionCreate(
                **{
                    **_email_payload(other_component, predecessor.id).model_dump(),
                    "form_instance_key": component.component_instance_key,
                }
            ),
        )
    email = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _email_payload(component, predecessor.id),
    )
    with pytest.raises(FormDeliveryConfigurationError, match="exact Website"):
        create_form_recipient_revision(
            isolated_session,
            other_website.id,
            WebsiteFormRecipientRevisionCreate(
                delivery_mode_revision_id=email.id,
                recipient_key="cross-website",
                email="cross.website@example.com",
                recipient_role="secondary",
                verification_status="unverified",
                created_by="test",
                updated_by="test",
                rationale="Cross-Website recipient must fail.",
            ),
        )


def test_same_website_recipient_from_another_form_cannot_satisfy_readiness(
    isolated_session: Session,
) -> None:
    website, component = _seed_form_component(isolated_session)
    other_component = WebsiteThemeComponentConfiguration(
        website_theme_configuration_id=component.website_theme_configuration_id,
        website_id=website.id,
        theme_family_version_id=component.theme_family_version_id,
        component_instance_key="compact-estimate-form:secondary",
        component_key="compact_estimate_form",
        component_contract_version=3,
        revision=1,
        scope_type="website_default",
        lifecycle_status="current",
        enabled=True,
        variant="compact-estimate-form",
        placement="secondary-cta",
        responsive_visibility={"desktop": True, "tablet": True, "mobile": True},
        configuration_payload={},
        created_by="test",
        updated_by="test",
        integrity_fingerprint="f" * 64,
    )
    isolated_session.add(other_component)
    isolated_session.commit()
    disabled = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _disabled_payload(component),
    )
    email = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _email_payload(component, disabled.id),
    )
    now = datetime.now(UTC)
    cross_form = WebsiteFormRecipientRevision(
        delivery_mode_revision_id=email.id,
        website_id=website.id,
        form_component_configuration_id=other_component.id,
        form_instance_key=other_component.component_instance_key,
        recipient_key="cross-form-primary",
        revision=1,
        email="cross.form@example.com",
        normalized_email="cross.form@example.com",
        label=None,
        recipient_role="primary",
        enabled=True,
        verification_status="verified",
        verified_at=now,
        verified_by="test",
        verification_method="synthetic_test",
        created_by="test",
        updated_by="test",
        integrity_fingerprint="0" * 64,
        created_at=now,
        updated_at=now,
    )
    cross_form.integrity_fingerprint = form_recipient_fingerprint(cross_form)
    isolated_session.add(cross_form)
    isolated_session.commit()
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    assert readiness.can_submit is False
    assert "blocked_missing_verified_recipient" in {
        blocker.code for blocker in readiness.blockers
    }
    with pytest.raises(FormDeliveryConfigurationError, match="scope"):
        validate_form_delivery_records(isolated_session)


def test_recipient_heads_support_same_mode_verification_and_direct_carry_forward(
    isolated_session: Session,
) -> None:
    website, component = _seed_form_component(isolated_session)
    disabled = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _disabled_payload(component),
    )
    email_v1 = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _email_payload(component, disabled.id),
    )
    recipient_v1 = create_form_recipient_revision(
        isolated_session,
        website.id,
        WebsiteFormRecipientRevisionCreate(
            delivery_mode_revision_id=email_v1.id,
            recipient_key="primary-office",
            email="synthetic.recipient@example.com",
            recipient_role="primary",
            verification_status="unverified",
            created_by="test",
            updated_by="test",
            rationale="Create an unverified synthetic recipient.",
        ),
    )
    recipient_v2 = create_form_recipient_revision(
        isolated_session,
        website.id,
        WebsiteFormRecipientRevisionCreate(
            delivery_mode_revision_id=email_v1.id,
            recipient_key="primary-office",
            supersedes_recipient_revision_id=recipient_v1.id,
            email="synthetic.recipient@example.com",
            recipient_role="primary",
            verification_status="verified",
            verified_at=datetime.now(UTC),
            verified_by="test-verifier",
            verification_method="synthetic_test",
            created_by="test",
            updated_by="test",
            rationale="Verify through an immutable same-mode recipient head.",
        ),
    )
    assert form_delivery_readiness(
        isolated_session,
        email_v1,
        allow_test_only=True,
        secure_payload_store_available=True,
    ).can_submit is True

    email_v2 = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _email_payload(component, email_v1.id),
    )
    recipient_v3 = create_form_recipient_revision(
        isolated_session,
        website.id,
        WebsiteFormRecipientRevisionCreate(
            delivery_mode_revision_id=email_v2.id,
            recipient_key="primary-office",
            supersedes_recipient_revision_id=recipient_v2.id,
            email="synthetic.recipient@example.com",
            recipient_role="primary",
            verification_status="verified",
            verified_at=datetime.now(UTC),
            verified_by="test-verifier",
            verification_method="synthetic_test",
            created_by="test",
            updated_by="test",
            rationale="Verify through a new immutable mode revision.",
        ),
    )
    assert (recipient_v1.revision, recipient_v2.revision, recipient_v3.revision) == (
        1,
        2,
        3,
    )
    assert recipient_v1.verification_status == "unverified"
    assert recipient_v2.delivery_mode_revision_id == email_v1.id
    assert recipient_v3.delivery_mode_revision_id == email_v2.id
    assert validate_form_delivery_records(isolated_session)[
        "website_form_recipient_revisions"
    ] == 3


def test_recipient_normalization_uniqueness_and_primary_preference_fail_closed(
    isolated_session: Session,
) -> None:
    website, component = _seed_form_component(isolated_session)
    disabled = create_form_delivery_mode_revision(
        isolated_session, website.id, _disabled_payload(component)
    )
    payload_values = _email_payload(component, disabled.id).model_dump()
    payload_values["configuration_payload"] = {
        **payload_values["configuration_payload"],
        "notification_preference": "primary_only",
    }
    payload = WebsiteFormDeliveryModeRevisionCreate.model_validate(payload_values)
    email = create_form_delivery_mode_revision(
        isolated_session, website.id, payload
    )
    create_form_recipient_revision(
        isolated_session,
        website.id,
        WebsiteFormRecipientRevisionCreate(
            delivery_mode_revision_id=email.id,
            recipient_key="secondary-office",
            email="Synthetic.Secondary@Example.com",
            recipient_role="secondary",
            verification_status="verified",
            verified_at=datetime.now(UTC),
            verified_by="test-verifier",
            verification_method="synthetic_test",
            created_by="test",
            updated_by="test",
            rationale="Secondary-only readiness fixture.",
        ),
    )
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    assert readiness.can_submit is False
    assert "blocked_missing_verified_recipient" in {
        blocker.code for blocker in readiness.blockers
    }
    with pytest.raises(FormDeliveryConfigurationError):
        create_form_recipient_revision(
            isolated_session,
            website.id,
            WebsiteFormRecipientRevisionCreate(
                delivery_mode_revision_id=email.id,
                recipient_key="duplicate-secondary",
                email="synthetic.secondary@example.COM",
                recipient_role="secondary",
                verification_status="unverified",
                created_by="test",
                updated_by="test",
                rationale="Duplicate normalized address must fail.",
            ),
        )
    with pytest.raises(ValueError):
        WebsiteFormRecipientRevisionCreate(
            delivery_mode_revision_id=email.id,
            recipient_key="invalid-address",
            email="not-an-email-address",
            recipient_role="secondary",
            verification_status="unverified",
            created_by="test",
            updated_by="test",
            rationale="Invalid email must fail.",
        )


def test_unverified_only_recipient_never_satisfies_email_readiness(
    isolated_session: Session,
) -> None:
    website, component = _seed_form_component(isolated_session)
    disabled = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _disabled_payload(component),
    )
    email = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _email_payload(component, disabled.id),
    )
    create_form_recipient_revision(
        isolated_session,
        website.id,
        WebsiteFormRecipientRevisionCreate(
            delivery_mode_revision_id=email.id,
            recipient_key="unverified-primary",
            email="unverified.primary@example.com",
            recipient_role="primary",
            enabled=True,
            verification_status="unverified",
            created_by="test",
            updated_by="test",
            rationale="Unverified-only readiness fixture.",
        ),
    )
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    assert readiness.can_submit is False
    assert "blocked_missing_verified_recipient" in {
        blocker.code for blocker in readiness.blockers
    }


def test_rehashed_duplicate_recipient_heads_fail_readiness_and_graph(
    isolated_session: Session,
) -> None:
    _website, _component, _disabled, email, existing = _seed_ready_email_mode(
        isolated_session
    )
    now = datetime.now(UTC)
    duplicate = WebsiteFormRecipientRevision(
        delivery_mode_revision_id=email.id,
        website_id=email.website_id,
        form_component_configuration_id=email.form_component_configuration_id,
        form_instance_key=email.form_instance_key,
        recipient_key="duplicate-current-head",
        revision=1,
        email=existing.email.swapcase(),
        normalized_email=existing.normalized_email,
        label=None,
        recipient_role="secondary",
        enabled=True,
        verification_status="verified",
        verified_at=now,
        verified_by="test",
        verification_method="synthetic_test",
        created_by="test",
        updated_by="test",
        integrity_fingerprint="0" * 64,
        created_at=now,
        updated_at=now,
    )
    duplicate.integrity_fingerprint = form_recipient_fingerprint(duplicate)
    isolated_session.add(duplicate)
    isolated_session.commit()
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    assert readiness.can_submit is False
    with pytest.raises(FormDeliveryConfigurationError, match="duplicate"):
        validate_form_delivery_records(isolated_session)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("transport_secret_reference", "raw-smtp-password"),
        ("smtp_password", "SyntheticSecret123!"),
        ("mailbox_password", "SyntheticMailboxSecret123!"),
    ),
)
def test_email_configuration_rejects_raw_mailbox_and_smtp_secrets(
    isolated_session: Session,
    field: str,
    value: str,
) -> None:
    website, component = _seed_form_component(isolated_session)
    disabled = create_form_delivery_mode_revision(
        isolated_session, website.id, _disabled_payload(component)
    )
    values = _email_payload(component, disabled.id).model_dump()
    values["configuration_payload"][field] = value
    with pytest.raises(ValueError):
        WebsiteFormDeliveryModeRevisionCreate.model_validate(values)


def test_create_services_revalidate_mutated_mode_and_recipient_dtos(
    isolated_session: Session,
) -> None:
    website, component = _seed_form_component(isolated_session)
    disabled_payload = _disabled_payload(component)
    disabled_payload.configuration_payload["smtp_password"] = "SyntheticSecret123!"
    with pytest.raises(FormDeliveryConfigurationError):
        create_form_delivery_mode_revision(
            isolated_session,
            website.id,
            disabled_payload,
        )
    valid_recipient = WebsiteFormRecipientRevisionCreate(
        delivery_mode_revision_id=999,
        recipient_key="mutated-recipient",
        email="synthetic.recipient@example.com",
        recipient_role="secondary",
        verification_status="unverified",
        created_by="test",
        updated_by="test",
        rationale="Mutation revalidation fixture.",
    )
    valid_recipient.email = "not-an-email-address"  # type: ignore[assignment]
    with pytest.raises(FormDeliveryConfigurationError):
        create_form_recipient_revision(
            isolated_session,
            website.id,
            valid_recipient,
        )


def test_transactional_outbox_is_idempotent_and_stores_no_plaintext_columns(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    normalized = _normalized_submission(website, component, email)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=readiness,
        envelope=normalized,
        payload_store=store,
        expires_at=expires_at,
    )
    duplicate = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=readiness,
        envelope=normalized,
        payload_store=store,
        expires_at=expires_at,
    )
    assert duplicate.id == outbox.id
    assert store.payload_count == 1
    with pytest.raises(FormDeliveryIdempotencyConflict):
        enqueue_form_delivery(
            isolated_session,
            mode_revision=email,
            readiness=readiness,
            envelope=NormalizedSubmissionEnvelope(
                **{
                    **normalized.__dict__,
                    "request_identity": "b" * 64,
                }
            ),
            payload_store=store,
            expires_at=expires_at,
        )
    assert store.payload_count == 1
    adapter = _test_delivery_adapter()
    original_deliver = adapter.deliver
    context_observed = False

    def inspect_context(context, envelope):
        nonlocal context_observed
        context_observed = True
        assert isinstance(envelope, NormalizedSubmissionEnvelope)
        assert context.mode == "atlas_email"
        assert context.provider_key == SYNTHETIC_EMAIL_PROVIDER_KEY
        assert context.adapter_version == "test-v1"
        assert context.destination_identity == email.destination_identity
        assert context.configuration_references == (
            ("transport_key_reference", "synthetic-mail"),
            (
                "transport_secret_reference",
                "secret-ref://synthetic/mail-transport",
            ),
        )
        assert tuple(item.normalized_email for item in context.recipients) == (
            "synthetic.recipient@example.com",
        )
        assert context.delivery_identity == isolated_session.get(
            FormSubmissionEnvelope, outbox.envelope_id
        ).integrity_fingerprint
        return original_deliver(context, envelope)

    monkeypatch.setattr(adapter, "deliver", inspect_context)
    attempt = process_form_delivery_outbox(
        isolated_session,
        outbox.id,
        payload_store=store,
        allow_test_only=True,
        transient_retry_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert attempt.outcome == "delivered"
    assert context_observed is True
    assert adapter.last_envelope_contract == "NormalizedSubmissionEnvelope"
    assert not hasattr(adapter, "last_context")
    assert store.payload_count == 0
    assert isolated_session.get(FormDeliveryOutbox, outbox.id).status == "delivered"
    assert len(isolated_session.exec(select(FormSubmissionEnvelope)).all()) == 1
    assert len(isolated_session.exec(select(FormDeliveryAttempt)).all()) == 1
    plaintext_fields = {
        "name",
        "phone",
        "postal_code",
        "requested_service",
        "message",
        "raw_body",
        "recipient_list",
        "payload",
    }
    for model in (FormSubmissionEnvelope, FormDeliveryOutbox, FormDeliveryAttempt):
        assert plaintext_fields.isdisjoint(model.model_fields)
    assert validate_form_delivery_records(isolated_session)[
        "form_delivery_attempts"
    ] == 1


def test_atlasops_adapter_receives_shared_normalized_contract_and_scoped_context(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component = _seed_form_component(isolated_session)
    disabled = create_form_delivery_mode_revision(
        isolated_session, website.id, _disabled_payload(component)
    )
    mode = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        WebsiteFormDeliveryModeRevisionCreate(
            form_component_configuration_id=component.id,
            form_instance_key=component.component_instance_key,
            supersedes_delivery_mode_revision_id=disabled.id,
            mode="atlasops360_native",
            enabled=True,
            provider_key=SYNTHETIC_ATLASOPS360_KEY,
            adapter_version="test-v1",
            destination_identity="binding-ref://synthetic/workspace",
            configuration_payload={
                "workspace_binding_reference": "binding-ref://synthetic/workspace",
                "adapter_configuration_reference": "binding-ref://synthetic/adapter",
                "consent_required": False,
            },
            privacy_policy_reference="/privacy",
            retention_policy_reference="policy-ref://synthetic/retention",
            abuse_policy_reference="policy-ref://synthetic/abuse",
            success_behavior="Show a generic success message.",
            failure_behavior="Show a generic failure message.",
            idempotency_policy_reference="policy-ref://synthetic/idempotency",
            audit_identity="test-atlasops-audit",
            created_by="test",
            updated_by="test",
            rationale="Synthetic AtlasOps360 adapter context test.",
            **_active_evidence(),
        ),
    )
    assert mode.website_id == website.id
    assert mode.form_component_configuration_id == component.id
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    readiness = form_delivery_readiness(
        isolated_session,
        mode,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    assert readiness.can_submit is True
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=mode,
        readiness=readiness,
        envelope=_normalized_submission(website, component, mode),
        payload_store=store,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    registration = FORM_DELIVERY_PROVIDER_REGISTRY.registration(
        SYNTHETIC_ATLASOPS360_KEY,
        allow_test_only=True,
    )
    assert registration is not None and registration.delivery_adapter is not None
    adapter = registration.delivery_adapter
    original_deliver = adapter.deliver
    observed = False

    def inspect_context(context, envelope):
        nonlocal observed
        observed = True
        assert isinstance(envelope, NormalizedSubmissionEnvelope)
        assert context.mode == "atlasops360_native"
        assert context.recipients == ()
        assert context.configuration_references == (
            ("workspace_binding_reference", "binding-ref://synthetic/workspace"),
            ("adapter_configuration_reference", "binding-ref://synthetic/adapter"),
        )
        return original_deliver(context, envelope)

    monkeypatch.setattr(adapter, "deliver", inspect_context)
    attempt = process_form_delivery_outbox(
        isolated_session,
        outbox.id,
        payload_store=store,
        allow_test_only=True,
        transient_retry_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert observed is True
    assert attempt.outcome == "delivered"


def test_delivery_time_registry_descriptor_drift_fails_before_adapter(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=form_delivery_readiness(
            isolated_session,
            email,
            allow_test_only=True,
            secure_payload_store_available=True,
        ),
        envelope=_normalized_submission(website, component, email),
        payload_store=store,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    registration = FORM_DELIVERY_PROVIDER_REGISTRY.registration(
        SYNTHETIC_EMAIL_PROVIDER_KEY,
        allow_test_only=True,
    )
    assert registration is not None and registration.delivery_adapter is not None
    adapter = registration.delivery_adapter
    deliveries_before = adapter.delivery_count
    drifted_descriptor = ProviderDescriptor(
        **{
            **registration.descriptor.__dict__,
            "adapter_version": "drifted-v2",
        }
    )
    drifted_registration = ProviderRegistration(
        descriptor=drifted_descriptor,
        delivery_adapter=adapter,
    )
    original_registration = FORM_DELIVERY_PROVIDER_REGISTRY.registration

    def drifted_lookup(provider_key: str, *, allow_test_only: bool = False):
        if provider_key == SYNTHETIC_EMAIL_PROVIDER_KEY and allow_test_only:
            return drifted_registration
        return original_registration(
            provider_key,
            allow_test_only=allow_test_only,
        )

    monkeypatch.setattr(
        FORM_DELIVERY_PROVIDER_REGISTRY,
        "registration",
        drifted_lookup,
    )
    try:
        with pytest.raises(FormDeliveryOutboxError, match="adapter is unavailable"):
            process_form_delivery_outbox(
                isolated_session,
                outbox.id,
                payload_store=store,
                allow_test_only=True,
                transient_retry_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        assert adapter.delivery_count == deliveries_before
        assert store.payload_count == 1
    finally:
        store.clear()


def test_post_put_failure_rolls_back_envelope_outbox_and_payload(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    store = InMemoryTestPayloadStore(test_environment_allowed=True)

    def forced_flush_failure(*_args, **_kwargs):
        raise IntegrityError("forced post-put failure", {}, RuntimeError("forced"))

    with monkeypatch.context() as patch:
        patch.setattr(isolated_session, "flush", forced_flush_failure)
        with pytest.raises(FormDeliveryOutboxError):
            enqueue_form_delivery(
                isolated_session,
                mode_revision=email,
                readiness=readiness,
                envelope=_normalized_submission(website, component, email),
                payload_store=store,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
    assert store.payload_count == 0
    assert isolated_session.exec(select(FormSubmissionEnvelope)).all() == []
    assert isolated_session.exec(select(FormDeliveryOutbox)).all() == []


def test_forged_prior_readiness_cannot_enqueue_tampered_mode(
    isolated_session: Session,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    prior_ready = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    email.integrity_fingerprint = "0" * 64
    isolated_session.add(email)
    isolated_session.commit()
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    with pytest.raises(FormDeliveryOutboxError, match="Authoritative"):
        enqueue_form_delivery(
            isolated_session,
            mode_revision=email,
            readiness=prior_ready,
            envelope=_normalized_submission(website, component, email),
            payload_store=store,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    assert store.payload_count == 0
    assert isolated_session.exec(select(FormSubmissionEnvelope)).all() == []


def test_superseded_mode_rejects_new_submission_and_recipient(
    isolated_session: Session,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    prior_ready = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    disabled_values = _disabled_payload(component).model_dump()
    disabled_values["supersedes_delivery_mode_revision_id"] = email.id
    create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        WebsiteFormDeliveryModeRevisionCreate.model_validate(disabled_values),
    )
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    with pytest.raises(FormDeliveryOutboxError, match="superseded"):
        enqueue_form_delivery(
            isolated_session,
            mode_revision=email,
            readiness=prior_ready,
            envelope=_normalized_submission(website, component, email),
            payload_store=store,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    with pytest.raises(FormDeliveryConfigurationError, match="frozen"):
        create_form_recipient_revision(
            isolated_session,
            website.id,
            WebsiteFormRecipientRevisionCreate(
                delivery_mode_revision_id=email.id,
                recipient_key="late-recipient",
                email="late.recipient@example.com",
                recipient_role="secondary",
                verification_status="unverified",
                created_by="test",
                updated_by="test",
                rationale="Superseded snapshot mutation must fail.",
            ),
        )
    assert store.payload_count == 0


@pytest.mark.parametrize(
    "tamper_case",
    ("before_mode", "after_first_submission", "after_successor"),
)
def test_recipient_chronology_tamper_fails_graph_validation(
    isolated_session: Session,
    tamper_case: str,
) -> None:
    website, component, _, email, recipient = _seed_ready_email_mode(
        isolated_session
    )
    if tamper_case == "before_mode":
        tampered_at = email.created_at - timedelta(seconds=1)
    elif tamper_case == "after_first_submission":
        store = InMemoryTestPayloadStore(test_environment_allowed=True)
        enqueue_form_delivery(
            isolated_session,
            mode_revision=email,
            readiness=form_delivery_readiness(
                isolated_session,
                email,
                allow_test_only=True,
                secure_payload_store_available=True,
            ),
            envelope=_normalized_submission(website, component, email),
            payload_store=store,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        first = isolated_session.exec(select(FormSubmissionEnvelope)).one()
        tampered_at = first.received_at + timedelta(seconds=1)
    else:
        successor_values = _disabled_payload(component).model_dump()
        successor_values["supersedes_delivery_mode_revision_id"] = email.id
        successor = create_form_delivery_mode_revision(
            isolated_session,
            website.id,
            WebsiteFormDeliveryModeRevisionCreate.model_validate(successor_values),
        )
        tampered_at = successor.created_at + timedelta(seconds=1)
    recipient.created_at = tampered_at
    recipient.updated_at = tampered_at
    isolated_session.add(recipient)
    isolated_session.commit()
    with pytest.raises(FormDeliveryConfigurationError, match="recipient"):
        validate_form_delivery_records(isolated_session)


def test_consent_required_blocks_before_storage_without_acceptance_and_version(
    isolated_session: Session,
) -> None:
    website, component = _seed_form_component(isolated_session)
    disabled = create_form_delivery_mode_revision(
        isolated_session, website.id, _disabled_payload(component)
    )
    payload_values = _email_payload(component, disabled.id).model_dump()
    payload_values["configuration_payload"] = {
        **payload_values["configuration_payload"],
        "consent_required": True,
    }
    payload_values["consent_policy_reference"] = (
        "policy-ref://synthetic/consent-v1"
    )
    payload = WebsiteFormDeliveryModeRevisionCreate.model_validate(payload_values)
    email = create_form_delivery_mode_revision(isolated_session, website.id, payload)
    create_form_recipient_revision(
        isolated_session,
        website.id,
        WebsiteFormRecipientRevisionCreate(
            delivery_mode_revision_id=email.id,
            recipient_key="primary-office",
            email="synthetic.recipient@example.com",
            recipient_role="primary",
            verification_status="verified",
            verified_at=datetime.now(UTC),
            verified_by="test-verifier",
            verification_method="synthetic_test",
            created_by="test",
            updated_by="test",
            rationale="Consent-mode verified recipient.",
        ),
    )
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    with pytest.raises(FormDeliveryOutboxError, match="consent"):
        enqueue_form_delivery(
            isolated_session,
            mode_revision=email,
            readiness=readiness,
            envelope=_normalized_submission(website, component, email),
            payload_store=store,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    assert store.payload_count == 0
    accepted = _normalized_submission(website, component, email)
    accepted = NormalizedSubmissionEnvelope(
        **{
            **accepted.__dict__,
            "consent_accepted": True,
            "consent_version": "consent-v1",
        }
    )
    queued = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=readiness,
        envelope=accepted,
        payload_store=store,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert queued.status == "queued"


def test_unsafe_request_payload_and_key_references_are_rejected(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    with pytest.raises(ValueError, match="request identity"):
        _normalized_submission(
            website,
            component,
            email,
            request_identity="Synthetic Person +14075550100",
        )
    monkeypatch.setattr(store, "encryption_key_reference", "raw-secret-value")
    with pytest.raises(FormDeliveryOutboxError, match="key identity"):
        enqueue_form_delivery(
            isolated_session,
            mode_revision=email,
            readiness=readiness,
            envelope=_normalized_submission(website, component, email),
            payload_store=store,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    monkeypatch.setattr(
        store,
        "encryption_key_reference",
        "secret-ref://synthetic/form-payload-key",
    )
    monkeypatch.setattr(
        store,
        "put",
        lambda _envelope: "memory://form-payload/Synthetic Person",
    )
    with pytest.raises(FormDeliveryOutboxError, match="opaque reference"):
        enqueue_form_delivery(
            isolated_session,
            mode_revision=email,
            readiness=readiness,
            envelope=_normalized_submission(website, component, email),
            payload_store=store,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )


@pytest.mark.parametrize(
    ("field", "unsafe_value", "message"),
    (
        ("audit_identity", "Synthetic Person", "audit identity"),
        ("anti_spam_decision", "Synthetic message", "anti-spam decision"),
        ("consent_version", "smtp_password=raw-secret", "consent version"),
        ("source_page_identity", "Synthetic Person / estimate", "source page"),
        ("destination_adapter_key", "smtp password", "destination adapter"),
    ),
)
def test_normalized_envelope_rejects_customer_or_secret_text_in_metadata(
    isolated_session: Session,
    field: str,
    unsafe_value: str,
    message: str,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    envelope = _normalized_submission(website, component, email)
    with pytest.raises(ValueError, match=message):
        NormalizedSubmissionEnvelope(
            **{
                **envelope.__dict__,
                field: unsafe_value,
            }
        )


def test_enqueue_binds_safe_envelope_metadata_to_exact_mode(
    isolated_session: Session,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    envelope = _normalized_submission(website, component, email)
    tampered = NormalizedSubmissionEnvelope(
        **{
            **envelope.__dict__,
            "audit_identity": "different-safe-audit",
        }
    )
    with pytest.raises(FormDeliveryOutboxError, match="governed scope"):
        enqueue_form_delivery(
            isolated_session,
            mode_revision=email,
            readiness=readiness,
            envelope=tampered,
            payload_store=store,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    assert store.payload_count == 0


def test_test_payload_and_transport_reject_active_style_session_bind(
    isolated_session: Session,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    active_style_engine = create_engine("sqlite:///atlas.db")
    try:
        with Session(active_style_engine) as active_style_session:
            with pytest.raises(FormDeliveryOutboxError, match="disposable Session"):
                enqueue_form_delivery(
                    active_style_session,
                    mode_revision=email,
                    readiness=readiness,
                    envelope=_normalized_submission(website, component, email),
                    payload_store=store,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            with pytest.raises(FormDeliveryOutboxError, match="disposable Session"):
                process_form_delivery_outbox(
                    active_style_session,
                    1,
                    payload_store=store,
                    allow_test_only=True,
                    transient_retry_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            with pytest.raises(FormDeliveryOutboxError, match="disposable Session"):
                expire_form_delivery_payload(
                    active_style_session,
                    1,
                    payload_store=store,
                    now=datetime.now(UTC),
                )
    finally:
        active_style_engine.dispose()
        store.clear()
    assert store.payload_count == 0


def test_transient_failure_retries_then_delivers_without_network(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=readiness,
        envelope=_normalized_submission(website, component, email),
        payload_store=store,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    adapter = _test_delivery_adapter()

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("The synthetic delivery adapter attempted network I/O")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(adapter, "outcome", "transient_failure")
    attempt_at = datetime.now(UTC)
    retry_at = attempt_at + timedelta(minutes=5)
    deliveries_before = adapter.delivery_count
    first = process_form_delivery_outbox(
        isolated_session,
        outbox.id,
        payload_store=store,
        allow_test_only=True,
        transient_retry_at=retry_at,
        now=attempt_at,
    )
    refreshed = isolated_session.get(FormDeliveryOutbox, outbox.id)
    assert first.outcome == "transient_failure"
    assert first.next_retry_at is not None
    assert _utc_value(first.next_retry_at) == retry_at
    assert refreshed is not None and refreshed.status == "retrying"
    assert refreshed.next_attempt_at is not None
    assert _utc_value(refreshed.next_attempt_at) == retry_at
    assert store.payload_count == 1

    with pytest.raises(FormDeliveryOutboxError, match="not due"):
        process_form_delivery_outbox(
            isolated_session,
            outbox.id,
            payload_store=store,
            allow_test_only=True,
            transient_retry_at=retry_at + timedelta(minutes=5),
            now=attempt_at + timedelta(minutes=1),
        )
    assert adapter.delivery_count == deliveries_before + 1

    monkeypatch.setattr(adapter, "outcome", "delivered")
    second = process_form_delivery_outbox(
        isolated_session,
        outbox.id,
        payload_store=store,
        allow_test_only=True,
        transient_retry_at=retry_at + timedelta(minutes=5),
        now=retry_at,
    )
    refreshed = isolated_session.get(FormDeliveryOutbox, outbox.id)
    assert (first.attempt_number, second.attempt_number) == (1, 2)
    assert refreshed is not None and refreshed.status == "delivered"
    assert refreshed.attempt_count == 2
    assert store.payload_count == 0
    assert adapter.delivery_count == deliveries_before + 2


def test_post_delivery_commit_failure_retries_one_external_delivery(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=readiness,
        envelope=_normalized_submission(website, component, email),
        payload_store=store,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    adapter = _test_delivery_adapter()
    monkeypatch.setattr(adapter, "outcome", "delivered")
    deliveries_before = adapter.delivery_count
    attempt_at = datetime.now(UTC)

    with monkeypatch.context() as patch:
        patch.setattr(
            isolated_session,
            "commit",
            lambda: (_ for _ in ()).throw(RuntimeError("forced commit failure")),
        )
        with pytest.raises(FormDeliveryOutboxError, match="persistence failed"):
            process_form_delivery_outbox(
                isolated_session,
                outbox.id,
                payload_store=store,
                allow_test_only=True,
                transient_retry_at=attempt_at + timedelta(minutes=5),
                now=attempt_at,
            )

    assert adapter.delivery_count == deliveries_before + 1
    assert store.payload_count == 1
    assert isolated_session.exec(select(FormDeliveryAttempt)).all() == []
    retried = process_form_delivery_outbox(
        isolated_session,
        outbox.id,
        payload_store=store,
        allow_test_only=True,
        transient_retry_at=attempt_at + timedelta(minutes=6),
        now=attempt_at + timedelta(minutes=1),
    )
    assert retried.outcome == "delivered"
    assert adapter.delivery_count == deliveries_before + 1
    assert store.payload_count == 0


def test_permanent_failure_stops_retry_and_deletes_payload(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=readiness,
        envelope=_normalized_submission(website, component, email),
        payload_store=store,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    monkeypatch.setattr(_test_delivery_adapter(), "outcome", "permanent_failure")
    attempt = process_form_delivery_outbox(
        isolated_session,
        outbox.id,
        payload_store=store,
        allow_test_only=True,
        transient_retry_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    refreshed = isolated_session.get(FormDeliveryOutbox, outbox.id)
    assert attempt.outcome == "permanent_failure"
    assert attempt.next_retry_at is None
    assert refreshed is not None and refreshed.status == "terminal_failed"
    assert refreshed.next_attempt_at is None
    assert store.payload_count == 0


def test_adapter_exception_is_redacted_from_attempt_and_logs(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=form_delivery_readiness(
            isolated_session,
            email,
            allow_test_only=True,
            secure_payload_store_available=True,
        ),
        envelope=_normalized_submission(website, component, email),
        payload_store=store,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    customer_values = (
        "Synthetic Person",
        "+14075550100",
        "Synthetic message",
        "raw-smtp-password",
    )

    def fail_with_sensitive_exception(_context, _envelope):
        raise RuntimeError(" ".join(customer_values))

    monkeypatch.setattr(_test_delivery_adapter(), "deliver", fail_with_sensitive_exception)
    with caplog.at_level("DEBUG"):
        attempt = process_form_delivery_outbox(
            isolated_session,
            outbox.id,
            payload_store=store,
            allow_test_only=True,
            transient_retry_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    assert attempt.outcome == "permanent_failure"
    assert attempt.safe_error_code == "adapter_contract_failure"
    durable = str(attempt.model_dump()) + str(
        isolated_session.get(FormDeliveryOutbox, outbox.id).model_dump()
    )
    for value in customer_values:
        assert value not in durable
        assert value not in caplog.text
    with pytest.raises(FormDeliveryOutboxError):
        process_form_delivery_outbox(
            isolated_session,
            outbox.id,
            payload_store=store,
            allow_test_only=True,
            transient_retry_at=datetime.now(UTC) + timedelta(minutes=10),
        )


def test_retention_expiration_is_deterministic(
    isolated_session: Session,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    received_at = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    expires_at = received_at + timedelta(hours=1)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=readiness,
        envelope=_normalized_submission(
            website,
            component,
            email,
            received_at=received_at,
        ),
        payload_store=store,
        expires_at=expires_at,
    )
    adapter = _test_delivery_adapter()
    deliveries_before = adapter.delivery_count
    with pytest.raises(FormDeliveryOutboxError, match="expired"):
        process_form_delivery_outbox(
            isolated_session,
            outbox.id,
            payload_store=store,
            allow_test_only=True,
            transient_retry_at=expires_at + timedelta(minutes=5),
            now=expires_at,
        )
    assert adapter.delivery_count == deliveries_before
    assert store.payload_count == 1
    with pytest.raises(FormDeliveryOutboxError):
        expire_form_delivery_payload(
            isolated_session,
            outbox.id,
            payload_store=store,
            now=expires_at - timedelta(microseconds=1),
        )
    expired = expire_form_delivery_payload(
        isolated_session,
        outbox.id,
        payload_store=store,
        now=expires_at,
    )
    assert expired.status == "expired"
    assert expired.expired_at is not None
    assert _utc_value(expired.expired_at) == expires_at
    assert store.payload_count == 0


def test_expiration_commit_failure_preserves_payload_and_queued_state(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    received_at = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    expires_at = received_at + timedelta(hours=1)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=form_delivery_readiness(
            isolated_session,
            email,
            allow_test_only=True,
            secure_payload_store_available=True,
        ),
        envelope=_normalized_submission(
            website, component, email, received_at=received_at
        ),
        payload_store=store,
        expires_at=expires_at,
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            isolated_session,
            "commit",
            lambda: (_ for _ in ()).throw(RuntimeError("forced expiration commit")),
        )
        with pytest.raises(FormDeliveryOutboxError, match="persistence failed"):
            expire_form_delivery_payload(
                isolated_session,
                outbox.id,
                payload_store=store,
                now=expires_at,
            )
    persisted = isolated_session.get(FormDeliveryOutbox, outbox.id)
    assert persisted is not None and persisted.status == "queued"
    assert persisted.expired_at is None
    assert store.payload_count == 1


def test_expiration_cleanup_failure_is_retryable_without_terminal_corruption(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    received_at = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    expires_at = received_at + timedelta(hours=1)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=form_delivery_readiness(
            isolated_session,
            email,
            allow_test_only=True,
            secure_payload_store_available=True,
        ),
        envelope=_normalized_submission(
            website, component, email, received_at=received_at
        ),
        payload_store=store,
        expires_at=expires_at,
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            store,
            "delete",
            lambda _reference: (_ for _ in ()).throw(RuntimeError("forced cleanup")),
        )
        with pytest.raises(FormDeliveryOutboxError, match="cleanup is pending"):
            expire_form_delivery_payload(
                isolated_session,
                outbox.id,
                payload_store=store,
                now=expires_at,
            )
    persisted = isolated_session.get(FormDeliveryOutbox, outbox.id)
    assert persisted is not None and persisted.status == "expired"
    assert persisted.expired_at is not None
    assert _utc_value(persisted.expired_at) == expires_at
    assert persisted.delivered_at is None and persisted.failed_at is None
    assert store.payload_count == 1
    retried = expire_form_delivery_payload(
        isolated_session,
        outbox.id,
        payload_store=store,
        now=expires_at + timedelta(minutes=1),
    )
    assert retried.status == "expired"
    assert store.payload_count == 0


@pytest.mark.parametrize(
    ("adapter_outcome", "terminal_status", "evidence_field"),
    (
        ("delivered", "delivered", "delivered_at"),
        ("permanent_failure", "terminal_failed", "failed_at"),
    ),
)
def test_expiration_preserves_existing_terminal_state(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    adapter_outcome: str,
    terminal_status: str,
    evidence_field: str,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    received_at = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    expires_at = received_at + timedelta(hours=1)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=form_delivery_readiness(
            isolated_session,
            email,
            allow_test_only=True,
            secure_payload_store_available=True,
        ),
        envelope=_normalized_submission(
            website, component, email, received_at=received_at
        ),
        payload_store=store,
        expires_at=expires_at,
    )
    monkeypatch.setattr(_test_delivery_adapter(), "outcome", adapter_outcome)
    process_form_delivery_outbox(
        isolated_session,
        outbox.id,
        payload_store=store,
        allow_test_only=True,
        transient_retry_at=received_at + timedelta(minutes=5),
        now=received_at,
    )
    terminal = isolated_session.get(FormDeliveryOutbox, outbox.id)
    assert terminal is not None
    evidence = getattr(terminal, evidence_field)
    expired = expire_form_delivery_payload(
        isolated_session,
        outbox.id,
        payload_store=store,
        now=expires_at,
    )
    assert expired.status == terminal_status
    assert getattr(expired, evidence_field) == evidence
    assert expired.expired_at is None


def test_expiration_rejects_processing_and_expires_retrying(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    readiness = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=True,
    )
    received_at = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    expires_at = received_at + timedelta(hours=1)
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=readiness,
        envelope=_normalized_submission(
            website, component, email, received_at=received_at
        ),
        payload_store=store,
        expires_at=expires_at,
    )
    monkeypatch.setattr(_test_delivery_adapter(), "outcome", "transient_failure")
    process_form_delivery_outbox(
        isolated_session,
        outbox.id,
        payload_store=store,
        allow_test_only=True,
        transient_retry_at=received_at + timedelta(minutes=5),
        now=received_at,
    )
    expired = expire_form_delivery_payload(
        isolated_session,
        outbox.id,
        payload_store=store,
        now=expires_at,
    )
    assert expired.status == "expired"
    assert expired.next_attempt_at is None

    second_store = InMemoryTestPayloadStore(test_environment_allowed=True)
    second = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=readiness,
        envelope=_normalized_submission(
            website,
            component,
            email,
            idempotency_key="synthetic-idempotency-key-processing",
            request_identity="c" * 64,
            received_at=received_at,
        ),
        payload_store=second_store,
        expires_at=expires_at,
    )
    second.status = "processing"
    second.state_version += 1
    isolated_session.add(second)
    isolated_session.commit()
    with pytest.raises(FormDeliveryOutboxError, match="cannot be expired"):
        expire_form_delivery_payload(
            isolated_session,
            second.id,
            payload_store=second_store,
            now=expires_at,
        )
    assert second_store.payload_count == 1


def test_adapter_reference_is_domain_separated_before_persistence(
    isolated_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=form_delivery_readiness(
            isolated_session,
            email,
            allow_test_only=True,
            secure_payload_store_available=True,
        ),
        envelope=_normalized_submission(website, component, email),
        payload_store=store,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    malicious = "Synthetic Person +14075550100 Synthetic message"
    monkeypatch.setattr(
        _test_delivery_adapter(),
        "deliver",
        lambda _context, _envelope: DeliveryAttemptResult(
            outcome="delivered",
            safe_provider_reference=malicious,
        ),
    )
    attempt = process_form_delivery_outbox(
        isolated_session,
        outbox.id,
        payload_store=store,
        allow_test_only=True,
        transient_retry_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert attempt.safe_provider_reference is not None
    assert len(attempt.safe_provider_reference) == 64
    assert set(attempt.safe_provider_reference) <= set("0123456789abcdef")
    assert malicious not in str(attempt.model_dump())


def test_database_terminal_and_retry_evidence_is_exclusive(
    isolated_session: Session,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    store = InMemoryTestPayloadStore(test_environment_allowed=True)
    outbox = enqueue_form_delivery(
        isolated_session,
        mode_revision=email,
        readiness=form_delivery_readiness(
            isolated_session,
            email,
            allow_test_only=True,
            secure_payload_store_available=True,
        ),
        envelope=_normalized_submission(website, component, email),
        payload_store=store,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    with pytest.raises(IntegrityError):
        isolated_session.exec(
            text(
                "UPDATE formdeliveryoutbox SET delivered_at = :now "
                "WHERE id = :id"
            ),
            params={"now": datetime.now(UTC), "id": outbox.id},
        )
        isolated_session.commit()
    isolated_session.rollback()
    with pytest.raises(IntegrityError):
        isolated_session.exec(
            text(
                "UPDATE formdeliveryoutbox SET status = 'retrying' "
                "WHERE id = :id"
            ),
            params={"id": outbox.id},
        )
        isolated_session.commit()
    isolated_session.rollback()


def test_missing_key_management_blocks_before_storage(
    isolated_session: Session,
) -> None:
    website, component, _, email, _ = _seed_ready_email_mode(isolated_session)
    blocked = form_delivery_readiness(
        isolated_session,
        email,
        allow_test_only=True,
        secure_payload_store_available=False,
    )
    assert blocked.can_submit is False
    with pytest.raises(FormDeliveryOutboxError):
        enqueue_form_delivery(
            isolated_session,
            mode_revision=email,
            readiness=blocked,
            envelope=_normalized_submission(website, component, email),
            payload_store=UnavailableProductionPayloadStore(),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    assert isolated_session.exec(select(FormSubmissionEnvelope)).all() == []
    assert isolated_session.exec(select(FormDeliveryOutbox)).all() == []


@pytest.mark.parametrize(
    ("mode", "provider_key", "destination_identity", "configuration_payload", "blocker"),
    (
        (
            "provider_owned",
            "missing-provider-owned",
            "https://forms.example.test/estimate",
            {
                "presentation_strategy": "hosted_route",
                "approved_https_destination": "https://forms.example.test/estimate",
                "approved_origin": "https://forms.example.test",
                "accessibility_title": "Request an estimate",
                "ownership_disclosure": "The synthetic provider operates this form.",
                "destination_verified_by": "test-verifier",
                "destination_verified_at": "2026-08-17T12:00:00Z",
            },
            "provider_presentation_unavailable",
        ),
        (
            "atlasops360_native",
            "atlasops360-unavailable",
            "binding-ref://synthetic/workspace",
            {
                "workspace_binding_reference": "binding-ref://synthetic/workspace",
                "adapter_configuration_reference": "binding-ref://synthetic/adapter",
                "consent_required": True,
            },
            "provider_adapter_unavailable",
        ),
        (
            "external_adapter",
            "external-adapter-unavailable",
            "destination-ref://synthetic/provider",
            {
                "adapter_configuration_reference": "destination-ref://synthetic/adapter",
                "adapter_secret_reference": "secret-ref://synthetic/external-adapter",
                "consent_required": False,
            },
            "provider_adapter_unavailable",
        ),
    ),
)
def test_optional_provider_modes_fail_closed_without_installed_adapter(
    isolated_session: Session,
    mode: str,
    provider_key: str,
    destination_identity: str,
    configuration_payload: dict[str, object],
    blocker: str,
) -> None:
    website, component = _seed_form_component(isolated_session)
    disabled = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        _disabled_payload(component),
    )
    atlas_owned = mode != "provider_owned"
    revision = create_form_delivery_mode_revision(
        isolated_session,
        website.id,
        WebsiteFormDeliveryModeRevisionCreate(
            form_component_configuration_id=component.id,
            form_instance_key=component.component_instance_key,
            supersedes_delivery_mode_revision_id=disabled.id,
            mode=mode,
            enabled=True,
            provider_key=provider_key,
            adapter_version="future-v1",
            destination_identity=destination_identity,
            configuration_payload=configuration_payload,
            privacy_policy_reference=(
                "/privacy" if atlas_owned else "/provider-privacy"
            ),
            consent_policy_reference=(
                "policy-ref://synthetic/consent"
                if configuration_payload.get("consent_required") is True
                else None
            ),
            retention_policy_reference=(
                "policy-ref://synthetic/retention" if atlas_owned else None
            ),
            abuse_policy_reference=(
                "policy-ref://synthetic/abuse" if atlas_owned else None
            ),
            success_behavior=(
                "Show a generic success message." if atlas_owned else None
            ),
            failure_behavior=(
                "Show a generic failure message." if atlas_owned else None
            ),
            idempotency_policy_reference=(
                "policy-ref://synthetic/idempotency" if atlas_owned else None
            ),
            audit_identity=f"test-{mode}-audit",
            created_by="test",
            updated_by="test",
            rationale=f"Synthetic {mode} missing-adapter decision.",
            **_active_evidence(),
        ),
    )
    readiness = form_delivery_readiness(
        isolated_session,
        revision,
        secure_payload_store_available=True,
    )
    assert readiness.can_submit is False
    assert blocker in {item.code for item in readiness.blockers}
    assert isolated_session.exec(select(FormSubmissionEnvelope)).all() == []
    assert isolated_session.exec(select(FormDeliveryOutbox)).all() == []
