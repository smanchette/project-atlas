from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.backup import (
    BACKUP_VERSION,
    BackupValidationError,
    export_backup,
    load_backup,
    restore_backup,
)
from app.models import (
    Business,
    GeneratedPage,
    ImageMetadata,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    SitePlan,
    Website,
    WebsiteMediaPlanningRecord,
)


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_payload(tmp_path: Path, payload: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _scope(
    session: Session,
    *,
    company: str,
    domain: str,
    with_page: bool = True,
) -> tuple[Business, Website, SitePlan | None, GeneratedPage | None, PlannedPage | None]:
    business = Business(
        company_name=company,
        business_type="Local service company",
        state="FL",
    )
    session.add(business)
    session.flush()
    website = Website(
        business_id=business.id,
        website_name=f"{company} Website",
        domain=domain,
        public_url=f"https://{domain}",
        status="active",
    )
    session.add(website)
    session.flush()
    if not with_page:
        session.commit()
        return business, website, None, None, None
    generated = GeneratedPage(
        business_id=business.id,
        website_id=website.id,
        page_type="home",
        page_title="Home",
        page_slug="home",
        draft_content={"title": "Home", "h1": "Home"},
        generation_status="generated",
    )
    session.add(generated)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name="Primary Site Plan",
        status="active",
        version=1,
    )
    session.add(plan)
    session.flush()
    page = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="home",
        working_name="Home",
        intended_slug="home",
        planning_status="planned",
        generated_page_id=generated.id,
    )
    session.add(page)
    session.flush()
    return business, website, plan, generated, page


def _planning_snapshot(plan: SitePlan, page: PlannedPage) -> dict:
    return {
        "website_id": plan.website_id,
        "site_plan_id": plan.id,
        "site_plan_version": plan.version,
        "algorithm_version": "page-media-planning-v1",
        "placement_contract_version": 1,
        "component_contract_versions": {},
        "planned_pages": [
            {
                "id": page.id,
                "page_type": page.page_type,
                "contract_page_type": "home",
                "service_id": None,
                "city_id": None,
                "county_id": None,
                "generated_page_id": page.generated_page_id,
                "updated_at": page.updated_at.isoformat(),
                "planning_record_updated_at": None,
            }
        ],
    }


def _suggestion(
    business: Business,
    website: Website,
    plan: SitePlan,
    page: PlannedPage,
) -> dict:
    return {
        "suggestion_key": "home:v1:hero",
        "website_id": website.id,
        "business_id": business.id,
        "site_plan_id": plan.id,
        "planned_page_id": page.id,
        "page_type": "home",
        "contract_page_type": "home",
        "placement_key": "hero",
        "component_or_section": "hero",
        "requirement_state": "required",
        "purpose": "Introduce the approved business.",
        "customer_outcome": "Understand the business and request service.",
        "intended_subject": "Approved company service context.",
        "orientation": "landscape",
        "aspect_ratio": "16:9",
        "minimum_width": 1200,
        "minimum_height": 675,
        "crop_intent": "Preserve the meaningful subject.",
        "focal_point_intent": "Retain the approved focal subject.",
        "responsive_behavior": "Use approved responsive derivatives.",
        "accessibility_intent": "informative",
        "caption_intent": None,
        "approved_source_constraints": ["approved company media"],
        "permitted_reuse_policy": "Reuse only for the same approved purpose.",
        "replacement_policy": "Replacement requires operator approval.",
        "compatible_page_types": ["home"],
        "contract_version": 1,
    }


