from __future__ import annotations

from functools import lru_cache
import secrets
from types import MappingProxyType
from typing import Mapping, cast

from app.services.form_delivery_test_guard import test_or_disposable_runtime_allowed
from app.website_builder_core.registry import (
    ProviderDescriptor,
    ProviderRegistration,
    ProviderRegistry,
)


SYNTHETIC_PROVIDER_KEY = "atlas-synthetic-memory"
SYNTHETIC_PROVIDER_DESTINATION = "memory://discard"
SYNTHETIC_EMAIL_PROVIDER_KEY = "atlas-synthetic-email"
SYNTHETIC_PROVIDER_OWNED_KEY = "atlas-synthetic-provider-owned"
SYNTHETIC_ATLASOPS360_KEY = "atlasops360-synthetic"
SYNTHETIC_EXTERNAL_ADAPTER_KEY = "atlas-synthetic-external"


PRODUCTION_PROVIDER_REGISTRY = ProviderRegistry(production={}, test_only={})


def test_transport_environment_allowed() -> bool:
    """Return true only inside pytest or an explicit disposable rehearsal runtime."""

    return test_or_disposable_runtime_allowed()


def _test_descriptor(
    provider_key: str,
    provider_type: str,
    modes: frozenset[str],
    *,
    secret_required: bool,
    external_request_behavior: str,
    retention_owner: str = "atlas",
    privacy_owner: str = "atlas",
) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_key=provider_key,
        provider_type=provider_type,
        supported_delivery_modes=cast(frozenset, modes),
        adapter_version="test-v1",
        installed=True,
        enabled=True,
        secret_reference_required=secret_required,
        destination_required=True,
        health_status="ready",
        supported_form_contract_versions=frozenset({1, 3}),
        website_compatibility=frozenset({"*"}),
        external_request_behavior=external_request_behavior,
        retention_owner=retention_owner,
        privacy_owner=privacy_owner,
        test_only=True,
    )


@lru_cache(maxsize=1)
def _contained_test_registry() -> ProviderRegistry:
    """Import and construct synthetic adapters only after an explicit guard."""

    if not test_transport_environment_allowed():
        raise RuntimeError(
            "Synthetic form-delivery adapters are unavailable in this runtime."
        )

    from app.services.contained_form_delivery_adapters import (
        SyntheticDeliveryAdapter,
        SyntheticDiscardProvider,
        SyntheticIdempotencyBoundary,
        SyntheticNoopSpamControl,
        SyntheticProviderOwnedPresentationAdapter,
    )

    legacy_provider = SyntheticDiscardProvider()
    legacy_spam = SyntheticNoopSpamControl()
    legacy_idempotency = SyntheticIdempotencyBoundary(secrets.token_bytes(32))
    return ProviderRegistry(
        production={},
        test_only={
            SYNTHETIC_PROVIDER_KEY: ProviderRegistration(
                descriptor=_test_descriptor(
                    SYNTHETIC_PROVIDER_KEY,
                    "synthetic_discard",
                    frozenset({"atlas_email"}),
                    secret_required=True,
                    external_request_behavior="none",
                ),
                submission_adapter=legacy_provider,
                delivery_adapter=SyntheticDeliveryAdapter(SYNTHETIC_PROVIDER_KEY),
                spam_controls={"synthetic_test": legacy_spam},
                idempotency_boundaries={"required_header": legacy_idempotency},
            ),
            SYNTHETIC_EMAIL_PROVIDER_KEY: ProviderRegistration(
                descriptor=_test_descriptor(
                    SYNTHETIC_EMAIL_PROVIDER_KEY,
                    "atlas_email_transport",
                    frozenset({"atlas_email"}),
                    secret_required=True,
                    external_request_behavior="synthetic_none",
                ),
                delivery_adapter=SyntheticDeliveryAdapter(SYNTHETIC_EMAIL_PROVIDER_KEY),
            ),
            SYNTHETIC_PROVIDER_OWNED_KEY: ProviderRegistration(
                descriptor=_test_descriptor(
                    SYNTHETIC_PROVIDER_OWNED_KEY,
                    "external_provider",
                    frozenset({"provider_owned"}),
                    secret_required=False,
                    external_request_behavior="browser_to_provider",
                    retention_owner="external_provider",
                    privacy_owner="external_provider",
                ),
                presentation_adapter=SyntheticProviderOwnedPresentationAdapter(),
            ),
            SYNTHETIC_ATLASOPS360_KEY: ProviderRegistration(
                descriptor=_test_descriptor(
                    SYNTHETIC_ATLASOPS360_KEY,
                    "atlasops360",
                    frozenset({"atlasops360_native"}),
                    secret_required=False,
                    external_request_behavior="synthetic_none",
                    retention_owner="atlasops360",
                    privacy_owner="atlasops360",
                ),
                delivery_adapter=SyntheticDeliveryAdapter(SYNTHETIC_ATLASOPS360_KEY),
            ),
            SYNTHETIC_EXTERNAL_ADAPTER_KEY: ProviderRegistration(
                descriptor=_test_descriptor(
                    SYNTHETIC_EXTERNAL_ADAPTER_KEY,
                    "external_adapter",
                    frozenset({"external_adapter"}),
                    secret_required=True,
                    external_request_behavior="synthetic_none",
                    retention_owner="external_adapter",
                    privacy_owner="atlas",
                ),
                delivery_adapter=SyntheticDeliveryAdapter(
                    SYNTHETIC_EXTERNAL_ADAPTER_KEY
                ),
            ),
        },
    )


class FormDeliveryProviderRegistry:
    """One facade; test registrations require an explicit contained call."""

    production = PRODUCTION_PROVIDER_REGISTRY.production

    def registration(
        self,
        provider_key: str,
        *,
        allow_test_only: bool = False,
    ) -> ProviderRegistration | None:
        if not allow_test_only:
            return PRODUCTION_PROVIDER_REGISTRY.registration(provider_key)
        if not test_transport_environment_allowed():
            return None
        return _contained_test_registry().registration(
            provider_key,
            allow_test_only=True,
        )


FORM_DELIVERY_PROVIDER_REGISTRY = FormDeliveryProviderRegistry()

PRODUCTION_SUBMISSION_PROVIDERS: Mapping[str, object] = (
    PRODUCTION_PROVIDER_REGISTRY.submission_providers()
)
PRODUCTION_SPAM_CONTROLS: Mapping[str, object] = (
    PRODUCTION_PROVIDER_REGISTRY.spam_controls()
)
PRODUCTION_IDEMPOTENCY_BOUNDARIES: Mapping[str, object] = (
    PRODUCTION_PROVIDER_REGISTRY.idempotency_boundaries()
)


def test_only_submission_providers(*, allowed: bool) -> Mapping[str, object]:
    if not allowed or not test_transport_environment_allowed():
        return MappingProxyType({})
    return _contained_test_registry().submission_providers(allow_test_only=True)


def test_only_spam_controls(*, allowed: bool) -> Mapping[str, object]:
    if not allowed or not test_transport_environment_allowed():
        return MappingProxyType({})
    return _contained_test_registry().spam_controls(allow_test_only=True)


def test_only_idempotency_boundaries(*, allowed: bool) -> Mapping[str, object]:
    if not allowed or not test_transport_environment_allowed():
        return MappingProxyType({})
    return _contained_test_registry().idempotency_boundaries(allow_test_only=True)
