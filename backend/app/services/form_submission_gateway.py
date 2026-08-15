from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from types import MappingProxyType
from typing import Callable, Literal, Protocol
from urllib.parse import urlsplit

from fastapi import Request
from pydantic import ValidationError
from sqlmodel import Session

from app.core.config import get_settings
from app.models import (
    ThemeFamily,
    ThemeFamilyVersion,
    Website,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
)
from app.schemas.theme_families import (
    CompactEstimateFormConfigurationV3,
    FormBehaviorReadinessStateRead,
    FormPrivacyReadinessStateRead,
    FormProviderReadinessStateRead,
    FormReadinessItemRead,
    FormRetentionReadinessStateRead,
    FormSecurityReadinessStateRead,
    FormSpamReadinessStateRead,
    PerformanceLocalFormReadinessRead,
    PerformanceLocalFormSubmissionInput,
    PerformanceLocalFormSubmissionRead,
)
from app.services import theme_configurations as theme_service


SYNTHETIC_PROVIDER_KEY = "atlas-synthetic-memory"
SYNTHETIC_PROVIDER_DESTINATION = "memory://discard"
_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._~:/+=-]{32,128}$")
_PHONE_INPUT_PATTERN = re.compile(r"^[+0-9().\-\s]+$")
_POSTAL_PATTERN = re.compile(r"^[A-Z0-9 -]+$")
_CSRF_PROCESS_KEY = secrets.token_bytes(32)


