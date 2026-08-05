from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
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
    Brand,
    Business,
    City,
    County,
    GeneratedPage,
    InternalLinkIntent,
    NavigationItem,
    NavigationSet,
    PageComposition,
    PlannedPage,
    PlanningRecord,
    Service,
    SitePlan,
    SiteConnectionPlanningRecord,
    Website,
    WebsiteIdentity,
)
from app.schemas.site_connections import (
    InternalLinkIntentCreate,
    InternalLinkIntentUpdate,
    NavigationItemCreate,
    NavigationItemUpdate,
    NavigationSetDecisionUpdate,
)
from app.services.site_connections import (
    SiteConnectionError,
    create_internal_link_intent,
    create_navigation_item,
    ensure_site_connection_foundation,
    evaluate_site_connection_diagnostics,
    read_site_connection_plan,
    refresh_site_connection_suggestions,
    update_internal_link_intent,
    update_navigation_item,
    update_navigation_set,
)
from app.services.website_readiness import evaluate_website_readiness


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _scope(session: Session, *, domain: str | None = None):
    suffix = uuid4().hex[:10]
    business = Business(
        company_name=f"Connection Business {suffix}",
        business_type="Test business",
        phone="407-555-0100",
        email=f"hello-{suffix}@example.test",
        main_city="Orlando",
        state="FL",
        license_number=f"TEST-{suffix}",
        description="Approved business facts for connection planning.",
    )
    session.add(business)
    session.flush()
    brand = Brand(
        business_id=business.id,
        brand_name=f"Connection Brand {suffix}",
        status="active",
    )
    session.add(brand)
    session.flush()
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name=f"Connection Website {suffix}",
        domain=domain or f"connections-{suffix}.example",
        public_url=f"https://connections-{suffix}.example",
        status="active",
    )
    session.add(website)
    session.flush()
    session.add(
        WebsiteIdentity(
            website_id=website.id,
            display_name=brand.brand_name,
            status="active",
        )
    )
    plan = SitePlan(
        website_id=website.id,
        plan_key="primary",
        plan_name="Connection Plan",
    )
    session.add(plan)
    session.flush()
    ensure_site_connection_foundation(session, plan)
    pages = {}
    for page_type, name, slug in (
        ("home", "Home", "home"),
        ("about", "About", "about"),
        ("contact", "Contact", "contact"),
        ("service", "Termite Service", "termite-service"),
        ("county", "Orange County", "orange-county"),
        ("city", "Deferred City", "deferred-city"),
    ):
        page = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type=page_type,
            working_name=name,
            intended_slug=slug,
            planning_status="planned",
        )
        session.add(page)
        session.flush()
        pages[page_type] = page
    session.commit()
    refresh_site_connection_suggestions(session, plan.id)
    return website, plan, pages


def _navigation_set(session: Session, plan: SitePlan, set_type: str) -> NavigationSet:
    return session.exec(
        select(NavigationSet).where(
            NavigationSet.site_plan_id == plan.id,
            NavigationSet.set_type == set_type,
        )
    ).one()


def _add_nav(
    session: Session,
    website: Website,
    plan: SitePlan,
    page: PlannedPage,
    set_type: str,
    position: int,
):
    nav_set = _navigation_set(session, plan, set_type)
    return create_navigation_item(
        session,
        NavigationItemCreate(
            website_id=website.id,
            site_plan_id=plan.id,
            navigation_set_id=nav_set.id,
            target_planned_page_id=page.id,
            label=page.working_name,
            position=position,
            status="active",
            decided_by="Connection Operator",
            rationale="Approved for the Website visitor journey.",
        ),
    )


def _add_link(
    session: Session,
    website: Website,
    plan: SitePlan,
    source: PlannedPage,
    target: PlannedPage,
    relationship_type: str = "conversion",
):
    return create_internal_link_intent(
        session,
        InternalLinkIntentCreate(
            website_id=website.id,
            site_plan_id=plan.id,
            source_planned_page_id=source.id,
            target_planned_page_id=target.id,
            purpose=f"Guide visitors from {source.working_name} to {target.working_name}.",
            relationship_type=relationship_type,
            approval_state="approved",
            decided_by="Connection Operator",
            rationale="Approved as an intentional Website connection.",
        ),
    )


