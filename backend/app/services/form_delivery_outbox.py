from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import re
from typing import Any, Mapping

from sqlmodel import Session, select

from app.models import (
    FormDeliveryAttempt,
    FormDeliveryOutbox,
    FormSubmissionEnvelope,
    WebsiteFormDeliveryModeRevision,
)
from app.schemas.form_delivery import FormDeliveryReadinessRead
from app.services.form_delivery_modes import (
    canonical_json_hash,
    form_delivery_readiness,
    form_delivery_mode_fingerprint,
    resolve_delivery_adapter_context,
    resolve_atlas_rendered_form_definition,
    resolve_current_form_delivery_mode,
)
from app.services.form_delivery_registry import FORM_DELIVERY_PROVIDER_REGISTRY
from app.services.form_delivery_test_guard import session_uses_disposable_database
from app.services.form_payload_store import SecureFormPayloadStore
from app.website_builder_core.configuration_safety import (
    FINGERPRINT_PATTERN,
    SECRET_REFERENCE_PATTERN,
)
from app.website_builder_core.contracts import (
    DeliveryAttemptResult,
    DeliveryAdapter,
    IdempotencyConflict,
    NormalizedSubmissionEnvelope,
    validate_submission_optional_field_binding,
)


class FormDeliveryOutboxError(RuntimeError):
    pass


class FormDeliveryIdempotencyConflict(FormDeliveryOutboxError, IdempotencyConflict):
    """A replay key was already bound to different governed request metadata."""


_SECURE_PAYLOAD_REFERENCE_PATTERN = re.compile(
    r"^(?:memory://form-payload/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}|"
    r"payload-ref://[a-z0-9][a-z0-9/_-]{2,479})$"
)


def form_submission_envelope_fingerprint_payload(
    record: FormSubmissionEnvelope | Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "website_id": _value(record, "website_id"),
        "form_component_configuration_id": _value(
            record, "form_component_configuration_id"
        ),
        "delivery_mode_revision_id": _value(record, "delivery_mode_revision_id"),
        "submission_contract_version": _value(
            record, "submission_contract_version"
        ),
        "consent_accepted": _value(record, "consent_accepted"),
        "consent_version": _value(record, "consent_version"),
        "privacy_policy_reference": _value(record, "privacy_policy_reference"),
        "retention_policy_reference": _value(record, "retention_policy_reference"),
        "abuse_policy_reference": _value(record, "abuse_policy_reference"),
        "anti_spam_decision": _value(record, "anti_spam_decision"),
        "idempotency_digest": _value(record, "idempotency_digest"),
        "received_at": _datetime_value(_value(record, "received_at")),
        "audit_identity": _value(record, "audit_identity"),
        "request_identity": _value(record, "request_identity"),
        "source_page_identity": _value(record, "source_page_identity"),
        "destination_adapter_key": _value(record, "destination_adapter_key"),
        "secure_payload_reference": _value(record, "secure_payload_reference"),
        "encryption_key_reference": _value(record, "encryption_key_reference"),
        "expires_at": _datetime_value(_value(record, "expires_at")),
    }


def form_submission_envelope_fingerprint(
    record: FormSubmissionEnvelope | Mapping[str, Any],
) -> str:
    return canonical_json_hash(form_submission_envelope_fingerprint_payload(record))


def form_delivery_attempt_fingerprint_payload(
    record: FormDeliveryAttempt | Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "outbox_id": _value(record, "outbox_id"),
        "attempt_number": _value(record, "attempt_number"),
        "started_at": _datetime_value(_value(record, "started_at")),
        "completed_at": _datetime_value(_value(record, "completed_at")),
        "outcome": _value(record, "outcome"),
        "safe_error_code": _value(record, "safe_error_code"),
        "safe_provider_reference": _value(record, "safe_provider_reference"),
        "next_retry_at": _datetime_value(_value(record, "next_retry_at")),
    }


def form_delivery_attempt_fingerprint(
    record: FormDeliveryAttempt | Mapping[str, Any],
) -> str:
    return canonical_json_hash(form_delivery_attempt_fingerprint_payload(record))