def _seed_governed_graph(
    session: Session,
) -> dict[str, int]:
    business, website, plan, generated, page = _scope(
        session,
        company="Media Planning Business",
        domain="media-planning.example.test",
    )
    assert plan and generated and page
    _, other_website, _, _, _ = _scope(
        session,
        company="Other Media Business",
        domain="other-media.example.test",
        with_page=False,
    )
    snapshot = _planning_snapshot(plan, page)
    suggestion = _suggestion(business, website, plan, page)
    planning_v1 = WebsiteMediaPlanningRecord(
        website_id=website.id,
        business_id=business.id,
        site_plan_id=plan.id,
        version=1,
        algorithm_version="page-media-planning-v1",
        generated_media_suggestions=[suggestion],
        source_snapshot=snapshot,
        source_hash=_hash(snapshot),
        generated_at=datetime(2026, 8, 7, 6, 0, tzinfo=UTC),
    )
    session.add(planning_v1)
    session.flush()
    snapshot_v2 = {
        **snapshot,
        "algorithm_version": "page-media-planning-v2",
        "placement_contract_version": 2,
        "placement_contract_manifest_hash": "a" * 64,
    }
    suggestion_v2 = {
        **suggestion,
        "suggestion_key": "home:v2:hero:exact-target",
        "target_component_instance_key": "hero",
        "contract_version": 2,
    }
    planning_v2 = WebsiteMediaPlanningRecord(
        website_id=website.id,
        business_id=business.id,
        site_plan_id=plan.id,
        version=2,
        algorithm_version="page-media-planning-v2",
        generated_media_suggestions=[suggestion_v2],
        source_snapshot=snapshot_v2,
        source_hash=_hash(snapshot_v2),
        generated_at=datetime(2026, 8, 7, 6, 5, tzinfo=UTC),
        replaces_record_id=planning_v1.id,
    )
    session.add(planning_v2)
    session.flush()

    requirement_values = {
        "website_id": website.id,
        "business_id": business.id,
        "site_plan_id": plan.id,
        "planned_page_id": page.id,
        "component_or_section": "hero",
        "placement_key": "hero",
        "requirement_state": "required",
        "purpose": "Introduce the approved business.",
        "customer_outcome": "Understand the business and request service.",
        "intended_subject": "Approved company service context.",
        "orientation": "landscape",
        "aspect_ratio": "16:9",
        "minimum_width": 1200,
        "minimum_height": 675,
        "crop_intent": "Preserve the meaningful subject.",
        "focal_point_intent": "Retain the operator-reviewed focal subject.",
        "responsive_behavior": "Use approved responsive derivatives.",
        "accessibility_intent": "informative",
        "caption_intent": None,
        "approved_source_constraints": ["approved company media"],
        "permitted_reuse_policy": "Reuse only for the same approved purpose.",
        "replacement_policy": "Replacement requires operator approval.",
        "compatible_page_types": ["home"],
        "decided_by": "Media Operator",
        "rationale": "Approve the governed Home hero placement.",
        "decided_at": datetime(2026, 8, 7, 6, 10, tzinfo=UTC),
    }
    requirement_v1 = PlannedPageMediaRequirement(
        **requirement_values,
        planning_record_id=planning_v1.id,
        contract_version=1,
        source_suggestion_key="home:v1:hero",
        version=1,
        lifecycle_status="superseded",
    )
    session.add(requirement_v1)
    session.flush()
    requirement_v2 = PlannedPageMediaRequirement(
        **requirement_values,
        planning_record_id=planning_v2.id,
        contract_version=2,
        target_component_instance_key="hero",
        source_suggestion_key="home:v2:hero:exact-target",
        version=2,
        lifecycle_status="active",
        replaces_requirement_id=requirement_v1.id,
    )
    session.add(requirement_v2)
    session.flush()

    base_image = {
        "business_id": business.id,
        "website_id": website.id,
        "media_key": "home-hero",
        "image_title": "Approved Home hero",
        "alt_text": "Approved company service context",
        "reviewed_alt_text": "Approved company service context",
        "mime_type": "image/png",
        "file_size": 4096,
        "width": 1600,
        "height": 900,
        "acquisition_source": "company_photograph",
        "creator_source_identity": "Company photographer",
        "created_by": "Media Operator",
        "provenance_type": "company_original",
        "provenance_notes": "Company supplied original photograph.",
        "rights_status": "owned",
        "rights_holder": "Media Planning Business",
        "rights_notes": "Company ownership confirmed.",
        "approved_usage": ["hero", "page_media"],
        "prohibited_usage": ["favicon"],
        "permitted_placement_keys": ["hero"],
        "accessibility_intent": "informative",
        "approval_version": 1,
        "approved_by": "Media Operator",
        "approved_at": datetime(2026, 8, 7, 6, 15, tzinfo=UTC),
        "gps_metadata_status": "absent",
        "gps_metadata": {},
        "review_status": "reviewed",
    }
    image_v1 = ImageMetadata(
        **base_image,
        media_version=1,
        file_name="home-hero-v1.png",
        original_filename="home-hero-v1.png",
        stored_filename="home-hero-v1.png",
        managed_storage_path="originals/home-hero-v1.png",
        asset_url="http://testserver/media/optimized/home-hero-v1-optimized.webp",
        optimized_url="http://testserver/media/optimized/home-hero-v1-optimized.webp",
        thumbnail_url="http://testserver/media/thumbnails/home-hero-v1-thumbnail.webp",
        checksum_sha256="1" * 64,
        governance_status="retired",
        retired_by="Media Operator",
        retirement_rationale="Replaced with an improved approved original.",
        retired_at=datetime(2026, 8, 7, 6, 20, tzinfo=UTC),
    )
    session.add(image_v1)
    session.flush()
    image_v2 = ImageMetadata(
        **base_image,
        media_version=2,
        file_name="home-hero-v2.png",
        original_filename="home-hero-v2.png",
        stored_filename="home-hero-v2.png",
        managed_storage_path="originals/home-hero-v2.png",
        asset_url="http://testserver/media/optimized/home-hero-v2-optimized.webp",
        optimized_url="http://testserver/media/optimized/home-hero-v2-optimized.webp",
        thumbnail_url="http://testserver/media/thumbnails/home-hero-v2-thumbnail.webp",
        checksum_sha256="2" * 64,
        governance_status="approved",
        replaces_image_metadata_id=image_v1.id,
    )
    session.add(image_v2)
    session.flush()

    assignment_v1 = PageImageAssignment(
        generated_page_id=generated.id,
        image_metadata_id=image_v1.id,
        website_id=website.id,
        site_plan_id=plan.id,
        planned_page_id=page.id,
        media_requirement_id=requirement_v2.id,
        assignment_version=1,
        media_version=1,
        placement_contract_version=2,
        image_role="hero",
        display_preset="hero_desktop",
        status="replaced",
        assigned_by="Media Operator",
        assignment_rationale="Assign the approved Home hero.",
        assigned_at=datetime(2026, 8, 7, 6, 21, tzinfo=UTC),
        replaced_by="Media Operator",
        replacement_rationale="Use the approved second media version.",
        replaced_at=datetime(2026, 8, 7, 6, 25, tzinfo=UTC),
    )
    session.add(assignment_v1)
    session.flush()
    assignment_v2 = PageImageAssignment(
        generated_page_id=generated.id,
        image_metadata_id=image_v2.id,
        website_id=website.id,
        site_plan_id=plan.id,
        planned_page_id=page.id,
        media_requirement_id=requirement_v2.id,
        assignment_version=2,
        media_version=2,
        placement_contract_version=2,
        image_role="hero",
        display_preset="hero_desktop",
        status="active",
        assigned_by="Media Operator",
        assignment_rationale="Assign the approved replacement Home hero.",
        assigned_at=datetime(2026, 8, 7, 6, 26, tzinfo=UTC),
        replaces_page_image_assignment_id=assignment_v1.id,
    )
    session.add(assignment_v2)
    session.flush()
    media_snapshot = {
        "planning_record": {
            "planning_record_id": planning_v2.id,
            "algorithm_version": "page-media-v1",
        },
        "requirements": [
            {
                "id": requirement_v2.id,
                "placement_key": requirement_v2.placement_key,
                "version": requirement_v2.version,
                "contract_version": requirement_v2.contract_version,
                "component_or_section": requirement_v2.component_or_section,
                "target_component_instance_key": (
                    requirement_v2.target_component_instance_key
                ),
                "component_contract_version": 1,
                "requirement_state": requirement_v2.requirement_state,
                "planning_record_id": planning_v2.id,
                "lifecycle_status": requirement_v2.lifecycle_status,
            }
        ],
        "assignments": [
            {
                "requirement_id": requirement_v2.id,
                "requirement_version": requirement_v2.version,
                "placement_contract_version": requirement_v2.contract_version,
                "target_component_instance_key": (
                    requirement_v2.target_component_instance_key
                ),
                "assignment_id": assignment_v2.id,
                "assignment_version": assignment_v2.assignment_version,
                "asset_id": image_v2.id,
                "media_version": image_v2.media_version,
                "checksum_sha256": image_v2.checksum_sha256,
                "governance_status": image_v2.governance_status,
            }
        ],
    }
    composition_snapshot = {"page_media": media_snapshot}
    composition = PageComposition(
        website_id=website.id,
        site_plan_id=plan.id,
        planned_page_id=page.id,
        generated_page_id=generated.id,
        composition_version=1,
        generated_components=[
            {
                "instance_key": "hero",
                "component_key": "hero",
                "contract_version": 1,
                "region": "main",
                "position": 0,
                "variant": "default",
                "input_bindings": {"generated_page_id": generated.id},
                "provenance": "atlas_generated",
            },
            {
                "instance_key": "media_placement:requirement-2",
                "component_key": "media_placement",
                "contract_version": 1,
                "region": "main",
                "position": 1,
                "variant": "approved_media",
                "input_bindings": {
                    "media_requirement_id": requirement_v2.id,
                    "page_image_assignment_id": assignment_v2.id,
                    "target_component_key": "hero",
                    "target_component_instance_key": "hero",
                    "placement_contract_version": 2,
                    "target_region": "main",
                },
                "provenance": "atlas_generated",
            }
        ],
        operator_decisions=[],
        source_snapshot=composition_snapshot,
        source_hash=_hash(composition_snapshot),
        status="stale",
    )
    session.add(composition)
    session.commit()
    return {
        "business_id": business.id,
        "website_id": website.id,
        "other_website_id": other_website.id,
        "site_plan_id": plan.id,
        "planned_page_id": page.id,
        "generated_page_id": generated.id,
    }