def _activate_sets(session: Session, plan: SitePlan) -> None:
    for set_type in ("primary", "utility", "footer"):
        navigation_set = _navigation_set(session, plan, set_type)
        update_navigation_set(
            session,
            navigation_set.id,
            NavigationSetDecisionUpdate(
                status="active",
                decided_by="Connection Operator",
                rationale=f"Approve the {set_type} navigation set.",
            ),
        )


def test_foundation_keeps_generated_suggestions_separate_from_operator_decisions():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, _ = _scope(session)
        result = read_site_connection_plan(session, plan.id)
        assert [item.set_type for item in result.navigation_sets] == [
            "primary",
            "utility",
            "footer",
        ]
        assert result.navigation_items == []
        assert result.internal_link_intents == []
        assert result.planning_record.generated_navigation_suggestions
        assert result.planning_record.generated_internal_link_suggestions

        before = result.planning_record.generated_navigation_suggestions
        refresh_site_connection_suggestions(session, plan.id)
        after = read_site_connection_plan(session, plan.id)
        assert after.navigation_items == []
        assert after.internal_link_intents == []
        assert after.planning_record.generated_navigation_suggestions == before
        assert after.website_id == website.id


def test_api_decisions_require_provenance_and_increment_versions():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        primary = _navigation_set(session, plan, "primary")
        with pytest.raises(ValidationError):
            NavigationItemCreate(
                website_id=website.id,
                site_plan_id=plan.id,
                navigation_set_id=primary.id,
                target_planned_page_id=pages["home"].id,
                label="Home",
            )

        result = read_site_connection_plan(session, plan.id)
        nav_suggestion = next(
            item
            for item in result.planning_record.generated_navigation_suggestions
            if item["set_type"] == "primary"
            and item["target_planned_page_id"] == pages["home"].id
        )
        decided_set = update_navigation_set(
            session,
            primary.id,
            NavigationSetDecisionUpdate(
                status="active",
                decided_by="First Operator",
                rationale="Approve the primary visitor navigation.",
            ),
        )
        assert decided_set.decision_version == 1
        decided_set = update_navigation_set(
            session,
            primary.id,
            NavigationSetDecisionUpdate(
                status="active",
                decided_by="Second Operator",
                rationale="Reconfirm the primary visitor navigation.",
            ),
        )
        assert decided_set.decision_version == 2
        assert decided_set.decided_by == "Second Operator"
        assert decided_set.source_suggestion_key is None

        nav = create_navigation_item(
            session,
            NavigationItemCreate(
                website_id=website.id,
                site_plan_id=plan.id,
                navigation_set_id=primary.id,
                target_planned_page_id=pages["home"].id,
                label="Home",
                decided_by="First Operator",
                rationale="Accept the generated Home destination.",
                source_suggestion_key=nav_suggestion["suggestion_key"],
            ),
        )
        assert nav.decision_version == 1
        updated = update_navigation_item(
            session,
            nav.id,
            NavigationItemUpdate(
                label="Home",
                decided_by="Second Operator",
                rationale="Reconfirm the Home label.",
            ),
        )
        assert updated.decision_version == 2
        assert updated.source_suggestion_key == nav_suggestion["suggestion_key"]

        with pytest.raises(SiteConnectionError, match="does not match"):
            create_navigation_item(
                session,
                NavigationItemCreate(
                    website_id=website.id,
                    site_plan_id=plan.id,
                    navigation_set_id=primary.id,
                    target_planned_page_id=pages["service"].id,
                    label="Service",
                    position=10,
                    decided_by="Connection Operator",
                    rationale="Attempt a mismatched suggestion binding.",
                    source_suggestion_key=nav_suggestion["suggestion_key"],
                ),
            )

        link_suggestion = next(
            item
            for item in result.planning_record.generated_internal_link_suggestions
            if item["source_planned_page_id"] == pages["home"].id
            and item["target_planned_page_id"] == pages["contact"].id
        )
        link = create_internal_link_intent(
            session,
            InternalLinkIntentCreate(
                website_id=website.id,
                site_plan_id=plan.id,
                source_planned_page_id=pages["home"].id,
                target_planned_page_id=pages["contact"].id,
                purpose="Provide a direct contact path.",
                relationship_type="conversion",
                approval_state="approved",
                decided_by="Connection Operator",
                rationale="Accept the generated conversion path.",
                source_suggestion_key=link_suggestion["suggestion_key"],
            ),
        )
        assert link.source_suggestion_key == link_suggestion["suggestion_key"]
        with pytest.raises(SiteConnectionError, match="does not match"):
            create_internal_link_intent(
                session,
                InternalLinkIntentCreate(
                    website_id=website.id,
                    site_plan_id=plan.id,
                    source_planned_page_id=pages["service"].id,
                    target_planned_page_id=pages["contact"].id,
                    purpose="Provide a Service contact path.",
                    relationship_type="conversion",
                    approval_state="approved",
                    decided_by="Connection Operator",
                    rationale="Attempt a mismatched link suggestion binding.",
                    source_suggestion_key=link_suggestion["suggestion_key"],
                ),
            )
        refresh_site_connection_suggestions(session, plan.id)
        reloaded = read_site_connection_plan(session, plan.id)
        assert reloaded.navigation_items[0].decision_version == 2
        assert reloaded.navigation_items[0].source_suggestion_key == nav_suggestion[
            "suggestion_key"
        ]
        assert reloaded.internal_link_intents[0].source_suggestion_key == link_suggestion[
            "suggestion_key"
        ]


