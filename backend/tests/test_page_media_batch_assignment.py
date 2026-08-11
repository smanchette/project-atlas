from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session
from sqlmodel import Session, SQLModel, select

from app.api.page_media_planning_routes import router
from app.db.session import get_session
from app.models import (
    GeneratedPageQAResult,
    ImageMetadata,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    ScopedMediaAuthorization,
)
from app.schemas.page_media_planning import (
    PageMediaAssignmentRequest,
    PageMediaBatchAssignmentOperation,
    PageMediaBatchAssignmentRequest,
    PageMediaBatchAssignmentResult,
)
from app.schemas.scoped_media_authorizations import ScopedMediaAuthorizationRequest
from app.services import page_composition as composition_service
from app.services import page_media_planning as media_planning
from app.services.page_media_planning import (
    PageMediaPlanningError,
    approve_page_media_asset,
    assign_media_batch_to_requirements,
    assign_media_to_requirement,
    effective_media_requirements,
    page_media_asset_read,
    refresh_site_plan_media_suggestions,
)
from app.services.page_media_roles import resolve_requirement_semantic_media_role
from app.services.scoped_media_authorizations import (
    ScopedMediaAuthorizationError,
    create_scoped_media_authorization,
    current_scoped_media_authorization,
)
from tests.test_page_media_planning import (
    _authorize_asset_for_requirement,
    _bind_flo_zone_identity,
    _create_asset,
    _decide_all,
    _engine,
    _refresh_test_compositions,
    _scope,
)


@dataclass
class _BatchFixture:
    business: object
    website: object
    plan: object
    planned: PlannedPage
    generated: object
    composition: PageComposition
    requirements: list[PlannedPageMediaRequirement]
    assets: list[ImageMetadata]
    authorizations: list[ScopedMediaAuthorization | None]
    payload: PageMediaBatchAssignmentRequest


def _prepare_batch(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    suffix: str = "atomic-batch",
    page_types: tuple[str, ...] = ("city_service",),
    page_index: int = 0,
    scoped: bool = True,
) -> _BatchFixture:
    business, website, plan, pages = _scope(
        session,
        suffix,
        page_types=page_types,
    )
    planned, generated = pages[page_index]
    generated.qa_status = "ready"
    generated.qa_result = {"status": "ready", "baseline": True}
    generated.qa_checked_at = datetime(2026, 8, 11, 15, 0, tzinfo=UTC)
    session.add(generated)
    session.commit()

    workspace = refresh_site_plan_media_suggestions(session, plan.id)
    _decide_all(session, plan.id, workspace)
    requirements = effective_media_requirements(session, planned.id)
    assets: list[ImageMetadata] = []
    authorizations: list[ScopedMediaAuthorization | None] = []
    operations: list[PageMediaBatchAssignmentOperation] = []
    for index, requirement in enumerate(requirements):
        asset = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=business.id,
            website_id=website.id,
            media_key=f"{suffix}-{index}",
            placement_key=requirement.placement_key,
            usage_authorization_mode=(
                "scoped_required" if scoped else "contract_default"
            ),
            required_authorization_terms=(
                ["representative_nonlocalized"] if scoped else None
            ),
        )
        asset = approve_page_media_asset(
            session,
            asset.id,
            expected_website_id=website.id,
            expected_business_id=business.id,
            approved_by="Batch Approval Operator",
            expected_media_version=asset.media_version,
        )
        authorization = (
            _authorize_asset_for_requirement(
                session,
                plan=plan,
                requirement=requirement,
                asset=asset,
            )
            if scoped
            else None
        )
        assets.append(asset)
        authorizations.append(authorization)
        operations.append(
            _operation(
                planned,
                requirement,
                asset,
                authorization,
            )
        )

    composition = session.exec(
        select(PageComposition).where(
            PageComposition.planned_page_id == planned.id
        )
    ).one()
    assert composition.status == "current"
    payload = PageMediaBatchAssignmentRequest(
        website_id=website.id,
        site_plan_id=plan.id,
        planned_page_id=planned.id,
        generated_page_id=generated.id,
        composition_id=composition.id,
        expected_composition_version=composition.composition_version,
        expected_composition_source_hash=composition.source_hash,
        assignments=operations,
    )
    return _BatchFixture(
        business=business,
        website=website,
        plan=plan,
        planned=planned,
        generated=generated,
        composition=composition,
        requirements=requirements,
        assets=assets,
        authorizations=authorizations,
        payload=payload,
    )


