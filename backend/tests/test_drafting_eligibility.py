import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.backup import export_backup, load_backup, restore_backup
from app.models import (
    Brand,
    Business,
    City,
    County,
    DraftingEligibilityAssessment,
    DraftingEligibilityDisposition,
    GeneratedPage,
    PlannedPage,
    PlanningRecord,
    PreDraftDistinctnessBrief,
    Service,
    SitePlan,
    SupportingPageAuthorization,
    Website,
    WebsiteCityCoverageDecision,
    WebsiteCountyCoverageDecision,
    WebsiteServiceCityCoverageDecision,
    WebsiteServiceCoverageDecision,
)
from app.schemas.drafting_eligibility import (
    CandidateDraftInput,
    EligibilityDispositionUpdate,
)
from app.schemas.site_coverage import CoverageDecisionUpdate
from app.schemas.entities import GeneratedPageUpdate
from app.schemas.page_editor import ManualDraftSaveRequest
from app.services.drafting_eligibility import (
    DraftingEligibilityError,
    assess_site_plan,
    read_manifest,
    record_disposition,
    require_effective_drafting_eligibility,
    validate_candidate_drafts,
)
from app.services.site_coverage import decide_supporting_page
from app.services.crud import update_record
from app.services.draft_generation import DraftGenerationError, generate_page_draft
from app.services.page_editor import save_manual_draft
from app.services.planned_page_drafting import (
    PlannedPageDraftingError,
    draft_planned_page,
)


def _scope(session: Session, suffix: str = "one"):
    business = Business(
        company_name=f"Company {suffix}",
        business_type="Pest control",
        state="FL",
    )
    session.add(business)
    session.flush()
    brand = Brand(business_id=business.id, brand_name=f"Brand {suffix}")
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name=f"Website {suffix}",
        domain=f"{suffix}.example.test",
        public_url=f"https://{suffix}.example.test/",
    )
    service = Service(
        business_id=business.id,
        service_name="Termite Control",
        service_slug=f"termite-control-{suffix}",
    )
    county = County(state="FL", county_name=f"County {suffix}")
    session.add_all([website, service, county])
    session.flush()
    city = City(
        county_id=county.id,
        city_name=f"City {suffix}",
        city_slug=f"city-{suffix}",
        notes="Approved local housing and service-access context.",
    )
    session.add(city)
    session.flush()
    plan = SitePlan(
        website_id=website.id, plan_key="primary", plan_name="Primary"
    )
    session.add(plan)
    session.flush()
    session.add_all(
        [
            WebsiteServiceCoverageDecision(
                website_id=website.id,
                service_id=service.id,
                status="included",
                decided_by="operator",
            ),
            WebsiteCountyCoverageDecision(
                website_id=website.id,
                county_id=county.id,
                status="included",
                page_appropriate=False,
                decided_by="operator",
            ),
            WebsiteCityCoverageDecision(
                website_id=website.id,
                city_id=city.id,
                status="included",
                decided_by="operator",
            ),
            WebsiteServiceCityCoverageDecision(
                website_id=website.id,
                service_id=service.id,
                city_id=city.id,
                status="included",
                decided_by="operator",
            ),
        ]
    )
    page = PlannedPage(
        website_id=website.id,
        site_plan_id=plan.id,
        page_type="city_service",
        working_name=f"Termite Control in City {suffix}",
        intended_slug=f"termite-control-city-{suffix}",
        service_id=service.id,
        city_id=city.id,
        county_id=county.id,
    )
    session.add(page)
    session.flush()
    session.add(
        PlanningRecord(
            planned_page_id=page.id,
            generated_answers={
                "page_purpose": "Explain approved service.",
                "relationships": ["service", "city"],
                "required_business_facts": ["company", "service area"],
            },
            missing_information=[],
        )
    )
    session.commit()
    return website, plan, page


def test_explicit_coverage_page_is_assessed_and_batch_eligible():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, plan, page = _scope(session)
        manifest = assess_site_plan(session, plan.id)
        item = next(
            item for item in manifest.assessments
            if item.planned_page_id == page.id
        )
        assert item.status == "eligible"
        assert item.effective_eligible is True
        assert manifest.batch_preview_ready is False  # required core pages remain missing