def test_legacy_rows_without_provenance_fail_closed_as_authoritative():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        primary = _navigation_set(session, plan, "primary")
        session.add(
            NavigationItem(
                website_id=website.id,
                site_plan_id=plan.id,
                navigation_set_id=primary.id,
                target_planned_page_id=pages["home"].id,
                label="Legacy Home",
                status="active",
            )
        )
        session.commit()

        result = read_site_connection_plan(session, plan.id)
        by_key = {item.key: item for item in result.diagnostics}
        assert result.ready is False
        assert by_key["decision_provenance"].status == "needs_attention"
        assert by_key["navigation_set_decisions"].status == "needs_attention"
        assert pages["about"].id in by_key["orphaned_pages"].affected_planned_page_ids


def test_disconnected_approved_link_cycle_remains_orphaned():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, _ = _scope(session)
        cycle_pages = []
        for index in (1, 2):
            page = PlannedPage(
                website_id=website.id,
                site_plan_id=plan.id,
                page_type="informational",
                working_name=f"Disconnected {index}",
                intended_slug=f"disconnected-{index}",
                planning_status="planned",
            )
            session.add(page)
            session.flush()
            cycle_pages.append(page)
        session.commit()
        _add_link(
            session,
            website,
            plan,
            cycle_pages[0],
            cycle_pages[1],
            "related_content",
        )
        _add_link(
            session,
            website,
            plan,
            cycle_pages[1],
            cycle_pages[0],
            "related_content",
        )

        result = read_site_connection_plan(session, plan.id)
        orphaned = next(
            item for item in result.diagnostics if item.key == "orphaned_pages"
        )
        assert orphaned.status == "needs_attention"
        assert {page.id for page in cycle_pages} <= set(
            orphaned.affected_planned_page_ids
        )


def test_active_navigation_child_requires_authoritative_active_parent():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        parent = _add_nav(session, website, plan, pages["home"], "primary", 0)
        update_navigation_item(
            session,
            parent.id,
            NavigationItemUpdate(
                status="disabled",
                decided_by="Connection Operator",
                rationale="Disable the parent destination.",
            ),
        )
        primary = _navigation_set(session, plan, "primary")
        with pytest.raises(SiteConnectionError, match="provenance-complete parent"):
            create_navigation_item(
                session,
                NavigationItemCreate(
                    website_id=website.id,
                    site_plan_id=plan.id,
                    navigation_set_id=primary.id,
                    target_planned_page_id=pages["service"].id,
                    parent_navigation_item_id=parent.id,
                    label="Service",
                    position=10,
                    decided_by="Connection Operator",
                    rationale="Attempt an active child under a disabled parent.",
                ),
            )

        session.add(
            NavigationItem(
                website_id=website.id,
                site_plan_id=plan.id,
                navigation_set_id=primary.id,
                target_planned_page_id=pages["service"].id,
                parent_navigation_item_id=parent.id,
                label="Legacy Invalid Child",
                position=10,
                status="active",
                decided_by="Legacy Operator",
                rationale="Preserved invalid historical relationship.",
                decision_version=1,
                decided_at=datetime.now(UTC),
            )
        )
        session.commit()
        result = read_site_connection_plan(session, plan.id)
        parent_gate = next(
            item
            for item in result.diagnostics
            if item.key == "navigation_parent_authority"
        )
        assert parent_gate.status == "needs_attention"


