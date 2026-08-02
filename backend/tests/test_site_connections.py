from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.backup import export_backup, restore_backup
from app.models import (
    Brand,
    Business,
    InternalLinkIntent,
    NavigationItem,
    NavigationSet,
    PlannedPage,
    PlanningRecord,
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
)
from app.services.site_connections import (
    SiteConnectionError,
    create_internal_link_intent,
    create_navigation_item,
    ensure_site_connection_foundation,
    read_site_connection_plan,
    refresh_site_connection_suggestions,
    update_internal_link_intent,
    update_navigation_item,
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
            "complete_site_preview",
            "media",
            "media_ingestion",
            "theme",
            "publication",
        } <= {item.key for item in future.items}


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

        assert other_plan.website_id == other_website.id


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
            NavigationItemUpdate(parent_navigation_item_id=home.id),
        )
        with pytest.raises(SiteConnectionError, match="cycle"):
            update_navigation_item(
                session,
                home.id,
                NavigationItemUpdate(parent_navigation_item_id=service.id),
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
            ),
        )
        updated = update_internal_link_intent(
            session,
            intent.id,
            InternalLinkIntentUpdate(approval_state="approved"),
        )
        assert updated.approval_state == "approved"
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
        assert restored_link.purpose == link.purpose
        assert restored_link.approval_state == "approved"
        assert len(session.exec(select(NavigationSet)).all()) == 3

        restore_backup(session, exported["path"])
        assert len(session.exec(select(NavigationItem)).all()) == 1
        assert len(session.exec(select(InternalLinkIntent)).all()) == 1
