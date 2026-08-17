from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import unicodedata
from typing import Any, Mapping

from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import (
    FormDeliveryAttempt,
    FormDeliveryConfigurationAudit,
    FormDeliveryOutbox,
    FormSubmissionEnvelope,
    Website,
    WebsiteFormDeliveryModeRevision,
    WebsiteFormRecipientRevision,
    WebsiteThemeComponentConfiguration,
)
from app.schemas.form_delivery import (
    FormDeliveryOperatorReviewRead,
    FormDeliveryReadinessBlockerRead,
    FormDeliveryReadinessRead,
    WebsiteFormDeliveryModeRevisionCreate,
    WebsiteFormDeliveryModeRevisionRead,
    WebsiteFormRecipientRevisionCreate,
    validate_mode_configuration,
)
from app.services.form_delivery_registry import FORM_DELIVERY_PROVIDER_REGISTRY
from app.website_builder_core.configuration_safety import (
    FINGERPRINT_PATTERN,
    KEY_PATTERN,
    SECRET_REFERENCE_PATTERN,
    SOURCE_REFERENCE_PATTERN,
    reject_secret_configuration,
)
from app.website_builder_core.contracts import (
    DeliveryAdapterContext,
    DeliveryRecipientSnapshot,
    FormDeliveryPresentation,
    PresentationAdapter,
)
from app.website_builder_core.readiness import (
    FormDeliveryReadinessInput,
    evaluate_form_delivery_readiness,
)


class FormDeliveryConfigurationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 409,
        code: str = "form_delivery_configuration_invalid",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


FORM_DELIVERY_TABLES = (
    "websiteformdeliverymoderevision",
    "websiteformrecipientrevision",
    "formsubmissionenvelope",
    "formdeliveryoutbox",
    "formdeliveryattempt",
    "formdeliveryconfigurationaudit",
)


def resolve_provider_owned_presentation(
    session: Session,
    record: WebsiteFormDeliveryModeRevision,
    *,
    allow_test_only: bool = False,
) -> FormDeliveryPresentation:
    """Resolve one safe provider-owned presentation from the sole registry."""

    if record.mode != "provider_owned" or not record.provider_key:
        raise FormDeliveryConfigurationError(
            "The revision is not a provider-owned presentation."
        )
    website, component = _website_and_component(
        session,
        record.website_id,
        record.form_component_configuration_id,
    )
    current = resolve_current_form_delivery_mode(
        session,
        record.website_id,
        record.form_component_configuration_id,
    )
    if (
        current.id != record.id
        or record.lifecycle_status != "active"
        or not record.enabled
        or not record.approval_identity
        or record.approved_at is None
        or not record.activation_identity
        or record.activated_at is None
        or record.integrity_fingerprint != form_delivery_mode_fingerprint(record)
        or not record.privacy_policy_reference
    ):
        raise FormDeliveryConfigurationError(
            "The provider-owned presentation revision is not governed and active."
        )
    try:
        configuration = validate_mode_configuration(
            "provider_owned",
            record.configuration_payload,
        )
    except (KeyError, ValidationError, ValueError) as exc:
        raise FormDeliveryConfigurationError(
            "The provider-owned presentation configuration is invalid."
        ) from exc
    registration = FORM_DELIVERY_PROVIDER_REGISTRY.registration(
        record.provider_key,
        allow_test_only=allow_test_only,
    )
    if (
        registration is None
        or record.adapter_version != registration.descriptor.adapter_version
        or not registration.descriptor.supports(
            mode="provider_owned",
            form_contract_version=component.component_contract_version,
            website_identity=str(website.id),
        )
    ):
        raise FormDeliveryConfigurationError(
            "The provider-owned presentation registration is incompatible."
        )
    adapter = registration.presentation_adapter if registration is not None else None
    if adapter is None or not isinstance(adapter, PresentationAdapter):
        raise FormDeliveryConfigurationError(
            "The provider-owned presentation adapter is unavailable."
        )
    try:
        presentation = adapter.presentation(configuration)
    except Exception as exc:
        raise FormDeliveryConfigurationError(
            "The provider-owned presentation adapter failed closed."
        ) from exc
    expected = FormDeliveryPresentation(
        kind=configuration["presentation_strategy"],  # type: ignore[arg-type]
        destination=str(configuration["approved_https_destination"]),
        title=str(configuration["accessibility_title"]),
        ownership_disclosure=str(configuration["ownership_disclosure"]),
        approved_origin=str(configuration["approved_origin"]),
        sandbox_policy=(
            str(configuration["sandbox_policy"])
            if configuration.get("sandbox_policy") is not None
            else None
        ),
        referrer_policy=(
            str(configuration["referrer_policy"])
            if configuration.get("referrer_policy") is not None
            else None
        ),
    )
    if presentation != expected:
        raise FormDeliveryConfigurationError(
            "The provider-owned presentation crossed its approved configuration."
        )
    return presentation


