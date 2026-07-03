from collections.abc import Generator

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings

settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, pool_pre_ping=True, connect_args=connect_args)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    ensure_city_schema()
    ensure_generated_page_schema()
    ensure_image_metadata_schema()
    ensure_page_image_assignment_schema()


def ensure_city_schema() -> None:
    inspector = inspect(engine)
    if "city" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("city")}
    statements: list[str] = []

    if "priority" not in existing_columns:
        statements.append("ALTER TABLE city ADD COLUMN priority VARCHAR NOT NULL DEFAULT 'Medium'")
    if "is_primary_market" not in existing_columns:
        statements.append("ALTER TABLE city ADD COLUMN is_primary_market BOOLEAN NOT NULL DEFAULT false")
    if "notes" not in existing_columns:
        statements.append("ALTER TABLE city ADD COLUMN notes VARCHAR")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_city_priority ON city (priority)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_city_is_primary_market ON city (is_primary_market)"))


def ensure_generated_page_schema() -> None:
    inspector = inspect(engine)
    if "generatedpage" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("generatedpage")}
    statements: list[str] = []

    if "draft_content" not in existing_columns:
        statements.append("ALTER TABLE generatedpage ADD COLUMN draft_content JSON")
    if "generation_status" not in existing_columns:
        statements.append(
            "ALTER TABLE generatedpage ADD COLUMN generation_status VARCHAR NOT NULL DEFAULT 'not_generated'"
        )
    if "generated_at" not in existing_columns:
        statements.append("ALTER TABLE generatedpage ADD COLUMN generated_at TIMESTAMP")
    if "qa_status" not in existing_columns:
        statements.append(
            "ALTER TABLE generatedpage ADD COLUMN "
            "qa_status VARCHAR NOT NULL DEFAULT 'not_run'"
        )
    if "qa_result" not in existing_columns:
        statements.append("ALTER TABLE generatedpage ADD COLUMN qa_result JSON")
    if "qa_checked_at" not in existing_columns:
        statements.append("ALTER TABLE generatedpage ADD COLUMN qa_checked_at TIMESTAMP")
    if "internal_notes" not in existing_columns:
        statements.append("ALTER TABLE generatedpage ADD COLUMN internal_notes VARCHAR")
    if "last_reviewed_at" not in existing_columns:
        statements.append("ALTER TABLE generatedpage ADD COLUMN last_reviewed_at TIMESTAMP")
    if "last_reviewed_by" not in existing_columns:
        statements.append("ALTER TABLE generatedpage ADD COLUMN last_reviewed_by VARCHAR")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_generatedpage_generation_status "
                "ON generatedpage (generation_status)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_generatedpage_qa_status "
                "ON generatedpage (qa_status)"
            )
        )


def ensure_image_metadata_schema() -> None:
    inspector = inspect(engine)
    if "imagemetadata" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("imagemetadata")}
    statements: list[str] = []

    if "county_id" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN county_id INTEGER")
    if "image_title" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN image_title VARCHAR")
    if "reviewed_alt_text" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN reviewed_alt_text VARCHAR")
    if "asset_url" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN asset_url VARCHAR")
    if "thumbnail_url" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN thumbnail_url VARCHAR")
    if "optimized_url" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN optimized_url VARCHAR")
    if "original_filename" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN original_filename VARCHAR")
    if "stored_filename" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN stored_filename VARCHAR")
    if "notes" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN notes VARCHAR")
    if "focal_x" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN focal_x FLOAT NOT NULL DEFAULT 0.5")
    if "focal_y" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN focal_y FLOAT NOT NULL DEFAULT 0.5")
    if "image_role" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN image_role VARCHAR NOT NULL DEFAULT 'support'")
    if "review_status" not in existing_columns:
        statements.append("ALTER TABLE imagemetadata ADD COLUMN review_status VARCHAR NOT NULL DEFAULT 'pending'")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_imagemetadata_county_id ON imagemetadata (county_id)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_imagemetadata_image_role ON imagemetadata (image_role)")
        )
        connection.execute(
            text("CREATE INDEX IF NOT EXISTS ix_imagemetadata_review_status ON imagemetadata (review_status)")
        )


def ensure_page_image_assignment_schema() -> None:
    inspector = inspect(engine)
    if "pageimageassignment" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("pageimageassignment")
    }
    statements: list[str] = []

    if "override_focal_x" not in existing_columns:
        statements.append(
            "ALTER TABLE pageimageassignment ADD COLUMN override_focal_x FLOAT"
        )
    if "override_focal_y" not in existing_columns:
        statements.append(
            "ALTER TABLE pageimageassignment ADD COLUMN override_focal_y FLOAT"
        )
    if "override_alt_text" not in existing_columns:
        statements.append(
            "ALTER TABLE pageimageassignment ADD COLUMN override_alt_text VARCHAR"
        )
    if "display_preset" not in existing_columns:
        statements.append(
            "ALTER TABLE pageimageassignment ADD COLUMN "
            "display_preset VARCHAR NOT NULL DEFAULT 'hero_desktop'"
        )

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_pageimageassignment_display_preset "
                "ON pageimageassignment (display_preset)"
            )
        )
        if engine.dialect.name == "postgresql":
            connection.execute(
                text(
                    "ALTER TABLE pageimageassignment "
                    "DROP CONSTRAINT IF EXISTS uq_page_image_role"
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_page_image_role_media "
                    "ON pageimageassignment "
                    "(generated_page_id, image_metadata_id, image_role)"
                )
            )


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
