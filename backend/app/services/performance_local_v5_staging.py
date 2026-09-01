from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import re
import secrets
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session, select

from app.models import (
    BrandAsset,
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    ImageMetadata,
    PageComposition,
    PageCompositionRevision,
    PlannedPage,
    WebsiteFormDeliveryModeRevision,
    WebsiteFormRecipientRevision,
    WordPressMetadataSyncAudit,
)
from app.schemas.performance_local_v5_staging import (
    PerformanceLocalV5MediaReadiness,
    PerformanceLocalV5PageIdentity,
    PerformanceLocalV5RegistrationIdentity,
    PerformanceLocalV5RemoteApplyResult,
    PerformanceLocalV5RemoteInspection,
    PerformanceLocalV5StagingApplyRequest,
    PerformanceLocalV5StagingApplyResult,
    PerformanceLocalV5StagingDryRun,
    V5_META_KEY,
    V5_PAYLOAD_SCHEMA,
    V5_PLUGIN_VERSION,
    V5_REQUEST_SCHEMA,
    V5_ROUTE_SCHEMA,
)
from app.schemas.wordpress import WordPressDraftGateResult
from app.services.wordpress_http import (
    classify_wordpress_exception,
    classify_wordpress_response,
    wordpress_basic_auth,
    wordpress_http_client,
)
from app.services.wordpress_sandbox import (
    get_wordpress_application_password,
    read_wordpress_settings,
)


EXPECTED_ALEMBIC_REVISION = "20260820_0048"
TARGET_PAGE_TYPE = "city_service"
TOKEN_ACTION = "apply_performance_local_v5_staging_payload"
TOKEN_TTL = timedelta(minutes=15)
ROUTE_PATH = "/wp-json/project-atlas/v4/performance-local-v5/page-payload/{post_id}"
UNCHANGED_PAGE_FIELDS = [
    "title",
    "slug",
    "content",
    "excerpt",
    "status",
    "featured_image",
    "author",
    "parent",
    "menu_order",
    "_wp_page_template",
]

# Every mutable Atlas source table read by the payload, registration, privacy,
# settings, migration, media, composition, and QA gates. PostgreSQL SHARE locks
# fence INSERT/UPDATE/DELETE while still allowing unrelated read-only work.
_STAGING_SOURCE_TABLES = (
    "alembic_version",
    "brand",
    "brandasset",
    "business",
    "city",
    "county",
    "generatedpage",
    "generatedpageqaresult",
    "generatedpagerevision",
    "imagemetadata",
    "internallinkintent",
    "navigationitem",
    "navigationset",
    "pagecomposition",
    "pagecompositionrevision",
    "pageimageassignment",
    "plannedpage",
    "plannedpagemediarequirement",
    "planningrecord",
    "scopedmediaauthorization",
    "semanticcomponentdefinition",
    "service",
    "setting",
    "siteplan",
    "theme",
    "themefamily",
    "themefamilyversion",
    "website",
    "websiteformdeliverymoderevision",
    "websiteformrecipientrevision",
    "websiteidentity",
    "websiteidentityassetassignment",
    "websitemediaplanningrecord",
    "websitethemecomponentconfiguration",
    "websitethemeconfiguration",
    "websitethemeselection",
)

_token_secret = secrets.token_bytes(32)
_SENSITIVE_KEYS = {
    "authorization",
    "destination_identity",
    "from_email",
    "password",
    "recipient_email",
    "recipient_emails",
    "reply_to",
    "secret",
    "smtp_password",
    "smtp_username",
    "api_key",
    "api_token",
}


@dataclass(frozen=True)
class _LocalContext:
    identity: PerformanceLocalV5PageIdentity
    payload: dict[str, Any]
    payload_sha256: str
    required_media: list[Any]


@dataclass(frozen=True)
class _PageRecords:
    planned: PlannedPage
    generated: GeneratedPage
    revision: GeneratedPageRevision
    composition: PageComposition
    immutable: PageCompositionRevision
    qa: GeneratedPageQAResult
    identity: PerformanceLocalV5PageIdentity


@dataclass(frozen=True)
class _DryRunState:
    response: PerformanceLocalV5StagingDryRun
    local: _LocalContext | None
    remote: PerformanceLocalV5RemoteInspection | None
    token_context: dict[str, Any] | None


def dry_run_performance_local_v5_staging(
    session: Session,
    page_id: int,
    *,
    no_network: bool = False,
    issue_token: bool = True,
) -> PerformanceLocalV5StagingDryRun:
    """Evaluate one staging activation without changing Atlas or WordPress.

    ``no_network`` is deliberately stronger than an ordinary dry-run: it never
    obtains the process-memory application password, creates an HTTP client, or
    issues a request.  It is safe to call inside a transaction whose ownership,
    commit, rollback, and isolation level belong to the caller.
    """

    return _evaluate_dry_run(
        session,
        page_id,
        no_network=no_network,
        issue_token=issue_token,
    ).response