def test_operator_decisions_make_navigation_and_conversion_paths_ready():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        _add_nav(session, website, plan, pages["home"], "primary", 0)
        _add_nav(session, website, plan, pages["service"], "primary", 10)
        _add_nav(session, website, plan, pages["county"], "primary", 20)
        _add_nav(session, website, plan, pages["about"], "footer", 0)
        _add_nav(session, website, plan, pages["contact"], "utility", 0)
        _add_link(session, website, plan, pages["home"], pages["service"])
        _add_link(session, website, plan, pages["home"], pages["contact"])
        _add_link(session, website, plan, pages["service"], pages["contact"])
        _add_link(session, website, plan, pages["county"], pages["contact"])
        _activate_sets(session, plan)

        result = read_site_connection_plan(session, plan.id)
        assert result.ready is True
        assert all(item.status == "ready" for item in result.diagnostics)

        report = evaluate_website_readiness(session, plan.id)
        website_category = next(
            item for item in report.categories if item.key == "website_readiness"
        )
        assert any(
            item.key == "site_connections_conversion_paths"
            and item.status == "ready"
            for item in website_category.items
        )
        assert any(
            item.key == "semantic_duplication"
            for item in website_category.items
        )
        future = next(
            item for item in report.categories if item.key == "future_readiness"
        )
        assert "navigation" not in {item.key for item in future.items}
        assert {"approved_brand_assets", "website_identity_asset_selections"} <= {
            item.key for item in website_category.items
        }
        assert {
            "theme_selection",
            "theme_approval",
            "theme_token_contract",
            "theme_accessibility",
            "theme_composition_freshness",
        } <= {item.key for item in website_category.items}
        assert {
            "complete_site_preview",
            "media",
            "media_ingestion",
            "publication",
        } <= {item.key for item in future.items}
        assert "theme" not in {item.key for item in future.items}


def test_scope_self_link_deferred_target_and_duplicate_guards_fail_closed():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        other_website, other_plan, other_pages = _scope(session)
        primary = _navigation_set(session, plan, "primary")

        with pytest.raises(SiteConnectionError, match="Website"):
            create_navigation_item(
                session,
                NavigationItemCreate(
                    website_id=other_website.id,
                    site_plan_id=plan.id,
                    navigation_set_id=primary.id,
                    target_planned_page_id=pages["home"].id,
                    label="Home",
                    decided_by="Connection Operator",
                    rationale="Attempt a cross-Website decision.",
                ),
            )
        with pytest.raises(SiteConnectionError, match="selected Website and Site Plan"):
            create_navigation_item(
                session,
                NavigationItemCreate(
                    website_id=website.id,
                    site_plan_id=plan.id,
                    navigation_set_id=primary.id,
                    target_planned_page_id=other_pages["home"].id,
                    label="Other Home",
                    decided_by="Connection Operator",
                    rationale="Attempt a cross-Website target.",
                ),
            )
        with pytest.raises(SiteConnectionError, match="deferred"):
            _add_nav(session, website, plan, pages["city"], "primary", 0)
        with pytest.raises(SiteConnectionError, match="itself"):
            _add_link(session, website, plan, pages["home"], pages["home"])

        _add_nav(session, website, plan, pages["home"], "primary", 0)
        with pytest.raises(SiteConnectionError, match="already"):
            _add_nav(session, website, plan, pages["home"], "primary", 1)
        _add_link(session, website, plan, pages["home"], pages["contact"])
        with pytest.raises(SiteConnectionError, match="already"):
            _add_link(session, website, plan, pages["home"], pages["contact"])
        with pytest.raises(SiteConnectionError, match="already"):
            _add_link(
                session,
                website,
                plan,
                pages["home"],
                pages["contact"],
                relationship_type="hierarchy",
            )

        assert other_plan.website_id == other_website.id