def _operation(
    planned: PlannedPage,
    requirement: PlannedPageMediaRequirement,
    asset: ImageMetadata,
    authorization: ScopedMediaAuthorization | None,
) -> PageMediaBatchAssignmentOperation:
    bound_session = object_session(asset)
    assert bound_session is not None
    bound_session.refresh(asset)
    if authorization is not None:
        bound_session.refresh(authorization)
    approval = page_media_asset_read(asset).approval_fingerprint
    assert approval is not None
    assert authorization is not None
    return PageMediaBatchAssignmentOperation(
        media_requirement_id=requirement.id,
        expected_requirement_version=requirement.version,
        expected_placement_contract_version=requirement.contract_version,
        placement_key=requirement.placement_key,
        target_component_instance_key=requirement.target_component_instance_key,
        image_metadata_id=asset.id,
        expected_media_version=asset.media_version,
        expected_asset_checksum_sha256=asset.checksum_sha256,
        expected_approval_version=asset.approval_version,
        expected_approval_fingerprint=approval,
        expected_scoped_authorization_id=authorization.id,
        expected_authorization_version=authorization.authorization_version,
        expected_authorization_fingerprint=authorization.authorization_fingerprint,
        expected_authorization_reuse_policy=authorization.reuse_policy,
        expected_authorization_terms=list(authorization.authorization_terms),
        canonical_media_role=resolve_requirement_semantic_media_role(
            requirement,
            planned,
        ),
        assigned_by="Batch Assignment Operator",
        rationale="Assign the exact approved media in one atomic page batch.",
        display_preset="hero_desktop",
    )


def _payload_with(
    fixture: _BatchFixture,
    operations: list[PageMediaBatchAssignmentOperation],
    **updates,
) -> PageMediaBatchAssignmentRequest:
    return fixture.payload.model_copy(
        update={"assignments": operations, **updates},
        deep=True,
    )


def _assert_no_batch_mutation(
    session: Session,
    fixture: _BatchFixture,
    *,
    expected_authorization_count: int | None = None,
) -> None:
    assert session.exec(select(PageImageAssignment)).all() == []
    composition = session.get(PageComposition, fixture.composition.id)
    assert composition is not None
    assert composition.status == "current"
    assert composition.composition_version == fixture.composition.composition_version
    assert composition.source_hash == fixture.composition.source_hash
    assert composition.source_snapshot == fixture.composition.source_snapshot
    generated = session.get(type(fixture.generated), fixture.generated.id)
    assert generated is not None
    assert generated.qa_status == "ready"
    assert generated.qa_result == {"status": "ready", "baseline": True}
    if expected_authorization_count is not None:
        assert len(session.exec(select(ScopedMediaAuthorization)).all()) == (
            expected_authorization_count
        )


def test_three_valid_assignments_commit_atomically_once_without_intermediate_qa_or_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(session, monkeypatch, tmp_path)
        initial_authorizations = {
            row.id: (row.authorization_fingerprint, row.authorized_at)
            for row in fixture.authorizations
            if row is not None
        }
        stale_calls: list[int] = []
        original_stale = media_planning._mark_composition_stale

        def mark_once(target_session: Session, planned_page_id: int) -> None:
            stale_calls.append(planned_page_id)
            original_stale(target_session, planned_page_id)

        monkeypatch.setattr(media_planning, "_mark_composition_stale", mark_once)
        monkeypatch.setattr(
            composition_service,
            "refresh_site_plan_compositions",
            lambda *_args, **_kwargs: pytest.fail(
                "Batch assignment must not refresh a composition."
            ),
        )

        result = assign_media_batch_to_requirements(
            session,
            fixture.plan.id,
            fixture.payload,
        )

        assert len(result.assignments) == 3
        assert result.composition_status == "stale"
        assert stale_calls == [fixture.planned.id]
        assert {row.image_role for row in result.assignments} == {
            "hero",
            "service",
            "support",
        }
        assert all(row.display_preset == "hero_desktop" for row in result.assignments)
        assert all(
            row.effective_display_preset == "hero_desktop"
            for row in result.assignments
        )
        assert len(session.exec(select(PageImageAssignment)).all()) == 3
        assert session.exec(select(GeneratedPageQAResult)).all() == []
        generated = session.get(type(fixture.generated), fixture.generated.id)
        assert generated.qa_status == "not_run"
        assert generated.qa_result is None
        assert generated.qa_checked_at is None
        histories = session.exec(
            select(ScopedMediaAuthorization).order_by(
                ScopedMediaAuthorization.media_requirement_id,
                ScopedMediaAuthorization.authorization_version,
            )
        ).all()
        assert len(histories) == 6
        for initial_id, identity in initial_authorizations.items():
            initial = session.get(ScopedMediaAuthorization, initial_id)
            assert initial.lifecycle_status == "superseded"
            assert (initial.authorization_fingerprint, initial.authorized_at) == identity
        current = [row for row in histories if row.lifecycle_status == "current"]
        assert len(current) == 3
        assert all(row.page_image_assignment_id is not None for row in current)
        requirement_presets = {
            placement.effective_requirement.effective_display_preset
            for placement in result.workspace.placements
            if placement.effective_requirement is not None
        }
        assert requirement_presets == {"hero_desktop"}