def apply_performance_local_v5_staging(
    session: Session,
    page_id: int,
    request: PerformanceLocalV5StagingApplyRequest,
) -> PerformanceLocalV5StagingApplyResult:
    _require_target(page_id)

    token = _decode_token(request.confirmation_token, action=TOKEN_ACTION)
    if token.get("page_id") != page_id:
        raise HTTPException(status_code=422, detail="The confirmation token targets a different page.")
    token_context = token.get("context") if isinstance(token.get("context"), dict) else {}
    wordpress_post_id = (token_context.get("identity") or {}).get("wordpress_post_id")
    expected_phrase = _confirmation_phrase(wordpress_post_id)
    if not hmac.compare_digest(request.confirmation_phrase, expected_phrase):
        raise HTTPException(status_code=422, detail="The exact staging confirmation phrase is required.")

    request_identity = str(token["request_identity"])
    token_fingerprint = hashlib.sha256(request.confirmation_token.encode("utf-8")).hexdigest()
    replay_marker = f"v5-staging-token:{token_fingerprint}"

    _lock_staging_source_tables(session)

    # Hold the target-page lock while rebuilding every local/remote preflight
    # identity. This closes the prior window in which current page state could
    # change after evaluation but before token consumption was serialized.
    locked_page = session.exec(
        select(GeneratedPage)
        .where(GeneratedPage.id == page_id)
        .with_for_update()
    ).first()
    if locked_page is None:
        raise HTTPException(status_code=409, detail="The generated page no longer exists.")
    prior_attempt = session.exec(
        select(WordPressMetadataSyncAudit).where(
            WordPressMetadataSyncAudit.data_backup_file_name == replay_marker
        )
    ).first()
    if prior_attempt is not None and prior_attempt.status != "verification_failed":
        raise HTTPException(status_code=409, detail="This staging confirmation token was already consumed.")

    # Rebuild from current governed Atlas rows and repeat the private inspection.
    # No caller payload is accepted or reused.
    evaluated = _evaluate_dry_run(
        session,
        page_id,
        no_network=False,
        issue_token=False,
    )
    if not evaluated.response.ready or evaluated.local is None or evaluated.remote is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "STAGING_PREFLIGHT_CHANGED",
                "blockers": evaluated.response.blockers,
            },
        )
    current_context = _token_context(
        evaluated.local,
        evaluated.response.registration,
        evaluated.response.media_readiness,
        evaluated.remote,
        request_identity=str(token.get("request_identity") or ""),
    )
    context_state = _token_context_state(
        token_context,
        current_context,
        evaluated.local,
        evaluated.remote,
    )
    if context_state is None:
        raise HTTPException(
            status_code=409,
            detail="The signed Atlas or remote staging state changed after dry-run.",
        )

    local = evaluated.local
    remote = evaluated.remote
    if locked_page.id != local.identity.generated_page_id:
        raise HTTPException(status_code=409, detail="The locked Generated Page identity changed.")

    payload_snapshot = {
        "metadata_key": V5_META_KEY,
        "payload_schema": V5_PAYLOAD_SCHEMA,
        "payload_sha256": local.payload_sha256,
        "identity": local.identity.model_dump(mode="json"),
        "registration": evaluated.response.registration.model_dump(mode="json"),
        "media": [item.model_dump(mode="json") for item in evaluated.response.media_readiness],
        "request_identity": request_identity,
        "expected_prior": {
            "metadata_exists": token_context.get("prior_metadata_exists"),
            "metadata_sha256": token_context.get("prior_metadata_sha256"),
            "metadata_valid": token_context.get("prior_metadata_valid"),
        },
    }
    if prior_attempt is not None:
        if not _retryable_audit_matches(
            prior_attempt,
            local,
            evaluated.response.target_staging_url or "",
            payload_snapshot,
            replay_marker,
        ):
            raise HTTPException(
                status_code=409,
                detail="The retryable staging audit differs from the signed operation.",
            )
        audit = prior_attempt
        audit.status = "pending"
        audit.completed_at = None
        audit.returned_snapshot = None
        audit.error_message = None
    else:
        audit = WordPressMetadataSyncAudit(
            generated_page_id=local.identity.generated_page_id,
            wordpress_post_id=local.identity.wordpress_post_id,
            action_type="apply_performance_local_v5_staging_payload",
            status="pending",
            attempted_at=datetime.now(UTC),
            wordpress_site_url=evaluated.response.target_staging_url or "",
            payload_hash=local.payload_sha256,
            payload_snapshot=payload_snapshot,
            previous_snapshot=payload_snapshot["expected_prior"],
            gate_results=[
                item.model_dump(mode="json")
                for item in evaluated.response.gate_results
            ],
            data_backup_file_name=replay_marker,
            wordpress_backup_reference="custom-route-cas-and-delete-rollback",
            plugin_version=V5_PLUGIN_VERSION,
        )
    session.add(audit)
    session.flush()

    route = _route_url(evaluated.response.target_staging_url or "", local.identity.wordpress_post_id)
    envelope = {
        "request_schema": V5_REQUEST_SCHEMA,
        "expected_prior_sha256": remote.metadata_sha256,
        "website_id": local.identity.website_id,
        "planned_page_id": local.identity.planned_page_id,
        "generated_page_id": local.identity.generated_page_id,
        "wordpress_post_id": local.identity.wordpress_post_id,
        "payload": local.payload,
        "request_identity": request_identity,
    }
    wordpress_post_count = 0
    wordpress_verification_get_count = 0
    reconciled_after_uncertainty = context_state == "reconciled"
    if _remote_metadata_is_exact(remote, local):
        applied = _reconciled_apply_result(
            local,
            remote,
            request_identity,
        )
        verified = remote
    else:
        try:
            wordpress_post_count = 1
            applied = _remote_post(session, route, envelope)
            _verify_apply_response(applied, local, remote, request_identity)
            wordpress_verification_get_count += 1
            verified = _remote_get(session, route)
            _verify_post_apply_inspection(
                verified,
                local,
                evaluated.response.target_staging_url or "",
            )
        except Exception as exc:
            try:
                wordpress_verification_get_count += 1
                reconciled = _remote_get(session, route)
                _verify_post_apply_inspection(
                    reconciled,
                    local,
                    evaluated.response.target_staging_url or "",
                )
            except Exception:
                audit.status = "verification_failed"
                audit.completed_at = datetime.now(UTC)
                audit.error_message = _sanitized_failure(exc)
                session.add(audit)
                _commit_staging_audit(session)
                if isinstance(exc, HTTPException):
                    raise
                raise HTTPException(
                    status_code=502,
                    detail="The staging metadata request failed or could not be verified.",
                ) from exc
            reconciled_after_uncertainty = True
            applied = _reconciled_apply_result(
                local,
                reconciled,
                request_identity,
            )
            verified = reconciled

    audit.status = "applied" if applied.status == "APPLIED" else "unchanged"
    audit.completed_at = datetime.now(UTC)
    audit.returned_snapshot = {
        "status": applied.status,
        "prior_sha256": applied.prior_sha256,
        "resulting_sha256": applied.resulting_sha256,
        "metadata_valid": applied.metadata_valid,
        "request_identity": applied.request_identity,
        "verified_get_sha256": verified.metadata_sha256,
        "reconciled_after_uncertainty": reconciled_after_uncertainty,
        "wordpress_post_count": wordpress_post_count,
        "wordpress_verification_get_count": wordpress_verification_get_count,
    }
    session.add(audit)
    _commit_staging_audit(session)

    return PerformanceLocalV5StagingApplyResult(
        status=applied.status,
        audit_id=audit.id or 0,
        target_staging_url=evaluated.response.target_staging_url or "",
        route=route,
        identity=local.identity,
        registration=evaluated.response.registration,
        payload_sha256=local.payload_sha256,
        prior_metadata_sha256=applied.prior_sha256,
        resulting_metadata_sha256=applied.resulting_sha256,
        request_identity=request_identity,
        unchanged_page_fields=list(UNCHANGED_PAGE_FIELDS),
        gate_results=evaluated.response.gate_results,
        wordpress_post_count=wordpress_post_count,
        wordpress_verification_get_count=wordpress_verification_get_count,
    )


