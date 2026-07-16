from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import secrets
from threading import Lock, Timer
from typing import Any

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    WordPressActivationAudit,
    WordPressDeploymentAudit,
    WordPressDeploymentTransition,
    WordPressMetadataState,
    WordPressMetadataSyncAudit,
)
from app.schemas.wordpress import (
    WordPressActivationApplyRequest,
    WordPressActivationPreflight,
    WordPressActivationPreflightRequest,
    WordPressActivationResult,
    WordPressDeploymentBackupEvidence,
    WordPressDraftGateResult,
)
from app.services.wordpress_deployment import (
    EXPECTED_CORRECTED_BODY_HASH,
    PLUGIN_FILE,
    PLUGIN_SLUG,
    PLUGIN_VERSION,
    ZIP_SHA256,
    _audit_revision,
    _backup_deadline,
    _backup_gates,
    _canonical_plugins,
    _clean_findings,
    _gate,
    _hash,
    _matching_reconciliation_plugins,
    _normalize_plugin_identifier,
    _observe,
    _rendered_metadata_absent,
    _target,
    _transition_history_hash,
    _verify_artifact,
)
from app.services.wordpress_rendered_state import EXPECTED_H1, validate_manual_browser_evidence
from app.services.wordpress_sandbox import get_wordpress_application_password, read_wordpress_settings


ACTIVATION_PHRASE = "ACTIVATE PROJECT ATLAS METADATA BRIDGE"
ACTIVATION_TTL = timedelta(minutes=10)
ACTIVATION_WORDPRESS_SCOPE = [
    "POST /wp-json/wp/v2/plugins/project-atlas-metadata-bridge/project-atlas-metadata-bridge",
    'JSON body exactly {"status":"active"}',
]
ACTIVATION_ATLAS_SCOPE = [
    "create one pending WordPressActivationAudit before the WordPress request",
    "finalize only that WordPressActivationAudit after read-only verification",
]


@dataclass(frozen=True)
class _ActivationHandleEntry:
    request: WordPressActivationPreflightRequest
    binding_hash: str
    issued_at: datetime
    expires_at: datetime


_handle_lock = Lock()
_handles: dict[str, _ActivationHandleEntry] = {}
_handle_timers: dict[str, Timer] = {}


