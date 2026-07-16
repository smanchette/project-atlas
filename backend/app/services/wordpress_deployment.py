from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
from threading import Lock, Timer
from typing import Any
from urllib.parse import unquote
import zipfile

import httpx
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.backup import BackupValidationError, load_backup, resolve_backup_download
from app.models import (
    GeneratedPage,
    ImageMetadata,
    WordPressDeploymentAudit,
    WordPressDeploymentNonce,
    WordPressDeploymentTransition,
    WordPressMetadataState,
    WordPressMetadataSyncAudit,
)
from app.schemas.wordpress import (
    WordPressDeploymentAuthorizeRequest,
    WordPressDeploymentAuthorization,
    WordPressDeploymentBackupEvidence,
    WordPressDeploymentInstallDryRun,
    WordPressDeploymentPreflight,
    WordPressDeploymentReconciliationApplyRequest,
    WordPressDeploymentReconciliationResult,
    WordPressDeploymentReconciliationVerification,
    WordPressDeploymentReconciliationVerifyRequest,
    WordPressDeploymentManualComplete,
    WordPressDeploymentManualCompleteRequest,
    WordPressDeploymentVerification,
    WordPressDeploymentVerifyRequest,
    WordPressDraftGateResult,
)
from app.services.wordpress_metadata import _hash, _parse_html, _sign_context, _verify
from app.services.wordpress_heading_contract import (
    EXPECTED_FEATURED_MEDIA,
    EXPECTED_SLUG,
    EXPECTED_TITLE,
    EXPECTED_URL,
    wordpress_body_hash,
)
from app.services.wordpress_sandbox import get_wordpress_application_password, read_wordpress_settings
from app.services.wordpress_deployment_release import (
    SOURCE_EXPECTATIONS,
    DeploymentReleaseError,
    artifact_sha256,
    readiness_diagnostics,
    release_paths,
    resolve_program_root,
    verify_runtime_release_identity,
)
from app.services.wordpress_rendered_state import EXPECTED_H1, EXPECTED_MEDIA_ALT, EXPECTED_MEDIA_URL, acquire_rendered_state, validate_manual_browser_evidence

PLUGIN_VERSION = SOURCE_EXPECTATIONS.plugin_version
PLUGIN_SLUG = SOURCE_EXPECTATIONS.plugin_slug
PLUGIN_FILE = SOURCE_EXPECTATIONS.plugin_entry_path
ZIP_NAME = SOURCE_EXPECTATIONS.plugin_zip_filename
ZIP_SHA256 = SOURCE_EXPECTATIONS.plugin_zip_sha256
SOURCE_SHA256 = SOURCE_EXPECTATIONS.plugin_source_sha256
INSTALL_PHRASE = "INSTALL PROJECT ATLAS METADATA BRIDGE"
RECONCILIATION_PHRASE = "RECONCILE INSTALLED INACTIVE METADATA BRIDGE"
RECONCILIATION_TTL = timedelta(minutes=10)
EXPECTED_CORRECTED_BODY_HASH = "c031a7aa841b8e9a0316956dd3bf25178f390e64d01ceb9d9cd4273cc4aed195"
BACKUP_WINDOW = timedelta(hours=4)
ALLOWED_TRANSITIONS = {
    "installation_authorized": {"awaiting_manual_installation", "failed"},
    "awaiting_manual_installation": {"manual_installation_reported", "failed"},
    "manual_installation_reported": {"verification_pending", "failed"},
    "verification_pending": {"verified", "verification_failed", "reconciliation_required", "failed"},
    "reconciliation_required": {"failed"},
}


@dataclass(frozen=True)
class _ReconciliationHandleEntry:
    request: WordPressDeploymentReconciliationVerifyRequest
    binding_hash: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class _PluginIdentifier:
    """Fail-closed interpretation of one raw WordPress plugin identifier."""

    raw_identifier: Any
    posix_identifier: str | None
    plugin_directory: str | None
    plugin_slug: str | None
    entry_filename: str | None
    authorized_entry_path: str | None
    extensionless_rest_identifier: bool
    valid: bool
    error: str | None = None


def _normalize_plugin_identifier(raw_identifier: Any) -> _PluginIdentifier:
    """Normalize only for identity matching; never mutate raw hash inputs.

    WordPress core REST removes the final ``.php`` from its ``plugin`` field.
    Only the locked extensionless bridge identifier may regain that suffix.
    """

    def invalid(error: str) -> _PluginIdentifier:
        return _PluginIdentifier(raw_identifier, None, None, None, None, None, False, False, error)

    if not isinstance(raw_identifier, str) or not raw_identifier or raw_identifier != raw_identifier.strip():
        return invalid("identifier must be a nonempty unpadded string")
    if "\x00" in raw_identifier:
        return invalid("identifier contains a null byte")
    if raw_identifier.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw_identifier):
        return invalid("identifier is absolute")

    posix_identifier = raw_identifier.replace("\\", "/")
    if posix_identifier.startswith("/") or posix_identifier.endswith("/"):
        return invalid("identifier has a leading or trailing slash")
    segments = posix_identifier.split("/")
    if any(not segment for segment in segments):
        return invalid("identifier contains an empty segment")
    if any(segment in {".", ".."} for segment in segments):
        return invalid("identifier contains traversal")
    if any(re.fullmatch(r"[A-Za-z0-9._-]+", segment) is None for segment in segments):
        return invalid("identifier contains malformed characters")

    directory = segments[0] if len(segments) > 1 else None
    filename = segments[-1]
    expected_path = PurePosixPath(PLUGIN_FILE).as_posix()
    expected_extensionless = expected_path.removesuffix(".php")
    authorized_path = None
    extensionless = False
    if posix_identifier == expected_path:
        authorized_path = expected_path
    elif posix_identifier == expected_extensionless:
        authorized_path = expected_path
        extensionless = True

    return _PluginIdentifier(
        raw_identifier=raw_identifier,
        posix_identifier=posix_identifier,
        plugin_directory=directory,
        plugin_slug=directory if directory == PLUGIN_SLUG else None,
        entry_filename=filename,
        authorized_entry_path=authorized_path,
        extensionless_rest_identifier=extensionless,
        valid=True,
    )


def _matching_reconciliation_plugins(plugins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in plugins
        if _normalize_plugin_identifier(item.get("plugin")).authorized_entry_path == PLUGIN_FILE
    ]


_reconciliation_handle_lock = Lock()
_reconciliation_handles: dict[str, _ReconciliationHandleEntry] = {}
_reconciliation_handle_timers: dict[str, Timer] = {}


def deployment_readiness() -> dict[str, Any]:
    try:
        program = readiness_diagnostics()
        root = resolve_program_root()
    except DeploymentReleaseError as exc:
        raise HTTPException(503, str(exc)) from exc
    try:
        release = verify_runtime_release_identity(root).identity()
        release_status = "verified"
        release_error = None
    except DeploymentReleaseError as exc:
        release = None
        release_status = "release_identity_unavailable"
        release_error = str(exc)
    return {"release": release, "release_status": release_status, "release_error": release_error, "source_expectations": SOURCE_EXPECTATIONS.identity(), "program": program, "read_only": True}


def inspect_installation_preflight(session: Session, page_id: int, proof: WordPressDeploymentBackupEvidence) -> WordPressDeploymentPreflight:
    _target(page_id)
    artifact, artifact_gates = _verify_artifact()
    release_verified = any(gate.code == "release_identity" and gate.passed for gate in artifact_gates)
    observed = _observe(session, proof) if release_verified else {
        "_error": "release_identity_unavailable",
        "plugins": [],
        "rendered": {"source": "none", "outcome": "unavailable", "verified": False},
        "read_only": True,
        "wordpress_request_performed": False,
    }
    gates = [*artifact_gates, *_backup_gates(proof), *_state_gates(session, observed)]
    ready = all(gate.passed for gate in gates)
    age = _backup_age(proof.wordpress_backup_completed_at)
    deadline = _backup_deadline(proof.wordpress_backup_completed_at) if proof.wordpress_backup_completed_at.tzinfo else None
    return WordPressDeploymentPreflight(
        status="preflight_ready" if ready else "preflight_blocked",
        preflight_ready=ready,
        artifact=artifact,
        inspected_state=observed,
        backup_age_seconds=int(age.total_seconds()) if age is not None else None,
        backup_deadline=deadline,
        gate_results=gates,
        php_error_findings={
            "source": "operator_supplied_read_only_evidence",
            "status": "no_errors_reported" if _clean_findings(proof.php_error_log_findings) else "findings_reported",
            "details_returned": False,
        },
    )