def _evaluate_dry_run(
    session: Session,
    page_id: int,
    *,
    no_network: bool,
    issue_token: bool,
) -> _DryRunState:
    _require_target(page_id)
    gates: list[WordPressDraftGateResult] = []
    blockers: list[str] = []
    local: _LocalContext | None = None
    remote: PerformanceLocalV5RemoteInspection | None = None
    observed_identity: PerformanceLocalV5PageIdentity | None = None
    required_media_from_error: list[Any] = []

    migration = _current_migration(session)
    _append_gate(
        gates,
        blockers,
        "atlas_revision",
        "Atlas schema revision is exact",
        migration == EXPECTED_ALEMBIC_REVISION,
        "ATLAS_MIGRATION_REQUIRED",
        f"Alembic revision must be {EXPECTED_ALEMBIC_REVISION}.",
    )

    try:
        local = _build_local_context(session, page_id)
        _append_gate(
            gates,
            blockers,
            "governed_page_state",
            "Current Page, composition, immutable revision, and QA identities are exact",
            True,
            "GOVERNED_PAGE_STATE_CHANGED",
            "The governed Page 41 state is current and exact.",
        )
    except Exception as exc:
        required_media_from_error = [
            *list(getattr(exc, "required_media", []) or []),
            *list(getattr(exc, "required_logo_media", []) or []),
        ]
        if getattr(exc, "code", None) == "REMOTE_MEDIA_SYNC_REQUIRED":
            _extend_unique(blockers, ["REMOTE_MEDIA_SYNC_REQUIRED"])
            try:
                records = _current_page_records(session, page_id)
                source_identity = getattr(exc, "source_identity", None)
                if _unavailable_source_matches(records, source_identity):
                    observed_identity = records.identity
            except Exception:
                observed_identity = None
        _append_gate(
            gates,
            blockers,
            "governed_page_state",
            "Current Page, composition, immutable revision, and QA identities are exact",
            observed_identity is not None,
            "GOVERNED_PAGE_STATE_CHANGED",
            (
                "The governed Page, revision, composition, immutable revision, and QA identities are exact; media synchronization is pending."
                if observed_identity is not None
                else _safe_builder_message(exc)
            ),
        )

    website_id = (
        local.identity.website_id
        if local is not None
        else (
            observed_identity.website_id
            if observed_identity is not None
            else _website_id_for_page(session, page_id)
        )
    )
    registration, registration_gates, registration_blockers = _registration_state(session, website_id)
    gates.extend(registration_gates)
    _extend_unique(blockers, registration_blockers)

    # A dry-run reads only persisted, non-secret settings until every local
    # gate has passed. In particular, no-network mode never probes process
    # memory or the environment for the application password.
    settings = read_wordpress_settings(session, include_secret_presence=False)
    target_url = _normalized_site_url(settings.site_url)
    media = _media_readiness(
        session,
        local.required_media if local is not None else required_media_from_error,
        target_origin=_normalized_origin(target_url),
    )
    media_ready = bool(media) and all(item.ready for item in media)
    _append_gate(
        gates,
        blockers,
        "remote_media_readiness",
        "All governed media have exact WordPress identities",
        media_ready,
        "REMOTE_MEDIA_SYNC_REQUIRED",
        (
            "All governed media have exact WordPress IDs, URLs, status, and checksums."
            if media_ready
            else "Governed media must be synchronized separately before V5 staging activation."
        ),
    )

    payload_withheld_for_media = local is None and bool(required_media_from_error)
    payload_safe = payload_withheld_for_media or (
        local is not None and _payload_is_public(session, website_id, local.payload)
    )
    _append_gate(
        gates,
        blockers,
        "public_payload_privacy",
        "Payload excludes private delivery configuration",
        payload_safe,
        "PRIVATE_DATA_IN_PUBLIC_PAYLOAD",
        (
            (
                "No usable payload exists while governed media synchronization is pending."
                if payload_withheld_for_media
                else "The payload contains public display values only."
            )
            if payload_safe
            else "The candidate payload contains a forbidden private delivery key or value."
        ),
    )

    settings_configuration_ready = bool(
        target_url
        and settings.username
        and settings.publishing_mode == "sandbox"
    )
    prior_local_gates_ready = bool(
        settings_configuration_ready
        and not blockers
        and bool(gates)
        and all(gate.passed for gate in gates)
    )
    password_available = bool(
        get_wordpress_application_password()
        if prior_local_gates_ready and not no_network
        else None
    )
    settings_ready = prior_local_gates_ready and password_available
    _append_gate(
        gates,
        blockers,
        "staging_credentials",
        "Authenticated staging configuration is available",
        settings_ready,
        "STAGING_CREDENTIALS_REQUIRED",
        (
            "The authenticated HTTPS staging configuration is available."
            if settings_ready
            else (
                "No-network mode does not inspect process-memory credentials."
                if no_network
                else (
                    "Credential inspection is withheld until every local staging gate passes."
                    if not prior_local_gates_ready
                    else "The process-memory staging credential is unavailable."
                )
            )
        ),
    )

    route: str | None = None
    if target_url and local is not None:
        route = _route_url(target_url, local.identity.wordpress_post_id)

    if no_network:
        _append_gate(
            gates,
            blockers,
            "remote_inspection",
            "Private staging route was inspected",
            False,
            "REMOTE_INSPECTION_REQUIRED",
            "No-network mode intentionally performs zero WordPress requests and issues no token.",
        )
    elif (
        local is not None
        and target_url
        and settings_ready
        and not blockers
        and all(gate.passed for gate in gates)
    ):
        try:
            remote = _remote_get(session, route or "")
            remote_gates, remote_blockers = _remote_inspection_gates(
                remote,
                local,
                target_url,
            )
            gates.extend(remote_gates)
            _extend_unique(blockers, remote_blockers)
        except Exception as exc:
            _append_gate(
                gates,
                blockers,
                "remote_inspection",
                "Private staging route was inspected",
                False,
                "REMOTE_INSPECTION_FAILED",
                _sanitized_failure(exc),
            )
    else:
        _append_gate(
            gates,
            blockers,
            "remote_inspection",
            "Private staging route was inspected",
            False,
            "REMOTE_INSPECTION_REQUIRED",
            "Local gates or staging configuration prevent remote inspection.",
        )

    ready = (
        not no_network
        and local is not None
        and remote is not None
        and bool(gates)
        and all(gate.passed for gate in gates)
    )
    expires_at: datetime | None = None
    confirmation_token: str | None = None
    token_context: dict[str, Any] | None = None
    if ready and issue_token and local is not None and remote is not None:
        expires_at = datetime.now(UTC) + TOKEN_TTL
        request_identity = str(uuid4())
        token_context = _token_context(
            local,
            registration,
            media,
            remote,
            request_identity=request_identity,
        )
        confirmation_token = _encode_token(
            action=TOKEN_ACTION,
            page_id=page_id,
            request_identity=request_identity,
            context=token_context,
            expires_at=expires_at,
        )

    response = PerformanceLocalV5StagingDryRun(
        status="DRY_RUN_READY" if ready else "BLOCKED",
        ready=ready,
        no_network=no_network,
        target_staging_url=target_url,
        route=route,
        identity=local.identity if local is not None else observed_identity,
        registration=registration,
        payload_sha256=local.payload_sha256 if local is not None else None,
        current_remote_metadata_sha256=remote.metadata_sha256 if remote is not None else None,
        media_readiness=media,
        unchanged_page_fields=list(UNCHANGED_PAGE_FIELDS),
        blockers=blockers,
        gate_results=gates,
        confirmation_token=confirmation_token,
        confirmation_phrase=(
            _confirmation_phrase(local.identity.wordpress_post_id)
            if confirmation_token and local is not None
            else None
        ),
        expires_at=expires_at,
    )
    return _DryRunState(
        response=response,
        local=local,
        remote=remote,
        token_context=token_context,
    )


