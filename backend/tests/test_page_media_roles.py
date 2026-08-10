from __future__ import annotations

import pytest

from app.services.page_media_planning import (
    PAGE_TYPE_MEDIA_CONTRACTS,
)
from app.services.page_media_roles import (
    SEMANTIC_MEDIA_ROLE_CONTRACTS,
    SemanticMediaRoleError,
    resolve_semantic_media_role,
)


def _governed_binding(
    *,
    page_type: str,
    placement_key: str,
    component: str,
    target: str,
    storage_role_token: str,
    assignment_version: int = 1,
    contract_version: int = 2,
    lifecycle_status: str = "active",
):
    page = {
        "id": 30,
        "website_id": 10,
        "site_plan_id": 20,
        "generated_page_id": 40,
        "page_type": page_type,
    }
    requirement = {
        "id": 50,
        "website_id": 10,
        "site_plan_id": 20,
        "planned_page_id": 30,
        "placement_key": placement_key,
        "contract_version": contract_version,
        "component_or_section": component,
        "target_component_instance_key": target,
        "lifecycle_status": lifecycle_status,
        "requirement_state": "required",
    }
    assignment = {
        "generated_page_id": 40,
        "website_id": 10,
        "site_plan_id": 20,
        "planned_page_id": 30,
        "media_requirement_id": 50,
        "assignment_version": assignment_version,
        "media_version": 1,
        "placement_contract_version": contract_version,
        "image_role": storage_role_token,
    }
    return assignment, requirement, page


def test_semantic_role_registry_exactly_matches_current_page_media_contracts() -> None:
    current_contracts = {
        (
            page_type,
            contract["placement_key"],
            contract["contract_version"],
            contract["component_or_section"],
            contract["target_component_instance_key"],
        )
        for page_type, contracts in PAGE_TYPE_MEDIA_CONTRACTS.items()
        for contract in contracts
    }

    assert set(SEMANTIC_MEDIA_ROLE_CONTRACTS) == current_contracts


def test_city_service_hero_resolves_from_exact_contract_not_storage_token() -> None:
    assignment, requirement, page = _governed_binding(
        page_type="city_service",
        placement_key="city-service-hero",
        component="hero",
        target="hero",
        storage_role_token="support",
    )

    assert (
        resolve_semantic_media_role(
            assignment,
            requirement=requirement,
            planned_page=page,
        )
        == "hero"
    )


def test_city_service_evidence_never_acquires_hero_semantics_from_storage() -> None:
    assignment, requirement, page = _governed_binding(
        page_type="city_service",
        placement_key="city-service-evidence",
        component="content_section",
        target="content_section:signs_section",
        storage_role_token="hero",
    )

    assert resolve_semantic_media_role(
        assignment,
        requirement=requirement,
        planned_page=page,
    ) == "support"


def test_city_service_process_never_acquires_hero_semantics_from_storage() -> None:
    assignment, requirement, page = _governed_binding(
        page_type="city_service",
        placement_key="city-service-process",
        component="service_summary",
        target="service_summary:why_it_matters",
        storage_role_token="hero",
    )

    assert resolve_semantic_media_role(
        assignment,
        requirement=requirement,
        planned_page=page,
    ) == "service"


def test_hero_like_filename_or_rationale_cannot_create_hero_semantics() -> None:
    assignment, requirement, page = _governed_binding(
        page_type="city_service",
        placement_key="city-service-evidence",
        component="content_section",
        target="content_section:signs_section",
        storage_role_token="support",
    )
    assignment["file_name"] = "definitely-a-hero.webp"
    assignment["assignment_rationale"] = "Use this as the hero image."

    assert resolve_semantic_media_role(
        assignment,
        requirement=requirement,
        planned_page=page,
    ) == "support"


def test_fabricated_hero_like_requirement_fails_closed() -> None:
    assignment, requirement, page = _governed_binding(
        page_type="city_service",
        placement_key="fabricated-hero",
        component="hero",
        target="hero",
        storage_role_token="hero",
    )

    with pytest.raises(SemanticMediaRoleError, match="exact current"):
        resolve_semantic_media_role(
            assignment,
            requirement=requirement,
            planned_page=page,
        )


def test_versioned_storage_tokens_preserve_replacement_history_semantics() -> None:
    first, requirement, page = _governed_binding(
        page_type="city_service",
        placement_key="city-service-hero",
        component="hero",
        target="hero",
        storage_role_token="city-service-hero:assignment-1",
    )
    replacement = {
        **first,
        "assignment_version": 2,
        "image_role": "city-service-hero:assignment-2",
    }

    assert first["image_role"] != replacement["image_role"]
    assert resolve_semantic_media_role(
        first,
        requirement=requirement,
        planned_page=page,
    ) == resolve_semantic_media_role(
        replacement,
        requirement=requirement,
        planned_page=page,
    ) == "hero"


def test_legacy_literal_hero_remains_readable() -> None:
    assignment = {
        "image_role": "hero",
        "website_id": None,
        "site_plan_id": None,
        "planned_page_id": None,
        "media_requirement_id": None,
        "assignment_version": None,
        "media_version": None,
        "placement_contract_version": None,
    }

    assert resolve_semantic_media_role(assignment) == "hero"


def test_historical_v1_governed_role_is_audit_readable_but_not_current() -> None:
    assignment, requirement, page = _governed_binding(
        page_type="home",
        placement_key="home-hero",
        component="hero",
        target="",
        storage_role_token="home-hero:assignment-1",
        contract_version=1,
        lifecycle_status="superseded",
    )

    with pytest.raises(SemanticMediaRoleError, match="active required or advisory"):
        resolve_semantic_media_role(
            assignment,
            requirement=requirement,
            planned_page=page,
        )
    assert resolve_semantic_media_role(
        assignment,
        requirement=requirement,
        planned_page=page,
        allow_historical=True,
    ) == "hero"