def install_dry_run(session: Session, page_id: int, proof: WordPressDeploymentBackupEvidence) -> WordPressDeploymentInstallDryRun:
    inspection = inspect_installation_preflight(session, page_id, proof)
    context = _bound_context(inspection.inspected_state, proof, inspection.artifact)
    ready = inspection.preflight_ready
    token = phrase = expires_at = None
    if ready:
        deadline = inspection.backup_deadline
        if deadline is None:
            raise HTTPException(422, "Backup timestamp must be timezone-aware.")
        expires = min(datetime.now(UTC) + timedelta(minutes=15), deadline)
        token = _sign_context("authorize_manual_plugin_install", context, expires)
        phrase = INSTALL_PHRASE
        expires_at = expires.isoformat()
    return WordPressDeploymentInstallDryRun(
        status="preflight_ready" if ready else "preflight_not_started",
        ready=ready,
        artifact=inspection.artifact,
        inspected_state=inspection.inspected_state,
        backup_age_seconds=inspection.backup_age_seconds,
        gate_results=inspection.gate_results,
        confirmation_token=token,
        confirmation_phrase=phrase,
        expires_at=expires_at,
    )


def authorize_manual_install(session: Session, page_id: int, request: WordPressDeploymentAuthorizeRequest) -> WordPressDeploymentAuthorization:
    _target(page_id)
    token = _verify(request.confirmation_token, "authorize_manual_plugin_install", page_id)
    if not hmac.compare_digest(request.confirmation_phrase, INSTALL_PHRASE):
        raise HTTPException(422, "The installation phrase is incorrect.")
    if request.shawn_approved_at.tzinfo is None:
        raise HTTPException(422, "Shawn approval timestamp must be timezone-aware.")
    evidence_path = _safe_evidence_path(request.evidence_directory)
    dry = install_dry_run(session, page_id, request)
    current_context = _bound_context(dry.inspected_state, request, dry.artifact)
    if not dry.ready or token["bound_state_hash"] != _hash(current_context):
        raise HTTPException(409, "Installation authorization state changed. Run a new preflight.")
    jti = str(token.get("nonce", ""))
    if not re.fullmatch(r"[0-9a-f]{32}", jti):
        raise HTTPException(422, "The authorization token has no valid nonce.")
    deployment_key = _deployment_key(request, dry.artifact)
    nonce = WordPressDeploymentNonce(
        jti=jti,
        token_fingerprint=hashlib.sha256(request.confirmation_token.encode()).hexdigest(),
        action_type="install_metadata_bridge",
    )
    audit = WordPressDeploymentAudit(
        generated_page_id=41,
        wordpress_post_id=8,
        action_type="install_metadata_bridge",
        status="installation_authorized",
        operator=request.operator,
        shawn_approved_at=request.shawn_approved_at.astimezone(UTC),
        confirmation_phrase_hash=hashlib.sha256(INSTALL_PHRASE.encode()).hexdigest(),
        atlas_version=str(dry.artifact["atlas_version"]),
        atlas_commit=str(dry.artifact["atlas_commit"]),
        atlas_tag=str(dry.artifact["atlas_tag"]),
        plugin_version=PLUGIN_VERSION,
        plugin_slug=PLUGIN_SLUG,
        plugin_path=PLUGIN_FILE,
        zip_file_name=ZIP_NAME,
        zip_sha256=ZIP_SHA256,
        plugin_source_sha256=SOURCE_SHA256,
        backup_reference=request.wordpress_backup_reference,
        backup_completed_at=request.wordpress_backup_completed_at.astimezone(UTC),
        backup_deadline=_backup_deadline(request.wordpress_backup_completed_at),
        authorization_jti=jti,
        deployment_key=deployment_key,
        backup_evidence=_backup_dict(request),
        pre_snapshot=dry.inspected_state,
        evidence_summary={
            "authorization_wordpress_request_performed": False,
            "upload_performed_by_atlas": False,
            "token_stored": False,
            "release_manifest_sha256": dry.artifact.get("release_manifest_sha256"),
            "release_verification_source": dry.artifact.get("release_verification_source"),
            "release_source_compatibility_id": dry.artifact.get("release_source_compatibility_id"),
            "release_manifest_integrity_verified": dry.artifact.get("release_manifest_integrity_verified"),
            "release_expected_identity_matched": dry.artifact.get("release_expected_identity_matched"),
            "release_git_metadata_available": dry.artifact.get("release_git_metadata_available"),
            "release_runtime_identity_verified": dry.artifact.get("release_runtime_identity_verified"),
        },
        evidence_directory=evidence_path,
    )
    try:
        session.add(nonce)
        session.add(audit)
        session.flush()
        nonce.audit_id = audit.id
        session.add(nonce)
        _record_initial_transition(session, audit, request.operator, "Shawn authorized manual installation", f"{jti}:authorized")
        _transition(session, audit, "awaiting_manual_installation", request.operator, "Authorization recorded; awaiting Shawn's manual upload", f"{jti}:awaiting")
        session.commit()
        session.refresh(audit)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "Authorization token was already consumed or this deployment was already authorized.") from exc
    return WordPressDeploymentAuthorization(
        audit_id=audit.id or 0,
        status="awaiting_manual_installation",
        zip_file_name=ZIP_NAME,
        zip_sha256=ZIP_SHA256,
        instructions=[
            "Open WordPress Admin using your normal administrator browser session.",
            "Go to Plugins -> Add Plugin -> Upload Plugin.",
            f"Select the local file {ZIP_NAME}.",
            f"Confirm SHA-256 {ZIP_SHA256}.",
            "Click Install Now.",
            "DO NOT CLICK ACTIVATE PLUGIN.",
            "Return to Atlas and report the manual upload complete.",
        ],
        state_history=_history(session, audit.id or 0),
    )


def report_manual_complete(session: Session, page_id: int, request: WordPressDeploymentManualCompleteRequest) -> WordPressDeploymentManualComplete:
    _target(page_id)
    audit = _audit(session, request.audit_id)
    if not request.manual_upload_completed_attestation:
        raise HTTPException(422, "Manual upload completion must be attested.")
    if audit.status != "awaiting_manual_installation":
        raise HTTPException(409, "Audit is not awaiting manual installation.")
    observed = _observe(session, WordPressDeploymentBackupEvidence.model_validate(audit.backup_evidence))
    gates = [*_stored_backup_gates(audit), *_expected_install_delta_gates(audit.pre_snapshot, observed)]
    if not all(gate.passed for gate in gates):
        _fail_audit(session, audit, request.operator, "manual_acknowledgment_invalid", gates)
        raise HTTPException(409, "Manual installation acknowledgment failed the backup or WordPress state boundary.")
    request_id = secrets.token_hex(16)
    _transition(session, audit, "manual_installation_reported", request.operator, "Shawn reported the manual upload complete; success not assumed", f"{request_id}:reported")
    _transition(session, audit, "verification_pending", request.operator, "Read-only verification is now required", f"{request_id}:pending")
    audit.evidence_summary = {
        **audit.evidence_summary,
        "manual_completion_reported_by": request.operator,
        "success_assumed": False,
        "acknowledgment_snapshot": observed,
    }
    session.add(audit)
    session.commit()
    return WordPressDeploymentManualComplete(
        audit_id=audit.id or 0,
        status="verification_pending",
        state_history=_history(session, audit.id or 0),
    )