def test_historical_unapproved_page_fails_closed():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, _ = _scope(session)
        extra = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="city_service",
            working_name="Historical",
            intended_slug="historical",
        )
        session.add(extra)
        session.flush()
        session.add(PlanningRecord(planned_page_id=extra.id))
        session.commit()
        manifest = assess_site_plan(session, plan.id)
        item = next(
            item for item in manifest.assessments
            if item.planned_page_id == extra.id
        )
        assert item.status == "excluded_by_coverage"
        assert item.effective_eligible is False


def test_coverage_version_change_makes_assessment_stale():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, page = _scope(session)
        assess_site_plan(session, plan.id)
        decision = session.exec(
            select(WebsiteServiceCityCoverageDecision).where(
                WebsiteServiceCityCoverageDecision.website_id == website.id
            )
        ).one()
        decision.decision_version += 1
        session.add(decision)
        session.commit()
        item = next(
            item for item in read_manifest(session, plan.id).assessments
            if item.planned_page_id == page.id
        )
        assert item.status == "stale_assessment"
        assert item.effective_eligible is False


def test_operator_exception_is_separate_and_cannot_override_missing_facts():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, plan, page = _scope(session)
        record = session.exec(
            select(PlanningRecord).where(
                PlanningRecord.planned_page_id == page.id
            )
        ).one()
        record.missing_information = ["Approved license fact"]
        session.add(record)
        session.commit()
        assessment = next(
            item for item in assess_site_plan(session, plan.id).assessments
            if item.planned_page_id == page.id
        )
        try:
            record_disposition(
                session,
                assessment.id,
                EligibilityDispositionUpdate(
                    decision="exception_approved",
                    rationale="Proceed anyway",
                    decided_by="operator",
                    accepted_exception=True,
                ),
            )
        except DraftingEligibilityError:
            pass
        else:
            raise AssertionError("Missing approved facts must remain fail-closed")
        assert session.exec(select(DraftingEligibilityDisposition)).first() is None


def test_cross_website_pages_are_not_semantically_compared():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, plan_one, page_one = _scope(session, "one")
        _, plan_two, page_two = _scope(session, "two")
        for page, title in ((page_one, "Same"), (page_two, "Same")):
            generated = GeneratedPage(
                business_id=session.get(Website, page.website_id).business_id,
                website_id=page.website_id,
                page_type="city_service",
                page_title=title,
                page_slug=page.intended_slug,
                h1=title,
                content_body="Identical approved body",
                draft_content={"title": title, "h1": title},
            )
            session.add(generated)
            session.flush()
            page.generated_page_id = generated.id
            session.add(page)
        session.commit()
        one = next(
            item for item in assess_site_plan(session, plan_one.id).assessments
            if item.planned_page_id == page_one.id
        )
        assert one.semantic_findings == []
        assert plan_two.id != plan_one.id


def test_same_website_duplicates_report_pairs_sections_and_intent():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, first = _scope(session)
        second = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="city_service",
            working_name="Duplicate candidate",
            intended_slug="duplicate-candidate",
            service_id=first.service_id,
            city_id=first.city_id,
            county_id=first.county_id,
        )
        session.add(second)
        session.flush()
        session.add(PlanningRecord(planned_page_id=second.id))
        for page in (first, second):
            generated = GeneratedPage(
                business_id=website.business_id,
                website_id=website.id,
                service_id=page.service_id,
                city_id=page.city_id,
                county_id=page.county_id,
                page_type="city_service",
                page_title="Same search intent",
                page_slug=page.intended_slug,
                h1="Same service heading",
                content_body="Identical approved body",
                draft_content={
                    "title": "Same search intent",
                    "h1": "Same service heading",
                    "intro": "Identical introduction",
                    "process_section": "Identical process",
                },
            )
            session.add(generated)
            session.flush()
            page.generated_page_id = generated.id
            session.add(page)
        session.commit()
        item = next(
            item for item in assess_site_plan(session, plan.id).assessments
            if item.planned_page_id == first.id
        )
        kinds = {finding["kind"] for finding in item.semantic_findings}
        assert {
            "exact_duplicate",
            "shared_section_ratio",
            "title_h1_similarity",
            "search_intent_overlap",
            "likely_cannibalization",
        } <= kinds
        assert all(
            finding.get("target_planned_page_id") == second.id
            for finding in item.semantic_findings
        )


