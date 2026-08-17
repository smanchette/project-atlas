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
    DEFAULT_CUSTOMER_ENTRY_FIELD_COUNT,
    FORM_DELIVERY_MODES,
    MAXIMUM_CUSTOMER_ENTRY_FIELD_COUNT,
    RESERVED_OPTIONAL_FIELD_KEYS,
    STANDARD_CUSTOMER_ENTRY_FIELD_LABELS,
    SYSTEM_FORM_CONTROL_KEYS,
    UNIVERSAL_ESTIMATE_FORM_DEFINITION,
    NormalizedOptionalFieldValue,
    NormalizedSubmissionEnvelope,
    OptionalFormFieldChoice,
    OptionalFormFieldDefinition,
    OptionalFormFieldValidationContract,
    SubmissionProvider,
    normalize_optional_field_value,
    validate_submission_optional_field_binding,
)
from app.website_builder_core.contracts import FormDeliveryPresentation
from app.website_builder_core.readiness import (
    FormDeliveryReadinessInput,
    evaluate_form_delivery_readiness,
)


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


def _optional_definition(
    **overrides: object,
) -> OptionalFormFieldDefinition:
    values: dict[str, object] = {
        "field_key": "project_type",
        "public_label": "Project type",
        "accessibility_label": "Select the project type",
        "field_type": "dropdown",
        "required": False,
        "display_order": 6,
        "maximum_length": None,
        "validation_contract": OptionalFormFieldValidationContract(
            rule="listed_choice"
        ),
        "choices": (
            OptionalFormFieldChoice("repair", "Repair"),
            OptionalFormFieldChoice("replacement", "Replacement"),
        ),
        "provider_mapping_key": "project_type",
        "help_text": "Choose one synthetic project type.",
        "definition_revision_identity": "project_type_revision_1",
    }
    values.update(overrides)
    return OptionalFormFieldDefinition(**values)  # type: ignore[arg-type]


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
    assert STANDARD_CUSTOMER_ENTRY_FIELD_LABELS == (
        "Name",
        "Phone",
        "ZIP code",
        "Requested Service",
        "Optional Message",
    )
    assert DEFAULT_CUSTOMER_ENTRY_FIELD_COUNT == 5
    assert MAXIMUM_CUSTOMER_ENTRY_FIELD_COUNT == 6
    assert definition.customer_entry_field_count == 5
    assert definition.optional_fields == ()
    assert {
        "consent",
        "privacy",
        "honeypot",
        "captcha",
        "idempotency",
        "request_id",
    }.issubset(SYSTEM_FORM_CONTROL_KEYS)
    with pytest.raises(FrozenInstanceError):
        definition.contract_version = 4  # type: ignore[misc]


def test_one_optional_sixth_field_is_valid_but_two_and_seven_are_rejected() -> None:
    sixth = _optional_definition()
    definition = UNIVERSAL_ESTIMATE_FORM_DEFINITION.with_optional_fields((sixth,))
    assert definition.customer_entry_field_count == 6
    assert definition.optional_fields == (sixth,)
    assert len(sixth.choices) == 2  # A choice group is one customer-entry field.

    with pytest.raises(ValueError, match="at most one"):
        UNIVERSAL_ESTIMATE_FORM_DEFINITION.with_optional_fields(
            (sixth, _optional_definition(field_key="property_type"))
        )


@pytest.mark.parametrize("field_key", sorted(RESERVED_OPTIONAL_FIELD_KEYS))
def test_optional_field_rejects_every_reserved_key_after_normalization(
    field_key: str,
) -> None:
    disguised = field_key.replace("_", " - ").upper()
    with pytest.raises(ValueError, match="reserved"):
        _optional_definition(field_key=disguised)