def verify_manual_install(session: Session, page_id: int, request: WordPressDeploymentVerifyRequest) -> WordPressDeploymentVerification:
    _target(page_id)
    audit = _audit(session, request.audit_id)
    if audit.status != "verification_pending":
        raise HTTPException(409, "Audit is not pending verification.")
    observed = _observe(session, WordPressDeploymentBackupEvidence.model_validate(audit.backup_evidence))
    gates = [
        *_stored_backup_gates(audit),
        *_expected_install_delta_gates(audit.pre_snapshot, observed),
        _gate("php_logs", "PHP/error-log evidence is clean", _clean_findings(request.php_error_log_findings), "PHP/error-log findings contain a warning, notice, fatal, REST registration, or header error."),
    ]
    verified = all(gate.passed for gate in gates)
    request_id = secrets.token_hex(16)
    _transition(
        session,
        audit,
        "verified" if verified else "verification_failed",
        request.operator,
        "Exact inactive plugin and bound state verified" if verified else "Post-installation verification gates failed",
        f"{request_id}:verify",
    )
    audit.post_snapshot = observed
    audit.completed_at = datetime.now(UTC)
    audit.evidence_summary = {
        **audit.evidence_summary,
        "verification_operator": request.operator,
        "php_error_log_findings": request.php_error_log_findings,
        "wordpress_mutation_request_performed": False,
        "independent_observations": {
            "plugin_inventory": True,
            "active_plugin_inventory": True,
            "page_rest_hash": True,
            "rendered_hashes": True,
            "media_snapshots": True,
            "cache_headers": True,
        },
        "inferred_not_directly_queryable_while_plugin_inactive": [
            "activation safety option absence",
            "private Atlas post-meta absence",
            "database writes beyond observable REST state",
        ],
    }
    if not verified:
        audit.error_code = "verification_gates_failed"
        audit.error_message = "Post-installation verification failed."
    session.add(audit)
    session.commit()
    return WordPressDeploymentVerification(
        audit_id=audit.id or 0,
        status=audit.status,
        verified=verified,
        gate_results=gates,
        inspected_state=observed,
        state_history=_history(session, audit.id or 0),
        inspection_limitations=[
            "The inactive plugin exposes no endpoint for direct option or private post-meta inspection; absence is corroborated by unchanged REST/render hashes, unchanged active inventory, and inactive status.",
            "Database writes are bounded by observable WordPress snapshots; direct database access is not used.",
        ],
    )


def verify_install_reconciliation(
    session: Session,
    page_id: int,
    request: WordPressDeploymentReconciliationVerifyRequest,
    *,
    issue_handle: bool = True,
) -> WordPressDeploymentReconciliationVerification:
    """Inspect an already-installed inactive bridge without mutating WordPress or Atlas."""
    _target(page_id)
    audit = _audit(session, request.audit_id)
    proof_values = dict(audit.backup_evidence)
    proof_values["manual_browser_evidence"] = request.manual_browser_evidence.model_dump(mode="json", exclude_none=True)
    try:
        proof = WordPressDeploymentBackupEvidence.model_validate(proof_values)
    except Exception as exc:
        raise HTTPException(409, "Stored deployment backup evidence is invalid.") from exc
    evidence_valid, evidence_reason = validate_manual_browser_evidence(
        request.manual_browser_evidence,
        os.getenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", ""),
    )
    evidence_contract_valid = evidence_valid and request.manual_browser_evidence.evidence_schema_version == 1
    if evidence_valid and not evidence_contract_valid:
        evidence_reason = "Installed-inactive reconciliation requires fresh schema-v1 evidence."
    artifact, artifact_gates = _verify_artifact()
    observed = _observe(session, proof) if evidence_contract_valid and any(g.code == "release_identity" and g.passed for g in artifact_gates) else {
        "_error": "manual_browser_evidence_invalid" if not evidence_contract_valid else "release_identity_unavailable",
        "manual_evidence_reason": evidence_reason if not evidence_contract_valid else None,
        "plugins": [],
        "rendered": {"verified": False, "outcome": "release_identity_unavailable"},
        "wordpress_request_methods": [],
        "wordpress_request_performed": False,
        "read_only": True,
    }
    nonce = session.exec(select(WordPressDeploymentNonce).where(WordPressDeploymentNonce.audit_id == audit.id)).one_or_none()
    transitions = _transition_records(session, audit.id or 0)
    metadata_states = session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == 41)).all()
    metadata_audits = session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id == 41)).all()
    gates = [
        *artifact_gates,
        *_reconciliation_gates(
            audit,
            nonce,
            transitions,
            observed,
            artifact,
            request,
            metadata_state_count=len(metadata_states),
            metadata_audit_count=len(metadata_audits),
            evidence_valid=evidence_contract_valid,
            evidence_reason=evidence_reason,
        ),
    ]
    ready = all(gate.passed for gate in gates)
    binding = _reconciliation_binding(audit, nonce, transitions, observed, artifact, request)
    binding_hash = _hash(binding)
    handle = None
    expires_at = None
    if ready and issue_handle:
        evidence_expiry = _evidence_expiry(request.manual_browser_evidence.expires_at)
        expires_at = min(datetime.now(UTC) + RECONCILIATION_TTL, evidence_expiry)
        if expires_at <= datetime.now(UTC):
            ready = False
            gates.append(_gate("handle_lifetime", "Fresh evidence permits a positive handle lifetime", False, "Evidence expires before a reconciliation handle can be issued."))
        else:
            handle = _store_reconciliation_handle(request, binding_hash, expires_at)
    return WordPressDeploymentReconciliationVerification(
        audit_id=audit.id or 0,
        status="reconciliation_ready" if ready else "reconciliation_blocked",
        reconciliation_ready=ready,
        reconciliation_handle=handle,
        confirmation_phrase=RECONCILIATION_PHRASE if ready else None,
        binding_hash=binding_hash if ready else None,
        expires_at=expires_at,
        gate_results=gates,
        inspected_state=_reconciliation_public_snapshot(observed, audit, nonce, transitions, len(metadata_states), len(metadata_audits)),
        proposed_atlas_changes=[
            "Update deployment audit status from awaiting_manual_installation to verified.",
            "Record installed_inactive_reconciliation evidence on the existing deployment audit.",
            "Append one reconciliation-specific deployment transition while preserving prior transitions and the original nonce.",
        ] if ready else [],
    )


def apply_install_reconciliation(
    session: Session,
    page_id: int,
    request: WordPressDeploymentReconciliationApplyRequest,
) -> WordPressDeploymentReconciliationResult:
    """Finalize the existing Atlas audit only; this function has no WordPress write transport."""
    _target(page_id)
    if not hmac.compare_digest(request.confirmation_phrase, RECONCILIATION_PHRASE):
        raise HTTPException(422, "The installed-inactive reconciliation phrase is incorrect.")
    entry = _consume_reconciliation_handle(request.reconciliation_handle)
    verification = verify_install_reconciliation(session, page_id, entry.request, issue_handle=False)
    if not verification.reconciliation_ready or verification.binding_hash != entry.binding_hash:
        raise HTTPException(409, "Installed-inactive reconciliation state changed. Run a new verification.")
    audit = _audit(session, entry.request.audit_id)
    nonce = session.exec(select(WordPressDeploymentNonce).where(WordPressDeploymentNonce.audit_id == audit.id)).one_or_none()
    transitions_before = _transition_records(session, audit.id or 0)
    evidence = entry.request.manual_browser_evidence
    request_identifier = f"reconcile:{hashlib.sha256(request.reconciliation_handle.encode()).hexdigest()[:54]}"
    previous_status = audit.status
    if audit.status != "awaiting_manual_installation":
        raise HTTPException(409, "Deployment audit status changed before reconciliation finalization.")
    audit.status = "verified"
    session.add(WordPressDeploymentTransition(
        audit_id=audit.id or 0,
        previous_state=previous_status,
        new_state="verified",
        actor=audit.operator,
        reason="Installed inactive plugin verified and deployment audit finalized by Atlas-only reconciliation",
        request_identifier=request_identifier,
    ))
    audit.post_snapshot = verification.inspected_state
    audit.completed_at = datetime.now(UTC)
    audit.error_code = None
    audit.error_message = None
    audit.evidence_summary = {
        **audit.evidence_summary,
        "completion_mode": "installed_inactive_reconciliation",
        "reconciliation": {
            "previous_status": previous_status,
            "final_status": "verified",
            "binding_hash": entry.binding_hash,
            "handle_fingerprint": hashlib.sha256(request.reconciliation_handle.encode()).hexdigest(),
            "fresh_evidence_id": evidence.evidence_id,
            "fresh_evidence_schema": evidence.evidence_schema,
            "fresh_evidence_schema_version": evidence.evidence_schema_version,
            "fresh_evidence_rendered_head_hash": evidence.rendered_head_hash,
            "fresh_evidence_visible_content_hash": evidence.visible_content_hash,
            "fresh_evidence_expires_at": _json_datetime(evidence.expires_at),
            "original_authorization_jti": nonce.jti if nonce else None,
            "original_transition_history_hash": _transition_history_hash(transitions_before),
            "wordpress_write_count": 0,
            "atlas_write_scope": ["existing_deployment_audit", "one_deployment_transition"],
            "accidental_activation_and_guarded_deactivation_not_rewritten": True,
        },
    }
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return WordPressDeploymentReconciliationResult(
        audit_id=audit.id or 0,
        status="verified",
        binding_hash=entry.binding_hash,
        state_history=_history(session, audit.id or 0),
    )


