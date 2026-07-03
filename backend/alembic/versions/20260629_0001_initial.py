"""initial schema

Revision ID: 20260629_0001
Revises:
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel

revision = "20260629_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("brand_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("business_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("phone", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("website", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("main_city", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(length=2), nullable=False),
        sa.Column("license_number", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("certified_operator", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_business_brand_name"), "business", ["brand_name"], unique=False)
    op.create_index(op.f("ix_business_company_name"), "business", ["company_name"], unique=False)
    op.create_index(op.f("ix_business_main_city"), "business", ["main_city"], unique=False)
    op.create_index(op.f("ix_business_state"), "business", ["state"], unique=False)

    op.create_table(
        "county",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(length=2), nullable=False),
        sa.Column("county_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_county_county_name"), "county", ["county_name"], unique=False)
    op.create_index(op.f("ix_county_state"), "county", ["state"], unique=False)
    op.create_index(op.f("ix_county_status"), "county", ["status"], unique=False)

    op.create_table(
        "setting",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setting_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("setting_value", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_setting_setting_key"), "setting", ["setting_key"], unique=True)

    op.create_table(
        "city",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("county_id", sa.Integer(), nullable=False),
        sa.Column("city_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(length=2), nullable=False),
        sa.Column("city_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["county_id"], ["county.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_city_city_name"), "city", ["city_name"], unique=False)
    op.create_index(op.f("ix_city_city_slug"), "city", ["city_slug"], unique=True)
    op.create_index(op.f("ix_city_county_id"), "city", ["county_id"], unique=False)
    op.create_index(op.f("ix_city_state"), "city", ["state"], unique=False)
    op.create_index(op.f("ix_city_status"), "city", ["status"], unique=False)

    op.create_table(
        "service",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("service_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("service_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("service_category", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("short_description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("long_description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_service_business_id"), "service", ["business_id"], unique=False)
    op.create_index(op.f("ix_service_service_category"), "service", ["service_category"], unique=False)
    op.create_index(op.f("ix_service_service_name"), "service", ["service_name"], unique=False)
    op.create_index(op.f("ix_service_service_slug"), "service", ["service_slug"], unique=True)
    op.create_index(op.f("ix_service_status"), "service", ["status"], unique=False)

    op.create_table(
        "generatedpage",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=True),
        sa.Column("county_id", sa.Integer(), nullable=True),
        sa.Column("page_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("page_title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("page_slug", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("meta_title", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("meta_description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("h1", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("content_body", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("wordpress_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.ForeignKeyConstraint(["city_id"], ["city.id"]),
        sa.ForeignKeyConstraint(["county_id"], ["county.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["service.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_generatedpage_business_id"), "generatedpage", ["business_id"], unique=False)
    op.create_index(op.f("ix_generatedpage_city_id"), "generatedpage", ["city_id"], unique=False)
    op.create_index(op.f("ix_generatedpage_county_id"), "generatedpage", ["county_id"], unique=False)
    op.create_index(op.f("ix_generatedpage_page_slug"), "generatedpage", ["page_slug"], unique=True)
    op.create_index(op.f("ix_generatedpage_page_type"), "generatedpage", ["page_type"], unique=False)
    op.create_index(op.f("ix_generatedpage_service_id"), "generatedpage", ["service_id"], unique=False)
    op.create_index(op.f("ix_generatedpage_status"), "generatedpage", ["status"], unique=False)

    op.create_table(
        "imagemetadata",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.Column("city_id", sa.Integer(), nullable=True),
        sa.Column("file_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("alt_text", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("caption", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("geo_city", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("geo_state", sqlmodel.sql.sqltypes.AutoString(length=2), nullable=True),
        sa.Column("image_prompt", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("exif_status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.ForeignKeyConstraint(["city_id"], ["city.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["service.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_imagemetadata_business_id"), "imagemetadata", ["business_id"], unique=False)
    op.create_index(op.f("ix_imagemetadata_city_id"), "imagemetadata", ["city_id"], unique=False)
    op.create_index(op.f("ix_imagemetadata_exif_status"), "imagemetadata", ["exif_status"], unique=False)
    op.create_index(op.f("ix_imagemetadata_file_name"), "imagemetadata", ["file_name"], unique=False)
    op.create_index(op.f("ix_imagemetadata_geo_city"), "imagemetadata", ["geo_city"], unique=False)
    op.create_index(op.f("ix_imagemetadata_geo_state"), "imagemetadata", ["geo_state"], unique=False)
    op.create_index(op.f("ix_imagemetadata_service_id"), "imagemetadata", ["service_id"], unique=False)


def downgrade() -> None:
    op.drop_table("imagemetadata")
    op.drop_table("generatedpage")
    op.drop_table("service")
    op.drop_table("city")
    op.drop_table("setting")
    op.drop_table("county")
    op.drop_table("business")