def test_backup_054_round_trip_remaps_complete_page_media_graph_and_is_idempotent(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        source_ids = _seed_governed_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)

    loaded = load_backup(Path(exported["path"]))
    assert BACKUP_VERSION == "0.54"
    assert loaded["metadata"]["version"] == "0.54"
    assert loaded["metadata"]["table_counts"]["website_media_planning_records"] == 2
    assert loaded["metadata"]["table_counts"]["planned_page_media_requirements"] == 2

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        _scope(
            session,
            company="Existing Target Business",
            domain="existing-target.example.test",
        )
        session.commit()
        result = restore_backup(session, exported["path"])
        assert result["status"] == "restored"
        website = session.exec(
            select(Website).where(Website.domain == "media-planning.example.test")
        ).one()
        plan = session.exec(
            select(SitePlan).where(SitePlan.website_id == website.id)
        ).one()
        page = session.exec(
            select(PlannedPage).where(PlannedPage.site_plan_id == plan.id)
        ).one()
        assert website.id != source_ids["website_id"]
        planning = list(
            session.exec(
                select(WebsiteMediaPlanningRecord)
                .where(WebsiteMediaPlanningRecord.site_plan_id == plan.id)
                .order_by(WebsiteMediaPlanningRecord.version)
            ).all()
        )
        assert len(planning) == 2
        assert planning[1].replaces_record_id == planning[0].id
        assert planning[1].generated_media_suggestions[0]["website_id"] == website.id
        assert planning[1].generated_media_suggestions[0]["site_plan_id"] == plan.id
        assert planning[1].generated_media_suggestions[0]["planned_page_id"] == page.id
        assert planning[1].source_snapshot["website_id"] == website.id
        assert planning[1].source_snapshot["planned_pages"][0]["id"] == page.id
        assert planning[1].source_hash == _hash(planning[1].source_snapshot)

        requirements = list(
            session.exec(
                select(PlannedPageMediaRequirement)
                .where(PlannedPageMediaRequirement.planned_page_id == page.id)
                .order_by(PlannedPageMediaRequirement.version)
            ).all()
        )
        assert len(requirements) == 2
        assert requirements[1].replaces_requirement_id == requirements[0].id
        assert requirements[0].planning_record_id == planning[0].id
        assert requirements[1].planning_record_id == planning[1].id

        images = list(
            session.exec(
                select(ImageMetadata)
                .where(ImageMetadata.website_id == website.id)
                .order_by(ImageMetadata.media_version)
            ).all()
        )
        assert len(images) == 2
        assert images[1].replaces_image_metadata_id == images[0].id
        assert images[1].business_id == website.business_id

        assignments = list(
            session.exec(
                select(PageImageAssignment)
                .where(PageImageAssignment.website_id == website.id)
                .order_by(PageImageAssignment.assignment_version)
            ).all()
        )
        assert len(assignments) == 2
        assert assignments[1].replaces_page_image_assignment_id == assignments[0].id
        assert assignments[1].site_plan_id == plan.id
        assert assignments[1].planned_page_id == page.id
        assert assignments[1].media_requirement_id == requirements[1].id
        assert assignments[1].image_metadata_id == images[1].id

        composition = session.exec(
            select(PageComposition).where(
                PageComposition.planned_page_id == page.id
            )
        ).one()
        media_component = next(
            item
            for item in composition.generated_components
            if item["component_key"] == "media_placement"
        )
        bindings = media_component["input_bindings"]
        assert composition.status == "stale"
        assert bindings["media_requirement_id"] == requirements[1].id
        assert bindings["page_image_assignment_id"] == assignments[1].id
        assert requirements[0].contract_version == 1
        assert requirements[0].target_component_instance_key is None
        assert requirements[1].contract_version == 2
        assert requirements[1].target_component_instance_key == "hero"
        assert bindings["target_component_instance_key"] == "hero"
        assert bindings["placement_contract_version"] == 2
        page_media = composition.source_snapshot["page_media"]
        assert page_media["planning_record"]["planning_record_id"] == planning[1].id
        assert page_media["requirements"][0]["id"] == requirements[1].id
        assert page_media["requirements"][0]["planning_record_id"] == planning[1].id
        assert page_media["assignments"][0]["requirement_id"] == requirements[1].id
        assert page_media["assignments"][0]["assignment_id"] == assignments[1].id
        assert page_media["assignments"][0]["asset_id"] == images[1].id
        assert composition.source_hash == _hash(composition.source_snapshot)

        restore_backup(session, exported["path"])
        assert len(session.exec(select(WebsiteMediaPlanningRecord)).all()) == 2
        assert len(session.exec(select(PlannedPageMediaRequirement)).all()) == 2
        assert len(session.exec(select(ImageMetadata)).all()) == 2
        assert len(session.exec(select(PageImageAssignment)).all()) == 2