def reconcile_install_audit(session: Session, page_id: int, request: WordPressDeploymentVerifyRequest) -> WordPressDeploymentVerification:
    """Legacy normal-flow placeholder retained to prevent bypass of the dedicated workflow."""
    _target(page_id)
    audit = _audit(session, request.audit_id)
    raise HTTPException(409, f"Audit {audit.id} requires the dedicated fresh-evidence reconciliation endpoints; no WordPress request was performed.")


def _observe(session: Session, proof: WordPressDeploymentBackupEvidence | None = None) -> dict[str, Any]:
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password):
        return {"_error": "credentials_unavailable", "plugins": [], "read_only": True, "wordpress_request_performed": False, "wordpress_request_methods": []}
    root = _request(settings.site_url, settings.username, password, "GET", "/wp-json/")
    plugins = _request(settings.site_url, settings.username, password, "GET", "/wp-json/wp/v2/plugins?context=edit")
    page = _request(settings.site_url, settings.username, password, "GET", "/wp-json/wp/v2/pages/8?context=edit")
    media31 = _request(settings.site_url, settings.username, password, "GET", "/wp-json/wp/v2/media/31?context=edit")
    media32 = _request(settings.site_url, settings.username, password, "GET", "/wp-json/wp/v2/media/32?context=edit")
    rendered = acquire_rendered_state(
        settings.username,
        password,
        manual_evidence=proof.manual_browser_evidence if proof else None,
        evidence_signing_key=os.getenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", ""),
        verified_bypass_url=os.getenv("WORDPRESS_VERIFIED_CACHE_BYPASS_URL", ""),
        bypass_independently_verified=os.getenv("WORDPRESS_CACHE_BYPASS_VERIFIED", "").lower() == "true",
    )
    plugin_list = plugins if isinstance(plugins, list) else []
    active_plugins = sorted(item.get("plugin") for item in plugin_list if item.get("status") in {"active", "network-active"})
    media32_url = media32.get("source_url", "") if isinstance(media32, dict) else ""
    page_encoded = json.dumps(page, sort_keys=True) if isinstance(page, dict) else ""
    rendered_encoded = json.dumps(rendered, sort_keys=True)
    page_body = _nested_text(page, "content")
    page_title = _nested_text(page, "title")
    page_excerpt = _nested_text(page, "excerpt")
    locked = {
        "site_title": root.get("name") if isinstance(root, dict) else None,
        "tagline": root.get("description") if isinstance(root, dict) else None,
        "page_snapshot_hash": _hash(page),
        "media31_snapshot_hash": _hash(media31),
        "media32_snapshot_hash": _hash(media32),
        "rendered_head_hash": rendered.get("head_hash"),
        "visible_content_hash": rendered.get("visible_hash"),
    }
    return {
        "plugins": plugin_list,
        "active_plugins": active_plugins,
        "plugin_inventory_hash": _hash(plugin_list),
        "active_plugin_inventory_hash": _hash(active_plugins),
        "page": _resource_snapshot(page),
        "page_snapshot_hash": _hash(page),
        "page_body_hash": wordpress_body_hash(page_body) if page_body else None,
        "page_body_begins_expected_h2": page_body.startswith(
            "<h2>Drywood Termite Tenting in Orlando, Florida</h2>"
        ) if page_body else False,
        "page_title": page_title,
        "page_excerpt": page_excerpt,
        "page_canonical": page.get("link") if isinstance(page, dict) else None,
        "media31": _resource_snapshot(media31),
        "media31_snapshot_hash": _hash(media31),
        "media32": _resource_snapshot(media32),
        "media32_snapshot_hash": _hash(media32),
        "site": {"name": root.get("name"), "description": root.get("description")} if isinstance(root, dict) else {},
        "rendered": {**rendered, "media32_reference_present": bool(media32_url and media32_url in rendered_encoded) or bool(rendered.get("media32_reference_present"))},
        "page_references_media32": bool(media32_url and media32_url in page_encoded) or "hero-1.png" in page_encoded,
        "locked_state_hash": _hash(locked),
        "cache_headers": rendered.get("cache_headers", {}),
        "wordpress_request_performed": True,
        "wordpress_request_methods": ["GET"],
        "read_only": True,
    }


def _state_gates(session: Session, observed: dict[str, Any]) -> list[WordPressDraftGateResult]:
    page = session.get(GeneratedPage, 41)
    image = session.get(ImageMetadata, 1)
    wordpress_page = observed.get("page", {})
    media31 = observed.get("media31", {})
    media32 = observed.get("media32", {})
    return [
        _gate("credentials", "Application-password credentials available in backend memory", "_error" not in observed, "Credentials required."),
        _gate("target", "Atlas page 41 maps to WordPress page 8", bool(page and page.wordpress_post_id == 8), "Wrong target mapping."),
        _gate("page", "Page 8 identity remains locked", wordpress_page.get("id") == 8 and wordpress_page.get("status") == "publish" and wordpress_page.get("slug") == "drywood-termite-tenting-orlando-fl" and wordpress_page.get("featured_media") == 31, "Page state changed."),
        _gate("site_identity", "Site Title and Tagline remain locked", observed.get("site", {}).get("name") == "My WordPress" and observed.get("site", {}).get("description") == "", "Site identity changed."),
        _gate("media31", "Media 31 remains exact", media31.get("id") == 31 and bool(image and image.wordpress_media_id == 31), "Media 31 changed."),
        _gate("media32", "Existing media 32 remains unattached, unfeatured, and unreferenced", media32.get("id") == 32 and not media32.get("post") and not observed.get("page_references_media32") and not observed.get("rendered", {}).get("media32_reference_present"), "Media 32 changed or is referenced."),
        _gate("plugin_absent", "Metadata bridge is absent", not any(str(item.get("plugin", "")).startswith(f"{PLUGIN_SLUG}/") for item in observed.get("plugins", [])), "Plugin slug/path conflict exists."),
        _gate("rendered", "Rendered state is explicitly verified with bound head and body hashes", bool(observed.get("rendered", {}).get("verified") and observed.get("rendered", {}).get("head_hash") and observed.get("rendered", {}).get("visible_hash")), f"Rendered state blocked: {observed.get('rendered', {}).get('outcome', 'unavailable')}."),
    ]


def _expected_install_delta_gates(before: dict[str, Any], after: dict[str, Any]) -> list[WordPressDraftGateResult]:
    matches = [item for item in after.get("plugins", []) if item.get("plugin") == PLUGIN_FILE]
    without_bridge = [item for item in after.get("plugins", []) if item.get("plugin") != PLUGIN_FILE]
    media32 = after.get("media32", {})
    return [
        _gate("exact_plugin", "Exactly one Metadata Bridge with the locked path and version is installed", len(matches) == 1 and matches[0].get("version") == PLUGIN_VERSION, "Exact plugin slug/path/version required."),
        _gate("inactive", "Metadata Bridge remains inactive", len(matches) == 1 and matches[0].get("status") == "inactive", "Plugin must remain inactive."),
        _gate("plugin_delta", "The Metadata Bridge is the only plugin inventory change", _canonical_plugins(without_bridge) == _canonical_plugins(before.get("plugins", [])), "An unrelated plugin was installed, removed, or updated."),
        _gate("active_inventory", "Active-plugin inventory is unchanged", after.get("active_plugin_inventory_hash") == before.get("active_plugin_inventory_hash"), "A plugin was activated or deactivated."),
        _gate("locked_state", "Page, site identity, media, rendered head, and visible content are unchanged", after.get("locked_state_hash") == before.get("locked_state_hash"), "A locked WordPress state changed."),
        _gate("cache_headers", "Cache-header observations are unchanged", after.get("cache_headers") == before.get("cache_headers"), "Cache headers changed; hard stop without purge."),
        _gate("no_render", "No Atlas metadata renders", not after.get("rendered", {}).get("atlas_metadata_marker_present", False), "Atlas metadata unexpectedly rendered."),
        _gate("media32_exists", "Known media 32 still exists", media32.get("id") == 32, "Media 32 disappeared."),
        _gate("media32_unchanged", "Media 32 snapshot is unchanged", after.get("media32_snapshot_hash") == before.get("media32_snapshot_hash"), "Media 32 changed."),
        _gate("media32_unattached", "Media 32 remains unattached and unfeatured", not media32.get("post") and after.get("page", {}).get("featured_media") != 32, "Media 32 became attached or featured."),
        _gate("media32_unreferenced", "Media 32 is absent from page content, rendered HTML, and plugin metadata", not after.get("page_references_media32") and not after.get("rendered", {}).get("media32_reference_present"), "Media 32 is referenced."),
        _gate("safety_state_inferred", "No activation transition occurred", not before.get("plugins") or not any(item.get("plugin") == PLUGIN_FILE for item in before.get("plugins", [])) and after.get("active_plugin_inventory_hash") == before.get("active_plugin_inventory_hash") and len(matches) == 1 and matches[0].get("status") == "inactive", "Activation safety state cannot be corroborated."),
        _gate("post_meta_inferred", "No Atlas post-meta change is observable", after.get("page_snapshot_hash") == before.get("page_snapshot_hash") and not after.get("rendered", {}).get("atlas_metadata_marker_present", False), "Atlas post metadata may have changed."),
        _gate("writes_bounded", "Observed changes are limited to the exact inactive plugin", _canonical_plugins(without_bridge) == _canonical_plugins(before.get("plugins", [])) and after.get("locked_state_hash") == before.get("locked_state_hash"), "Unexpected observable WordPress writes occurred."),
    ]