def test_backup_round_trip_preserves_assessment_and_operator_provenance(tmp_path):
    source = create_engine("sqlite://")
    SQLModel.metadata.create_all(source)
    with Session(source) as session:
        _, plan, page = _scope(session)
        assessment = next(
            item for item in assess_site_plan(session, plan.id).assessments
            if item.planned_page_id == page.id
        )
        record_disposition(
            session,
            assessment.id,
            EligibilityDispositionUpdate(
                decision="accepted",
                rationale="Reviewed approved sources.",
                decided_by="operator@example.test",
            ),
        )
        exported = export_backup(session, backup_dir=tmp_path)
    payload = load_backup(tmp_path / exported["file_name"])
    assert payload["metadata"]["version"] == "0.58"
    assert len(payload["data"]["drafting_eligibility_assessments"]) == 1
    assert len(payload["data"]["drafting_eligibility_dispositions"]) == 1

    target = create_engine("sqlite://")
    SQLModel.metadata.create_all(target)
    with Session(target) as session:
        restore_backup(session, tmp_path / exported["file_name"])
        restored_disposition = session.exec(
            select(DraftingEligibilityDisposition)
        ).one()
        restored_assessment = session.get(
            DraftingEligibilityAssessment,
            restored_disposition.assessment_id,
        )
        assert restored_assessment is not None
        assert restored_assessment.status == "eligible"
        assert restored_disposition.rationale == "Reviewed approved sources."
        assert restored_disposition.decided_by == "operator@example.test"


def test_missing_and_stale_assessments_fail_the_authoritative_gate():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, page = _scope(session, "gate")
        with pytest.raises(DraftingEligibilityError, match="no pre-draft"):
            require_effective_drafting_eligibility(session, page.id)
        assess_site_plan(session, plan.id)
        require_effective_drafting_eligibility(session, page.id)
        decision = session.exec(
            select(WebsiteServiceCityCoverageDecision).where(
                WebsiteServiceCityCoverageDecision.website_id == website.id
            )
        ).one()
        decision.decision_version += 1
        session.add(decision)
        session.commit()
        with pytest.raises(DraftingEligibilityError, match="stale"):
            require_effective_drafting_eligibility(session, page.id)


def test_ordinary_planned_page_drafting_cannot_bypass_missing_gate():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, _, page = _scope(session, "ordinary-path")
        with pytest.raises(PlannedPageDraftingError, match="no pre-draft"):
            draft_planned_page(
                session,
                page.id,
                expected_website_id=website.id,
            )


def test_direct_generation_editing_and_generic_updates_cannot_bypass_gate():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, _, page = _scope(session, "all-paths")
        generated = GeneratedPage(
            business_id=website.business_id,
            website_id=website.id,
            service_id=page.service_id,
            city_id=page.city_id,
            county_id=page.county_id,
            page_type="city_service",
            page_title="Protected draft",
            page_slug=page.intended_slug,
            status="draft",
            draft_content={"title": "Protected draft"},
        )
        session.add(generated)
        session.flush()
        page.generated_page_id = generated.id
        session.add(page)
        session.commit()

        with pytest.raises(DraftGenerationError, match="no pre-draft"):
            generate_page_draft(session, generated.id)
        with pytest.raises(HTTPException, match="no pre-draft"):
            save_manual_draft(
                session,
                generated.id,
                ManualDraftSaveRequest(draft={}),
            )
        with pytest.raises(HTTPException, match="no pre-draft"):
            update_record(
                session,
                GeneratedPage,
                generated.id,
                GeneratedPageUpdate(page_title="Blocked change"),
            )


