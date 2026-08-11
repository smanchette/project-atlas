from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import (
    GeneratedPage,
    ImageMetadata,
    PageImageAssignment,
    PlannedPageMediaRequirement,
    Website,
)
from app.services import page_composition, page_export
from app.services.media_display_presets import effective_assignment_display_preset
from app.services.page_composition import PageCompositionError


NOW = datetime(2026, 8, 11, 15, 0, tzinfo=UTC)


def _requirement(*, aspect_ratio: str = "16:9") -> SimpleNamespace:
    return SimpleNamespace(
        id=257,
        contract_version=2,
        version=1,
        aspect_ratio=aspect_ratio,
        purpose="Explain the approved service process.",
        customer_outcome="Understand what to expect.",
        placement_key="city-service-process",
        component_or_section="service_summary",
        target_component_instance_key="service_summary:why_it_matters",
        intended_subject="Approved process media.",
        accessibility_intent="informative",
        requirement_state="advisory",
    )


def _assignment(*, display_preset: str | None = "hero_desktop") -> SimpleNamespace:
    return SimpleNamespace(
        id=501,
        generated_page_id=41,
        image_metadata_id=701,
        media_requirement_id=257,
        image_role="city-service-process:assignment-1",
        display_preset=display_preset,
        status="active",
        updated_at=NOW,
        override_alt_text=None,
        override_focal_x=None,
        override_focal_y=None,
        sort_order=0,
    )


def _image() -> SimpleNamespace:
    return SimpleNamespace(
        id=701,
        updated_at=NOW,
        optimized_url="/media/optimized/process.webp",
        asset_url="/media/originals/process.webp",
        thumbnail_url="/media/thumbnails/process.webp",
        reviewed_alt_text="Representative drywood termite tenting process.",
        alt_text=None,
        image_title="Drywood tenting process",
        caption=None,
        media_key="drywood-process",
        media_version=1,
        provenance_type="generated",
        rights_status="licensed",
        focal_x=0.5,
        focal_y=0.5,
        review_status="reviewed",
    )


class _CompositionSession:
    def __init__(self, requirement, assignment, image):
        self.requirement = requirement
        self.assignment = assignment
        self.image = image

    def get(self, model, identity):
        if model is PageImageAssignment and identity == self.assignment.id:
            return self.assignment
        if model is ImageMetadata and identity == self.image.id:
            return self.image
        if model is PlannedPageMediaRequirement and identity == self.requirement.id:
            return self.requirement
        if model is Website and identity == 1:
            return SimpleNamespace(id=1)
        return None


def _component_item(*, assigned: bool = True) -> dict:
    bindings = {
        "media_requirement_id": 257,
        "target_component_key": "service_summary",
        "target_component_instance_key": "service_summary:why_it_matters",
        "target_region": "main",
        "placement_contract_version": 2,
    }
    if assigned:
        bindings["page_image_assignment_id"] = 501
    return {
        "instance_key": "media_placement:requirement-257",
        "component_key": "media_placement",
        "contract_version": 1,
        "region": "main",
        "position": 5,
        "variant": "approved_media" if assigned else "placeholder",
        "input_bindings": bindings,
    }


@pytest.fixture
def _composition_dependencies(monkeypatch):
    monkeypatch.setattr(
        page_composition,
        "build_website_context",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        page_composition,
        "resolve_semantic_media_role",
        lambda *_args, **_kwargs: "service",
    )
    monkeypatch.setattr(
        page_composition,
        "is_image_metadata_excluded",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        page_composition,
        "current_scoped_media_authorization",
        lambda *_args, **_kwargs: None,
    )


def test_current_v2_preset_survives_composition_serialization_and_stays_separate_from_role(
    _composition_dependencies,
):
    requirement = _requirement()
    assignment = _assignment()
    image = _image()
    session = _CompositionSession(requirement, assignment, image)

    resolved = page_composition._resolve_instance(
        session,
        SimpleNamespace(website_id=1, site_plan_id=1),
        SimpleNamespace(id=41, draft_content={}, page_type="city_service"),
        _component_item(),
    )

    assert resolved.resolved_data["image_role"] == "service"
    assert resolved.resolved_data["stored_display_preset"] == "hero_desktop"
    assert resolved.resolved_data["effective_display_preset"] == "hero_desktop"
    assert resolved.resolved_data["display_preset"] == "hero_desktop"
    serialized = resolved.model_dump(mode="json")
    assert serialized["resolved_data"]["stored_display_preset"] == "hero_desktop"
    assert serialized["resolved_data"]["effective_display_preset"] == "hero_desktop"


def test_current_v2_placeholder_exposes_contract_preset_without_claiming_stored_value(
    _composition_dependencies,
):
    requirement = _requirement()
    session = _CompositionSession(requirement, _assignment(), _image())

    resolved = page_composition._resolve_instance(
        session,
        SimpleNamespace(website_id=1, site_plan_id=1),
        SimpleNamespace(id=41, draft_content={}, page_type="city_service"),
        _component_item(assigned=False),
    )

    assert resolved.resolved_data["stored_display_preset"] is None
    assert resolved.resolved_data["effective_display_preset"] == "hero_desktop"
    assert "asset_url" not in resolved.resolved_data