def _reconciliation_gates(
    audit: WordPressDeploymentAudit,
    nonce: WordPressDeploymentNonce | None,
    transitions: list[WordPressDeploymentTransition],
    observed: dict[str, Any],
    artifact: dict[str, Any],
    request: WordPressDeploymentReconciliationVerifyRequest,
    *,
    metadata_state_count: int,
    metadata_audit_count: int,
    evidence_valid: bool,
    evidence_reason: str,
) -> list[WordPressDraftGateResult]:
    matches = _matching_reconciliation_plugins(observed.get("plugins", []))
    rendered = observed.get("rendered", {})
    page = observed.get("page", {})
    media31 = observed.get("media31", {})
    media32 = observed.get("media32", {})
    expected_runtime = request.expected_runtime_identity.model_dump(mode="json")
    actual_runtime = {
        "atlas_version": artifact.get("atlas_version"),
        "atlas_commit": artifact.get("atlas_commit"),
        "atlas_tag": artifact.get("atlas_tag"),
        "manifest_sha256": artifact.get("release_manifest_sha256"),
        "source_compatibility_id": artifact.get("release_source_compatibility_id"),
    }
    expected_history = ["installation_authorized", "awaiting_manual_installation"]
    observable_safety_state = (
        len(matches) == 1
        and matches[0].get("status") == "inactive"
        and metadata_state_count == 0
        and metadata_audit_count == 0
        and rendered.get("verified") is True
        and not rendered.get("atlas_metadata_marker_present", False)
        and _rendered_metadata_absent(rendered)
        and observed.get("page_snapshot_hash") == request.expected_page_snapshot_hash
        and observed.get("page_body_hash") == request.expected_body_hash
        and observed.get("media31_snapshot_hash") == request.expected_media31_snapshot_hash
        and observed.get("media32_snapshot_hash") == request.expected_media32_snapshot_hash
        and observed.get("page_references_media32") is False
        and observed.get("cache_headers") == rendered.get("cache_headers", {}) == audit.pre_snapshot.get("cache_headers", {})
    )
    return [
        _gate("evidence_contract", "Fresh signed canonical schema-v1 browser evidence is valid", evidence_valid and request.manual_browser_evidence.evidence_schema_version == 1, evidence_reason or "Schema-v1 browser evidence is required."),
        _gate("audit_target", "Existing deployment audit is bound to Atlas page 41 and WordPress page 8", audit.generated_page_id == 41 and audit.wordpress_post_id == 8, "Deployment audit target changed."),
        _gate("audit_status", "Audit is awaiting manual installation reconciliation", audit.status == "awaiting_manual_installation", "Audit status is not awaiting_manual_installation."),
        _gate("original_nonce", "Original installation authorization nonce remains consumed and bound", bool(nonce and nonce.jti == audit.authorization_jti and nonce.audit_id == audit.id and nonce.consumed_at), "Original consumed authorization nonce is missing or changed."),
        _gate("transition_history", "Original authorization transitions remain intact", [item.new_state for item in transitions] == expected_history, "Original deployment transition history changed."),
        _gate("authorized_identity", "Authorized plugin identity and artifact remain exact", audit.plugin_slug == request.expected_plugin_slug == PLUGIN_SLUG and audit.plugin_path == request.expected_plugin_path == PLUGIN_FILE and audit.plugin_version == request.expected_plugin_version == PLUGIN_VERSION and audit.zip_sha256 == request.expected_zip_sha256 == ZIP_SHA256, "Authorized plugin identity or ZIP checksum differs."),
        _gate("artifact_source", "Authorized ZIP remains portable, byte-equal to source, and bound to installed identity", artifact.get("zip_sha256") == request.expected_zip_sha256 and artifact.get("plugin_source_sha256") == audit.plugin_source_sha256 and artifact.get("plugin_path") == request.expected_plugin_path, "Authorized source artifact changed."),
        _gate("runtime_identity", "Independent expected runtime identity remains verified and exact", actual_runtime == expected_runtime and artifact.get("release_runtime_identity_verified") is True and artifact.get("release_manifest_integrity_verified") is True and artifact.get("release_expected_identity_matched") is True, "Runtime release identity or repository artifact safety changed."),
        _gate("credentials", "Authenticated WordPress read credentials are available in backend memory", "_error" not in observed and observed.get("wordpress_request_performed") is True, "Authenticated WordPress reads are unavailable."),
        _gate("read_only_transport", "Every WordPress request is GET-only", observed.get("wordpress_request_methods") == ["GET"] and observed.get("read_only") is True, "A non-read-only WordPress request was observed."),
        _gate("plugin_singleton", "Metadata Bridge is installed exactly once at the authorized path", len(matches) == 1, "Plugin is absent, duplicated, or installed under another entry path."),
        _gate("plugin_inactive", "Installed Metadata Bridge remains inactive", len(matches) == 1 and matches[0].get("status") == "inactive", "Plugin is active or its state is unavailable."),
        _gate("plugin_version", "Installed Metadata Bridge version remains exact", len(matches) == 1 and matches[0].get("version") == request.expected_plugin_version, "Installed plugin version changed."),
        _gate("plugin_inventory", "Complete inactive plugin inventory hash remains exact", observed.get("plugin_inventory_hash") == request.expected_plugin_inventory_hash, "Complete plugin inventory changed."),
        _gate("active_inventory", "Active-plugin inventory remains at the pre-install baseline", observed.get("active_plugin_inventory_hash") == request.expected_active_plugin_inventory_hash == audit.pre_snapshot.get("active_plugin_inventory_hash"), "Active-plugin inventory changed."),
        _gate("inactive_safety_corroboration", "Inactive safety is corroborated without claiming a direct private-option read", observable_safety_state, "Inactive safety requires the core inactive inventory, zero Atlas metadata rows, exact page/body/media snapshots, rendered metadata absence, and an unchanged cache observation."),
        _gate("metadata_rows", "Atlas metadata audit and state rows remain absent", metadata_audit_count == 0 and metadata_state_count == 0, "Atlas metadata state or audit rows exist."),
        _gate("page_identity", "Page 8 title, slug, URL, status, excerpt, canonical, and featured media remain locked", page.get("id") == 8 and page.get("status") == "publish" and page.get("slug") == EXPECTED_SLUG and page.get("link") == EXPECTED_URL and page.get("featured_media") == EXPECTED_FEATURED_MEDIA and observed.get("page_title") == EXPECTED_TITLE and rendered.get("canonical") == [EXPECTED_URL], "Page identity changed."),
        _gate("page_snapshot", "Complete page snapshot remains exact", observed.get("page_snapshot_hash") == request.expected_page_snapshot_hash, "Page snapshot changed."),
        _gate("body_hash", "Corrected canonical body hash remains exact", observed.get("page_body_hash") == request.expected_body_hash == EXPECTED_CORRECTED_BODY_HASH, "Page body changed."),
        _gate("rendered_evidence", "Fresh signed schema-v1 evidence verifies the corrected public page", rendered.get("verified") is True and rendered.get("signature_validated") is True and rendered.get("evidence_schema_version") == 1 and rendered.get("browser_evidence_identifier") == request.manual_browser_evidence.evidence_id, "Fresh signed schema-v1 rendered evidence is required."),
        _gate("rendered_h1", "Exactly one visible Orlando H1 remains", rendered.get("h1") == [EXPECTED_H1], "Rendered H1 inventory changed."),
        _gate("rendered_image", "Featured image URL and alt text remain exact", rendered.get("featured_image_url") == EXPECTED_MEDIA_URL and rendered.get("featured_image_alt") == EXPECTED_MEDIA_ALT, "Rendered featured image changed."),
        _gate("metadata_absent", "No Atlas, description, Open Graph, Twitter, or JSON-LD metadata renders", not rendered.get("atlas_metadata_marker_present", False) and _rendered_metadata_absent(rendered), "Unexpected metadata is rendered."),
        _gate("media31", "Media 31 remains exact and visible", media31.get("id") == 31 and observed.get("media31_snapshot_hash") == request.expected_media31_snapshot_hash and rendered.get("featured_image_url") == EXPECTED_MEDIA_URL, "Media 31 changed or is not visible."),
        _gate("media32", "Media 32 remains exact, unattached, unfeatured, and absent", media32.get("id") == 32 and not media32.get("post") and observed.get("media32_snapshot_hash") == request.expected_media32_snapshot_hash and page.get("featured_media") != 32 and not observed.get("page_references_media32") and not rendered.get("media32_reference_present", False), "Media 32 changed or is referenced."),
        _gate("site_identity", "Site Title and Tagline remain exact", observed.get("site") == {"name": "My WordPress", "description": ""}, "Site Title or Tagline changed."),
        _gate("cache_boundary", "Reconciliation has no cache-purge transport and the cache observation remains unchanged", observed.get("cache_headers") == rendered.get("cache_headers", {}) == audit.pre_snapshot.get("cache_headers", {}), "Cache observation changed; reconciliation stops without purging."),
        _gate("zero_wordpress_writes", "Reconciliation verification requires zero WordPress writes", observed.get("wordpress_request_methods") == ["GET"], "WordPress write count is not zero."),
        _gate("atlas_only_finalization", "Proposed finalization is limited to the existing audit and one transition", True, "Atlas-only finalization scope changed."),
    ]


