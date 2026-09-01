from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

from app.schemas.wordpress import WordPressDraftGateResult


V5_META_KEY = "_project_atlas_performance_local_v5_v1"
V5_PAYLOAD_SCHEMA = "project-atlas-performance-local-v5-wordpress@1"
V5_ROUTE_SCHEMA = "project-atlas-performance-local-v5-page-payload-route@1"
V5_REQUEST_SCHEMA = "project-atlas-performance-local-v5-page-payload-request@1"
V5_PLUGIN_VERSION = "0.57.11"


class PerformanceLocalV5StagingDryRunRequest(SQLModel):
    """Caller-controlled dry-run policy; it can never carry a page payload."""

    model_config = ConfigDict(extra="forbid")

    no_network: bool = False


class PerformanceLocalV5StagingApplyRequest(SQLModel):
    """Apply accepts only the signed dry-run authority and exact phrase."""

    model_config = ConfigDict(extra="forbid")

    confirmation_token: str = Field(min_length=32, max_length=12000)
    confirmation_phrase: str = Field(min_length=1, max_length=160)


class PerformanceLocalV5PageIdentity(SQLModel):
    website_id: int = Field(gt=0)
    planned_page_id: int = Field(gt=0)
    generated_page_id: int = Field(gt=0)
    generated_page_revision_id: int = Field(gt=0)
    composition_id: int = Field(gt=0)
    composition_version: int = Field(gt=0)
    immutable_composition_revision_id: int = Field(gt=0)
    qa_result_id: int = Field(gt=0)
    wordpress_post_id: int = Field(gt=0)
    wordpress_post_status: str
    page_title: str
    page_slug: str


class PerformanceLocalV5RegistrationIdentity(SQLModel):
    theme_family_id: int | None = None
    theme_family_version_id: int | None = None
    theme_family_version: int | None = None
    website_theme_configuration_id: int | None = None
    component_configuration_ids: list[int] = Field(default_factory=list)
    materialized_theme_id: int | None = None
    website_theme_selection_id: int | None = None
    expected_source_commit: str | None = None
    expected_contract_fingerprint: str | None = None
    ready: bool = False


class PerformanceLocalV5MediaReadiness(SQLModel):
    identity_kind: Literal["page_media", "brand_asset"] = "page_media"
    requirement_id: int | None = Field(default=None, gt=0)
    placement_key: str | None = None
    target_component_instance_key: str | None = None
    assignment_id: int | None = None
    assignment_version: int | None = None
    asset_id: int = Field(gt=0)
    brand_asset_id: int | None = Field(default=None, gt=0)
    role: Literal["header_logo", "footer_logo"] | None = None
    asset_key: str | None = None
    asset_version: int | None = Field(default=None, gt=0)
    media_key: str | None = None
    media_version: int | None = None
    authorization_id: int | None = None
    authorization_version: int | None = None
    authorization_fingerprint: str | None = None
    asset_sha256: str = Field(min_length=64, max_length=64)
    source_file_name: str | None = None
    source_mime_type: str | None = None
    source_width: int | None = Field(default=None, gt=0)
    source_height: int | None = Field(default=None, gt=0)
    governed_asset_url: str | None = None
    wordpress_media_id: int | None = None
    wordpress_media_url: str | None = None
    wordpress_media_status: str | None = None
    wordpress_media_checksum: str | None = None
    ready: bool = False
    blocker: str | None = None


class PerformanceLocalV5StagingDryRun(SQLModel):
    status: Literal["BLOCKED", "DRY_RUN_READY"]
    ready: bool
    no_network: bool
    target_staging_url: str | None = None
    route: str | None = None
    metadata_key: Literal["_project_atlas_performance_local_v5_v1"] = V5_META_KEY
    payload_schema: Literal["project-atlas-performance-local-v5-wordpress@1"] = (
        V5_PAYLOAD_SCHEMA
    )
    plugin_version: Literal["0.57.11"] = V5_PLUGIN_VERSION
    identity: PerformanceLocalV5PageIdentity | None = None
    registration: PerformanceLocalV5RegistrationIdentity
    payload_sha256: str | None = None
    current_remote_metadata_sha256: str | None = None
    media_readiness: list[PerformanceLocalV5MediaReadiness] = Field(default_factory=list)
    unchanged_page_fields: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    gate_results: list[WordPressDraftGateResult] = Field(default_factory=list)
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    expires_at: datetime | None = None


class PerformanceLocalV5StagingApplyResult(SQLModel):
    status: Literal["APPLIED", "UNCHANGED"]
    audit_id: int = Field(gt=0)
    target_staging_url: str
    route: str
    metadata_key: Literal["_project_atlas_performance_local_v5_v1"] = V5_META_KEY
    payload_schema: Literal["project-atlas-performance-local-v5-wordpress@1"] = (
        V5_PAYLOAD_SCHEMA
    )
    plugin_version: Literal["0.57.11"] = V5_PLUGIN_VERSION
    identity: PerformanceLocalV5PageIdentity
    registration: PerformanceLocalV5RegistrationIdentity
    payload_sha256: str = Field(min_length=64, max_length=64)
    prior_metadata_sha256: str | None = None
    resulting_metadata_sha256: str = Field(min_length=64, max_length=64)
    request_identity: str
    unchanged_page_fields: list[str]
    gate_results: list[WordPressDraftGateResult]
    wordpress_post_count: Literal[0, 1] = 1
    wordpress_verification_get_count: int = Field(default=1, ge=0, le=2)
    atlas_audit_write_count: Literal[1] = 1


class PerformanceLocalV5RemoteInspection(SQLModel):
    """The exact sanitized response contract of the private Bridge GET route."""

    model_config = ConfigDict(extra="forbid")

    route_schema: Literal["project-atlas-performance-local-v5-page-payload-route@1"]
    metadata_bridge_version: Literal["0.57.11"]
    environment_type: str
    home: str
    siteurl: str
    blog_public: int
    post_id: int
    post_type: str
    post_status: str
    post_title: str
    post_slug: str
    metadata_exists: bool
    metadata_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    metadata_valid: bool
    atlas_identity: dict[str, Any] | None = None


class PerformanceLocalV5RemoteApplyResult(SQLModel):
    """The exact sanitized response contract of the private Bridge POST route."""

    model_config = ConfigDict(extra="forbid")

    route_schema: Literal["project-atlas-performance-local-v5-page-payload-route@1"]
    metadata_bridge_version: Literal["0.57.11"]
    status: Literal["APPLIED", "UNCHANGED"]
    post_id: int
    prior_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    resulting_sha256: str = Field(min_length=64, max_length=64)
    website_id: int
    planned_page_id: int
    generated_page_id: int
    request_identity: str
    metadata_valid: bool
