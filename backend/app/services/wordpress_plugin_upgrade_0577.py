"""Strict Metadata Bridge 0.57.6 to 0.57.7 guarded upgrade profile."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
from threading import Lock, Timer
from typing import Any
import zipfile

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    WordPressActivationAudit,
    WordPressBootstrapCleanupAudit,
    WordPressBootstrapEstablishmentAudit,
    WordPressDeploymentAudit,
    WordPressMetadataLifecycleAudit,
    WordPressMetadataState,
    WordPressMetadataSyncAudit,
    WordPressPluginUpgradeAudit,
)
from app.schemas.wordpress import (
    WordPressDeploymentBackupEvidence,
    WordPressDraftGateResult,
    WordPressPluginUpgradeApplyRequest,
    WordPressPluginUpgradePreflight,
    WordPressPluginUpgradePreflightRequest,
    WordPressPluginUpgradeRecoveryAssessment,
    WordPressPluginUpgradeRecoveryRequest,
    WordPressPluginUpgradeResult,
)
from app.services.wordpress_activation import _read_plugin_status
from app.services.wordpress_deployment import (
    EXPECTED_CORRECTED_BODY_HASH,
    PLUGIN_FILE,
    PLUGIN_SLUG,
    SOURCE_SHA256,
    ZIP_NAME,
    ZIP_SHA256,
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
    _verify_artifact,
)
from app.services.wordpress_deployment_release import release_paths, resolve_program_root
from app.services.wordpress_rendered_state import EXPECTED_H1, validate_manual_browser_evidence
from app.services.wordpress_sandbox import get_wordpress_application_password, read_wordpress_settings


CURRENT_VERSION = "0.57.6"
CURRENT_ZIP_NAME = "project-atlas-metadata-bridge-0.57.6.zip"
CURRENT_ZIP_SHA256 = "3b2d0035f995c3006e0d3be02596bd2cf19ef7e4a97572168621beb7a9abf788"
TARGET_VERSION = "0.57.7"
UPGRADE_PHRASE = "UPGRADE PROJECT ATLAS METADATA BRIDGE TO 0.57.7"
UPGRADE_TTL = timedelta(minutes=10)
BOOTSTRAP_VERSION = "0.3.0"
BOOTSTRAP_STATUS_ROUTE = "/project-atlas-deployment/v1/metadata-bridge/upgrade-0577/status"
BOOTSTRAP_UPGRADE_ROUTE = "/project-atlas-deployment/v1/metadata-bridge/upgrade-0577"
BOOTSTRAP_ZIP_NAME = "project-atlas-upgrade-bootstrap-0.3.0.zip"
BOOTSTRAP_ZIP_SHA256 = "de5bfb7875b6f84f2009ef2043c1c86c7f9d20f0f973a5cb16b478fe37e83bef"
BOOTSTRAP_ENTRY_SHA256 = "a977c077573ab732213a06d17dcc317b09854564777ce9cb24c869383972cd53"
UPGRADE_WORDPRESS_SCOPE = [
    f"POST /wp-json{BOOTSTRAP_UPGRADE_ROUTE}",
    f"multipart artifact fixed to {ZIP_NAME} and SHA-256 {ZIP_SHA256}",
    "single-purpose bootstrap replaces only the existing bridge; active status is preserved",
]
UPGRADE_ATLAS_SCOPE = [
    "create one pending WordPressPluginUpgradeAudit before the WordPress request",
    "finalize only that WordPressPluginUpgradeAudit after read-only verification",
]
LIFECYCLE_ROUTES = {
    "/project-atlas/v2/pages/8/metadata/stage",
    "/project-atlas/v2/pages/8/metadata/rendering/enable",
    "/project-atlas/v2/pages/8/metadata/rendering/disable",
    "/project-atlas/v2/pages/8/metadata/stage/rollback",
}
PREVIEW_ROUTE = "/project-atlas/v3/pages/8/metadata/rendering/preview"
CACHE_PURGE_ROUTE = "/project-atlas/v3/pages/8/cache/siteground/purge"
EXPECTED_PAYLOAD_HASH = "fe24398ee322ca8557814feb034a0ccff0302d5d26b6ea47b11001567854711d"
LEGACY_ROUTE = "/project-atlas/v1/pages/8/metadata"


@dataclass(frozen=True)
class _UpgradeHandleEntry:
    request: WordPressPluginUpgradePreflightRequest
    binding_hash: str
    issued_at: datetime
    expires_at: datetime


_handle_lock = Lock()
_handles: dict[str, _UpgradeHandleEntry] = {}
_handle_timers: dict[str, Timer] = {}


def plugin_upgrade_preflight(
    session: Session,
    page_id: int,
    request: WordPressPluginUpgradePreflightRequest,
    *,
    issue_handle: bool = True,
    bound_expiry: datetime | None = None,
) -> WordPressPluginUpgradePreflight:
    """Run the complete upgrade inspection without persisting or mutating anything."""
    _target(page_id)
    proof = _proof(request)
    evidence = request.manual_browser_evidence
    evidence_valid, evidence_reason = validate_manual_browser_evidence(
        evidence,
        __import__("os").environ.get("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", ""),
    )
    evidence_valid = bool(evidence_valid and evidence and evidence.evidence_schema_version == 1)
    if evidence and evidence.evidence_schema_version != 1:
        evidence_reason = "Plugin upgrade requires fresh schema-v1 evidence."
    artifact, artifact_gates = _verify_artifact()
    current_artifact, current_artifact_gates = _verify_current_artifact()
    bootstrap_artifact, bootstrap_artifact_gates = _verify_bootstrap_artifact()
    release_ok = any(g.code == "release_identity" and g.passed for g in artifact_gates)
    observed = _observe(session, proof) if evidence_valid and release_ok else _unavailable_observation(evidence_reason)
    plugin_status = _read_plugin_status(session) if observed.get("wordpress_request_performed") else {"_error": "observation_unavailable"}
    bootstrap_status = _read_bootstrap_status(session) if observed.get("wordpress_request_performed") else {"_error": "observation_unavailable"}
    installation = session.get(WordPressDeploymentAudit, request.installation_audit_id)
    activation = session.get(WordPressActivationAudit, request.activation_audit_id)
    prior_upgrades = list(session.exec(select(WordPressPluginUpgradeAudit)))
    cleanup_audits = list(session.exec(select(WordPressBootstrapCleanupAudit)))
    establishment_audits = list(session.exec(select(WordPressBootstrapEstablishmentAudit)))
    lifecycle = list(session.exec(select(WordPressMetadataLifecycleAudit)))
    metadata_states = list(session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == 41)))
    metadata_audits = list(session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id == 41)))
    expected_post = _expected_post_upgrade(observed)
    gates = [
        *artifact_gates,
        *current_artifact_gates,
        *bootstrap_artifact_gates,
        *_backup_gates(proof),
        *_upgrade_gates(
            request, installation, activation, prior_upgrades, cleanup_audits, establishment_audits, lifecycle,
            metadata_states, metadata_audits, observed, plugin_status,
            bootstrap_status, bootstrap_artifact, artifact, current_artifact, expected_post, evidence_valid,
            evidence_reason,
        ),
    ]
    ready = all(gate.passed for gate in gates)
    expires_at = bound_expiry
    if ready and expires_at is None:
        expires_at = min(
            datetime.now(UTC) + UPGRADE_TTL,
            _evidence_expiry(evidence.expires_at),
            _backup_deadline(proof.wordpress_backup_completed_at),
        )
    binding = _binding(
        request, installation, activation, observed, plugin_status, bootstrap_status,
        artifact, current_artifact, expected_post, expires_at,
    )
    binding_hash = _hash(binding)
    handle = fingerprint = None
    if ready and (not expires_at or expires_at <= datetime.now(UTC)):
        ready = False
        gates.append(_gate("upgrade_handle_lifetime", "Evidence and backup permit a positive handle lifetime", False, "Evidence or backup expires before the upgrade can be authorized."))
    elif ready and issue_handle and expires_at:
        handle = _store_handle(request, binding_hash, expires_at)
        fingerprint = hashlib.sha256(handle.encode()).hexdigest()
    return WordPressPluginUpgradePreflight(
        status="plugin_upgrade_preflight_ready" if ready else "plugin_upgrade_preflight_blocked",
        plugin_upgrade_preflight_ready=ready,
        upgrade_handle=handle,
        upgrade_handle_fingerprint=fingerprint,
        confirmation_phrase=UPGRADE_PHRASE if ready else None,
        binding_hash=binding_hash if ready else None,
        expires_at=expires_at if ready else None,
        backup_deadline=_backup_deadline(proof.wordpress_backup_completed_at) if proof.wordpress_backup_completed_at.tzinfo else None,
        current_version=CURRENT_VERSION,
        target_version=TARGET_VERSION,
        artifact={
            **artifact,
            "current_artifact": current_artifact,
            "upgrade_bootstrap_artifact": bootstrap_artifact,
        },
        inspected_state={
            **_public_snapshot(observed, plugin_status, metadata_states, metadata_audits),
            "upgrade_bootstrap": _safe_bootstrap_status(bootstrap_status),
        },
        gate_results=gates,
        proposed_wordpress_write_scope=UPGRADE_WORDPRESS_SCOPE if ready else [],
        proposed_atlas_write_scope=UPGRADE_ATLAS_SCOPE if ready else [],
        expected_post_plugin_inventory_hash=expected_post.get("plugin_inventory_hash") if ready else None,
        expected_post_active_plugin_inventory_hash=expected_post.get("active_plugin_inventory_hash") if ready else None,
    )


def apply_plugin_upgrade(
    session: Session,
    page_id: int,
    request: WordPressPluginUpgradeApplyRequest,
) -> WordPressPluginUpgradeResult:
    """Consume one handle and invoke the one fixed bootstrap REST request."""
    _target(page_id)
    if not hmac.compare_digest(request.confirmation_phrase, UPGRADE_PHRASE):
        raise HTTPException(422, "The Metadata Bridge upgrade phrase is incorrect.")
    entry = _consume_handle(request.upgrade_handle)
    rerun = plugin_upgrade_preflight(
        session, page_id, entry.request, issue_handle=False, bound_expiry=entry.expires_at,
    )
    if not rerun.plugin_upgrade_preflight_ready or rerun.binding_hash != entry.binding_hash:
        raise HTTPException(409, "Plugin upgrade state changed. Run a new token-free preflight.")
    evidence = entry.request.manual_browser_evidence
    handle_fingerprint = hashlib.sha256(request.upgrade_handle.encode()).hexdigest()
    audit = WordPressPluginUpgradeAudit(
        generated_page_id=41,
        wordpress_post_id=8,
        installation_audit_id=entry.request.installation_audit_id,
        activation_audit_id=entry.request.activation_audit_id,
        status="pending",
        operator=entry.request.operator,
        confirmation_phrase_hash=hashlib.sha256(UPGRADE_PHRASE.encode()).hexdigest(),
        handle_fingerprint=handle_fingerprint,
        binding_hash=entry.binding_hash,
        previous_version=CURRENT_VERSION,
        target_version=TARGET_VERSION,
        previous_artifact_sha256=CURRENT_ZIP_SHA256,
        target_artifact_sha256=ZIP_SHA256,
        release_identity=entry.request.expected_runtime_identity.model_dump(mode="json"),
        backup_evidence=_proof(entry.request).model_dump(mode="json"),
        browser_evidence_id=evidence.evidence_id,
        browser_evidence_hashes={
            "rendered_head": evidence.rendered_head_hash,
            "visible_content": evidence.visible_content_hash,
            "metadata_inventory": evidence.metadata_inventory_hash,
        },
        pre_snapshot=rerun.inspected_state,
        previous_inventories={
            "plugins": entry.request.expected_plugin_inventory_hash,
            "active_plugins": entry.request.expected_active_plugin_inventory_hash,
        },
        metadata_rendering_state=_metadata_state(rerun.inspected_state),
        page_media_snapshots=_page_media_state(rerun.inspected_state),
        gate_results=[gate.model_dump(mode="json") for gate in rerun.gate_results],
        wordpress_write_scope=UPGRADE_WORDPRESS_SCOPE,
        atlas_write_scope=UPGRADE_ATLAS_SCOPE,
        transition_history=["pending"],
    )
    session.add(audit)
    session.commit()
    session.refresh(audit)
    response = _send_fixed_upgrade(session)
    audit.wordpress_write_count = 1
    if response.get("_error"):
        return _finalize(session, audit, "failed", [
            _gate("upgrade_response", "WordPress accepted the fixed artifact replacement", False, str(response["_error"]))
        ], {"upgrade_response": response}, "siteground_restore")
    observed = _observe(session, _proof(entry.request))
    plugin_status = _read_plugin_status(session)
    bootstrap_status = _read_bootstrap_status(session)
    routes = _read_route_registry(session)
    preview = _read_disabled_preview_contract(session)
    metadata_states = list(session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == 41)))
    metadata_audits = list(session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id == 41)))
    post_gates = _post_upgrade_gates(entry.request, rerun.inspected_state, observed, plugin_status, bootstrap_status, routes, preview, metadata_states, metadata_audits)
    status = "verified" if all(g.passed for g in post_gates) else "verification_failed"
    recommendation = "no_action" if status == "verified" else _recovery_recommendation(observed, plugin_status)
    snapshot = {
        **_public_snapshot(
            observed, plugin_status,
            list(session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == 41))),
            list(session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id == 41))),
        ),
        "route_registry": routes,
        "disabled_preview_contract": preview,
        "upgrade_bootstrap": _safe_bootstrap_status(bootstrap_status),
        "upgrade_response": _safe_upgrade_response(response),
    }
    return _finalize(session, audit, status, post_gates, snapshot, recommendation)


def assess_plugin_upgrade_recovery(
    session: Session,
    page_id: int,
    request: WordPressPluginUpgradeRecoveryRequest,
) -> WordPressPluginUpgradeRecoveryAssessment:
    """Read-only recovery guidance. It never downgrades or restores."""
    _target(page_id)
    audit = session.get(WordPressPluginUpgradeAudit, request.upgrade_audit_id)
    observed = _observe(session, _proof(request))
    plugin_status = _read_plugin_status(session) if observed.get("wordpress_request_performed") else {"_error": "observation_unavailable"}
    gates = [
        _gate("upgrade_audit", "Selected upgrade audit exists", audit is not None, "Upgrade audit not found."),
        _gate("read_only", "Recovery assessment used GET-only observation", observed.get("wordpress_request_methods") == ["GET"], "Recovery observation unavailable."),
    ]
    recommendation = _recovery_recommendation(observed, plugin_status) if audit else "siteground_restore"
    if audit and audit.status == "verified":
        recommendation = "no_action"
    return WordPressPluginUpgradeRecoveryAssessment(
        upgrade_audit_id=request.upgrade_audit_id,
        status="recovery_assessment_complete" if all(g.passed for g in gates) else "recovery_assessment_blocked",
        recommendation=recommendation,
        gate_results=gates,
        inspected_state=_public_snapshot(observed, plugin_status, [], []),
    )


def _upgrade_gates(request, installation, activation, prior_upgrades, cleanup_audits, establishment_audits, lifecycle, metadata_states, metadata_audits, observed, plugin_status, bootstrap_status, bootstrap_artifact, artifact, current_artifact, expected_post, evidence_valid, evidence_reason):
    matches = _matching_reconciliation_plugins(observed.get("plugins", []))
    rendered = observed.get("rendered", {})
    page = observed.get("page", {})
    status_snapshot = plugin_status.get("snapshot", {}) if isinstance(plugin_status.get("snapshot"), dict) else plugin_status
    expected_runtime = request.expected_runtime_identity.model_dump(mode="json")
    actual_runtime = {
        "atlas_version": artifact.get("atlas_version"),
        "atlas_commit": artifact.get("atlas_commit"),
        "atlas_tag": artifact.get("atlas_tag"),
        "manifest_sha256": artifact.get("release_manifest_sha256"),
        "source_compatibility_id": artifact.get("release_source_compatibility_id"),
    }
    previous_upgrade = next((audit for audit in prior_upgrades if audit.id == request.previous_upgrade_audit_id), None)
    cleanup = next((audit for audit in cleanup_audits if audit.id == request.bootstrap_cleanup_audit_id), None)
    staging = next((audit for audit in lifecycle if audit.id == request.staging_audit_id), None)
    recovery_disable = next((audit for audit in lifecycle if audit.id == request.recovery_disable_audit_id), None)
    establishment = max(establishment_audits, key=lambda item: item.id or 0, default=None)
    state = metadata_states[0] if len(metadata_states) == 1 else None
    unresolved = [audit for audit in prior_upgrades if audit.status in {"pending", "verification_failed"}]
    pending_lifecycle = [audit for audit in lifecycle if audit.status == "pending"]
    return [
        _gate("evidence_contract", "Fresh signed schema-v1 evidence is valid", evidence_valid, evidence_reason or "Fresh schema-v1 evidence required."),
        _gate("expected_runtime", "Expected runtime identity independently matches", expected_runtime == actual_runtime and artifact.get("release_runtime_identity_verified") is True and artifact.get("release_manifest_integrity_verified") is True and artifact.get("release_expected_identity_matched") is True, "Runtime identity changed."),
        _gate("repository_identity", "HEAD, origin/main, tag, and branch match", request.repository_head == request.repository_origin_main == request.expected_runtime_identity.atlas_commit and request.repository_tag == request.expected_runtime_identity.atlas_tag and request.repository_branch == "main", "Repository identity differs."),
        _gate("repository_clean", "Working tree is attested clean", request.repository_working_tree_clean, "Working tree is not clean."),
        _gate("protected_paths", "Protected paths are attested unchanged", request.protected_paths_unchanged, "Protected paths changed."),
        _gate("no_post_backup_change", "No relevant WordPress change followed the SiteGround backup", request.no_relevant_wordpress_change_after_backup, "A post-backup WordPress change requires a fresh backup."),
        _gate("installation_audit", "Installation audit 1 is verified", bool(installation and installation.id == 1 and installation.status == "verified"), "Verified installation audit 1 required."),
        _gate("activation_audit", "Activation audit 1 is verified", bool(activation and activation.id == 1 and activation.status == "verified"), "Verified activation audit 1 required."),
        _gate("previous_upgrade_audit", "The 0.57.5 to 0.57.6 upgrade audit is verified", bool(previous_upgrade and previous_upgrade.status == "verified" and previous_upgrade.previous_version == "0.57.5" and previous_upgrade.target_version == CURRENT_VERSION and previous_upgrade.recovery_recommendation == "no_action"), "Verified prior bridge-upgrade audit required."),
        _gate("bootstrap_cleanup_audit", "The bootstrap 0.2.0 cleanup audit is verified", bool(cleanup and cleanup.status == "verified" and cleanup.bootstrap_version == "0.2.0" and cleanup.bridge_version == CURRENT_VERSION), "Verified prior bootstrap-cleanup audit required."),
        _gate("staging_audit", "Staging audit 2 is verified for the exact payload", bool(staging and staging.action_type == "stage_metadata_payload" and staging.status == "verified" and staging.payload_hash == request.expected_payload_hash == EXPECTED_PAYLOAD_HASH and str(staging.final_revision) == "1" and staging.final_rendering_enabled is False), "Verified staging audit for the approved payload required."),
        _gate("recovery_disable_audit", "Recovery-disable audit is verified", bool(recovery_disable and recovery_disable.action_type == "disable_metadata_rendering" and recovery_disable.status == "verified" and recovery_disable.payload_hash == EXPECTED_PAYLOAD_HASH and str(recovery_disable.final_revision) == "1" and recovery_disable.final_rendering_enabled is False), "Verified recovery-disable audit required."),
        _gate("bootstrap_establishment_audit", "The active 0.3.0 bootstrap passed immediate executable-checksum verification", bool(establishment and establishment.status == "verified" and establishment.bootstrap_path == "project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap.php" and establishment.bootstrap_version == BOOTSTRAP_VERSION and establishment.bootstrap_entry_sha256 == BOOTSTRAP_ENTRY_SHA256 and establishment.checksum_verification_result == "matched"), "A verified bootstrap-establishment audit is required; quarantine or unverified manual activation blocks upgrade."),
        _gate("upgrade_audit_clear", "No unresolved plugin upgrade exists", not unresolved, "An unresolved plugin upgrade already exists."),
        _gate("metadata_lifecycle_clear", "No metadata lifecycle action is pending", not pending_lifecycle, "A metadata lifecycle action is pending."),
        _gate("plugin_singleton", "Exactly one Metadata Bridge is installed", len(matches) == 1, "Plugin is missing, duplicated, wrapped, or malformed."),
        _gate("plugin_active", "Metadata Bridge is active", len(matches) == 1 and matches[0].get("status") in {"active", "network-active"}, "Plugin must be active before upgrade."),
        _gate("current_version", "Installed version is exactly 0.57.6", len(matches) == 1 and matches[0].get("version") == request.current_plugin_version == CURRENT_VERSION and plugin_status.get("version") == CURRENT_VERSION, "Current plugin version differs."),
        _gate("plugin_identity", "Slug and entry path are exact", len(matches) == 1 and request.current_plugin_slug == PLUGIN_SLUG and request.current_plugin_path == PLUGIN_FILE and _normalize_plugin_identifier(matches[0].get("plugin")).authorized_entry_path == PLUGIN_FILE, "Plugin identity differs."),
        _gate("current_entry_checksum", "Remote executable entry matches the authorized 0.57.6 artifact", plugin_status.get("checksum") == current_artifact.get("entry_sha256"), "Installed executable checksum differs from 0.57.6."),
        _gate("current_artifact", "Current ZIP filename and checksum are exact", request.current_zip_filename == CURRENT_ZIP_NAME and request.current_zip_sha256 == CURRENT_ZIP_SHA256 == current_artifact.get("zip_sha256"), "Current artifact identity differs."),
        _gate("plugin_inventory", "Current full-plugin inventory hash is exact", observed.get("plugin_inventory_hash") == request.expected_plugin_inventory_hash, "Plugin inventory changed."),
        _gate("active_inventory", "Current active-plugin inventory hash is exact", observed.get("active_plugin_inventory_hash") == request.expected_active_plugin_inventory_hash, "Active-plugin inventory changed."),
        _gate("target_version", "Upgrade is exactly 0.57.6 to 0.57.7", request.target_plugin_version == TARGET_VERSION == artifact.get("plugin_version"), "Target version differs."),
        _gate("target_artifact", "Target filename and checksum are exact", request.target_zip_filename == ZIP_NAME and request.target_zip_sha256 == ZIP_SHA256 == artifact.get("zip_sha256"), "Target artifact differs."),
        _gate(
            "upgrade_bootstrap",
            "Separately approved single-purpose bootstrap is active and bound to the fixed upgrade",
            bootstrap_status.get("bootstrap") == "project-atlas-upgrade-bootstrap"
            and bootstrap_status.get("bootstrap_version") == BOOTSTRAP_VERSION
            and bootstrap_status.get("bootstrap_checksum") == bootstrap_artifact.get("entry_sha256") == BOOTSTRAP_ENTRY_SHA256
            and bootstrap_status.get("operation") == "upgrade_metadata_bridge_0.57.6_to_0.57.7"
            and bootstrap_status.get("application_password_compatible") is True
            and bootstrap_status.get("target_plugin") == PLUGIN_FILE
            and bootstrap_status.get("current_version") == CURRENT_VERSION
            and bootstrap_status.get("target_version") == TARGET_VERSION
            and bootstrap_status.get("target_zip") == ZIP_NAME
            and bootstrap_status.get("target_zip_sha256") == ZIP_SHA256
            and bootstrap_status.get("available") is True
            and bootstrap_status.get("metadata", {}).get("payload_present") is True
            and bootstrap_status.get("metadata", {}).get("payload_hash") == EXPECTED_PAYLOAD_HASH
            and str(bootstrap_status.get("metadata", {}).get("revision")) == "1"
            and bootstrap_status.get("metadata", {}).get("rendering_enabled") is False,
            "The separately approved fixed upgrade bootstrap is absent, inactive, mismatched, or unavailable.",
        ),
        _gate("metadata_rows", "Atlas metadata state and sync-audit rows remain exactly 1/0", len(metadata_states) == request.expected_metadata_state_rows == 1 and len(metadata_audits) == request.expected_metadata_sync_audit_rows == 0, "Metadata row counts changed."),
        _gate("metadata_state", "Atlas metadata state remains staged at revision 1", bool(state and state.status == request.expected_metadata_state_status == "staged" and state.payload_hash == EXPECTED_PAYLOAD_HASH and str(state.wordpress_revision) == request.expected_revision == "1" and state.payload == status_snapshot.get("payload")), "Atlas metadata state drifted."),
        _gate("rendering_disabled", "Rendering remains disabled", status_snapshot.get("rendering_enabled") is False and status_snapshot.get("enabled_metadata_state") is False, "Rendering is enabled."),
        _gate("payload_preserved", "The exact staged payload and hash are present", isinstance(status_snapshot.get("payload"), dict) and status_snapshot.get("payload_hash") == request.expected_payload_hash == EXPECTED_PAYLOAD_HASH, "Staged payload changed."),
        _gate("revision_one", "Metadata revision remains one", str(status_snapshot.get("revision")) == request.expected_revision == "1", "Metadata revision changed."),
        _gate("rendered_state", "Public rendered state is signed and unchanged", rendered.get("verified") is True and rendered.get("signature_validated") is True and rendered.get("h1") == [EXPECTED_H1] and _rendered_metadata_absent(rendered) and not rendered.get("atlas_metadata_marker_present", False), "Rendered state changed."),
        _gate("page_snapshot", "Page snapshot is exact", observed.get("page_snapshot_hash") == request.expected_page_snapshot_hash, "Page snapshot changed."),
        _gate("page_identity", "Page 8 identity remains exact", page.get("id") == 8 and page.get("status") == "publish" and page.get("slug") == "drywood-termite-tenting-orlando-fl" and page.get("featured_media") == 31, "Page identity changed."),
        _gate("body_hash", "Corrected body hash is exact", observed.get("page_body_hash") == request.expected_body_hash == EXPECTED_CORRECTED_BODY_HASH and observed.get("page_body_begins_expected_h2") is True, "Page body changed."),
        _gate("media31", "Media 31 snapshot is exact", observed.get("media31_snapshot_hash") == request.expected_media31_snapshot_hash, "Media 31 changed."),
        _gate("media32", "Media 32 remains unchanged and absent", observed.get("media32_snapshot_hash") == request.expected_media32_snapshot_hash and not observed.get("page_references_media32") and not rendered.get("media32_reference_present"), "Media 32 changed or rendered."),
        _gate("site_identity", "Site Title and Tagline remain exact", observed.get("site") == {"name": "My WordPress", "description": ""}, "Site identity changed."),
        _gate("php_findings", "PHP, REST, and header findings are clean", _clean_findings(request.php_error_log_findings), "PHP or REST findings require review."),
        _gate("browser_findings", "Browser and visible-site findings are clean", _clean_findings(request.browser_console_findings), "Browser findings require review."),
        _gate("cache_boundary", "No cache purge is observed", request.expected_cache_purge_count == 0 and observed.get("cache_purge_count", 0) == 0 and observed.get("cache_headers") == rendered.get("cache_headers", {}), "Cache observation changed."),
        _gate("expected_post_inventory", "Deterministic post-upgrade inventories match supplied expectations when supplied", (request.expected_post_plugin_inventory_hash in {None, expected_post.get("plugin_inventory_hash")} and request.expected_post_active_plugin_inventory_hash in {None, expected_post.get("active_plugin_inventory_hash")}), "Expected post-upgrade inventory differs."),
        _gate("read_only_preflight", "Preflight uses WordPress GET requests only", observed.get("wordpress_request_methods") == ["GET"], "Preflight attempted a WordPress mutation."),
    ]


def _post_upgrade_gates(request, before, after, plugin_status, bootstrap_status, routes, preview, metadata_states, metadata_audits):
    matches = _matching_reconciliation_plugins(after.get("plugins", []))
    rendered = after.get("rendered", {})
    status_snapshot = plugin_status.get("snapshot", {}) if isinstance(plugin_status.get("snapshot"), dict) else plugin_status
    previous_status = before.get("plugin_status", {}).get("snapshot", {})
    state = metadata_states[0] if len(metadata_states) == 1 else None
    expected = _expected_post_upgrade(before)
    return [
        _gate("plugin_singleton", "Exactly one Metadata Bridge remains installed", len(matches) == 1, "Plugin is missing or duplicated."),
        _gate("target_version", "Installed version is exactly 0.57.7", len(matches) == 1 and matches[0].get("version") == TARGET_VERSION and plugin_status.get("version") == TARGET_VERSION, "Target version not observed."),
        _gate("target_entry_checksum", "Remote executable entry matches the locked 0.57.7 artifact", plugin_status.get("checksum") == _target_entry_sha256(), "Installed executable differs from the target artifact."),
        _gate("plugin_active", "Plugin active status is preserved", len(matches) == 1 and matches[0].get("status") in {"active", "network-active"} and plugin_status.get("active") is True, "Plugin became inactive."),
        _gate("plugin_inventory", "Only the bridge version changed in full inventory", after.get("plugin_inventory_hash") == expected.get("plugin_inventory_hash"), "Full plugin inventory delta differs."),
        _gate("active_inventory", "Active-plugin inventory is unchanged", after.get("active_plugin_inventory_hash") == expected.get("active_plugin_inventory_hash"), "Active plugin inventory changed."),
        _gate("other_plugins", "No unrelated plugin changed", _plugins_without_bridge(after) == _plugins_without_bridge(before), "An unrelated plugin changed."),
        _gate("rendering_disabled", "Rendering remains disabled", status_snapshot.get("rendering_enabled") is False and status_snapshot.get("enabled_metadata_state") is False, "Rendering became enabled."),
        _gate("payload_preserved", "Staged payload and hash are preserved", status_snapshot.get("payload") == previous_status.get("payload") and status_snapshot.get("payload_hash") == previous_status.get("payload_hash") == request.expected_payload_hash == EXPECTED_PAYLOAD_HASH, "Staged payload changed."),
        _gate("revision_one", "Metadata revision remains one", str(status_snapshot.get("revision")) == str(previous_status.get("revision")) == request.expected_revision == "1", "Metadata revision changed."),
        _gate("metadata_state", "Atlas staged metadata state and row counts are preserved", len(metadata_states) == 1 and len(metadata_audits) == 0 and bool(state and state.status == request.expected_metadata_state_status == "staged" and state.payload_hash == EXPECTED_PAYLOAD_HASH and str(state.wordpress_revision) == "1" and state.payload == status_snapshot.get("payload")), "Atlas metadata state changed."),
        _gate("page_snapshot", "Page remains unchanged", after.get("page_snapshot_hash") == before.get("page_snapshot_hash") == request.expected_page_snapshot_hash, "Page changed."),
        _gate("body_hash", "Body remains unchanged", after.get("page_body_hash") == before.get("page_body_hash") == request.expected_body_hash, "Body changed."),
        _gate("media31", "Media 31 remains unchanged", after.get("media31_snapshot_hash") == before.get("media31_snapshot_hash") == request.expected_media31_snapshot_hash, "Media 31 changed."),
        _gate("media32", "Media 32 remains unchanged and absent", after.get("media32_snapshot_hash") == before.get("media32_snapshot_hash") == request.expected_media32_snapshot_hash and not after.get("page_references_media32") and not rendered.get("media32_reference_present"), "Media 32 changed or rendered."),
        _gate("site_identity", "Site Title and Tagline remain unchanged", after.get("site") == before.get("site") == {"name": "My WordPress", "description": ""}, "Site identity changed."),
        _gate("rendered_metadata", "No Atlas metadata renders", rendered.get("verified") is True and _rendered_metadata_absent(rendered) and not rendered.get("atlas_metadata_marker_present", False), "Atlas metadata rendered."),
        _gate(
            "cache_boundary",
            "No cache purge occurred",
            after.get("cache_headers") == before.get("cache_headers")
            and after.get("cache_purge_count", 0) == before.get("cache_purge_count", 0) == request.expected_cache_purge_count == 0,
            "Cache observation changed or a purge occurred.",
        ),
        _gate("lifecycle_routes", "Separated lifecycle, preview, and cache routes are registered", (LIFECYCLE_ROUTES | {PREVIEW_ROUTE, CACHE_PURGE_ROUTE}) <= set(routes.get("routes", [])), "Required lifecycle, preview, or cache route is missing."),
        _gate("preview_disabled_contract", "Read-only preview fails closed with the approved HTTP 409 while rendering is disabled", preview.get("status_code") == 409 and preview.get("code") == "atlas_rendering_preview_unavailable" and preview.get("request_method") == "GET" and _target_artifact_preview_contract(), "Disabled preview contract changed or unexpectedly returned output."),
        _gate("preview_output_deferred", "Preview output verification is explicitly deferred to guarded cache-aware rendering preflight", preview.get("output_verification_deferred") is True, "Preview-output deferral was not recorded."),
        _gate("legacy_route_disabled", "Locked 0.57.7 artifact keeps the legacy combined route disabled with HTTP 410", routes.get("legacy_route_registered") is True and _target_artifact_disables_legacy_route(), "Legacy route contract is not disabled."),
        _gate(
            "bootstrap_fail_closed",
            "Upgrade bootstrap is no longer reusable after the fixed version transition",
            bootstrap_status.get("bootstrap") == "project-atlas-upgrade-bootstrap"
            and bootstrap_status.get("bootstrap_version") == BOOTSTRAP_VERSION
            and bootstrap_status.get("available") is False
            and bootstrap_status.get("plugin", {}).get("version") == TARGET_VERSION,
            "The single-purpose bootstrap did not become fail-closed after upgrade.",
        ),
        _gate("read_only_verification", "Post-upgrade verification uses GET requests only", after.get("wordpress_request_methods") == ["GET"] and routes.get("request_method") == preview.get("request_method") == "GET", "Post-upgrade verification attempted a mutation."),
    ]


def _send_fixed_upgrade(session: Session) -> dict[str, Any]:
    """The only WordPress mutation reachable from this service."""
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password):
        return {"_error": "credentials_unavailable"}
    zip_path, _ = release_paths(resolve_program_root())
    try:
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            response = client.post(
                f"{settings.site_url.rstrip('/')}/wp-json{BOOTSTRAP_UPGRADE_ROUTE}",
                files={"artifact": (ZIP_NAME, zip_path.read_bytes(), "application/zip")},
                auth=httpx.BasicAuth(settings.username, password),
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
        payload = response.json() if response.status_code == 200 else {}
        accepted = (
            response.status_code == 200
            and isinstance(payload, dict)
            and payload.get("accepted") is True
            and payload.get("operation") == "upgrade_metadata_bridge_0.57.6_to_0.57.7"
            and payload.get("plugin") == PLUGIN_FILE
            and payload.get("previous_version") == CURRENT_VERSION
            and payload.get("target_version") == TARGET_VERSION
            and payload.get("active") is True
            and payload.get("entry_sha256") == _target_entry_sha256()
            and payload.get("metadata_preserved") is True
            and payload.get("payload_hash") == EXPECTED_PAYLOAD_HASH
            and str(payload.get("revision")) == "1"
            and payload.get("rendering_enabled") is False
            and payload.get("bootstrap_reusable") is False
        )
        return {
            "status_code": response.status_code,
            "accepted": accepted,
            "_error": None if accepted else f"fixed_bootstrap_http_{response.status_code}_unconfirmed",
        }
    except (OSError, ValueError, httpx.HTTPError) as exc:
        return {"_error": exc.__class__.__name__}


def _read_bootstrap_status(session: Session) -> dict[str, Any]:
    """Read the fixed helper identity through application-password REST authentication."""
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password):
        return {"_error": "credentials_unavailable"}
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get(
                f"{settings.site_url.rstrip('/')}/wp-json{BOOTSTRAP_STATUS_ROUTE}",
                auth=httpx.BasicAuth(settings.username, password),
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
        payload = response.json() if response.status_code == 200 else {}
        if not isinstance(payload, dict):
            payload = {}
        return {**payload, "status_code": response.status_code, "request_method": "GET"}
    except (httpx.HTTPError, ValueError):
        return {"_error": "upgrade_bootstrap_unavailable", "request_method": "GET"}


def _read_disabled_preview_contract(session: Session) -> dict[str, Any]:
    """Confirm the locked preview route fails closed while rendering is disabled."""
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password):
        return {"_error": "credentials_unavailable", "request_method": "GET", "output_verification_deferred": True}
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get(
                f"{settings.site_url.rstrip('/')}/wp-json{PREVIEW_ROUTE}",
                auth=httpx.BasicAuth(settings.username, password),
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
        payload = response.json() if response.status_code == 409 else {}
        return {
            "status_code": response.status_code,
            "code": payload.get("code") if isinstance(payload, dict) else None,
            "message": payload.get("message") if isinstance(payload, dict) else None,
            "request_method": "GET",
            "output_verification_deferred": True,
        }
    except (httpx.HTTPError, ValueError):
        return {"_error": "preview_contract_unavailable", "request_method": "GET", "output_verification_deferred": True}


def _read_route_registry(session: Session) -> dict[str, Any]:
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password):
        return {"routes": [], "legacy_route_registered": False, "request_method": "GET", "_error": "credentials_unavailable"}
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get(
                f"{settings.site_url.rstrip('/')}/wp-json/",
                auth=httpx.BasicAuth(settings.username, password),
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
        payload = response.json() if response.status_code == 200 else {}
        routes = payload.get("routes", {}) if isinstance(payload, dict) else {}
        return {
            "routes": sorted(routes),
            "legacy_route_registered": LEGACY_ROUTE in routes,
            "request_method": "GET",
            "status_code": response.status_code,
        }
    except (httpx.HTTPError, ValueError):
        return {"routes": [], "legacy_route_registered": False, "request_method": "GET", "_error": "route_registry_unavailable"}


def _verify_current_artifact() -> tuple[dict[str, Any], list[WordPressDraftGateResult]]:
    path = resolve_program_root() / "wordpress" / "dist" / CURRENT_ZIP_NAME
    try:
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            entry = archive.read(PLUGIN_FILE)
            header = entry.decode("utf-8")
            valid = (
                len(names) == len(set(names))
                and all("\\" not in name and ".." not in name.split("/") for name in names)
                and {name.split("/")[0] for name in names} == {PLUGIN_SLUG}
                and f"Version: {CURRENT_VERSION}" in header
            )
            entry_sha = hashlib.sha256(entry).hexdigest()
    except (OSError, UnicodeError, KeyError, zipfile.BadZipFile):
        sha = entry_sha = None
        valid = False
    artifact = {
        "version": CURRENT_VERSION,
        "zip_filename": CURRENT_ZIP_NAME,
        "zip_sha256": sha,
        "entry_sha256": entry_sha,
        "portable": valid,
    }
    return artifact, [
        _gate("current_artifact_hash", "Authorized 0.57.6 ZIP checksum is exact", sha == CURRENT_ZIP_SHA256, "Current artifact checksum differs."),
        _gate("current_artifact_portable", "Authorized 0.57.6 ZIP structure and version are valid", valid, "Current artifact is malformed."),
    ]


def _verify_bootstrap_artifact() -> tuple[dict[str, Any], list[WordPressDraftGateResult]]:
    path = resolve_program_root() / "wordpress" / "dist" / BOOTSTRAP_ZIP_NAME
    entry = "project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap.php"
    readme = "project-atlas-upgrade-bootstrap/README.md"
    try:
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            entry_raw = archive.read(entry)
            readme_raw = archive.read(readme)
            valid = (
                len(names) == len(set(names)) == 2
                and set(names) == {entry, readme}
                and all("\\" not in name and ".." not in name.split("/") for name in names)
                and b"Version: 0.3.0" in entry_raw
                and b"ATLAS_UPGRADE_BOOTSTRAP_TARGET_ZIP_SHA256" in entry_raw
                and b"current_user_can('update_plugins')" in entry_raw
            )
            entry_sha = hashlib.sha256(entry_raw).hexdigest()
    except (OSError, KeyError, zipfile.BadZipFile):
        sha = entry_sha = None
        valid = False
    artifact = {
        "version": BOOTSTRAP_VERSION,
        "zip_filename": BOOTSTRAP_ZIP_NAME,
        "zip_sha256": sha,
        "entry_sha256": entry_sha,
        "portable": valid,
    }
    return artifact, [
        _gate("bootstrap_artifact_hash", "Upgrade bootstrap ZIP checksum is exact", sha == BOOTSTRAP_ZIP_SHA256, "Upgrade bootstrap checksum differs."),
        _gate("bootstrap_artifact_portable", "Upgrade bootstrap ZIP structure and contract are exact", valid and entry_sha == BOOTSTRAP_ENTRY_SHA256, "Upgrade bootstrap artifact is malformed."),
    ]


def _target_entry_sha256() -> str:
    path, _ = release_paths(resolve_program_root())
    with zipfile.ZipFile(path) as archive:
        return hashlib.sha256(archive.read(PLUGIN_FILE)).hexdigest()


def _target_artifact_disables_legacy_route() -> bool:
    _, source = release_paths(resolve_program_root())
    text = (source / "project-atlas-metadata-bridge.php").read_text(encoding="utf-8")
    return "atlas_legacy_combined_apply_disabled" in text and "['status' => 410]" in text


def _target_artifact_preview_contract() -> bool:
    _, source = release_paths(resolve_program_root())
    text = (source / "project-atlas-metadata-bridge.php").read_text(encoding="utf-8")
    return all(fragment in text for fragment in (
        "register_rest_route('project-atlas/v3', '/pages/8/metadata/rendering/preview'",
        "function atlas_metadata_head_markup_from_snapshot(array $snapshot): string",
        "function atlas_metadata_public_request_is_page_8(): bool",
        "return atlas_metadata_head_markup_from_snapshot(atlas_metadata_snapshot());",
        "$markup = atlas_metadata_head_markup_from_snapshot($snapshot);",
        "if (!$snapshot['rendering_enabled'] || $markup === '')",
        "atlas_rendering_preview_unavailable",
        "['status' => 409]",
        "register_rest_route('project-atlas/v3', '/pages/8/cache/siteground/purge'",
    ))


def _expected_post_upgrade(observed):
    plugins = deepcopy(observed.get("plugins", []))
    matches = [item for item in plugins if _normalize_plugin_identifier(item.get("plugin")).authorized_entry_path == PLUGIN_FILE]
    if len(matches) != 1:
        return {}
    matches[0]["version"] = TARGET_VERSION
    return {
        "plugin_inventory_hash": _hash(plugins),
        "active_plugin_inventory_hash": _hash(sorted(observed.get("active_plugins", []))),
    }


def _binding(request, installation, activation, observed, plugin_status, bootstrap_status, artifact, current_artifact, expected_post, expires_at):
    evidence = request.manual_browser_evidence
    return {
        "action": "upgrade_metadata_bridge_0.57.6_to_0.57.7",
        "targets": {"page_id": 41, "wordpress_post_id": 8, "installation_audit_id": request.installation_audit_id, "activation_audit_id": request.activation_audit_id},
        "audits": {"installation_status": installation.status if installation else None, "activation_status": activation.status if activation else None},
        "runtime": request.expected_runtime_identity.model_dump(mode="json"),
        "repository": {"head": request.repository_head, "origin_main": request.repository_origin_main, "tag": request.repository_tag, "branch": request.repository_branch, "clean": request.repository_working_tree_clean, "protected": request.protected_paths_unchanged},
        "backup": _proof(request).model_dump(mode="json", exclude={"manual_browser_evidence"}),
        "current_artifact": current_artifact,
        "target_artifact": {"version": artifact.get("plugin_version"), "zip": artifact.get("zip_file_name"), "sha256": artifact.get("zip_sha256"), "source_sha256": artifact.get("plugin_source_sha256")},
        "before": {"plugins": observed.get("plugin_inventory_hash"), "active": observed.get("active_plugin_inventory_hash"), "status_checksum": plugin_status.get("checksum"), "page": observed.get("page_snapshot_hash"), "body": observed.get("page_body_hash"), "media31": observed.get("media31_snapshot_hash"), "media32": observed.get("media32_snapshot_hash"), "cache": _hash(observed.get("cache_headers", {}))},
        "upgrade_bootstrap": _safe_bootstrap_status(bootstrap_status),
        "expected_after": expected_post,
        "evidence": {"id": evidence.evidence_id if evidence else None, "schema": evidence.evidence_schema if evidence else None, "version": evidence.evidence_schema_version if evidence else None, "signature": evidence.helper_signature if evidence else None, "expires_at": str(evidence.expires_at) if evidence else None},
        "handle_expires_at": expires_at.isoformat() if expires_at else None,
    }


def _finalize(session, audit, status, gates, snapshot, recommendation):
    audit.status = status
    audit.post_snapshot = snapshot
    audit.final_inventories = {
        "plugins": snapshot.get("plugin_inventory_hash"),
        "active_plugins": snapshot.get("active_plugin_inventory_hash"),
    }
    audit.gate_results = [gate.model_dump(mode="json") for gate in gates]
    audit.verification_findings = {"failed_gates": [gate.code for gate in gates if not gate.passed]}
    audit.recovery_recommendation = recommendation
    audit.transition_history = [*audit.transition_history, status]
    audit.atlas_write_count = 2
    audit.completed_at = datetime.now(UTC)
    audit.error_code = None if status == "verified" else status
    audit.error_message = None if status == "verified" else "; ".join(g.message for g in gates if not g.passed)[:2000]
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return WordPressPluginUpgradeResult(
        upgrade_audit_id=audit.id or 0,
        status=status,
        binding_hash=audit.binding_hash,
        state_history=audit.transition_history,
        previous_version=CURRENT_VERSION,
        target_version=TARGET_VERSION,
        gate_results=gates,
        inspected_state=snapshot,
        wordpress_write_scope=UPGRADE_WORDPRESS_SCOPE,
        atlas_write_scope=UPGRADE_ATLAS_SCOPE,
        recovery_recommendation=recommendation,
        further_action_required=status != "verified",
    )


def _recovery_recommendation(observed, plugin_status):
    matches = _matching_reconciliation_plugins(observed.get("plugins", []))
    if len(matches) == 1 and matches[0].get("version") == TARGET_VERSION and matches[0].get("status") in {"active", "network-active"} and plugin_status.get("version") == TARGET_VERSION:
        return "guarded_downgrade"
    return "siteground_restore"


def _proof(request):
    return WordPressDeploymentBackupEvidence.model_validate(
        request.model_dump(mode="json", include=set(WordPressDeploymentBackupEvidence.model_fields))
    )


def _public_snapshot(observed, plugin_status, metadata_states, metadata_audits):
    return {
        **observed,
        "plugin_status": {
            key: plugin_status.get(key)
            for key in ("plugin", "version", "checksum", "active", "snapshot")
            if key in plugin_status
        },
        "metadata_state_rows": len(metadata_states),
        "metadata_sync_audit_rows": len(metadata_audits),
        "wordpress_write_count": 0,
        "atlas_write_count": 0,
    }


def _metadata_state(snapshot):
    status = snapshot.get("plugin_status", {}).get("snapshot", {})
    return {
        "rendering_enabled": status.get("rendering_enabled"),
        "payload_present": status.get("payload") is not None,
        "payload_hash": status.get("payload_hash"),
        "revision": status.get("revision"),
        "metadata_state_rows": snapshot.get("metadata_state_rows"),
        "metadata_sync_audit_rows": snapshot.get("metadata_sync_audit_rows"),
    }


def _page_media_state(snapshot):
    return {
        "page": snapshot.get("page_snapshot_hash"),
        "body": snapshot.get("page_body_hash"),
        "media31": snapshot.get("media31_snapshot_hash"),
        "media32": snapshot.get("media32_snapshot_hash"),
    }


def _plugins_without_bridge(snapshot):
    return _canonical_plugins([
        item for item in snapshot.get("plugins", [])
        if _normalize_plugin_identifier(item.get("plugin")).authorized_entry_path != PLUGIN_FILE
    ])


def _safe_upgrade_response(value):
    return {key: value.get(key) for key in ("status_code", "accepted") if key in value}


def _safe_bootstrap_status(value):
    allowed = (
        "bootstrap",
        "bootstrap_version",
        "bootstrap_checksum",
        "operation",
        "application_password_compatible",
        "target_plugin",
        "current_version",
        "target_version",
        "target_zip",
        "target_zip_sha256",
        "available",
        "plugin",
        "status_code",
        "request_method",
        "_error",
        "metadata",
    )
    return {key: value.get(key) for key in allowed if key in value}


def _store_handle(request, binding_hash, expires_at):
    handle = secrets.token_urlsafe(32)
    entry = _UpgradeHandleEntry(request, binding_hash, datetime.now(UTC), expires_at)
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
        raise HTTPException(422, "Upgrade handle is unknown, expired, consumed, or invalidated by restart.")
    if entry.expires_at <= datetime.now(UTC):
        raise HTTPException(422, "Upgrade handle expired.")
    return entry


def _expire_handle(handle):
    with _handle_lock:
        _handles.pop(handle, None)
        _handle_timers.pop(handle, None)


def _clear_upgrade_handles():
    with _handle_lock:
        for timer in _handle_timers.values():
            timer.cancel()
        _handles.clear()
        _handle_timers.clear()


def _unavailable_observation(reason):
    return {"_error": reason or "evidence_or_runtime_unavailable", "plugins": [], "rendered": {"verified": False}, "wordpress_request_methods": [], "wordpress_request_performed": False, "read_only": True}


def _evidence_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise HTTPException(422, "Browser evidence expiration is malformed.") from exc
    if parsed.tzinfo is None:
        raise HTTPException(422, "Browser evidence expiration must be timezone-aware.")
    return parsed.astimezone(UTC)