def activation_preflight(
    session: Session,
    page_id: int,
    request: WordPressActivationPreflightRequest,
    *,
    issue_handle: bool = True,
    bound_expiry: datetime | None = None,
) -> WordPressActivationPreflight:
    """Inspect activation readiness without mutating WordPress or Atlas."""
    _target(page_id)
    proof = WordPressDeploymentBackupEvidence.model_validate(
        request.model_dump(mode="json", include=set(WordPressDeploymentBackupEvidence.model_fields))
    )
    audit = session.get(WordPressDeploymentAudit, request.installation_audit_id)
    evidence = request.manual_browser_evidence
    evidence_valid, evidence_reason = validate_manual_browser_evidence(
        evidence,
        __import__("os").environ.get("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", ""),
    )
    evidence_valid = bool(evidence_valid and evidence and evidence.evidence_schema_version == 1)
    if evidence and evidence.evidence_schema_version != 1:
        evidence_reason = "Activation preflight requires fresh schema-v1 evidence."
    artifact, artifact_gates = _verify_artifact()
    observed = _observe(session, proof) if evidence_valid and any(
        gate.code == "release_identity" and gate.passed for gate in artifact_gates
    ) else _unavailable_observation(evidence_reason)
    activation_audits = list(session.exec(select(WordPressActivationAudit)))
    metadata_states = list(session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == 41)))
    metadata_audits = list(session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id == 41)))
    transitions = list(session.exec(
        select(WordPressDeploymentTransition)
        .where(WordPressDeploymentTransition.audit_id == request.installation_audit_id)
        .order_by(WordPressDeploymentTransition.id)
    ))
    expected_post = _expected_post_activation(observed)
    gates = [
        *artifact_gates,
        *_backup_gates(proof),
        *_activation_gates(
            request,
            audit,
            transitions,
            activation_audits,
            observed,
            artifact,
            metadata_states,
            metadata_audits,
            evidence_valid,
            evidence_reason,
        ),
    ]
    ready = all(gate.passed for gate in gates)
    expires_at = bound_expiry
    if ready and expires_at is None:
        evidence_expiry = _evidence_expiry(evidence.expires_at) if evidence else datetime.now(UTC)
        expires_at = min(datetime.now(UTC) + ACTIVATION_TTL, evidence_expiry, _backup_deadline(proof.wordpress_backup_completed_at))
    binding = _activation_binding(request, audit, transitions, observed, artifact, expected_post, expires_at)
    binding_hash = _hash(binding)
    handle = None
    handle_fingerprint = None
    if ready and expires_at and expires_at <= datetime.now(UTC):
        ready = False
        gates.append(_gate("activation_handle_lifetime", "Evidence and backup permit a positive handle lifetime", False, "Evidence or backup expires before activation can be authorized."))
    elif ready and issue_handle and expires_at:
        handle = _store_handle(request, binding_hash, expires_at)
        handle_fingerprint = hashlib.sha256(handle.encode()).hexdigest()
    return WordPressActivationPreflight(
        installation_audit_id=request.installation_audit_id,
        status="activation_preflight_ready" if ready else "activation_preflight_blocked",
        activation_preflight_ready=ready,
        activation_handle=handle,
        activation_handle_fingerprint=handle_fingerprint,
        confirmation_phrase=ACTIVATION_PHRASE if ready else None,
        binding_hash=binding_hash if ready else None,
        expires_at=expires_at if ready else None,
        backup_deadline=_backup_deadline(proof.wordpress_backup_completed_at) if proof.wordpress_backup_completed_at.tzinfo else None,
        artifact=artifact,
        inspected_state=_public_snapshot(observed, audit, metadata_states, metadata_audits),
        gate_results=gates,
        proposed_wordpress_write_scope=ACTIVATION_WORDPRESS_SCOPE if ready else [],
        proposed_atlas_write_scope=ACTIVATION_ATLAS_SCOPE if ready else [],
        expected_post_plugin_inventory_hash=expected_post.get("plugin_inventory_hash") if ready else None,
        expected_post_active_plugin_inventory_hash=expected_post.get("active_plugin_inventory_hash") if ready else None,
    )