def _reconciliation_binding(
    audit: WordPressDeploymentAudit,
    nonce: WordPressDeploymentNonce | None,
    transitions: list[WordPressDeploymentTransition],
    observed: dict[str, Any],
    artifact: dict[str, Any],
    request: WordPressDeploymentReconciliationVerifyRequest,
) -> dict[str, Any]:
    evidence = request.manual_browser_evidence
    return {
        "action": "reconcile_installed_inactive_metadata_bridge",
        "audit_id": audit.id,
        "atlas_page_id": audit.generated_page_id,
        "wordpress_page_id": audit.wordpress_post_id,
        "runtime_identity": request.expected_runtime_identity.model_dump(mode="json"),
        "audit_revision": _audit_revision(audit),
        "audit_status": audit.status,
        "authorization_nonce": {"id": nonce.id if nonce else None, "jti": nonce.jti if nonce else None, "consumed_at": _json_datetime(nonce.consumed_at) if nonce else None},
        "transition_history_hash": _transition_history_hash(transitions),
        "plugin": {"slug": request.expected_plugin_slug, "path": request.expected_plugin_path, "version": request.expected_plugin_version, "zip_sha256": request.expected_zip_sha256, "source_sha256": artifact.get("plugin_source_sha256")},
        "inventories": {"plugins": observed.get("plugin_inventory_hash"), "active": observed.get("active_plugin_inventory_hash")},
        "snapshots": {"page": observed.get("page_snapshot_hash"), "body": observed.get("page_body_hash"), "media31": observed.get("media31_snapshot_hash"), "media32": observed.get("media32_snapshot_hash"), "cache": _hash(observed.get("cache_headers", {}))},
        "evidence": {"id": evidence.evidence_id, "schema": evidence.evidence_schema, "version": evidence.evidence_schema_version, "signature": evidence.helper_signature, "head_hash": evidence.rendered_head_hash, "visible_hash": evidence.visible_content_hash, "expires_at": _json_datetime(evidence.expires_at)},
        "reconciliation_generation": 1 + sum(1 for item in transitions if "reconciliation" in item.reason.lower()),
    }


def _verify_artifact() -> tuple[dict[str, Any], list[WordPressDraftGateResult]]:
    try:
        root = resolve_program_root()
        zip_path, source_dir = release_paths(root)
        diagnostics = readiness_diagnostics()
        sha = artifact_sha256(zip_path)
        resolution_error = None
    except DeploymentReleaseError as exc:
        diagnostics = {"artifact_relative_path": SOURCE_EXPECTATIONS.artifact_relative_path, "artifact_exists": False, "source_directory_exists": False}
        sha = None
        resolution_error = str(exc)
        zip_path = source_dir = Path("__invalid_atlas_release_path__")
        root = None
    try:
        runtime_release = verify_runtime_release_identity(root) if root else None
        release_error = None if runtime_release else "release_identity_unavailable"
    except DeploymentReleaseError as exc:
        runtime_release = None
        release_error = str(exc)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            expected = {f"{PLUGIN_SLUG}/{path.relative_to(source_dir).as_posix()}": path.read_bytes() for path in source_dir.rglob("*") if path.is_file()}
            actual = {name: archive.read(name) for name in names if not name.endswith("/")}
            valid = len(names) == len(set(names)) and all("\\" not in name and not name.startswith("/") and not re.match(r"^[A-Za-z]:", name) and ".." not in PurePosixPath(name).parts for name in names) and {PurePosixPath(name).parts[0] for name in names} == {PLUGIN_SLUG} and actual == expected and PLUGIN_FILE in names
    except (OSError, zipfile.BadZipFile):
        valid = False
    artifact = {
        "atlas_version": runtime_release.atlas_version if runtime_release else None,
        "atlas_commit": runtime_release.atlas_commit if runtime_release else None,
        "atlas_tag": runtime_release.atlas_tag if runtime_release else None,
        "release_identity_status": "verified" if runtime_release else "release_identity_unavailable",
        "release_verification_source": runtime_release.verification_source if runtime_release else None,
        "release_manifest_sha256": runtime_release.manifest_sha256 if runtime_release else None,
        "release_source_compatibility_id": runtime_release.source_compatibility_id if runtime_release else None,
        "release_manifest_integrity_verified": runtime_release.manifest_integrity_verified if runtime_release else False,
        "release_expected_identity_matched": runtime_release.expected_release_matched if runtime_release else False,
        "release_git_metadata_available": runtime_release.git_metadata_available if runtime_release else False,
        "release_runtime_identity_verified": runtime_release.runtime_identity_verified if runtime_release else False,
        "plugin_slug": PLUGIN_SLUG,
        "plugin_path": PLUGIN_FILE,
        "plugin_version": PLUGIN_VERSION,
        "zip_file_name": ZIP_NAME,
        "zip_sha256": sha,
        "plugin_source_sha256": SOURCE_SHA256,
        "readiness": diagnostics,
    }
    return artifact, [
        _gate("program_root", "Atlas program root is explicitly resolved and validated", resolution_error is None, resolution_error or "Invalid program root."),
        _gate("artifact_hash", "ZIP SHA-256 is locked", sha == ZIP_SHA256, resolution_error or "ZIP checksum mismatch."),
        _gate("artifact_portable", "ZIP is portable and byte-equal to source", valid, "ZIP structure/source mismatch."),
        _gate("release_identity", "External runtime release identity is verified", runtime_release is not None, release_error or "release_identity_unavailable"),
    ]


