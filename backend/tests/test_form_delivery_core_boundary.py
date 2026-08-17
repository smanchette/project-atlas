from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.schemas.form_delivery import (
    ProviderOwnedModeConfiguration,
    validate_mode_configuration,
)
from app.services import form_submission_contracts
from app.website_builder_core.contracts import (
    FORM_DELIVERY_MODES,
    UNIVERSAL_ESTIMATE_FORM_DEFINITION,
    NormalizedSubmissionEnvelope,
    SubmissionProvider,
)
from app.website_builder_core.contracts import FormDeliveryPresentation


BACKEND = Path(__file__).parents[1]
CORE = BACKEND / "app" / "website_builder_core"


def test_website_builder_core_has_no_persistence_or_provider_dependency() -> None:
    forbidden_modules = {
        "alembic",
        "fastapi",
        "sqlalchemy",
        "sqlmodel",
        "app.models",
        "app.db",
        "app.services",
        "atlasops360",
        "gorilladesk",
    }
    observed: list[tuple[str, str]] = []
    for path in CORE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                if any(
                    module == forbidden or module.startswith(f"{forbidden}.")
                    for forbidden in forbidden_modules
                ):
                    observed.append((path.name, module))
        lowered = path.read_text(encoding="utf-8").lower()
        assert "gorilladesk" not in lowered
        assert "atlasops360://" not in lowered
    assert observed == []
    assert "atlasops360_native" in FORM_DELIVERY_MODES
    assert all(
        not name.startswith("atlasops360")
        for name in sys.modules
    )


def test_legacy_submission_contract_names_alias_the_single_core_contract() -> None:
    assert (
        form_submission_contracts.NormalizedFormSubmissionEnvelope
        is NormalizedSubmissionEnvelope
    )
    assert form_submission_contracts.FormSubmissionProvider is SubmissionProvider


def test_shared_form_definition_is_immutable_provider_neutral_and_five_field() -> None:
    definition = UNIVERSAL_ESTIMATE_FORM_DEFINITION
    assert (definition.component_key, definition.contract_version) == (
        "compact_estimate_form",
        3,
    )
    assert tuple(field.field_key for field in definition.fields) == (
        "name",
        "phone",
        "postal-code",
        "requested-service",
        "message",
    )
    assert tuple(field.envelope_field for field in definition.fields) == (
        "name",
        "phone",
        "postal_code",
        "requested_service",
        "message",
    )
    assert tuple(field.required for field in definition.fields) == (
        True,
        True,
        True,
        True,
        False,
    )
    with pytest.raises(FrozenInstanceError):
        definition.contract_version = 4  # type: ignore[misc]


def test_production_registry_import_does_not_load_test_adapters() -> None:
    code = """
import json
import sys
from app.services import form_delivery_registry as registry
from app.services import form_submission_gateway as gateway
from app.services.form_payload_store import (
    FormPayloadStoreError,
    InMemoryTestPayloadStore,
)
guarded_registration = registry.FORM_DELIVERY_PROVIDER_REGISTRY.registration(
    registry.SYNTHETIC_EMAIL_PROVIDER_KEY,
    allow_test_only=True,
)
try:
    InMemoryTestPayloadStore(test_environment_allowed=True)
except FormPayloadStoreError:
    payload_store_constructed = False
else:
    payload_store_constructed = True
try:
    __import__('app.services.contained_form_delivery_adapters')
except RuntimeError:
    direct_test_import_blocked = True
else:
    direct_test_import_blocked = False
print(json.dumps({
    'test_module_loaded': 'app.services.contained_form_delivery_adapters' in sys.modules,
    'guarded_registration': guarded_registration is not None,
    'payload_store_constructed': payload_store_constructed,
    'direct_test_import_blocked': direct_test_import_blocked,
    'production': list(registry.PRODUCTION_PROVIDER_REGISTRY.production),
    'submission': list(registry.PRODUCTION_SUBMISSION_PROVIDERS),
    'gateway_submission': list(gateway.PRODUCTION_SUBMISSION_PROVIDERS),
    'gateway_test_submission': list(gateway.TEST_ONLY_SUBMISSION_PROVIDERS),
}))
"""
    environment = dict(os.environ)
    environment.pop("PYTEST_CURRENT_TEST", None)
    environment["ATLAS_RUNTIME_MODE"] = "active_local"
    environment["DATABASE_URL"] = "sqlite:///atlas.db"
    environment["FRONTEND_ORIGIN"] = "http://localhost:5173"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == {
        "test_module_loaded": False,
        "guarded_registration": False,
        "payload_store_constructed": False,
        "direct_test_import_blocked": True,
        "production": [],
        "submission": [],
        "gateway_submission": [],
        "gateway_test_submission": [],
    }
    environment["PYTEST_CURRENT_TEST"] = "spoofed-production-marker"
    environment["DATABASE_URL"] = (
        "postgresql+psycopg://atlas:synthetic@localhost:5432/atlas"
    )
    spoofed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(spoofed.stdout) == {
        "test_module_loaded": False,
        "guarded_registration": False,
        "payload_store_constructed": False,
        "direct_test_import_blocked": True,
        "production": [],
        "submission": [],
        "gateway_submission": [],
        "gateway_test_submission": [],
    }


