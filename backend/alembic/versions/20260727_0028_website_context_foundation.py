"""Add website context and business identity foundation.

Revision ID: 20260727_0028
Revises: 20260725_0027
"""

from alembic import op
import sqlalchemy as sa
from datetime import UTC, datetime
from urllib.parse import urlparse


revision = "20260727_0028"
down_revision = "20260725_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "brand" not in tables:
        op.create_table(
            "brand",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.id"), nullable=False),
            sa.Column("brand_name", sa.String(), nullable=False),
            sa.Column("tagline", sa.String(), nullable=True),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("identity_settings", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.UniqueConstraint("business_id", "brand_name", name="uq_brand_business_name"),
        )
        op.create_index("ix_brand_business_id", "brand", ["business_id"])
        op.create_index("ix_brand_brand_name", "brand", ["brand_name"])
        op.create_index("ix_brand_status", "brand", ["status"])
    if "website" not in tables:
        op.create_table(
            "website",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("business.id"), nullable=False),
            sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brand.id"), nullable=True),
            sa.Column("website_name", sa.String(), nullable=False),
            sa.Column("domain", sa.String(), nullable=False),
            sa.Column("public_url", sa.String(), nullable=False),
            sa.Column("locale", sa.String(length=20), nullable=False),
            sa.Column("primary_language", sa.String(length=12), nullable=False),
            sa.Column("configuration", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.UniqueConstraint("business_id", "domain", name="uq_website_business_domain"),
        )
        for name in ("business_id", "brand_id", "website_name", "domain", "locale", "primary_language", "status"):
            op.create_index(f"ix_website_{name}", "website", [name])
    if "websiteidentity" not in tables:
        op.create_table(
            "websiteidentity",
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("website_id", sa.Integer(), sa.ForeignKey("website.id"), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("favicon_url", sa.String(), nullable=True),
            sa.Column("browser_icon_url", sa.String(), nullable=True),
            sa.Column("apple_touch_icon_url", sa.String(), nullable=True),
            sa.Column("social_identity_image_url", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("website_id", name="uq_websiteidentity_website"),
        )
        op.create_index("ix_websiteidentity_website_id", "websiteidentity", ["website_id"])
        op.create_index("ix_websiteidentity_status", "websiteidentity", ["status"])
    _backfill_website_records()
    generated_columns = {item["name"] for item in inspector.get_columns("generatedpage")}
    if "website_id" not in generated_columns:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("generatedpage") as batch:
                batch.add_column(sa.Column("website_id", sa.Integer(), nullable=True))
                batch.create_foreign_key(
                    "fk_generatedpage_website_id",
                    "website",
                    ["website_id"],
                    ["id"],
                )
                batch.create_index("ix_generatedpage_website_id", ["website_id"])
        else:
            op.add_column("generatedpage", sa.Column("website_id", sa.Integer(), nullable=True))
            op.create_foreign_key(
                "fk_generatedpage_website_id",
                "generatedpage",
                "website",
                ["website_id"],
                ["id"],
            )
            op.create_index("ix_generatedpage_website_id", "generatedpage", ["website_id"])
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE generatedpage SET website_id = "
            "(SELECT MIN(website.id) FROM website "
            "WHERE website.business_id = generatedpage.business_id AND website.status = 'active') "
            "WHERE website_id IS NULL"
        )
    )


def _backfill_website_records() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    business_table = sa.Table("business", metadata, autoload_with=bind)
    brand_table = sa.Table("brand", metadata, autoload_with=bind)
    website_table = sa.Table("website", metadata, autoload_with=bind)
    identity_table = sa.Table("websiteidentity", metadata, autoload_with=bind)
    now = datetime.now(UTC)
    businesses = bind.execute(sa.select(business_table)).mappings().all()
    for business in businesses:
        existing = bind.execute(
            sa.select(website_table.c.id).where(website_table.c.business_id == business["id"])
        ).first()
        if existing:
            continue
        is_flo_zone = business["company_name"] == "Flo-Zone Pest And Termite Solutions Inc"
        public_name = "Flo-Zone" if is_flo_zone else business.get("brand_name") or business["company_name"]
        brand_result = bind.execute(
            brand_table.insert().values(
                created_at=now,
                updated_at=now,
                business_id=business["id"],
                brand_name=public_name,
                tagline="Drywood termite specialists" if is_flo_zone else None,
                description=None,
                identity_settings={"brand_mark": "FZ"} if is_flo_zone else {},
                status="active",
            )
        )
        brand_id = brand_result.inserted_primary_key[0]
        raw_url = (business.get("website") or "").strip().rstrip("/")
        public_url = raw_url if "://" in raw_url else f"https://{raw_url}" if raw_url else ""
        domain = urlparse(public_url).netloc.lower() or f"business-{business['id']}.invalid"
        configuration = {
            "short_brand_name": "Flo-Zone",
            "state_name": "Florida",
            "state_slug": "fl",
            "license_label": "Florida License",
        } if is_flo_zone else {}
        website_result = bind.execute(
            website_table.insert().values(
                created_at=now,
                updated_at=now,
                business_id=business["id"],
                brand_id=brand_id,
                website_name=business.get("brand_name") or public_name,
                domain=domain,
                public_url=public_url,
                locale="en-US",
                primary_language="en",
                configuration=configuration,
                status="active",
            )
        )
        website_id = website_result.inserted_primary_key[0]
        bind.execute(
            identity_table.insert().values(
                created_at=now,
                updated_at=now,
                website_id=website_id,
                display_name=business.get("brand_name") or public_name,
                favicon_url=None,
                browser_icon_url=None,
                apple_touch_icon_url=None,
                social_identity_image_url=None,
                status="active",
                approved_at=None,
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT COUNT(*) FROM brand) + "
            "(SELECT COUNT(*) FROM website) + "
            "(SELECT COUNT(*) FROM websiteidentity) + "
            "(SELECT COUNT(*) FROM generatedpage WHERE website_id IS NOT NULL)"
        )
    ).scalar_one()
    if populated:
        raise RuntimeError(
            "Cannot downgrade while website-context records or page bindings exist; "
            "preserve them with a pre-migration Atlas Data backup."
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("generatedpage") as batch:
            batch.drop_index("ix_generatedpage_website_id")
            batch.drop_constraint("fk_generatedpage_website_id", type_="foreignkey")
            batch.drop_column("website_id")
    else:
        op.drop_index("ix_generatedpage_website_id", table_name="generatedpage")
        op.drop_constraint("fk_generatedpage_website_id", "generatedpage", type_="foreignkey")
        op.drop_column("generatedpage", "website_id")
    op.drop_table("websiteidentity")
    op.drop_table("website")
    op.drop_table("brand")
