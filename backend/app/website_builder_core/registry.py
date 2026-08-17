from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from app.website_builder_core.contracts import FormDeliveryMode


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_key: str
    provider_type: str
    supported_delivery_modes: frozenset[FormDeliveryMode]
    adapter_version: str
    installed: bool
    enabled: bool
    secret_reference_required: bool
    destination_required: bool
    health_status: str
    supported_form_contract_versions: frozenset[int]
    website_compatibility: frozenset[str] = frozenset({"*"})
    external_request_behavior: str = "none"
    retention_owner: str = "atlas"
    privacy_owner: str = "atlas"
    test_only: bool = False

    def supports(
        self,
        *,
        mode: FormDeliveryMode,
        form_contract_version: int,
        website_identity: str,
    ) -> bool:
        return bool(
            self.installed
            and self.enabled
            and self.health_status == "ready"
            and mode in self.supported_delivery_modes
            and form_contract_version in self.supported_form_contract_versions
            and (
                "*" in self.website_compatibility
                or website_identity in self.website_compatibility
            )
        )


@dataclass(frozen=True)
class ProviderRegistration:
    descriptor: ProviderDescriptor
    submission_adapter: object | None = None
    delivery_adapter: object | None = None
    presentation_adapter: object | None = None
    spam_controls: Mapping[str, object] = field(default_factory=dict)
    idempotency_boundaries: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "spam_controls", MappingProxyType(dict(self.spam_controls)))
        object.__setattr__(
            self,
            "idempotency_boundaries",
            MappingProxyType(dict(self.idempotency_boundaries)),
        )


class ProviderRegistry:
    """One sealed registry with physically separate production/test views."""

    def __init__(
        self,
        *,
        production: Mapping[str, ProviderRegistration] | None = None,
        test_only: Mapping[str, ProviderRegistration] | None = None,
    ) -> None:
        production_records = dict(production or {})
        test_records = dict(test_only or {})
        self._validate(production_records, require_test_only=False)
        self._validate(test_records, require_test_only=True)
        overlap = set(production_records).intersection(test_records)
        if overlap:
            raise ValueError("Provider keys cannot cross production and test registries")
        self.production = MappingProxyType(production_records)
        self.test_only = MappingProxyType(test_records)

    @staticmethod
    def _validate(
        records: Mapping[str, ProviderRegistration],
        *,
        require_test_only: bool,
    ) -> None:
        for key, registration in records.items():
            if key != registration.descriptor.provider_key:
                raise ValueError("Provider registry key does not match its descriptor")
            if registration.descriptor.test_only is not require_test_only:
                raise ValueError("Provider registry environment classification is invalid")

    def registrations(self, *, allow_test_only: bool = False) -> Mapping[str, ProviderRegistration]:
        return self.test_only if allow_test_only else self.production

    def registration(
        self,
        provider_key: str,
        *,
        allow_test_only: bool = False,
    ) -> ProviderRegistration | None:
        return self.registrations(allow_test_only=allow_test_only).get(provider_key)

    def submission_providers(self, *, allow_test_only: bool = False) -> Mapping[str, object]:
        return MappingProxyType(
            {
                key: record.submission_adapter
                for key, record in self.registrations(
                    allow_test_only=allow_test_only
                ).items()
                if record.submission_adapter is not None
            }
        )

    def spam_controls(self, *, allow_test_only: bool = False) -> Mapping[str, object]:
        result: dict[str, object] = {}
        for record in self.registrations(allow_test_only=allow_test_only).values():
            for strategy, adapter in record.spam_controls.items():
                if strategy in result and result[strategy] is not adapter:
                    raise ValueError("Spam-control strategy is registered more than once")
                result[strategy] = adapter
        return MappingProxyType(result)

    def idempotency_boundaries(
        self,
        *,
        allow_test_only: bool = False,
    ) -> Mapping[str, object]:
        result: dict[str, object] = {}
        for record in self.registrations(allow_test_only=allow_test_only).values():
            for strategy, boundary in record.idempotency_boundaries.items():
                if strategy in result and result[strategy] is not boundary:
                    raise ValueError("Idempotency strategy is registered more than once")
                result[strategy] = boundary
        return MappingProxyType(result)