def test_cached_test_adapter_module_cannot_construct_after_runtime_changes() -> None:
    code = """
import json
import os
from app.core.config import get_settings
from app.services import contained_form_delivery_adapters as adapters
os.environ['ATLAS_RUNTIME_MODE'] = 'active_local'
os.environ['DATABASE_URL'] = 'sqlite:///atlas.db'
os.environ['FRONTEND_ORIGIN'] = 'http://localhost:5173'
os.environ.pop('PYTEST_CURRENT_TEST', None)
get_settings.cache_clear()
constructors = (
    lambda: adapters.SyntheticDiscardProvider(),
    lambda: adapters.SyntheticNoopSpamControl(),
    lambda: adapters.SyntheticIdempotencyBoundary(b'x' * 32),
    lambda: adapters.SyntheticDeliveryAdapter(adapters.SYNTHETIC_EMAIL_PROVIDER_KEY),
    lambda: adapters.SyntheticProviderOwnedPresentationAdapter(),
)
blocked = []
for constructor in constructors:
    try:
        constructor()
    except RuntimeError:
        blocked.append(True)
    else:
        blocked.append(False)
print(json.dumps(blocked))
"""
    environment = dict(os.environ)
    environment["PYTEST_CURRENT_TEST"] = "contained-constructor-test"
    environment["ATLAS_RUNTIME_MODE"] = "automated_test"
    environment["DATABASE_URL"] = "sqlite:///constructor-test.sqlite3"
    environment["FRONTEND_ORIGIN"] = "http://localhost:5173"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == [True] * 5


def test_provider_owned_adapter_embed_is_portable_without_raw_markup() -> None:
    configuration = ProviderOwnedModeConfiguration.model_validate(
        {
            "presentation_strategy": "adapter_embed",
            "approved_https_destination": "https://forms.example.test/estimate",
            "approved_origin": "https://forms.example.test",
            "accessibility_title": "Request an estimate",
            "ownership_disclosure": "This form is operated by Synthetic Provider.",
            "destination_verified_by": "test-operator",
            "destination_verified_at": "2026-08-17T12:00:00Z",
        }
    )
    presentation = FormDeliveryPresentation(
        kind=configuration.presentation_strategy,
        destination=configuration.approved_https_destination,
        title=configuration.accessibility_title,
        ownership_disclosure=configuration.ownership_disclosure,
        approved_origin=configuration.approved_origin,
    )
    assert presentation.kind == "adapter_embed"
    assert not hasattr(presentation, "html")
    assert not hasattr(presentation, "script")

    for forbidden in (
        {**configuration.model_dump(mode="json"), "html": "<form></form>"},
        {
            **configuration.model_dump(mode="json"),
            "script": "window.location='https://example.test'",
        },
        {
            **configuration.model_dump(mode="json"),
            "ownership_disclosure": "<script>alert(1)</script>",
        },
    ):
        with pytest.raises((ValidationError, ValueError)):
            validate_mode_configuration("provider_owned", forbidden)


def test_provider_owned_origin_is_exact_and_never_wildcard() -> None:
    base = {
        "presentation_strategy": "hosted_route",
        "approved_https_destination": "https://forms.example.test/estimate",
        "approved_origin": "https://forms.example.test",
        "accessibility_title": "Request an estimate",
        "ownership_disclosure": "Synthetic provider owns this form.",
        "destination_verified_by": "test-operator",
        "destination_verified_at": "2026-08-17T12:00:00Z",
    }
    ProviderOwnedModeConfiguration.model_validate(base)
    with pytest.raises(ValidationError):
        ProviderOwnedModeConfiguration.model_validate(
            {**base, "approved_origin": "https://*.example.test"}
        )
