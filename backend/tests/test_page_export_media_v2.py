from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import PlannedPage, PlannedPageMediaRequirement
from app.schemas.page_export import ExportMediaReference
from app.services import page_export


class _SessionStub:
    def __init__(self, requirement, planned_page):
        self.requirement = requirement
        self.planned_page = planned_page

    def get(self, model, identity):
        if model is PlannedPageMediaRequirement and identity == self.requirement.id:
            return self.requirement
        if model is PlannedPage and identity == self.planned_page.id:
            return self.planned_page
        return None


def _records(*, contract_version: int = 2, target: str | None = "content_section:intro"):
    page = SimpleNamespace(id=41, business_id=1, website_id=1)
    planned = SimpleNamespace(
        id=79,
        website_id=1,
        site_plan_id=1,
        generated_page_id=41,
    )
    requirement = SimpleNamespace(
        id=201,
        website_id=1,
        business_id=1,
        site_plan_id=1,
        planned_page_id=79,
        placement_key="home-evidence",
        component_or_section="content_section",
        target_component_instance_key=target,
        contract_version=contract_version,
        version=2,
        requirement_state="advisory",
        lifecycle_status="active",
    )
    assignment = SimpleNamespace(
        generated_page_id=41,
        website_id=1,
        planned_page_id=79,
        media_requirement_id=201,
        placement_contract_version=contract_version,
    )
    return page, planned, requirement, assignment


def _composition(*, target: str = "content_section:intro", binding_target: str | None = None):
    binding_target = target if binding_target is None else binding_target
    return SimpleNamespace(
        effective_components=[
            SimpleNamespace(
                instance_key=target,
                component_key="content_section",
                input_bindings={"section_key": "intro"},
            ),
            SimpleNamespace(
                instance_key="media_placement:requirement-201",
                component_key="media_placement",
                input_bindings={
                    "media_requirement_id": 201,
                    "target_component_key": "content_section",
                    "target_component_instance_key": binding_target,
                    "placement_contract_version": 2,
                },
            ),
        ]
    )


def test_v2_export_projects_persisted_exact_media_target(monkeypatch):
    page, planned, requirement, assignment = _records()
    monkeypatch.setattr(
        page_export,
        "read_composition_for_generated_page",
        lambda *_args: _composition(),
    )

    result = page_export._governed_media_export_identity(
        _SessionStub(requirement, planned),
        page,
        assignment,
    )

    assert result == {
        "media_requirement_id": 201,
        "media_requirement_version": 2,
        "placement_key": "home-evidence",
        "target_component_key": "content_section",
        "target_component_instance_key": "content_section:intro",
        "placement_contract_version": 2,
    }


@pytest.mark.parametrize(
    ("target", "composition", "message"),
    [
        (None, _composition(), "missing its exact component-instance selector"),
        (
            "content_section:missing",
            _composition(),
            "does not resolve exactly once",
        ),
        (
            "content_section:intro",
            _composition(binding_target="content_section:other"),
            "does not match the durable exact target",
        ),
    ],
)
def test_v2_export_fails_closed_for_missing_or_invalid_exact_target(
    monkeypatch,
    target,
    composition,
    message,
):
    page, planned, requirement, assignment = _records(target=target)
    monkeypatch.setattr(
        page_export,
        "read_composition_for_generated_page",
        lambda *_args: composition,
    )

    with pytest.raises(HTTPException, match=message) as exc:
        page_export._governed_media_export_identity(
            _SessionStub(requirement, planned),
            page,
            assignment,
        )

    assert exc.value.status_code == 409


def test_governed_v1_export_preserves_legacy_target_semantics(monkeypatch):
    page, planned, requirement, assignment = _records(
        contract_version=1,
        target=None,
    )
    monkeypatch.setattr(
        page_export,
        "read_composition_for_generated_page",
        lambda *_args: pytest.fail("V1 export must not require a V2 exact target"),
    )

    result = page_export._governed_media_export_identity(
        _SessionStub(requirement, planned),
        page,
        assignment,
    )

    assert result["media_requirement_id"] == 201
    assert result["placement_key"] == "home-evidence"
    assert result["target_component_key"] == "content_section"
    assert result["target_component_instance_key"] is None
    assert result["placement_contract_version"] == 1


@pytest.mark.parametrize("binding_version", (None, 1))
def test_v2_export_rejects_missing_or_mismatched_binding_contract_version(
    monkeypatch,
    binding_version,
):
    page, planned, requirement, assignment = _records()
    composition = _composition()
    placement = composition.effective_components[1]
    if binding_version is None:
        placement.input_bindings.pop("placement_contract_version")
    else:
        placement.input_bindings["placement_contract_version"] = binding_version
    monkeypatch.setattr(
        page_export,
        "read_composition_for_generated_page",
        lambda *_args: composition,
    )

    with pytest.raises(HTTPException, match="placement contract version") as exc:
        page_export._governed_media_export_identity(
            _SessionStub(requirement, planned),
            page,
            assignment,
        )

    assert exc.value.status_code == 409


def test_ungoverned_export_reference_retains_null_governed_identity():
    reference = ExportMediaReference(
        image_id=31,
        image_role="hero",
        sort_order=0,
        alt_text="Approved legacy media",
        display_preset="hero_desktop",
        focal_x=0.5,
        focal_y=0.5,
        review_status="reviewed",
    )

    assert reference.media_requirement_id is None
    assert reference.media_requirement_version is None
    assert reference.placement_key is None
    assert reference.target_component_key is None
    assert reference.target_component_instance_key is None
    assert reference.placement_contract_version is None