class FormGatewayError(ValueError):
    """A stable, value-free public gateway failure."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.safe_message = message


class _IdempotencyConflict(Exception):
    """Internal signal translated to one Atlas-owned, value-free response."""


@dataclass(frozen=True)
class NormalizedSubmissionEnvelope:
    website_id: int
    component_configuration_id: int
    name: str
    phone: str
    postal_code: str
    requested_service: str
    message: str | None
    consent_accepted: bool | None
    audit_identity: str
    idempotency_key: str


@dataclass(frozen=True)
class ProviderDeliveryContext:
    """Governed provider metadata; references are opaque and never resolved here."""

    provider_key: str
    destination_reference: str
    secret_reference: str
    audit_identity: str
    privacy_policy_destination: str
    consent_mode: str
    consent_text_version: str | None
    retention_duration: str
    deletion_expiration_behavior: str
    spam_strategy: str
    spam_configuration_reference: str
    success_behavior: str
    failure_behavior: str


class SubmissionProvider(Protocol):
    provider_key: str

    def submit(
        self,
        context: ProviderDeliveryContext,
        envelope: NormalizedSubmissionEnvelope,
    ) -> PerformanceLocalFormSubmissionRead: ...


class SpamControlAdapter(Protocol):
    strategy: str

    def supports_reference(self, configuration_reference: str) -> bool: ...

    def verify(
        self,
        context: ProviderDeliveryContext,
        envelope: NormalizedSubmissionEnvelope,
    ) -> None: ...


class IdempotencyBoundary(Protocol):
    strategy: str

    def deliver(
        self,
        *,
        namespace: str,
        request_identity: str,
        operation: Callable[[], PerformanceLocalFormSubmissionRead],
    ) -> PerformanceLocalFormSubmissionRead: ...


class _SyntheticDiscardProvider:
    """Stateless test adapter: deterministic, network-free, storage-free."""

    provider_key = SYNTHETIC_PROVIDER_KEY

    def submit(
        self,
        context: ProviderDeliveryContext,
        envelope: NormalizedSubmissionEnvelope,
    ) -> PerformanceLocalFormSubmissionRead:
        identity = json.dumps(
            {
                "provider_key": context.provider_key,
                "destination_reference": context.destination_reference,
                "secret_reference": context.secret_reference,
                "retention_duration": context.retention_duration,
                "deletion_expiration_behavior": (
                    context.deletion_expiration_behavior
                ),
                "spam_strategy": context.spam_strategy,
                "spam_configuration_reference": (
                    context.spam_configuration_reference
                ),
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
        return PerformanceLocalFormSubmissionRead(
            safe_message="Your synthetic rehearsal request was accepted.",
            provider_reference=reference,
        )


class _SyntheticNoopSpamControl:
    """Contained rehearsal control; validates the exact synthetic strategy only."""

    strategy = "synthetic_test"

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
            raise _unavailable()


class _SyntheticIdempotencyBoundary:
    """Process-local replay control storing only keyed hashes and safe results."""

    strategy = "required_header"
    _maximum_entries = 4096

    def __init__(self) -> None:
        self._lock = Lock()
        self._results: OrderedDict[
            str,
            tuple[str, PerformanceLocalFormSubmissionRead],
        ] = OrderedDict()

    def deliver(
        self,
        *,
        namespace: str,
        request_identity: str,
        operation: Callable[[], PerformanceLocalFormSubmissionRead],
    ) -> PerformanceLocalFormSubmissionRead:
        namespace_hash = hmac.new(
            _CSRF_PROCESS_KEY,
            namespace.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        with self._lock:
            prior = self._results.get(namespace_hash)
            if prior is not None:
                prior_identity, result = prior
                if not hmac.compare_digest(prior_identity, request_identity):
                    raise _IdempotencyConflict
                self._results.move_to_end(namespace_hash)
                return result
            result = operation()
            self._results[namespace_hash] = (request_identity, result)
            while len(self._results) > self._maximum_entries:
                self._results.popitem(last=False)
            return result


# Production discovery remains intentionally empty. The synthetic adapter lives
# in a separate immutable registry and is reachable only through all rehearsal
# guards below.
PRODUCTION_SUBMISSION_PROVIDERS: MappingProxyType[str, SubmissionProvider] = (
    MappingProxyType({})
)
TEST_ONLY_SUBMISSION_PROVIDERS: MappingProxyType[str, SubmissionProvider] = (
    MappingProxyType({SYNTHETIC_PROVIDER_KEY: _SyntheticDiscardProvider()})
)
PRODUCTION_SPAM_CONTROLS: MappingProxyType[str, SpamControlAdapter] = MappingProxyType(
    {}
)
TEST_ONLY_SPAM_CONTROLS: MappingProxyType[str, SpamControlAdapter] = MappingProxyType(
    {"synthetic_test": _SyntheticNoopSpamControl()}
)
PRODUCTION_IDEMPOTENCY_BOUNDARIES: MappingProxyType[str, IdempotencyBoundary] = (
    MappingProxyType({})
)
TEST_ONLY_IDEMPOTENCY_BOUNDARIES: MappingProxyType[str, IdempotencyBoundary] = (
    MappingProxyType({"required_header": _SyntheticIdempotencyBoundary()})
)


@dataclass(frozen=True)
class FormGatewayPreflight:
    website: Website
    configuration: WebsiteThemeConfiguration
    component: WebsiteThemeComponentConfiguration
    contract: CompactEstimateFormConfigurationV3
    readiness: PerformanceLocalFormReadinessRead
    mode: Literal["active", "activation_rehearsal"]


def evaluate_form_readiness(
    component: WebsiteThemeComponentConfiguration | None,
    *,
    mode: Literal["active", "inactive_draft_preview", "activation_rehearsal"],
    test_environment_allowed: bool | None = None,
) -> PerformanceLocalFormReadinessRead:
    if component is None:
        return _missing_form_readiness()

    try:
        contract = CompactEstimateFormConfigurationV3.model_validate(
            component.configuration_payload
        )
    except ValidationError:
        return _missing_form_readiness(
            component_configuration_id=component.id,
            submission_state="invalid",
            initial=[
                _blocker(
                    "invalid_form_contract",
                    "configuration_payload",
                    "The governed V3 form contract is invalid.",
                )
            ],
        )

    if test_environment_allowed is None:
        test_environment_allowed = disposable_rehearsal_environment_allowed()
    rehearsal_adapter = (
        mode == "activation_rehearsal"
        and contract.provider.test_only
        and test_environment_allowed
        and contract.provider.provider_key in TEST_ONLY_SUBMISSION_PROVIDERS
    )
    production_adapter = (
        mode == "active"
        and not contract.provider.test_only
        and contract.provider.provider_key in PRODUCTION_SUBMISSION_PROVIDERS
    )
    adapter_registered = rehearsal_adapter or production_adapter
    rehearsal_spam_adapter = TEST_ONLY_SPAM_CONTROLS.get(
        contract.spam.strategy or ""
    )
    production_spam_adapter = PRODUCTION_SPAM_CONTROLS.get(
        contract.spam.strategy or ""
    )
    rehearsal_spam_control = (
        mode == "activation_rehearsal"
        and contract.provider.test_only
        and test_environment_allowed
        and _spam_adapter_supports(
            rehearsal_spam_adapter,
            contract.spam.configuration_reference,
        )
    )
    production_spam_control = (
        mode == "active"
        and not contract.provider.test_only
        and _spam_adapter_supports(
            production_spam_adapter,
            contract.spam.configuration_reference,
        )
    )
    spam_control_registered = rehearsal_spam_control or production_spam_control
    idempotency_strategy = contract.security.idempotency_strategy
    rehearsal_idempotency_boundary = (
        mode == "activation_rehearsal"
        and contract.provider.test_only
        and test_environment_allowed
        and idempotency_strategy in TEST_ONLY_IDEMPOTENCY_BOUNDARIES
    )
    production_idempotency_boundary = (
        mode == "active"
        and not contract.provider.test_only
        and idempotency_strategy in PRODUCTION_IDEMPOTENCY_BOUNDARIES
    )
    idempotency_boundary_registered = (
        rehearsal_idempotency_boundary or production_idempotency_boundary
    )

    blockers: list[FormReadinessItemRead] = []

    def require(field: str, value: object, code: str, reason: str) -> None:
        if value is None or value is False or value == "":
            blockers.append(_blocker(code, field, reason))

    require(
        "provider.provider_key",
        contract.provider.provider_key,
        "missing_provider",
        "A governed submission-provider identity is required.",
    )
    require(
        "provider.destination",
        contract.provider.destination,
        "missing_provider_destination",
        "A governed provider destination is required.",
    )
    if not adapter_registered:
        blockers.append(
            _blocker(
                "provider_adapter_unavailable",
                "provider.provider_key",
                "No adapter is registered for this form in the current runtime mode.",
            )
        )
    require(
        "privacy.policy_destination",
        contract.privacy.policy_destination,
        "missing_privacy_destination",
        "An approved privacy-policy destination is required.",
    )
    active_loopback_privacy = (
        mode == "active"
        and _is_loopback_http_policy_destination(
            contract.privacy.policy_destination
        )
    )
    if active_loopback_privacy:
        blockers.append(
            _blocker(
                "loopback_privacy_destination_forbidden",
                "privacy.policy_destination",
                "Active delivery requires a relative or HTTPS privacy-policy destination.",
            )
        )
    require(
        "privacy.consent_mode",
        contract.privacy.consent_mode,
        "missing_consent_mode",
        "An approved consent mode is required.",
    )
    if contract.privacy.consent_mode == "explicit":
        require(
            "privacy.consent_text_version",
            contract.privacy.consent_text_version,
            "missing_consent_text_version",
            "Explicit consent requires an approved text version.",
        )
    require(
        "retention.duration",
        contract.retention.duration,
        "missing_retention_duration",
        "An approved retention duration is required.",
    )
    require(
        "retention.deletion_expiration_behavior",
        contract.retention.deletion_expiration_behavior,
        "missing_deletion_behavior",
        "An approved deletion or expiration behavior is required.",
    )
    require(
        "spam.strategy",
        contract.spam.strategy,
        "missing_spam_strategy",
        "An approved spam-control strategy is required.",
    )
    if not spam_control_registered:
        blockers.append(
            _blocker(
                "spam_adapter_unavailable",
                "spam.strategy",
                "No Atlas-owned spam-control adapter is registered for this strategy.",
            )
        )
    require(
        "success_behavior",
        contract.success_behavior,
        "missing_success_behavior",
        "An approved success behavior is required.",
    )
    require(
        "failure_behavior",
        contract.failure_behavior,
        "missing_failure_behavior",
        "An approved failure behavior is required.",
    )
    require(
        "provider.provider_secret_reference",
        contract.provider.provider_secret_reference,
        "missing_secret_reference",
        "An opaque provider secret reference is required.",
    )
    require(
        "security.same_origin_policy",
        contract.security.same_origin_policy,
        "missing_same_origin_policy",
        "An exact same-origin policy is required.",
    )
    require(
        "security.csrf_policy",
        contract.security.csrf_policy,
        "missing_csrf_policy",
        "An origin-and-token CSRF policy is required.",
    )
    require(
        "security.request_size_limit_bytes",
        contract.security.request_size_limit_bytes,
        "missing_request_size_policy",
        "A bounded request-size policy is required.",
    )
    require(
        "security.idempotency_strategy",
        contract.security.idempotency_strategy,
        "missing_idempotency_strategy",
        "A required-header idempotency strategy is required.",
    )
    if not idempotency_boundary_registered:
        blockers.append(
            _blocker(
                "idempotency_boundary_unavailable",
                "security.idempotency_strategy",
                "No Atlas-owned idempotency boundary is registered for this strategy.",
            )
        )
    require(
        "audit_identity",
        contract.audit_identity,
        "missing_audit_identity",
        "An exact form-governance audit identity is required.",
    )
    if contract.submission_state == "disabled_pending_provider_configuration":
        blockers.insert(
            0,
            _blocker(
                "submission_disabled",
                "submission_state",
                "Form submission is disabled pending governed configuration.",
            ),
        )
    if mode == "activation_rehearsal" and not test_environment_allowed:
        blockers.append(
            _blocker(
                "rehearsal_environment_refused",
                "provider.test_only",
                "The synthetic adapter is restricted to an explicit disposable loopback runtime.",
            )
        )
    if mode != "activation_rehearsal" and contract.provider.test_only:
        blockers.append(
            _blocker(
                "test_provider_containment",
                "provider.test_only",
                "A test-only provider cannot enter active delivery.",
            )
        )

    ready = not blockers
    privacy_ready = bool(
        contract.privacy.policy_destination
        and not active_loopback_privacy
        and contract.privacy.consent_mode
        and (
            contract.privacy.consent_mode != "explicit"
            or contract.privacy.consent_text_version
        )
    )
    retention_ready = bool(
        contract.retention.duration
        and contract.retention.deletion_expiration_behavior
    )
    behavior_ready = bool(contract.success_behavior and contract.failure_behavior)
    security_ready = bool(
        contract.provider.provider_secret_reference
        and contract.security.same_origin_policy
        and contract.security.csrf_policy
        and contract.security.request_size_limit_bytes
        and contract.security.idempotency_strategy
        and idempotency_boundary_registered
    )
    return PerformanceLocalFormReadinessRead(
        status="ready" if ready else "blocked",
        can_submit=ready,
        submission_state=contract.submission_state,
        component_configuration_id=component.id,
        provider_state=FormProviderReadinessStateRead(
            provider_key=contract.provider.provider_key,
            destination_configured=contract.provider.destination is not None,
            adapter_registered=adapter_registered,
            test_only=contract.provider.test_only,
        ),
        privacy=FormPrivacyReadinessStateRead(
            destination_configured=contract.privacy.policy_destination is not None,
            consent_mode=contract.privacy.consent_mode,
            consent_text_version=contract.privacy.consent_text_version,
            ready=privacy_ready,
        ),
        retention=FormRetentionReadinessStateRead(
            duration_configured=contract.retention.duration is not None,
            deletion_behavior_configured=(
                contract.retention.deletion_expiration_behavior is not None
            ),
            ready=retention_ready,
        ),
        spam=FormSpamReadinessStateRead(
            strategy=contract.spam.strategy,
            ready=bool(contract.spam.strategy and spam_control_registered),
        ),
        behavior=FormBehaviorReadinessStateRead(
            success_configured=contract.success_behavior is not None,
            failure_configured=contract.failure_behavior is not None,
            ready=behavior_ready,
        ),
        security=FormSecurityReadinessStateRead(
            secret_reference_configured=(
                contract.provider.provider_secret_reference is not None
            ),
            same_origin_policy=contract.security.same_origin_policy,
            csrf_policy=contract.security.csrf_policy,
            csrf_token=(
                _csrf_token(component, contract.audit_identity)
                if security_ready and ready
                else None
            ),
            request_size_limit_bytes=contract.security.request_size_limit_bytes,
            idempotency_strategy=contract.security.idempotency_strategy,
            ready=security_ready,
        ),
        audit_identity=contract.audit_identity,
        blockers=blockers,
    )


def preflight_form_gateway(
    session: Session,
    website_id: int,
    component_configuration_id: int,
) -> FormGatewayPreflight:
    website = session.get(Website, website_id)
    component = session.get(
        WebsiteThemeComponentConfiguration,
        component_configuration_id,
    )
    if website is None or component is None:
        raise _unavailable()
    if (
        component.website_id != website_id
        or component.component_key != "compact_estimate_form"
        or component.component_contract_version != 3
        or component.lifecycle_status != "current"
        or not component.enabled
        or component.scope_type != "website_default"
        or component.planned_page_id is not None
        or component.overrides_component_configuration_id is not None
    ):
        raise _unavailable()
    configuration = session.get(
        WebsiteThemeConfiguration,
        component.website_theme_configuration_id,
    )
    if configuration is None or configuration.website_id != website_id:
        raise _unavailable()
    version = session.get(ThemeFamilyVersion, configuration.theme_family_version_id)
    family = (
        session.get(ThemeFamily, version.theme_family_id)
        if version is not None
        else None
    )
    if version is None or family is None or family.family_key != "performance-local" or version.version != 3:
        raise _unavailable()
    from app.services.theme_delivery import (
        ThemeDeliveryError,
        _validate_activated_rehearsal_component,
        _validate_activated_rehearsal_configuration,
    )

    try:
        theme_service._validate_family(family)
        theme_service._validate_family_version(session, version)
        contract = CompactEstimateFormConfigurationV3.model_validate(
            component.configuration_payload
        )
        activated_rehearsal = (
            contract.submission_state == "rehearsal_ready"
            and configuration.lifecycle_status == "active"
        )
        if activated_rehearsal:
            _validate_activated_rehearsal_configuration(
                session,
                configuration=configuration,
                version=version,
                family=family,
            )
            _validate_activated_rehearsal_component(
                session,
                configuration=configuration,
                component=component,
            )
        else:
            theme_service._validate_component_configuration(session, component)
    except (
        ValueError,
        ValidationError,
        theme_service.ThemeConfigurationError,
        ThemeDeliveryError,
    ):
        raise _unavailable() from None

    mode: Literal["active", "activation_rehearsal"]
    if contract.submission_state == "rehearsal_ready":
        mode = "activation_rehearsal"
    else:
        mode = "active"
    if mode == "active":
        if (
            contract.submission_state != "production_configured"
            or version.lifecycle_status != "approved"
            or not version.production_ready
            or configuration.lifecycle_status != "active"
            or configuration.materialized_theme_id is None
            or configuration.website_theme_selection_id is None
            or component.activation_identity is None
            or component.activated_at is None
            or component.rollback_identity is not None
            or component.rollback_at is not None
        ):
            raise _unavailable()
        try:
            theme_service._require_audit_coverage(
                session,
                families=[family],
                versions=[version],
                configurations=[configuration],
                components=[component],
            )
        except theme_service.ThemeConfigurationError:
            raise _unavailable() from None
    else:
        if (
            contract.submission_state != "rehearsal_ready"
            or configuration.lifecycle_status != "active"
            or version.lifecycle_status != "preview_candidate"
            or version.production_ready
            or not contract.provider.test_only
            or component.activation_identity is None
            or component.activated_at is None
            or component.rollback_identity is not None
            or component.rollback_at is not None
            or not disposable_rehearsal_environment_allowed()
            or not _session_uses_explicit_disposable_database(session)
        ):
            raise _unavailable()
        try:
            theme_service._require_audit_coverage(
                session,
                families=[family],
                versions=[version],
                configurations=[configuration],
                components=[component],
            )
        except theme_service.ThemeConfigurationError:
            raise _unavailable() from None
    readiness = evaluate_form_readiness(component, mode=mode)
    if not readiness.can_submit:
        raise _unavailable()
    return FormGatewayPreflight(
        website=website,
        configuration=configuration,
        component=component,
        contract=contract,
        readiness=readiness,
        mode=mode,
    )


async def submit_preflighted_request(
    request: Request,
    preflight: FormGatewayPreflight,
) -> PerformanceLocalFormSubmissionRead:
    if request.scope.get("query_string", b""):
        request.scope["query_string"] = b""
        raise FormGatewayError(
            400,
            "query_parameters_forbidden",
            "Form submissions do not accept query parameters.",
        )
    _require_origin(request, preflight)
    _require_csrf(request, preflight)
    idempotency_key = _require_idempotency_key(request)
    limit = preflight.contract.security.request_size_limit_bytes
    if limit is None:  # guarded by readiness; retain fail-closed defense in depth
        raise _unavailable()
    body = await _read_bounded_json_body(request, limit)
    values = _normalize_submission(body, preflight.contract)
    envelope = NormalizedSubmissionEnvelope(
        website_id=preflight.website.id,
        component_configuration_id=preflight.component.id,
        audit_identity=preflight.contract.audit_identity or "",
        idempotency_key=idempotency_key,
        **values.model_dump(mode="python"),
    )
    context = _provider_delivery_context(preflight)
    spam_control = _spam_control_for(preflight)
    try:
        spam_control.verify(context, envelope)
    except Exception:
        raise _unavailable() from None
    provider = _provider_for(preflight)
    idempotency = _idempotency_boundary_for(preflight)

    def submit_to_provider() -> PerformanceLocalFormSubmissionRead:
        try:
            return provider.submit(context, envelope)
        except Exception:
            raise _unavailable() from None

    try:
        return idempotency.deliver(
            namespace=(
                f"{preflight.website.id}:{preflight.component.id}:"
                f"{preflight.component.integrity_fingerprint}:{idempotency_key}"
            ),
            request_identity=_submission_request_identity(context, envelope),
            operation=submit_to_provider,
        )
    except _IdempotencyConflict:
        raise FormGatewayError(
            409,
            "idempotency_conflict",
            "The Idempotency-Key was already used for a different request.",
        ) from None
    except Exception:
        raise _unavailable() from None


def disposable_rehearsal_environment_allowed() -> bool:
    settings = get_settings()
    if settings.atlas_runtime_mode not in {"automated_test", "activation_rehearsal"}:
        return False
    if not _is_disposable_database(settings.database_url):
        return False
    return _is_loopback_origin(str(settings.frontend_origin))


def require_loopback_request(request: Request) -> None:
    host = request.client.host if request.client is not None else None
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise FormGatewayError(
            404,
            "rehearsal_route_unavailable",
            "The rehearsal route is available only on a loopback client.",
        )
    if not disposable_rehearsal_environment_allowed():
        raise FormGatewayError(
            404,
            "rehearsal_route_unavailable",
            "The rehearsal route is unavailable in this runtime.",
        )


def require_local_operator_request(request: Request) -> None:
    """Guard explicit inactive preview without requiring a disposable database."""

    host = request.client.host if request.client is not None else None
    settings = get_settings()
    if (
        host not in {"127.0.0.1", "::1", "localhost", "testclient"}
        or not _is_loopback_origin(str(settings.frontend_origin))
    ):
        raise FormGatewayError(
            404,
            "local_preview_unavailable",
            "The local preview route is unavailable in this runtime.",
        )


def _provider_for(preflight: FormGatewayPreflight) -> SubmissionProvider:
    key = preflight.contract.provider.provider_key
    if preflight.mode == "activation_rehearsal":
        if not disposable_rehearsal_environment_allowed():
            raise _unavailable()
        provider = TEST_ONLY_SUBMISSION_PROVIDERS.get(key or "")
    else:
        provider = PRODUCTION_SUBMISSION_PROVIDERS.get(key or "")
    if provider is None:
        raise _unavailable()
    return provider


def _spam_control_for(preflight: FormGatewayPreflight) -> SpamControlAdapter:
    strategy = preflight.contract.spam.strategy or ""
    configuration_reference = (
        preflight.contract.spam.configuration_reference or ""
    )
    if preflight.mode == "activation_rehearsal":
        if not disposable_rehearsal_environment_allowed():
            raise _unavailable()
        adapter = TEST_ONLY_SPAM_CONTROLS.get(strategy)
    else:
        adapter = PRODUCTION_SPAM_CONTROLS.get(strategy)
    if not _spam_adapter_supports(adapter, configuration_reference):
        raise _unavailable()
    assert adapter is not None
    return adapter


def _spam_adapter_supports(
    adapter: SpamControlAdapter | None,
    configuration_reference: str | None,
) -> bool:
    if adapter is None or not configuration_reference:
        return False
    try:
        return adapter.supports_reference(configuration_reference) is True
    except Exception:
        return False


def _idempotency_boundary_for(
    preflight: FormGatewayPreflight,
) -> IdempotencyBoundary:
    strategy = preflight.contract.security.idempotency_strategy or ""
    if preflight.mode == "activation_rehearsal":
        if not disposable_rehearsal_environment_allowed():
            raise _unavailable()
        boundary = TEST_ONLY_IDEMPOTENCY_BOUNDARIES.get(strategy)
    else:
        boundary = PRODUCTION_IDEMPOTENCY_BOUNDARIES.get(strategy)
    if boundary is None:
        raise _unavailable()
    return boundary


def _provider_delivery_context(
    preflight: FormGatewayPreflight,
) -> ProviderDeliveryContext:
    contract = preflight.contract
    required = (
        contract.provider.provider_key,
        contract.provider.destination,
        contract.provider.provider_secret_reference,
        contract.audit_identity,
        contract.privacy.policy_destination,
        contract.privacy.consent_mode,
        contract.retention.duration,
        contract.retention.deletion_expiration_behavior,
        contract.spam.strategy,
        contract.spam.configuration_reference,
        contract.success_behavior,
        contract.failure_behavior,
    )
    if any(value is None or value == "" for value in required):
        raise _unavailable()
    return ProviderDeliveryContext(
        provider_key=contract.provider.provider_key or "",
        destination_reference=contract.provider.destination or "",
        secret_reference=contract.provider.provider_secret_reference or "",
        audit_identity=contract.audit_identity or "",
        privacy_policy_destination=contract.privacy.policy_destination or "",
        consent_mode=contract.privacy.consent_mode or "",
        consent_text_version=contract.privacy.consent_text_version,
        retention_duration=contract.retention.duration or "",
        deletion_expiration_behavior=(
            contract.retention.deletion_expiration_behavior or ""
        ),
        spam_strategy=contract.spam.strategy or "",
        spam_configuration_reference=(
            contract.spam.configuration_reference or ""
        ),
        success_behavior=contract.success_behavior or "",
        failure_behavior=contract.failure_behavior or "",
    )


def _submission_request_identity(
    context: ProviderDeliveryContext,
    envelope: NormalizedSubmissionEnvelope,
) -> str:
    value = {
        "context": context.__dict__,
        "envelope": {
            key: item
            for key, item in envelope.__dict__.items()
            if key != "idempotency_key"
        },
    }
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _require_origin(request: Request, preflight: FormGatewayPreflight) -> None:
    observed_values = request.headers.getlist("origin")
    observed = observed_values[0] if len(observed_values) == 1 else None
    expected = (
        str(get_settings().frontend_origin)
        if preflight.mode == "activation_rehearsal"
        else preflight.website.public_url
    )
    observed_origin = _normalized_origin(observed) if observed is not None else None
    expected_origin = _normalized_origin(expected)
    if (
        observed_origin is None
        or expected_origin is None
        or observed_origin != expected_origin
    ):
        raise FormGatewayError(403, "origin_rejected", "The request origin is not allowed.")
    if preflight.mode == "activation_rehearsal":
        require_loopback_request(request)


def _require_csrf(request: Request, preflight: FormGatewayPreflight) -> None:
    supplied_values = request.headers.getlist("x-atlas-csrf-token")
    supplied = supplied_values[0] if len(supplied_values) == 1 else ""
    expected = _csrf_token(preflight.component, preflight.contract.audit_identity)
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise FormGatewayError(403, "csrf_rejected", "The request token is not valid.")


def _require_idempotency_key(request: Request) -> str:
    values = request.headers.getlist("idempotency-key")
    value = values[0] if len(values) == 1 else ""
    if not _IDEMPOTENCY_PATTERN.fullmatch(value):
        raise FormGatewayError(
            400,
            "idempotency_key_invalid",
            "A valid Idempotency-Key header is required.",
        )
    return value


async def _read_bounded_json_body(request: Request, limit: int) -> object:
    content_encodings = request.headers.getlist("content-encoding")
    if content_encodings and (
        len(content_encodings) != 1
        or content_encodings[0].strip().lower() != "identity"
    ):
        raise FormGatewayError(
            415,
            "unsupported_content_encoding",
            "The request must not use content encoding.",
        )
    content_types = request.headers.getlist("content-type")
    content_type = content_types[0] if len(content_types) == 1 else ""
    media_type, *parameters = [part.strip().lower() for part in content_type.split(";")]
    if (
        media_type != "application/json"
        or len(parameters) > 1
        or any(
            parameter not in {"charset=utf-8", "charset=\"utf-8\""}
            for parameter in parameters
        )
    ):
        raise FormGatewayError(
            415,
            "unsupported_content_type",
            "The request must use application/json with UTF-8 encoding.",
        )
    length_headers = request.headers.getlist("content-length")
    if len(length_headers) > 1:
        raise FormGatewayError(400, "invalid_content_length", "The request is invalid.")
    if length_headers:
        length_header = length_headers[0]
        try:
            declared_length = int(length_header)
        except ValueError:
            raise FormGatewayError(400, "invalid_content_length", "The request is invalid.") from None
        if declared_length < 0 or declared_length > limit:
            raise FormGatewayError(413, "request_too_large", "The request is too large.")

    chunks: list[bytes] = []
    observed_length = 0
    try:
        async for chunk in request.stream():
            observed_length += len(chunk)
            if observed_length > limit:
                raise FormGatewayError(413, "request_too_large", "The request is too large.")
            chunks.append(chunk)
    except FormGatewayError:
        raise
    except Exception:
        raise FormGatewayError(400, "request_invalid", "The request is invalid.") from None
    try:
        parsed = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise FormGatewayError(400, "malformed_json", "The JSON request is malformed.") from None
    if not _json_structure_is_bounded(parsed):
        raise FormGatewayError(400, "malformed_json", "The JSON request is malformed.")
    return parsed


def _json_structure_is_bounded(value: object) -> bool:
    """Bound parser output independently of byte size without recursive walking."""

    stack: list[tuple[object, int]] = [(value, 0)]
    observed_nodes = 0
    while stack:
        item, depth = stack.pop()
        observed_nodes += 1
        if observed_nodes > 128 or depth > 8:
            return False
        if isinstance(item, dict):
            stack.extend((nested, depth + 1) for nested in item.values())
        elif isinstance(item, list):
            stack.extend((nested, depth + 1) for nested in item)
    return True


def _normalize_submission(
    body: object,
    contract: CompactEstimateFormConfigurationV3,
) -> PerformanceLocalFormSubmissionInput:
    try:
        parsed = PerformanceLocalFormSubmissionInput.model_validate(body)
    except ValidationError:
        raise FormGatewayError(422, "submission_invalid", "The submitted fields are invalid.") from None

    raw_values: dict[str, str | None] = {
        "name": parsed.name,
        "phone": parsed.phone,
        "postal-code": parsed.postal_code,
        "requested-service": parsed.requested_service,
        "message": parsed.message,
    }
    field_contracts = {item.field_key: item for item in contract.fields}
    normalized: dict[str, str | bool | None] = {}
    public_keys = {
        "name": "name",
        "phone": "phone",
        "postal-code": "postal_code",
        "requested-service": "requested_service",
        "message": "message",
    }
    for durable_key, value in raw_values.items():
        field = field_contracts[durable_key]
        cleaned = _normalize_plain_text(value, required=field.required)
        if cleaned is not None and (
            len(cleaned) < field.validation_contract.minimum_length
            or len(cleaned) > field.maximum_length
        ):
            raise FormGatewayError(422, "submission_invalid", "The submitted fields are invalid.")
        normalized[public_keys[durable_key]] = cleaned

    phone = normalized["phone"]
    postal = normalized["postal_code"]
    if not isinstance(phone, str) or not _PHONE_INPUT_PATTERN.fullmatch(phone):
        raise FormGatewayError(422, "submission_invalid", "The submitted fields are invalid.")
    digits = "".join(character for character in phone if character.isdigit())
    if not 7 <= len(digits) <= 15 or phone.count("+") > 1 or ("+" in phone and not phone.startswith("+")):
        raise FormGatewayError(422, "submission_invalid", "The submitted fields are invalid.")
    normalized["phone"] = ("+" if phone.startswith("+") else "") + digits
    if not isinstance(postal, str):
        raise FormGatewayError(422, "submission_invalid", "The submitted fields are invalid.")
    normalized_postal = " ".join(postal.upper().split())
    if not _POSTAL_PATTERN.fullmatch(normalized_postal):
        raise FormGatewayError(422, "submission_invalid", "The submitted fields are invalid.")
    normalized["postal_code"] = normalized_postal

    if contract.privacy.consent_mode == "explicit" and parsed.consent_accepted is not True:
        raise FormGatewayError(422, "consent_required", "Required consent was not accepted.")
    normalized["consent_accepted"] = parsed.consent_accepted
    return PerformanceLocalFormSubmissionInput.model_validate(normalized)


def _normalize_plain_text(value: str | None, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise FormGatewayError(422, "submission_invalid", "The submitted fields are invalid.")
        return None
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        if required:
            raise FormGatewayError(422, "submission_invalid", "The submitted fields are invalid.")
        return None
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise FormGatewayError(422, "submission_invalid", "The submitted fields are invalid.")
    if "\r" in normalized or "\n" in normalized or "<" in normalized or ">" in normalized:
        raise FormGatewayError(422, "submission_invalid", "The submitted fields are invalid.")
    return normalized


def _csrf_token(
    component: WebsiteThemeComponentConfiguration,
    audit_identity: str | None,
) -> str:
    identity = (
        f"atlas-form-csrf-v1:{component.website_id}:{component.id}:"
        f"{component.integrity_fingerprint}:{audit_identity or ''}"
    ).encode("utf-8")
    return hmac.new(_CSRF_PROCESS_KEY, identity, hashlib.sha256).hexdigest()


def _missing_form_readiness(
    *,
    component_configuration_id: int | None = None,
    submission_state: str = "missing",
    initial: list[FormReadinessItemRead] | None = None,
) -> PerformanceLocalFormReadinessRead:
    blockers = list(initial or [])
    if not blockers:
        blockers.append(
            _blocker(
                "missing_form_component",
                "component_configuration_id",
                "No exact governed V3 form component is available.",
            )
        )
    return PerformanceLocalFormReadinessRead(
        status="blocked",
        can_submit=False,
        submission_state=submission_state,
        component_configuration_id=component_configuration_id,
        provider_state=FormProviderReadinessStateRead(
            provider_key=None,
            destination_configured=False,
            adapter_registered=False,
            test_only=False,
        ),
        privacy=FormPrivacyReadinessStateRead(
            destination_configured=False,
            consent_mode=None,
            consent_text_version=None,
            ready=False,
        ),
        retention=FormRetentionReadinessStateRead(
            duration_configured=False,
            deletion_behavior_configured=False,
            ready=False,
        ),
        spam=FormSpamReadinessStateRead(strategy=None, ready=False),
        behavior=FormBehaviorReadinessStateRead(
            success_configured=False,
            failure_configured=False,
            ready=False,
        ),
        security=FormSecurityReadinessStateRead(
            secret_reference_configured=False,
            same_origin_policy=None,
            csrf_policy=None,
            csrf_token=None,
            request_size_limit_bytes=None,
            idempotency_strategy=None,
            ready=False,
        ),
        audit_identity=None,
        blockers=blockers,
    )


def _blocker(code: str, field: str, reason: str) -> FormReadinessItemRead:
    return FormReadinessItemRead(code=code, field=field, reason=reason)


def _unavailable() -> FormGatewayError:
    return FormGatewayError(
        503,
        "form_submission_unavailable",
        "Form submission is not available.",
    )


def _normalized_origin(value: str) -> tuple[str, str, int | None] | None:
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, hostname.lower(), port


def _is_loopback_origin(value: str) -> bool:
    origin = _normalized_origin(value)
    return origin is not None and origin[1] in {"localhost", "127.0.0.1", "::1"}


def _is_loopback_http_policy_destination(value: str | None) -> bool:
    if value is None:
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
    except (TypeError, ValueError):
        return False


def _is_disposable_database(database_url: str) -> bool:
    lowered = database_url.strip().lower().replace("\\", "/")
    if lowered.startswith("sqlite:"):
        final_name = lowered.rsplit("/", 1)[-1]
        return is_explicit_disposable_database_name(final_name)
    database_name = lowered.rsplit("/", 1)[-1].split("?", 1)[0]
    return is_explicit_disposable_database_name(database_name)


def _session_uses_explicit_disposable_database(session: Session) -> bool:
    bind = session.get_bind()
    database_name = str(getattr(bind.url, "database", "") or "").lower()
    exact_sqlite_memory = (
        getattr(bind.dialect, "name", "") == "sqlite"
        and database_name in {"", ":memory:"}
        and str(bind.url) in {"sqlite://", "sqlite:///:memory:"}
    )
    return database_name != "atlas" and (
        exact_sqlite_memory
        or is_explicit_disposable_database_name(database_name)
    )


def is_explicit_disposable_database_name(database_name: str) -> bool:
    """Recognize an explicit disposable DB token, never an incidental substring."""

    normalized = database_name.strip().lower().replace("\\", "/")
    normalized = normalized.rsplit("/", 1)[-1].split("?", 1)[0]
    if normalized == ":memory:":
        return True
    if not normalized:
        return False
    segments = {item for item in re.split(r"[^a-z0-9]+", normalized) if item}
    return bool(
        segments
        & {"test", "tests", "testing", "pytest", "rehearsal", "clone", "disposable"}
    )