def _backup_gates(proof: WordPressDeploymentBackupEvidence) -> list[WordPressDraftGateResult]:
    aware = proof.wordpress_backup_completed_at.tzinfo is not None
    age = _backup_age(proof.wordpress_backup_completed_at)
    valid_age = bool(age is not None and timedelta(0) <= age <= BACKUP_WINDOW)
    try:
        load_backup(resolve_backup_download(proof.atlas_data_backup_file))
        data_valid = True
    except (BackupValidationError, OSError, KeyError, TypeError):
        data_valid = False
    return [
        _gate("atlas_data_backup", "Atlas Data Backup validates", data_valid, "Invalid Data Backup."),
        _gate("atlas_media_backup", "Atlas Media Backup identity validates", bool(re.fullmatch(r"atlas-media-backup-\d{4}-\d{2}-\d{2}-\d{6}\.zip", proof.atlas_media_backup_file)), "Invalid Media Backup identity."),
        _gate("atlas_program_backup", "Atlas Program Backup identity validates", bool(re.fullmatch(r"atlas-program-backup-\d{4}-\d{2}-\d{2}-\d{6}\.zip", proof.atlas_program_backup_file)), "Invalid Program Backup identity."),
        _gate("backup_method", "SiteGround on-demand full-site method identified", "siteground" in proof.wordpress_backup_method.lower() and "on-demand" in proof.wordpress_backup_method.lower(), "Exact SiteGround method required."),
        _gate("backup_reference", "Durable WordPress backup reference supplied", len(proof.wordpress_backup_reference.strip()) >= 6, "Durable reference required."),
        _gate("backup_timezone", "Backup timestamp is timezone-aware", aware, "Timezone required."),
        _gate("backup_window", "Backup is not future-dated and no older than four hours", valid_age, "Backup is future-dated or outside four-hour window."),
        _gate("database_attestation", "Database inclusion attested", proof.wordpress_database_included_attestation, "Database attestation required."),
        _gate("plugins_attestation", "wp-content/plugins inclusion attested", proof.wordpress_plugins_included_attestation, "Plugin-files attestation required."),
        _gate("restore_attestation", "Restore capability attested", proof.wordpress_restore_capability_attestation, "Restore attestation required."),
        _gate("confirmer", "Confirmer identity supplied", len(proof.confirmer_identity.strip()) >= 3, "Confirmer required."),
    ]


def _stored_backup_gates(audit: WordPressDeploymentAudit) -> list[WordPressDraftGateResult]:
    try:
        proof = WordPressDeploymentBackupEvidence.model_validate(audit.backup_evidence)
        gates = _backup_gates(proof)
    except Exception:
        gates = [_gate("stored_backup", "Stored backup evidence validates", False, "Stored backup evidence is invalid.")]
    deadline = _as_utc(audit.backup_deadline)
    gates.append(_gate("workflow_deadline", "Manual upload and verification remain inside the original four-hour window", datetime.now(UTC) <= deadline, "The original four-hour backup deadline expired; a new backup, preflight, token, and audit are required."))
    gates.append(_gate("backup_reference_bound", "Stored backup reference remains bound", audit.backup_reference == audit.backup_evidence.get("wordpress_backup_reference"), "Backup reference changed."))
    try:
        runtime = verify_runtime_release_identity(resolve_program_root())
    except DeploymentReleaseError:
        runtime = None
    gates.append(_gate(
        "release_identity_bound",
        "Audit remains bound to the verified runtime deployment release",
        runtime is not None and audit.atlas_version == runtime.atlas_version and audit.atlas_commit == runtime.atlas_commit and audit.atlas_tag == runtime.atlas_tag
        and audit.plugin_version == PLUGIN_VERSION and audit.zip_sha256 == ZIP_SHA256
        and audit.evidence_summary.get("release_manifest_sha256") == runtime.manifest_sha256
        and audit.evidence_summary.get("release_verification_source") == runtime.verification_source
        and audit.evidence_summary.get("release_source_compatibility_id") == runtime.source_compatibility_id
        and audit.evidence_summary.get("release_manifest_integrity_verified") is True
        and audit.evidence_summary.get("release_expected_identity_matched") is True
        and audit.evidence_summary.get("release_runtime_identity_verified") is True,
        "Stored deployment release identity differs from the locked manifest.",
    ))
    return gates


def _bound_context(observed: dict[str, Any], proof: WordPressDeploymentBackupEvidence, artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "manual_install_authorization",
        "atlas_page_id": 41,
        "wordpress_page_id": 8,
        "plugin_slug": PLUGIN_SLUG,
        "plugin_path": PLUGIN_FILE,
        "artifact": artifact,
        "atlas_release": {"version": artifact.get("atlas_version"), "commit": artifact.get("atlas_commit"), "tag": artifact.get("atlas_tag"), "manifest_sha256": artifact.get("release_manifest_sha256"), "source_compatibility_id": artifact.get("release_source_compatibility_id"), "verification_source": artifact.get("release_verification_source"), "manifest_integrity_verified": artifact.get("release_manifest_integrity_verified"), "expected_release_matched": artifact.get("release_expected_identity_matched"), "git_metadata_available": artifact.get("release_git_metadata_available"), "runtime_identity_verified": artifact.get("release_runtime_identity_verified")},
        "backup": _backup_dict(proof),
        "backup_deadline": _backup_deadline(proof.wordpress_backup_completed_at).isoformat(),
        "plugin_inventory_hash": observed.get("plugin_inventory_hash"),
        "active_plugin_inventory_hash": observed.get("active_plugin_inventory_hash"),
        "page_snapshot_hash": observed.get("page_snapshot_hash"),
        "rendered_head_hash": observed.get("rendered", {}).get("head_hash"),
        "visible_content_hash": observed.get("rendered", {}).get("visible_hash"),
        "site_title": observed.get("site", {}).get("name"),
        "tagline": observed.get("site", {}).get("description"),
        "media31_snapshot_hash": observed.get("media31_snapshot_hash"),
        "media32_snapshot_hash": observed.get("media32_snapshot_hash"),
        "locked_state_hash": observed.get("locked_state_hash"),
    }


def _deployment_key(proof: WordPressDeploymentBackupEvidence, artifact: dict[str, Any]) -> str:
    return _hash({"page": 41, "wordpress_page": 8, "plugin_slug": PLUGIN_SLUG, "plugin_version": PLUGIN_VERSION, "zip_sha256": ZIP_SHA256, "atlas_version": artifact.get("atlas_version"), "atlas_commit": artifact.get("atlas_commit"), "atlas_tag": artifact.get("atlas_tag"), "manifest_sha256": artifact.get("release_manifest_sha256"), "backup_reference": proof.wordpress_backup_reference})


def _safe_evidence_path(value: str) -> str:
    if not value or "\x00" in value or value.startswith(("/", "\\")) or "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise HTTPException(422, "Evidence directory must be a relative forward-slash path.")
    if unquote(value) != value or any(separator in value for separator in ("∕", "⁄", "／", "⧵")):
        raise HTTPException(422, "Encoded traversal and alternate separators are forbidden.")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise HTTPException(422, "Empty, current, and parent path segments are forbidden.")
    if not re.fullmatch(r"docs/deployment-records/wordpress/orlando-page-8/\d{4}/\d{4}-\d{2}-\d{2}/v0\.59-install", value):
        raise HTTPException(422, "Evidence directory is outside the approved structure.")
    try:
        project_root = resolve_program_root()
    except DeploymentReleaseError as exc:
        raise HTTPException(503, str(exc)) from exc
    candidate = (project_root / value).resolve(strict=False)
    approved = (project_root / "docs" / "deployment-records" / "wordpress" / "orlando-page-8").resolve(strict=False)
    if candidate != approved and approved not in candidate.parents:
        raise HTTPException(422, "Resolved evidence directory escapes the approved root.")
    return value


def _store_reconciliation_handle(
    request: WordPressDeploymentReconciliationVerifyRequest,
    binding_hash: str,
    expires_at: datetime,
) -> str:
    now = datetime.now(UTC)
    entry = _ReconciliationHandleEntry(
        request=request.model_copy(deep=True),
        binding_hash=binding_hash,
        issued_at=now,
        expires_at=expires_at,
    )
    with _reconciliation_handle_lock:
        _purge_expired_reconciliation_handles(now)
        handle = secrets.token_urlsafe(32)
        while handle in _reconciliation_handles:
            handle = secrets.token_urlsafe(32)
        _reconciliation_handles[handle] = entry
        timer = Timer(max(0.0, (expires_at - now).total_seconds()), _expire_reconciliation_handle, args=(handle,))
        timer.daemon = True
        _reconciliation_handle_timers[handle] = timer
    timer.start()
    return handle


def _consume_reconciliation_handle(handle: str) -> _ReconciliationHandleEntry:
    now = datetime.now(UTC)
    with _reconciliation_handle_lock:
        entry = _reconciliation_handles.pop(handle, None)
        timer = _reconciliation_handle_timers.pop(handle, None)
        if timer is not None:
            timer.cancel()
        _purge_expired_reconciliation_handles(now)
    if entry is None:
        raise HTTPException(422, "The reconciliation handle is unknown, expired, already consumed, or cleared by a backend restart.")
    if entry.expires_at <= now:
        raise HTTPException(422, "The reconciliation handle expired.")
    return entry