def _build_local_context(session: Session, page_id: int) -> _LocalContext:
    from app.services.performance_local_v5_payload import (
        build_performance_local_v5_staging_payload,
    )

    records = _current_page_records(session, page_id)
    built = build_performance_local_v5_staging_payload(session, page_id)
    payload = _field(built, "payload")
    payload_hash = _field(built, "payload_hash", _field(built, "payload_sha256"))
    required_media = [
        *list(_field(built, "required_media", []) or []),
        *list(_field(built, "required_logo_media", []) or []),
    ]
    if not isinstance(payload, dict) or not _is_sha256(payload_hash):
        raise ValueError("The V5 payload builder returned an invalid governed payload identity.")
    if _field(built, "website_id", records.planned.website_id) != records.planned.website_id:
        raise ValueError("The V5 payload builder Website identity changed.")
    if _field(built, "planned_page_id", records.planned.id) != records.planned.id:
        raise ValueError("The V5 payload builder Planned Page identity changed.")
    if _field(built, "generated_page_id", records.generated.id) != records.generated.id:
        raise ValueError("The V5 payload builder Generated Page identity changed.")
    if _field(built, "wordpress_post_id", records.generated.wordpress_post_id) != records.generated.wordpress_post_id:
        raise ValueError("The V5 payload builder WordPress target changed.")
    if _field(built, "metadata_key", V5_META_KEY) != V5_META_KEY:
        raise ValueError("The V5 payload metadata key changed.")
    if _field(built, "payload_schema", V5_PAYLOAD_SCHEMA) != V5_PAYLOAD_SCHEMA:
        raise ValueError("The V5 payload schema changed.")
    if _field(built, "template_value") is not None:
        raise ValueError("The V5 payload builder may not request a WordPress template write.")
    bindings = _field(built, "source_bindings")
    if not all(
        (
            _field(bindings, "generated_page_revision_id") == records.revision.id,
            _field(bindings, "generated_page_revision_hash") == records.revision.draft_hash_after,
            _field(bindings, "page_composition_id") == records.composition.id,
            _field(bindings, "composition_version") == records.composition.composition_version,
            _field(bindings, "page_composition_revision_id") == records.immutable.id,
            _field(bindings, "page_composition_revision_hash") == records.immutable.revision_hash,
            _field(bindings, "composition_source_hash") == records.composition.source_hash,
            _field(bindings, "qa_result_id") == records.qa.id,
            _field(bindings, "qa_result_hash") == records.qa.result_hash,
        )
    ):
        raise ValueError("The V5 payload source bindings do not match current Atlas rows.")

    return _LocalContext(
        identity=records.identity,
        payload=payload,
        payload_sha256=str(payload_hash),
        required_media=list(required_media or []),
    )


def _current_page_records(session: Session, page_id: int) -> _PageRecords:
    generated = session.get(GeneratedPage, page_id)
    if generated is None or generated.id is None:
        raise ValueError("The requested Generated Page was not found.")
    planned_rows = session.exec(
        select(PlannedPage).where(PlannedPage.generated_page_id == generated.id)
    ).all()
    if len(planned_rows) != 1:
        raise ValueError("The Generated Page must bind exactly one Planned Page.")
    planned = planned_rows[0]
    if planned.id is None or planned.page_type.replace("-", "_").lower() != TARGET_PAGE_TYPE:
        raise ValueError("The target must remain a City-Service page.")
    if generated.website_id != planned.website_id or generated.page_type.replace("-", "_").lower() != TARGET_PAGE_TYPE:
        raise ValueError("The Generated Page scope changed.")
    if generated.wordpress_post_id is None or generated.wordpress_post_id <= 0:
        raise ValueError("The Generated Page must have one positive WordPress post identity.")
    if generated.status != "published" or generated.wordpress_status != "publish":
        raise ValueError("The target must remain published in Atlas and WordPress.")

    revision = session.exec(
        select(GeneratedPageRevision)
        .where(GeneratedPageRevision.generated_page_id == generated.id)
        .order_by(GeneratedPageRevision.created_at.desc(), GeneratedPageRevision.id.desc())
    ).first()
    composition = session.exec(
        select(PageComposition).where(
            PageComposition.planned_page_id == planned.id,
            PageComposition.generated_page_id == generated.id,
        )
    ).first()
    if revision is None or revision.id is None or composition is None or composition.id is None:
        raise ValueError("The current Generated Page revision or composition is missing.")
    if composition.status != "current":
        raise ValueError("The Page composition is not current.")
    immutable = session.exec(
        select(PageCompositionRevision).where(
            PageCompositionRevision.page_composition_id == composition.id,
            PageCompositionRevision.composition_version == composition.composition_version,
            PageCompositionRevision.source_hash == composition.source_hash,
        )
    ).first()
    qa = session.exec(
        select(GeneratedPageQAResult).where(
            GeneratedPageQAResult.generated_page_id == generated.id,
            GeneratedPageQAResult.lifecycle_status == "current",
        )
    ).first()
    if immutable is None or immutable.id is None:
        raise ValueError("The exact immutable composition revision is missing.")
    if qa is None or qa.id is None:
        raise ValueError("The current Page QA result is missing.")
    if not all(
        (
            qa.website_id == planned.website_id,
            qa.planned_page_id == planned.id,
            qa.latest_generated_page_revision_id == revision.id,
            qa.page_composition_id == composition.id,
            qa.composition_version == composition.composition_version,
            qa.composition_source_hash == composition.source_hash,
            qa.readiness_status == "ready",
            qa.warning_count == 0,
            qa.failed_count == 0,
        )
    ):
        raise ValueError("Page QA does not bind the exact current revision and composition.")
    identity = PerformanceLocalV5PageIdentity(
        website_id=planned.website_id,
        planned_page_id=planned.id,
        generated_page_id=generated.id,
        generated_page_revision_id=revision.id,
        composition_id=composition.id,
        composition_version=composition.composition_version,
        immutable_composition_revision_id=immutable.id,
        qa_result_id=qa.id,
        wordpress_post_id=generated.wordpress_post_id,
        wordpress_post_status=generated.wordpress_status,
        page_title=generated.page_title,
        page_slug=generated.page_slug,
    )
    return _PageRecords(
        planned=planned,
        generated=generated,
        revision=revision,
        composition=composition,
        immutable=immutable,
        qa=qa,
        identity=identity,
    )


def _unavailable_source_matches(records: _PageRecords, source_identity: Any) -> bool:
    bindings = _field(source_identity, "source_bindings")
    return all(
        (
            _field(source_identity, "website_id") == records.identity.website_id,
            _field(source_identity, "planned_page_id") == records.identity.planned_page_id,
            _field(source_identity, "generated_page_id") == records.identity.generated_page_id,
            _field(source_identity, "wordpress_post_id") == records.identity.wordpress_post_id,
            _field(bindings, "generated_page_revision_id") == records.revision.id,
            _field(bindings, "generated_page_revision_hash") == records.revision.draft_hash_after,
            _field(bindings, "page_composition_id") == records.composition.id,
            _field(bindings, "composition_version") == records.composition.composition_version,
            _field(bindings, "page_composition_revision_id") == records.immutable.id,
            _field(bindings, "page_composition_revision_hash") == records.immutable.revision_hash,
            _field(bindings, "composition_source_hash") == records.composition.source_hash,
            _field(bindings, "qa_result_id") == records.qa.id,
            _field(bindings, "qa_result_hash") == records.qa.result_hash,
        )
    )