def test_updates_revalidate_same_website_site_plan_ownership():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        second_plan = SitePlan(
            website_id=website.id,
            plan_key="secondary",
            plan_name="Secondary Connection Plan",
        )
        session.add(second_plan)
        session.flush()
        ensure_site_connection_foundation(session, second_plan)
        second_page = PlannedPage(
            website_id=website.id,
            site_plan_id=second_plan.id,
            page_type="informational",
            working_name="Other Plan Page",
            intended_slug="other-plan-page",
            planning_status="planned",
        )
        session.add(second_page)
        session.commit()

        navigation_item = _add_nav(
            session,
            website,
            plan,
            pages["home"],
            "primary",
            0,
        )
        stored_navigation_item = session.get(NavigationItem, navigation_item.id)
        stored_navigation_item.target_planned_page_id = second_page.id
        session.add(stored_navigation_item)
        session.commit()
        with pytest.raises(SiteConnectionError, match="selected Website and Site Plan"):
            update_navigation_item(
                session,
                navigation_item.id,
                NavigationItemUpdate(
                    label="Still invalid",
                    decided_by="Connection Operator",
                    rationale="Revalidate an intentionally corrupted target.",
                ),
            )

        stored_navigation_item.target_planned_page_id = pages["home"].id
        session.add(stored_navigation_item)
        session.commit()
        link = _add_link(session, website, plan, pages["home"], pages["contact"])
        stored_link = session.get(InternalLinkIntent, link.id)
        stored_link.target_planned_page_id = second_page.id
        session.add(stored_link)
        session.commit()
        with pytest.raises(SiteConnectionError, match="selected Website and Site Plan"):
            update_internal_link_intent(
                session,
                link.id,
                InternalLinkIntentUpdate(
                    purpose="Still invalid",
                    decided_by="Connection Operator",
                    rationale="Revalidate an intentionally corrupted target.",
                ),
            )


def test_service_county_city_service_journeys_require_exact_bidirectional_edges():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, _ = _scope(session)
        suffix = uuid4().hex[:8]
        service = Service(
            business_id=website.business_id,
            service_name="Drywood Termite Tenting",
            service_slug=f"drywood-tenting-{suffix}",
        )
        county = County(state="FL", county_name=f"Orange {suffix}")
        wrong_county = County(state="FL", county_name=f"Seminole {suffix}")
        session.add(service)
        session.add(county)
        session.add(wrong_county)
        session.flush()
        city = City(
            county_id=county.id,
            city_name=f"Orlando {suffix}",
            city_slug=f"orlando-{suffix}",
        )
        session.add(city)
        session.flush()
        owner = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="county",
            working_name="Drywood Tenting in Orange County",
            intended_slug=f"drywood-orange-{suffix}",
            service_id=service.id,
            county_id=county.id,
            planning_status="planned",
        )
        wrong_owner = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="county",
            working_name="Drywood Tenting in Seminole County",
            intended_slug=f"drywood-seminole-{suffix}",
            service_id=service.id,
            county_id=wrong_county.id,
            planning_status="planned",
        )
        city_service = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="city_service",
            working_name="Drywood Tenting in Orlando",
            intended_slug=f"drywood-orlando-{suffix}",
            service_id=service.id,
            county_id=county.id,
            city_id=city.id,
            planning_status="planned",
        )
        session.add(owner)
        session.add(wrong_owner)
        session.add(city_service)
        session.commit()

        def journey_diagnostic():
            return next(
                item
                for item in evaluate_site_connection_diagnostics(session, plan)
                if item.key == "service_county_city_service_journeys"
            )

        initial = journey_diagnostic()
        assert initial.status == "needs_attention"
        assert initial.affected_planned_page_ids == [owner.id, city_service.id]

        _add_link(session, website, plan, wrong_owner, city_service)
        _add_link(session, website, plan, city_service, wrong_owner)
        wrong_pair = journey_diagnostic()
        assert wrong_pair.status == "needs_attention"
        assert wrong_pair.affected_planned_page_ids == [owner.id, city_service.id]

        _add_link(session, website, plan, owner, city_service)
        missing_return = journey_diagnostic()
        assert missing_return.status == "needs_attention"
        assert missing_return.affected_planned_page_ids == [city_service.id]

        _add_link(session, website, plan, city_service, owner)
        complete = journey_diagnostic()
        assert complete.status == "ready"
        assert complete.affected_planned_page_ids == []


