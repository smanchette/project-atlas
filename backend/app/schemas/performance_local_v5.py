from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel


class PerformanceLocalV5SourceBindings(SQLModel):
    """Exact current Atlas records consumed by one V5 payload build."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    generated_page_revision_id: int = Field(gt=0)
    generated_page_revision_hash: str = Field(min_length=64, max_length=64)
    page_composition_id: int = Field(gt=0)
    composition_version: int = Field(gt=0)
    page_composition_revision_id: int = Field(gt=0)
    page_composition_revision_hash: str = Field(min_length=64, max_length=64)
    composition_source_hash: str = Field(min_length=64, max_length=64)
    qa_result_id: int = Field(gt=0)
    qa_result_hash: str = Field(min_length=64, max_length=64)


class PerformanceLocalV5UnavailablePayloadIdentity(SQLModel):
    """Validated current Atlas identity retained when remote media blocks a payload."""

    model_config = ConfigDict(extra="forbid")

    website_id: int = Field(gt=0)
    planned_page_id: int = Field(gt=0)
    generated_page_id: int = Field(gt=0)
    wordpress_post_id: int = Field(gt=0)
    source_bindings: PerformanceLocalV5SourceBindings


class PerformanceLocalV5MediaIdentity(SQLModel):
    """One exact, governed media assignment required by the payload."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: int = Field(gt=0)
    placement_key: str
    target_component_instance_key: str
    assignment_id: int = Field(gt=0)
    assignment_version: int = Field(gt=0)
    image_metadata_id: int = Field(gt=0)
    media_key: str
    media_version: int = Field(gt=0)
    source_filename: str
    source_mime_type: str
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    checksum_sha256: str = Field(min_length=64, max_length=64)
    authorization_id: int = Field(gt=0)
    authorization_version: int = Field(gt=0)
    authorization_fingerprint: str = Field(min_length=64, max_length=64)
    wordpress_media_id: int | None = None
    wordpress_media_url: str | None = None
    payload_src: str | None = None
    verification_source: Literal["persisted_atlas", "verified_media_mapping"] | None = None
    observed_remote_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    observed_remote_mime_type: str | None = None
    observed_remote_width: int | None = Field(default=None, gt=0)
    observed_remote_height: int | None = Field(default=None, gt=0)
    ready: bool = False
    blocker: str | None = None


class PerformanceLocalV5LogoIdentity(SQLModel):
    """One exact governed Brand Asset required for Bridge logo transport."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["header_logo", "footer_logo"]
    target_component_instance_key: Literal["website_header", "website_footer"]
    assignment_id: int | None = Field(default=None, gt=0)
    assignment_version: int | None = Field(default=None, gt=0)
    brand_asset_id: int = Field(gt=0)
    asset_key: str
    asset_version: int = Field(gt=0)
    checksum_sha256: str = Field(min_length=64, max_length=64)
    source_filename: str
    source_mime_type: str
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    governed_asset_url: str
    wordpress_media_id: int | None = None
    wordpress_media_url: str | None = None
    payload_src: str | None = None
    verification_source: Literal["persisted_atlas", "verified_media_mapping"] | None = None
    observed_remote_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    observed_remote_mime_type: str | None = None
    observed_remote_width: int | None = Field(default=None, gt=0)
    observed_remote_height: int | None = Field(default=None, gt=0)
    ready: bool = False
    blocker: str | None = None


class PerformanceLocalV5VerifiedMediaContext(SQLModel):
    """Exact current activation context bound to a nondurable browser proof."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    website_id: int = Field(gt=0)
    planned_page_id: int = Field(gt=0)
    generated_page_id: int = Field(gt=0)
    wordpress_post_id: int = Field(gt=0)
    staging_origin: str
    source_bindings: PerformanceLocalV5SourceBindings


