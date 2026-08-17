from __future__ import annotations

import hashlib
import hmac
import json
from collections import OrderedDict
from dataclasses import asdict
from threading import Lock
from typing import Callable

from app.schemas.form_delivery import FormSubmissionAcceptanceRead
from app.services.form_delivery_test_guard import test_or_disposable_runtime_allowed
from app.website_builder_core.contracts import (
    DeliveryAdapterContext,
    DeliveryAttemptResult,
    FormDeliveryPresentation,
    IdempotencyConflict,
    NormalizedSubmissionEnvelope,
    ProviderDeliveryContext,
)


SYNTHETIC_PROVIDER_KEY = "atlas-synthetic-memory"
SYNTHETIC_PROVIDER_DESTINATION = "memory://discard"
SYNTHETIC_EMAIL_PROVIDER_KEY = "atlas-synthetic-email"
SYNTHETIC_PROVIDER_OWNED_KEY = "atlas-synthetic-provider-owned"
SYNTHETIC_ATLASOPS360_KEY = "atlasops360-synthetic"
SYNTHETIC_EXTERNAL_ADAPTER_KEY = "atlas-synthetic-external"


if not test_or_disposable_runtime_allowed():
    raise RuntimeError(
        "Synthetic form-delivery transports cannot load outside a disposable runtime."
    )


def _require_contained_runtime() -> None:
    if not test_or_disposable_runtime_allowed():
        raise RuntimeError(
            "Synthetic form-delivery transports require a disposable runtime."
        )