def enqueue_form_delivery(
    session: Session,
    *,
    mode_revision: WebsiteFormDeliveryModeRevision,
    readiness: FormDeliveryReadinessRead,
    envelope: NormalizedSubmissionEnvelope,
    payload_store: SecureFormPayloadStore,
    expires_at: datetime,
    commit: bool = True,
) -> FormDeliveryOutbox:
    """Persist safe envelope metadata and one outbox row in one DB transaction."""

    if getattr(payload_store, "test_only", False) and not session_uses_disposable_database(
        session
    ):
        raise FormDeliveryOutboxError(
            "Test payload storage requires an explicitly disposable Session bind."
        )
    if mode_revision.id is None:
        raise FormDeliveryOutboxError("The mode revision has no durable identity.")
    with session.no_autoflush:
        persisted_mode = session.exec(
            select(WebsiteFormDeliveryModeRevision)
            .where(WebsiteFormDeliveryModeRevision.id == mode_revision.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
    if persisted_mode is None:
        raise FormDeliveryOutboxError("The mode revision is not durable.")
    try:
        with session.no_autoflush:
            current_mode = resolve_current_form_delivery_mode(
                session,
                persisted_mode.website_id,
                persisted_mode.form_component_configuration_id,
            )
    except Exception as exc:
        raise FormDeliveryOutboxError(
            "Authoritative current form-delivery mode cannot be resolved."
        ) from exc
    if current_mode.id != persisted_mode.id:
        raise FormDeliveryOutboxError(
            "A superseded form-delivery mode cannot accept new submissions."
        )
    with session.no_autoflush:
        authoritative_readiness = form_delivery_readiness(
            session,
            persisted_mode,
            allow_test_only=bool(
                getattr(payload_store, "test_only", False)
                and session_uses_disposable_database(session)
            ),
            secure_payload_store_available=bool(
                payload_store.available and payload_store.encryption_key_reference
            ),
        )
    if (
        not authoritative_readiness.can_submit
        or authoritative_readiness.status != "ready"
    ):
        raise FormDeliveryOutboxError(
            "Authoritative form delivery readiness must pass before storage."
        )
    if not readiness.can_submit or readiness.status != "ready":
        raise FormDeliveryOutboxError("Form delivery readiness must pass before storage.")
    mode_revision = persisted_mode
    if mode_revision.mode not in {
        "atlas_email",
        "atlasops360_native",
        "external_adapter",
    }:
        raise FormDeliveryOutboxError("The selected mode does not use the Atlas gateway.")
    if (
        mode_revision.id is None
        or envelope.delivery_mode_revision_id != mode_revision.id
        or envelope.website_id != mode_revision.website_id
        or envelope.component_configuration_id
        != mode_revision.form_component_configuration_id
        or envelope.audit_identity != mode_revision.audit_identity
        or envelope.destination_adapter_key != mode_revision.provider_key
        or envelope.privacy_policy_identity
        != mode_revision.privacy_policy_reference
        or envelope.retention_policy_identity
        != mode_revision.retention_policy_reference
        or envelope.abuse_policy_identity != mode_revision.abuse_policy_reference
    ):
        raise FormDeliveryOutboxError("The normalized envelope crosses its governed scope.")
    try:
        form_definition = resolve_atlas_rendered_form_definition(
            mode_revision.mode,
            mode_revision.configuration_payload,
        )
        if (
            form_definition is None
            or envelope.submission_contract_version
            != form_definition.contract_version
        ):
            raise ValueError("The form definition identity is unavailable.")
        validate_submission_optional_field_binding(
            form_definition,
            envelope.optional_field,
            envelope.optional_field_definition_revision_identity,
        )
    except (TypeError, ValueError) as exc:
        raise FormDeliveryOutboxError(
            "The normalized envelope does not match its exact field definition."
        ) from exc
    if not payload_store.available or not payload_store.encryption_key_reference:
        raise FormDeliveryOutboxError(
            "Secure payload storage and key management are unavailable."
        )
    received_at = envelope.received_at or datetime.now(UTC)
    if _as_utc(expires_at) < _as_utc(received_at):
        raise FormDeliveryOutboxError("Envelope expiration predates receipt.")
    if (
        not envelope.request_identity
        or not FINGERPRINT_PATTERN.fullmatch(envelope.request_identity)
        or not envelope.anti_spam_decision
    ):
        raise FormDeliveryOutboxError(
            "The normalized envelope lacks request or anti-spam evidence."
        )
    if not SECRET_REFERENCE_PATTERN.fullmatch(
        payload_store.encryption_key_reference or ""
    ):
        raise FormDeliveryOutboxError(
            "The payload-store key identity is not an opaque secret reference."
        )
    required = (
        mode_revision.provider_key,
        mode_revision.adapter_version,
        mode_revision.destination_identity,
        mode_revision.privacy_policy_reference,
        mode_revision.retention_policy_reference,
        mode_revision.abuse_policy_reference,
    )
    if any(value is None or value == "" for value in required):
        raise FormDeliveryOutboxError("The mode revision lacks durable delivery policy.")
    consent_required = bool(
        mode_revision.configuration_payload.get("consent_required", False)
    )
    if consent_required and (
        envelope.consent_accepted is not True
        or not envelope.consent_version
        or not mode_revision.consent_policy_reference
    ):
        raise FormDeliveryOutboxError(
            "The governed consent decision is missing or was not accepted."
        )

    idempotency_digest = canonical_json_hash(
        {
            "website_id": envelope.website_id,
            "component_configuration_id": envelope.component_configuration_id,
            "idempotency_key": envelope.idempotency_key,
        }
    )
    with session.no_autoflush:
        prior_envelope = session.exec(
            select(FormSubmissionEnvelope).where(
                FormSubmissionEnvelope.website_id == envelope.website_id,
                FormSubmissionEnvelope.form_component_configuration_id
                == envelope.component_configuration_id,
                FormSubmissionEnvelope.idempotency_digest == idempotency_digest,
            )
        ).first()
    if prior_envelope is not None:
        exact_replay = bool(
            prior_envelope.delivery_mode_revision_id == mode_revision.id
            and prior_envelope.destination_adapter_key == mode_revision.provider_key
            and hmac.compare_digest(
                prior_envelope.request_identity,
                envelope.request_identity,
            )
        )
        if not exact_replay:
            raise FormDeliveryIdempotencyConflict(
                "The idempotency identity is already bound to another request."
            )
        with session.no_autoflush:
            prior_outbox = session.exec(
                select(FormDeliveryOutbox).where(
                    FormDeliveryOutbox.envelope_id == prior_envelope.id
                )
            ).one()
        return prior_outbox

    payload_reference: str | None = None
    try:
        payload_reference = payload_store.put(envelope)
        if not _SECURE_PAYLOAD_REFERENCE_PATTERN.fullmatch(payload_reference):
            raise FormDeliveryOutboxError(
                "The secure payload identity is not an approved opaque reference."
            )
        durable_envelope = FormSubmissionEnvelope(
            website_id=envelope.website_id,
            form_component_configuration_id=envelope.component_configuration_id,
            delivery_mode_revision_id=mode_revision.id,
            submission_contract_version=envelope.submission_contract_version,
            consent_accepted=envelope.consent_accepted,
            consent_version=envelope.consent_version,
            privacy_policy_reference=mode_revision.privacy_policy_reference or "",
            retention_policy_reference=mode_revision.retention_policy_reference or "",
            abuse_policy_reference=mode_revision.abuse_policy_reference or "",
            anti_spam_decision=envelope.anti_spam_decision,
            idempotency_digest=idempotency_digest,
            received_at=received_at,
            audit_identity=envelope.audit_identity,
            request_identity=envelope.request_identity,
            source_page_identity=envelope.source_page_identity,
            destination_adapter_key=mode_revision.provider_key or "",
            secure_payload_reference=payload_reference,
            encryption_key_reference=payload_store.encryption_key_reference,
            expires_at=expires_at,
            integrity_fingerprint="0" * 64,
        )
        durable_envelope.integrity_fingerprint = form_submission_envelope_fingerprint(
            durable_envelope
        )
        session.add(durable_envelope)
        session.flush()
        if durable_envelope.id is None:
            raise FormDeliveryOutboxError("The envelope identity was not allocated.")
        outbox = FormDeliveryOutbox(
            envelope_id=durable_envelope.id,
            delivery_mode_revision_id=mode_revision.id,
            adapter_key=mode_revision.provider_key or "",
            adapter_version=mode_revision.adapter_version or "",
            destination_identity=mode_revision.destination_identity or "",
            status="queued",
            attempt_count=0,
            next_attempt_at=None,
            last_safe_error_code=None,
            state_version=1,
        )
        session.add(outbox)
        session.flush()
        if commit:
            session.commit()
            session.refresh(outbox)
        return outbox
    except Exception as exc:
        session.rollback()
        if payload_reference is not None:
            try:
                payload_store.delete(payload_reference)
            except Exception:
                pass
        if isinstance(exc, FormDeliveryOutboxError):
            raise
        raise FormDeliveryOutboxError(
            "The secure envelope and outbox transaction failed."
        ) from exc


def process_form_delivery_outbox(
    session: Session,
    outbox_id: int,
    *,
    payload_store: SecureFormPayloadStore,
    allow_test_only: bool,
    transient_retry_at: datetime,
    now: datetime | None = None,
) -> FormDeliveryAttempt:
    """Run one adapter attempt; retry timing must come from an approved caller policy."""

    if (
        allow_test_only or getattr(payload_store, "test_only", False)
    ) and not session_uses_disposable_database(session):
        raise FormDeliveryOutboxError(
            "Test delivery requires an explicitly disposable Session bind."
        )
    attempt_now = _as_utc(now or datetime.now(UTC))
    retry_at = _as_utc(transient_retry_at)
    if retry_at <= attempt_now:
        raise FormDeliveryOutboxError("The transient retry time must be in the future.")

    outbox = session.exec(
        select(FormDeliveryOutbox)
        .where(FormDeliveryOutbox.id == outbox_id)
        .with_for_update()
    ).first()
    if outbox is None:
        raise FormDeliveryOutboxError("The outbox record was not found.")
    if outbox.status not in {"queued", "retrying"}:
        raise FormDeliveryOutboxError("The outbox record is not eligible for delivery.")
    if (
        outbox.next_attempt_at is not None
        and attempt_now < _as_utc(outbox.next_attempt_at)
    ):
        raise FormDeliveryOutboxError("The outbox record is not due for delivery.")
    if outbox.status == "retrying" and outbox.next_attempt_at is None:
        raise FormDeliveryOutboxError("The retrying outbox lacks its retry schedule.")
    envelope_record = session.get(FormSubmissionEnvelope, outbox.envelope_id)
    if (
        envelope_record is None
        or envelope_record.integrity_fingerprint
        != form_submission_envelope_fingerprint(envelope_record)
        or envelope_record.secure_payload_reference is None
    ):
        raise FormDeliveryOutboxError("The secure envelope metadata is unavailable.")
    mode_revision = session.get(
        WebsiteFormDeliveryModeRevision,
        outbox.delivery_mode_revision_id,
    )
    if (
        mode_revision is None
        or mode_revision.id != envelope_record.delivery_mode_revision_id
        or mode_revision.website_id != envelope_record.website_id
        or mode_revision.form_component_configuration_id
        != envelope_record.form_component_configuration_id
        or mode_revision.mode
        not in {"atlas_email", "atlasops360_native", "external_adapter"}
        or mode_revision.lifecycle_status != "active"
        or not mode_revision.enabled
        or mode_revision.integrity_fingerprint
        != form_delivery_mode_fingerprint(mode_revision)
        or outbox.adapter_key != mode_revision.provider_key
        or outbox.adapter_version != mode_revision.adapter_version
        or outbox.destination_identity != mode_revision.destination_identity
        or envelope_record.destination_adapter_key != outbox.adapter_key
    ):
        raise FormDeliveryOutboxError("The outbox delivery identity is invalid.")
    if (
        not payload_store.available
        or not payload_store.encryption_key_reference
        or envelope_record.encryption_key_reference
        != payload_store.encryption_key_reference
    ):
        raise FormDeliveryOutboxError("The secure payload key identity is unavailable.")
    if (
        envelope_record.expires_at is not None
        and attempt_now >= _as_utc(envelope_record.expires_at)
    ):
        raise FormDeliveryOutboxError("The secure envelope has expired.")
    registration = FORM_DELIVERY_PROVIDER_REGISTRY.registration(
        outbox.adapter_key,
        allow_test_only=allow_test_only,
    )
    if (
        registration is None
        or registration.delivery_adapter is None
        or registration.descriptor.provider_key != outbox.adapter_key
        or registration.descriptor.adapter_version != outbox.adapter_version
        or not registration.descriptor.supports(
            mode=mode_revision.mode,  # type: ignore[arg-type]
            form_contract_version=envelope_record.submission_contract_version,
            website_identity=str(envelope_record.website_id),
        )
    ):
        raise FormDeliveryOutboxError("The delivery adapter is unavailable.")
    adapter = registration.delivery_adapter
    if not isinstance(adapter, DeliveryAdapter):
        raise FormDeliveryOutboxError("The delivery adapter contract is invalid.")
    normalized = payload_store.get(envelope_record.secure_payload_reference)
    if (
        normalized.website_id != envelope_record.website_id
        or normalized.component_configuration_id
        != envelope_record.form_component_configuration_id
        or normalized.delivery_mode_revision_id
        != envelope_record.delivery_mode_revision_id
        or normalized.request_identity != envelope_record.request_identity
        or normalized.destination_adapter_key
        != envelope_record.destination_adapter_key
        or canonical_json_hash(
            {
                "website_id": normalized.website_id,
                "component_configuration_id": normalized.component_configuration_id,
                "idempotency_key": normalized.idempotency_key,
            }
        )
        != envelope_record.idempotency_digest
    ):
        raise FormDeliveryOutboxError("The secure envelope payload crosses durable scope.")
    try:
        form_definition = resolve_atlas_rendered_form_definition(
            mode_revision.mode,
            mode_revision.configuration_payload,
        )
        if (
            form_definition is None
            or normalized.submission_contract_version
            != form_definition.contract_version
        ):
            raise ValueError("The form definition identity is unavailable.")
        validate_submission_optional_field_binding(
            form_definition,
            normalized.optional_field,
            normalized.optional_field_definition_revision_identity,
        )
    except (TypeError, ValueError) as exc:
        raise FormDeliveryOutboxError(
            "The secure envelope payload does not match its exact field definition."
        ) from exc
    try:
        delivery_context = resolve_delivery_adapter_context(
            session,
            mode_revision,
            delivery_identity=envelope_record.integrity_fingerprint,
            idempotency_digest=envelope_record.idempotency_digest,
        )
    except Exception as exc:
        raise FormDeliveryOutboxError(
            "The delivery-adapter context is invalid."
        ) from exc

    outbox.status = "processing"
    outbox.next_attempt_at = None
    outbox.state_version += 1
    outbox.updated_at = attempt_now
    session.add(outbox)
    session.flush()
    started_at = attempt_now
    try:
        result = adapter.deliver(
            delivery_context,
            normalized,
        )
    except Exception:
        result = None
    completed_at = _as_utc(now or datetime.now(UTC))
    if result is None or not _valid_adapter_result(result):
        outcome = "permanent_failure"
        safe_error_code = "adapter_contract_failure"
        safe_provider_reference = None
        next_retry_at = None
    else:
        outcome = result.outcome
        safe_error_code = result.safe_error_code
        safe_provider_reference = _opaque_provider_reference(
            result.safe_provider_reference,
            delivery_identity=envelope_record.integrity_fingerprint,
        )
        next_retry_at = retry_at if outcome == "transient_failure" else None

    attempt = FormDeliveryAttempt(
        outbox_id=outbox.id,
        attempt_number=outbox.attempt_count + 1,
        started_at=started_at,
        completed_at=completed_at,
        outcome=outcome,
        safe_error_code=safe_error_code,
        safe_provider_reference=safe_provider_reference,
        next_retry_at=next_retry_at,
        integrity_fingerprint="0" * 64,
    )
    attempt.integrity_fingerprint = form_delivery_attempt_fingerprint(attempt)
    outbox.attempt_count += 1
    outbox.state_version += 1
    outbox.last_safe_error_code = safe_error_code
    outbox.updated_at = completed_at
    if outcome == "delivered":
        outbox.status = "delivered"
        outbox.delivered_at = completed_at
        outbox.next_attempt_at = None
    elif outcome == "transient_failure":
        outbox.status = "retrying"
        outbox.next_attempt_at = retry_at
    else:
        outbox.status = "terminal_failed"
        outbox.failed_at = completed_at
        outbox.next_attempt_at = None
    session.add(attempt)
    session.add(outbox)
    try:
        session.commit()
        session.refresh(attempt)
    except Exception as exc:
        session.rollback()
        raise FormDeliveryOutboxError("Delivery-attempt persistence failed.") from exc
    if outcome in {"delivered", "permanent_failure"}:
        payload_store.delete(envelope_record.secure_payload_reference)
    return attempt


def expire_form_delivery_payload(
    session: Session,
    outbox_id: int,
    *,
    payload_store: SecureFormPayloadStore,
    now: datetime,
) -> FormDeliveryOutbox:
    if getattr(payload_store, "test_only", False) and not session_uses_disposable_database(
        session
    ):
        raise FormDeliveryOutboxError(
            "Test payload cleanup requires an explicitly disposable Session bind."
        )
    expiration_now = _as_utc(now)
    outbox = session.exec(
        select(FormDeliveryOutbox)
        .where(FormDeliveryOutbox.id == outbox_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if outbox is None:
        raise FormDeliveryOutboxError("The outbox record was not found.")
    envelope = session.exec(
        select(FormSubmissionEnvelope)
        .where(FormSubmissionEnvelope.id == outbox.envelope_id)
        .execution_options(populate_existing=True)
    ).first()
    if envelope is None or envelope.expires_at is None:
        session.rollback()
        raise FormDeliveryOutboxError("The outbox has no governed expiration.")
    if expiration_now < _as_utc(envelope.expires_at):
        session.rollback()
        raise FormDeliveryOutboxError("The governed expiration has not arrived.")
    if outbox.status == "processing":
        session.rollback()
        raise FormDeliveryOutboxError(
            "A processing outbox record cannot be expired concurrently."
        )
    if outbox.status not in {
        "queued",
        "retrying",
        "expired",
        "delivered",
        "terminal_failed",
    }:
        session.rollback()
        raise FormDeliveryOutboxError("The outbox record has an invalid state.")

    if outbox.status in {"queued", "retrying"}:
        outbox.status = "expired"
        outbox.expired_at = expiration_now
        outbox.next_attempt_at = None
        outbox.state_version += 1
        outbox.updated_at = expiration_now
        session.add(outbox)
    try:
        # Commit the governed state transition before deleting external payload
        # material. A failed commit must never orphan the durable evidence.
        session.commit()
        session.refresh(outbox)
    except Exception as exc:
        session.rollback()
        raise FormDeliveryOutboxError("Payload expiration persistence failed.") from exc

    if envelope.secure_payload_reference:
        try:
            payload_store.delete(envelope.secure_payload_reference)
        except Exception as exc:
            # The durable terminal state is already coherent. A later idempotent
            # call can retry only the external cleanup.
            raise FormDeliveryOutboxError(
                "Payload expiration is durable but secure cleanup is pending."
            ) from exc
    return outbox


def _value(record: object | Mapping[str, Any], field: str) -> Any:
    return record.get(field) if isinstance(record, Mapping) else getattr(record, field)


def _datetime_value(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _as_utc(value).isoformat()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _valid_adapter_result(value: object) -> bool:
    if not isinstance(value, DeliveryAttemptResult):
        return False
    if value.outcome not in {
        "delivered",
        "transient_failure",
        "permanent_failure",
    }:
        return False
    if not _safe_adapter_text(value.safe_error_code, maximum_length=120):
        return False
    if not _safe_adapter_text(value.safe_provider_reference, maximum_length=240):
        return False
    if value.safe_error_code is not None and (
        value.safe_error_code.strip() != value.safe_error_code
        or any(
            not (character.islower() or character.isdigit() or character in "_-")
            for character in value.safe_error_code
        )
    ):
        return False
    if value.outcome == "delivered":
        return value.safe_error_code is None and value.safe_provider_reference is not None
    return value.safe_error_code is not None


def _opaque_provider_reference(
    value: str | None,
    *,
    delivery_identity: str,
) -> str | None:
    """Domain-separate an adapter reference before it reaches durable storage."""

    if value is None:
        return None
    material = (
        b"project-atlas:form-delivery:provider-reference:v1\x00"
        + delivery_identity.encode("ascii")
        + b"\x00"
        + value.encode("utf-8")
    )
    return hashlib.sha256(material).hexdigest()


def _safe_adapter_text(value: str | None, *, maximum_length: int) -> bool:
    return value is None or bool(
        isinstance(value, str)
        and 0 < len(value) <= maximum_length
        and value.strip() == value
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )
