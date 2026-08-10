from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Business,
    GeneratedPage,
    ImageMetadata,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    ScopedMediaAuthorization,
    SitePlan,
    Website,
    WebsiteMediaPlanningRecord,
)
from app.schemas.scoped_media_authorizations import (
    ScopedMediaAuthorizationRead,
    ScopedMediaAuthorizationRequest,
    scoped_media_approval_fingerprint,
)
from app.services.page_media_planning import _asset_compatibility_errors
from app.services.scoped_media_authorizations import (
    ScopedMediaAuthorizationError,
    bind_scoped_media_authorization_to_assignment,
    create_scoped_media_authorization,
    current_scoped_media_authorization,
    list_scoped_media_authorizations,
    scoped_media_assignment_authorization_errors,
    scoped_media_asset_use_errors,
    scoped_media_authorization_errors,
    supersede_current_scoped_media_authorization,
)


NOW = datetime(2026, 8, 10, 16, 0, tzinfo=UTC)
CHECKSUM = "a" * 64
DEFAULT_TERMS = ["representative_nonlocalized"]
REQUIREMENT_ONLY_TERMS = [
    "representative_nonlocalized",
    "requirement_only_usage",
    "no_reuse",
]


@dataclass
class AuthorizationGraph:
    business: Business
    website: Website
    plan: SitePlan
    page: PlannedPage
    requirement: PlannedPageMediaRequirement
    same_page_requirement: PlannedPageMediaRequirement
    other_page: PlannedPage
    same_key_requirement: PlannedPageMediaRequirement
    asset: ImageMetadata
    assignment: PageImageAssignment


@pytest.fixture
def authorization_graph() -> tuple[Session, AuthorizationGraph]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session, _seed_authorization_graph(session)
    engine.dispose()


def _seed_authorization_graph(session: Session) -> AuthorizationGraph:
    business = Business(
        company_name="Scoped Media Test Business",
        business_type="Local service business",
        state="FL",
    )
    session.add(business)
    session.flush()
    website = Website(
        business_id=business.id,
        website_name="Scoped Media Test Website",
        domain="scoped-media.example.test",
        public_url="https://scoped-media.example.test",
    )
    session.add(website)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name="Primary Site Plan",
        status="active",
    )
    session.add(plan)
    session.flush()

    generated = _generated_page(session, business, website, "orlando-service")
    page = _planned_page(session, website, plan, generated, "orlando-service")
    other_generated = _generated_page(
        session,
        business,
        website,
        "winter-park-service",
    )
    other_page = _planned_page(
        session,
        website,
        plan,
        other_generated,
        "winter-park-service",
    )
    planning = WebsiteMediaPlanningRecord(
        website_id=website.id,
        business_id=business.id,
        site_plan_id=plan.id,
        version=1,
        algorithm_version="page-media-planning-v2",
        generated_media_suggestions=[],
        source_snapshot={"fixture": "scoped-media-authorizations"},
        source_hash="b" * 64,
        generated_at=NOW,
    )
    session.add(planning)
    session.flush()

    requirement = _requirement(
        session,
        business,
        website,
        plan,
        page,
        planning,
        placement_key="city-service-hero",
        component="hero",
        target="hero",
    )
    same_page_requirement = _requirement(
        session,
        business,
        website,
        plan,
        page,
        planning,
        placement_key="city-service-evidence",
        component="content_section",
        target="content_section:signs_section",
    )
    same_key_requirement = _requirement(
        session,
        business,
        website,
        plan,
        other_page,
        planning,
        placement_key="city-service-hero",
        component="hero",
        target="hero",
    )
    asset = ImageMetadata(
        business_id=business.id,
        website_id=website.id,
        media_key="scoped-hero",
        media_version=1,
        file_name="scoped-hero.webp",
        image_title="Representative service image",
        alt_text="Representative service image",
        reviewed_alt_text="Representative service image",
        asset_url="/media/page-media/originals/scoped-hero.webp",
        optimized_url="/media/page-media/optimized/scoped-hero.webp",
        thumbnail_url="/media/page-media/thumbnails/scoped-hero.webp",
        original_filename="scoped-hero.webp",
        stored_filename="scoped-hero.webp",
        mime_type="image/webp",
        file_size=25_000,
        width=1600,
        height=900,
        checksum_sha256=CHECKSUM,
        managed_storage_path="page-media/originals/scoped-hero.webp",
        acquisition_source="generated",
        creator_source_identity="Scoped media test operator",
        created_by="Scoped media test operator",
        provenance_type="generated",
        provenance_notes="Synthetic representative image created for an isolated test.",
        rights_status="owned",
        rights_holder="Scoped Media Test Business",
        rights_notes="Authorized for the exact governed test scope.",
        approved_usage=["page_media", "city-service-hero", "city-service-evidence"],
        prohibited_usage=["website_identity"],
        permitted_placement_keys=["city-service-hero", "city-service-evidence"],
        accessibility_intent="informative",
        governance_status="approved",
        approval_version=1,
        usage_authorization_mode="scoped_required",
        required_authorization_terms=list(DEFAULT_TERMS),
        approved_by="Approval Operator",
        approved_at=NOW,
        gps_metadata_status="absent",
        gps_metadata={},
        review_status="reviewed",
        image_role="support",
    )
    session.add(asset)
    session.flush()
    assignment = _assignment(session, page, requirement, asset)
    session.commit()
    return AuthorizationGraph(
        business=business,
        website=website,
        plan=plan,
        page=page,
        requirement=requirement,
        same_page_requirement=same_page_requirement,
        other_page=other_page,
        same_key_requirement=same_key_requirement,
        asset=asset,
        assignment=assignment,
    )


def _generated_page(
    session: Session,
    business: Business,
    website: Website,
    slug: str,
) -> GeneratedPage:
    generated = GeneratedPage(
        business_id=business.id,
        website_id=website.id,
        page_type="city_service",
        page_title=slug.replace("-", " ").title(),
        page_slug=slug,
        h1=slug.replace("-", " ").title(),
        generation_status="generated",
        status="draft",
    )
    session.add(generated)
    session.flush()
    return generated


def _planned_page(
    session: Session,
    website: Website,
    plan: SitePlan,
    generated: GeneratedPage,
    slug: str,
) -> PlannedPage:
    page = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="city_service",
        working_name=slug.replace("-", " ").title(),
        intended_slug=slug,
        planning_status="planned",
        generated_page_id=generated.id,
    )
    session.add(page)
    session.flush()
    return page


def _requirement(
    session: Session,
    business: Business,
    website: Website,
    plan: SitePlan,
    page: PlannedPage,
    planning: WebsiteMediaPlanningRecord,
    *,
    placement_key: str,
    component: str,
    target: str,
) -> PlannedPageMediaRequirement:
    requirement = PlannedPageMediaRequirement(
        website_id=website.id,
        business_id=business.id,
        site_plan_id=plan.id,
        planned_page_id=page.id,
        planning_record_id=planning.id,
        component_or_section=component,
        target_component_instance_key=target,
        placement_key=placement_key,
        contract_version=2,
        version=1,
        requirement_state="required",
        purpose="Provide one exact governed media placement.",
        customer_outcome="Understand the approved service context.",
        intended_subject="Representative service imagery.",
        orientation="landscape",
        aspect_ratio="16:9",
        minimum_width=1200,
        minimum_height=675,
        crop_intent="Preserve the meaningful subject.",
        focal_point_intent="Use the reviewed focal point.",
        responsive_behavior="Use approved responsive derivatives.",
        accessibility_intent="informative",
        approved_source_constraints=["approved_generated_media"],
        permitted_reuse_policy="Use only under the typed authorization policy.",
        replacement_policy="Replacement requires a new exact authorization.",
        compatible_page_types=["city_service"],
        decided_by="Planning Operator",
        rationale="Exact isolated test requirement.",
        decided_at=NOW,
        lifecycle_status="active",
    )
    session.add(requirement)
    session.flush()
    return requirement


def _assignment(
    session: Session,
    page: PlannedPage,
    requirement: PlannedPageMediaRequirement,
    asset: ImageMetadata,
) -> PageImageAssignment:
    assignment = PageImageAssignment(
        generated_page_id=page.generated_page_id,
        image_metadata_id=asset.id,
        website_id=page.website_id,
        site_plan_id=page.site_plan_id,
        planned_page_id=page.id,
        media_requirement_id=requirement.id,
        assignment_version=1,
        media_version=asset.media_version,
        placement_contract_version=requirement.contract_version,
        assigned_by="Assignment Operator",
        assignment_rationale="Exact isolated test assignment.",
        assigned_at=NOW,
        image_role=f"{requirement.placement_key}:assignment-1",
        display_preset="hero_desktop",
        status="active",
    )
    session.add(assignment)
    session.flush()
    return assignment


def _approved_successor_asset(
    session: Session,
    graph: AuthorizationGraph,
) -> ImageMetadata:
    successor = ImageMetadata(
        business_id=graph.business.id,
        website_id=graph.website.id,
        media_key=graph.asset.media_key,
        media_version=2,
        replaces_image_metadata_id=graph.asset.id,
        file_name="scoped-hero-v2.webp",
        image_title=graph.asset.image_title,
        alt_text=graph.asset.alt_text,
        reviewed_alt_text=graph.asset.reviewed_alt_text,
        asset_url="/media/page-media/originals/scoped-hero-v2.webp",
        optimized_url="/media/page-media/optimized/scoped-hero-v2.webp",
        thumbnail_url="/media/page-media/thumbnails/scoped-hero-v2.webp",
        original_filename="scoped-hero-v2.webp",
        stored_filename="scoped-hero-v2.webp",
        mime_type="image/webp",
        file_size=25_000,
        width=1600,
        height=900,
        checksum_sha256="b" * 64,
        managed_storage_path="page-media/originals/scoped-hero-v2.webp",
        acquisition_source=graph.asset.acquisition_source,
        creator_source_identity=graph.asset.creator_source_identity,
        created_by=graph.asset.created_by,
        provenance_type=graph.asset.provenance_type,
        provenance_notes=graph.asset.provenance_notes,
        rights_status=graph.asset.rights_status,
        rights_holder=graph.asset.rights_holder,
        rights_notes=graph.asset.rights_notes,
        approved_usage=list(graph.asset.approved_usage),
        prohibited_usage=list(graph.asset.prohibited_usage),
        permitted_placement_keys=list(graph.asset.permitted_placement_keys),
        accessibility_intent=graph.asset.accessibility_intent,
        governance_status="approved",
        approval_version=1,
        usage_authorization_mode=graph.asset.usage_authorization_mode,
        required_authorization_terms=list(
            graph.asset.required_authorization_terms
        ),
        approved_by="Approval Operator",
        approved_at=NOW,
        gps_metadata_status="absent",
        gps_metadata={},
        review_status="reviewed",
        image_role="support",
    )
    session.add(successor)
    session.commit()
    session.refresh(successor)
    return successor


def _request(
    graph: AuthorizationGraph,
    *,
    requirement: PlannedPageMediaRequirement | None = None,
    assignment: PageImageAssignment | None | object = ...,
    reuse_policy: str = "contract_default",
    terms: list[str] | None = None,
    expected_current_authorization_fingerprint: str | None = None,
) -> ScopedMediaAuthorizationRequest:
    bound_assignment = graph.assignment if assignment is ... else assignment
    return ScopedMediaAuthorizationRequest(
        media_requirement_id=(requirement or graph.requirement).id,
        expected_requirement_version=(requirement or graph.requirement).version,
        expected_placement_contract_version=(
            requirement or graph.requirement
        ).contract_version,
        image_metadata_id=graph.asset.id,
        expected_media_version=graph.asset.media_version,
        expected_asset_checksum_sha256=graph.asset.checksum_sha256,
        expected_approval_version=graph.asset.approval_version,
        expected_approval_fingerprint=scoped_media_approval_fingerprint(
            {
                "image_metadata_id": graph.asset.id,
                "asset_website_id": graph.asset.website_id,
                "asset_business_id": graph.asset.business_id,
                "media_version": graph.asset.media_version,
                "asset_checksum_sha256": graph.asset.checksum_sha256,
                "approval_version": graph.asset.approval_version,
                "asset_approved_by": graph.asset.approved_by,
                "asset_approved_at": graph.asset.approved_at,
                "usage_authorization_mode": graph.asset.usage_authorization_mode,
                "required_authorization_terms": (
                    graph.asset.required_authorization_terms
                ),
            }
        ),
        page_image_assignment_id=(
            bound_assignment.id
            if isinstance(bound_assignment, PageImageAssignment)
            else None
        ),
        expected_assignment_version=(
            bound_assignment.assignment_version
            if isinstance(bound_assignment, PageImageAssignment)
            else None
        ),
        expected_current_authorization_fingerprint=(
            expected_current_authorization_fingerprint
        ),
        reuse_policy=reuse_policy,
        authorization_terms=list(
            dict.fromkeys(
                [
                    *(terms or list(DEFAULT_TERMS)),
                    *graph.asset.required_authorization_terms,
                ]
            )
        ),
        authorized_by="Authorization Operator",
        authorization_rationale="Typed authorization for one exact governed use.",
    )


def _create(
    session: Session,
    graph: AuthorizationGraph,
    **kwargs,
) -> ScopedMediaAuthorizationRead:
    requirement = kwargs.get("requirement") or graph.requirement
    current = current_scoped_media_authorization(session, requirement.id)
    return create_scoped_media_authorization(
        session,
        graph.plan.id,
        _request(
            graph,
            expected_current_authorization_fingerprint=(
                current.authorization_fingerprint if current else None
            ),
            **kwargs,
        ),
    )


def _durable(
    session: Session,
    authorization: ScopedMediaAuthorizationRead,
) -> ScopedMediaAuthorization:
    row = session.get(ScopedMediaAuthorization, authorization.id)
    assert row is not None
    return row


def _errors(
    session: Session,
    graph: AuthorizationGraph,
    authorization: ScopedMediaAuthorization,
    *,
    assignment: PageImageAssignment | None | object = ...,
) -> list[str]:
    bound_assignment = graph.assignment if assignment is ... else assignment
    return scoped_media_authorization_errors(
        session,
        authorization,
        asset=graph.asset,
        requirement=graph.requirement,
        page=graph.page,
        website=graph.website,
        assignment=(
            bound_assignment
            if isinstance(bound_assignment, PageImageAssignment)
            else None
        ),
    )


def _target_use_errors(
    session: Session,
    graph: AuthorizationGraph,
    *,
    requirement: PlannedPageMediaRequirement,
    page: PlannedPage,
    assignment: PageImageAssignment | None = None,
) -> list[str]:
    return scoped_media_asset_use_errors(
        session,
        asset=graph.asset,
        requirement=requirement,
        page=page,
        website=graph.website,
        assignment=assignment,
    )


def _candidate_errors(
    session: Session,
    graph: AuthorizationGraph,
    *,
    requirement: PlannedPageMediaRequirement,
    page: PlannedPage,
) -> list[str]:
    return _asset_compatibility_errors(
        session,
        graph.asset,
        requirement,
        page,
        graph.website,
    )


def test_01_exact_scope_asset_approval_and_assignment_succeed(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    created = _create(session, graph)
    durable = _durable(session, created)

    assert created.website_id == graph.website.id
    assert created.site_plan_id == graph.plan.id
    assert created.planned_page_id == graph.page.id
    assert created.generated_page_id == graph.page.generated_page_id
    assert created.media_requirement_id == graph.requirement.id
    assert created.requirement_version == graph.requirement.version
    assert created.placement_key == "city-service-hero"
    assert created.image_metadata_id == graph.asset.id
    assert created.approval_version == graph.asset.approval_version
    assert created.page_image_assignment_id == graph.assignment.id
    assert created.assignment_version == graph.assignment.assignment_version
    assert len(created.approval_fingerprint) == 64
    assert len(created.authorization_fingerprint) == 64
    assert _errors(session, graph, durable) == []


@pytest.mark.parametrize(
    "mismatch",
    (
        "website",
        "site_plan",
        "page",
        "requirement",
        "asset",
        "approval",
        "assignment",
    ),
)
def test_02_through_08_exact_scope_mismatches_fail_closed(
    authorization_graph: tuple[Session, AuthorizationGraph],
    mismatch: str,
) -> None:
    session, graph = authorization_graph
    durable = _durable(session, _create(session, graph))

    if mismatch == "website":
        durable.website_id += 10_000
    elif mismatch == "site_plan":
        durable.site_plan_id += 10_000
    elif mismatch == "page":
        durable.planned_page_id += 10_000
    elif mismatch == "requirement":
        durable.media_requirement_id += 10_000
    elif mismatch == "asset":
        durable.image_metadata_id += 10_000
    elif mismatch == "approval":
        durable.approval_version += 1
    else:
        durable.page_image_assignment_id = (durable.page_image_assignment_id or 0) + 10_000

    errors = _errors(session, graph, durable)

    assert errors
    assert any(
        marker in " ".join(errors).lower()
        for marker in ("exact", "approval", "assignment", "fingerprint")
    )


def test_09_missing_authorization_fails_the_central_candidate_use_gate(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph

    assert current_scoped_media_authorization(session, graph.requirement.id) is None
    assert _candidate_errors(
        session,
        graph,
        requirement=graph.requirement,
        page=graph.page,
    )


def test_10_free_text_assignment_rationale_never_replaces_typed_authorization(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    graph.assignment.assignment_rationale = (
        "visible_branding_allowed, no_reuse, contract_deviation_authorized"
    )

    errors = _candidate_errors(
        session,
        graph,
        requirement=graph.requirement,
        page=graph.page,
    )

    assert errors
    assert current_scoped_media_authorization(session, graph.requirement.id) is None


def test_11_superseded_authorization_is_stale_but_preserved(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    first = _create(session, graph)
    second = _create(session, graph)
    stale = _durable(session, first)

    assert stale.lifecycle_status == "superseded"
    assert second.supersedes_authorization_id == first.id
    assert any("stale or superseded" in error for error in _errors(session, graph, stale))


def test_12_tampered_typed_terms_fail_integrity_validation(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    durable = _durable(session, _create(session, graph))
    durable.authorization_terms = [
        "representative_nonlocalized",
        "visible_branding_allowed",
    ]

    errors = _errors(session, graph, durable)

    assert any("integrity fingerprint" in error for error in errors)


def test_13_read_schema_serializes_the_complete_typed_identity(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    created = _create(
        session,
        graph,
        reuse_policy="requirement_only",
        terms=list(REQUIREMENT_ONLY_TERMS),
    )

    serialized = created.model_dump(mode="json")
    restored = ScopedMediaAuthorizationRead.model_validate(serialized)

    assert restored == created
    assert serialized["authorization_terms"] == sorted(REQUIREMENT_ONLY_TERMS)
    assert serialized["authorization_fingerprint"] == created.authorization_fingerprint


def test_14_history_api_serializes_current_and_superseded_versions(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    _create(session, graph)
    current = _create(
        session,
        graph,
        reuse_policy="explicitly_reusable",
        terms=["visible_branding_allowed"],
    )

    history = list_scoped_media_authorizations(
        session,
        graph.plan.id,
        media_requirement_id=graph.requirement.id,
        image_metadata_id=graph.asset.id,
    )

    assert [row.authorization_version for row in history] == [1, 2]
    assert [row.lifecycle_status for row in history] == ["superseded", "current"]
    assert history[-1].model_dump(mode="json")["id"] == current.id


def test_15_candidate_to_assignment_binding_appends_immutable_lineage(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    candidate = _create(session, graph, assignment=None)
    candidate_row = _durable(session, candidate)

    bound = bind_scoped_media_authorization_to_assignment(
        session,
        authorization=candidate_row,
        assignment=graph.assignment,
    )
    session.commit()
    session.refresh(candidate_row)
    session.refresh(bound)

    assert candidate_row.lifecycle_status == "superseded"
    assert candidate_row.page_image_assignment_id is None
    assert bound.lifecycle_status == "current"
    assert bound.authorization_version == 2
    assert bound.supersedes_authorization_id == candidate_row.id
    assert bound.page_image_assignment_id == graph.assignment.id
    assert bound.assignment_version == graph.assignment.assignment_version
    assert bound.authorization_terms == candidate_row.authorization_terms
    assert bound.authorized_at == candidate_row.authorized_at


def test_16_reauthorization_preserves_a_single_successor_chain(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    first = _create(session, graph, assignment=None)
    second = _create(
        session,
        graph,
        assignment=None,
        reuse_policy="explicitly_reusable",
        terms=["visible_branding_allowed"],
    )

    rows = list(
        session.exec(
            select(ScopedMediaAuthorization)
            .where(ScopedMediaAuthorization.media_requirement_id == graph.requirement.id)
            .order_by(ScopedMediaAuthorization.authorization_version)
        ).all()
    )

    assert [row.id for row in rows] == [first.id, second.id]
    assert rows[1].supersedes_authorization_id == rows[0].id
    assert [row.lifecycle_status for row in rows] == ["superseded", "current"]


def test_17_requirement_only_asset_is_not_a_candidate_for_another_requirement(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    _create(
        session,
        graph,
        assignment=None,
        reuse_policy="requirement_only",
        terms=list(REQUIREMENT_ONLY_TERMS),
    )

    errors = _candidate_errors(
        session,
        graph,
        requirement=graph.same_page_requirement,
        page=graph.page,
    )

    assert any("exact requirement" in error for error in errors)


def test_18_requirement_only_rejects_direct_authorization_elsewhere(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    _create(
        session,
        graph,
        assignment=None,
        reuse_policy="requirement_only",
        terms=list(REQUIREMENT_ONLY_TERMS),
    )

    direct_errors = scoped_media_assignment_authorization_errors(
        session,
        asset=graph.asset,
        requirement=graph.same_key_requirement,
        page=graph.other_page,
        website=graph.website,
    )
    assert direct_errors

    with pytest.raises(ScopedMediaAuthorizationError, match="prohibits another scope"):
        _create(
            session,
            graph,
            requirement=graph.same_key_requirement,
            assignment=None,
        )


def test_19_page_only_rejects_candidate_use_on_another_page(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    _create(
        session,
        graph,
        assignment=None,
        reuse_policy="page_only",
        terms=["page_only_usage"],
    )

    errors = _candidate_errors(
        session,
        graph,
        requirement=graph.same_key_requirement,
        page=graph.other_page,
    )

    assert any("authorized page" in error for error in errors)


def test_20_no_reuse_rejects_fallback_equivalent_resolution(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    _create(
        session,
        graph,
        assignment=None,
        reuse_policy="requirement_only",
        terms=list(REQUIREMENT_ONLY_TERMS),
    )

    fallback_errors = _target_use_errors(
        session,
        graph,
        requirement=graph.same_page_requirement,
        page=graph.page,
        assignment=None,
    )

    assert fallback_errors
    assert any("exact requirement" in error for error in fallback_errors)


def test_21_no_reuse_authorization_cannot_bind_a_cloned_assignment(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    created = _create(
        session,
        graph,
        reuse_policy="requirement_only",
        terms=list(REQUIREMENT_ONLY_TERMS),
    )
    clone = _assignment(
        session,
        graph.other_page,
        graph.same_key_requirement,
        graph.asset,
    )
    current = _durable(session, created)

    with pytest.raises(
        ScopedMediaAuthorizationError,
        match="does not preserve the exact predecessor",
    ):
        bind_scoped_media_authorization_to_assignment(
            session,
            authorization=current,
            assignment=clone,
        )


def test_22_approval_and_dimension_compatibility_do_not_bypass_no_reuse(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    assert graph.asset.governance_status == "approved"
    assert graph.asset.width >= graph.same_key_requirement.minimum_width
    assert graph.asset.height >= graph.same_key_requirement.minimum_height
    _create(
        session,
        graph,
        assignment=None,
        reuse_policy="requirement_only",
        terms=list(REQUIREMENT_ONLY_TERMS),
    )

    assert _candidate_errors(
        session,
        graph,
        requirement=graph.same_key_requirement,
        page=graph.other_page,
    )


def test_23_only_available_asset_still_cannot_bypass_no_reuse(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    _create(
        session,
        graph,
        assignment=None,
        reuse_policy="requirement_only",
        terms=list(REQUIREMENT_ONLY_TERMS),
    )
    only_available_assets = [graph.asset]

    compatible = [
        asset
        for asset in only_available_assets
        if not _asset_compatibility_errors(
            session,
            asset,
            requirement=graph.same_key_requirement,
            page=graph.other_page,
            website=graph.website,
        )
    ]

    assert compatible == []


def test_24_same_website_and_placement_key_do_not_bypass_exact_scope(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    assert graph.requirement.placement_key == graph.same_key_requirement.placement_key
    assert graph.page.website_id == graph.other_page.website_id
    _create(
        session,
        graph,
        assignment=None,
        reuse_policy="requirement_only",
        terms=list(REQUIREMENT_ONLY_TERMS),
    )

    errors = _candidate_errors(
        session,
        graph,
        requirement=graph.same_key_requirement,
        page=graph.other_page,
    )

    assert any("exact requirement" in error for error in errors)


def test_25_contract_default_remains_reusable_with_fresh_exact_authorization(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    _create(session, graph, assignment=None, reuse_policy="contract_default")

    assert _candidate_errors(
        session,
        graph,
        requirement=graph.same_page_requirement,
        page=graph.page,
    ) == []

    second = _create(
        session,
        graph,
        requirement=graph.same_page_requirement,
        assignment=None,
        reuse_policy="contract_default",
    )

    assert second.media_requirement_id == graph.same_page_requirement.id
    assert second.reuse_policy == "contract_default"


def test_scoped_required_reusable_authorization_never_substitutes_for_exact_scope(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    _create(
        session,
        graph,
        assignment=graph.assignment,
        reuse_policy="explicitly_reusable",
    )
    second_assignment = _assignment(
        session,
        graph.page,
        graph.same_page_requirement,
        graph.asset,
    )
    session.commit()

    errors = _target_use_errors(
        session,
        graph,
        requirement=graph.same_page_requirement,
        page=graph.page,
        assignment=second_assignment,
    )

    assert errors == [
        "Governed media requires a current typed scoped authorization for this exact requirement."
    ]


def test_cross_page_page_only_authorization_cannot_follow_existing_use(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    _create(session, graph, assignment=None, reuse_policy="contract_default")

    with pytest.raises(
        ScopedMediaAuthorizationError,
        match="another page",
    ):
        _create(
            session,
            graph,
            requirement=graph.same_key_requirement,
            assignment=None,
            reuse_policy="page_only",
            terms=["page_only_usage"],
        )


def test_visible_branding_term_never_waives_asset_prohibited_usage(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    _create(
        session,
        graph,
        assignment=None,
        terms=["visible_branding_allowed", "contract_deviation_authorized"],
    )
    graph.asset.prohibited_usage = [
        *(graph.asset.prohibited_usage or []),
        "page_media",
    ]
    session.add(graph.asset)
    session.commit()

    errors = _candidate_errors(
        session,
        graph,
        requirement=graph.requirement,
        page=graph.page,
    )

    assert "Media prohibited usage blocks this placement." in errors


def test_requirement_retirement_closes_current_authorization_without_copy_forward(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    original = _create(session, graph)

    supersede_current_scoped_media_authorization(
        session,
        graph.requirement.id,
        changed_at=NOW,
    )
    graph.requirement.lifecycle_status = "superseded"
    graph.assignment.status = "replaced"
    graph.assignment.replaced_by = "Planning Operator"
    graph.assignment.replacement_rationale = "Requirement retired in test."
    graph.assignment.replaced_at = NOW
    session.add(graph.requirement)
    session.add(graph.assignment)
    session.commit()

    retired = session.get(ScopedMediaAuthorization, original.id)
    assert retired is not None
    assert retired.lifecycle_status == "superseded"
    assert current_scoped_media_authorization(session, graph.requirement.id) is None
    assert current_scoped_media_authorization(
        session,
        graph.same_page_requirement.id,
    ) is None

    replacement = _create(
        session,
        graph,
        requirement=graph.same_page_requirement,
        assignment=None,
    )
    assert replacement.media_requirement_id == graph.same_page_requirement.id
    assert replacement.supersedes_authorization_id is None


def test_asset_ownership_change_invalidates_approval_and_scope_identity(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    created = _create(session, graph)
    authorization = _durable(session, created)
    graph.asset.business_id += 1000

    errors = _errors(session, graph, authorization)

    assert any("Website or Business boundary" in error for error in errors)
    assert any("approval identity" in error for error in errors)


def test_closed_lineage_reauthorization_uses_full_history_tip_and_next_version(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    first = _create(session, graph, assignment=None)
    supersede_current_scoped_media_authorization(
        session,
        graph.requirement.id,
        changed_at=NOW,
    )
    session.commit()

    second = create_scoped_media_authorization(
        session,
        graph.plan.id,
        _request(graph, assignment=None),
    )

    assert second.authorization_version == 2
    assert second.supersedes_authorization_id == first.id
    assert [
        row.lifecycle_status
        for row in session.exec(
            select(ScopedMediaAuthorization)
            .where(
                ScopedMediaAuthorization.media_requirement_id
                == graph.requirement.id
            )
            .order_by(ScopedMediaAuthorization.authorization_version)
        ).all()
    ] == ["superseded", "current"]


def test_non_tip_current_lineage_tampering_fails_closed(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    first = _durable(session, _create(session, graph, assignment=None))
    second = _durable(session, _create(session, graph, assignment=None))
    second.lifecycle_status = "superseded"
    session.add(second)
    session.commit()
    first.lifecycle_status = "current"
    session.add(first)
    session.commit()

    with pytest.raises(ScopedMediaAuthorizationError, match="lineage"):
        current_scoped_media_authorization(session, graph.requirement.id)


def test_missing_optional_assignment_reference_fails_closed(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    request = _request(graph, assignment=None).model_copy(
        update={
            "page_image_assignment_id": 999_999,
            "expected_assignment_version": 1,
        }
    )

    with pytest.raises(
        ScopedMediaAuthorizationError,
        match="assignment was not found",
    ):
        create_scoped_media_authorization(session, graph.plan.id, request)


def test_scoped_required_asset_rejects_missing_asset_required_typed_term(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    graph.asset.required_authorization_terms = [
        "authorized_person_likeness"
    ]
    session.add(graph.asset)
    session.commit()
    request = _request(graph, assignment=None).model_copy(
        update={"authorization_terms": ["representative_nonlocalized"]}
    )

    with pytest.raises(
        ScopedMediaAuthorizationError,
        match="missing asset-required typed terms: authorized_person_likeness",
    ):
        create_scoped_media_authorization(session, graph.plan.id, request)


def test_exact_asset_authorization_rejects_an_approved_successor_version(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    authorization = _durable(session, _create(session, graph, assignment=None))
    _approved_successor_asset(session, graph)

    errors = _errors(session, graph, authorization, assignment=None)

    assert "Scoped media authorization asset version is superseded." in errors


def test_new_authorization_rejects_asset_with_approved_successor_without_reactivation(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    _approved_successor_asset(session, graph)

    with pytest.raises(
        ScopedMediaAuthorizationError,
        match="superseded governed media version",
    ):
        create_scoped_media_authorization(
            session,
            graph.plan.id,
            _request(
                graph,
                assignment=None,
                expected_current_authorization_fingerprint=None,
            ),
        )

    assert current_scoped_media_authorization(
        session,
        graph.requirement.id,
    ) is None
    assert list(
        session.exec(
            select(ScopedMediaAuthorization).where(
                ScopedMediaAuthorization.media_requirement_id
                == graph.requirement.id
            )
        ).all()
    ) == []


def test_mismatched_assignment_successor_is_rejected_without_mutating_predecessor(
    authorization_graph: tuple[Session, AuthorizationGraph],
) -> None:
    session, graph = authorization_graph
    created = _create(session, graph)
    authorization = _durable(session, created)
    mismatched = _assignment(
        session,
        graph.other_page,
        graph.same_key_requirement,
        graph.asset,
    )
    predecessor_id = graph.assignment.id
    mismatched.assignment_version = 2
    mismatched.replaces_page_image_assignment_id = predecessor_id
    session.add(mismatched)
    session.commit()

    with pytest.raises(
        ScopedMediaAuthorizationError,
        match="does not preserve the exact predecessor",
    ):
        bind_scoped_media_authorization_to_assignment(
            session,
            authorization=authorization,
            assignment=mismatched,
        )

    session.refresh(authorization)
    session.refresh(graph.assignment)
    assert authorization.lifecycle_status == "current"
    assert authorization.page_image_assignment_id == graph.assignment.id
    assert graph.assignment.status == "active"
    assert current_scoped_media_authorization(
        session,
        graph.requirement.id,
    ).id == authorization.id