class SyntheticDiscardProvider:
    """Stateless legacy V3 adapter: deterministic, network/storage free."""

    provider_key = SYNTHETIC_PROVIDER_KEY

    def __init__(self) -> None:
        _require_contained_runtime()

    def submit(
        self,
        context: ProviderDeliveryContext,
        envelope: NormalizedSubmissionEnvelope,
    ) -> FormSubmissionAcceptanceRead:
        identity = json.dumps(
            {
                "provider_key": context.provider_key,
                "destination_reference": context.destination_reference,
                "secret_reference": context.secret_reference,
                "retention_duration": context.retention_duration,
                "deletion_expiration_behavior": context.deletion_expiration_behavior,
                "spam_strategy": context.spam_strategy,
                "spam_configuration_reference": context.spam_configuration_reference,
                "website_id": envelope.website_id,
                "component_configuration_id": envelope.component_configuration_id,
                "name": envelope.name,
                "phone": envelope.phone,
                "postal_code": envelope.postal_code,
                "requested_service": envelope.requested_service,
                "message": envelope.message,
                "consent_accepted": envelope.consent_accepted,
                "audit_identity": envelope.audit_identity,
                "idempotency_key": envelope.idempotency_key,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        reference = "synthetic-" + hashlib.sha256(identity).hexdigest()[:24]
        return FormSubmissionAcceptanceRead(
            safe_message="Your synthetic rehearsal request was accepted.",
            provider_reference=reference,
        )


class SyntheticNoopSpamControl:
    strategy = "synthetic_test"

    def __init__(self) -> None:
        _require_contained_runtime()

    def supports_reference(self, configuration_reference: str) -> bool:
        return configuration_reference == "synthetic-noop"

    def verify(
        self,
        context: ProviderDeliveryContext,
        envelope: NormalizedSubmissionEnvelope,
    ) -> None:
        if (
            context.spam_strategy != self.strategy
            or not self.supports_reference(context.spam_configuration_reference)
            or envelope.website_id < 1
        ):
            raise ValueError("Synthetic spam-control contract is unavailable")


class SyntheticIdempotencyBoundary:
    strategy = "required_header"
    _maximum_entries = 4096

    def __init__(self, process_key: bytes) -> None:
        _require_contained_runtime()
        self._process_key = process_key
        self._lock = Lock()
        self._results: OrderedDict[str, tuple[str, object]] = OrderedDict()

    def deliver(
        self,
        *,
        namespace: str,
        request_identity: str,
        operation: Callable[[], object],
    ) -> object:
        namespace_hash = hmac.new(
            self._process_key,
            namespace.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        with self._lock:
            prior = self._results.get(namespace_hash)
            if prior is not None:
                prior_identity, result = prior
                if not hmac.compare_digest(prior_identity, request_identity):
                    raise IdempotencyConflict
                self._results.move_to_end(namespace_hash)
                return result
            result = operation()
            self._results[namespace_hash] = (request_identity, result)
            while len(self._results) > self._maximum_entries:
                self._results.popitem(last=False)
            return result


class SyntheticDeliveryAdapter:
    """Configurable deterministic adapter used only by explicit test registry access."""

    def __init__(
        self,
        provider_key: str,
        outcome: str = "delivered",
    ) -> None:
        _require_contained_runtime()
        self.provider_key = provider_key
        self.outcome = outcome
        self.delivery_count = 0
        self.last_context_fingerprint: str | None = None
        self.last_context_scope: tuple[str, int] | None = None
        self.last_recipient_count = 0
        self.last_configuration_reference_keys: tuple[str, ...] = ()
        self.last_envelope_contract: str | None = None
        self.last_envelope_scope: tuple[int, int, int | None] | None = None
        self._lock = Lock()
        self._completed: OrderedDict[
            str, tuple[str, DeliveryAttemptResult]
        ] = OrderedDict()

    def deliver(
        self,
        context: DeliveryAdapterContext,
        envelope: NormalizedSubmissionEnvelope,
    ) -> DeliveryAttemptResult:
        delivery_identity = context.delivery_identity
        if not delivery_identity:
            raise ValueError("A durable delivery identity is required.")
        if context.provider_key != self.provider_key:
            raise ValueError("The delivery context names another provider.")
        request_identity = envelope.request_identity or ""
        with self._lock:
            self.last_context_fingerprint = hashlib.sha256(
                json.dumps(
                    asdict(context),
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.last_context_scope = (context.mode, envelope.website_id)
            self.last_recipient_count = len(context.recipients)
            self.last_configuration_reference_keys = tuple(
                key for key, _value in context.configuration_references
            )
            self.last_envelope_contract = type(envelope).__name__
            self.last_envelope_scope = (
                envelope.website_id,
                envelope.component_configuration_id,
                envelope.delivery_mode_revision_id,
            )
            prior = self._completed.get(delivery_identity)
            if prior is not None:
                prior_request_identity, prior_result = prior
                if not hmac.compare_digest(prior_request_identity, request_identity):
                    raise IdempotencyConflict
                self._completed.move_to_end(delivery_identity)
                return prior_result

            self.delivery_count += 1
            if self.outcome == "transient_failure":
                return DeliveryAttemptResult(
                    outcome="transient_failure",
                    safe_error_code="synthetic_transient_failure",
                )
            if self.outcome == "permanent_failure":
                result = DeliveryAttemptResult(
                    outcome="permanent_failure",
                    safe_error_code="synthetic_permanent_failure",
                )
            else:
                reference_seed = (
                    f"{self.provider_key}:{envelope.website_id}:"
                    f"{envelope.component_configuration_id}:{envelope.idempotency_key}"
                )
                result = DeliveryAttemptResult(
                    outcome="delivered",
                    safe_provider_reference=(
                        "synthetic-"
                        + hashlib.sha256(reference_seed.encode()).hexdigest()[:24]
                    ),
                )
            self._completed[delivery_identity] = (request_identity, result)
            while len(self._completed) > 4096:
                self._completed.popitem(last=False)
            return result


class SyntheticProviderOwnedPresentationAdapter:
    provider_key = SYNTHETIC_PROVIDER_OWNED_KEY

    def __init__(self) -> None:
        _require_contained_runtime()

    def presentation(
        self,
        configuration: dict[str, object],
    ) -> FormDeliveryPresentation:
        return FormDeliveryPresentation(
            kind=str(configuration["presentation_strategy"]),  # type: ignore[arg-type]
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