def _purge_expired_reconciliation_handles(now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    expired = [handle for handle, entry in _reconciliation_handles.items() if entry.expires_at <= current]
    for handle in expired:
        _reconciliation_handles.pop(handle, None)
        timer = _reconciliation_handle_timers.pop(handle, None)
        if timer is not None:
            timer.cancel()


def _expire_reconciliation_handle(handle: str) -> None:
    with _reconciliation_handle_lock:
        _reconciliation_handles.pop(handle, None)
        _reconciliation_handle_timers.pop(handle, None)


def _clear_reconciliation_handles() -> None:
    """Model a backend restart in tests; production restarts clear module memory."""
    with _reconciliation_handle_lock:
        _reconciliation_handles.clear()
        for timer in _reconciliation_handle_timers.values():
            timer.cancel()
        _reconciliation_handle_timers.clear()


def _transition_records(session: Session, audit_id: int) -> list[WordPressDeploymentTransition]:
    return list(session.exec(select(WordPressDeploymentTransition).where(WordPressDeploymentTransition.audit_id == audit_id).order_by(WordPressDeploymentTransition.id)).all())


def _transition_history_hash(records: list[WordPressDeploymentTransition]) -> str:
    return _hash([
        {
            "id": record.id,
            "previous_state": record.previous_state,
            "new_state": record.new_state,
            "transitioned_at": _json_datetime(record.transitioned_at),
            "actor": record.actor,
            "reason": record.reason,
            "request_identifier": record.request_identifier,
        }
        for record in records
    ])


def _audit_revision(audit: WordPressDeploymentAudit) -> str:
    return _hash({
        "id": audit.id,
        "status": audit.status,
        "post_snapshot": audit.post_snapshot,
        "evidence_summary": audit.evidence_summary,
        "completed_at": _json_datetime(audit.completed_at),
        "error_code": audit.error_code,
        "error_message": audit.error_message,
    })


def _reconciliation_public_snapshot(
    observed: dict[str, Any],
    audit: WordPressDeploymentAudit,
    nonce: WordPressDeploymentNonce | None,
    transitions: list[WordPressDeploymentTransition],
    metadata_state_count: int,
    metadata_audit_count: int,
) -> dict[str, Any]:
    return {
        **observed,
        "audit": {"id": audit.id, "status": audit.status, "revision": _audit_revision(audit)},
        "authorization_nonce": {"id": nonce.id if nonce else None, "consumed": bool(nonce and nonce.consumed_at), "jti_fingerprint": hashlib.sha256(nonce.jti.encode()).hexdigest() if nonce else None},
        "transition_history": [record.new_state for record in transitions],
        "transition_history_hash": _transition_history_hash(transitions),
        "inactive_metadata_safety": {
            "verification_source": "corroborated_inactive_inventory_atlas_rows_and_rendered_absence",
            "private_option_name": "_project_atlas_metadata_safety_v1",
            "private_option_known_to_exist_from_prior_read_only_diagnosis": True,
            "private_option_directly_read": False,
            "private_option_serialized_value_available": False,
            "direct_payload_or_revision_claimed": False,
            "metadata_state_rows": metadata_state_count,
            "metadata_audit_rows": metadata_audit_count,
            "rendered_metadata_absent": _rendered_metadata_absent(observed.get("rendered", {})),
            "cache_purge_observed": False,
        },
        "reconciliation_cache_purge_count": 0,
        "wordpress_write_count": 0,
        "atlas_write_count": 0,
    }


def _rendered_metadata_absent(rendered: dict[str, Any]) -> bool:
    inventory = rendered.get("metadata_inventory", {})
    return all(not inventory.get(key, []) for key in ("meta_descriptions", "open_graph", "twitter", "json_ld", "media32_references")) and not inventory.get("unexpected_metadata_owners", []) and not inventory.get("duplicates", [])


def _nested_text(value: Any, key: str) -> str:
    if not isinstance(value, dict):
        return ""
    nested = value.get(key)
    if isinstance(nested, dict):
        raw = nested.get("raw")
        if isinstance(raw, str):
            return raw
        rendered = nested.get("rendered")
        if isinstance(rendered, str):
            return rendered
    return str(nested) if isinstance(nested, str) else ""


def _evidence_expiry(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise HTTPException(422, "Browser evidence expiry must be timezone-aware.")
    return parsed.astimezone(UTC)


def _json_datetime(value: datetime | str | None) -> str | None:
    if isinstance(value, str):
        return value
    return value.astimezone(UTC).isoformat() if value and value.tzinfo else (value.replace(tzinfo=UTC).isoformat() if value else None)


def _transition(session: Session, audit: WordPressDeploymentAudit, new_state: str, actor: str, reason: str, request_identifier: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(audit.status, set())
    if new_state not in allowed:
        raise HTTPException(409, f"Invalid deployment transition: {audit.status} -> {new_state}.")
    previous = audit.status
    audit.status = new_state
    session.add(audit)
    session.add(WordPressDeploymentTransition(audit_id=audit.id or 0, previous_state=previous, new_state=new_state, actor=actor, reason=reason, request_identifier=request_identifier))


def _record_initial_transition(session: Session, audit: WordPressDeploymentAudit, actor: str, reason: str, request_identifier: str) -> None:
    session.add(WordPressDeploymentTransition(audit_id=audit.id or 0, previous_state=None, new_state="installation_authorized", actor=actor, reason=reason, request_identifier=request_identifier))


def _fail_audit(session: Session, audit: WordPressDeploymentAudit, actor: str, error_code: str, gates: list[WordPressDraftGateResult]) -> None:
    _transition(session, audit, "failed", actor, error_code, secrets.token_hex(16))
    audit.error_code = error_code
    audit.error_message = "; ".join(gate.message for gate in gates if not gate.passed)[:2000]
    audit.completed_at = datetime.now(UTC)
    session.add(audit)
    session.commit()


def _history(session: Session, audit_id: int) -> list[str]:
    records = session.exec(select(WordPressDeploymentTransition).where(WordPressDeploymentTransition.audit_id == audit_id).order_by(WordPressDeploymentTransition.id)).all()
    return [record.new_state for record in records]


def _request(site: str, user: str, password: str, method: str, path: str, text: bool = False) -> Any:
    if method != "GET":
        raise RuntimeError("Deployment inspection permits WordPress GET requests only.")
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            response = client.request(method, f"{site.rstrip('/')}{path}", auth=httpx.BasicAuth(user, password), headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
        if response.status_code >= 400:
            return {"_error": f"HTTP {response.status_code}"}
        if text:
            parsed = _parse_html(response.text)
            return {
                "parsed": parsed,
                "atlas_metadata_marker_present": "data-project-atlas=\"metadata\"" in response.text or "Project Atlas Metadata Bridge" in response.text,
                "cache_headers": {key: value for key, value in response.headers.items() if key.lower() in {"age", "cache-control", "cf-cache-status", "x-cache", "x-proxy-cache", "x-sg-cache"}},
            }
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"_error": exc.__class__.__name__}


def _audit(session: Session, audit_id: int) -> WordPressDeploymentAudit:
    audit = session.get(WordPressDeploymentAudit, audit_id)
    if not audit or audit.generated_page_id != 41 or audit.wordpress_post_id != 8 or audit.plugin_slug != PLUGIN_SLUG:
        raise HTTPException(404, "Deployment audit not found.")
    return audit


def _canonical_plugins(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(value, key=lambda item: str(item.get("plugin", "")))


def _resource_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value.get(key) for key in ("id", "status", "slug", "link", "featured_media", "post", "source_url", "modified_gmt")}


def _backup_dict(proof: WordPressDeploymentBackupEvidence) -> dict[str, Any]:
    return proof.model_dump(mode="json", include=set(WordPressDeploymentBackupEvidence.model_fields))


def _backup_age(value: datetime) -> timedelta | None:
    return datetime.now(UTC) - value.astimezone(UTC) if value.tzinfo else None


def _backup_deadline(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HTTPException(422, "Backup timestamp must be timezone-aware.")
    return value.astimezone(UTC) + BACKUP_WINDOW


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _clean_findings(value: str) -> bool:
    return not re.search(r"warning|notice|fatal|register_rest_route|headers already sent", value, re.I)


def _target(page_id: int) -> None:
    if page_id != 41:
        raise HTTPException(404, "Deployment workflow is limited to Atlas page 41.")


def _gate(code: str, label: str, passed: bool, message: str) -> WordPressDraftGateResult:
    return WordPressDraftGateResult(code=code, label=label, passed=bool(passed), message="Passed." if passed else message)