def _registration_state(
    session: Session,
    website_id: int | None,
) -> tuple[
    PerformanceLocalV5RegistrationIdentity,
    list[WordPressDraftGateResult],
    list[str],
]:
    from app.services.performance_local_v5_registration import (
        plan_performance_local_v5_registration,
    )

    gates: list[WordPressDraftGateResult] = []
    blockers: list[str] = []
    if website_id is None:
        registration = PerformanceLocalV5RegistrationIdentity()
        _append_gate(
            gates,
            blockers,
            "v5_registration",
            "Performance Local V5 is durably registered and selected",
            False,
            "V5_REGISTRATION_REQUIRED",
            "The Website identity could not be resolved.",
        )
        return registration, gates, blockers
    try:
        plan = plan_performance_local_v5_registration(session, website_id)
    except Exception:
        registration = PerformanceLocalV5RegistrationIdentity()
        _append_gate(
            gates,
            blockers,
            "v5_registration",
            "Performance Local V5 is durably registered and selected",
            False,
            "V5_REGISTRATION_CONFLICT",
            "The canonical V5 registration planner could not prove an exact durable graph.",
        )
        return registration, gates, blockers
    ready = plan.status == "UNCHANGED"
    identity = plan.identity
    registration = PerformanceLocalV5RegistrationIdentity(
        theme_family_id=identity.theme_family_id,
        theme_family_version_id=identity.theme_family_version_id,
        theme_family_version=5 if identity.theme_family_version_id is not None else None,
        website_theme_configuration_id=identity.website_theme_configuration_id,
        component_configuration_ids=list(identity.component_configuration_ids),
        materialized_theme_id=identity.materialized_theme_id,
        website_theme_selection_id=identity.website_theme_selection_id,
        expected_source_commit=plan.expected_source_commit,
        expected_contract_fingerprint=plan.expected_contract_fingerprint,
        ready=ready,
    )
    blocker = (
        "V5_REGISTRATION_REQUIRED"
        if plan.status == "PLANNED"
        else "V5_REGISTRATION_CONFLICT"
    )
    _append_gate(
        gates,
        blockers,
        "v5_registration",
        "Performance Local V5 is durably registered and selected",
        ready,
        blocker,
        (
            "The exact registered, production-ready V5 family/configuration/Theme selection is active."
            if ready
            else (
                "Performance Local V5 must be registered in a separate governed action."
                if plan.status == "PLANNED"
                else "The durable V5 graph conflicts with the canonical registration contract."
            )
        ),
    )
    return registration, gates, blockers


def _media_readiness(
    session: Session,
    required_media: list[Any],
    *,
    target_origin: str | None = None,
) -> list[PerformanceLocalV5MediaReadiness]:
    results: list[PerformanceLocalV5MediaReadiness] = []
    for item in required_media:
        if _first_field(item, "brand_asset_id") is not None or _first_field(
            item, "role"
        ) is not None:
            results.append(
                _logo_media_readiness(
                    session,
                    item,
                    target_origin=target_origin,
                )
            )
            continue
        requirement_id = _first_field(item, "requirement_id", "media_requirement_id", default=0)
        asset_id = _first_field(item, "asset_id", "brand_asset_id", "image_metadata_id", default=0)
        asset_hash = _first_field(
            item,
            "asset_sha256",
            "sha256",
            "checksum_sha256",
            "source_sha256",
            default="",
        )
        image = session.get(ImageMetadata, asset_id) if isinstance(asset_id, int) and asset_id > 0 else None
        media_id = _first_field(item, "wordpress_media_id", "wp_media_id")
        media_url = _first_field(item, "wordpress_media_url", "wp_media_url")
        media_status = image.wordpress_media_status if image is not None else None
        media_checksum = image.wordpress_media_checksum if image is not None else None
        source_file_name = image.file_name if image is not None else None
        source_mime_type = image.mime_type if image is not None else None
        source_width = image.width if image is not None else None
        source_height = image.height if image is not None else None
        payload_src = _first_field(item, "payload_src", default="")
        authorization_id = _first_field(item, "authorization_id", "media_authorization_id")
        authorization_version = _first_field(item, "authorization_version")
        authorization_fingerprint = _first_field(item, "authorization_fingerprint")
        parsed_media_url = _safe_media_url(media_url)
        ready = bool(
            isinstance(requirement_id, int)
            and requirement_id > 0
            and isinstance(asset_id, int)
            and asset_id > 0
            and _is_sha256(asset_hash)
            and isinstance(media_id, int)
            and media_id > 0
            and isinstance(media_url, str)
            and parsed_media_url is not None
            and parsed_media_url[0] == target_origin
            and parsed_media_url[1] == payload_src
            and _safe_wordpress_upload_path(str(payload_src))
            and media_status in {
                "uploaded",
                "verified",
                "active",
                "available",
                "reconciled",
            }
            and hmac.compare_digest(str(media_checksum or ""), str(asset_hash))
            and image is not None
            and image.wordpress_media_id == media_id
            and image.wordpress_media_url == media_url
            and image.checksum_sha256 == asset_hash
            and isinstance(source_file_name, str)
            and bool(source_file_name.strip())
            and isinstance(source_mime_type, str)
            and bool(source_mime_type.strip())
            and type(source_width) is int
            and source_width > 0
            and type(source_height) is int
            and source_height > 0
            and isinstance(authorization_id, int)
            and authorization_id > 0
            and isinstance(authorization_version, int)
            and authorization_version > 0
            and _is_sha256(authorization_fingerprint)
        )
        results.append(
            PerformanceLocalV5MediaReadiness(
                identity_kind="page_media",
                requirement_id=int(requirement_id or 0),
                placement_key=_first_field(item, "placement_key"),
                target_component_instance_key=_first_field(
                    item,
                    "target_component_instance_key",
                ),
                assignment_id=_first_field(item, "assignment_id", "page_image_assignment_id"),
                assignment_version=_first_field(item, "assignment_version"),
                asset_id=int(asset_id or 0),
                media_key=_first_field(item, "media_key"),
                media_version=_first_field(item, "media_version"),
                authorization_id=authorization_id,
                authorization_version=authorization_version,
                authorization_fingerprint=authorization_fingerprint,
                asset_sha256=str(asset_hash),
                source_file_name=source_file_name,
                source_mime_type=source_mime_type,
                source_width=source_width,
                source_height=source_height,
                wordpress_media_id=media_id,
                wordpress_media_url=media_url,
                wordpress_media_status=media_status,
                wordpress_media_checksum=media_checksum,
                ready=ready,
                blocker=None if ready else "REMOTE_MEDIA_SYNC_REQUIRED",
            )
        )
    return results