def resolve_delivery_adapter_context(
    session: Session,
    record: WebsiteFormDeliveryModeRevision,
    *,
    delivery_identity: str,
    idempotency_digest: str,
) -> DeliveryAdapterContext:
    """Resolve immutable Atlas state into one provider-neutral in-memory context."""

    if record.mode not in {"atlas_email", "atlasops360_native", "external_adapter"}:
        raise FormDeliveryConfigurationError(
            "The selected mode does not use a delivery adapter."
        )
    if (
        len(delivery_identity) != 64
        or delivery_identity != delivery_identity.lower()
        or any(character not in "0123456789abcdef" for character in delivery_identity)
        or len(idempotency_digest) != 64
        or idempotency_digest != idempotency_digest.lower()
        or any(character not in "0123456789abcdef" for character in idempotency_digest)
    ):
        raise FormDeliveryConfigurationError(
            "The durable delivery identity is invalid."
        )
    _, component = _website_and_component(
        session,
        record.website_id,
        record.form_component_configuration_id,
    )
    if (
        record.lifecycle_status != "active"
        or not record.enabled
        or component.component_instance_key != record.form_instance_key
        or record.integrity_fingerprint != form_delivery_mode_fingerprint(record)
    ):
        raise FormDeliveryConfigurationError(
            "The delivery-adapter mode scope or fingerprint is invalid."
        )
    try:
        configuration = validate_mode_configuration(
            record.mode,  # type: ignore[arg-type]
            record.configuration_payload,
        )
    except (KeyError, ValidationError, ValueError) as exc:
        raise FormDeliveryConfigurationError(
            "The delivery-adapter configuration is invalid."
        ) from exc

    reference_keys = {
        "atlas_email": (
            "transport_key_reference",
            "transport_secret_reference",
        ),
        "atlasops360_native": (
            "workspace_binding_reference",
            "adapter_configuration_reference",
        ),
        "external_adapter": (
            "adapter_configuration_reference",
            "adapter_secret_reference",
        ),
    }[record.mode]
    references = tuple(
        (key, str(configuration[key]))
        for key in reference_keys
    )
    recipients: tuple[DeliveryRecipientSnapshot, ...] = ()
    if record.mode == "atlas_email":
        eligible = _eligible_recipients_for_mode(session, record)
        if configuration.get("notification_preference") == "primary_only":
            eligible = [
                recipient
                for recipient in eligible
                if recipient.recipient_role == "primary"
            ]
        if not eligible:
            raise FormDeliveryConfigurationError(
                "The delivery-adapter context has no eligible verified recipient."
            )
        recipients = tuple(
            DeliveryRecipientSnapshot(
                recipient_key=recipient.recipient_key,
                normalized_email=recipient.normalized_email,
                recipient_role=recipient.recipient_role,  # type: ignore[arg-type]
            )
            for recipient in sorted(eligible, key=lambda item: item.recipient_key)
        )

    required = (
        record.provider_key,
        record.adapter_version,
        record.destination_identity,
        record.privacy_policy_reference,
        record.retention_policy_reference,
        record.abuse_policy_reference,
        record.idempotency_policy_reference,
    )
    if any(value is None or value == "" for value in required):
        raise FormDeliveryConfigurationError(
            "The delivery-adapter context lacks governed policy metadata."
        )
    return DeliveryAdapterContext(
        delivery_identity=delivery_identity,
        idempotency_digest=idempotency_digest,
        mode=record.mode,  # type: ignore[arg-type]
        provider_key=record.provider_key or "",
        adapter_version=record.adapter_version or "",
        destination_identity=record.destination_identity or "",
        configuration_references=references,
        privacy_policy_reference=record.privacy_policy_reference or "",
        consent_required=bool(configuration.get("consent_required", False)),
        consent_policy_reference=record.consent_policy_reference,
        retention_policy_reference=record.retention_policy_reference or "",
        abuse_policy_reference=record.abuse_policy_reference or "",
        idempotency_policy_reference=record.idempotency_policy_reference or "",
        audit_identity=record.audit_identity,
        recipients=recipients,
    )


def canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def form_delivery_mode_fingerprint_payload(
    record: WebsiteFormDeliveryModeRevision | Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "website_id": _value(record, "website_id"),
        "form_component_configuration_id": _value(
            record, "form_component_configuration_id"
        ),
        "form_instance_key": _value(record, "form_instance_key"),
        "revision": _value(record, "revision"),
        "supersedes_delivery_mode_revision_id": _value(
            record, "supersedes_delivery_mode_revision_id"
        ),
        "lifecycle_status": _value(record, "lifecycle_status"),
        "mode": _value(record, "mode"),
        "enabled": _value(record, "enabled"),
        "provider_key": _value(record, "provider_key"),
        "adapter_version": _value(record, "adapter_version"),
        "destination_identity": _value(record, "destination_identity"),
        "configuration_payload": _value(record, "configuration_payload"),
        "privacy_policy_reference": _value(record, "privacy_policy_reference"),
        "consent_policy_reference": _value(record, "consent_policy_reference"),
        "retention_policy_reference": _value(record, "retention_policy_reference"),
        "abuse_policy_reference": _value(record, "abuse_policy_reference"),
        "success_behavior": _value(record, "success_behavior"),
        "failure_behavior": _value(record, "failure_behavior"),
        "idempotency_policy_reference": _value(
            record, "idempotency_policy_reference"
        ),
        "audit_identity": _value(record, "audit_identity"),
        "approval_identity": _value(record, "approval_identity"),
        "approved_at": _datetime_value(_value(record, "approved_at")),
        "activation_identity": _value(record, "activation_identity"),
        "activated_at": _datetime_value(_value(record, "activated_at")),
        "created_by": _value(record, "created_by"),
        "updated_by": _value(record, "updated_by"),
    }


def form_delivery_mode_fingerprint(
    record: WebsiteFormDeliveryModeRevision | Mapping[str, Any],
) -> str:
    return canonical_json_hash(form_delivery_mode_fingerprint_payload(record))


def form_recipient_fingerprint_payload(
    record: WebsiteFormRecipientRevision | Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "delivery_mode_revision_id": _value(record, "delivery_mode_revision_id"),
        "website_id": _value(record, "website_id"),
        "form_component_configuration_id": _value(
            record, "form_component_configuration_id"
        ),
        "form_instance_key": _value(record, "form_instance_key"),
        "recipient_key": _value(record, "recipient_key"),
        "revision": _value(record, "revision"),
        "supersedes_recipient_revision_id": _value(
            record, "supersedes_recipient_revision_id"
        ),
        "email": _value(record, "email"),
        "normalized_email": _value(record, "normalized_email"),
        "label": _value(record, "label"),
        "recipient_role": _value(record, "recipient_role"),
        "enabled": _value(record, "enabled"),
        "verification_status": _value(record, "verification_status"),
        "verified_at": _datetime_value(_value(record, "verified_at")),
        "verified_by": _value(record, "verified_by"),
        "verification_method": _value(record, "verification_method"),
        "created_by": _value(record, "created_by"),
        "updated_by": _value(record, "updated_by"),
    }