def test_cycle_detection_and_readiness_diagnostics_are_deterministic():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        home = _add_nav(session, website, plan, pages["home"], "primary", 0)
        service = _add_nav(session, website, plan, pages["service"], "primary", 1)
        update_navigation_item(
            session,
            service.id,
            NavigationItemUpdate(
                parent_navigation_item_id=home.id,
                decided_by="Connection Operator",
                rationale="Nest the Service destination under Home.",
            ),
        )
        with pytest.raises(SiteConnectionError, match="cycle"):
            update_navigation_item(
                session,
                home.id,
                NavigationItemUpdate(
                    parent_navigation_item_id=service.id,
                    decided_by="Connection Operator",
                    rationale="Attempt a cyclic relationship.",
                ),
            )
        update_navigation_set(
            session,
            _navigation_set(session, plan, "primary").id,
            NavigationSetDecisionUpdate(
                status="active",
                decided_by="Connection Operator",
                rationale="Approve the tested primary hierarchy.",
            ),
        )

        result = read_site_connection_plan(session, plan.id)
        by_key = {item.key: item for item in result.diagnostics}
        assert by_key["navigation_cycles"].status == "ready"
        assert by_key["orphaned_pages"].status == "needs_attention"
        assert by_key["orphaned_pages"].affected_planned_page_ids == sorted(
            [pages["about"].id, pages["contact"].id, pages["county"].id]
        )
        assert by_key["conversion_paths"].status == "needs_attention"


def test_approval_updates_do_not_modify_generated_page_content():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        planning_record = session.exec(
            select(PlanningRecord).where(
                PlanningRecord.planned_page_id == pages["home"].id
            )
        ).first()
        before = dict(planning_record.operator_overrides) if planning_record else {}
        intent = create_internal_link_intent(
            session,
            InternalLinkIntentCreate(
                website_id=website.id,
                site_plan_id=plan.id,
                source_planned_page_id=pages["home"].id,
                target_planned_page_id=pages["contact"].id,
                purpose="Offer a contact path.",
                relationship_type="conversion",
                approval_state="proposed",
                decided_by="Connection Operator",
                rationale="Propose a direct customer contact path.",
            ),
        )
        updated = update_internal_link_intent(
            session,
            intent.id,
            InternalLinkIntentUpdate(
                approval_state="approved",
                decided_by="Connection Operator",
                rationale="Approve the direct customer contact path.",
            ),
        )
        assert updated.approval_state == "approved"
        assert intent.decision_version == 1
        assert updated.decision_version == 2
        assert updated.decided_by == "Connection Operator"
        if planning_record:
            session.refresh(planning_record)
            assert planning_record.operator_overrides == before
        assert session.exec(select(InternalLinkIntent)).one().approval_state == "approved"
        assert session.exec(select(NavigationItem)).all() == []


def test_connection_planning_backup_round_trip_preserves_operator_decisions(tmp_path):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        nav = _add_nav(session, website, plan, pages["home"], "primary", 0)
        link = _add_link(session, website, plan, pages["home"], pages["contact"])
        _activate_sets(session, plan)
        exported = export_backup(session, backup_dir=tmp_path)
        assert exported["table_counts"]["navigation_sets"] == 3
        assert exported["table_counts"]["navigation_items"] == 1
        assert exported["table_counts"]["internal_link_intents"] == 1

        for record in session.exec(select(InternalLinkIntent)).all():
            session.delete(record)
        for record in session.exec(select(NavigationItem)).all():
            session.delete(record)
        for record in session.exec(select(NavigationSet)).all():
            session.delete(record)
        for record in session.exec(select(SiteConnectionPlanningRecord)).all():
            session.delete(record)
        session.commit()

        restored = restore_backup(session, exported["path"])
        assert restored["status"] == "restored"
        assert restored["table_counts"]["site_connection_planning_records"] == 1
        restored_nav = session.exec(select(NavigationItem)).one()
        restored_link = session.exec(select(InternalLinkIntent)).one()
        assert restored_nav.label == nav.label
        assert restored_nav.website_id == website.id
        assert restored_nav.decided_by == "Connection Operator"
        assert restored_nav.decision_version == 1
        assert restored_link.purpose == link.purpose
        assert restored_link.approval_state == "approved"
        assert restored_link.rationale == "Approved as an intentional Website connection."
        assert restored_link.decided_at is not None
        assert len(session.exec(select(NavigationSet)).all()) == 3
        assert all(
            item.decision_version == 1
            for item in session.exec(select(NavigationSet)).all()
        )

        restore_backup(session, exported["path"])
        assert len(session.exec(select(NavigationItem)).all()) == 1
        assert len(session.exec(select(InternalLinkIntent)).all()) == 1