def test_one_item_batch_succeeds_through_actual_fastapi_route_serialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(session, monkeypatch, tmp_path)
        payload = _payload_with(fixture, [fixture.payload.assignments[0]])
        app = FastAPI()
        app.include_router(router)

        def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        response = TestClient(app).post(
            f"/site-plans/{fixture.plan.id}/page-media/placements/assign-batch",
            json=payload.model_dump(mode="json"),
        )

        assert response.status_code == 200
        body = response.json()
        validated = PageMediaBatchAssignmentResult.model_validate(body)
        assert validated.planned_page_id == fixture.planned.id
        assert len(validated.assignments) == 1
        assert validated.assignments[0].effective_display_preset == "hero_desktop"
        placement = next(
            item
            for item in validated.workspace.placements
            if item.effective_requirement
            and item.effective_requirement.id
            == fixture.requirements[0].id
        )
        assert placement.effective_requirement.effective_display_preset == "hero_desktop"


def test_batch_rejects_mixed_planned_pages_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="mixed-page-source",
            page_types=("home", "about"),
        )
        second_planned = session.exec(
            select(PlannedPage).where(
                PlannedPage.site_plan_id == first.plan.id,
                PlannedPage.id != first.planned.id,
            )
        ).one()
        second_requirement = effective_media_requirements(
            session,
            second_planned.id,
        )[0]
        second_asset = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=first.business.id,
            website_id=first.website.id,
            media_key="mixed-page-second",
            placement_key=second_requirement.placement_key,
            usage_authorization_mode="scoped_required",
            required_authorization_terms=["representative_nonlocalized"],
        )
        second_asset = approve_page_media_asset(
            session,
            second_asset.id,
            expected_website_id=first.website.id,
            expected_business_id=first.business.id,
            approved_by="Batch Approval Operator",
            expected_media_version=1,
        )
        second_authorization = _authorize_asset_for_requirement(
            session,
            plan=first.plan,
            requirement=second_requirement,
            asset=second_asset,
        )
        second_operation = _operation(
            second_planned,
            second_requirement,
            second_asset,
            second_authorization,
        )
        payload = _payload_with(
            first,
            [first.payload.assignments[1], second_operation],
        )

        with pytest.raises(PageMediaPlanningError, match="exact page scope"):
            assign_media_batch_to_requirements(session, first.plan.id, payload)
        _assert_no_batch_mutation(session, first)


def test_batch_rejects_mixed_website_and_site_plan_assertions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="mixed-scope-first",
        )
        second = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="mixed-scope-second",
        )

        mixed_website = _payload_with(
            first,
            first.payload.assignments,
            website_id=second.website.id,
        )
        with pytest.raises(PageMediaPlanningError, match="Website or Site Plan"):
            assign_media_batch_to_requirements(session, first.plan.id, mixed_website)

        mixed_site_plan = _payload_with(
            first,
            [first.payload.assignments[0], second.payload.assignments[1]],
        )
        with pytest.raises(PageMediaPlanningError, match="exact page scope"):
            assign_media_batch_to_requirements(session, first.plan.id, mixed_site_plan)

        wrong_route_plan = _payload_with(
            first,
            first.payload.assignments,
            site_plan_id=second.plan.id,
        )
        with pytest.raises(PageMediaPlanningError, match="does not match the route"):
            assign_media_batch_to_requirements(session, first.plan.id, wrong_route_plan)
        _assert_no_batch_mutation(session, first)