def test_optional_field_rejects_blank_labels_and_invalid_choice_contracts() -> None:
    with pytest.raises(ValueError, match="public label"):
        _optional_definition(public_label="   ")
    with pytest.raises(ValueError, match="require bounded choices"):
        _optional_definition(choices=())
    with pytest.raises(ValueError, match="Choices apply only"):
        _optional_definition(
            field_type="short_text",
            maximum_length=80,
            validation_contract=OptionalFormFieldValidationContract(
                rule="trimmed_text",
                minimum_length=0,
            ),
        )
    with pytest.raises(ValueError, match="validation rule"):
        _optional_definition(
            field_type="radio",
            validation_contract=OptionalFormFieldValidationContract(rule="boolean"),
        )
    with pytest.raises(ValueError, match="type is not supported"):
        _optional_definition(field_type="file_upload")


@pytest.mark.parametrize(
    ("property_name", "forbidden_value"),
    (
        ("field_key", "social_security_number"),
        ("provider_mapping_key", "raw_provider_payload"),
        ("public_label", "Upload a file"),
        ("accessibility_label", "Enter payment card information"),
        ("help_text", "Provide a bank account or routing number"),
        ("field_key", "smtp_password"),
        ("provider_mapping_key", "api_credential"),
        ("public_label", "Medical information"),
    ),
)
def test_optional_field_rejects_sensitive_or_raw_payload_purposes(
    property_name: str,
    forbidden_value: str,
) -> None:
    with pytest.raises(ValueError, match="forbidden sensitive or payload"):
        _optional_definition(**{property_name: forbidden_value})


def test_optional_choice_cannot_hide_a_sensitive_customer_question() -> None:
    with pytest.raises(ValueError, match="forbidden sensitive or payload"):
        _optional_definition(
            choices=(
                OptionalFormFieldChoice("repair", "Repair"),
                OptionalFormFieldChoice("medical_information", "Medical information"),
            )
        )


@pytest.mark.parametrize(
    ("field_type", "raw_value", "normalized_value", "maximum_length", "rule", "choices"),
    (
        ("email", " Person@Example.TEST ", "Person@example.test", 254, "email_address", ()),
        ("short_text", " Synthetic text ", "Synthetic text", 80, "trimmed_text", ()),
        (
            "dropdown",
            " Replacement ",
            "replacement",
            None,
            "listed_choice",
            (
                OptionalFormFieldChoice("repair", "Repair"),
                OptionalFormFieldChoice("replacement", "Replacement"),
            ),
        ),
        (
            "radio",
            "Repair",
            "repair",
            None,
            "listed_choice",
            (
                OptionalFormFieldChoice("repair", "Repair"),
                OptionalFormFieldChoice("replacement", "Replacement"),
            ),
        ),
        ("checkbox", False, False, None, "boolean", ()),
        ("date", "2026-08-17", "2026-08-17", None, "iso_date", ()),
        ("textarea", "Line one\nLine two", "Line one\nLine two", 500, "trimmed_text", ()),
    ),
)
def test_optional_field_value_normalization_matches_every_controlled_type(
    field_type: str,
    raw_value: object,
    normalized_value: object,
    maximum_length: int | None,
    rule: str,
    choices: tuple[OptionalFormFieldChoice, ...],
) -> None:
    minimum_length = 0 if maximum_length is not None else None
    definition = _optional_definition(
        field_type=field_type,
        maximum_length=maximum_length,
        validation_contract=OptionalFormFieldValidationContract(
            rule=rule,  # type: ignore[arg-type]
            minimum_length=minimum_length,
        ),
        choices=choices,
    )
    normalized = normalize_optional_field_value(definition, raw_value)
    assert normalized is not None
    assert normalized.value == normalized_value
    assert normalized.provider_mapping_key == "project_type"