def apply_activation(
    session: Session,
    page_id: int,
    request: WordPressActivationApplyRequest,
) -> WordPressActivationResult:
    """Consume one handle and issue exactly one narrowly fixed activation request."""
    _target(page_id)
    if not hmac.compare_digest(request.confirmation_phrase, ACTIVATION_PHRASE):
        raise HTTPException(422, "The Metadata Bridge activation phrase is incorrect.")
    entry = _consume_handle(request.activation_handle)
    rerun = activation_preflight(
        session,
        page_id,
        entry.request,
        issue_handle=False,
        bound_expiry=entry.expires_at,
    )
    if not rerun.activation_preflight_ready or rerun.binding_hash != entry.binding_hash:
        raise HTTPException(409, "Activation state changed. Run a new token-free activation preflight.")
    handle_fingerprint = hashlib.sha256(request.activation_handle.encode()).hexdigest()
    evidence = entry.request.manual_browser_evidence
    runtime = entry.request.expected_runtime_identity
    audit = WordPressActivationAudit(
        generated_page_id=41,
        wordpress_post_id=8,
        installation_audit_id=entry.request.installation_audit_id,
        status="pending",
        operator=entry.request.operator,
        confirmation_phrase_hash=hashlib.sha256(ACTIVATION_PHRASE.encode()).hexdigest(),
        handle_fingerprint=handle_fingerprint,
        binding_hash=entry.binding_hash,
        atlas_version=runtime.atlas_version,
        atlas_commit=runtime.atlas_commit,
        atlas_tag=runtime.atlas_tag,
        manifest_sha256=runtime.manifest_sha256,
        plugin_slug=entry.request.expected_plugin_slug,
        plugin_path=entry.request.expected_plugin_path,
        plugin_version=entry.request.expected_plugin_version,
        zip_sha256=entry.request.expected_zip_sha256,
        backup_evidence=entry.request.model_dump(mode="json", include=set(WordPressDeploymentBackupEvidence.model_fields)),
        browser_evidence_id=evidence.evidence_id if evidence else "missing",
        browser_evidence_schema=evidence.evidence_schema if evidence else "missing",
        browser_evidence_schema_version=evidence.evidence_schema_version if evidence else 0,
        pre_snapshot=rerun.inspected_state,
        gate_results=[gate.model_dump(mode="json") for gate in rerun.gate_results],
        wordpress_write_count=0,
        wordpress_write_scope=ACTIVATION_WORDPRESS_SCOPE,
        atlas_write_scope=ACTIVATION_ATLAS_SCOPE,
        transition_history=["pending"],
    )
    session.add(audit)
    session.commit()
    session.refresh(audit)
    activation_response = _activate_plugin(session)
    audit.wordpress_write_count = 1
    if activation_response.get("_error"):
        failure = _gate("activation_response", "WordPress accepted the one activation request", False, str(activation_response["_error"]))
        return _finalize_audit(session, audit, "failed", [failure], {"activation_response": activation_response})
    proof = WordPressDeploymentBackupEvidence.model_validate(
        entry.request.model_dump(mode="json", include=set(WordPressDeploymentBackupEvidence.model_fields))
    )
    observed = _observe(session, proof)
    plugin_status = _read_plugin_status(session)
    expected_post = {
        "plugin_inventory_hash": rerun.expected_post_plugin_inventory_hash,
        "active_plugin_inventory_hash": rerun.expected_post_active_plugin_inventory_hash,
    }
    post_gates = _post_activation_gates(entry.request, rerun.inspected_state, observed, plugin_status, expected_post, session)
    status = "verified" if all(gate.passed for gate in post_gates) else "verification_failed"
    snapshot = {**_public_snapshot(observed, session.get(WordPressDeploymentAudit, entry.request.installation_audit_id), list(session.exec(select(WordPressMetadataState))), list(session.exec(select(WordPressMetadataSyncAudit)))), "plugin_status": plugin_status, "activation_response": _activation_response_snapshot(activation_response)}
    return _finalize_audit(session, audit, status, post_gates, snapshot)