def test_stale_starting_composition_blocks_batch_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(session, monkeypatch, tmp_path)
        fixture.composition.status = "stale"
        session.add(fixture.composition)
        session.commit()

        with pytest.raises(PageMediaPlanningError, match="Starting Page Composition is stale"):
            assign_media_batch_to_requirements(session, fixture.plan.id, fixture.payload)
        assert session.exec(select(PageImageAssignment)).all() == []
        assert session.get(PageComposition, fixture.composition.id).status == "stale"


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("duplicate_requirement", "duplicate media requirement"),
        ("duplicate_target", "duplicate exact component-instance target"),
        ("wrong_role", "canonical semantic media role"),
        ("stale_asset", "asset identity or version changed"),
        ("wrong_approval", "approval identity or fingerprint changed"),
        ("stale_authorization", "authorization identity, typed terms"),
        ("wrong_authorization", "authorization identity, typed terms"),
        ("wrong_authorization_terms", "authorization identity, typed terms"),
    ),
)
def test_batch_validation_rejects_conflicts_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    message: str,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix=f"reject-{case}",
        )
        operations = list(fixture.payload.assignments)
        if case == "duplicate_requirement":
            operations = [operations[0], operations[0].model_copy(deep=True)]
        elif case == "duplicate_target":
            operations[1] = operations[1].model_copy(
                update={
                    "target_component_instance_key": (
                        operations[0].target_component_instance_key
                    )
                }
            )
        elif case == "wrong_role":
            wrong_role = (
                "support"
                if operations[1].canonical_media_role != "support"
                else "hero"
            )
            operations[1] = operations[1].model_copy(
                update={"canonical_media_role": wrong_role}
            )
        elif case == "stale_asset":
            operations[0] = operations[0].model_copy(
                update={
                    "expected_media_version": operations[0].expected_media_version + 1
                }
            )
        elif case == "wrong_approval":
            operations[0] = operations[0].model_copy(
                update={"expected_approval_fingerprint": "f" * 64}
            )
        elif case == "stale_authorization":
            operations[0] = operations[0].model_copy(
                update={
                    "expected_authorization_version": (
                        operations[0].expected_authorization_version + 1
                    )
                }
            )
        elif case == "wrong_authorization":
            other = operations[1]
            operations[0] = operations[0].model_copy(
                update={
                    "expected_scoped_authorization_id": (
                        other.expected_scoped_authorization_id
                    ),
                    "expected_authorization_version": (
                        other.expected_authorization_version
                    ),
                    "expected_authorization_fingerprint": (
                        other.expected_authorization_fingerprint
                    ),
                    "expected_authorization_reuse_policy": (
                        other.expected_authorization_reuse_policy
                    ),
                    "expected_authorization_terms": (
                        other.expected_authorization_terms
                    ),
                }
            )
        else:
            operations[0] = operations[0].model_copy(
                update={"expected_authorization_terms": ["no_reuse"]}
            )
        payload = _payload_with(fixture, operations)

        with pytest.raises(PageMediaPlanningError, match=message):
            assign_media_batch_to_requirements(session, fixture.plan.id, payload)
        _assert_no_batch_mutation(
            session,
            fixture,
            expected_authorization_count=3,
        )


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("placement_key", "placement key or exact component-instance target"),
        ("target", "placement key or exact component-instance target"),
        ("requirement_version", "requirement or placement-contract version"),
        ("contract_version", "requirement or placement-contract version"),
        ("composition_id", "exact Page Composition boundary"),
        ("composition_version", "Composition identity or version changed"),
        ("composition_hash", "Composition identity or version changed"),
        ("generated_page_id", "exact Planned Page boundary"),
    ),
)
def test_batch_rejects_stale_or_ambiguous_exact_identity_assertions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    message: str,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix=f"exact-identity-{case}",
        )
        operation = fixture.payload.assignments[0]
        payload_updates: dict[str, object] = {}
        operation_updates: dict[str, object] = {}
        if case == "placement_key":
            operation_updates["placement_key"] = "wrong-exact-placement"
        elif case == "target":
            operation_updates["target_component_instance_key"] = (
                "wrong-exact-component-instance"
            )
        elif case == "requirement_version":
            operation_updates["expected_requirement_version"] = (
                operation.expected_requirement_version + 1
            )
        elif case == "contract_version":
            operation_updates["expected_placement_contract_version"] = (
                operation.expected_placement_contract_version + 1
            )
        elif case == "composition_id":
            payload_updates["composition_id"] = fixture.composition.id + 10_000
        elif case == "composition_version":
            payload_updates["expected_composition_version"] = (
                fixture.composition.composition_version + 1
            )
        elif case == "composition_hash":
            payload_updates["expected_composition_source_hash"] = "0" * 64
        else:
            payload_updates["generated_page_id"] = fixture.generated.id + 10_000

        payload = _payload_with(
            fixture,
            [operation.model_copy(update=operation_updates)],
            **payload_updates,
        )
        with pytest.raises(PageMediaPlanningError, match=message):
            assign_media_batch_to_requirements(session, fixture.plan.id, payload)
        _assert_no_batch_mutation(session, fixture)


