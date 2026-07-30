from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlmodel import Session, select

from app.core.config import get_settings
from app.models import Brand, Business, SitePlan, Website


BACKEND = Path(__file__).parents[1]


def _config(monkeypatch, database: Path) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def test_0031_clean_disposable_database_upgrade(monkeypatch, tmp_path):
    database = tmp_path / "site-connections-clean.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260730_0031")
    tables = set(inspect(create_engine(f"sqlite:///{database.as_posix()}")).get_table_names())
    assert {
        "siteconnectionplanningrecord",
        "navigationset",
        "navigationitem",
        "internallinkintent",
    } <= tables
    get_settings.cache_clear()


def test_0031_backfills_existing_site_plan_without_changing_it(monkeypatch, tmp_path):
    database = tmp_path / "site-connections-populated.sqlite3"
    config = _config(monkeypatch, database)
    command.upgrade(config, "20260728_0030")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with Session(engine) as session:
        business = Business(
            company_name="Migration Sentinel",
            business_type="Test",
            phone="407-555-0100",
            email="migration@example.test",
            main_city="Orlando",
            state="FL",
        )
        session.add(business)
        session.flush()
        brand = Brand(
            business_id=business.id,
            brand_name="Migration Sentinel",
            status="active",
        )
        session.add(brand)
        session.flush()
        website = Website(
            business_id=business.id,
            brand_id=brand.id,
            website_name="Migration Sentinel",
            domain="migration.example.test",
            public_url="https://migration.example.test",
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
        session.commit()
        plan_id = plan.id

    command.upgrade(config, "20260730_0031")
    with engine.connect() as connection:
        sets = connection.exec_driver_sql(
            "SELECT set_type FROM navigationset WHERE site_plan_id = ? ORDER BY set_type",
            (plan_id,),
        ).scalars().all()
        records = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM siteconnectionplanningrecord WHERE site_plan_id = ?",
            (plan_id,),
        ).scalar_one()
        preserved = connection.exec_driver_sql(
            "SELECT plan_name FROM siteplan WHERE id = ?",
            (plan_id,),
        ).scalar_one()
    assert sets == ["footer", "primary", "utility"]
    assert records == 1
    assert preserved == "Preserved Plan"
    assert inspect(engine).get_table_names().count("siteplan") == 1
    get_settings.cache_clear()