def test_backup_052_rejects_partial_navigation_provenance(tmp_path):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        _add_nav(session, website, plan, pages["home"], "primary", 0)
        exported = export_backup(session, backup_dir=tmp_path)

    assert BACKUP_VERSION == "0.52"
    path = tmp_path / "partial-navigation-provenance.json"
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    assert payload["metadata"]["version"] == "0.52"
    payload["data"]["navigation_items"][0]["decided_at"] = None
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupValidationError, match="partial decision provenance"):
        load_backup(path)


def test_backup_052_rejects_parallel_typed_internal_link_edges(tmp_path):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        _add_link(session, website, plan, pages["home"], pages["contact"])
        exported = export_backup(session, backup_dir=tmp_path)

    path = tmp_path / "duplicate-typed-edge.json"
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    duplicate = dict(payload["data"]["internal_link_intents"][0])
    duplicate["id"] += 1000
    duplicate["relationship_type"] = "hierarchy"
    payload["data"]["internal_link_intents"].append(duplicate)
    payload["metadata"]["table_counts"]["internal_link_intents"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupValidationError, match="duplicate records"):
        load_backup(path)


def test_backup_052_allows_legacy_composition_snapshot_for_draft_graph_and_restores_stale(
    tmp_path,
):
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        website, plan, pages = _scope(session)
        navigation_item = _add_nav(
            session,
            website,
            plan,
            pages["home"],
            "primary",
            0,
        )
        generated = GeneratedPage(
            business_id=website.business_id,
            website_id=website.id,
            page_type="home",
            page_title="Home",
            page_slug=f"home-{uuid4().hex[:8]}",
            draft_content={"title": "Home", "h1": "Home"},
            generation_status="generated",
        )
        session.add(generated)
        session.flush()
        pages["home"].generated_page_id = generated.id
        session.add(pages["home"])
        session.add(
            PageComposition(
                website_id=website.id,
                site_plan_id=plan.id,
                planned_page_id=pages["home"].id,
                generated_page_id=generated.id,
                generated_components=[],
                operator_decisions=[],
                source_snapshot={
                    "website_id": website.id,
                    "site_plan_id": plan.id,
                    "planned_page_id": pages["home"].id,
                    "generated_page_id": generated.id,
                    "navigation_sets": [],
                    "navigation_items": [
                        {
                            "id": navigation_item.id,
                            "target": pages["home"].id,
                        }
                    ],
                    "internal_links": [],
                },
                source_hash="0" * 64,
                status="current",
            )
        )
        session.commit()
        exported = export_backup(session, backup_dir=tmp_path)

    loaded = load_backup(Path(exported["path"]))
    assert loaded["metadata"]["version"] == "0.52"

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restored = restore_backup(session, exported["path"])
        assert restored["status"] == "restored"
        assert session.exec(select(PageComposition)).one().status == "stale"