def test_backup_053_accepts_human_readable_approved_source_constraints(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)

    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    requirement = payload["data"]["planned_page_media_requirements"][0]
    requirement["approved_source_constraints"].append(
        "Representative imagery must not be presented as proof of a specific event."
    )
    path = _write_payload(tmp_path, payload, "human-readable-source-constraints.json")

    loaded = load_backup(path)

    assert loaded["data"]["planned_page_media_requirements"][0][
        "approved_source_constraints"
    ][-1] == "Representative imagery must not be presented as proof of a specific event."


def test_backup_052_defaults_new_groups_empty_without_inventing_governance(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    payload["metadata"]["version"] = "0.52"
    for group in (
        "website_media_planning_records",
        "planned_page_media_requirements",
    ):
        payload["data"].pop(group)
        payload["metadata"]["table_counts"].pop(group)
    payload["data"]["page_compositions"] = []
    payload["metadata"]["table_counts"]["page_compositions"] = 0
    payload["data"]["image_metadata"] = payload["data"]["image_metadata"][:1]
    payload["metadata"]["table_counts"]["image_metadata"] = 1
    payload["data"]["page_image_assignments"] = payload["data"]["page_image_assignments"][:1]
    payload["metadata"]["table_counts"]["page_image_assignments"] = 1
    for record in payload["data"]["image_metadata"]:
        for field in (
            "website_id", "media_key", "media_version", "mime_type", "file_size",
            "width", "height", "checksum_sha256", "managed_storage_path",
            "acquisition_source", "creator_source_identity", "provenance_type",
            "created_by",
            "provenance_notes", "rights_status", "rights_holder", "rights_notes",
            "approved_usage", "prohibited_usage", "permitted_placement_keys",
            "accessibility_intent", "governance_status", "approval_version",
            "approved_by", "approved_at", "retired_by", "retirement_rationale",
            "retired_at", "replaces_image_metadata_id", "gps_metadata_status",
            "gps_metadata", "gps_authorized_by", "gps_authorized_at",
            "gps_authorization_notes",
        ):
            record.pop(field, None)
    for record in payload["data"]["page_image_assignments"]:
        record["status"] = "active"
        for field in (
            "website_id", "site_plan_id", "planned_page_id", "media_requirement_id",
            "assignment_version", "media_version", "placement_contract_version",
            "assigned_by", "assignment_rationale", "assigned_at", "replaced_by",
            "replacement_rationale", "replaced_at", "retired_by",
            "retirement_rationale", "retired_at", "replaces_page_image_assignment_id",
        ):
            record.pop(field, None)
    legacy_path = _write_payload(tmp_path, payload, "legacy-052.json")

    loaded = load_backup(legacy_path)
    assert loaded["data"]["website_media_planning_records"] == []
    assert loaded["data"]["planned_page_media_requirements"] == []

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restore_backup(session, legacy_path)
        image = session.exec(select(ImageMetadata)).one()
        assignment = session.exec(select(PageImageAssignment)).one()
        assert image.governance_status == "legacy_unverified"
        assert image.website_id is None
        assert image.media_key is None
        assert image.approved_by is None
        assert assignment.website_id is None
        assert assignment.media_requirement_id is None
        assert assignment.assigned_by is None
        assert session.exec(select(WebsiteMediaPlanningRecord)).all() == []
        assert session.exec(select(PlannedPageMediaRequirement)).all() == []


@pytest.mark.parametrize(
    ("tamper", "message"),
    (
        ("requirement_website", "crosses a Website"),
        ("planning_snapshot", "source snapshot"),
        ("assignment_page", "crosses a Website"),
        ("image_replacement", "replacement crosses ownership"),
        ("source_provenance", "incomplete or invalid governed page-media"),
        ("external_asset_url", "incomplete or invalid governed page-media"),
        ("mime_extension", "incomplete or invalid governed page-media"),
    ),
)
def test_backup_053_rejects_malformed_or_cross_scope_page_media_graphs(
    tmp_path: Path,
    tamper: str,
    message: str,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        ids = _seed_governed_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    if tamper == "requirement_website":
        payload["data"]["planned_page_media_requirements"][0]["website_id"] = ids[
            "other_website_id"
        ]
    elif tamper == "planning_snapshot":
        payload["data"]["website_media_planning_records"][0]["source_snapshot"][
            "site_plan_id"
        ] += 1000
    elif tamper == "assignment_page":
        payload["data"]["page_image_assignments"][0]["website_id"] = ids[
            "other_website_id"
        ]
    elif tamper == "source_provenance":
        payload["data"]["image_metadata"][0]["acquisition_source"] = "generated"
        payload["data"]["image_metadata"][0]["provenance_type"] = "company_original"
        payload["data"]["image_metadata"][0]["rights_status"] = "owned"
    elif tamper == "external_asset_url":
        payload["data"]["image_metadata"][0]["asset_url"] = (
            "https://external.example.test/unmanaged.webp"
        )
    elif tamper == "mime_extension":
        payload["data"]["image_metadata"][0]["original_filename"] = (
            "home-hero-v1.jpg"
        )
    else:
        payload["data"]["image_metadata"][1]["media_key"] = "different-key"
    path = _write_payload(tmp_path, payload, f"tampered-{tamper}.json")
    with pytest.raises(BackupValidationError, match=message):
        load_backup(path)


def test_backup_054_binds_planning_algorithm_to_source_snapshot(
    tmp_path: Path,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    planning = next(
        item
        for item in payload["data"]["website_media_planning_records"]
        if item["version"] == 2
    )
    planning["source_snapshot"]["algorithm_version"] = (
        "tampered-page-media-planning-v2"
    )
    planning["source_hash"] = _hash(planning["source_snapshot"])

    path = _write_payload(tmp_path, payload, "tampered-algorithm-binding.json")

    with pytest.raises(BackupValidationError, match="source snapshot"):
        load_backup(path)


@pytest.mark.parametrize(
    "v2_signal",
    ("snapshot", "suggestion", "requirement"),
)
def test_backup_054_v2_detection_cannot_be_bypassed_by_relabeling_algorithm(
    tmp_path: Path,
    v2_signal: str,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    planning = next(
        item
        for item in payload["data"]["website_media_planning_records"]
        if item["version"] == 2
    )
    requirement = next(
        item
        for item in payload["data"]["planned_page_media_requirements"]
        if item["planning_record_id"] == planning["id"]
    )
    suggestion = planning["generated_media_suggestions"][0]

    planning["algorithm_version"] = "page-media-planning-v1"
    planning["source_snapshot"]["algorithm_version"] = "page-media-planning-v1"
    planning["source_snapshot"]["placement_contract_version"] = 1
    planning["source_snapshot"].pop("placement_contract_manifest_hash", None)
    suggestion["contract_version"] = 1
    suggestion["target_component_instance_key"] = None
    requirement["contract_version"] = 1
    requirement["target_component_instance_key"] = None

    if v2_signal == "snapshot":
        planning["source_snapshot"]["placement_contract_version"] = 2
    elif v2_signal == "suggestion":
        suggestion["contract_version"] = 2
        suggestion["target_component_instance_key"] = "hero"
    else:
        requirement["contract_version"] = 2
        requirement["target_component_instance_key"] = "hero"
    planning["source_hash"] = _hash(planning["source_snapshot"])

    path = _write_payload(tmp_path, payload, f"tampered-v2-{v2_signal}.json")

    with pytest.raises(
        BackupValidationError,
        match="lacks its exact contract manifest identity",
    ):
        load_backup(path)


@pytest.mark.parametrize(
    "missing_field",
    ("placement_contract_version", "placement_contract_manifest_hash"),
)
def test_backup_054_requires_v2_contract_version_and_manifest_fields(
    tmp_path: Path,
    missing_field: str,
) -> None:
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        _seed_governed_graph(session)
        exported = export_backup(session, backup_dir=tmp_path)
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    planning = next(
        item
        for item in payload["data"]["website_media_planning_records"]
        if item["version"] == 2
    )
    planning["source_snapshot"].pop(missing_field)
    planning["source_hash"] = _hash(planning["source_snapshot"])

    path = _write_payload(tmp_path, payload, f"missing-v2-{missing_field}.json")

    with pytest.raises(
        BackupValidationError,
        match="lacks its exact contract manifest identity",
    ):
        load_backup(path)
