from __future__ import annotations

from threading import Lock
from typing import Protocol, runtime_checkable
from uuid import uuid4

from app.services.form_delivery_test_guard import test_or_disposable_runtime_allowed
from app.website_builder_core.contracts import NormalizedSubmissionEnvelope


class FormPayloadStoreError(RuntimeError):
    pass


@runtime_checkable
class SecureFormPayloadStore(Protocol):
    available: bool
    encryption_key_reference: str | None

    def put(self, envelope: NormalizedSubmissionEnvelope) -> str: ...

    def get(self, reference: str) -> NormalizedSubmissionEnvelope: ...

    def delete(self, reference: str) -> None: ...


class UnavailableProductionPayloadStore:
    """Fail-closed production placeholder until managed encryption exists."""

    available = False
    encryption_key_reference = None

    def put(self, envelope: NormalizedSubmissionEnvelope) -> str:
        raise FormPayloadStoreError(
            "Secure form payload storage and key management are unavailable."
        )

    def get(self, reference: str) -> NormalizedSubmissionEnvelope:
        raise FormPayloadStoreError(
            "Secure form payload storage and key management are unavailable."
        )

    def delete(self, reference: str) -> None:
        return None


class InMemoryTestPayloadStore:
    """Explicit test-only process memory; never a production encryption claim."""

    available = True
    test_only = True
    encryption_key_reference = "secret-ref://synthetic/form-payload-key"

    def __init__(self, *, test_environment_allowed: bool) -> None:
        if not test_environment_allowed or not test_or_disposable_runtime_allowed():
            raise FormPayloadStoreError(
                "The in-memory payload store is restricted to tests or disposable rehearsal."
            )
        self._lock = Lock()
        self._payloads: dict[str, NormalizedSubmissionEnvelope] = {}

    def put(self, envelope: NormalizedSubmissionEnvelope) -> str:
        reference = f"memory://form-payload/{uuid4()}"
        with self._lock:
            self._payloads[reference] = envelope
        return reference

    def get(self, reference: str) -> NormalizedSubmissionEnvelope:
        with self._lock:
            try:
                return self._payloads[reference]
            except KeyError as exc:
                raise FormPayloadStoreError(
                    "The test payload reference is unavailable."
                ) from exc

    def delete(self, reference: str) -> None:
        with self._lock:
            self._payloads.pop(reference, None)

    def clear(self) -> None:
        with self._lock:
            self._payloads.clear()

    @property
    def payload_count(self) -> int:
        with self._lock:
            return len(self._payloads)
