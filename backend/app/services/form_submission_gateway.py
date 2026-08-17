from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Request
from pydantic import ValidationError
from sqlmodel import Session

from app.core.config import get_settings
from app.models import WebsiteFormDeliveryModeRevision
from app.schemas.form_delivery import (
    FormDeliveryReadinessRead,
    NormalizedFormSubmissionInput,
)
from app.services.form_delivery_registry import (
    PRODUCTION_IDEMPOTENCY_BOUNDARIES,
    PRODUCTION_SPAM_CONTROLS,
    PRODUCTION_SUBMISSION_PROVIDERS,
    SYNTHETIC_PROVIDER_DESTINATION,
    SYNTHETIC_PROVIDER_KEY,
    test_only_idempotency_boundaries,
    test_only_spam_controls,
    test_only_submission_providers,
)
from app.website_builder_core.contracts import (
    FormRequestSecurityPolicy,
    NormalizedFormDefinition,
    NormalizedSubmissionEnvelope,
    ProviderDeliveryContext,
)


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


def _test_registry_access_allowed() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or disposable_rehearsal_environment_allowed()


class _ContainedTestRegistryView(Mapping[str, object]):
    def __init__(self, capability: str) -> None:
        self.capability = capability

    def _records(self) -> Mapping[str, object]:
        allowed = _test_registry_access_allowed()
        if self.capability == "submission":
            return test_only_submission_providers(allowed=allowed)
        if self.capability == "spam":
            return test_only_spam_controls(allowed=allowed)
        return test_only_idempotency_boundaries(allowed=allowed)

    def __getitem__(self, key: str) -> object:
        return self._records()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._records())

    def __len__(self) -> int:
        return len(self._records())


TEST_ONLY_SUBMISSION_PROVIDERS = _ContainedTestRegistryView("submission")
TEST_ONLY_SPAM_CONTROLS = _ContainedTestRegistryView("spam")
TEST_ONLY_IDEMPOTENCY_BOUNDARIES = _ContainedTestRegistryView("idempotency")


class _SyntheticDiscardProvider:
    def __new__(cls):
        if not _test_registry_access_allowed():
            raise _unavailable()
        from app.services.contained_form_delivery_adapters import SyntheticDiscardProvider

        return SyntheticDiscardProvider()


class _SyntheticNoopSpamControl:
    def __new__(cls):
        if not _test_registry_access_allowed():
            raise _unavailable()
        from app.services.contained_form_delivery_adapters import SyntheticNoopSpamControl

        return SyntheticNoopSpamControl()


class _SyntheticIdempotencyBoundary:
    """Backward-compatible lazy constructor for focused V3 gateway tests."""

    def __new__(cls):
        if not _test_registry_access_allowed():
            raise _unavailable()
        from app.services.contained_form_delivery_adapters import (
            SyntheticIdempotencyBoundary,
        )

        return SyntheticIdempotencyBoundary(_CSRF_PROCESS_KEY)


@dataclass(frozen=True)
class FormGatewayPreflight:
    website_public_url: str
    component_configuration_id: int
    component_integrity_fingerprint: str
    delivery_mode_revision: WebsiteFormDeliveryModeRevision
    readiness: FormDeliveryReadinessRead
    definition: NormalizedFormDefinition
    security: FormRequestSecurityPolicy
    csrf_token: str
    runtime_scope: Literal["public", "contained_test"]


def evaluate_form_readiness(
    component: object | None,
    *,
    mode: str,
    test_environment_allowed: bool | None = None,
) -> object:
    """Compatibility adapter; Theme/V3 evaluation lives outside this gateway."""

    from app.services.form_submission_contracts import (
        evaluate_performance_local_form_readiness,
    )

    return evaluate_performance_local_form_readiness(
        component,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        test_environment_allowed=test_environment_allowed,
    )