def form_recipient_fingerprint(
    record: WebsiteFormRecipientRevision | Mapping[str, Any],
) -> str:
    return canonical_json_hash(form_recipient_fingerprint_payload(record))


def form_delivery_audit_hash_payload(
    record: FormDeliveryConfigurationAudit | Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "delivery_mode_revision_id": _value(record, "delivery_mode_revision_id"),
        "recipient_revision_id": _value(record, "recipient_revision_id"),
        "action_type": _value(record, "action_type"),
        "actor": _value(record, "actor"),
        "rationale": _value(record, "rationale"),
        "snapshot": _value(record, "snapshot"),
        "created_at": _datetime_value(_value(record, "created_at")),
    }


def form_delivery_configuration_audit_hash(
    record: FormDeliveryConfigurationAudit | Mapping[str, Any],
) -> str:
    return canonical_json_hash(form_delivery_audit_hash_payload(record))


def create_form_delivery_mode_revision(
    session: Session,
    website_id: int,
    payload: WebsiteFormDeliveryModeRevisionCreate,
    *,
    commit: bool = True,
) -> WebsiteFormDeliveryModeRevision:
    try:
        payload = WebsiteFormDeliveryModeRevisionCreate.model_validate(
            payload.model_dump()
        )
    except (ValidationError, ValueError) as exc:
        raise FormDeliveryConfigurationError(
            "The form-delivery mode payload is invalid."
        ) from exc
    website, component = _website_and_component(
        session,
        website_id,
        payload.form_component_configuration_id,
    )
    if component.component_instance_key != payload.form_instance_key:
        raise FormDeliveryConfigurationError(
            "Form delivery mode does not match the exact component instance."
        )

    predecessor: WebsiteFormDeliveryModeRevision | None = None
    if payload.supersedes_delivery_mode_revision_id is not None:
        predecessor = session.exec(
            select(WebsiteFormDeliveryModeRevision)
            .where(
                WebsiteFormDeliveryModeRevision.id
                == payload.supersedes_delivery_mode_revision_id
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if predecessor is None:
            raise FormDeliveryConfigurationError(
                "The predecessor mode revision was not found.",
                status_code=404,
                code="form_delivery_predecessor_not_found",
            )
        if (
            predecessor.website_id != website_id
            or predecessor.form_instance_key != payload.form_instance_key
        ):
            raise FormDeliveryConfigurationError(
                "The predecessor mode revision crosses Website or form scope."
            )
        existing_successor = session.exec(
            select(WebsiteFormDeliveryModeRevision).where(
                WebsiteFormDeliveryModeRevision.supersedes_delivery_mode_revision_id
                == predecessor.id
            )
        ).first()
        if existing_successor is not None:
            raise FormDeliveryConfigurationError(
                "The predecessor mode revision already has a successor."
            )
        revision = predecessor.revision + 1
    else:
        existing = session.exec(
            select(WebsiteFormDeliveryModeRevision).where(
                WebsiteFormDeliveryModeRevision.website_id == website_id,
                WebsiteFormDeliveryModeRevision.form_instance_key
                == payload.form_instance_key,
            )
        ).first()
        if existing is not None:
            raise FormDeliveryConfigurationError(
                "An existing form-delivery chain requires an exact predecessor."
            )
        revision = 1

    now = datetime.now(UTC)
    values = payload.model_dump(exclude={"rationale"})
    values.update(
        website_id=website.id,
        revision=revision,
        created_at=now,
        updated_at=now,
        integrity_fingerprint="0" * 64,
    )
    record = WebsiteFormDeliveryModeRevision(**values)
    record.integrity_fingerprint = form_delivery_mode_fingerprint(record)
    session.add(record)
    try:
        session.flush()
        _append_configuration_audit(
            session,
            mode_revision=record,
            recipient_revision=None,
            action_type=_mode_audit_action(record.lifecycle_status),
            actor=payload.updated_by,
            rationale=payload.rationale,
        )
        if commit:
            session.commit()
            session.refresh(record)
    except (IntegrityError, ValueError) as exc:
        session.rollback()
        raise FormDeliveryConfigurationError(
            "The form-delivery mode revision conflicts with durable state."
        ) from exc
    return record


def create_form_recipient_revision(
    session: Session,
    website_id: int,
    payload: WebsiteFormRecipientRevisionCreate,
    *,
    commit: bool = True,
) -> WebsiteFormRecipientRevision:
    try:
        payload = WebsiteFormRecipientRevisionCreate.model_validate(
            payload.model_dump()
        )
    except (ValidationError, ValueError) as exc:
        raise FormDeliveryConfigurationError(
            "The form-recipient payload is invalid."
        ) from exc
    mode = session.exec(
        select(WebsiteFormDeliveryModeRevision)
        .where(
            WebsiteFormDeliveryModeRevision.id
            == payload.delivery_mode_revision_id
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if mode is None:
        raise FormDeliveryConfigurationError(
            "The recipient mode revision was not found.",
            status_code=404,
            code="form_delivery_mode_not_found",
        )
    if mode.website_id != website_id or mode.mode != "atlas_email":
        raise FormDeliveryConfigurationError(
            "Recipients belong only to the exact Website Atlas-email revision."
        )
    current_mode = resolve_current_form_delivery_mode(
        session,
        website_id,
        mode.form_component_configuration_id,
    )
    if current_mode.id != mode.id:
        raise FormDeliveryConfigurationError(
            "A superseded delivery-mode revision has a frozen recipient snapshot."
        )
    if session.exec(
        select(FormSubmissionEnvelope).where(
            FormSubmissionEnvelope.delivery_mode_revision_id == mode.id
        )
    ).first() is not None:
        raise FormDeliveryConfigurationError(
            "A delivery-mode revision with submission evidence has a frozen recipient snapshot."
        )

    normalized_email = normalize_recipient_email(str(payload.email))

    predecessor: WebsiteFormRecipientRevision | None = None
    if payload.supersedes_recipient_revision_id is not None:
        predecessor = session.get(
            WebsiteFormRecipientRevision,
            payload.supersedes_recipient_revision_id,
        )
        if predecessor is None:
            raise FormDeliveryConfigurationError(
                "The predecessor recipient revision was not found.",
                status_code=404,
                code="form_recipient_predecessor_not_found",
            )
        if (
            predecessor.website_id != website_id
            or predecessor.form_instance_key != mode.form_instance_key
            or predecessor.recipient_key != payload.recipient_key
            or not (
                predecessor.delivery_mode_revision_id == mode.id
                or mode.supersedes_delivery_mode_revision_id
                == predecessor.delivery_mode_revision_id
            )
        ):
            raise FormDeliveryConfigurationError(
                "The predecessor recipient must belong to this mode revision or "
                "its directly superseded Website form-delivery mode revision."
            )
        existing_successor = session.exec(
            select(WebsiteFormRecipientRevision).where(
                WebsiteFormRecipientRevision.supersedes_recipient_revision_id
                == predecessor.id
            )
        ).first()
        if existing_successor is not None:
            raise FormDeliveryConfigurationError(
                "The predecessor recipient already has a successor."
            )
        revision = predecessor.revision + 1
    else:
        existing = session.exec(
            select(WebsiteFormRecipientRevision).where(
                WebsiteFormRecipientRevision.website_id == website_id,
                WebsiteFormRecipientRevision.form_instance_key
                == mode.form_instance_key,
                WebsiteFormRecipientRevision.recipient_key == payload.recipient_key,
            )
        ).first()
        if existing is not None:
            raise FormDeliveryConfigurationError(
                "An existing recipient chain requires an exact predecessor."
            )
        revision = 1

    other_heads = [
        recipient
        for recipient in _recipient_heads_for_mode(session, mode)
        if predecessor is None or recipient.id != predecessor.id
    ]
    if any(
        recipient.normalized_email == normalized_email
        for recipient in other_heads
    ):
        raise FormDeliveryConfigurationError(
            "The normalized recipient address already belongs to a current head."
        )
    if payload.enabled and payload.recipient_role == "primary" and any(
        recipient.enabled and recipient.recipient_role == "primary"
        for recipient in other_heads
    ):
        raise FormDeliveryConfigurationError(
            "The mode revision already has an enabled primary recipient head."
        )
    now = datetime.now(UTC)
    values = payload.model_dump(exclude={"rationale"})
    values.update(
        website_id=website_id,
        form_component_configuration_id=mode.form_component_configuration_id,
        form_instance_key=mode.form_instance_key,
        email=str(payload.email),
        normalized_email=normalized_email,
        revision=revision,
        created_at=now,
        updated_at=now,
        integrity_fingerprint="0" * 64,
    )
    record = WebsiteFormRecipientRevision(**values)
    record.integrity_fingerprint = form_recipient_fingerprint(record)
    session.add(record)
    try:
        session.flush()
        _append_configuration_audit(
            session,
            mode_revision=None,
            recipient_revision=record,
            action_type=_recipient_audit_action(record.verification_status),
            actor=payload.updated_by,
            rationale=payload.rationale,
        )
        if commit:
            session.commit()
            session.refresh(record)
    except (IntegrityError, ValueError) as exc:
        session.rollback()
        raise FormDeliveryConfigurationError(
            "The form recipient revision conflicts with durable state."
        ) from exc
    return record


def normalize_recipient_email(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip()).casefold()


def resolve_current_form_delivery_mode(
    session: Session,
    website_id: int,
    component_configuration_id: int,
) -> WebsiteFormDeliveryModeRevision:
    _, component = _website_and_component(
        session,
        website_id,
        component_configuration_id,
    )
    _require_form_delivery_schema(session, absent_is_not_found=True)
    records = list(
        session.exec(
            select(WebsiteFormDeliveryModeRevision)
            .where(
                WebsiteFormDeliveryModeRevision.website_id == website_id,
                WebsiteFormDeliveryModeRevision.form_instance_key
                == component.component_instance_key,
            )
            .order_by(WebsiteFormDeliveryModeRevision.revision)
        ).all()
    )
    if not records:
        raise FormDeliveryConfigurationError(
            "No explicit form-delivery mode is configured.",
            status_code=404,
            code="form_delivery_mode_not_found",
        )
    _validate_mode_chain(records)
    predecessor_ids = {
        record.supersedes_delivery_mode_revision_id
        for record in records
        if record.supersedes_delivery_mode_revision_id is not None
    }
    heads = [record for record in records if record.id not in predecessor_ids]
    if len(heads) != 1:
        raise FormDeliveryConfigurationError(
            "The form-delivery mode chain does not have exactly one current head."
        )
    current = heads[0]
    if current.form_component_configuration_id != component_configuration_id:
        raise FormDeliveryConfigurationError(
            "The current mode revision does not govern the requested component revision."
        )
    return current


def _require_form_delivery_schema(
    session: Session,
    *,
    absent_is_not_found: bool,
) -> None:
    existing = set(inspect(session.get_bind()).get_table_names())
    governed = existing.intersection(FORM_DELIVERY_TABLES)
    if governed == set(FORM_DELIVERY_TABLES):
        return
    if not governed and absent_is_not_found:
        raise FormDeliveryConfigurationError(
            "No explicit form-delivery mode is configured.",
            status_code=404,
            code="form_delivery_mode_not_found",
        )
    raise FormDeliveryConfigurationError(
        "The universal form-delivery schema is unavailable or partial.",
        status_code=503,
        code="form_delivery_schema_incompatible",
    )


def form_delivery_readiness(
    session: Session,
    record: WebsiteFormDeliveryModeRevision,
    *,
    allow_test_only: bool = False,
    secure_payload_store_available: bool = False,
) -> FormDeliveryReadinessRead:
    website = session.get(Website, record.website_id)
    component = session.get(
        WebsiteThemeComponentConfiguration,
        record.form_component_configuration_id,
    )
    try:
        current_revision = resolve_current_form_delivery_mode(
            session,
            record.website_id,
            record.form_component_configuration_id,
        )
    except FormDeliveryConfigurationError:
        current_revision = None
    recipients = _recipient_heads_for_mode(session, record)
    recipient_heads_valid = _recipient_head_set_valid(record, recipients)
    eligible_recipients = [
        recipient
        for recipient in recipients
        if recipient_heads_valid
        and recipient.enabled
        and recipient.verification_status == "verified"
        and recipient.website_id == record.website_id
        and recipient.form_component_configuration_id
        == record.form_component_configuration_id
        and recipient.form_instance_key == record.form_instance_key
        and recipient.normalized_email == normalize_recipient_email(recipient.email)
        and recipient.integrity_fingerprint == form_recipient_fingerprint(recipient)
    ]
    registration = FORM_DELIVERY_PROVIDER_REGISTRY.registration(
        record.provider_key or "",
        allow_test_only=allow_test_only,
    )
    try:
        validate_mode_configuration(record.mode, record.configuration_payload)  # type: ignore[arg-type]
        configuration_valid = True
    except (KeyError, ValidationError, ValueError):
        configuration_valid = False
    provider_presentation_ready = False
    if record.mode == "provider_owned" and configuration_valid:
        try:
            resolve_provider_owned_presentation(
                session,
                record,
                allow_test_only=allow_test_only,
            )
            provider_presentation_ready = True
        except FormDeliveryConfigurationError:
            pass
    secret_reference_configured = _secret_reference_configured(
        record.configuration_payload
    )
    readiness = evaluate_form_delivery_readiness(
        FormDeliveryReadinessInput(
            mode=record.mode,  # type: ignore[arg-type]
            lifecycle_status=record.lifecycle_status,
            enabled=record.enabled,
            scope_valid=bool(
                website
                and component
                and component.website_id == record.website_id
                and component.component_instance_key == record.form_instance_key
                and configuration_valid
                and recipient_heads_valid
                and current_revision is not None
                and current_revision.id == record.id
            ),
            fingerprint_valid=(
                record.integrity_fingerprint == form_delivery_mode_fingerprint(record)
            ),
            website_enabled=bool(website and website.status == "active"),
            component_enabled=bool(
                component
                and component.enabled
                and component.lifecycle_status == "current"
            ),
            approval_identity=record.approval_identity,
            activation_identity=record.activation_identity,
            provider_key=record.provider_key,
            adapter_version=record.adapter_version,
            destination_identity=record.destination_identity,
            privacy_policy_reference=record.privacy_policy_reference,
            consent_required=bool(
                record.configuration_payload.get("consent_required", False)
            ),
            consent_policy_reference=record.consent_policy_reference,
            retention_policy_reference=record.retention_policy_reference,
            abuse_policy_reference=record.abuse_policy_reference,
            success_behavior=record.success_behavior,
            failure_behavior=record.failure_behavior,
            idempotency_policy_reference=record.idempotency_policy_reference,
            audit_identity=record.audit_identity,
            verified_recipient_count=sum(
                1
                for recipient in eligible_recipients
            ),
            verified_primary_recipient_count=sum(
                1
                for recipient in eligible_recipients
                if recipient.recipient_role == "primary"
            ),
            notification_preference=(
                str(record.configuration_payload.get("notification_preference"))
                if record.mode == "atlas_email"
                else None
            ),
            secret_reference_configured=secret_reference_configured,
            secure_payload_store_available=secure_payload_store_available,
            provider_owned_presentation_ready=provider_presentation_ready,
            form_contract_version=(
                component.component_contract_version if component is not None else 1
            ),
            website_identity=str(record.website_id),
        ),
        registration.descriptor if registration is not None else None,
    )
    return FormDeliveryReadinessRead(
        **{
            **readiness.__dict__,
            "blockers": [
                FormDeliveryReadinessBlockerRead(**blocker.__dict__)
                for blocker in readiness.blockers
            ],
        }
    )


def _eligible_recipients_for_mode(
    session: Session,
    record: WebsiteFormDeliveryModeRevision,
) -> list[WebsiteFormRecipientRevision]:
    recipients = _recipient_heads_for_mode(session, record)
    if not _recipient_head_set_valid(record, recipients):
        return []
    return [
        recipient
        for recipient in recipients
        if recipient.enabled
        and recipient.verification_status == "verified"
        and recipient.website_id == record.website_id
        and recipient.form_component_configuration_id
        == record.form_component_configuration_id
        and recipient.form_instance_key == record.form_instance_key
        and recipient.normalized_email == normalize_recipient_email(recipient.email)
        and recipient.integrity_fingerprint == form_recipient_fingerprint(recipient)
    ]


def _recipient_head_set_valid(
    record: WebsiteFormDeliveryModeRevision,
    recipients: list[WebsiteFormRecipientRevision],
) -> bool:
    if record.mode != "atlas_email":
        return not recipients
    if any(
        recipient.website_id != record.website_id
        or recipient.form_component_configuration_id
        != record.form_component_configuration_id
        or recipient.form_instance_key != record.form_instance_key
        or recipient.normalized_email != normalize_recipient_email(recipient.email)
        or recipient.integrity_fingerprint != form_recipient_fingerprint(recipient)
        for recipient in recipients
    ):
        return False
    normalized_addresses = [recipient.normalized_email for recipient in recipients]
    if len(normalized_addresses) != len(set(normalized_addresses)):
        return False
    return (
        sum(
            1
            for recipient in recipients
            if recipient.enabled and recipient.recipient_role == "primary"
        )
        <= 1
    )


def _recipient_heads_for_mode(
    session: Session,
    record: WebsiteFormDeliveryModeRevision,
) -> list[WebsiteFormRecipientRevision]:
    records = list(
        session.exec(
            select(WebsiteFormRecipientRevision).where(
                WebsiteFormRecipientRevision.delivery_mode_revision_id == record.id
            )
        ).all()
    )
    superseded_ids = {
        item.supersedes_recipient_revision_id
        for item in records
        if item.supersedes_recipient_revision_id is not None
    }
    return [item for item in records if item.id not in superseded_ids]


def read_form_delivery_operator_review(
    session: Session,
    website_id: int,
    component_configuration_id: int,
) -> FormDeliveryOperatorReviewRead:
    record = resolve_current_form_delivery_mode(
        session,
        website_id,
        component_configuration_id,
    )
    recipients = _recipient_heads_for_mode(session, record)
    eligible_recipients = _eligible_recipients_for_mode(session, record)
    redacted = record.model_dump()
    redacted["configuration_payload"] = _redacted_configuration_summary(
        record.configuration_payload
    )
    return FormDeliveryOperatorReviewRead(
        current_revision=WebsiteFormDeliveryModeRevisionRead.model_validate(redacted),
        readiness=form_delivery_readiness(session, record),
        recipient_count=len(recipients),
        enabled_verified_recipient_count=len(eligible_recipients),
        secret_reference_configured=_secret_reference_configured(
            record.configuration_payload
        ),
        configuration_summary=_redacted_configuration_summary(
            record.configuration_payload
        ),
    )


def read_form_delivery_mode_history(
    session: Session,
    website_id: int,
    component_configuration_id: int,
) -> list[WebsiteFormDeliveryModeRevisionRead]:
    _, component = _website_and_component(
        session,
        website_id,
        component_configuration_id,
    )
    _require_form_delivery_schema(session, absent_is_not_found=True)
    records = list(
        session.exec(
            select(WebsiteFormDeliveryModeRevision)
            .where(
                WebsiteFormDeliveryModeRevision.website_id == website_id,
                WebsiteFormDeliveryModeRevision.form_instance_key
                == component.component_instance_key,
            )
            .order_by(WebsiteFormDeliveryModeRevision.revision)
        ).all()
    )
    if not records:
        raise FormDeliveryConfigurationError(
            "No explicit form-delivery mode is configured.",
            status_code=404,
            code="form_delivery_mode_not_found",
        )
    _validate_mode_chain(records)
    result: list[WebsiteFormDeliveryModeRevisionRead] = []
    for record in records:
        redacted = record.model_dump()
        redacted["configuration_payload"] = _redacted_configuration_summary(
            record.configuration_payload
        )
        result.append(WebsiteFormDeliveryModeRevisionRead.model_validate(redacted))
    return result


def validate_form_delivery_records(session: Session) -> dict[str, int]:
    """Validate the complete durable graph without mutating any record."""

    from app.services.form_delivery_outbox import (
        form_delivery_attempt_fingerprint,
        form_submission_envelope_fingerprint,
    )

    modes = list(session.exec(select(WebsiteFormDeliveryModeRevision)).all())
    recipients = list(session.exec(select(WebsiteFormRecipientRevision)).all())
    envelopes = list(session.exec(select(FormSubmissionEnvelope)).all())
    outboxes = list(session.exec(select(FormDeliveryOutbox)).all())
    attempts = list(session.exec(select(FormDeliveryAttempt)).all())
    audits = list(session.exec(select(FormDeliveryConfigurationAudit)).all())

    mode_groups: dict[tuple[int, str], list[WebsiteFormDeliveryModeRevision]] = {}
    mode_by_id = {record.id: record for record in modes}
    for record in modes:
        try:
            _, component = _website_and_component(
                session,
                record.website_id,
                record.form_component_configuration_id,
            )
            WebsiteFormDeliveryModeRevisionCreate.model_validate(
                {
                    **record.model_dump(
                        exclude={
                            "id",
                            "website_id",
                            "revision",
                            "integrity_fingerprint",
                            "created_at",
                            "updated_at",
                        }
                    ),
                    "rationale": "Durable form-delivery graph validation.",
                }
            )
        except (FormDeliveryConfigurationError, ValidationError, ValueError) as exc:
            raise FormDeliveryConfigurationError(
                "A durable form-delivery mode contract or scope is invalid."
            ) from exc
        if component.component_instance_key != record.form_instance_key:
            raise FormDeliveryConfigurationError(
                "A durable form-delivery mode crosses its component instance scope."
            )
        mode_groups.setdefault(
            (record.website_id, record.form_instance_key), []
        ).append(record)
        try:
            validate_mode_configuration(record.mode, record.configuration_payload)  # type: ignore[arg-type]
        except (KeyError, ValidationError, ValueError) as exc:
            raise FormDeliveryConfigurationError(
                "A durable form-delivery mode payload is invalid."
            ) from exc
    for records in mode_groups.values():
        ordered = sorted(records, key=lambda item: item.revision)
        _validate_mode_chain(ordered)
        predecessor_ids = {
            item.supersedes_delivery_mode_revision_id
            for item in ordered
            if item.supersedes_delivery_mode_revision_id is not None
        }
        if len([item for item in ordered if item.id not in predecessor_ids]) != 1:
            raise FormDeliveryConfigurationError(
                "A durable form-delivery chain lacks exactly one current head."
            )

    recipient_groups: dict[
        tuple[int, str, str], list[WebsiteFormRecipientRevision]
    ] = {}
    mode_successors = {
        item.supersedes_delivery_mode_revision_id: item
        for item in modes
        if item.supersedes_delivery_mode_revision_id is not None
    }
    first_envelope_by_mode: dict[int, datetime] = {}
    for envelope in envelopes:
        observed = first_envelope_by_mode.get(envelope.delivery_mode_revision_id)
        if observed is None or _utc_datetime(envelope.received_at) < _utc_datetime(
            observed
        ):
            first_envelope_by_mode[envelope.delivery_mode_revision_id] = (
                envelope.received_at
            )
    for record in recipients:
        mode = mode_by_id.get(record.delivery_mode_revision_id)
        try:
            WebsiteFormRecipientRevisionCreate.model_validate(
                {
                    **record.model_dump(
                        exclude={
                            "id",
                            "website_id",
                            "form_component_configuration_id",
                            "form_instance_key",
                            "revision",
                            "normalized_email",
                            "integrity_fingerprint",
                            "created_at",
                            "updated_at",
                        }
                    ),
                    "rationale": "Durable form-recipient graph validation.",
                }
            )
        except (ValidationError, ValueError) as exc:
            raise FormDeliveryConfigurationError(
                "A durable form recipient contract is invalid."
            ) from exc
        cutoffs = [
            _utc_datetime(value)
            for value in (
                first_envelope_by_mode.get(record.delivery_mode_revision_id),
                (
                    mode_successors[record.delivery_mode_revision_id].created_at
                    if record.delivery_mode_revision_id in mode_successors
                    else None
                ),
            )
            if value is not None
        ]
        if (
            mode is None
            or mode.website_id != record.website_id
            or mode.form_component_configuration_id
            != record.form_component_configuration_id
            or mode.form_instance_key != record.form_instance_key
            or mode.mode != "atlas_email"
            or record.normalized_email != normalize_recipient_email(record.email)
            or record.integrity_fingerprint != form_recipient_fingerprint(record)
            or _utc_datetime(record.updated_at) < _utc_datetime(record.created_at)
            or _utc_datetime(record.created_at) < _utc_datetime(mode.created_at)
            or (cutoffs and _utc_datetime(record.created_at) > min(cutoffs))
        ):
            raise FormDeliveryConfigurationError(
                "A durable form recipient crosses scope or has invalid integrity evidence."
            )
        recipient_groups.setdefault(
            (record.website_id, record.form_instance_key, record.recipient_key), []
        ).append(record)
    for records in recipient_groups.values():
        ordered = sorted(records, key=lambda item: item.revision)
        roots = [item for item in ordered if item.supersedes_recipient_revision_id is None]
        by_id = {item.id: item for item in ordered}
        successors: set[int] = set()
        if len(roots) != 1 or roots[0].revision != 1:
            raise FormDeliveryConfigurationError("A recipient lineage root is invalid.")
        for item in ordered[1:]:
            predecessor = by_id.get(item.supersedes_recipient_revision_id)
            current_mode = mode_by_id.get(item.delivery_mode_revision_id)
            predecessor_mode = (
                mode_by_id.get(predecessor.delivery_mode_revision_id)
                if predecessor is not None
                else None
            )
            if (
                predecessor is None
                or predecessor.revision + 1 != item.revision
                or predecessor.id in successors
                or current_mode is None
                or predecessor_mode is None
                or not (
                    current_mode.id == predecessor_mode.id
                    or current_mode.supersedes_delivery_mode_revision_id
                    == predecessor_mode.id
                )
            ):
                raise FormDeliveryConfigurationError("A recipient lineage is invalid.")
            successors.add(predecessor.id)  # type: ignore[arg-type]
        if len([item for item in ordered if item.id not in successors]) != 1:
            raise FormDeliveryConfigurationError(
                "A recipient lineage lacks exactly one current head."
            )

    for mode in modes:
        heads = _recipient_heads_for_mode(session, mode)
        normalized_addresses = [item.normalized_email for item in heads]
        if len(normalized_addresses) != len(set(normalized_addresses)):
            raise FormDeliveryConfigurationError(
                "A mode has duplicate normalized recipient heads."
            )
        enabled_primary_heads = [
            item
            for item in heads
            if item.enabled and item.recipient_role == "primary"
        ]
        if len(enabled_primary_heads) > 1:
            raise FormDeliveryConfigurationError(
                "A mode has more than one enabled primary recipient head."
            )

    envelope_by_id = {record.id: record for record in envelopes}
    for record in envelopes:
        mode = mode_by_id.get(record.delivery_mode_revision_id)
        if (
            mode is None
            or mode.website_id != record.website_id
            or mode.form_component_configuration_id
            != record.form_component_configuration_id
            or mode.mode not in {
                "atlas_email",
                "atlasops360_native",
                "external_adapter",
            }
            or record.destination_adapter_key != mode.provider_key
            or record.audit_identity != mode.audit_identity
            or not FINGERPRINT_PATTERN.fullmatch(record.request_identity)
            or not KEY_PATTERN.fullmatch(record.anti_spam_decision)
            or (
                record.consent_version is not None
                and not KEY_PATTERN.fullmatch(record.consent_version)
            )
            or (
                record.source_page_identity is not None
                and not SOURCE_REFERENCE_PATTERN.fullmatch(
                    record.source_page_identity
                )
            )
            or record.privacy_policy_reference != mode.privacy_policy_reference
            or record.retention_policy_reference != mode.retention_policy_reference
            or record.abuse_policy_reference != mode.abuse_policy_reference
            or record.integrity_fingerprint
            != form_submission_envelope_fingerprint(record)
        ):
            raise FormDeliveryConfigurationError(
                "A durable form envelope crosses scope or has invalid integrity evidence."
            )

    outbox_by_id = {record.id: record for record in outboxes}
    attempts_by_outbox: dict[int, list[FormDeliveryAttempt]] = {}
    for attempt in attempts:
        if (
            attempt.outbox_id not in outbox_by_id
            or attempt.integrity_fingerprint
            != form_delivery_attempt_fingerprint(attempt)
        ):
            raise FormDeliveryConfigurationError(
                "A durable form delivery attempt has invalid integrity evidence."
            )
        attempts_by_outbox.setdefault(attempt.outbox_id, []).append(attempt)
    for record in outboxes:
        envelope = envelope_by_id.get(record.envelope_id)
        mode = mode_by_id.get(record.delivery_mode_revision_id)
        ordered_attempts = sorted(
            attempts_by_outbox.get(record.id, []),
            key=lambda item: item.attempt_number,
        )
        if (
            envelope is None
            or mode is None
            or envelope.delivery_mode_revision_id != record.delivery_mode_revision_id
            or record.adapter_key != mode.provider_key
            or record.adapter_version != mode.adapter_version
            or record.destination_identity != mode.destination_identity
            or record.attempt_count != len(ordered_attempts)
            or [item.attempt_number for item in ordered_attempts]
            != list(range(1, len(ordered_attempts) + 1))
        ):
            raise FormDeliveryConfigurationError(
                "A durable form outbox crosses scope or has invalid attempt evidence."
            )

    mode_ids = set(mode_by_id)
    recipient_ids = {record.id for record in recipients}
    for audit in audits:
        mode_target = (
            audit.delivery_mode_revision_id in mode_ids
            and audit.recipient_revision_id is None
        )
        recipient_target = (
            audit.recipient_revision_id in recipient_ids
            and audit.delivery_mode_revision_id is None
        )
        action_matches_target = (
            mode_target and audit.action_type.startswith("mode_revision_")
        ) or (
            recipient_target
            and (
                audit.action_type.startswith("recipient_revision_")
                or audit.action_type in {"recipient_verified", "recipient_revoked"}
            )
        )
        if (
            not action_matches_target
            or audit.snapshot_hash
            != form_delivery_configuration_audit_hash(audit)
        ):
            raise FormDeliveryConfigurationError(
                "A durable form-delivery audit target or hash is invalid."
            )

    return {
        "website_form_delivery_mode_revisions": len(modes),
        "website_form_recipient_revisions": len(recipients),
        "form_submission_envelopes": len(envelopes),
        "form_delivery_outbox_records": len(outboxes),
        "form_delivery_attempts": len(attempts),
        "form_delivery_configuration_audits": len(audits),
    }


def _validate_mode_chain(records: list[WebsiteFormDeliveryModeRevision]) -> None:
    roots = [record for record in records if record.supersedes_delivery_mode_revision_id is None]
    if len(roots) != 1 or roots[0].revision != 1:
        raise FormDeliveryConfigurationError(
            "The form-delivery mode chain must have exactly one revision-one root."
        )
    by_id = {record.id: record for record in records}
    if len(by_id) != len(records):
        raise FormDeliveryConfigurationError("The form-delivery mode chain has duplicate identities.")
    successors: set[int] = set()
    for record in records:
        if record.integrity_fingerprint != form_delivery_mode_fingerprint(record):
            raise FormDeliveryConfigurationError("A form-delivery mode fingerprint is invalid.")
        if record.revision == 1:
            continue
        predecessor = by_id.get(record.supersedes_delivery_mode_revision_id)
        if (
            predecessor is None
            or predecessor.website_id != record.website_id
            or predecessor.form_instance_key != record.form_instance_key
            or predecessor.revision + 1 != record.revision
            or predecessor.id in successors
        ):
            raise FormDeliveryConfigurationError("The form-delivery mode lineage is invalid.")
        successors.add(predecessor.id)  # type: ignore[arg-type]


def _website_and_component(
    session: Session,
    website_id: int,
    component_configuration_id: int,
) -> tuple[Website, WebsiteThemeComponentConfiguration]:
    website = session.get(Website, website_id)
    component = session.get(
        WebsiteThemeComponentConfiguration,
        component_configuration_id,
    )
    if website is None or component is None:
        raise FormDeliveryConfigurationError(
            "The Website form component was not found.",
            status_code=404,
            code="form_component_not_found",
        )
    if (
        component.website_id != website_id
        or component.component_key != "compact_estimate_form"
        or component.scope_type != "website_default"
        or component.planned_page_id is not None
        or component.overrides_component_configuration_id is not None
    ):
        raise FormDeliveryConfigurationError(
            "The form component crosses Website, Page, or component scope."
        )
    return website, component


def _append_configuration_audit(
    session: Session,
    *,
    mode_revision: WebsiteFormDeliveryModeRevision | None,
    recipient_revision: WebsiteFormRecipientRevision | None,
    action_type: str,
    actor: str,
    rationale: str,
) -> FormDeliveryConfigurationAudit:
    now = datetime.now(UTC)
    snapshot = (
        {
            "target": "mode_revision",
            "target_id": mode_revision.id,
            "website_id": mode_revision.website_id,
            "form_component_configuration_id": mode_revision.form_component_configuration_id,
            "revision": mode_revision.revision,
            "mode": mode_revision.mode,
            "lifecycle_status": mode_revision.lifecycle_status,
            "integrity_fingerprint": mode_revision.integrity_fingerprint,
        }
        if mode_revision is not None
        else {
            "target": "recipient_revision",
            "target_id": recipient_revision.id,
            "website_id": recipient_revision.website_id,
            "form_component_configuration_id": recipient_revision.form_component_configuration_id,
            "revision": recipient_revision.revision,
            "recipient_key": recipient_revision.recipient_key,
            "verification_status": recipient_revision.verification_status,
            "integrity_fingerprint": recipient_revision.integrity_fingerprint,
        }
    )
    audit = FormDeliveryConfigurationAudit(
        delivery_mode_revision_id=(mode_revision.id if mode_revision else None),
        recipient_revision_id=(recipient_revision.id if recipient_revision else None),
        action_type=action_type,
        actor=actor,
        rationale=rationale,
        snapshot=snapshot,
        snapshot_hash="0" * 64,
        created_at=now,
    )
    audit.snapshot_hash = form_delivery_configuration_audit_hash(audit)
    session.add(audit)
    return audit


def _mode_audit_action(lifecycle: str) -> str:
    return {
        "approved": "mode_revision_approved",
        "active": "mode_revision_activated",
        "retired": "mode_revision_retired",
    }.get(lifecycle, "mode_revision_created")


def _recipient_audit_action(status: str) -> str:
    return {
        "verified": "recipient_verified",
        "revoked": "recipient_revoked",
    }.get(status, "recipient_revision_created")


def _secret_reference_configured(payload: Mapping[str, Any]) -> bool:
    references = [
        value
        for key, value in payload.items()
        if key in {"transport_secret_reference", "adapter_secret_reference"}
    ]
    return bool(
        references
        and all(
            isinstance(value, str) and SECRET_REFERENCE_PATTERN.fullmatch(value)
            for value in references
        )
    )


def _redacted_configuration_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    reject_secret_configuration(dict(payload))
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"transport_secret_reference", "adapter_secret_reference"}:
            result[f"{key}_configured"] = value is not None
        else:
            result[key] = value
    return result


def _value(record: object | Mapping[str, Any], field: str) -> Any:
    return record.get(field) if isinstance(record, Mapping) else getattr(record, field)


def _datetime_value(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