def test_batch_requires_current_authorization_for_compatible_contract_default_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="missing-current-authorization",
        )
        requirement = fixture.requirements[0]
        original_authorization = fixture.authorizations[0]
        assert original_authorization is not None
        original_authorization.lifecycle_status = "superseded"
        session.add(original_authorization)
        session.commit()

        asset = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=fixture.business.id,
            website_id=fixture.website.id,
            media_key="compatible-default-without-authorization",
            placement_key=requirement.placement_key,
            usage_authorization_mode="contract_default",
        )
        asset = approve_page_media_asset(
            session,
            asset.id,
            expected_website_id=fixture.website.id,
            expected_business_id=fixture.business.id,
            approved_by="Batch Approval Operator",
            expected_media_version=1,
        )
        session.refresh(asset)
        approval = page_media_asset_read(asset).approval_fingerprint
        assert approval is not None
        operation = fixture.payload.assignments[0].model_copy(
            update={
                "image_metadata_id": asset.id,
                "expected_media_version": asset.media_version,
                "expected_asset_checksum_sha256": asset.checksum_sha256,
                "expected_approval_version": asset.approval_version,
                "expected_approval_fingerprint": approval,
                "expected_scoped_authorization_id": 99_999,
                "expected_authorization_version": 1,
                "expected_authorization_fingerprint": "a" * 64,
                "expected_authorization_reuse_policy": "contract_default",
                "expected_authorization_terms": [
                    "representative_nonlocalized"
                ],
            }
        )
        payload = _payload_with(fixture, [operation])

        with pytest.raises(
            PageMediaPlanningError,
            match="requires a current exact scoped media authorization",
        ):
            assign_media_batch_to_requirements(session, fixture.plan.id, payload)
        _assert_no_batch_mutation(
            session,
            fixture,
            expected_authorization_count=3,
        )


def test_status_current_but_live_composition_source_drift_blocks_entire_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="live-source-drift",
        )
        generated = session.get(type(fixture.generated), fixture.generated.id)
        assert generated is not None
        generated.draft_content = {
            **generated.draft_content,
            "live_source_drift_probe": "authoritative source changed",
        }
        session.add(generated)
        session.commit()
        stored = session.get(PageComposition, fixture.composition.id)
        assert stored is not None
        assert stored.status == "current"

        with pytest.raises(
            PageMediaPlanningError,
            match="stale against its live authoritative sources",
        ):
            assign_media_batch_to_requirements(
                session,
                fixture.plan.id,
                fixture.payload,
            )
        _assert_no_batch_mutation(session, fixture)


def test_partial_or_ambiguous_batch_input_is_rejected_by_schema() -> None:
    operation = {
        "media_requirement_id": 1,
        "expected_requirement_version": 1,
        "expected_placement_contract_version": 2,
        "target_component_instance_key": "hero",
        "image_metadata_id": 1,
        "expected_media_version": 1,
        "expected_asset_checksum_sha256": "a" * 64,
        "expected_approval_version": 1,
        "expected_approval_fingerprint": "b" * 64,
        "expected_scoped_authorization_id": 1,
        "expected_authorization_version": 1,
        "expected_authorization_fingerprint": "c" * 64,
        "expected_authorization_reuse_policy": "contract_default",
        "expected_authorization_terms": ["representative_nonlocalized"],
        "canonical_media_role": "hero",
        "assigned_by": "Batch Operator",
        "rationale": "Incomplete because its exact placement key is absent.",
    }
    with pytest.raises(ValidationError, match="placement_key"):
        PageMediaBatchAssignmentOperation.model_validate(operation)
    complete = {**operation, "placement_key": "home-hero"}
    without_target = dict(complete)
    without_target.pop("target_component_instance_key")
    with pytest.raises(ValidationError, match="target_component_instance_key"):
        PageMediaBatchAssignmentOperation.model_validate(without_target)
    with pytest.raises(ValidationError, match="target_component_instance_key"):
        PageMediaBatchAssignmentOperation.model_validate(
            {**complete, "target_component_instance_key": None}
        )
    with pytest.raises(ValidationError, match="target_component_instance_key"):
        PageMediaBatchAssignmentOperation.model_validate(
            {**complete, "target_component_instance_key": ""}
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PageMediaBatchAssignmentOperation.model_validate(
            {**complete, "filename_hint": "hero.webp"}
        )


def test_flo_zone_media_32_is_rejected_by_batch_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="batch-media-32",
        )
        _bind_flo_zone_identity(session, fixture.website)
        _refresh_test_compositions(
            session,
            fixture.plan,
            [(fixture.planned, fixture.generated)],
        )
        asset = fixture.assets[0]
        asset.wordpress_media_id = 32
        session.add(asset)
        session.commit()
        fixture.composition = session.get(PageComposition, fixture.composition.id)
        operation = _operation(
            fixture.planned,
            fixture.requirements[0],
            asset,
            fixture.authorizations[0],
        )
        payload = PageMediaBatchAssignmentRequest(
            website_id=fixture.website.id,
            site_plan_id=fixture.plan.id,
            planned_page_id=fixture.planned.id,
            generated_page_id=fixture.generated.id,
            composition_id=fixture.composition.id,
            expected_composition_version=fixture.composition.composition_version,
            expected_composition_source_hash=fixture.composition.source_hash,
            assignments=[operation],
        )

        with pytest.raises(PageMediaPlanningError, match="excluded"):
            assign_media_batch_to_requirements(session, fixture.plan.id, payload)
        assert session.exec(select(PageImageAssignment)).all() == []