def test_optional_and_required_sixth_values_and_internal_binding_fail_closed() -> None:
    optional = _optional_definition()
    definition = UNIVERSAL_ESTIMATE_FORM_DEFINITION.with_optional_fields((optional,))
    assert normalize_optional_field_value(optional, None) is None
    validate_submission_optional_field_binding(
        definition,
        None,
        optional.definition_revision_identity,
    )

    required = _optional_definition(required=True)
    required_definition = UNIVERSAL_ESTIMATE_FORM_DEFINITION.with_optional_fields(
        (required,)
    )
    with pytest.raises(ValueError, match="required"):
        validate_submission_optional_field_binding(
            required_definition,
            None,
            required.definition_revision_identity,
        )

    valid = normalize_optional_field_value(required, "repair")
    assert valid is not None
    validate_submission_optional_field_binding(
        required_definition,
        valid,
        required.definition_revision_identity,
    )
    for forged in (
        NormalizedOptionalFieldValue(
            field_key=valid.field_key,
            definition_revision_identity="forged_revision",
            provider_mapping_key=valid.provider_mapping_key,
            value=valid.value,
        ),
        NormalizedOptionalFieldValue(
            field_key=valid.field_key,
            definition_revision_identity=valid.definition_revision_identity,
            provider_mapping_key="forged_mapping",
            value=valid.value,
        ),
        NormalizedOptionalFieldValue(
            field_key=valid.field_key,
            definition_revision_identity=valid.definition_revision_identity,
            provider_mapping_key=valid.provider_mapping_key,
            value="unknown_choice",
        ),
    ):
        with pytest.raises(ValueError, match="exact governed definition|configured"):
            validate_submission_optional_field_binding(
                required_definition,
                forged,
                required.definition_revision_identity,
            )

    with pytest.raises(ValueError, match="exact optional field definition revision"):
        validate_submission_optional_field_binding(
            required_definition,
            valid,
            "forged_revision",
        )

    with pytest.raises(ValueError, match="no governed definition"):
        validate_submission_optional_field_binding(
            UNIVERSAL_ESTIMATE_FORM_DEFINITION,
            valid,
            valid.definition_revision_identity,
        )

    bounded_text = _optional_definition(
        field_type="short_text",
        maximum_length=5,
        validation_contract=OptionalFormFieldValidationContract(
            rule="trimmed_text",
            minimum_length=0,
        ),
        choices=(),
    )
    bounded_definition = UNIVERSAL_ESTIMATE_FORM_DEFINITION.with_optional_fields(
        (bounded_text,)
    )
    with pytest.raises(ValueError, match="configured length"):
        validate_submission_optional_field_binding(
            bounded_definition,
            NormalizedOptionalFieldValue(
                field_key=bounded_text.field_key,
                definition_revision_identity=(
                    bounded_text.definition_revision_identity
                ),
                provider_mapping_key=bounded_text.provider_mapping_key,
                value="sixsix",
            ),
            bounded_text.definition_revision_identity,
        )


def test_atlas_rendered_readiness_defaults_field_contract_to_fail_closed() -> None:
    common = {
        "lifecycle_status": "active",
        "enabled": True,
        "scope_valid": True,
        "fingerprint_valid": True,
        "website_enabled": True,
        "component_enabled": True,
        "approval_identity": "synthetic_approval",
        "activation_identity": "synthetic_activation",
        "provider_key": "synthetic_provider",
        "adapter_version": "test-v1",
        "destination_identity": "destination-ref://synthetic/forms",
        "privacy_policy_reference": "policy-ref://synthetic/privacy",
        "consent_required": False,
        "consent_policy_reference": None,
        "retention_policy_reference": "policy-ref://synthetic/retention",
        "abuse_policy_reference": "policy-ref://synthetic/abuse",
        "success_behavior": "Show a success state.",
        "failure_behavior": "Show a failure state.",
        "idempotency_policy_reference": "policy-ref://synthetic/idempotency",
        "audit_identity": "synthetic_audit",
    }
    atlas = evaluate_form_delivery_readiness(
        FormDeliveryReadinessInput(mode="atlas_email", **common),  # type: ignore[arg-type]
        None,
    )
    assert "invalid_customer_entry_field_contract" in {
        blocker.code for blocker in atlas.blockers
    }

    provider_owned = evaluate_form_delivery_readiness(
        FormDeliveryReadinessInput(
            mode="provider_owned",
            provider_owned_presentation_ready=False,
            **common,  # type: ignore[arg-type]
        ),
        None,
    )
    assert "invalid_customer_entry_field_contract" not in {
        blocker.code for blocker in provider_owned.blockers
    }


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