def _logo_media_readiness(
    session: Session,
    item: Any,
    *,
    target_origin: str | None,
) -> PerformanceLocalV5MediaReadiness:
    role = _first_field(item, "role")
    asset_id = _first_field(item, "brand_asset_id", "asset_id", default=0)
    asset_key = _first_field(item, "asset_key")
    asset_version = _first_field(item, "asset_version", "version")
    asset_hash = _first_field(item, "checksum_sha256", "asset_sha256", default="")
    expected_file_name = _first_field(item, "source_filename", "source_file_name")
    expected_mime_type = _first_field(item, "source_mime_type")
    expected_width = _first_field(item, "source_width")
    expected_height = _first_field(item, "source_height")
    governed_asset_url = _first_field(item, "governed_asset_url")
    payload_src = _first_field(item, "payload_src", default="")
    asset = (
        session.get(BrandAsset, asset_id)
        if isinstance(asset_id, int) and asset_id > 0
        else None
    )
    current_url = (
        asset.optimized_url or asset.asset_url
        if asset is not None
        else None
    )
    parsed_asset_url = _safe_media_url(governed_asset_url)
    governed_identity_is_current = bool(
        role in {"header_logo", "footer_logo"}
        and isinstance(asset_id, int)
        and asset_id > 0
        and isinstance(asset_key, str)
        and bool(asset_key.strip())
        and isinstance(asset_version, int)
        and asset_version > 0
        and _is_sha256(asset_hash)
        and isinstance(expected_file_name, str)
        and bool(expected_file_name.strip())
        and isinstance(expected_mime_type, str)
        and expected_mime_type.startswith("image/")
        and type(expected_width) is int
        and expected_width > 0
        and type(expected_height) is int
        and expected_height > 0
        and parsed_asset_url is not None
        and parsed_asset_url[0] == target_origin
        and parsed_asset_url[1] == payload_src
        and asset is not None
        and asset.status == "approved"
        and asset.asset_key == asset_key
        and asset.version == asset_version
        and asset.checksum_sha256 == asset_hash
        and asset.original_filename == expected_file_name
        and asset.mime_type == expected_mime_type
        and asset.width == expected_width
        and asset.height == expected_height
        and current_url == governed_asset_url
    )
    # Even an exact current Brand Asset and a same-origin Bridge path do not
    # prove that the remote bytes exist.  Keep the local identity available for
    # reporting and token binding, but fail closed until a separately governed
    # transport proof exists.
    return PerformanceLocalV5MediaReadiness(
        identity_kind="brand_asset",
        requirement_id=None,
        asset_id=int(asset_id or 0),
        brand_asset_id=int(asset_id or 0),
        role=role,
        asset_key=asset_key,
        asset_version=asset_version,
        asset_sha256=str(asset_hash),
        source_file_name=expected_file_name,
        source_mime_type=expected_mime_type,
        source_width=expected_width,
        source_height=expected_height,
        governed_asset_url=governed_asset_url,
        wordpress_media_url=None,
        ready=False,
        blocker=(
            "REMOTE_MEDIA_SYNC_REQUIRED"
            if governed_identity_is_current
            else "GOVERNED_LOGO_IDENTITY_CHANGED"
        ),
    )


def _safe_media_url(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not _safe_wordpress_upload_path(parsed.path)
    ):
        return None
    origin = _normalized_origin(value)
    return (origin, parsed.path) if origin else None


def _safe_wordpress_upload_path(path: str) -> bool:
    """Mirror the narrow Bridge upload-path contract for remote readiness."""

    if not isinstance(path, str) or "%" in path or "\\" in path:
        return False
    legacy = re.fullmatch(
        r"/wp-content/uploads/atlas-v5/"
        r"[A-Za-z0-9][A-Za-z0-9._-]*"
        r"(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*"
        r"\.(?:avif|jpe?g|png|svg|webp)",
        path,
        flags=re.IGNORECASE,
    )
    dated = re.fullmatch(
        r"/wp-content/uploads/[1-9][0-9]{3}/(?:0[1-9]|1[0-2])/"
        r"[A-Za-z0-9][A-Za-z0-9._-]*\.(?:avif|jpe?g|png|svg|webp)",
        path,
        flags=re.IGNORECASE,
    )
    return legacy is not None or dated is not None


def _remote_inspection_gates(
    remote: PerformanceLocalV5RemoteInspection,
    local: _LocalContext,
    target_url: str,
) -> tuple[list[WordPressDraftGateResult], list[str]]:
    gates: list[WordPressDraftGateResult] = []
    blockers: list[str] = []

    checks = [
        (
            "remote_contract",
            "Private route and plugin version are exact",
            remote.route_schema == V5_ROUTE_SCHEMA
            and remote.metadata_bridge_version == V5_PLUGIN_VERSION,
            "REMOTE_PLUGIN_CONTRACT_MISMATCH",
        ),
        (
            "remote_environment",
            "Remote target is private staging",
            remote.environment_type == "staging"
            and remote.blog_public == 0
            and _normalized_site_url(remote.home) == target_url
            and _normalized_site_url(remote.siteurl) == target_url,
            "REMOTE_TARGET_NOT_PRIVATE_STAGING",
        ),
        (
            "remote_post_identity",
            "Remote post identity is exact",
            remote.post_id == local.identity.wordpress_post_id
            and remote.post_type == "page"
            and remote.post_status == local.identity.wordpress_post_status
            and remote.post_title == local.identity.page_title
            and remote.post_slug == local.identity.page_slug,
            "REMOTE_POST_IDENTITY_MISMATCH",
        ),
    ]
    for code, label, passed, blocker in checks:
        _append_gate(gates, blockers, code, label, passed, blocker, label + ("." if passed else " failed."))

    metadata_compatible = (
        (not remote.metadata_exists and remote.metadata_sha256 is None)
        or (
            remote.metadata_exists
            and remote.metadata_valid
            and remote.metadata_sha256 == local.payload_sha256
        )
    )
    _append_gate(
        gates,
        blockers,
        "remote_metadata_state",
        "Remote V5 metadata is absent or already identical",
        metadata_compatible,
        "REMOTE_METADATA_CONFLICT",
        (
            "Remote V5 metadata is absent or already identical."
            if metadata_compatible
            else "Existing remote V5 metadata differs or is invalid; activation is blocked."
        ),
    )
    return gates, blockers


def _remote_get(session: Session, route: str) -> PerformanceLocalV5RemoteInspection:
    settings = read_wordpress_settings(session, include_secret_presence=False)
    password = get_wordpress_application_password()
    if not settings.username or not password:
        raise HTTPException(status_code=409, detail="Staging application-password credentials are unavailable.")
    auth = wordpress_basic_auth(settings.username, password)
    try:
        with wordpress_http_client(settings.site_url, timeout=15.0, follow_redirects=False) as client:
            response = client.get(route, auth=auth)
    except httpx.HTTPError as exc:
        source, reason = classify_wordpress_exception(exc)
        raise HTTPException(status_code=502, detail=f"{source}:{reason}") from exc
    source, reason = classify_wordpress_response(response)
    if response.status_code != 200 or source != "wordpress_json_success":
        raise HTTPException(status_code=502, detail=f"remote_get_rejected:{reason}")
    try:
        return PerformanceLocalV5RemoteInspection.model_validate(response.json())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="remote_get_contract_invalid") from exc