def test_supporting_page_authorization_retains_provenance_and_is_not_implicit(
    tmp_path,
):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, _ = _scope(session, "supporting")
        supporting = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="informational",
            working_name="Approved preparation guide",
            intended_slug="preparation-guide",
        )
        session.add(supporting)
        session.flush()
        session.add(
            PlanningRecord(
                planned_page_id=supporting.id,
                generated_answers={"purpose": "Explain approved preparation facts."},
                missing_information=[],
            )
        )
        session.commit()
        before = assess_site_plan(session, plan.id)
        item = next(
            row for row in before.assessments
            if row.planned_page_id == supporting.id
        )
        assert item.status == "deferred"
        decision = decide_supporting_page(
            session,
            plan.id,
            supporting.id,
            CoverageDecisionUpdate(
                status="included",
                rationale="Required supporting page in the approved Site Plan.",
                decided_by="operator@example.test",
            ),
        )
        assert decision.decision_version == 1
        assert decision.decided_by == "operator@example.test"
        assert decision.rationale
        assert session.exec(select(SupportingPageAuthorization)).one()
        after = assess_site_plan(session, plan.id)
        item = next(
            row for row in after.assessments
            if row.planned_page_id == supporting.id
        )
        assert item.status == "eligible"
        exported = export_backup(session, backup_dir=tmp_path)
        payload = load_backup(tmp_path / exported["file_name"])
        assert len(payload["data"]["supporting_page_authorizations"]) == 1
        assert len(payload["data"]["pre_draft_distinctness_briefs"]) >= 1

        target = create_engine("sqlite://")
        SQLModel.metadata.create_all(target)
        with Session(target) as target_session:
            restore_backup(target_session, tmp_path / exported["file_name"])
            assert target_session.exec(
                select(SupportingPageAuthorization)
            ).one().decided_by == "operator@example.test"
            assert target_session.exec(
                select(PreDraftDistinctnessBrief)
            ).first() is not None


def test_coverage_relationships_alone_do_not_satisfy_local_value():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, plan, page = _scope(session, "no-local-value")
        city = session.get(City, page.city_id)
        city.notes = None
        session.add(city)
        session.commit()
        manifest = assess_site_plan(session, plan.id)
        item = next(
            row for row in manifest.assessments
            if row.planned_page_id == page.id
        )
        assert item.status == "insufficient_local_value"
        assert item.local_value_findings == []
        assert "Coverage relationships" in item.reasons[0]


def test_predraft_semantic_findings_are_explainable_and_website_scoped():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, page = _scope(session, "semantic")
        record = session.exec(
            select(PlanningRecord).where(
                PlanningRecord.planned_page_id == page.id
            )
        ).one()
        record.operator_overrides = {
            "search_intent": "city service termite control",
            "page_specific_value": ["Approved local access context."],
        }
        session.add(record)
        session.commit()
        manifest = assess_site_plan(session, plan.id)
        item = next(
            row for row in manifest.assessments
            if row.planned_page_id == page.id
        )
        assert all(
            finding.get("explanation")
            for finding in item.semantic_findings
        )

        _, other_plan, other_page = _scope(session, "other-website")
        other_manifest = assess_site_plan(session, other_plan.id)
        other_item = next(
            row for row in other_manifest.assessments
            if row.planned_page_id == other_page.id
        )
        assert all(
            finding.get("target_planned_page_id") != page.id
            for finding in other_item.semantic_findings
        )


def test_batch_manifest_classifies_every_inventory_item_and_candidates_are_read_only():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, plan, page = _scope(session, "manifest")
        manifest = assess_site_plan(session, plan.id)
        counts = manifest.batch_manifest.counts.model_dump()
        assert len(manifest.batch_manifest.items) == sum(counts.values())
        assert any(
            item.planned_page_id == page.id
            and item.classification == "eligible"
            for item in manifest.batch_manifest.items
        )
        result = validate_candidate_drafts(
            session,
            plan.id,
            [
                CandidateDraftInput(
                    planned_page_id=page.id,
                    draft_content={"schema_version": "legacy-city-service-v1"},
                )
            ],
        )
        assert result.valid is False
        assert session.exec(select(GeneratedPage)).all() == []
