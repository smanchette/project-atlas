from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlmodel import Session

from app.core.config import get_settings
from app.models import Brand, Business, PlannedPage, SitePlan, Website


BACKEND = Path(__file__).parents[1]


def _config(monkeypatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_0032_clean_disposable_database_upgrade(monkeypatch, tmp_path):
    database = tmp_path / "coverage-clean.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260730_0032")
    tables = set(inspect(create_engine(f"sqlite:///{database.as_posix()}")).get_table_names())
    assert {
        "websitecoverageplanningrecord",
        "websiteservicecoveragedecision",
        "websitecountycoveragedecision",
        "websitecitycoveragedecision",
        "websiteservicecitycoveragedecision",
    } <= tables
    get_settings.cache_clear()


def test_0032_backfills_planning_record_without_approving_historical_page(
    monkeypatch,
    tmp_path,
):
    database = tmp_path / "coverage-populated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260730_0031")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with Session(engine) as session:
        business = Business(
            company_name="Coverage Migration Sentinel",
            business_type="Test",
            state="FL",
        )
        session.add(business)
        session.flush()
        brand = Brand(
            business_id=business.id,
            brand_name="Coverage Migration Sentinel",
            status="active",
        )
        session.add(brand)
        session.flush()
        website = Website(
            business_id=business.id,
            brand_id=brand.id,
            website_name="Coverage Migration Sentinel",
            domain="coverage-migration.example.test",
            public_url="https://coverage-migration.example.test",
            status="active",
        )
        session.add(website)
        session.flush()
        plan = SitePlan(
            website_id=website.id,
            plan_key="primary",
            plan_name="Preserved Plan",
        )
        session.add(plan)
        session.flush()
        historical = PlannedPage(
            website_id=website.id,
            site_plan_id=plan.id,
            page_type="informational",
            working_name="Preserved Historical Page",
            intended_slug="preserved-historical-page",
        )
        session.add(historical)
        session.commit()
        plan_id = plan.id
        page_id = historical.id

    command.upgrade(config, "20260730_0032")
    with engine.connect() as connection:
        planning_records = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM websitecoverageplanningrecord WHERE site_plan_id = ?",
            (plan_id,),
        ).scalar_one()
        decision_count = sum(
            connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one()
            for table in (
                "websiteservicecoveragedecision",
                "websitecountycoveragedecision",
                "websitecitycoveragedecision",
                "websiteservicecitycoveragedecision",
            )
        )
        preserved = connection.exec_driver_sql(
            "SELECT working_name, intended_slug FROM plannedpage WHERE id = ?",
            (page_id,),
        ).one()
    assert planning_records == 1
    assert decision_count == 0
    assert tuple(preserved) == ("Preserved Historical Page", "preserved-historical-page")
    get_settings.cache_clear()


def test_0036_adds_service_county_decisions_and_candidate_projection(
    monkeypatch,
    tmp_path,
):
    database = tmp_path / "service-county-clean.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260731_0035")
    command.upgrade(config, "20260731_0036")
    inspector = inspect(create_engine(f"sqlite:///{database.as_posix()}"))
    assert "websiteservicecountycoveragedecision" in inspector.get_table_names()
    columns = {
        item["name"]
        for item in inspector.get_columns("websitecoverageplanningrecord")
    }
    assert "generated_service_county_candidates" in columns
    get_settings.cache_clear()