def _remote_post(
    session: Session,
    route: str,
    envelope: dict[str, Any],
) -> PerformanceLocalV5RemoteApplyResult:
    settings = read_wordpress_settings(session, include_secret_presence=False)
    password = get_wordpress_application_password()
    if not settings.username or not password:
        raise HTTPException(status_code=409, detail="Staging application-password credentials are unavailable.")
    auth = wordpress_basic_auth(settings.username, password)
    try:
        with wordpress_http_client(settings.site_url, timeout=30.0, follow_redirects=False) as client:
            response = client.post(route, auth=auth, json=envelope)
    except httpx.HTTPError as exc:
        source, reason = classify_wordpress_exception(exc)
        raise HTTPException(status_code=502, detail=f"{source}:{reason}") from exc
    source, reason = classify_wordpress_response(response)
    if response.status_code != 200 or source != "wordpress_json_success":
        raise HTTPException(status_code=502, detail=f"remote_post_rejected:{reason}")
    try:
        return PerformanceLocalV5RemoteApplyResult.model_validate(response.json())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="remote_post_contract_invalid") from exc


def _verify_apply_response(
    applied: PerformanceLocalV5RemoteApplyResult,
    local: _LocalContext,
    prior: PerformanceLocalV5RemoteInspection,
    request_identity: str,
) -> None:
    if not all(
        (
            applied.route_schema == V5_ROUTE_SCHEMA,
            applied.metadata_bridge_version == V5_PLUGIN_VERSION,
            applied.post_id == local.identity.wordpress_post_id,
            applied.prior_sha256 == prior.metadata_sha256,
            applied.resulting_sha256 == local.payload_sha256,
            applied.website_id == local.identity.website_id,
            applied.planned_page_id == local.identity.planned_page_id,
            applied.generated_page_id == local.identity.generated_page_id,
            applied.request_identity == request_identity,
            applied.metadata_valid is True,
        )
    ):
        raise HTTPException(status_code=502, detail="The staging apply response identity is invalid.")


def _verify_post_apply_inspection(
    remote: PerformanceLocalV5RemoteInspection,
    local: _LocalContext,
    expected_target_url: str,
) -> None:
    gates, blockers = _remote_inspection_gates(
        remote,
        local,
        expected_target_url,
    )
    if blockers or not remote.metadata_exists or remote.metadata_sha256 != local.payload_sha256:
        raise HTTPException(
            status_code=502,
            detail={"code": "POST_APPLY_VERIFICATION_FAILED", "blockers": blockers},
        )
    if not all(gate.passed for gate in gates):
        raise HTTPException(status_code=502, detail="Post-apply staging inspection failed.")


def _token_context(
    local: _LocalContext,
    registration: PerformanceLocalV5RegistrationIdentity,
    media: list[PerformanceLocalV5MediaReadiness],
    remote: PerformanceLocalV5RemoteInspection,
    *,
    request_identity: str,
) -> dict[str, Any]:
    return {
        "identity": local.identity.model_dump(mode="json"),
        "registration": registration.model_dump(mode="json"),
        "media_identity_sha256": _canonical_sha256(
            [item.model_dump(mode="json") for item in media]
        ),
        "payload_sha256": local.payload_sha256,
        "metadata_key": V5_META_KEY,
        "payload_schema": V5_PAYLOAD_SCHEMA,
        "route_schema": remote.route_schema,
        "plugin_version": remote.metadata_bridge_version,
        "environment_type": remote.environment_type,
        "target_home": _normalized_site_url(remote.home),
        "target_siteurl": _normalized_site_url(remote.siteurl),
        "blog_public": remote.blog_public,
        "remote_post": {
            "id": remote.post_id,
            "type": remote.post_type,
            "status": remote.post_status,
            "title": remote.post_title,
            "slug": remote.post_slug,
        },
        "prior_metadata_sha256": remote.metadata_sha256,
        "prior_metadata_exists": remote.metadata_exists,
        "prior_metadata_valid": remote.metadata_valid,
        "request_identity": request_identity,
    }


def _token_context_state(
    signed: dict[str, Any],
    current: dict[str, Any],
    local: _LocalContext,
    remote: PerformanceLocalV5RemoteInspection,
) -> str | None:
    """Return the sole safe token-state relationship for apply/retry.

    An exact context is the ordinary apply path. The only accepted transition
    is the remote metadata moving to the exact desired valid hash, which is the
    observable state left by a successful WordPress write whose response or
    local audit commit was lost. Every other signed local and remote identity
    must remain byte-for-byte equivalent.
    """

    if signed == current:
        return "exact"
    if not _remote_metadata_is_exact(remote, local):
        return None
    adjusted = dict(current)
    for key in (
        "prior_metadata_sha256",
        "prior_metadata_exists",
        "prior_metadata_valid",
    ):
        adjusted[key] = signed.get(key)
    return "reconciled" if adjusted == signed else None


def _remote_metadata_is_exact(
    remote: PerformanceLocalV5RemoteInspection,
    local: _LocalContext,
) -> bool:
    return bool(
        remote.metadata_exists
        and remote.metadata_valid
        and remote.metadata_sha256 == local.payload_sha256
    )


def _reconciled_apply_result(
    local: _LocalContext,
    remote: PerformanceLocalV5RemoteInspection,
    request_identity: str,
) -> PerformanceLocalV5RemoteApplyResult:
    """Represent proven current desired state without another remote mutation."""

    return PerformanceLocalV5RemoteApplyResult(
        route_schema=V5_ROUTE_SCHEMA,
        metadata_bridge_version=V5_PLUGIN_VERSION,
        status="UNCHANGED",
        post_id=local.identity.wordpress_post_id,
        prior_sha256=remote.metadata_sha256,
        resulting_sha256=local.payload_sha256,
        website_id=local.identity.website_id,
        planned_page_id=local.identity.planned_page_id,
        generated_page_id=local.identity.generated_page_id,
        request_identity=request_identity,
        metadata_valid=True,
    )


def _retryable_audit_matches(
    audit: WordPressMetadataSyncAudit,
    local: _LocalContext,
    target_url: str,
    payload_snapshot: dict[str, Any],
    replay_marker: str,
) -> bool:
    """Bind a retry to the exact prior verification-failed operation."""

    return all(
        (
            audit.status == "verification_failed",
            audit.generated_page_id == local.identity.generated_page_id,
            audit.wordpress_post_id == local.identity.wordpress_post_id,
            audit.action_type == "apply_performance_local_v5_staging_payload",
            audit.wordpress_site_url == target_url,
            audit.payload_hash == local.payload_sha256,
            audit.payload_snapshot == payload_snapshot,
            audit.data_backup_file_name == replay_marker,
            audit.wordpress_backup_reference == "custom-route-cas-and-delete-rollback",
            audit.plugin_version == V5_PLUGIN_VERSION,
        )
    )