def test_final_item_failure_rolls_back_assignments_authorization_bindings_and_page_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="final-item-rollback",
        )
        before_composition = deepcopy(fixture.composition.model_dump())
        before_authorizations = [
            deepcopy(row.model_dump())
            for row in session.exec(
                select(ScopedMediaAuthorization).order_by(ScopedMediaAuthorization.id)
            ).all()
        ]
        original_bind = media_planning.bind_scoped_media_authorization_to_assignment
        calls = 0

        def fail_final_binding(target_session: Session, **kwargs):
            nonlocal calls
            calls += 1
            if calls == len(fixture.payload.assignments):
                raise ScopedMediaAuthorizationError(
                    "Simulated final assignment authorization failure."
                )
            return original_bind(target_session, **kwargs)

        monkeypatch.setattr(
            media_planning,
            "bind_scoped_media_authorization_to_assignment",
            fail_final_binding,
        )

        with pytest.raises(PageMediaPlanningError, match="Simulated final"):
            assign_media_batch_to_requirements(
                session,
                fixture.plan.id,
                fixture.payload,
            )

        assert calls == 3
        _assert_no_batch_mutation(
            session,
            fixture,
            expected_authorization_count=3,
        )
        restored_composition = session.get(PageComposition, fixture.composition.id)
        assert restored_composition.model_dump() == before_composition
        after_authorizations = [
            row.model_dump()
            for row in session.exec(
                select(ScopedMediaAuthorization).order_by(ScopedMediaAuthorization.id)
            ).all()
        ]
        assert after_authorizations == before_authorizations


def test_simulated_concurrent_unique_conflict_rolls_back_and_reports_reload_guidance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="simulated-concurrent-conflict",
        )
        original_flush = session.flush
        conflict_raised = False

        def conflicting_flush(*args, **kwargs):
            nonlocal conflict_raised
            if not conflict_raised and any(
                isinstance(row, PageImageAssignment) for row in session.new
            ):
                conflict_raised = True
                raise IntegrityError(
                    "INSERT pageimageassignment",
                    {},
                    RuntimeError("simulated unique-index race"),
                )
            return original_flush(*args, **kwargs)

        monkeypatch.setattr(session, "flush", conflicting_flush)

        with pytest.raises(PageMediaPlanningError, match="Concurrent.*reload"):
            assign_media_batch_to_requirements(
                session,
                fixture.plan.id,
                fixture.payload,
            )

        assert conflict_raised is True
        _assert_no_batch_mutation(session, fixture)


def test_requirement_only_asset_reuse_is_rejected_for_two_batch_requirements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="requirement-only-reuse",
        )
        first, second = fixture.requirements[:2]
        shared = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=fixture.business.id,
            website_id=fixture.website.id,
            media_key="requirement-only-shared",
            placement_key=first.placement_key,
            usage_authorization_mode="scoped_required",
            required_authorization_terms=["representative_nonlocalized"],
        )
        shared.permitted_placement_keys = [
            first.placement_key,
            second.placement_key,
        ]
        session.add(shared)
        session.commit()
        shared = approve_page_media_asset(
            session,
            shared.id,
            expected_website_id=fixture.website.id,
            expected_business_id=fixture.business.id,
            approved_by="Batch Approval Operator",
            expected_media_version=1,
        )
        approval = page_media_asset_read(shared).approval_fingerprint
        authorization_read = create_scoped_media_authorization(
            session,
            fixture.plan.id,
            ScopedMediaAuthorizationRequest(
                media_requirement_id=first.id,
                expected_requirement_version=first.version,
                expected_placement_contract_version=first.contract_version,
                image_metadata_id=shared.id,
                expected_media_version=shared.media_version,
                expected_asset_checksum_sha256=shared.checksum_sha256,
                expected_approval_version=shared.approval_version,
                expected_approval_fingerprint=approval,
                reuse_policy="requirement_only",
                authorization_terms=[
                    "representative_nonlocalized",
                    "requirement_only_usage",
                ],
                authorized_by="Restriction Operator",
                authorization_rationale="Restrict this exact asset to one requirement.",
                expected_current_authorization_fingerprint=(
                    fixture.authorizations[0].authorization_fingerprint
                ),
            ),
        )
        authorization = session.get(ScopedMediaAuthorization, authorization_read.id)
        first_operation = _operation(
            fixture.planned,
            first,
            shared,
            authorization,
        )
        second_operation = _operation(
            fixture.planned,
            second,
            shared,
            fixture.authorizations[1],
        )
        payload = _payload_with(
            fixture,
            [first_operation, second_operation],
        )

        with pytest.raises(
            PageMediaPlanningError,
            match="duplicates a governed asset whose exact authorization prohibits reuse",
        ):
            assign_media_batch_to_requirements(session, fixture.plan.id, payload)
        assert session.exec(select(PageImageAssignment)).all() == []