def test_unknown_current_v2_preset_contract_fails_closed_in_composition(
    _composition_dependencies,
):
    requirement = _requirement(aspect_ratio="3:2")
    session = _CompositionSession(requirement, _assignment(), _image())

    with pytest.raises(PageCompositionError, match="unsupported aspect-ratio"):
        page_composition._resolve_instance(
            session,
            SimpleNamespace(website_id=1, site_plan_id=1),
            SimpleNamespace(id=41, draft_content={}, page_type="city_service"),
            _component_item(),
        )


def test_legacy_source_identity_remains_byte_shape_compatible():
    assignment = _assignment()
    assignment.media_requirement_id = None
    assignment.image_role = "hero"

    identity = page_composition._media_assignment_source_identity(
        SimpleNamespace(),
        assignment,
        _image(),
    )

    assert identity == {
        "id": 501,
        "image_metadata_id": 701,
        "role": "hero",
        "status": "active",
        "updated_at": NOW.isoformat(),
        "image_updated_at": NOW.isoformat(),
    }


@pytest.mark.parametrize("semantic_role", ("hero", "service", "support", None))
def test_historical_assignment_without_stored_preset_uses_safe_role_independent_fallback(
    semantic_role,
):
    assert (
        effective_assignment_display_preset(
            SimpleNamespace(display_preset=None),
            requirement=None,
            semantic_role=semantic_role,
        )
        == "original"
    )


def test_governed_source_identity_binds_stored_and_effective_presets(
    _composition_dependencies,
):
    requirement = _requirement()
    assignment = _assignment()
    identity = page_composition._media_assignment_source_identity(
        _CompositionSession(requirement, assignment, _image()),
        assignment,
        _image(),
    )

    assert identity["role"] == "service"
    assert identity["storage_role_token"] == "city-service-process:assignment-1"
    assert identity["stored_display_preset"] == "hero_desktop"
    assert identity["effective_display_preset"] == "hero_desktop"


class _ExportSession:
    def __init__(self, assignment, requirement, image):
        self.assignment = assignment
        self.requirement = requirement
        self.image = image
        self.page = SimpleNamespace(id=41, website_id=1)
        self.website = SimpleNamespace(id=1)

    def exec(self, _statement):
        return SimpleNamespace(all=lambda: [self.assignment])

    def get(self, model, identity):
        if model is GeneratedPage and identity == 41:
            return self.page
        if model is Website and identity == 1:
            return self.website
        if model is PlannedPageMediaRequirement and identity == self.requirement.id:
            return self.requirement
        if model is ImageMetadata and identity == self.image.id:
            return self.image
        return None


def _empty_governed_export_identity() -> dict:
    return {
        "media_requirement_id": 257,
        "media_requirement_version": 1,
        "placement_key": "city-service-process",
        "target_component_key": "service_summary",
        "target_component_instance_key": "service_summary:why_it_matters",
        "placement_contract_version": 2,
        "scoped_authorization_id": None,
        "scoped_authorization_version": None,
        "scoped_authorization_fingerprint": None,
        "scoped_authorization_terms": [],
        "scoped_reuse_policy": None,
    }


def test_export_uses_the_same_effective_preset_as_composition(monkeypatch):
    assignment = _assignment()
    requirement = _requirement()
    image = _image()
    session = _ExportSession(assignment, requirement, image)
    monkeypatch.setattr(
        page_export,
        "_governed_media_export_identity",
        lambda *_args, **_kwargs: _empty_governed_export_identity(),
    )
    monkeypatch.setattr(
        page_export,
        "resolve_semantic_media_role",
        lambda *_args, **_kwargs: "service",
    )
    monkeypatch.setattr(
        page_export,
        "is_image_metadata_excluded",
        lambda *_args, **_kwargs: False,
    )

    reference = page_export._media_references(session, 41)[0]

    assert reference.image_role == "service"
    assert reference.stored_display_preset == "hero_desktop"
    assert reference.effective_display_preset == "hero_desktop"
    assert reference.display_preset == "hero_desktop"


def test_export_rejects_stored_preset_that_disagrees_with_current_v2_contract(
    monkeypatch,
):
    assignment = _assignment(display_preset="card_thumbnail")
    requirement = _requirement()
    session = _ExportSession(assignment, requirement, _image())
    monkeypatch.setattr(
        page_export,
        "_governed_media_export_identity",
        lambda *_args, **_kwargs: _empty_governed_export_identity(),
    )
    monkeypatch.setattr(
        page_export,
        "resolve_semantic_media_role",
        lambda *_args, **_kwargs: "service",
    )

    with pytest.raises(HTTPException, match="does not match the exact current V2") as exc:
        page_export._media_references(session, 41)

    assert exc.value.status_code == 409