def _commit_staging_audit(session: Session) -> None:
    """Persist the sole audit transition or leave the operation retryable."""

    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail=(
                "The staging audit could not be persisted; the same signed "
                "operation may be retried for exact state reconciliation."
            ),
        ) from exc


def _encode_token(
    *,
    action: str,
    page_id: int,
    request_identity: str,
    context: dict[str, Any],
    expires_at: datetime,
) -> str:
    body = {
        "action": action,
        "page_id": page_id,
        "request_identity": request_identity,
        "context": context,
        "issued_at": int(datetime.now(UTC).timestamp()),
        "expires_at": int(expires_at.timestamp()),
        "nonce": secrets.token_hex(16),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(_token_secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _decode_token(token: str, *, action: str) -> dict[str, Any]:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(_token_secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        padded = encoded + "=" * (-len(encoded) % 4)
        body = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="The staging confirmation token is invalid.") from exc
    if not isinstance(body, dict) or body.get("action") != action:
        raise HTTPException(status_code=422, detail="The token is for a different action.")
    issued_at = body.get("issued_at")
    expires_at = body.get("expires_at")
    now = int(datetime.now(UTC).timestamp())
    max_lifetime = int(TOKEN_TTL.total_seconds())
    if (
        type(issued_at) is not int
        or type(expires_at) is not int
        or issued_at > now + 5
        or expires_at <= now
        or expires_at <= issued_at
        or expires_at - issued_at > max_lifetime
    ):
        raise HTTPException(status_code=422, detail="The staging confirmation token expired.")
    request_identity = body.get("request_identity")
    nonce = body.get("nonce")
    context = body.get("context")
    if (
        not isinstance(context, dict)
        or not _is_uuid4(request_identity)
        or context.get("request_identity") != request_identity
        or not isinstance(nonce, str)
        or re.fullmatch(r"[0-9a-f]{32}", nonce) is None
        or type(body.get("page_id")) is not int
        or body["page_id"] <= 0
    ):
        raise HTTPException(status_code=422, detail="The staging confirmation token is incomplete.")
    return body


def _is_uuid4(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value


def _payload_is_public(session: Session, website_id: int | None, payload: dict[str, Any]) -> bool:
    if _contains_sensitive_key(payload):
        return False
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).casefold()
    if website_id is None:
        return False
    recipients = session.exec(
        select(WebsiteFormRecipientRevision).where(
            WebsiteFormRecipientRevision.website_id == website_id
        )
    ).all()
    for recipient in recipients:
        for value in (recipient.email, recipient.normalized_email):
            if value and value.casefold() in serialized:
                return False
    modes = session.exec(
        select(WebsiteFormDeliveryModeRevision).where(
            WebsiteFormDeliveryModeRevision.website_id == website_id
        )
    ).all()
    for mode in modes:
        private_values = _private_delivery_values(mode.configuration_payload)
        if isinstance(mode.destination_identity, str) and "@" in mode.destination_identity:
            private_values.add(mode.destination_identity)
        if any(value.casefold() in serialized for value in private_values):
            return False
    return True


def _private_delivery_values(value: Any, *, private_scope: bool = False) -> set[str]:
    private_keys = {
        "destination_email",
        "from_email",
        "recipient_email",
        "recipient_emails",
        "recipients",
        "reply_to",
        "to_email",
    }
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            found.update(
                _private_delivery_values(
                    child,
                    private_scope=private_scope or normalized in private_keys,
                )
            )
    elif isinstance(value, list):
        for child in value:
            found.update(_private_delivery_values(child, private_scope=private_scope))
    elif private_scope and isinstance(value, str) and "@" in value:
        found.add(value.strip())
    return {item for item in found if item}


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            if (
                normalized in _SENSITIVE_KEYS
                or normalized.endswith(("_password", "_secret", "_credential"))
                or normalized.startswith("smtp_")
            ):
                return True
            if _contains_sensitive_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(child) for child in value)
    return False


def _current_migration(session: Session) -> str | None:
    try:
        result = session.exec(text("SELECT version_num FROM alembic_version"))
        row = result.first()
    except Exception:
        return None
    if row is None:
        return None
    if isinstance(row, str):
        return row
    try:
        return str(row[0])
    except (KeyError, TypeError, IndexError):
        return None


def _website_id_for_page(session: Session, page_id: int) -> int | None:
    generated = session.get(GeneratedPage, page_id)
    return generated.website_id if generated is not None else None


def _require_target(page_id: int) -> None:
    if page_id <= 0:
        raise HTTPException(
            status_code=422,
            detail="A positive Generated Page identity is required.",
        )


def _lock_staging_source_tables(session: Session) -> None:
    """Fence every mutable local gate input through the apply transaction."""

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    session.exec(
        text(
            "LOCK TABLE "
            + ", ".join(_STAGING_SOURCE_TABLES)
            + " IN SHARE MODE"
        )
    )


def _confirmation_phrase(wordpress_post_id: Any) -> str:
    if not isinstance(wordpress_post_id, int) or wordpress_post_id <= 0:
        raise HTTPException(status_code=422, detail="The WordPress post identity is invalid.")
    return f"APPLY PERFORMANCE LOCAL V5 TO STAGING PAGE {wordpress_post_id}"


def _route_url(site_url: str, post_id: int) -> str:
    normalized = _normalized_site_url(site_url)
    if not normalized:
        raise HTTPException(status_code=409, detail="A valid staging origin is required.")
    return f"{normalized}{ROUTE_PATH.format(post_id=post_id)}"


def _normalized_origin(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port}"


def _normalized_site_url(value: str | None) -> str | None:
    origin = _normalized_origin(value)
    if origin is None or value is None:
        return None
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return None
    if parsed.scheme.lower() != "https":
        return None
    path = parsed.path.rstrip("/")
    if any(part in {".", ".."} for part in path.split("/")):
        return None
    return f"{origin}{path}"


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _append_gate(
    gates: list[WordPressDraftGateResult],
    blockers: list[str],
    code: str,
    label: str,
    passed: bool,
    blocker: str,
    message: str,
) -> None:
    gates.append(WordPressDraftGateResult(code=code, label=label, passed=passed, message=message))
    if not passed and blocker not in blockers:
        blockers.append(blocker)


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _first_field(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        candidate = _field(value, name)
        if candidate is not None:
            return candidate
    return default


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def _safe_builder_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException) and isinstance(exc.detail, str):
        return exc.detail[:300]
    if getattr(exc, "code", None) == "REMOTE_MEDIA_SYNC_REQUIRED":
        return "The governed V5 payload is blocked until the exact media identities are synchronized."
    return "The governed V5 payload could not be built from the current Atlas state."


def _sanitized_failure(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, str):
            return detail[:300]
        if isinstance(detail, dict):
            code = detail.get("code")
            return str(code or "wordpress_contract_failure")[:300]
    if isinstance(exc, httpx.HTTPError):
        source, reason = classify_wordpress_exception(exc)
        return f"{source}:{reason}"
    return "staging_contract_verification_failed"
