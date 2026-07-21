"""Strict cleanup profile for upgrade bootstrap 0.3.0 after bridge 0.57.7 verification."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import os
import secrets
from threading import Lock, Timer
from typing import Literal

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    WordPressActivationAudit,
    WordPressBootstrapCleanupAudit,
    WordPressDeploymentAudit,
    WordPressMetadataLifecycleAudit,
    WordPressMetadataState,
    WordPressMetadataSyncAudit,
    WordPressPluginUpgradeAudit,
)
from app.schemas.wordpress import (
    WordPressBootstrapCleanupApplyRequest,
    WordPressBootstrapCleanupPreflight,
    WordPressBootstrapCleanupPreflightRequest,
    WordPressBootstrapCleanupResult,
    WordPressBootstrapDeletionPreflightRequest,
    WordPressDeploymentBackupEvidence,
    WordPressDraftGateResult,
)
from app.services.wordpress_activation import _read_plugin_status
from app.services.wordpress_deployment import (
    EXPECTED_CORRECTED_BODY_HASH,
    PLUGIN_FILE,
    PLUGIN_SLUG,
    _backup_deadline,
    _backup_gates,
    _clean_findings,
    _gate,
    _hash,
    _matching_reconciliation_plugins,
    _normalize_plugin_identifier,
    _observe,
    _rendered_metadata_absent,
    _target,
    _verify_artifact,
)
from app.services.wordpress_plugin_upgrade_0577 import (
    BOOTSTRAP_ENTRY_SHA256,
    BOOTSTRAP_STATUS_ROUTE,
    BOOTSTRAP_UPGRADE_ROUTE,
    BOOTSTRAP_VERSION,
    BOOTSTRAP_ZIP_SHA256,
    LEGACY_ROUTE,
    LIFECYCLE_ROUTES,
    TARGET_VERSION,
    _evidence_expiry,
    _metadata_state,
    _page_media_state,
    _proof,
    _public_snapshot,
    _read_bootstrap_status,
    _read_route_registry,
    _target_artifact_disables_legacy_route,
    _unavailable_observation,
    _verify_bootstrap_artifact,
)
from app.services.wordpress_rendered_state import EXPECTED_H1, validate_manual_browser_evidence
from app.services.wordpress_http import wordpress_basic_auth, wordpress_http_client
from app.services.wordpress_sandbox import get_wordpress_application_password, read_wordpress_settings


BOOTSTRAP_SLUG = "project-atlas-upgrade-bootstrap"
BOOTSTRAP_ENTRY = f"{BOOTSTRAP_SLUG}/{BOOTSTRAP_SLUG}.php"
DEACTIVATION_PHRASE = "DEACTIVATE PROJECT ATLAS UPGRADE BOOTSTRAP 0.3.0"
DELETION_PHRASE = "DELETE PROJECT ATLAS UPGRADE BOOTSTRAP 0.3.0"
CLEANUP_TTL = timedelta(minutes=10)
DEACTIVATION_WORDPRESS_SCOPE = [
    f"POST /wp-json/wp/v2/plugins/{BOOTSTRAP_SLUG}/{BOOTSTRAP_SLUG}",
    'JSON body exactly {"status":"inactive"}',
    "only the fixed upgrade bootstrap is removed from the active-plugin inventory",
]
DELETION_WORDPRESS_SCOPE = [
    f"DELETE /wp-json/wp/v2/plugins/{BOOTSTRAP_SLUG}/{BOOTSTRAP_SLUG}",
    "no caller-controlled path, slug, endpoint, method, or body",
    "only the already-inactive fixed upgrade bootstrap is deleted",
]
DEACTIVATION_ATLAS_SCOPE = [
    "create one pending WordPressBootstrapCleanupAudit before deactivation",
    "finalize only that audit as deactivated after read-only verification",
]
DELETION_ATLAS_SCOPE = [
    "mark the selected deactivated WordPressBootstrapCleanupAudit pending before deletion",
    "finalize only that audit as verified after read-only verification",
]


@dataclass(frozen=True)
class _CleanupHandleEntry:
    phase: Literal["deactivation", "deletion"]
    request: WordPressBootstrapCleanupPreflightRequest | WordPressBootstrapDeletionPreflightRequest
    binding_hash: str
    issued_at: datetime
    expires_at: datetime


_handle_lock = Lock()
_handles: dict[str, _CleanupHandleEntry] = {}
_handle_timers: dict[str, Timer] = {}
_cleared_generation = 0


def cleanup_preflight(
    session: Session,
    page_id: int,
    request: WordPressBootstrapCleanupPreflightRequest,
    *,
    issue_handle: bool = True,
    bound_expiry: datetime | None = None,
) -> WordPressBootstrapCleanupPreflight:
    return _preflight(session, page_id, request, "deactivation", issue_handle, bound_expiry)


def deletion_preflight(
    session: Session,
    page_id: int,
    request: WordPressBootstrapDeletionPreflightRequest,
    *,
    issue_handle: bool = True,
    bound_expiry: datetime | None = None,
) -> WordPressBootstrapCleanupPreflight:
    return _preflight(session, page_id, request, "deletion", issue_handle, bound_expiry)


def _preflight(session, page_id, request, phase, issue_handle, bound_expiry):
    """Run the complete cleanup inspection without writing Atlas or WordPress."""
    _target(page_id)
    proof = _proof(request)
    evidence = request.manual_browser_evidence
    evidence_valid, evidence_reason = validate_manual_browser_evidence(
        evidence,
        os.getenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", ""),
    )
    evidence_valid = bool(evidence_valid and evidence and evidence.evidence_schema_version == 1)
    if evidence and evidence.evidence_schema_version != 1:
        evidence_reason = "Bootstrap cleanup requires fresh schema-v1 evidence."
    artifact, artifact_gates = _verify_artifact()
    bootstrap_artifact, bootstrap_artifact_gates = _verify_bootstrap_artifact()
    release_ok = any(g.code == "release_identity" and g.passed for g in artifact_gates)
    observed = _observe(session, proof) if evidence_valid and release_ok else _unavailable_observation(evidence_reason)
    plugin_status = _read_plugin_status(session) if observed.get("wordpress_request_performed") else {"_error": "observation_unavailable"}
    bootstrap_status = _read_bootstrap_status(session) if observed.get("wordpress_request_performed") else {"_error": "observation_unavailable"}
    routes = _read_route_registry(session) if observed.get("wordpress_request_performed") else {"routes": [], "_error": "observation_unavailable"}
    installation = session.get(WordPressDeploymentAudit, request.installation_audit_id)
    activation = session.get(WordPressActivationAudit, request.activation_audit_id)
    upgrade = session.get(WordPressPluginUpgradeAudit, request.upgrade_audit_id)
    installations = list(session.exec(select(WordPressDeploymentAudit)))
    activations = list(session.exec(select(WordPressActivationAudit)))
    upgrades = list(session.exec(select(WordPressPluginUpgradeAudit)))
    cleanup = session.get(WordPressBootstrapCleanupAudit, request.cleanup_audit_id) if phase == "deletion" else None
    cleanups = list(session.exec(select(WordPressBootstrapCleanupAudit)))
    lifecycle = list(session.exec(select(WordPressMetadataLifecycleAudit)))
    metadata_states = list(session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == 41)))
    metadata_audits = list(session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id == 41)))
    expected_post = _expected_after(observed, phase)
    gates = [
        *artifact_gates,
        *bootstrap_artifact_gates,
        *_backup_gates(proof),
        *_common_gates(
            request, installation, activation, upgrade, installations,
            activations, upgrades, cleanups, lifecycle,
            metadata_states, metadata_audits, observed, plugin_status,
            bootstrap_status, bootstrap_artifact, evidence_valid, evidence_reason,
        ),
    ]
    if phase == "deactivation":
        gates.extend(_deactivation_gates(observed, bootstrap_status, routes))
    else:
        gates.extend(_deletion_gates(request, cleanup, observed, bootstrap_status, routes))
    ready = all(g.passed for g in gates)
    expires_at = bound_expiry
    if ready and expires_at is None:
        expires_at = min(
            datetime.now(UTC) + CLEANUP_TTL,
            _evidence_expiry(evidence.expires_at),
            _backup_deadline(proof.wordpress_backup_completed_at),
        )
    binding = _binding(request, phase, observed, plugin_status, bootstrap_status, expected_post, expires_at, cleanup)
    binding_hash = _hash(binding)
    handle = fingerprint = None
    if ready and (not expires_at or expires_at <= datetime.now(UTC)):
        ready = False
        gates.append(_gate("cleanup_handle_lifetime", "Evidence and backup permit a positive handle lifetime", False, "Evidence or backup expires before cleanup can be authorized."))
    elif ready and issue_handle and expires_at:
        handle = _store_handle(phase, request, binding_hash, expires_at)
        fingerprint = hashlib.sha256(handle.encode()).hexdigest()
    phrase = DEACTIVATION_PHRASE if phase == "deactivation" else DELETION_PHRASE
    wordpress_scope = DEACTIVATION_WORDPRESS_SCOPE if phase == "deactivation" else DELETION_WORDPRESS_SCOPE
    atlas_scope = DEACTIVATION_ATLAS_SCOPE if phase == "deactivation" else DELETION_ATLAS_SCOPE
    return WordPressBootstrapCleanupPreflight(
        phase=phase,
        status="bootstrap_cleanup_preflight_ready" if ready else "bootstrap_cleanup_preflight_blocked",
        bootstrap_cleanup_preflight_ready=ready,
        cleanup_handle=handle,
        cleanup_handle_fingerprint=fingerprint,
        confirmation_phrase=phrase if ready else None,
        binding_hash=binding_hash if ready else None,
        expires_at=expires_at if ready else None,
        backup_deadline=_backup_deadline(proof.wordpress_backup_completed_at) if proof.wordpress_backup_completed_at.tzinfo else None,
        inspected_state={
            **_public_snapshot(observed, plugin_status, metadata_states, metadata_audits),
            "upgrade_bootstrap": _safe_bootstrap(bootstrap_status),
            "bootstrap_routes_present": _bootstrap_routes_present(routes),
            "cleanup_audit": _safe_cleanup(cleanup),
        },
        gate_results=gates,
        proposed_wordpress_write_scope=wordpress_scope if ready else [],
        proposed_atlas_write_scope=atlas_scope if ready else [],
        expected_post_plugin_inventory_hash=expected_post.get("plugin_inventory_hash") if ready else None,
        expected_post_active_plugin_inventory_hash=expected_post.get("active_plugin_inventory_hash") if ready else None,
    )


def deactivate_bootstrap(session: Session, page_id: int, request: WordPressBootstrapCleanupApplyRequest) -> WordPressBootstrapCleanupResult:
    _target(page_id)
    if not hmac.compare_digest(request.confirmation_phrase, DEACTIVATION_PHRASE):
        raise HTTPException(422, "The upgrade-bootstrap deactivation phrase is incorrect.")
    entry = _consume_handle(request.cleanup_handle, "deactivation")
    rerun = cleanup_preflight(session, page_id, entry.request, issue_handle=False, bound_expiry=entry.expires_at)
    if not rerun.bootstrap_cleanup_preflight_ready or rerun.binding_hash != entry.binding_hash:
        raise HTTPException(409, "Bootstrap cleanup state changed. Run a new token-free preflight.")
    evidence = entry.request.manual_browser_evidence
    fingerprint = hashlib.sha256(request.cleanup_handle.encode()).hexdigest()
    audit = WordPressBootstrapCleanupAudit(
        generated_page_id=41,
        wordpress_post_id=8,
        installation_audit_id=entry.request.installation_audit_id,
        activation_audit_id=entry.request.activation_audit_id,
        upgrade_audit_id=entry.request.upgrade_audit_id,
        status="pending",
        operator=entry.request.operator,
        bootstrap_slug=BOOTSTRAP_SLUG,
        bootstrap_path=BOOTSTRAP_ENTRY,
        bootstrap_version=BOOTSTRAP_VERSION,
        bootstrap_zip_sha256=BOOTSTRAP_ZIP_SHA256,
        bridge_version=TARGET_VERSION,
        deactivation_phrase_hash=hashlib.sha256(DEACTIVATION_PHRASE.encode()).hexdigest(),
        deletion_phrase_hash=hashlib.sha256(DELETION_PHRASE.encode()).hexdigest(),
        deactivation_handle_fingerprint=fingerprint,
        deactivation_binding_hash=entry.binding_hash,
        release_identity=entry.request.expected_runtime_identity.model_dump(mode="json"),
        backup_evidence=_proof(entry.request).model_dump(mode="json"),
        browser_evidence_id=evidence.evidence_id,
        browser_evidence_hashes=_evidence_hashes(evidence),
        pre_snapshot=rerun.inspected_state,
        previous_inventories=_inventories(rerun.inspected_state),
        metadata_rendering_state=_metadata_state(rerun.inspected_state),
        page_media_snapshots=_page_media_state(rerun.inspected_state),
        gate_results=[g.model_dump(mode="json") for g in rerun.gate_results],
        wordpress_write_scope=DEACTIVATION_WORDPRESS_SCOPE,
        atlas_write_scope=DEACTIVATION_ATLAS_SCOPE,
        transition_history=["pending"],
    )
    session.add(audit)
    session.commit()
    session.refresh(audit)
    response = _send_deactivation(session)
    audit.wordpress_write_count = 1
    if response.get("_error"):
        return _finalize_deactivation(session, audit, "failed", [
            _gate("deactivation_response", "WordPress accepted only the fixed bootstrap deactivation", False, str(response["_error"]))
        ], {"deactivation_response": response}, "siteground_restore")
    after = _observe(session, _proof(entry.request))
    plugin_status = _read_plugin_status(session)
    bootstrap_status = _read_bootstrap_status(session)
    routes = _read_route_registry(session)
    post_gates = _post_deactivation_gates(entry.request, rerun.inspected_state, after, plugin_status, bootstrap_status, routes)
    status = "deactivated" if all(g.passed for g in post_gates) else "verification_failed"
    recommendation = "no_action" if status == "deactivated" else _deactivation_recovery(after)
    snapshot = _snapshot(session, after, plugin_status, bootstrap_status, routes, response)
    return _finalize_deactivation(session, audit, status, post_gates, snapshot, recommendation)


def delete_bootstrap(session: Session, page_id: int, request: WordPressBootstrapCleanupApplyRequest) -> WordPressBootstrapCleanupResult:
    _target(page_id)
    if not hmac.compare_digest(request.confirmation_phrase, DELETION_PHRASE):
        raise HTTPException(422, "The upgrade-bootstrap deletion phrase is incorrect.")
    entry = _consume_handle(request.cleanup_handle, "deletion")
    rerun = deletion_preflight(session, page_id, entry.request, issue_handle=False, bound_expiry=entry.expires_at)
    if not rerun.bootstrap_cleanup_preflight_ready or rerun.binding_hash != entry.binding_hash:
        raise HTTPException(409, "Bootstrap deletion state changed. Run a new deletion preflight.")
    audit = session.get(WordPressBootstrapCleanupAudit, entry.request.cleanup_audit_id)
    if audit is None or audit.status != "deactivated":
        raise HTTPException(409, "A verified bootstrap deactivation audit is required.")
    audit.status = "pending"
    audit.deletion_handle_fingerprint = hashlib.sha256(request.cleanup_handle.encode()).hexdigest()
    audit.deletion_binding_hash = entry.binding_hash
    audit.transition_history = [*audit.transition_history, "pending"]
    audit.atlas_write_count += 1
    audit.wordpress_write_scope = [*audit.wordpress_write_scope, *DELETION_WORDPRESS_SCOPE]
    audit.atlas_write_scope = [*audit.atlas_write_scope, *DELETION_ATLAS_SCOPE]
    session.add(audit)
    session.commit()
    response = _send_deletion(session)
    audit.wordpress_write_count += 1
    if response.get("_error"):
        return _finalize_deletion(session, audit, "failed", [
            _gate("deletion_response", "WordPress accepted only the fixed inactive-bootstrap deletion", False, str(response["_error"]))
        ], {"deletion_response": response}, "siteground_restore")
    after = _observe(session, _proof(entry.request))
    plugin_status = _read_plugin_status(session)
    bootstrap_status = _read_bootstrap_status(session)
    routes = _read_route_registry(session)
    post_gates = _post_deletion_gates(entry.request, rerun.inspected_state, after, plugin_status, bootstrap_status, routes)
    status = "verified" if all(g.passed for g in post_gates) else "verification_failed"
    recommendation = "no_action" if status == "verified" else _deletion_recovery(after)
    snapshot = _snapshot(session, after, plugin_status, bootstrap_status, routes, response)
    return _finalize_deletion(session, audit, status, post_gates, snapshot, recommendation)


def _common_gates(request, installation, activation, upgrade, installations, activations, upgrades, cleanups, lifecycle, metadata_states, metadata_audits, observed, plugin_status, bootstrap_status, bootstrap_artifact, evidence_valid, evidence_reason):
    matches = _matching_reconciliation_plugins(observed.get("plugins", []))
    rendered = observed.get("rendered", {})
    page = observed.get("page", {})
    snapshot = plugin_status.get("snapshot", {}) if isinstance(plugin_status.get("snapshot"), dict) else plugin_status
    artifact, _ = _verify_artifact()
    expected_runtime = request.expected_runtime_identity.model_dump(mode="json")
    actual_runtime = {
        "atlas_version": artifact.get("atlas_version"),
        "atlas_commit": artifact.get("atlas_commit"),
        "atlas_tag": artifact.get("atlas_tag"),
        "manifest_sha256": artifact.get("release_manifest_sha256"),
        "source_compatibility_id": artifact.get("release_source_compatibility_id"),
    }
    unresolved_cleanup = [a for a in cleanups if a.status in {"pending", "verification_failed"}]
    unresolved_plugin_actions = [
        *[a for a in installations if a.status in {"pending", "authorized", "awaiting_manual_installation", "verification_failed"}],
        *[a for a in activations if a.status in {"pending", "verification_failed"}],
        *[a for a in upgrades if a.status in {"pending", "verification_failed"}],
    ]
    return [
        _gate("evidence_contract", "Fresh signed schema-v1 evidence is valid", evidence_valid, evidence_reason or "Fresh schema-v1 evidence required."),
        _gate("expected_runtime", "Expected runtime identity independently matches", expected_runtime == actual_runtime and artifact.get("release_runtime_identity_verified") is True and artifact.get("release_manifest_integrity_verified") is True and artifact.get("release_expected_identity_matched") is True, "Runtime identity changed."),
        _gate("repository_identity", "HEAD, origin/main, tag, and branch match", request.repository_head == request.repository_origin_main == request.expected_runtime_identity.atlas_commit and request.repository_tag == request.expected_runtime_identity.atlas_tag and request.repository_branch == "main", "Repository identity differs."),
        _gate("repository_clean", "Working tree is attested clean", request.repository_working_tree_clean, "Working tree is not clean."),
        _gate("protected_paths", "Protected paths are attested unchanged", request.protected_paths_unchanged, "Protected paths changed."),
        _gate("no_post_backup_change", "No relevant WordPress change followed the SiteGround backup", request.no_relevant_wordpress_change_after_backup, "A post-backup WordPress change requires a fresh backup."),
        _gate("installation_audit", "Installation audit 1 is verified", bool(installation and installation.id == 1 and installation.status == "verified"), "Verified installation audit 1 required."),
        _gate("activation_audit", "Activation audit 1 is verified", bool(activation and activation.id == 1 and activation.status == "verified"), "Verified activation audit 1 required."),
        _gate("upgrade_audit", "Selected 0.57.6 to 0.57.7 upgrade audit is verified", bool(upgrade and upgrade.id == request.upgrade_audit_id and upgrade.status == "verified" and upgrade.previous_version == "0.57.6" and upgrade.target_version == TARGET_VERSION and upgrade.recovery_recommendation == "no_action"), "Verified 0.57.6 to 0.57.7 upgrade audit required."),
        _gate("plugin_actions_clear", "No plugin installation, activation, or upgrade action is unresolved", not unresolved_plugin_actions, "A plugin action is unresolved."),
        _gate("cleanup_clear", "No unresolved bootstrap cleanup exists", not unresolved_cleanup, "A bootstrap cleanup is unresolved."),
        _gate("metadata_lifecycle_clear", "No metadata lifecycle action is pending", not any(a.status == "pending" for a in lifecycle), "Metadata lifecycle action is pending."),
        _gate("bridge_singleton", "Exactly one Metadata Bridge is installed", len(matches) == 1, "Metadata Bridge is missing or duplicated."),
        _gate("bridge_identity", "Metadata Bridge 0.57.7 identity is exact", len(matches) == 1 and matches[0].get("version") == request.expected_bridge_version == TARGET_VERSION and request.expected_bridge_slug == PLUGIN_SLUG and request.expected_bridge_path == PLUGIN_FILE and _normalize_plugin_identifier(matches[0].get("plugin")).authorized_entry_path == PLUGIN_FILE, "Metadata Bridge identity differs."),
        _gate("bridge_active", "Metadata Bridge remains active", len(matches) == 1 and matches[0].get("status") in {"active", "network-active"} and plugin_status.get("active") is True, "Metadata Bridge is inactive."),
        _gate("bridge_checksum", "Metadata Bridge executable matches 0.57.7", plugin_status.get("checksum") == artifact.get("plugin_source_sha256") and request.expected_bridge_zip_sha256 == artifact.get("zip_sha256"), "Metadata Bridge artifact differs."),
        _gate("plugin_inventory", "Current full-plugin inventory hash is exact", observed.get("plugin_inventory_hash") == request.expected_plugin_inventory_hash, "Plugin inventory changed."),
        _gate("active_inventory", "Current active-plugin inventory hash is exact", observed.get("active_plugin_inventory_hash") == request.expected_active_plugin_inventory_hash, "Active-plugin inventory changed."),
        _gate("metadata_rows", "Atlas metadata state and sync-audit rows remain exactly 1/0", len(metadata_states) == 1 and len(metadata_audits) == 0, "Metadata row counts changed."),
        _gate("metadata_state", "Atlas metadata state remains staged", len(metadata_states) == 1 and metadata_states[0].status == request.expected_metadata_state_status == "staged" and metadata_states[0].payload_hash == request.expected_payload_hash and str(metadata_states[0].wordpress_revision) == request.expected_revision == "1" and metadata_states[0].payload == snapshot.get("payload"), "Metadata state changed."),
        _gate("rendering_disabled", "Rendering remains disabled", snapshot.get("rendering_enabled") is False and snapshot.get("enabled_metadata_state") is False, "Rendering is enabled."),
        _gate("payload_preserved", "Staged payload and hash remain exact", isinstance(snapshot.get("payload"), dict) and snapshot.get("payload_hash") == request.expected_payload_hash, "Metadata payload changed."),
        _gate("revision_one", "Metadata revision remains one", str(snapshot.get("revision")) == request.expected_revision == "1", "Metadata revision changed."),
        _gate("rendered_state", "Public state is signed and unchanged", rendered.get("verified") is True and rendered.get("signature_validated") is True and rendered.get("h1") == [EXPECTED_H1] and _rendered_metadata_absent(rendered) and not rendered.get("atlas_metadata_marker_present", False), "Rendered state changed."),
        _gate("page_snapshot", "Page snapshot is exact", observed.get("page_snapshot_hash") == request.expected_page_snapshot_hash, "Page snapshot changed."),
        _gate("page_identity", "Page 8 identity remains exact", page.get("id") == 8 and page.get("status") == "publish" and page.get("slug") == "drywood-termite-tenting-orlando-fl" and page.get("featured_media") == 31, "Page identity changed."),
        _gate("body_hash", "Corrected body hash is exact", observed.get("page_body_hash") == request.expected_body_hash == EXPECTED_CORRECTED_BODY_HASH and observed.get("page_body_begins_expected_h2") is True, "Page body changed."),
        _gate("media31", "Media 31 snapshot is exact", observed.get("media31_snapshot_hash") == request.expected_media31_snapshot_hash, "Media 31 changed."),
        _gate("media32", "Media 32 remains unchanged and absent", observed.get("media32_snapshot_hash") == request.expected_media32_snapshot_hash and not observed.get("page_references_media32") and not rendered.get("media32_reference_present"), "Media 32 changed or rendered."),
        _gate("site_identity", "Site Title and Tagline remain exact", observed.get("site") == {"name": "My WordPress", "description": ""}, "Site identity changed."),
        _gate("php_findings", "PHP, REST, and header findings are clean", _clean_findings(request.php_error_log_findings), "PHP or REST findings require review."),
        _gate("browser_findings", "Browser-console and visible-site findings are clean", _clean_findings(request.browser_console_findings), "Browser findings require review."),
        _gate("cache_boundary", "No cache purge is observed", observed.get("cache_headers") == rendered.get("cache_headers", {}), "Cache observation changed."),
        _gate("bootstrap_artifact", "Approved bootstrap ZIP and executable are exact", request.expected_bootstrap_slug == BOOTSTRAP_SLUG and request.expected_bootstrap_path == BOOTSTRAP_ENTRY and request.expected_bootstrap_version == BOOTSTRAP_VERSION and request.expected_bootstrap_zip_sha256 == bootstrap_artifact.get("zip_sha256") == BOOTSTRAP_ZIP_SHA256 and bootstrap_artifact.get("entry_sha256") == BOOTSTRAP_ENTRY_SHA256, "Bootstrap artifact differs."),
        _gate("read_only_preflight", "Preflight uses WordPress GET requests only", observed.get("wordpress_request_methods") == ["GET"] and routes_get_only(bootstrap_status), "Preflight attempted a WordPress mutation."),
    ]


def _deactivation_gates(observed, bootstrap_status, routes):
    matches = _bootstrap_matches(observed)
    return [
        _gate("bootstrap_singleton", "Exactly one bootstrap is installed", len(matches) == 1, "Bootstrap is missing or duplicated."),
        _gate("bootstrap_identity", "Bootstrap version and path are exact", len(matches) == 1 and matches[0].get("version") == BOOTSTRAP_VERSION and _normalized_path(matches[0]) == BOOTSTRAP_ENTRY, "Bootstrap identity differs."),
        _gate("bootstrap_active", "Bootstrap is active before deactivation", len(matches) == 1 and matches[0].get("status") in {"active", "network-active"}, "Bootstrap is not active."),
        _gate("bootstrap_fail_closed", "Bootstrap status is authenticated and upgrade is unavailable", bootstrap_status.get("bootstrap") == BOOTSTRAP_SLUG and bootstrap_status.get("bootstrap_version") == BOOTSTRAP_VERSION and bootstrap_status.get("bootstrap_checksum") == BOOTSTRAP_ENTRY_SHA256 and bootstrap_status.get("available") is False and bootstrap_status.get("plugin", {}).get("version") == TARGET_VERSION, "Bootstrap is not the approved fail-closed helper."),
        _gate("bootstrap_routes", "Only the fixed bootstrap routes are present", _bootstrap_routes_present(routes), "Bootstrap route registry is unavailable."),
    ]


def _deletion_gates(request, cleanup, observed, bootstrap_status, routes):
    matches = _bootstrap_matches(observed)
    return [
        _gate("cleanup_audit", "Selected cleanup audit records verified deactivation", bool(cleanup and cleanup.id == request.cleanup_audit_id and cleanup.status == "deactivated" and cleanup.wordpress_write_count == 1 and cleanup.transition_history == ["pending", "deactivated"]), "Verified bootstrap deactivation audit required."),
        _gate("bootstrap_singleton", "Exactly one bootstrap remains installed", len(matches) == 1, "Bootstrap is missing or duplicated."),
        _gate("bootstrap_identity", "Inactive bootstrap version and path are exact", len(matches) == 1 and matches[0].get("version") == BOOTSTRAP_VERSION and _normalized_path(matches[0]) == BOOTSTRAP_ENTRY, "Bootstrap identity differs."),
        _gate("bootstrap_inactive", "Bootstrap is inactive before deletion", len(matches) == 1 and matches[0].get("status") == "inactive", "Bootstrap must be inactive before deletion."),
        _gate("bootstrap_endpoints_absent", "Inactive bootstrap REST endpoints are unavailable", bootstrap_status.get("status_code") in {404, 405} and not _bootstrap_routes_present(routes), "Bootstrap REST endpoints remain active."),
    ]


def _post_deactivation_gates(request, before, after, plugin_status, bootstrap_status, routes):
    matches = _bootstrap_matches(after)
    expected = _expected_after(before, "deactivation")
    return [
        _gate("bootstrap_singleton", "Bootstrap remains installed exactly once", len(matches) == 1, "Bootstrap files changed or disappeared."),
        _gate("bootstrap_inactive", "Bootstrap is inactive", len(matches) == 1 and matches[0].get("status") == "inactive", "Bootstrap remains active."),
        _gate("bootstrap_endpoints_absent", "Bootstrap REST endpoints are unavailable", bootstrap_status.get("status_code") in {404, 405} and not _bootstrap_routes_present(routes), "Bootstrap REST endpoints remain registered."),
        *_preservation_gates(request, before, after, plugin_status, expected),
    ]


def _post_deletion_gates(request, before, after, plugin_status, bootstrap_status, routes):
    expected = _expected_after(before, "deletion")
    return [
        _gate("bootstrap_absent", "Bootstrap inventory entry and directory are absent", not _bootstrap_matches(after), "Bootstrap remains installed."),
        _gate("bootstrap_endpoints_absent", "Bootstrap REST namespace is absent", bootstrap_status.get("status_code") in {404, 405} and not _bootstrap_routes_present(routes), "Bootstrap REST namespace remains registered."),
        _gate("lifecycle_routes", "Separated metadata lifecycle routes remain registered", LIFECYCLE_ROUTES <= set(routes.get("routes", [])), "Separated lifecycle routes are missing."),
        _gate("legacy_route_disabled", "Legacy combined metadata route remains HTTP 410-disabled", routes.get("legacy_route_registered") is True and _target_artifact_disables_legacy_route(), "Legacy route contract changed."),
        *_preservation_gates(request, before, after, plugin_status, expected),
    ]


def _preservation_gates(request, before, after, plugin_status, expected):
    matches = _matching_reconciliation_plugins(after.get("plugins", []))
    rendered = after.get("rendered", {})
    snapshot = plugin_status.get("snapshot", {}) if isinstance(plugin_status.get("snapshot"), dict) else plugin_status
    return [
        _gate("bridge_singleton", "Metadata Bridge remains installed once", len(matches) == 1 and matches[0].get("version") == TARGET_VERSION, "Metadata Bridge changed."),
        _gate("bridge_active", "Metadata Bridge remains active", len(matches) == 1 and matches[0].get("status") in {"active", "network-active"} and plugin_status.get("active") is True, "Metadata Bridge became inactive."),
        _gate("plugin_inventory", "Only the authorized bootstrap state changed", after.get("plugin_inventory_hash") == expected.get("plugin_inventory_hash"), "Full plugin inventory delta differs."),
        _gate("active_inventory", "Active-plugin inventory delta is exact", after.get("active_plugin_inventory_hash") == expected.get("active_plugin_inventory_hash"), "Active-plugin inventory delta differs."),
        _gate("unrelated_plugins", "No unrelated plugin changed", _plugins_without_targets(after) == _plugins_without_targets(before), "An unrelated plugin changed."),
        _gate("rendering_disabled", "Rendering remains disabled", snapshot.get("rendering_enabled") is False and snapshot.get("enabled_metadata_state") is False, "Rendering changed."),
        _gate("payload_preserved", "Staged payload and hash remain exact", snapshot.get("payload") == before.get("plugin_status", {}).get("snapshot", {}).get("payload") and snapshot.get("payload_hash") == request.expected_payload_hash, "Metadata payload changed."),
        _gate("revision_one", "Metadata revision remains one", str(snapshot.get("revision")) == request.expected_revision == "1", "Metadata revision changed."),
        _gate("page_snapshot", "Page remains unchanged", after.get("page_snapshot_hash") == before.get("page_snapshot_hash") == request.expected_page_snapshot_hash, "Page changed."),
        _gate("body_hash", "Body remains unchanged", after.get("page_body_hash") == before.get("page_body_hash") == request.expected_body_hash, "Body changed."),
        _gate("media31", "Media 31 remains unchanged", after.get("media31_snapshot_hash") == before.get("media31_snapshot_hash") == request.expected_media31_snapshot_hash, "Media 31 changed."),
        _gate("media32", "Media 32 remains unchanged and absent", after.get("media32_snapshot_hash") == before.get("media32_snapshot_hash") == request.expected_media32_snapshot_hash and not after.get("page_references_media32") and not rendered.get("media32_reference_present"), "Media 32 changed or rendered."),
        _gate("site_identity", "Site Title and Tagline remain unchanged", after.get("site") == before.get("site") == {"name": "My WordPress", "description": ""}, "Site identity changed."),
        _gate("rendered_metadata", "No Atlas metadata renders", rendered.get("verified") is True and _rendered_metadata_absent(rendered) and not rendered.get("atlas_metadata_marker_present", False), "Atlas metadata rendered."),
        _gate("cache_boundary", "No cache purge occurred", after.get("cache_headers") == before.get("cache_headers"), "Cache observation changed."),
        _gate("read_only_verification", "Post-write verification uses GET requests only", after.get("wordpress_request_methods") == ["GET"], "Verification attempted another WordPress write."),
    ]


def _send_deactivation(session):
    return _fixed_plugin_request(session, "POST", {"status": "inactive"})


def _send_deletion(session):
    return _fixed_plugin_request(session, "DELETE", None)


def _fixed_plugin_request(session, method, body):
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password):
        return {"_error": "credentials_unavailable"}
    path = f"/wp-json/wp/v2/plugins/{BOOTSTRAP_SLUG}/{BOOTSTRAP_SLUG}"
    try:
        with wordpress_http_client(settings.site_url, timeout=30, follow_redirects=False, client_factory=httpx.Client) as client:
            request_kwargs = {
                "auth": wordpress_basic_auth(settings.username, password),
                "headers": {"Cache-Control": "no-cache", "Pragma": "no-cache"},
            }
            if body is not None:
                request_kwargs["json"] = body
            response = client.request(
                method,
                f"{settings.site_url.rstrip('/')}{path}",
                **request_kwargs,
            )
        payload = response.json() if response.status_code < 400 else {}
        if response.status_code >= 400 or not isinstance(payload, dict):
            return {"_error": f"HTTP {response.status_code}", "status_code": response.status_code}
        if method == "POST":
            accepted = payload.get("status") == "inactive" and _normalized_path(payload) == BOOTSTRAP_ENTRY
        else:
            previous = payload.get("previous") if isinstance(payload.get("previous"), dict) else {}
            accepted = payload.get("deleted") is True and _normalized_path(previous) == BOOTSTRAP_ENTRY
        return {"status_code": response.status_code, "accepted": accepted, "method": method, "_error": None if accepted else "fixed_response_unconfirmed"}
    except (httpx.HTTPError, ValueError) as exc:
        return {"_error": exc.__class__.__name__, "method": method}


def _expected_after(observed, phase):
    plugins = deepcopy(observed.get("plugins", []))
    matches = [p for p in plugins if _normalized_path(p) == BOOTSTRAP_ENTRY]
    if len(matches) != 1:
        return {}
    active = sorted(observed.get("active_plugins", []))
    identifier = matches[0].get("plugin")
    if phase == "deactivation":
        matches[0]["status"] = "inactive"
        active = [p for p in active if _normalized_path(p) != BOOTSTRAP_ENTRY]
    else:
        plugins = [p for p in plugins if _normalized_path(p) != BOOTSTRAP_ENTRY]
    return {"plugin_inventory_hash": _hash(plugins), "active_plugin_inventory_hash": _hash(active)}


def _binding(request, phase, observed, plugin_status, bootstrap_status, expected_post, expires_at, cleanup):
    evidence = request.manual_browser_evidence
    return {
        "action": f"{phase}_upgrade_bootstrap",
        "targets": {"page": 41, "post": 8, "installation_audit": 1, "activation_audit": 1, "upgrade_audit": 1, "cleanup_audit": cleanup.id if cleanup else None},
        "runtime": request.expected_runtime_identity.model_dump(mode="json"),
        "repository": {"head": request.repository_head, "origin_main": request.repository_origin_main, "tag": request.repository_tag, "branch": request.repository_branch, "clean": request.repository_working_tree_clean, "protected": request.protected_paths_unchanged},
        "backup": _proof(request).model_dump(mode="json", exclude={"manual_browser_evidence"}),
        "bootstrap": {"slug": BOOTSTRAP_SLUG, "path": BOOTSTRAP_ENTRY, "version": BOOTSTRAP_VERSION, "zip_sha256": BOOTSTRAP_ZIP_SHA256, "status": _safe_bootstrap(bootstrap_status)},
        "bridge": {"version": TARGET_VERSION, "status": plugin_status.get("snapshot", plugin_status)},
        "before": _inventories(observed) | _page_media_state(observed),
        "expected_after": expected_post,
        "evidence": {"id": evidence.evidence_id if evidence else None, "head": evidence.rendered_head_hash if evidence else None, "visible": evidence.visible_content_hash if evidence else None, "expires": str(evidence.expires_at) if evidence else None},
        "handle_expires_at": expires_at.isoformat() if expires_at else None,
    }


def _store_handle(phase, request, binding_hash, expires_at):
    handle = secrets.token_urlsafe(48)
    entry = _CleanupHandleEntry(phase=phase, request=request, binding_hash=binding_hash, issued_at=datetime.now(UTC), expires_at=expires_at)
    with _handle_lock:
        _handles[handle] = entry
        timer = Timer(max(0.0, (expires_at - datetime.now(UTC)).total_seconds()), _expire_handle, args=(handle,))
        timer.daemon = True
        _handle_timers[handle] = timer
        timer.start()
    return handle


def _consume_handle(handle, expected_phase):
    with _handle_lock:
        entry = _handles.pop(handle, None)
        timer = _handle_timers.pop(handle, None)
        generation = _cleared_generation
    if timer:
        timer.cancel()
    if entry is None:
        reason = "invalidated by restart" if generation else "unknown, expired, or consumed"
        raise HTTPException(409, f"Bootstrap cleanup handle is {reason}.")
    if entry.phase != expected_phase:
        raise HTTPException(409, "Bootstrap cleanup handle is bound to another action.")
    if entry.expires_at <= datetime.now(UTC):
        raise HTTPException(409, "Bootstrap cleanup handle expired.")
    return entry


def _expire_handle(handle):
    with _handle_lock:
        _handles.pop(handle, None)
        _handle_timers.pop(handle, None)


def _clear_cleanup_handles():
    global _cleared_generation
    with _handle_lock:
        for timer in _handle_timers.values():
            timer.cancel()
        _handles.clear()
        _handle_timers.clear()
        _cleared_generation += 1


def _finalize_deactivation(session, audit, status, gates, snapshot, recommendation):
    audit.status = status
    audit.deactivated_snapshot = snapshot
    audit.deactivated_inventories = _inventories(snapshot)
    audit.gate_results = [g.model_dump(mode="json") for g in gates]
    audit.verification_findings = {"failed_gates": [g.code for g in gates if not g.passed]}
    audit.recovery_recommendation = recommendation
    audit.atlas_write_count = 2
    audit.transition_history = [*audit.transition_history, status]
    audit.deactivated_at = datetime.now(UTC) if status == "deactivated" else None
    if status in {"failed", "verification_failed"}:
        audit.completed_at = datetime.now(UTC)
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return _result(audit, "deactivation", status, gates, snapshot, DEACTIVATION_WORDPRESS_SCOPE, DEACTIVATION_ATLAS_SCOPE, 1, 2)


def _finalize_deletion(session, audit, status, gates, snapshot, recommendation):
    audit.status = status
    audit.final_snapshot = snapshot
    audit.final_inventories = _inventories(snapshot)
    audit.gate_results = [g.model_dump(mode="json") for g in gates]
    audit.verification_findings = {"failed_gates": [g.code for g in gates if not g.passed]}
    audit.recovery_recommendation = recommendation
    audit.atlas_write_count += 1
    audit.transition_history = [*audit.transition_history, status]
    audit.completed_at = datetime.now(UTC)
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return _result(audit, "deletion", status, gates, snapshot, DELETION_WORDPRESS_SCOPE, DELETION_ATLAS_SCOPE, 1, 2)


def _result(audit, phase, status, gates, snapshot, wordpress_scope, atlas_scope, wordpress_writes, atlas_writes):
    return WordPressBootstrapCleanupResult(
        cleanup_audit_id=audit.id or 0,
        phase=phase,
        status=status,
        binding_hash=audit.deactivation_binding_hash if phase == "deactivation" else audit.deletion_binding_hash or "",
        state_history=audit.transition_history,
        gate_results=gates,
        inspected_state=snapshot,
        wordpress_write_count=wordpress_writes,
        wordpress_write_scope=wordpress_scope,
        atlas_write_count=atlas_writes,
        atlas_write_scope=atlas_scope,
        recovery_recommendation=audit.recovery_recommendation,
        further_action_required=status not in {"deactivated", "verified"},
    )


def _snapshot(session, observed, plugin_status, bootstrap_status, routes, response):
    return {
        **_public_snapshot(
            observed,
            plugin_status,
            list(session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == 41))),
            list(session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id == 41))),
        ),
        "upgrade_bootstrap": _safe_bootstrap(bootstrap_status),
        "bootstrap_routes_present": _bootstrap_routes_present(routes),
        "route_registry": {"legacy_route_registered": routes.get("legacy_route_registered"), "request_method": routes.get("request_method"), "status_code": routes.get("status_code")},
        "fixed_wordpress_response": response,
    }


def _safe_bootstrap(value):
    if not isinstance(value, dict):
        return {"_error": "invalid_bootstrap_status"}
    allowed = {
        "bootstrap", "bootstrap_version", "bootstrap_checksum", "operation",
        "application_password_compatible", "target_plugin", "current_version",
        "target_version", "target_zip", "target_zip_sha256", "available",
        "plugin", "status_code", "request_method", "_error",
    }
    return {key: value.get(key) for key in allowed if key in value}


def _safe_cleanup(audit):
    return None if audit is None else {"id": audit.id, "status": audit.status, "transition_history": audit.transition_history, "wordpress_write_count": audit.wordpress_write_count}


def _bootstrap_matches(observed):
    return [p for p in observed.get("plugins", []) if _normalized_path(p) == BOOTSTRAP_ENTRY]


def _normalized_path(plugin):
    value = plugin.get("plugin") if isinstance(plugin, dict) else plugin
    if value in {BOOTSTRAP_ENTRY, BOOTSTRAP_ENTRY.removesuffix(".php")}:
        return BOOTSTRAP_ENTRY
    return _normalize_plugin_identifier(value).authorized_entry_path if value else ""


def _bootstrap_routes_present(routes):
    values = set(routes.get("routes", [])) if isinstance(routes, dict) else set()
    return BOOTSTRAP_STATUS_ROUTE in values and BOOTSTRAP_UPGRADE_ROUTE in values


def routes_get_only(status):
    return status.get("request_method") in {"GET", None}


def _plugins_without_targets(observed):
    return [p for p in observed.get("plugins", []) if _normalized_path(p) not in {BOOTSTRAP_ENTRY, PLUGIN_FILE}]


def _inventories(snapshot):
    return {"plugins": snapshot.get("plugin_inventory_hash"), "active_plugins": snapshot.get("active_plugin_inventory_hash")}


def _evidence_hashes(evidence):
    return {"rendered_head": evidence.rendered_head_hash, "visible_content": evidence.visible_content_hash, "metadata_inventory": evidence.metadata_inventory_hash}


def _deactivation_recovery(observed):
    matches = _bootstrap_matches(observed)
    if len(matches) == 1 and matches[0].get("status") == "inactive":
        return "no_action"
    if len(matches) == 1:
        return "guarded_reactivation"
    return "siteground_restore"


def _deletion_recovery(observed):
    matches = _bootstrap_matches(observed)
    if not matches:
        return "no_action"
    if len(matches) == 1:
        return "guarded_reinstall"
    return "siteground_restore"
