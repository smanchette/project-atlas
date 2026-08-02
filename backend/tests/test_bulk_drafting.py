from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Brand,
    Business,
    City,
    County,
    DraftingEligibilityAssessment,
    GeneratedPage,
    PlannedPage,
    Service,
    SitePlan,
    Website,
    WebsiteDraftGenerationItem,
    WebsiteDraftGenerationRun,
    WebsiteIdentity,
)
from app.db.backup import export_backup, load_backup, restore_backup
from app.db.seed import FLO_ZONE_COMPANY_NAME, seed_database
from app.schemas.site_coverage import (
    CountyCoverageDecisionUpdate,
    CoverageDecisionUpdate,
)
from app.services.bulk_drafting import (
    BulkDraftingError,
    read_generation_run,
    resume_generation,
    start_or_resume_generation,
)
import app.services.bulk_drafting as bulk_drafting_service
from app.services.drafting_eligibility import assess_site_plan, read_manifest
from app.services.site_connections import ensure_site_connection_foundation
from app.services.site_coverage import (
    decide_city,
    decide_county,
    decide_service,
    decide_service_city,
    ensure_coverage_foundation,
    reconcile_expected_inventory,
)


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_bulk_drafting_routes_are_local_site_plan_capabilities():
    from app.main import app

    methods_by_path = {
        route.path: set(route.methods or [])
        for route in app.routes
        if hasattr(route, "methods")
    }
    assert methods_by_path[
        "/api/site-plans/{plan_id}/draft-generation/start"
    ] == {"POST"}
    assert methods_by_path[
        "/api/site-plans/draft-generation/runs/{run_id}/resume"
    ] == {"POST"}
    assert methods_by_path[
        "/api/site-plans/draft-generation/runs/{run_id}"
    ] == {"GET"}
    assert methods_by_path[
        "/api/site-plans/{plan_id}/draft-generation/runs"
    ] == {"GET"}


def _scope(session: Session, label: str):
    suffix = uuid4().hex[:8]
    business = Business(
        company_name=f"{label} Company {suffix}",
        business_type="Pest control",
        phone="407-555-0100",
        email=f"{suffix}@example.test",
        main_city="Orlando",
        state="FL",
        description="Approved company description and customer service facts.",
        license_number=f"LIC-{suffix}",
        certified_operator="Approved Operator",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name=f"{label} Brand {suffix}",
        description="Approved brand trust information.",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name=f"{label} Website {suffix}",
        domain=f"{label.lower()}-{suffix}.example.test",
        public_url=f"https://{label.lower()}-{suffix}.example.test/",
        configuration={"market_state_codes": ["FL"]},
        status="active",
    )
    session.add(website)
    session.flush()
    session.add(
        WebsiteIdentity(
            website_id=website.id,
            display_name=brand.brand_name,
            status="approved",
        )
    )
    service = Service(
        business_id=business.id,
        service_name=f"Termite Control {suffix}",
        service_slug=f"termite-control-{suffix}",
        short_description="Approved termite inspection and treatment service.",
        long_description=(
            "Approved details about inspection, treatment options, and follow-up."
        ),
        status="active",
    )
    county = County(
        county_name=f"Orange {suffix}",
        state="FL",
        status="active",
    )
    session.add_all([service, county])
    session.flush()
    city = City(
        county_id=county.id,
        city_name=f"Orlando {suffix}",
        city_slug=f"orlando-{suffix}",
        state="FL",
        notes="Approved local housing and service-access context.",
        status="active",
    )
    session.add(city)
    session.flush()
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name=f"{label} Primary Site Plan",
    )
    session.add(plan)
    session.flush()
    ensure_site_connection_foundation(session, plan, commit=False)
    ensure_coverage_foundation(session, plan, commit=False)
    session.commit()

    operator = "batch-reviewer@example.test"
    decide_service(
        session,
        plan.id,
        service.id,
        CoverageDecisionUpdate(
            status="included",
            rationale="Approved Website service.",
            decided_by=operator,
        ),
    )
    decide_county(
        session,
        plan.id,
        county.id,
        CountyCoverageDecisionUpdate(
            status="included",
            page_appropriate=True,
            rationale="Approved service area; County drafting remains deferred.",
            decided_by=operator,
        ),
    )
    decide_city(
        session,
        plan.id,
        city.id,
        CoverageDecisionUpdate(
            status="included",
            rationale="Approved service city.",
            decided_by=operator,
        ),
    )
    decide_service_city(
        session,
        plan.id,
        service.id,
        city.id,
        CoverageDecisionUpdate(
            status="included",
            rationale="Approved exact Service × City combination.",
            decided_by=operator,
        ),
    )
    reconcile_expected_inventory(session, plan.id)
    manifest = assess_site_plan(session, plan.id)
    return website, plan, manifest