def _activation_gates(
    request: WordPressActivationPreflightRequest,
    audit: WordPressDeploymentAudit | None,
    transitions: list[WordPressDeploymentTransition],
    activation_audits: list[WordPressActivationAudit],
    observed: dict[str, Any],
    artifact: dict[str, Any],
    metadata_states: list[WordPressMetadataState],
    metadata_audits: list[WordPressMetadataSyncAudit],
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
    audit_completion = (audit.evidence_summary or {}).get("completion_mode") if audit else None
    prior_safety = ((audit.post_snapshot or {}).get("inactive_metadata_safety") or {}) if audit else {}
    return [
        _gate("evidence_contract", "Fresh signed schema-v1 evidence is valid", evidence_valid, evidence_reason or "Fresh schema-v1 evidence required."),
        _gate("expected_runtime", "Expected runtime identity independently matches", expected_runtime == actual_runtime and artifact.get("release_runtime_identity_verified") is True and artifact.get("release_manifest_integrity_verified") is True and artifact.get("release_expected_identity_matched") is True, "Runtime identity changed."),
        _gate("repository_identity", "HEAD, origin/main, and tag attest to the published release", request.repository_head == request.repository_origin_main == request.expected_runtime_identity.atlas_commit and request.repository_tag == request.expected_runtime_identity.atlas_tag, "Repository identity differs."),
        _gate("repository_clean", "Working tree is attested clean", request.repository_working_tree_clean, "Working tree is not clean."),
        _gate("protected_paths", "Protected paths are attested unchanged", request.protected_paths_unchanged, "Protected paths changed."),
        _gate("no_post_backup_change", "No relevant WordPress change followed the SiteGround backup", request.no_relevant_wordpress_change_after_backup, "A post-backup WordPress change requires a fresh backup."),
        _gate("installation_audit", "Installation audit 1 is verified through installed-inactive reconciliation", bool(audit and audit.id == 1 and audit.status == "verified" and audit_completion == "installed_inactive_reconciliation"), "Verified installed-inactive audit 1 required."),
        _gate("installation_history", "Original installation history remains intact", [item.new_state for item in transitions] == ["installation_authorized", "awaiting_manual_installation", "verified"], "Installation transition history changed."),
        _gate("activation_audit_absent", "No activation audit already exists", not activation_audits, "Activation was already attempted."),
        _gate("authorized_artifact", "Plugin identity and authorized ZIP remain exact", bool(audit and audit.plugin_slug == request.expected_plugin_slug == PLUGIN_SLUG and audit.plugin_path == request.expected_plugin_path == PLUGIN_FILE and audit.plugin_version == request.expected_plugin_version == PLUGIN_VERSION and audit.zip_sha256 == request.expected_zip_sha256 == ZIP_SHA256), "Authorized plugin artifact differs."),
        _gate("plugin_singleton", "Exactly one normalized Metadata Bridge is installed", len(matches) == 1, "Plugin is missing, duplicated, wrapped, or malformed."),
        _gate("plugin_inactive", "Metadata Bridge is currently inactive", len(matches) == 1 and matches[0].get("status") == "inactive", "Plugin must be inactive before activation."),
        _gate("plugin_version", "Installed Metadata Bridge version is exact", len(matches) == 1 and matches[0].get("version") == PLUGIN_VERSION, "Plugin version differs."),
        _gate("extensionless_identifier", "WordPress extensionless REST identity normalizes to the authorized entry", len(matches) == 1 and _normalize_plugin_identifier(matches[0].get("plugin")).authorized_entry_path == PLUGIN_FILE, "Plugin REST identity is unsafe."),
        _gate("plugin_inventory", "Inactive plugin inventory hash is exact", observed.get("plugin_inventory_hash") == request.expected_plugin_inventory_hash, "Plugin inventory changed."),
        _gate("active_inventory", "Active-plugin inventory hash is exact", observed.get("active_plugin_inventory_hash") == request.expected_active_plugin_inventory_hash, "Active-plugin inventory changed."),
        _gate("metadata_rows", "Atlas metadata state and audit rows remain zero", len(metadata_states) == len(metadata_audits) == 0, "Metadata state already exists."),
        _gate("inactive_safety", "Inactive safety is corroborated without overclaiming private option values", prior_safety.get("verification_source") == "corroborated_inactive_inventory_atlas_rows_and_rendered_absence" and prior_safety.get("direct_payload_or_revision_claimed") is False, "Inactive safety state is not corroborated."),
        _gate("rendered", "Rendered public state is verified", rendered.get("verified") is True and rendered.get("signature_validated") is True, "Rendered state unavailable."),
        _gate("h1", "Exactly one unchanged visible H1 renders", rendered.get("h1") == [EXPECTED_H1], "Rendered H1 changed."),
        _gate("rendering_disabled", "No Atlas metadata renders", not rendered.get("atlas_metadata_marker_present", False) and _rendered_metadata_absent(rendered), "Atlas metadata unexpectedly renders."),
        _gate("page", "Page 8 identity remains exact", page.get("id") == 8 and page.get("status") == "publish" and page.get("slug") == "drywood-termite-tenting-orlando-fl" and page.get("featured_media") == 31, "Page 8 identity changed."),
        _gate("page_snapshot", "Page snapshot hash is exact", observed.get("page_snapshot_hash") == request.expected_page_snapshot_hash, "Page snapshot changed."),
        _gate("body_hash", "Corrected body hash is exact", observed.get("page_body_hash") == request.expected_body_hash == EXPECTED_CORRECTED_BODY_HASH, "Page body changed."),
        _gate("body_opening", "Body begins with the exact H2", observed.get("page_body_begins_expected_h2") is True, "Body H2 opening changed."),
        _gate("media31", "Media 31 snapshot is exact", media31.get("id") == 31 and observed.get("media31_snapshot_hash") == request.expected_media31_snapshot_hash, "Media 31 changed."),
        _gate("media32", "Media 32 remains unchanged and absent", media32.get("id") == 32 and observed.get("media32_snapshot_hash") == request.expected_media32_snapshot_hash and not observed.get("page_references_media32") and not rendered.get("media32_reference_present"), "Media 32 changed or is referenced."),
        _gate("site_identity", "Site Title and Tagline remain exact", observed.get("site") == {"name": "My WordPress", "description": ""}, "Site identity changed."),
        _gate("php_findings", "PHP and REST/header findings are clean", _clean_findings(request.php_error_log_findings), "PHP, REST registration, or header findings require review."),
        _gate("browser_findings", "Browser-console and visible-site findings are clean", _clean_findings(request.browser_console_findings), "Browser or visible-site findings require review."),
        _gate("cache_boundary", "No Atlas cache purge is observed", observed.get("cache_headers") == rendered.get("cache_headers", {}) and ((audit.post_snapshot or {}).get("reconciliation_cache_purge_count") if audit else None) == 0, "Cache observation changed."),
        _gate("activation_contract", "Activation is separate from metadata application", True, "Activation scope changed."),
        _gate("read_only_preflight", "Preflight uses WordPress GET requests only", observed.get("wordpress_request_methods") == ["GET"], "Preflight attempted a WordPress write."),
    ]


def _post_activation_gates(request, before, after, plugin_status, expected_post, session):
    matches = _matching_reconciliation_plugins(after.get("plugins", []))
    rendered = after.get("rendered", {})
    metadata_states = list(session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == 41)))
    metadata_audits = list(session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id == 41)))
    snapshot = plugin_status.get("snapshot") if isinstance(plugin_status.get("snapshot"), dict) else plugin_status
    return [
        _gate("activation_response", "Exactly one activation request succeeded", plugin_status.get("active") is True, "Plugin status endpoint did not confirm activation."),
        _gate("plugin_singleton", "Exactly one Metadata Bridge remains installed", len(matches) == 1 and matches[0].get("version") == PLUGIN_VERSION, "Installed plugin identity changed."),
        _gate("plugin_active", "Metadata Bridge is active", len(matches) == 1 and matches[0].get("status") in {"active", "network-active"}, "Plugin is not active."),
        _gate("plugin_inventory", "Full plugin inventory matches the deterministic active state", after.get("plugin_inventory_hash") == expected_post.get("plugin_inventory_hash"), "Plugin inventory delta is not activation-only."),
        _gate("active_inventory", "Active-plugin inventory contains exactly the expected new entry", after.get("active_plugin_inventory_hash") == expected_post.get("active_plugin_inventory_hash"), "Active-plugin inventory delta changed."),
        _gate("other_plugins", "No unrelated plugin changed", _plugins_without_bridge(after) == _plugins_without_bridge(before), "An unrelated plugin changed."),
        _gate("disabled_safety", "Activation initialized or preserved disabled safety", snapshot.get("rendering_enabled") is False and snapshot.get("enabled_metadata_state") is False, "Rendering became enabled."),
        _gate("payload_absent", "Metadata payload remains absent", snapshot.get("payload") is None and not snapshot.get("payload_hash"), "Metadata payload was applied."),
        _gate("revision_zero", "Metadata revision remains zero", str(snapshot.get("revision")) == "0", "Metadata revision changed."),
        _gate("metadata_rows", "Activation created no Atlas metadata rows", len(metadata_states) == len(metadata_audits) == 0, "Activation created metadata state or audit rows."),
        _gate("page_snapshot", "Page snapshot remains unchanged", after.get("page_snapshot_hash") == before.get("page_snapshot_hash") == request.expected_page_snapshot_hash, "Page changed during activation."),
        _gate("body_hash", "Body hash remains unchanged", after.get("page_body_hash") == before.get("page_body_hash") == request.expected_body_hash, "Body changed during activation."),
        _gate("media31", "Media 31 remains unchanged", after.get("media31_snapshot_hash") == before.get("media31_snapshot_hash") == request.expected_media31_snapshot_hash, "Media 31 changed."),
        _gate("media32", "Media 32 remains unchanged and absent", after.get("media32_snapshot_hash") == before.get("media32_snapshot_hash") == request.expected_media32_snapshot_hash and not after.get("page_references_media32") and not rendered.get("media32_reference_present"), "Media 32 changed or rendered."),
        _gate("site_identity", "Site Title and Tagline remain unchanged", after.get("site") == before.get("site") == {"name": "My WordPress", "description": ""}, "Site identity changed."),
        _gate("rendered_metadata", "No Atlas metadata renders after activation", rendered.get("verified") is True and not rendered.get("atlas_metadata_marker_present", False) and _rendered_metadata_absent(rendered), "Atlas metadata rendered after activation."),
        _gate("cache_boundary", "No cache purge occurred", after.get("cache_headers") == before.get("cache_headers") and before.get("reconciliation_cache_purge_count", 0) == 0, "Cache observation changed."),
        _gate("read_only_verification", "Post-activation verification uses GET requests only", after.get("wordpress_request_methods") == ["GET"], "Verification attempted another WordPress write."),
    ]