def test_backup_052_remaps_suggestion_provenance_when_restored_ids_shift(tmp_path):
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        website, plan, pages = _scope(session, domain="source-connections.example")
        planning = session.exec(
            select(SiteConnectionPlanningRecord).where(
                SiteConnectionPlanningRecord.site_plan_id == plan.id
            )
        ).one()
        navigation_suggestion = next(
            item
            for item in planning.generated_navigation_suggestions
            if item["target_planned_page_id"] == pages["home"].id
        )
        link_suggestion = next(
            item
            for item in planning.generated_internal_link_suggestions
            if item["source_planned_page_id"] == pages["home"].id
            and item["target_planned_page_id"] == pages["contact"].id
        )
        navigation_set = _navigation_set(
            session,
            plan,
            navigation_suggestion["set_type"],
        )
        create_navigation_item(
            session,
            NavigationItemCreate(
                website_id=website.id,
                site_plan_id=plan.id,
                navigation_set_id=navigation_set.id,
                target_planned_page_id=pages["home"].id,
                label="Home",
                position=0,
                status="active",
                decided_by="Connection Operator",
                rationale="Accept the exact generated Home suggestion.",
                source_suggestion_key=navigation_suggestion["suggestion_key"],
            ),
        )
        create_internal_link_intent(
            session,
            InternalLinkIntentCreate(
                website_id=website.id,
                site_plan_id=plan.id,
                source_planned_page_id=pages["home"].id,
                target_planned_page_id=pages["contact"].id,
                purpose="Provide the approved generated contact path.",
                relationship_type=link_suggestion["relationship_type"],
                approval_state="approved",
                decided_by="Connection Operator",
                rationale="Accept the exact generated contact suggestion.",
                source_suggestion_key=link_suggestion["suggestion_key"],
            ),
        )
        source_page_ids = {page.id for page in pages.values()}
        exported = export_backup(session, backup_dir=tmp_path)

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        _scope(session, domain="existing-connections.example")
        restored = restore_backup(session, exported["path"])
        assert restored["status"] == "restored"
        restored_website = session.exec(
            select(Website).where(Website.domain == "source-connections.example")
        ).one()
        restored_plan = session.exec(
            select(SitePlan).where(SitePlan.website_id == restored_website.id)
        ).one()
        restored_navigation = session.exec(
            select(NavigationItem).where(
                NavigationItem.website_id == restored_website.id
            )
        ).one()
        restored_link = session.exec(
            select(InternalLinkIntent).where(
                InternalLinkIntent.website_id == restored_website.id
            )
        ).one()
        restored_planning = session.exec(
            select(SiteConnectionPlanningRecord).where(
                SiteConnectionPlanningRecord.site_plan_id == restored_plan.id
            )
        ).one()

        assert restored_navigation.target_planned_page_id not in source_page_ids
        assert restored_navigation.source_suggestion_key == (
            f"navigation:primary:{restored_navigation.target_planned_page_id}"
        )
        assert restored_navigation.source_suggestion_key in {
            item["suggestion_key"]
            for item in restored_planning.generated_navigation_suggestions
        }
        assert restored_link.source_suggestion_key == (
            f"internal-link:{restored_link.source_planned_page_id}:"
            f"{restored_link.target_planned_page_id}:"
            f"{restored_link.relationship_type}"
        )
        assert restored_link.source_suggestion_key in {
            item["suggestion_key"]
            for item in restored_planning.generated_internal_link_suggestions
        }


def test_backup_051_restores_navigation_records_as_legacy_non_authoritative(tmp_path):
    source_engine = _engine()
    SQLModel.metadata.create_all(source_engine)
    with Session(source_engine) as session:
        website, plan, pages = _scope(session)
        _add_nav(session, website, plan, pages["home"], "primary", 0)
        _add_link(session, website, plan, pages["home"], pages["contact"])
        exported = export_backup(session, backup_dir=tmp_path)

    legacy_path = tmp_path / "atlas-backup-legacy-051.json"
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    payload["metadata"]["version"] = "0.51"
    for group in ("navigation_sets", "navigation_items", "internal_link_intents"):
        for record in payload["data"][group]:
            for field in (
                "rationale",
                "decided_by",
                "decision_version",
                "decided_at",
                "source_suggestion_key",
            ):
                record.pop(field, None)
    legacy_path.write_text(json.dumps(payload), encoding="utf-8")

    target_engine = _engine()
    SQLModel.metadata.create_all(target_engine)
    with Session(target_engine) as session:
        restored = restore_backup(session, legacy_path)
        assert restored["status"] == "restored"
        nav = session.exec(select(NavigationItem)).one()
        link = session.exec(select(InternalLinkIntent)).one()
        assert nav.decision_version is None
        assert nav.decided_by is None
        assert link.decision_version is None
        restored_plan = session.exec(select(SitePlan)).one()
        diagnostics = read_site_connection_plan(session, restored_plan.id)
        assert diagnostics.ready is False
        assert next(
            item
            for item in diagnostics.diagnostics
            if item.key == "decision_provenance"
        ).status == "needs_attention"


def test_backup_051_rejects_cross_website_navigation_ownership(tmp_path):
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        website, plan, pages = _scope(session)
        other_website, _, _ = _scope(session)
        _add_nav(session, website, plan, pages["home"], "primary", 0)
        exported = export_backup(session, backup_dir=tmp_path)

    path = tmp_path / "cross-website-legacy-051.json"
    payload = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    payload["metadata"]["version"] = "0.51"
    for group in ("navigation_sets", "navigation_items", "internal_link_intents"):
        for record in payload["data"][group]:
            for field in (
                "rationale",
                "decided_by",
                "decision_version",
                "decided_at",
                "source_suggestion_key",
            ):
                record.pop(field, None)
    payload["data"]["navigation_items"][0]["website_id"] = other_website.id
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BackupValidationError, match="crosses a Website"):
        load_backup(path)