def preflight_form_gateway(
    session: Session,
    website_id: int,
    component_configuration_id: int,
) -> FormGatewayPreflight:
    from app.services.form_submission_contracts import (
        resolve_universal_form_gateway_scope,
    )

    scope = resolve_universal_form_gateway_scope(
        session,
        website_id,
        component_configuration_id,
    )
    if scope is None:
        raise _unavailable()

    # Website-scoped delivery is selected before Theme-family or provider
    # details. The component key/version establish only the shared normalized
    # five-field contract; they do not choose a delivery mode.
    from app.services.form_delivery_modes import (
        FormDeliveryConfigurationError,
        form_delivery_readiness,
        resolve_current_form_delivery_mode,
    )

    try:
        explicit_mode = resolve_current_form_delivery_mode(
            session,
            scope.website_id,
            scope.component_configuration_id,
        )
    except FormDeliveryConfigurationError as exc:
        if exc.code != "form_delivery_mode_not_found":
            raise _unavailable() from None
        raise FormGatewayError(
            503,
            "form_delivery_mode_not_found",
            "Form submission is not available.",
        ) from None
    else:
        explicit_readiness = form_delivery_readiness(
            session,
            explicit_mode,
            allow_test_only=bool(
                disposable_rehearsal_environment_allowed()
                and _session_uses_explicit_disposable_database(session)
            ),
            secure_payload_store_available=False,
        )
        if explicit_mode.mode == "disabled":
            raise FormGatewayError(
                404,
                "form_submission_disabled",
                "Form submission is disabled.",
            )
        if explicit_mode.mode == "provider_owned":
            raise FormGatewayError(
                404,
                "atlas_gateway_not_used",
                "This form does not submit through Atlas.",
            )
        if not explicit_readiness.can_submit:
            raise FormGatewayError(
                503,
                "form_delivery_mode_unavailable",
                "Form submission is not available.",
            )
        # Managed payload encryption is intentionally unavailable in this
        # milestone, so no explicit Atlas-owned mode can reach the legacy
        # synchronous provider path even if future readiness code changes.
        raise FormGatewayError(
            503,
            "form_delivery_mode_unavailable",
            "Form submission is not available.",
        )

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


def _require_origin(request: Request, preflight: object) -> None:
    observed_values = request.headers.getlist("origin")
    observed = observed_values[0] if len(observed_values) == 1 else None
    contained_test = getattr(preflight, "runtime_scope", None) == "contained_test"
    if contained_test:
        expected = str(get_settings().frontend_origin)
    else:
        expected = getattr(preflight, "website_public_url", None)
        if expected is None:
            # Compatibility for isolated legacy parser tests only. Production
            # preflight uses the provider-neutral scalar projection.
            website = getattr(preflight, "website", None)
            expected = getattr(website, "public_url", None)
    observed_origin = _normalized_origin(observed) if observed is not None else None
    expected_origin = _normalized_origin(expected) if isinstance(expected, str) else None
    if (
        observed_origin is None
        or expected_origin is None
        or observed_origin != expected_origin
    ):
        raise FormGatewayError(403, "origin_rejected", "The request origin is not allowed.")
    if contained_test:
        require_loopback_request(request)


def _require_csrf(request: Request, preflight: FormGatewayPreflight) -> None:
    supplied_values = request.headers.getlist("x-atlas-csrf-token")
    supplied = supplied_values[0] if len(supplied_values) == 1 else ""
    expected = preflight.csrf_token
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
    contract: object,
) -> NormalizedFormSubmissionInput:
    try:
        parsed = NormalizedFormSubmissionInput.model_validate(body)
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
        minimum_length = getattr(field, "minimum_length", None)
        if minimum_length is None:
            minimum_length = field.validation_contract.minimum_length
        if cleaned is not None and (
            len(cleaned) < minimum_length or len(cleaned) > field.maximum_length
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
    return NormalizedFormSubmissionInput.model_validate(normalized)


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


def _csrf_token(component: object, audit_identity: str | None) -> str:
    website_id = getattr(component, "website_id")
    component_id = getattr(
        component,
        "component_configuration_id",
        getattr(component, "id", None),
    )
    if component_id is None:
        raise ValueError("The form component lacks a stable configuration identity.")
    integrity_fingerprint = getattr(component, "integrity_fingerprint")
    identity = (
        f"atlas-form-csrf-v1:{website_id}:{component_id}:"
        f"{integrity_fingerprint}:{audit_identity or ''}"
    ).encode("utf-8")
    return hmac.new(_CSRF_PROCESS_KEY, identity, hashlib.sha256).hexdigest()


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