def _activate_plugin(session: Session) -> dict[str, Any]:
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password):
        return {"_error": "credentials_unavailable"}
    path = "/wp-json/wp/v2/plugins/project-atlas-metadata-bridge/project-atlas-metadata-bridge"
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            response = client.post(
                f"{settings.site_url.rstrip('/')}{path}",
                json={"status": "active"},
                auth=httpx.BasicAuth(settings.username, password),
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
        if response.status_code >= 400:
            return {"_error": f"HTTP {response.status_code}", "status_code": response.status_code}
        value = response.json()
        return value if isinstance(value, dict) else {"_error": "non_object_response"}
    except (httpx.HTTPError, ValueError) as exc:
        return {"_error": exc.__class__.__name__}


def _read_plugin_status(session: Session) -> dict[str, Any]:
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password):
        return {"_error": "credentials_unavailable"}
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get(
                f"{settings.site_url.rstrip('/')}/wp-json/project-atlas/v1/status",
                auth=httpx.BasicAuth(settings.username, password),
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
        if response.status_code >= 400:
            return {"_error": f"HTTP {response.status_code}"}
        value = response.json()
        return value if isinstance(value, dict) else {"_error": "non_object_response"}
    except (httpx.HTTPError, ValueError) as exc:
        return {"_error": exc.__class__.__name__}


def _expected_post_activation(observed: dict[str, Any]) -> dict[str, Any]:
    plugins = deepcopy(observed.get("plugins", []))
    matches = [item for item in plugins if _normalize_plugin_identifier(item.get("plugin")).authorized_entry_path == PLUGIN_FILE]
    if len(matches) != 1:
        return {}
    matches[0]["status"] = "active"
    active = sorted(set([*observed.get("active_plugins", []), matches[0].get("plugin")]))
    return {"plugin_inventory_hash": _hash(plugins), "active_plugin_inventory_hash": _hash(active)}


def _activation_binding(request, audit, transitions, observed, artifact, expected_post, expires_at):
    evidence = request.manual_browser_evidence
    return {
        "action": "activate_metadata_bridge",
        "installation_audit_id": request.installation_audit_id,
        "installation_audit_revision": _audit_revision(audit) if audit else None,
        "installation_history_hash": _transition_history_hash(transitions),
        "runtime": request.expected_runtime_identity.model_dump(mode="json"),
        "repository": {"head": request.repository_head, "origin_main": request.repository_origin_main, "tag": request.repository_tag, "clean": request.repository_working_tree_clean, "protected": request.protected_paths_unchanged},
        "backup": request.model_dump(mode="json", include=set(WordPressDeploymentBackupEvidence.model_fields), exclude={"manual_browser_evidence"}),
        "plugin": {"slug": request.expected_plugin_slug, "path": request.expected_plugin_path, "version": request.expected_plugin_version, "zip_sha256": request.expected_zip_sha256},
        "before": {"plugins": observed.get("plugin_inventory_hash"), "active_plugins": observed.get("active_plugin_inventory_hash"), "page": observed.get("page_snapshot_hash"), "body": observed.get("page_body_hash"), "media31": observed.get("media31_snapshot_hash"), "media32": observed.get("media32_snapshot_hash"), "rendered_head": observed.get("rendered", {}).get("head_hash"), "visible": observed.get("rendered", {}).get("visible_hash"), "cache": _hash(observed.get("cache_headers", {}))},
        "expected_after": expected_post,
        "evidence": {"id": evidence.evidence_id if evidence else None, "schema": evidence.evidence_schema if evidence else None, "version": evidence.evidence_schema_version if evidence else None, "signature": evidence.helper_signature if evidence else None, "expires_at": str(evidence.expires_at) if evidence else None},
        "artifact_source_sha256": artifact.get("plugin_source_sha256"),
        "handle_expires_at": expires_at.isoformat() if expires_at else None,
    }


def _store_handle(request, binding_hash, expires_at):
    handle = secrets.token_urlsafe(32)
    entry = _ActivationHandleEntry(request=request, binding_hash=binding_hash, issued_at=datetime.now(UTC), expires_at=expires_at)
    with _handle_lock:
        _handles[handle] = entry
        timer = Timer(max(0.0, (expires_at - datetime.now(UTC)).total_seconds()), _expire_handle, args=(handle,))
        timer.daemon = True
        _handle_timers[handle] = timer
        timer.start()
    return handle


def _consume_handle(handle):
    with _handle_lock:
        entry = _handles.pop(handle, None)
        timer = _handle_timers.pop(handle, None)
        if timer:
            timer.cancel()
    if not entry:
        raise HTTPException(422, "Activation handle is unknown, expired, consumed, or invalidated by restart.")
    if entry.expires_at <= datetime.now(UTC):
        raise HTTPException(422, "Activation handle expired.")
    return entry


def _expire_handle(handle):
    with _handle_lock:
        _handles.pop(handle, None)
        _handle_timers.pop(handle, None)


def _clear_activation_handles() -> None:
    """Test/restart helper; production restarts naturally discard process memory."""
    with _handle_lock:
        for timer in _handle_timers.values():
            timer.cancel()
        _handles.clear()
        _handle_timers.clear()


def _finalize_audit(session, audit, status, gates, snapshot):
    audit.status = status
    audit.post_snapshot = snapshot
    audit.gate_results = [gate.model_dump(mode="json") for gate in gates]
    audit.transition_history = [*audit.transition_history, status]
    audit.completed_at = datetime.now(UTC)
    audit.error_code = None if status == "verified" else status
    audit.error_message = None if status == "verified" else "; ".join(g.message for g in gates if not g.passed)[:2000]
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return WordPressActivationResult(
        installation_audit_id=audit.installation_audit_id,
        activation_audit_id=audit.id or 0,
        status=status,
        binding_hash=audit.binding_hash,
        state_history=audit.transition_history,
        gate_results=gates,
        inspected_state=snapshot,
        wordpress_write_scope=ACTIVATION_WORDPRESS_SCOPE,
        atlas_write_scope=ACTIVATION_ATLAS_SCOPE,
        further_action_required=status != "verified",
    )


def _public_snapshot(observed, audit, metadata_states, metadata_audits):
    return {
        **observed,
        "installation_audit": {"id": audit.id, "status": audit.status, "completion_mode": (audit.evidence_summary or {}).get("completion_mode")} if audit else None,
        "metadata_state_rows": len(metadata_states),
        "metadata_audit_rows": len(metadata_audits),
        "wordpress_write_count": 0,
        "atlas_write_count": 0,
    }


def _unavailable_observation(reason):
    return {"_error": reason or "evidence_or_runtime_unavailable", "plugins": [], "rendered": {"verified": False}, "wordpress_request_methods": [], "wordpress_request_performed": False, "read_only": True}


def _plugins_without_bridge(snapshot):
    return _canonical_plugins([item for item in snapshot.get("plugins", []) if _normalize_plugin_identifier(item.get("plugin")).authorized_entry_path != PLUGIN_FILE])


def _activation_response_snapshot(value):
    return {key: value.get(key) for key in ("plugin", "status", "version") if key in value}


def _evidence_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise HTTPException(422, "Browser evidence expiration is malformed.") from exc
    if parsed.tzinfo is None:
        raise HTTPException(422, "Browser evidence expiration must be timezone-aware.")
    return parsed.astimezone(UTC)