def test_existing_standalone_assignment_behavior_remains_valid_and_batch_detects_stale_expectation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="standalone-compatible",
        )
        requirement = fixture.requirements[0]
        asset = fixture.assets[0]
        workspace = assign_media_to_requirement(
            session,
            fixture.plan.id,
            requirement.id,
            PageMediaAssignmentRequest(
                image_metadata_id=asset.id,
                assigned_by="Standalone Assignment Operator",
                rationale="Preserve the legitimate one-assignment workflow.",
                expected_requirement_version=requirement.version,
                display_preset="hero_desktop",
            ),
        )
        assert workspace.site_plan_id == fixture.plan.id
        active = session.exec(
            select(PageImageAssignment).where(
                PageImageAssignment.media_requirement_id == requirement.id,
                PageImageAssignment.status == "active",
            )
        ).one()
        assert active.assignment_version == 1
        assert active.display_preset == "hero_desktop"

        _refresh_test_compositions(
            session,
            fixture.plan,
            [(fixture.planned, fixture.generated)],
        )
        composition = session.get(PageComposition, fixture.composition.id)
        rebound_authorization = current_scoped_media_authorization(
            session,
            requirement.id,
        )
        assert rebound_authorization is not None
        stale_operation = _operation(
            fixture.planned,
            requirement,
            asset,
            rebound_authorization,
        )
        stale_expectation = PageMediaBatchAssignmentRequest(
            website_id=fixture.website.id,
            site_plan_id=fixture.plan.id,
            planned_page_id=fixture.planned.id,
            generated_page_id=fixture.generated.id,
            composition_id=composition.id,
            expected_composition_version=composition.composition_version,
            expected_composition_source_hash=composition.source_hash,
            assignments=[stale_operation],
        )
        with pytest.raises(
            PageMediaPlanningError,
            match="Current governed assignment identity or version changed",
        ):
            assign_media_batch_to_requirements(
                session,
                fixture.plan.id,
                stale_expectation,
            )
        assert len(session.exec(select(PageImageAssignment)).all()) == 1