def test_batch_generation_resumes_and_is_idempotent_without_replacing_drafts():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, manifest = _scope(session, "Resume")
        assert manifest.batch_manifest.counts.eligible >= 2

        first = start_or_resume_generation(
            session,
            plan.id,
            website_id=website.id,
            draft_limit=1,
        )
        assert first.status == "interrupted"
        assert first.counts.generated == 1
        first_generated = next(
            item for item in first.items if item.outcome == "generated"
        )
        generated = session.get(
            GeneratedPage, first_generated.generated_page_id
        )
        assert generated is not None
        preserved = (
            generated.id,
            generated.updated_at,
            generated.draft_content,
            generated.content_body,
        )

        completed = resume_generation(
            session,
            first.id,
            website_id=website.id,
        )
        assert completed.status in {"completed", "completed_with_errors"}
        assert completed.counts.generated >= 2
        generated = session.get(GeneratedPage, preserved[0])
        assert generated is not None
        assert (
            generated.id,
            generated.updated_at,
            generated.draft_content,
            generated.content_body,
        ) == preserved

        repeated = start_or_resume_generation(
            session,
            plan.id,
            website_id=website.id,
        )
        assert repeated.counts.generated == 0
        assert repeated.counts.already_drafted >= completed.counts.generated
        assert len(session.exec(select(GeneratedPage)).all()) == (
            completed.counts.generated + completed.counts.already_drafted
        )


def test_manifest_identity_binds_the_current_assessment_version():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        _, plan, manifest = _scope(session, "Assessment Binding")
        original_hash, _ = bulk_drafting_service._manifest_identity(manifest)
        assessment = session.exec(
            select(DraftingEligibilityAssessment).where(
                DraftingEligibilityAssessment.site_plan_id == plan.id
            )
        ).first()
        assert assessment is not None
        assessment.assessed_at += timedelta(microseconds=1)
        session.add(assessment)
        session.commit()

        refreshed = read_manifest(session, plan.id)
        refreshed_hash, snapshot = bulk_drafting_service._manifest_identity(refreshed)
        assert refreshed_hash != original_hash
        bound_item = next(
            item
            for item in snapshot["items"]
            if item["planned_page_id"] == assessment.planned_page_id
        )
        assert bound_item["assessment_binding"]["assessed_at"] == (
            assessment.assessed_at.isoformat()
        )


def test_batch_manifest_skips_noneligible_and_preserves_existing_draft():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, _ = _scope(session, "Preserve")
        home = session.exec(
            select(PlannedPage).where(
                PlannedPage.site_plan_id == plan.id,
                PlannedPage.page_type == "home",
            )
        ).one()
        existing = GeneratedPage(
            business_id=website.business_id,
            website_id=website.id,
            page_type="home",
            page_title="Preserved Home",
            page_slug=home.intended_slug,
            h1="Preserved Home",
            content_body="<h1>Preserved Home</h1>",
            draft_content={
                "title": "Preserved Home",
                "h1": "Preserved Home",
                "sections": [],
            },
            generation_status="generated",
        )
        session.add(existing)
        session.flush()
        home.generated_page_id = existing.id
        session.add(home)
        session.commit()
        assess_site_plan(session, plan.id)
        session.refresh(existing)
        before = existing.model_dump()

        result = start_or_resume_generation(
            session,
            plan.id,
            website_id=website.id,
        )
        home_item = next(
            item for item in result.items if item.planned_page_id == home.id
        )
        assert home_item.outcome == "already_drafted"
        assert session.get(GeneratedPage, existing.id).model_dump() == before
        assert result.counts.already_drafted == 1
        assert result.counts.unsupported == 0
        assert not any(
            item.page_type == "county" and item.outcome == "unsupported"
            for item in result.items
        )
        assert all(
            item.generated_page_id is None
            for item in result.items
            if item.outcome
            in {
                "blocked",
                "deferred",
                "excluded",
                "stale",
                "consolidation_recommended",
                "unsupported",
                "error",
            }
        )


def test_batch_generation_is_strictly_website_scoped():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website_one, plan_one, _ = _scope(session, "One")
        website_two, plan_two, _ = _scope(session, "Two")
        with pytest.raises(BulkDraftingError, match="selected Website"):
            start_or_resume_generation(
                session,
                plan_one.id,
                website_id=website_two.id,
            )
        one = start_or_resume_generation(
            session,
            plan_one.id,
            website_id=website_one.id,
            draft_limit=1,
        )
        two = start_or_resume_generation(
            session,
            plan_two.id,
            website_id=website_two.id,
            draft_limit=1,
        )
        assert one.website_id != two.website_id
        assert {
            item.website_id
            for item in session.exec(
                select(WebsiteDraftGenerationItem).where(
                    WebsiteDraftGenerationItem.run_id == one.id
                )
            ).all()
        } == {website_one.id}
        assert all(
            page.website_id == website_one.id
            for page in session.exec(
                select(GeneratedPage).where(
                    GeneratedPage.id.in_(
                        [
                            item.generated_page_id
                            for item in one.items
                            if item.generated_page_id is not None
                        ]
                    )
                )
            ).all()
        )