class PerformanceLocalV5VerifiedMediaEntry(SQLModel):
    """One exact governed asset and its browser-observed WordPress original."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    governed_asset_class: Literal["page_media", "brand_asset"]
    requirement_id: int | None = Field(default=None, gt=0)
    placement_key: str
    target_component_instance_key: str
    assignment_id: int = Field(gt=0)
    assignment_version: int = Field(gt=0)
    authorization_id: int | None = Field(default=None, gt=0)
    authorization_version: int | None = Field(default=None, gt=0)
    authorization_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    governed_asset_id: int = Field(gt=0)
    governed_asset_key: str
    governed_asset_version: int = Field(gt=0)
    expected_sha256: str = Field(min_length=64, max_length=64)
    expected_mime_type: str
    expected_width: int = Field(gt=0)
    expected_height: int = Field(gt=0)
    wordpress_attachment_id: int = Field(gt=0)
    wordpress_original_url: str
    observed_sha256: str = Field(min_length=64, max_length=64)
    observed_mime_type: str
    observed_width: int = Field(gt=0)
    observed_height: int = Field(gt=0)


class PerformanceLocalV5VerifiedMediaMap(SQLModel):
    """Strict nondurable media proof accepted only by V5 payload finalization."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    mapping_schema: Literal[
        "project-atlas-performance-local-v5-verified-media-map@1"
    ] = "project-atlas-performance-local-v5-verified-media-map@1"
    context: PerformanceLocalV5VerifiedMediaContext
    entries: list[PerformanceLocalV5VerifiedMediaEntry]


class PerformanceLocalV5PreparedPayload(SQLModel):
    """Current governed V5 template that is deliberately not deployable."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    website_id: int = Field(gt=0)
    planned_page_id: int = Field(gt=0)
    generated_page_id: int = Field(gt=0)
    wordpress_post_id: int = Field(gt=0)
    metadata_key: Literal["_project_atlas_performance_local_v5_v1"]
    payload_schema: Literal["project-atlas-performance-local-v5-wordpress@1"]
    payload_template: dict[str, Any]
    template_sha256: str = Field(min_length=64, max_length=64)
    preparation_sha256: str = Field(min_length=64, max_length=64)
    source_bindings: PerformanceLocalV5SourceBindings
    required_media: list[PerformanceLocalV5MediaIdentity]
    required_logo_media: list[PerformanceLocalV5LogoIdentity]


class PerformanceLocalV5PayloadBuild(SQLModel):
    """Pure result consumed by the guarded staging orchestration."""

    model_config = ConfigDict(extra="forbid")

    website_id: int = Field(gt=0)
    planned_page_id: int = Field(gt=0)
    generated_page_id: int = Field(gt=0)
    wordpress_post_id: int = Field(gt=0)
    metadata_key: Literal["_project_atlas_performance_local_v5_v1"]
    payload_schema: Literal["project-atlas-performance-local-v5-wordpress@1"]
    # The Bridge selects its bundled template dynamically from valid metadata;
    # no `_wp_page_template` value is written by this contract.
    template_value: None = None
    template_path: Literal[
        "project-atlas-metadata-bridge/templates/performance-local-v5-page.php"
    ]
    payload: dict[str, Any]
    payload_sha256: str = Field(min_length=64, max_length=64)
    source_bindings: PerformanceLocalV5SourceBindings
    required_media: list[PerformanceLocalV5MediaIdentity]
    required_logo_media: list[PerformanceLocalV5LogoIdentity]


class PerformanceLocalV5RegistrationAction(SQLModel):
    model_config = ConfigDict(extra="forbid")

    order: int = Field(gt=0)
    action: Literal[
        "register_family",
        "register_family_version",
        "approve_family_version",
        "create_configuration",
        "create_component_graph",
        "approve_configuration",
        "materialize_theme",
        "select_theme",
        "activate_configuration",
    ]
    target: str


class PerformanceLocalV5RegistrationIdentity(SQLModel):
    model_config = ConfigDict(extra="forbid")

    theme_family_id: int | None = None
    theme_family_version_id: int | None = None
    website_theme_configuration_id: int | None = None
    component_configuration_ids: list[int] = Field(default_factory=list)
    materialized_theme_id: int | None = None
    website_theme_selection_id: int | None = None


class PerformanceLocalV5RegistrationPlan(SQLModel):
    """Read-only all-missing/exact/conflict decision for durable V5 state."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["PLANNED", "UNCHANGED", "CONFLICT"]
    website_id: int = Field(gt=0)
    family_key: Literal["performance-local"] = "performance-local"
    family_version: Literal[5] = 5
    configuration_key: Literal["performance-local-v5"] = "performance-local-v5"
    expected_source_commit: str = Field(min_length=40, max_length=40)
    expected_contract_fingerprint: str = Field(min_length=64, max_length=64)
    identity: PerformanceLocalV5RegistrationIdentity
    actions: list[PerformanceLocalV5RegistrationAction] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    write_count: Literal[0] = 0


class PerformanceLocalV5RegistrationApplyResult(SQLModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["APPLIED", "UNCHANGED"]
    website_id: int = Field(gt=0)
    identity: PerformanceLocalV5RegistrationIdentity
    audit_ids: list[int]