def test_identical_current_batch_is_a_true_noop_after_single_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="idempotent-noop",
        )
        first = assign_media_batch_to_requirements(
            session,
            fixture.plan.id,
            fixture.payload,
        )
        assert len(first.assignments) == 3
        _refresh_test_compositions(
            session,
            fixture.plan,
            [(fixture.planned, fixture.generated)],
        )
        composition = session.get(PageComposition, fixture.composition.id)
        assert composition is not None
        assert composition.status == "current"
        before_assignments = [
            row.model_dump()
            for row in session.exec(
                select(PageImageAssignment).order_by(PageImageAssignment.id)
            ).all()
        ]
        before_authorizations = [
            row.model_dump()
            for row in session.exec(
                select(ScopedMediaAuthorization).order_by(
                    ScopedMediaAuthorization.id
                )
            ).all()
        ]
        repeated_operations: list[PageMediaBatchAssignmentOperation] = []
        for requirement, asset in zip(
            fixture.requirements,
            fixture.assets,
            strict=True,
        ):
            active = session.exec(
                select(PageImageAssignment).where(
                    PageImageAssignment.media_requirement_id == requirement.id,
                    PageImageAssignment.status == "active",
                )
            ).one()
            authorization = current_scoped_media_authorization(
                session,
                requirement.id,
            )
            assert authorization is not None
            repeated_operations.append(
                _operation(
                    fixture.planned,
                    requirement,
                    asset,
                    authorization,
                ).model_copy(
                    update={
                        "expected_current_assignment_id": active.id,
                        "expected_current_assignment_version": (
                            active.assignment_version
                        ),
                    }
                )
            )
        payload = PageMediaBatchAssignmentRequest(
            website_id=fixture.website.id,
            site_plan_id=fixture.plan.id,
            planned_page_id=fixture.planned.id,
            generated_page_id=fixture.generated.id,
            composition_id=composition.id,
            expected_composition_version=composition.composition_version,
            expected_composition_source_hash=composition.source_hash,
            assignments=repeated_operations,
        )
        monkeypatch.setattr(
            media_planning,
            "_mark_composition_stale",
            lambda *_args, **_kwargs: pytest.fail(
                "An identical current batch must not mark composition stale."
            ),
        )

        repeated = assign_media_batch_to_requirements(
            session,
            fixture.plan.id,
            payload,
        )

        assert repeated.composition_status == "current"
        assert [row.id for row in repeated.assignments] == [
            row["id"] for row in before_assignments
        ]
        assert [
            row.model_dump()
            for row in session.exec(
                select(PageImageAssignment).order_by(PageImageAssignment.id)
            ).all()
        ] == before_assignments
        assert [
            row.model_dump()
            for row in session.exec(
                select(ScopedMediaAuthorization).order_by(
                    ScopedMediaAuthorization.id
                )
            ).all()
        ] == before_authorizations


def test_duplicate_asset_reuse_succeeds_when_two_exact_page_authorizations_permit_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="permitted-page-reuse",
        )
        first, second = fixture.requirements[:2]
        shared = _create_asset(
            session,
            monkeypatch,
            tmp_path,
            business_id=fixture.business.id,
            website_id=fixture.website.id,
            media_key="permitted-page-shared",
            placement_key=first.placement_key,
            usage_authorization_mode="scoped_required",
            required_authorization_terms=["representative_nonlocalized"],
        )
        shared.permitted_placement_keys = [
            first.placement_key,
            second.placement_key,
        ]
        session.add(shared)
        session.commit()
        shared = approve_page_media_asset(
            session,
            shared.id,
            expected_website_id=fixture.website.id,
            expected_business_id=fixture.business.id,
            approved_by="Batch Approval Operator",
            expected_media_version=1,
        )
        session.refresh(shared)
        approval = page_media_asset_read(shared).approval_fingerprint
        assert approval is not None
        authorizations: list[ScopedMediaAuthorization] = []
        for requirement, prior in zip(
            (first, second),
            fixture.authorizations[:2],
            strict=True,
        ):
            assert prior is not None
            created = create_scoped_media_authorization(
                session,
                fixture.plan.id,
                ScopedMediaAuthorizationRequest(
                    media_requirement_id=requirement.id,
                    expected_requirement_version=requirement.version,
                    expected_placement_contract_version=(
                        requirement.contract_version
                    ),
                    image_metadata_id=shared.id,
                    expected_media_version=shared.media_version,
                    expected_asset_checksum_sha256=shared.checksum_sha256,
                    expected_approval_version=shared.approval_version,
                    expected_approval_fingerprint=approval,
                    reuse_policy="page_only",
                    authorization_terms=[
                        "representative_nonlocalized",
                        "page_only_usage",
                    ],
                    authorized_by="Page Reuse Operator",
                    authorization_rationale=(
                        "Permit this asset across two exact requirements on one page."
                    ),
                    expected_current_authorization_fingerprint=(
                        prior.authorization_fingerprint
                    ),
                ),
            )
            authorization = session.get(ScopedMediaAuthorization, created.id)
            assert authorization is not None
            authorizations.append(authorization)

        payload = _payload_with(
            fixture,
            [
                _operation(fixture.planned, first, shared, authorizations[0]),
                _operation(fixture.planned, second, shared, authorizations[1]),
            ],
        )
        result = assign_media_batch_to_requirements(
            session,
            fixture.plan.id,
            payload,
        )

        assert len(result.assignments) == 2
        assert {row.image_metadata_id for row in result.assignments} == {
            shared.id
        }
        assert result.composition_status == "stale"


def test_legacy_requirement_read_uses_role_independent_original_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _prepare_batch(
            session,
            monkeypatch,
            tmp_path,
            suffix="legacy-requirement-read",
        )
        session.refresh(fixture.requirements[0])
        legacy = fixture.requirements[0].model_copy(
            update={"contract_version": 1}
        )

        serialized = media_planning._requirement_read(legacy)

        assert serialized.contract_version == 1
        assert serialized.effective_display_preset == "original"
