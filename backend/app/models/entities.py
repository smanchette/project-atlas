from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Column, Index, JSON, UniqueConstraint, text
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class Business(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    company_name: str = Field(index=True)
    brand_name: str | None = Field(default=None, index=True)
    business_type: str
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    main_city: str | None = Field(default=None, index=True)
    state: str = Field(default="FL", max_length=2, index=True)
    license_number: str | None = None
    certified_operator: str | None = None
    description: str | None = None


class Brand(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("business_id", "brand_name", name="uq_brand_business_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    brand_name: str = Field(index=True)
    tagline: str | None = None
    description: str | None = None
    identity_settings: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    status: str = Field(default="active", index=True)


class Website(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("business_id", "domain", name="uq_website_business_domain"),
    )

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    brand_id: int | None = Field(default=None, foreign_key="brand.id", index=True)
    website_name: str = Field(index=True)
    domain: str = Field(index=True)
    public_url: str
    locale: str = Field(default="en-US", max_length=20, index=True)
    primary_language: str = Field(default="en", max_length=12, index=True)
    configuration: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    status: str = Field(default="active", index=True)


class WebsiteIdentity(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("website_id", name="uq_websiteidentity_website"),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    display_name: str
    favicon_url: str | None = None
    browser_icon_url: str | None = None
    apple_touch_icon_url: str | None = None
    social_identity_image_url: str | None = None
    status: str = Field(default="draft", index=True)
    approved_at: datetime | None = None


class BrandAsset(TimestampMixin, table=True):
    """An approved, versioned visual-identity artifact owned by a Brand."""

    __table_args__ = (
        UniqueConstraint(
            "brand_id",
            "asset_key",
            "version",
            name="uq_brandasset_brand_key_version",
        ),
        CheckConstraint(
            "asset_type IN ('primary_logo','alternate_logo','brand_mark','favicon',"
            "'browser_icon','apple_touch_icon','open_graph_image')",
            name="ck_brandasset_type",
        ),
        CheckConstraint(
            "status IN ('draft','pending_review','approved','rejected','retired')",
            name="ck_brandasset_status",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    brand_id: int = Field(foreign_key="brand.id", index=True)
    asset_key: str = Field(max_length=120, index=True)
    version: int = Field(default=1, ge=1)
    asset_type: str = Field(index=True)
    variant_key: str = Field(default="default", max_length=80)
    purpose: str
    approved_usage: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    restrictions: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    accessibility_description: str
    original_filename: str
    stored_filename: str
    asset_url: str
    optimized_url: str | None = None
    thumbnail_url: str | None = None
    mime_type: str
    file_size: int = Field(ge=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    checksum_sha256: str = Field(max_length=64, index=True)
    provenance_type: str
    provenance_notes: str | None = None
    rights_status: str
    rights_holder: str | None = None
    rights_notes: str | None = None
    status: str = Field(default="draft", index=True)
    created_by: str
    approved_by: str | None = None
    approved_at: datetime | None = None
    retired_by: str | None = None
    retirement_rationale: str | None = None
    retired_at: datetime | None = None
    replaces_brand_asset_id: int | None = Field(
        default=None,
        foreign_key="brandasset.id",
        index=True,
    )


class WebsiteIdentityAssetAssignment(TimestampMixin, table=True):
    """A versioned Website Identity selection of an approved Brand Asset."""

    __table_args__ = (
        UniqueConstraint(
            "website_identity_id",
            "slot",
            "version",
            name="uq_identityassetassignment_identity_slot_version",
        ),
        CheckConstraint(
            "slot IN ('header_logo','footer_logo','favicon','browser_icon',"
            "'apple_touch_icon','open_graph_image')",
            name="ck_identityassetassignment_slot",
        ),
        CheckConstraint(
            "status IN ('active','replaced','retired')",
            name="ck_identityassetassignment_status",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_identity_id: int = Field(foreign_key="websiteidentity.id", index=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    brand_id: int = Field(foreign_key="brand.id", index=True)
    brand_asset_id: int = Field(foreign_key="brandasset.id", index=True)
    slot: str = Field(index=True)
    version: int = Field(default=1, ge=1)
    status: str = Field(default="active", index=True)
    assigned_by: str
    rationale: str | None = None
    assigned_at: datetime = Field(default_factory=utc_now, nullable=False)
    replaced_at: datetime | None = None


class Theme(TimestampMixin, table=True):
    """Versioned Website-owned presentation tokens with governed approval history."""

    __table_args__ = (
        UniqueConstraint(
            "website_id",
            "theme_key",
            "version",
            name="uq_theme_website_key_version",
        ),
        CheckConstraint(
            "lifecycle_status IN ('draft','available','retired')",
            name="ck_theme_lifecycle_status",
        ),
        CheckConstraint(
            "approval_status IN ('pending_review','approved','rejected')",
            name="ck_theme_approval_status",
        ),
        CheckConstraint(
            "provenance_type IN ('operator_configured','company_original','licensed','third_party')",
            name="ck_theme_provenance_type",
        ),
        CheckConstraint("version >= 1", name="ck_theme_version"),
        CheckConstraint(
            "token_contract_version >= 1",
            name="ck_theme_token_contract_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    brand_id: int = Field(foreign_key="brand.id", index=True)
    theme_key: str = Field(max_length=120, index=True)
    theme_name: str = Field(max_length=160)
    version: int = Field(default=1, ge=1)
    token_contract_version: int = Field(default=1, ge=1)
    design_tokens: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    token_hash_sha256: str = Field(max_length=64, index=True)
    description: str | None = Field(default=None, max_length=2000)
    lifecycle_status: str = Field(default="draft", max_length=24, index=True)
    approval_status: str = Field(default="pending_review", max_length=24, index=True)
    created_by: str = Field(max_length=160)
    provenance_type: str = Field(max_length=40, index=True)
    provenance_notes: str = Field(max_length=2000)
    approved_by: str | None = Field(default=None, max_length=160)
    approved_at: datetime | None = None
    retired_by: str | None = Field(default=None, max_length=160)
    retirement_rationale: str | None = Field(default=None, max_length=2000)
    retired_at: datetime | None = None
    replaces_theme_id: int | None = Field(
        default=None,
        foreign_key="theme.id",
        index=True,
    )


class WebsiteThemeSelection(TimestampMixin, table=True):
    """Durable, versioned selection history for one effective Theme per Website."""

    __table_args__ = (
        UniqueConstraint(
            "website_id",
            "version",
            name="uq_websitethemeselection_website_version",
        ),
        CheckConstraint(
            "status IN ('active','replaced','retired')",
            name="ck_websitethemeselection_status",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_websitethemeselection_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    theme_id: int = Field(foreign_key="theme.id", index=True)
    version: int = Field(default=1, ge=1)
    status: str = Field(default="active", max_length=24, index=True)
    selected_by: str = Field(max_length=160)
    rationale: str = Field(max_length=2000)
    selected_at: datetime = Field(default_factory=utc_now, nullable=False)
    replaced_at: datetime | None = None


class SitePlan(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("website_id", "plan_key", name="uq_siteplan_website_key"),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    plan_key: str = Field(default="primary", max_length=80, index=True)
    plan_name: str
    status: str = Field(default="draft", index=True)
    version: int = Field(default=1, ge=1)


class PlannedPage(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("website_id", "intended_slug", name="uq_plannedpage_website_slug"),
        UniqueConstraint("generated_page_id", name="uq_plannedpage_generated_page"),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    page_type: str = Field(index=True)
    working_name: str
    intended_slug: str = Field(index=True)
    service_id: int | None = Field(default=None, foreign_key="service.id", index=True)
    city_id: int | None = Field(default=None, foreign_key="city.id", index=True)
    county_id: int | None = Field(default=None, foreign_key="county.id", index=True)
    parent_planned_page_id: int | None = Field(
        default=None,
        foreign_key="plannedpage.id",
        index=True,
    )
    planning_status: str = Field(default="planned", index=True)
    generated_page_id: int | None = Field(
        default=None,
        foreign_key="generatedpage.id",
        index=True,
    )


class PlanningRecord(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("planned_page_id", name="uq_planningrecord_planned_page"),
    )

    id: int | None = Field(default=None, primary_key=True)
    planned_page_id: int = Field(foreign_key="plannedpage.id", index=True)
    generated_answers: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    operator_overrides: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    source_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    confidence_score: float = Field(default=0.0, ge=0, le=1)
    confidence_level: str = Field(default="low", index=True)
    missing_information: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    improvement_recommendations: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    generated_at: datetime = Field(default_factory=utc_now, nullable=False)
    reviewed_at: datetime | None = None


class WebsiteMediaPlanningRecord(TimestampMixin, table=True):
    """Versioned Atlas-generated page-media suggestions for one Website Site Plan."""

    __table_args__ = (
        CheckConstraint(
            "version >= 1",
            name="ck_websitemediaplanningrecord_version",
        ),
        UniqueConstraint(
            "site_plan_id",
            "version",
            name="uq_websitemediaplanningrecord_plan_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    version: int = Field(default=1, ge=1)
    algorithm_version: str = Field(max_length=80, index=True)
    generated_media_suggestions: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    source_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    source_hash: str = Field(max_length=64, index=True)
    generated_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    replaces_record_id: int | None = Field(
        default=None,
        foreign_key="websitemediaplanningrecord.id",
        index=True,
    )


class PlannedPageMediaRequirement(TimestampMixin, table=True):
    """One versioned, operator-governed media placement contract for a Planned Page."""

    __table_args__ = (
        CheckConstraint(
            "contract_version >= 1",
            name="ck_plannedpagemediarequirement_contract_version",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_plannedpagemediarequirement_version",
        ),
        CheckConstraint(
            "minimum_width >= 1",
            name="ck_plannedpagemediarequirement_minimum_width",
        ),
        CheckConstraint(
            "minimum_height >= 1",
            name="ck_plannedpagemediarequirement_minimum_height",
        ),
        CheckConstraint(
            "requirement_state IN ('required','advisory','excluded','deferred')",
            name="ck_plannedpagemediarequirement_state",
        ),
        CheckConstraint(
            "lifecycle_status IN ('active','superseded','retired')",
            name="ck_plannedpagemediarequirement_lifecycle",
        ),
        CheckConstraint(
            "(version = 1 AND replaces_requirement_id IS NULL) "
            "OR (version > 1 AND replaces_requirement_id IS NOT NULL)",
            name="ck_plannedpagemediarequirement_replacement",
        ),
        CheckConstraint(
            "contract_version < 2 OR "
            "(target_component_instance_key IS NOT NULL "
            "AND length(trim(target_component_instance_key)) > 0)",
            name="ck_plannedpagemediarequirement_v2_target",
        ),
        UniqueConstraint(
            "planned_page_id",
            "placement_key",
            "version",
            name="uq_plannedpagemediarequirement_page_key_version",
        ),
        Index(
            "uq_plannedpagemediarequirement_active_placement",
            "planned_page_id",
            "placement_key",
            unique=True,
            postgresql_where=text("lifecycle_status = 'active'"),
            sqlite_where=text("lifecycle_status = 'active'"),
        ),
        Index(
            "uq_plannedpagemediarequirement_active_target",
            "planned_page_id",
            "target_component_instance_key",
            unique=True,
            postgresql_where=text(
                "lifecycle_status = 'active' "
                "AND target_component_instance_key IS NOT NULL"
            ),
            sqlite_where=text(
                "lifecycle_status = 'active' "
                "AND target_component_instance_key IS NOT NULL"
            ),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    planned_page_id: int = Field(foreign_key="plannedpage.id", index=True)
    planning_record_id: int = Field(
        foreign_key="websitemediaplanningrecord.id",
        index=True,
    )
    component_or_section: str = Field(max_length=120, index=True)
    target_component_instance_key: str | None = Field(
        default=None,
        max_length=200,
        index=True,
    )
    placement_key: str = Field(max_length=120, index=True)
    contract_version: int = Field(default=1, ge=1)
    version: int = Field(default=1, ge=1)
    requirement_state: str = Field(index=True)
    purpose: str
    customer_outcome: str
    intended_subject: str
    orientation: str = Field(max_length=40)
    aspect_ratio: str = Field(max_length=40)
    minimum_width: int = Field(ge=1)
    minimum_height: int = Field(ge=1)
    crop_intent: str
    focal_point_intent: str
    responsive_behavior: str
    accessibility_intent: str
    caption_intent: str | None = None
    approved_source_constraints: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    permitted_reuse_policy: str
    replacement_policy: str
    compatible_page_types: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    source_suggestion_key: str | None = Field(default=None, max_length=200)
    decided_by: str = Field(max_length=160)
    rationale: str
    decided_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    lifecycle_status: str = Field(default="active", max_length=24, index=True)
    replaces_requirement_id: int | None = Field(
        default=None,
        foreign_key="plannedpagemediarequirement.id",
        index=True,
    )


class SiteConnectionPlanningRecord(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint(
            "site_plan_id",
            name="uq_siteconnectionplanningrecord_site_plan",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    generated_navigation_suggestions: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    generated_internal_link_suggestions: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    source_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    generated_at: datetime = Field(default_factory=utc_now, nullable=False)


class NavigationSet(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "(decision_version IS NULL AND decided_by IS NULL AND rationale IS NULL "
            "AND decided_at IS NULL AND source_suggestion_key IS NULL) "
            "OR (decision_version IS NOT NULL "
            "AND decision_version >= 1 AND decided_by IS NOT NULL "
            "AND rationale IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_navigationset_decision_provenance",
        ),
        UniqueConstraint(
            "site_plan_id",
            "set_type",
            name="uq_navigationset_site_plan_type",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    set_type: str = Field(max_length=24, index=True)
    label: str
    status: str = Field(default="draft", max_length=24, index=True)
    version: int = Field(default=1, ge=1)
    rationale: str | None = None
    decided_by: str | None = None
    decision_version: int | None = Field(default=None, ge=1)
    decided_at: datetime | None = Field(default=None, index=True)
    source_suggestion_key: str | None = Field(default=None, max_length=200)


class NavigationItem(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "(decision_version IS NULL AND decided_by IS NULL AND rationale IS NULL "
            "AND decided_at IS NULL AND source_suggestion_key IS NULL) "
            "OR (decision_version IS NOT NULL "
            "AND decision_version >= 1 AND decided_by IS NOT NULL "
            "AND rationale IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_navigationitem_decision_provenance",
        ),
        UniqueConstraint(
            "navigation_set_id",
            "target_planned_page_id",
            name="uq_navigationitem_set_target",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    navigation_set_id: int = Field(foreign_key="navigationset.id", index=True)
    target_planned_page_id: int = Field(foreign_key="plannedpage.id", index=True)
    parent_navigation_item_id: int | None = Field(
        default=None,
        foreign_key="navigationitem.id",
        index=True,
    )
    label: str
    position: int = Field(default=0, ge=0)
    status: str = Field(default="active", max_length=24, index=True)
    rationale: str | None = None
    decided_by: str | None = None
    decision_version: int | None = Field(default=None, ge=1)
    decided_at: datetime | None = Field(default=None, index=True)
    source_suggestion_key: str | None = Field(default=None, max_length=200)


class InternalLinkIntent(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "(decision_version IS NULL AND decided_by IS NULL AND rationale IS NULL "
            "AND decided_at IS NULL AND source_suggestion_key IS NULL) "
            "OR (decision_version IS NOT NULL "
            "AND decision_version >= 1 AND decided_by IS NOT NULL "
            "AND rationale IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_internallinkintent_decision_provenance",
        ),
        UniqueConstraint(
            "site_plan_id",
            "source_planned_page_id",
            "target_planned_page_id",
            "relationship_type",
            name="uq_internallinkintent_plan_edge_type",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    source_planned_page_id: int = Field(foreign_key="plannedpage.id", index=True)
    target_planned_page_id: int = Field(foreign_key="plannedpage.id", index=True)
    purpose: str
    relationship_type: str = Field(max_length=40, index=True)
    anchor_guidance: str | None = None
    approval_state: str = Field(default="proposed", max_length=24, index=True)
    rationale: str | None = None
    decided_by: str | None = None
    decision_version: int | None = Field(default=None, ge=1)
    decided_at: datetime | None = Field(default=None, index=True)
    source_suggestion_key: str | None = Field(default=None, max_length=200)


class SemanticComponentDefinition(TimestampMixin, table=True):
    """Versioned, reusable presentation contract that never owns business facts."""

    __table_args__ = (
        UniqueConstraint(
            "component_key",
            "contract_version",
            name="uq_semanticcomponentdefinition_key_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    component_key: str = Field(max_length=80, index=True)
    contract_version: int = Field(default=1, ge=1)
    purpose: str
    required_inputs: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    customer_outcome: str
    compatible_page_types: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    supported_variants: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    accessibility_requirements: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    status: str = Field(default="active", max_length=24, index=True)


class PageComposition(TimestampMixin, table=True):
    """Website-owned composition choices bound to approved Atlas source records."""

    __table_args__ = (
        UniqueConstraint(
            "planned_page_id",
            name="uq_pagecomposition_planned_page",
        ),
        UniqueConstraint(
            "generated_page_id",
            name="uq_pagecomposition_generated_page",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    planned_page_id: int = Field(foreign_key="plannedpage.id", index=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    composition_version: int = Field(default=1, ge=1)
    generated_components: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    operator_decisions: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    source_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    source_hash: str = Field(max_length=64, index=True)
    status: str = Field(default="current", max_length=24, index=True)
    generated_at: datetime = Field(default_factory=utc_now, nullable=False)
    decided_by: str | None = None
    decided_at: datetime | None = None


class WebsiteCoveragePlanningRecord(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint(
            "site_plan_id",
            name="uq_websitecoverageplanningrecord_site_plan",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    generated_service_candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    generated_county_candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    generated_city_candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    generated_matrix_candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    generated_service_county_candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    generated_supporting_page_candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    source_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    generated_at: datetime = Field(default_factory=utc_now, nullable=False)


class WebsiteServiceCoverageDecision(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ('included','excluded','deferred')",
            name="ck_websiteservicecoveragedecision_status",
        ),
        CheckConstraint(
            "decision_version >= 1",
            name="ck_websiteservicecoveragedecision_version",
        ),
        UniqueConstraint(
            "website_id",
            "service_id",
            name="uq_websiteservicecoveragedecision_website_service",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    service_id: int = Field(foreign_key="service.id", index=True)
    status: str = Field(max_length=24, index=True)
    rationale: str | None = None
    decided_by: str
    decision_version: int = Field(default=1, ge=1)
    decided_at: datetime = Field(default_factory=utc_now, nullable=False)


class WebsiteCountyCoverageDecision(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ('included','excluded','deferred')",
            name="ck_websitecountycoveragedecision_status",
        ),
        CheckConstraint(
            "decision_version >= 1",
            name="ck_websitecountycoveragedecision_version",
        ),
        UniqueConstraint(
            "website_id",
            "county_id",
            name="uq_websitecountycoveragedecision_website_county",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    county_id: int = Field(foreign_key="county.id", index=True)
    status: str = Field(max_length=24, index=True)
    page_appropriate: bool = Field(default=False, index=True)
    rationale: str | None = None
    decided_by: str
    decision_version: int = Field(default=1, ge=1)
    decided_at: datetime = Field(default_factory=utc_now, nullable=False)


class WebsiteCityCoverageDecision(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ('included','excluded','deferred')",
            name="ck_websitecitycoveragedecision_status",
        ),
        CheckConstraint(
            "decision_version >= 1",
            name="ck_websitecitycoveragedecision_version",
        ),
        UniqueConstraint(
            "website_id",
            "city_id",
            name="uq_websitecitycoveragedecision_website_city",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    city_id: int = Field(foreign_key="city.id", index=True)
    status: str = Field(max_length=24, index=True)
    rationale: str | None = None
    decided_by: str
    decision_version: int = Field(default=1, ge=1)
    decided_at: datetime = Field(default_factory=utc_now, nullable=False)


class WebsiteServiceCityCoverageDecision(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ('included','excluded','deferred')",
            name="ck_websiteservicecitycoveragedecision_status",
        ),
        CheckConstraint(
            "decision_version >= 1",
            name="ck_websiteservicecitycoveragedecision_version",
        ),
        UniqueConstraint(
            "website_id",
            "service_id",
            "city_id",
            name="uq_websiteservicecitycoveragedecision_website_service_city",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    service_id: int = Field(foreign_key="service.id", index=True)
    city_id: int = Field(foreign_key="city.id", index=True)
    status: str = Field(max_length=24, index=True)
    rationale: str | None = None
    decided_by: str
    decision_version: int = Field(default=1, ge=1)
    decided_at: datetime = Field(default_factory=utc_now, nullable=False)


class WebsiteServiceCountyCoverageDecision(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ('included','excluded','deferred')",
            name="ck_websiteservicecountycoveragedecision_status",
        ),
        CheckConstraint(
            "decision_version >= 1",
            name="ck_websiteservicecountycoveragedecision_version",
        ),
        UniqueConstraint(
            "website_id",
            "service_id",
            "county_id",
            name="uq_websiteservicecountycoveragedecision_website_service_county",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    service_id: int = Field(foreign_key="service.id", index=True)
    county_id: int = Field(foreign_key="county.id", index=True)
    status: str = Field(max_length=24, index=True)
    rationale: str | None = None
    decided_by: str
    decision_version: int = Field(default=1, ge=1)
    decided_at: datetime = Field(default_factory=utc_now, nullable=False)


class SupportingPageAuthorization(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ('included','excluded','deferred')",
            name="ck_supportingpageauthorization_status",
        ),
        CheckConstraint(
            "decision_version >= 1",
            name="ck_supportingpageauthorization_version",
        ),
        UniqueConstraint(
            "planned_page_id",
            name="uq_supportingpageauthorization_planned_page",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    planned_page_id: int = Field(foreign_key="plannedpage.id", index=True)
    status: str = Field(max_length=24, index=True)
    rationale: str
    decided_by: str
    decision_version: int = Field(default=1, ge=1)
    decided_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)


class PreDraftDistinctnessBrief(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint(
            "planned_page_id",
            name="uq_predraftdistinctnessbrief_planned_page",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    planned_page_id: int = Field(foreign_key="plannedpage.id", index=True)
    algorithm_version: str = Field(max_length=80, index=True)
    intended_audience: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    search_intent: str
    approved_fact_identities: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    approved_knowledge_identities: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    conversion_purpose: str
    required_page_specific_value: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    proposed_unique_elements: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    related_planned_page_ids: list[int] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    competing_planned_page_ids: list[int] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    source_binding: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    brief_hash: str = Field(max_length=64, index=True)
    generated_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)


class DraftingEligibilityAssessment(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ('eligible','blocked_missing_required_information',"
            "'insufficient_local_value','semantic_duplication',"
            "'consolidation_recommended','deferred','excluded_by_coverage',"
            "'stale_assessment')",
            name="ck_draftingeligibilityassessment_status",
        ),
        UniqueConstraint(
            "planned_page_id",
            name="uq_draftingeligibilityassessment_planned_page",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    planned_page_id: int = Field(foreign_key="plannedpage.id", index=True)
    status: str = Field(index=True)
    algorithm_version: str = Field(max_length=80, index=True)
    coverage_binding: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    expected_inventory_binding: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    planning_record_binding: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    distinctness_brief_binding: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    approved_source_identities: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    evidence: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    local_value_findings: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    semantic_findings: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    reasons: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    assessed_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)


class DraftingEligibilityDisposition(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "decision IN ('accepted','exception_approved','deferred','consolidate')",
            name="ck_draftingeligibilitydisposition_decision",
        ),
        CheckConstraint(
            "decision_version >= 1",
            name="ck_draftingeligibilitydisposition_version",
        ),
        UniqueConstraint(
            "planned_page_id",
            name="uq_draftingeligibilitydisposition_planned_page",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    planned_page_id: int = Field(foreign_key="plannedpage.id", index=True)
    assessment_id: int = Field(
        foreign_key="draftingeligibilityassessment.id", index=True
    )
    decision: str = Field(index=True)
    rationale: str
    decided_by: str
    accepted_exception: bool = Field(default=False)
    decision_version: int = Field(default=1, ge=1)
    decided_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)


class WebsiteDraftGenerationRun(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "status IN ('preparing','running','interrupted','completed',"
            "'completed_with_errors')",
            name="ck_websitedraftgenerationrun_status",
        ),
        UniqueConstraint(
            "site_plan_id",
            "manifest_hash",
            name="uq_websitedraftgenerationrun_plan_manifest",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    manifest_hash: str = Field(max_length=64, index=True)
    eligibility_algorithm_version: str = Field(max_length=80, index=True)
    status: str = Field(default="preparing", max_length=32, index=True)
    manifest_snapshot: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    expected_count: int = Field(default=0, ge=0)
    eligible_count: int = Field(default=0, ge=0)
    generated_count: int = Field(default=0, ge=0)
    already_drafted_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    deferred_count: int = Field(default=0, ge=0)
    excluded_count: int = Field(default=0, ge=0)
    stale_count: int = Field(default=0, ge=0)
    consolidation_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    processed_count: int = Field(default=0, ge=0)
    progress_message: str = Field(default="Preparing inventory...")
    started_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    last_resumed_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class WebsiteDraftGenerationItem(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint(
            "manifest_classification IN ('eligible','blocked','excluded','deferred',"
            "'stale','consolidation_recommended')",
            name="ck_websitedraftgenerationitem_classification",
        ),
        CheckConstraint(
            "outcome IN ('pending','generated','already_drafted','blocked','deferred',"
            "'excluded','stale','consolidation_recommended','unsupported','error')",
            name="ck_websitedraftgenerationitem_outcome",
        ),
        UniqueConstraint(
            "run_id",
            "inventory_key",
            name="uq_websitedraftgenerationitem_run_inventory",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="websitedraftgenerationrun.id", index=True)
    website_id: int = Field(foreign_key="website.id", index=True)
    site_plan_id: int = Field(foreign_key="siteplan.id", index=True)
    planned_page_id: int | None = Field(
        default=None, foreign_key="plannedpage.id", index=True
    )
    generated_page_id: int | None = Field(
        default=None, foreign_key="generatedpage.id", index=True
    )
    inventory_key: str = Field(max_length=180, index=True)
    ordinal: int = Field(ge=1)
    page_type: str = Field(max_length=40, index=True)
    working_name: str
    manifest_classification: str = Field(max_length=40, index=True)
    outcome: str = Field(default="pending", max_length=40, index=True)
    reasons: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    assessment_id: int | None = Field(
        default=None, foreign_key="draftingeligibilityassessment.id", index=True
    )
    assessment_binding: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    generated_content_hash: str | None = Field(default=None, max_length=64)
    attempt_count: int = Field(default=0, ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class Service(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    service_name: str = Field(index=True)
    service_slug: str = Field(index=True, unique=True)
    service_category: str | None = Field(default=None, index=True)
    short_description: str | None = None
    long_description: str | None = None
    status: str = Field(default="active", index=True)


class County(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    state: str = Field(default="FL", max_length=2, index=True)
    county_name: str = Field(index=True)
    status: str = Field(default="active", index=True)


class City(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    county_id: int = Field(foreign_key="county.id", index=True)
    city_name: str = Field(index=True)
    state: str = Field(default="FL", max_length=2, index=True)
    city_slug: str = Field(index=True, unique=True)
    priority: str = Field(default="Medium", index=True)
    is_primary_market: bool = Field(default=False, index=True)
    notes: str | None = None
    status: str = Field(default="active", index=True)


class GeneratedPage(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("website_id", "page_slug", name="uq_generatedpage_website_slug"),
    )

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    website_id: int | None = Field(default=None, foreign_key="website.id", index=True)
    service_id: int | None = Field(default=None, foreign_key="service.id", index=True)
    city_id: int | None = Field(default=None, foreign_key="city.id", index=True)
    county_id: int | None = Field(default=None, foreign_key="county.id", index=True)
    page_type: str = Field(index=True)
    page_title: str
    page_slug: str = Field(index=True)
    meta_title: str | None = None
    meta_description: str | None = None
    h1: str | None = None
    content_body: str | None = None
    draft_content: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    generation_status: str = Field(default="not_generated", index=True)
    generated_at: datetime | None = None
    qa_status: str = Field(default="not_run", index=True)
    qa_result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    qa_checked_at: datetime | None = None
    internal_notes: str | None = None
    last_reviewed_at: datetime | None = None
    last_reviewed_by: str | None = None
    status: str = Field(default="draft", index=True)
    wordpress_post_id: int | None = Field(default=None, index=True)
    wordpress_url: str | None = None
    wordpress_status: str | None = Field(default=None, index=True)
    wordpress_created_at: datetime | None = None
    last_wordpress_sync_at: datetime | None = None


class ApprovalAudit(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id",
            "approved_at",
            "draft_hash_at_approval",
            name="uq_approvalaudit_page_time_hash",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    approved_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    approved_by: str | None = None
    qa_status_at_approval: str = Field(index=True)
    qa_checked_at: datetime
    qa_result_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    draft_hash_at_approval: str = Field(index=True)
    page_status_before: str
    page_status_after: str


class GeneratedPageRevision(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id",
            "created_at",
            "draft_hash_after",
            name="uq_pagerevision_page_time_hash",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    created_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    created_by: str | None = None
    reason: str | None = None
    draft_hash_before: str
    draft_hash_after: str = Field(index=True)
    draft_content_before: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    draft_content_after: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    changed_fields: list[str] = Field(sa_column=Column(JSON, nullable=False))


class WordPressDraftAudit(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id",
            "attempted_at",
            "payload_hash",
            name="uq_wordpressdraftaudit_page_time_hash",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    action_type: str = Field(default="create_draft", index=True)
    status: str = Field(index=True)
    wordpress_site_url: str
    wordpress_post_id: int | None = Field(default=None, index=True)
    wordpress_status: str | None = Field(default=None, index=True)
    slug: str = Field(index=True)
    payload_hash: str = Field(index=True)
    qa_status_at_attempt: str
    qa_checked_at: datetime | None = None
    draft_hash_at_attempt: str = Field(index=True)
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    error_message: str | None = None


class WordPressPublishAudit(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id", "attempted_at", "publish_payload_hash",
            name="uq_wordpresspublishaudit_page_time_hash",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    wordpress_site_url: str
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    status: str = Field(default="pending", index=True)
    pre_publish_wordpress_status: str | None = None
    returned_wordpress_status: str | None = None
    returned_wordpress_url: str | None = None
    current_draft_payload_hash: str = Field(index=True)
    latest_update_audit_id: int | None = Field(default=None, foreign_key="wordpressdraftaudit.id")
    latest_update_audit_hash: str
    publish_payload_hash: str = Field(index=True)
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    backup_file_name: str
    error_message: str | None = None


class WordPressQualityReview(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id",
            name="uq_wordpressqualityreview_generated_page_id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    review_status: str = Field(default="not_reviewed", index=True)
    reviewer_notes: str | None = None
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None


class ImageMetadata(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint("focal_x >= 0 AND focal_x <= 1", name="ck_imagemetadata_focal_x_range"),
        CheckConstraint("focal_y >= 0 AND focal_y <= 1", name="ck_imagemetadata_focal_y_range"),
        CheckConstraint(
            "governance_status IN ('legacy_unverified','pending_review','approved','rejected','retired')",
            name="ck_imagemetadata_governance_status",
        ),
        CheckConstraint(
            "gps_metadata_status IS NULL OR gps_metadata_status IN "
            "('absent','stripped','present_unverified','verified_authorized')",
            name="ck_imagemetadata_gps_status",
        ),
        CheckConstraint(
            "media_version IS NULL OR media_version >= 1",
            name="ck_imagemetadata_media_version",
        ),
        CheckConstraint(
            "approval_version IS NULL OR approval_version >= 1",
            name="ck_imagemetadata_approval_version",
        ),
        CheckConstraint(
            "(media_version IS NULL AND replaces_image_metadata_id IS NULL) OR "
            "(media_version = 1 AND replaces_image_metadata_id IS NULL) OR "
            "(media_version > 1 AND replaces_image_metadata_id IS NOT NULL)",
            name="ck_imagemetadata_replacement",
        ),
        CheckConstraint(
            "(file_size IS NULL AND width IS NULL AND height IS NULL "
            "AND mime_type IS NULL AND checksum_sha256 IS NULL) OR "
            "(file_size >= 1 AND width >= 1 AND height >= 1 "
            "AND mime_type IS NOT NULL AND checksum_sha256 IS NOT NULL "
            "AND length(checksum_sha256) = 64)",
            name="ck_imagemetadata_binary_identity",
        ),
        CheckConstraint(
            "governance_status = 'legacy_unverified' OR "
            "(website_id IS NOT NULL AND media_key IS NOT NULL "
            "AND media_version IS NOT NULL AND managed_storage_path IS NOT NULL "
            "AND acquisition_source IS NOT NULL AND creator_source_identity IS NOT NULL "
            "AND provenance_type IS NOT NULL AND provenance_notes IS NOT NULL "
            "AND rights_status IS NOT NULL AND rights_holder IS NOT NULL "
            "AND rights_notes IS NOT NULL AND approved_usage IS NOT NULL "
            "AND prohibited_usage IS NOT NULL AND permitted_placement_keys IS NOT NULL "
            "AND accessibility_intent IS NOT NULL AND created_by IS NOT NULL "
            "AND file_size IS NOT NULL)",
            name="ck_imagemetadata_governed_completeness",
        ),
        CheckConstraint(
            "governance_status NOT IN ('approved','retired') OR "
            "(approval_version IS NOT NULL AND approved_by IS NOT NULL "
            "AND approved_at IS NOT NULL)",
            name="ck_imagemetadata_approval_provenance",
        ),
        CheckConstraint(
            "governance_status != 'retired' OR "
            "(retired_by IS NOT NULL AND retirement_rationale IS NOT NULL "
            "AND retired_at IS NOT NULL)",
            name="ck_imagemetadata_retirement_provenance",
        ),
        CheckConstraint(
            "gps_metadata_status != 'verified_authorized' OR "
            "(gps_metadata IS NOT NULL AND gps_authorized_by IS NOT NULL "
            "AND gps_authorized_at IS NOT NULL AND gps_authorization_notes IS NOT NULL)",
            name="ck_imagemetadata_gps_authorization",
        ),
        UniqueConstraint(
            "website_id",
            "media_key",
            "media_version",
            name="uq_imagemetadata_website_key_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    website_id: int | None = Field(default=None, foreign_key="website.id", index=True)
    service_id: int | None = Field(default=None, foreign_key="service.id", index=True)
    city_id: int | None = Field(default=None, foreign_key="city.id", index=True)
    county_id: int | None = Field(default=None, foreign_key="county.id", index=True)
    media_key: str | None = Field(default=None, max_length=120, index=True)
    media_version: int | None = Field(default=None, ge=1)
    file_name: str = Field(index=True)
    image_title: str | None = None
    alt_text: str | None = None
    reviewed_alt_text: str | None = None
    caption: str | None = None
    asset_url: str | None = None
    thumbnail_url: str | None = None
    optimized_url: str | None = None
    original_filename: str | None = None
    stored_filename: str | None = None
    mime_type: str | None = None
    file_size: int | None = Field(default=None, ge=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    checksum_sha256: str | None = Field(default=None, max_length=64, index=True)
    managed_storage_path: str | None = None
    acquisition_source: str | None = None
    creator_source_identity: str | None = None
    created_by: str | None = None
    provenance_type: str | None = Field(default=None, index=True)
    provenance_notes: str | None = None
    rights_status: str | None = Field(default=None, index=True)
    rights_holder: str | None = None
    rights_notes: str | None = None
    approved_usage: list[str] | None = Field(default=None, sa_column=Column(JSON))
    prohibited_usage: list[str] | None = Field(default=None, sa_column=Column(JSON))
    permitted_placement_keys: list[str] | None = Field(default=None, sa_column=Column(JSON))
    accessibility_intent: str | None = None
    governance_status: str = Field(default="legacy_unverified", max_length=32, index=True)
    approval_version: int | None = Field(default=None, ge=1)
    approved_by: str | None = None
    approved_at: datetime | None = Field(default=None, index=True)
    retired_by: str | None = None
    retirement_rationale: str | None = None
    retired_at: datetime | None = Field(default=None, index=True)
    replaces_image_metadata_id: int | None = Field(
        default=None,
        foreign_key="imagemetadata.id",
        index=True,
    )
    gps_metadata_status: str | None = Field(default=None, max_length=32, index=True)
    gps_metadata: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    gps_authorized_by: str | None = None
    gps_authorized_at: datetime | None = Field(default=None, index=True)
    gps_authorization_notes: str | None = None
    notes: str | None = None
    focal_x: float = Field(default=0.5, ge=0, le=1)
    focal_y: float = Field(default=0.5, ge=0, le=1)
    image_role: str = Field(default="support", index=True)
    review_status: str = Field(default="pending", index=True)
    geo_city: str | None = Field(default=None, index=True)
    geo_state: str | None = Field(default="FL", max_length=2, index=True)
    image_prompt: str | None = None
    exif_status: str = Field(default="pending", index=True)
    wordpress_media_id: int | None = Field(default=None, index=True)
    wordpress_media_url: str | None = None
    wordpress_media_status: str | None = Field(default=None, index=True)
    wordpress_media_checksum: str | None = Field(default=None, index=True)
    wordpress_media_uploaded_at: datetime | None = None
    last_wordpress_media_sync_at: datetime | None = None


class WordPressMediaSyncAudit(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("generated_page_id", "attempted_at", "source_checksum", name="uq_wordpressmediasyncaudit_page_time_checksum"),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    image_metadata_id: int = Field(foreign_key="imagemetadata.id", index=True)
    page_image_assignment_id: int = Field(foreign_key="pageimageassignment.id", index=True)
    wordpress_post_id: int = Field(index=True)
    wordpress_media_id: int | None = Field(default=None, index=True)
    action_type: str = Field(default="upload_media", index=True)
    status: str = Field(default="pending", index=True)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    wordpress_site_url: str
    source_file_name: str
    source_mime_type: str
    source_file_size: int
    source_width: int
    source_height: int
    source_checksum: str = Field(index=True)
    alt_text: str
    returned_media_url: str | None = None
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    backup_file_name: str
    error_message: str | None = None


class WordPressMetadataState(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("generated_page_id", name="uq_wordpressmetadatastate_generated_page_id"),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    schema_version: str = Field(default="1.0")
    status: str = Field(default="not_applied", index=True)
    payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    payload_hash: str | None = Field(default=None, index=True)
    wordpress_revision: str | None = None
    last_verified_at: datetime | None = None
    last_wordpress_metadata_sync_at: datetime | None = None


class WordPressMetadataSyncAudit(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id", "attempted_at", "payload_hash",
            name="uq_wordpressmetadatasyncaudit_page_time_hash",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    action_type: str = Field(index=True)
    status: str = Field(default="pending", index=True)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    wordpress_site_url: str
    payload_hash: str = Field(index=True)
    payload_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    previous_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    returned_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    data_backup_file_name: str
    wordpress_backup_reference: str
    plugin_version: str
    error_message: str | None = None


class WordPressDeploymentAudit(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint("action_type = 'install_metadata_bridge'", name="ck_wordpressdeploymentaudit_action"),
        CheckConstraint(
            "status IN ('installation_authorized','awaiting_manual_installation','manual_installation_reported','verification_pending','verified','verification_failed','reconciliation_required','failed')",
            name="ck_wordpressdeploymentaudit_status",
        ),
        UniqueConstraint("deployment_key", name="uq_wordpressdeploymentaudit_deployment_key"),
        UniqueConstraint("authorization_jti", name="uq_wordpressdeploymentaudit_authorization_jti"),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    action_type: str = Field(max_length=64, index=True)
    status: str = Field(max_length=40, index=True)
    operator: str = Field(max_length=200)
    shawn_approved_at: datetime
    confirmation_phrase_hash: str = Field(max_length=64)
    atlas_version: str = Field(max_length=32)
    atlas_commit: str = Field(max_length=40)
    atlas_tag: str = Field(max_length=32)
    plugin_version: str = Field(max_length=32)
    plugin_slug: str = Field(max_length=100)
    plugin_path: str = Field(max_length=255)
    zip_file_name: str = Field(max_length=255)
    zip_sha256: str = Field(max_length=64)
    plugin_source_sha256: str = Field(max_length=64)
    installation_transport: str = Field(default="manual_wordpress_admin_upload", max_length=64)
    backup_reference: str = Field(max_length=255, index=True)
    backup_completed_at: datetime
    backup_deadline: datetime = Field(index=True)
    authorization_jti: str = Field(max_length=64, index=True)
    deployment_key: str = Field(max_length=64, index=True)
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    post_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    evidence_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    evidence_directory: str = Field(max_length=500)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)
    partial_failure_details: str | None = None


class WordPressHeadingCorrectionAudit(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "action_type = 'correct_orlando_duplicate_h1'",
            name="ck_wordpressheadingcorrectionaudit_action",
        ),
        CheckConstraint(
            "status IN ('pending','corrected','verified','reconciliation_required','failed')",
            name="ck_wordpressheadingcorrectionaudit_status",
        ),
        UniqueConstraint(
            "token_fingerprint",
            name="uq_wordpressheadingcorrectionaudit_token_fingerprint",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    action_type: str = Field(default="correct_orlando_duplicate_h1", max_length=64, index=True)
    status: str = Field(default="pending", max_length=40, index=True)
    wordpress_site_url: str = Field(max_length=500)
    current_body_hash: str = Field(max_length=64, index=True)
    proposed_body_hash: str = Field(max_length=64, index=True)
    token_fingerprint: str = Field(max_length=64, index=True)
    backup_identities: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    release_identity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    post_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_message: str | None = Field(default=None, max_length=2000)


class WordPressDeploymentNonce(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("jti", name="uq_wordpressdeploymentnonce_jti"),
        UniqueConstraint("token_fingerprint", name="uq_wordpressdeploymentnonce_token_fingerprint"),
    )
    id: int | None = Field(default=None, primary_key=True)
    jti: str = Field(max_length=64, index=True)
    token_fingerprint: str = Field(max_length=64)
    action_type: str = Field(max_length=64, index=True)
    consumed_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    audit_id: int | None = Field(default=None, foreign_key="wordpressdeploymentaudit.id", index=True)


class WordPressDeploymentTransition(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN ('installation_authorized','awaiting_manual_installation','manual_installation_reported','verification_pending','verified','verification_failed','reconciliation_required','failed')",
            name="ck_wordpressdeploymenttransition_previous_state",
        ),
        CheckConstraint(
            "new_state IN ('installation_authorized','awaiting_manual_installation','manual_installation_reported','verification_pending','verified','verification_failed','reconciliation_required','failed')",
            name="ck_wordpressdeploymenttransition_new_state",
        ),
        UniqueConstraint("request_identifier", name="uq_wordpressdeploymenttransition_request_identifier"),
    )
    id: int | None = Field(default=None, primary_key=True)
    audit_id: int = Field(foreign_key="wordpressdeploymentaudit.id", index=True)
    previous_state: str | None = Field(default=None, max_length=40)
    new_state: str = Field(max_length=40, index=True)
    transitioned_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    actor: str = Field(max_length=200)
    reason: str = Field(max_length=500)
    request_identifier: str = Field(max_length=64, index=True)


class WordPressActivationAudit(SQLModel, table=True):
    """Durable record for the separately authorized Metadata Bridge activation."""

    __table_args__ = (
        CheckConstraint(
            "action_type = 'activate_metadata_bridge'",
            name="ck_wordpressactivationaudit_action",
        ),
        CheckConstraint(
            "status IN ('pending','verified','verification_failed','failed')",
            name="ck_wordpressactivationaudit_status",
        ),
        UniqueConstraint(
            "handle_fingerprint",
            name="uq_wordpressactivationaudit_handle_fingerprint",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    installation_audit_id: int = Field(foreign_key="wordpressdeploymentaudit.id", index=True)
    action_type: str = Field(default="activate_metadata_bridge", max_length=64, index=True)
    status: str = Field(default="pending", max_length=40, index=True)
    operator: str = Field(max_length=200)
    confirmation_phrase_hash: str = Field(max_length=64)
    handle_fingerprint: str = Field(max_length=64, index=True)
    binding_hash: str = Field(max_length=64, index=True)
    atlas_version: str = Field(max_length=32)
    atlas_commit: str = Field(max_length=40)
    atlas_tag: str = Field(max_length=32)
    manifest_sha256: str = Field(max_length=64)
    plugin_slug: str = Field(max_length=100)
    plugin_path: str = Field(max_length=255)
    plugin_version: str = Field(max_length=32)
    zip_sha256: str = Field(max_length=64)
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    browser_evidence_id: str = Field(max_length=100)
    browser_evidence_schema: str = Field(max_length=100)
    browser_evidence_schema_version: int
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    post_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    wordpress_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    atlas_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    transition_history: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)


class WordPressPluginUpgradeAudit(SQLModel, table=True):
    """Durable record for one guarded Metadata Bridge artifact replacement."""

    __table_args__ = (
        CheckConstraint(
            "action_type = 'upgrade_metadata_bridge'",
            name="ck_wordpresspluginupgradeaudit_action",
        ),
        CheckConstraint(
            "status IN ('pending','verified','verification_failed','failed')",
            name="ck_wordpresspluginupgradeaudit_status",
        ),
        UniqueConstraint(
            "handle_fingerprint",
            name="uq_wordpresspluginupgradeaudit_handle_fingerprint",
        ),
        UniqueConstraint(
            "reconciliation_handle_fingerprint",
            name="uq_wppluginupgradeaudit_reconciliation_handle",
        ),
        CheckConstraint(
            "(reconciliation_reason IS NULL AND reconciliation_handle_fingerprint IS NULL "
            "AND reconciliation_binding_hash IS NULL AND reconciliation_snapshot IS NULL "
            "AND reconciled_at IS NULL) OR "
            "(status = 'verified' AND "
            "reconciliation_reason = 'cache_boundary_volatile_observation_reconciled' "
            "AND reconciliation_handle_fingerprint IS NOT NULL "
            "AND reconciliation_binding_hash IS NOT NULL "
            "AND reconciliation_snapshot IS NOT NULL AND reconciled_at IS NOT NULL)",
            name="ck_wppluginupgradeaudit_reconciliation",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    installation_audit_id: int = Field(foreign_key="wordpressdeploymentaudit.id", index=True)
    activation_audit_id: int = Field(foreign_key="wordpressactivationaudit.id", index=True)
    action_type: str = Field(default="upgrade_metadata_bridge", max_length=64, index=True)
    status: str = Field(default="pending", max_length=40, index=True)
    operator: str = Field(max_length=200)
    confirmation_phrase_hash: str = Field(max_length=64)
    handle_fingerprint: str = Field(max_length=64, index=True)
    binding_hash: str = Field(max_length=64, index=True)
    previous_version: str = Field(max_length=32)
    target_version: str = Field(max_length=32)
    previous_artifact_sha256: str = Field(max_length=64)
    target_artifact_sha256: str = Field(max_length=64)
    release_identity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    browser_evidence_id: str = Field(max_length=200)
    browser_evidence_hashes: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    post_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    previous_inventories: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    final_inventories: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    metadata_rendering_state: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    page_media_snapshots: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    wordpress_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    atlas_write_count: int = Field(default=0)
    atlas_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    verification_findings: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    recovery_recommendation: str | None = Field(default=None, max_length=64)
    transition_history: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)
    reconciliation_reason: str | None = Field(default=None, max_length=100, index=True)
    reconciliation_handle_fingerprint: str | None = Field(default=None, max_length=64)
    reconciliation_binding_hash: str | None = Field(default=None, max_length=64)
    reconciliation_snapshot: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON(none_as_null=True)),
    )
    reconciled_at: datetime | None = None


class WordPressBootstrapCleanupAudit(SQLModel, table=True):
    """Durable record for the separately gated upgrade-bootstrap cleanup."""

    __table_args__ = (
        CheckConstraint(
            "action_type = 'cleanup_upgrade_bootstrap'",
            name="ck_wordpressbootstrapcleanupaudit_action",
        ),
        CheckConstraint(
            "status IN ('pending','deactivated','verified','verification_failed','failed')",
            name="ck_wordpressbootstrapcleanupaudit_status",
        ),
        UniqueConstraint(
            "deactivation_handle_fingerprint",
            name="uq_wordpressbootstrapcleanupaudit_deactivation_handle",
        ),
        UniqueConstraint(
            "deletion_handle_fingerprint",
            name="uq_wordpressbootstrapcleanupaudit_deletion_handle",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    installation_audit_id: int = Field(foreign_key="wordpressdeploymentaudit.id", index=True)
    activation_audit_id: int = Field(foreign_key="wordpressactivationaudit.id", index=True)
    upgrade_audit_id: int = Field(foreign_key="wordpresspluginupgradeaudit.id", index=True)
    action_type: str = Field(default="cleanup_upgrade_bootstrap", max_length=64, index=True)
    status: str = Field(default="pending", max_length=40, index=True)
    operator: str = Field(max_length=200)
    bootstrap_slug: str = Field(max_length=100)
    bootstrap_path: str = Field(max_length=255)
    bootstrap_version: str = Field(max_length=32)
    bootstrap_zip_sha256: str = Field(max_length=64)
    bridge_version: str = Field(max_length=32)
    deactivation_phrase_hash: str = Field(max_length=64)
    deletion_phrase_hash: str = Field(max_length=64)
    deactivation_handle_fingerprint: str = Field(max_length=64, index=True)
    deletion_handle_fingerprint: str | None = Field(default=None, max_length=64, index=True)
    deactivation_binding_hash: str = Field(max_length=64, index=True)
    deletion_binding_hash: str | None = Field(default=None, max_length=64, index=True)
    release_identity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    browser_evidence_id: str = Field(max_length=200)
    browser_evidence_hashes: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    deactivated_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    final_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    previous_inventories: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    deactivated_inventories: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    final_inventories: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    metadata_rendering_state: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    page_media_snapshots: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    wordpress_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    atlas_write_count: int = Field(default=0)
    atlas_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    verification_findings: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    recovery_recommendation: str | None = Field(default=None, max_length=64)
    transition_history: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    deactivated_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)


class WordPressBootstrapEstablishmentAudit(SQLModel, table=True):
    """Durable record for the audited manual bootstrap handoff and fixed activation."""

    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_manual_bootstrap_installation','manual_installation_inventory_verified','activation_pending_checksum_verification','verified','authorization_retired','manual_installation_mismatch','manual_activation_detected','installation_partial','checksum_mismatch','checksum_unavailable','verification_failed','recovery_required')",
            name="ck_wordpressbootstrapestablishmentaudit_status",
        ),
        CheckConstraint(
            "authorization_mode IN ('manual_upload','existing_exact_inactive_bootstrap')",
            name="ck_wordpressbootstrapestablishmentaudit_authorization_mode",
        ),
        CheckConstraint(
            "(status = 'authorization_retired' AND retirement_reason = 'manual_install_verification_genuine_transport_drift') OR (status != 'authorization_retired' AND retirement_reason IS NULL)",
            name="ck_wordpressbootstrapestablishmentaudit_retirement_reason",
        ),
        CheckConstraint(
            "(reconciliation_reason IS NULL AND reconciliation_handle_fingerprint IS NULL AND reconciliation_binding_hash IS NULL AND reconciled_at IS NULL) OR "
            "(status = 'verified' AND reconciliation_reason = 'post_activation_verifier_contract_defect_reconciled' AND reconciliation_handle_fingerprint IS NOT NULL AND reconciliation_binding_hash IS NOT NULL AND reconciled_at IS NOT NULL)",
            name="ck_wordpressbootstrapestablishmentaudit_reconciliation",
        ),
        UniqueConstraint("manual_handle_fingerprint", name="uq_bootstrapestablishment_manual_handle"),
        UniqueConstraint("activation_handle_fingerprint", name="uq_bootstrapestablishment_activation_handle"),
        UniqueConstraint(
            "reconciliation_handle_fingerprint",
            name="uq_wordpressbootstrapestablishmentaudit_reconciliation_handle",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    installation_audit_id: int = Field(foreign_key="wordpressdeploymentaudit.id", index=True)
    activation_audit_id: int = Field(foreign_key="wordpressactivationaudit.id", index=True)
    action_type: str = Field(default="establish_upgrade_bootstrap_0_3_0", max_length=80, index=True)
    authorization_mode: str = Field(default="manual_upload", max_length=64, index=True)
    status: str = Field(default="awaiting_manual_bootstrap_installation", max_length=64, index=True)
    retirement_reason: str | None = Field(default=None, max_length=100, index=True)
    operator: str = Field(max_length=200)
    bootstrap_slug: str = Field(max_length=100)
    bootstrap_directory: str = Field(max_length=160)
    bootstrap_path: str = Field(max_length=255)
    bootstrap_version: str = Field(max_length=32)
    bootstrap_zip_filename: str = Field(max_length=180)
    bootstrap_zip_sha256: str = Field(max_length=64)
    bootstrap_entry_sha256: str = Field(max_length=64)
    manual_phrase_hash: str = Field(max_length=64)
    activation_phrase_hash: str = Field(max_length=64)
    manual_handle_fingerprint: str = Field(max_length=64, index=True)
    activation_handle_fingerprint: str | None = Field(default=None, max_length=64, index=True)
    manual_binding_hash: str = Field(max_length=64, index=True)
    activation_binding_hash: str | None = Field(default=None, max_length=64, index=True)
    release_identity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    backup_renewals: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    active_backup_evidence: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    browser_evidence_id: str = Field(max_length=200)
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    upload_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    final_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    source_inventories: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    upload_inventories: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    final_inventories: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    protected_state: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    inactive_checksum_verifiable: bool = Field(default=False)
    approved_residual_risk: bool = Field(default=True)
    checksum_verification_source: str | None = Field(default=None, max_length=160)
    checksum_verification_result: str | None = Field(default=None, max_length=80)
    reconciliation_reason: str | None = Field(default=None, max_length=100, index=True)
    reconciliation_handle_fingerprint: str | None = Field(default=None, max_length=64)
    reconciliation_binding_hash: str | None = Field(default=None, max_length=64)
    reconciled_at: datetime | None = None
    wordpress_write_count: int = Field(default=0)
    wordpress_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    cache_write_count: int = Field(default=0)
    atlas_write_count: int = Field(default=0)
    atlas_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    transition_history: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    recovery_recommendation: str | None = Field(default=None, max_length=80)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=2000)


class WordPressMetadataLifecycleAudit(SQLModel, table=True):
    """Durable record for one isolated Metadata Bridge lifecycle mutation."""

    __table_args__ = (
        CheckConstraint(
            "action_type IN ('stage_metadata_payload','enable_metadata_rendering','disable_metadata_rendering','rollback_metadata_payload')",
            name="ck_wordpressmetadatalifecycleaudit_action",
        ),
        CheckConstraint(
            "status IN ('pending','verified','verification_failed','failed')",
            name="ck_wordpressmetadatalifecycleaudit_status",
        ),
        UniqueConstraint("handle_fingerprint", name="uq_wordpressmetadatalifecycleaudit_handle_fingerprint"),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    installation_audit_id: int = Field(foreign_key="wordpressdeploymentaudit.id", index=True)
    activation_audit_id: int = Field(foreign_key="wordpressactivationaudit.id", index=True)
    action_type: str = Field(max_length=64, index=True)
    completion_mode: str = Field(default="standard", max_length=80, index=True)
    status: str = Field(default="pending", max_length=40, index=True)
    operator: str = Field(max_length=200)
    confirmation_phrase_hash: str = Field(max_length=64)
    handle_fingerprint: str = Field(max_length=64, index=True)
    binding_hash: str = Field(max_length=64, index=True)
    release_identity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    browser_evidence_id: str = Field(max_length=200)
    browser_evidence_hashes: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    payload_hash: str = Field(default="", max_length=64, index=True)
    previous_revision: str = Field(max_length=40)
    final_revision: str | None = Field(default=None, max_length=40)
    previous_rendering_enabled: bool
    final_rendering_enabled: bool | None = None
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    post_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    page_media_snapshots: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    wordpress_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    atlas_write_count: int = Field(default=0)
    atlas_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    transition_history: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)
    recovery_recommendation: str | None = Field(default=None, max_length=64)


class WordPressCacheAwareRenderingAudit(SQLModel, table=True):
    """Durable orchestration record for rendering, origin proof, and one URL purge."""

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_rendering','origin_verified','pending_cache_purge','verified','verification_failed','failed')",
            name="ck_wordpresscacheawarerenderingaudit_status",
        ),
        UniqueConstraint("rendering_handle_fingerprint", name="uq_cacheaware_rendering_handle"),
        UniqueConstraint("cache_handle_fingerprint", name="uq_cacheaware_cache_handle"),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    staging_audit_id: int = Field(foreign_key="wordpressmetadatalifecycleaudit.id", index=True)
    recovery_disable_audit_id: int = Field(foreign_key="wordpressmetadatalifecycleaudit.id", index=True)
    status: str = Field(default="pending_rendering", max_length=40, index=True)
    operator: str = Field(max_length=200)
    rendering_handle_fingerprint: str = Field(max_length=64, index=True)
    cache_handle_fingerprint: str | None = Field(default=None, max_length=64, index=True)
    rendering_binding_hash: str = Field(max_length=64, index=True)
    cache_binding_hash: str | None = Field(default=None, max_length=64, index=True)
    rendering_phrase_hash: str = Field(max_length=64)
    cache_phrase_hash: str | None = Field(default=None, max_length=64)
    release_identity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    payload_hash: str = Field(max_length=64, index=True)
    revision: str = Field(max_length=40)
    cache_provider: str | None = Field(default=None, max_length=80)
    cache_scope: str | None = Field(default=None, max_length=80)
    cache_target: str | None = Field(default=None, max_length=500)
    pre_purge_headers: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    post_purge_headers: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    origin_verification: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    public_verification: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    public_evidence: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    page_media_snapshots: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    gate_results: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    cache_write_count: int = Field(default=0)
    atlas_write_count: int = Field(default=0)
    wordpress_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    cache_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    atlas_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    transition_history: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    final_state: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    recovery_recommendation: str | None = Field(default=None, max_length=64)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=2000)


class PageImageAssignment(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id",
            "image_metadata_id",
            "image_role",
            name="uq_page_image_role_media",
        ),
        CheckConstraint(
            "override_focal_x IS NULL OR (override_focal_x >= 0 AND override_focal_x <= 1)",
            name="ck_pageimageassignment_override_focal_x_range",
        ),
        CheckConstraint(
            "override_focal_y IS NULL OR (override_focal_y >= 0 AND override_focal_y <= 1)",
            name="ck_pageimageassignment_override_focal_y_range",
        ),
        CheckConstraint(
            "assignment_version IS NULL OR assignment_version >= 1",
            name="ck_pageimageassignment_assignment_version",
        ),
        CheckConstraint(
            "media_version IS NULL OR media_version >= 1",
            name="ck_pageimageassignment_media_version",
        ),
        CheckConstraint(
            "placement_contract_version IS NULL OR placement_contract_version >= 1",
            name="ck_pageimageassignment_contract_version",
        ),
        CheckConstraint(
            "status IN ('active','replaced','retired')",
            name="ck_pageimageassignment_status",
        ),
        CheckConstraint(
            "(assignment_version IS NULL AND replaces_page_image_assignment_id IS NULL) OR "
            "(assignment_version = 1 AND replaces_page_image_assignment_id IS NULL) OR "
            "(assignment_version > 1 AND replaces_page_image_assignment_id IS NOT NULL)",
            name="ck_pageimageassignment_replacement",
        ),
        CheckConstraint(
            "(website_id IS NULL AND site_plan_id IS NULL AND planned_page_id IS NULL "
            "AND media_requirement_id IS NULL AND assignment_version IS NULL "
            "AND media_version IS NULL AND placement_contract_version IS NULL "
            "AND assigned_by IS NULL AND assignment_rationale IS NULL "
            "AND assigned_at IS NULL) OR "
            "(website_id IS NOT NULL AND site_plan_id IS NOT NULL "
            "AND planned_page_id IS NOT NULL AND media_requirement_id IS NOT NULL "
            "AND assignment_version IS NOT NULL AND media_version IS NOT NULL "
            "AND placement_contract_version IS NOT NULL AND assigned_by IS NOT NULL "
            "AND assignment_rationale IS NOT NULL AND assigned_at IS NOT NULL)",
            name="ck_pageimageassignment_governed_binding",
        ),
        CheckConstraint(
            "status != 'replaced' OR "
            "(replaced_by IS NOT NULL AND replacement_rationale IS NOT NULL "
            "AND replaced_at IS NOT NULL)",
            name="ck_pageimageassignment_replacement_provenance",
        ),
        CheckConstraint(
            "status != 'retired' OR "
            "(retired_by IS NOT NULL AND retirement_rationale IS NOT NULL "
            "AND retired_at IS NOT NULL)",
            name="ck_pageimageassignment_retirement_provenance",
        ),
        UniqueConstraint(
            "media_requirement_id",
            "assignment_version",
            name="uq_pageimageassignment_requirement_version",
        ),
        Index(
            "uq_pageimageassignment_active_requirement",
            "media_requirement_id",
            unique=True,
            postgresql_where=text("status = 'active' AND media_requirement_id IS NOT NULL"),
            sqlite_where=text("status = 'active' AND media_requirement_id IS NOT NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    image_metadata_id: int = Field(foreign_key="imagemetadata.id", index=True)
    website_id: int | None = Field(default=None, foreign_key="website.id", index=True)
    site_plan_id: int | None = Field(default=None, foreign_key="siteplan.id", index=True)
    planned_page_id: int | None = Field(default=None, foreign_key="plannedpage.id", index=True)
    media_requirement_id: int | None = Field(
        default=None,
        foreign_key="plannedpagemediarequirement.id",
        index=True,
    )
    assignment_version: int | None = Field(default=None, ge=1)
    media_version: int | None = Field(default=None, ge=1)
    placement_contract_version: int | None = Field(default=None, ge=1)
    assigned_by: str | None = None
    assignment_rationale: str | None = None
    assigned_at: datetime | None = Field(default=None, index=True)
    replaced_by: str | None = None
    replacement_rationale: str | None = None
    replaced_at: datetime | None = Field(default=None, index=True)
    retired_by: str | None = None
    retirement_rationale: str | None = None
    retired_at: datetime | None = Field(default=None, index=True)
    replaces_page_image_assignment_id: int | None = Field(
        default=None,
        foreign_key="pageimageassignment.id",
        index=True,
    )
    image_role: str = Field(default="hero", index=True)
    sort_order: int = Field(default=0)
    override_focal_x: float | None = Field(default=None, ge=0, le=1)
    override_focal_y: float | None = Field(default=None, ge=0, le=1)
    override_alt_text: str | None = None
    display_preset: str = Field(default="hero_desktop", index=True)
    status: str = Field(default="active", index=True)


class KnowledgeBlock(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    service_id: int = Field(foreign_key="service.id", index=True)
    title: str = Field(index=True)
    slug: str = Field(index=True, unique=True)
    question: str
    short_answer: str
    long_answer: str
    category: str = Field(index=True)
    customer_type: str = Field(default="general", index=True)
    confidence_level: str = Field(default="Medium", index=True)
    source_notes: str | None = None
    sort_order: int = Field(default=0, index=True)
    status: str = Field(default="active", index=True)


class Setting(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    setting_key: str = Field(index=True, unique=True)
    setting_value: str | None = None
    description: str | None = None