def test_read_progress_reports_deterministic_counts_and_duration():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, manifest = _scope(session, "Progress")
        result = start_or_resume_generation(
            session,
            plan.id,
            website_id=website.id,
            draft_limit=1,
        )
        report = read_generation_run(session, result.id)
        assert report.counts.expected == len(
            manifest.batch_manifest.items
        )
        assert report.counts.eligible == manifest.batch_manifest.counts.eligible
        assert report.processed_count + sum(
            item.outcome == "pending" for item in report.items
        ) == report.progress_total
        assert report.duration_ms is not None
        assert report.duration_ms >= 0
        assert report.progress_message.startswith("Paused after")


def test_one_page_error_is_reported_and_does_not_stop_remaining_generation(
    monkeypatch,
):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, manifest = _scope(session, "Continue")
        eligible_ids = [
            item.planned_page_id
            for item in manifest.batch_manifest.items
            if item.classification == "eligible"
            and item.planned_page_id is not None
        ]
        assert len(eligible_ids) >= 2
        fail_id = eligible_ids[0]
        original = bulk_drafting_service.draft_planned_page

        def fail_one_page(*args, **kwargs):
            if args[1] == fail_id:
                raise RuntimeError("simulated isolated page failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(
            bulk_drafting_service, "draft_planned_page", fail_one_page
        )
        result = start_or_resume_generation(
            session,
            plan.id,
            website_id=website.id,
        )
        failed = next(
            item for item in result.items if item.planned_page_id == fail_id
        )
        assert result.status == "completed_with_errors"
        assert failed.outcome == "error"
        assert "simulated isolated page failure" in " ".join(failed.reasons)
        assert result.counts.generated >= 1


def test_backup_round_trip_preserves_resumable_run_and_item_bindings(tmp_path):
    source = _engine()
    SQLModel.metadata.create_all(source)
    with Session(source) as session:
        website, plan, _ = _scope(session, "Backup")
        run = start_or_resume_generation(
            session,
            plan.id,
            website_id=website.id,
            draft_limit=1,
        )
        exported = export_backup(session, backup_dir=tmp_path)
    payload = load_backup(tmp_path / exported["file_name"])
    assert payload["metadata"]["version"] == "0.50"
    assert len(payload["data"]["website_draft_generation_runs"]) == 1
    assert len(payload["data"]["website_draft_generation_items"]) == (
        run.counts.expected
    )

    target = _engine()
    SQLModel.metadata.create_all(target)
    with Session(target) as session:
        restore_backup(session, tmp_path / exported["file_name"])
        restored = session.exec(select(WebsiteDraftGenerationRun)).one()
        restored_items = session.exec(
            select(WebsiteDraftGenerationItem).where(
                WebsiteDraftGenerationItem.run_id == restored.id
            )
        ).all()
        assert restored.status == "interrupted"
        assert restored.manifest_hash == run.manifest_hash
        assert len(restored_items) == run.counts.expected
        assert sum(item.outcome == "generated" for item in restored_items) == 1


def test_flo_zone_historical_drafts_remain_untouched_without_explicit_coverage():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        business = session.exec(
            select(Business).where(
                Business.company_name == FLO_ZONE_COMPANY_NAME
            )
        ).one()
        website = session.exec(
            select(Website).where(Website.business_id == business.id)
        ).one()
        plan = session.exec(
            select(SitePlan).where(SitePlan.website_id == website.id)
        ).one()
        before = {
            page.id: page.model_dump(mode="json")
            for page in session.exec(
                select(GeneratedPage)
                .where(GeneratedPage.website_id == website.id)
                .order_by(GeneratedPage.id)
            ).all()
        }
        assert len(before) == 55
        assess_site_plan(session, plan.id)
        result = start_or_resume_generation(
            session,
            plan.id,
            website_id=website.id,
        )
        after = {
            page.id: page.model_dump(mode="json")
            for page in session.exec(
                select(GeneratedPage)
                .where(GeneratedPage.website_id == website.id)
                .order_by(GeneratedPage.id)
            ).all()
        }
        assert after == before
        assert result.counts.already_drafted == 55
        assert result.counts.generated == 0
