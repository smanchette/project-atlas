"""Atlas-only reconciliation for the exact 0.57.7 cache-boundary false failure."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import PureWindowsPath
import secrets
from threading import RLock, Timer
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.backup import BackupValidationError, load_backup, resolve_backup_download
from app.models import (
    WordPressBootstrapEstablishmentAudit,
    WordPressMetadataState,
    WordPressMetadataSyncAudit,
    WordPressPluginUpgradeAudit,
)
from app.schemas.wordpress import (
    WordPressDraftGateResult,
    WordPressPluginUpgradeReconciliationApplyRequest,
    WordPressPluginUpgradeReconciliationPreflight,
    WordPressPluginUpgradeReconciliationRequest,
    WordPressPluginUpgradeReconciliationResult,
)
from app.services import wordpress_plugin_upgrade_0577 as upgrade
from app.services.wordpress_bootstrap_establishment import (
    BOOTSTRAP_ENTRY,
    BOOTSTRAP_ENTRY_SHA256,
    BOOTSTRAP_VERSION,
    RETIREMENT_REASON,
    _pending_operation_exists,
)
from app.services.wordpress_deployment import (
    EXPECTED_CORRECTED_BODY_HASH,
    PLUGIN_FILE,
    _gate,
    _matching_reconciliation_plugins,
    _observe,
    deployment_readiness,
)
from app.services.wordpress_rendered_state import (
    EXPECTED_H1,
    EXPECTED_MEDIA_ALT,
    EXPECTED_MEDIA_URL,
    EXPECTED_URL,
    validate_manual_browser_evidence,
)


AUDIT_ID = 3
RECONCILIATION_REASON = "cache_boundary_volatile_observation_reconciled"
RECONCILIATION_PHRASE = (
    "RECONCILE PROJECT ATLAS METADATA BRIDGE UPGRADE AUDIT 3 "
    "WITHOUT ANOTHER WORDPRESS WRITE"
)
HANDLE_TTL = timedelta(minutes=10)
RELEASE_VERSION = "v0.59.96"
SOURCE_COMPATIBILITY_ID = "project-atlas-release-identity-v0.59.96"


@dataclass(frozen=True)
class _ReconciliationHandle:
    request: WordPressPluginUpgradeReconciliationRequest
    audit_id: int
    binding_hash: str
    expires_at: datetime


_lock = RLock()
_handles: dict[str, _ReconciliationHandle] = {}
_timers: dict[str, Timer] = {}


def reconciliation_preflight(
    session: Session,
    page_id: int,
    request: WordPressPluginUpgradeReconciliationRequest,
) -> WordPressPluginUpgradeReconciliationPreflight:
    """Run fresh GET-only verification and issue one process-memory handle."""

    _target(page_id, request.upgrade_audit_id)
    audit = session.get(WordPressPluginUpgradeAudit, request.upgrade_audit_id)
    inspected, gates, backup = _inspect(session, request, audit)
    ready = all(gate.passed for gate in gates)
    expires_at = None
    if ready:
        expires_at = min(
            datetime.now(UTC) + HANDLE_TTL,
            upgrade._evidence_expiry(request.manual_browser_evidence.expires_at),
        )
        if expires_at <= datetime.now(UTC):
            ready = False
            expires_at = None
            gates.append(
                _gate(
                    "reconciliation_handle_lifetime",
                    "Fresh evidence permits a positive reconciliation-handle lifetime",
                    False,
                    "Fresh evidence expires before reconciliation can be authorized.",
                )
            )
    binding_hash = _hash(_binding(request, audit, inspected, backup, expires_at))
    handle = (
        _store(request, request.upgrade_audit_id, binding_hash, expires_at)
        if ready and expires_at
        else None
    )
    return WordPressPluginUpgradeReconciliationPreflight(
        status=(
            "plugin_upgrade_reconciliation_ready"
            if ready
            else "plugin_upgrade_reconciliation_blocked"
        ),
        reconciliation_ready=ready,
        reconciliation_handle=handle,
        reconciliation_handle_fingerprint=_sha(handle) if handle else None,
        binding_hash=binding_hash if ready else None,
        confirmation_phrase=RECONCILIATION_PHRASE if ready else None,
        expires_at=expires_at,
        atlas_data_backup=backup,
        inspected_state=inspected,
        gate_results=gates,
    )


def apply_reconciliation(
    session: Session,
    page_id: int,
    request: WordPressPluginUpgradeReconciliationApplyRequest,
) -> WordPressPluginUpgradeReconciliationResult:
    """Consume one handle and atomically finalize only Upgrade Audit ID 3."""

    _target(page_id, AUDIT_ID)
    if not hmac.compare_digest(request.confirmation_phrase, RECONCILIATION_PHRASE):
        raise HTTPException(422, "The plugin-upgrade reconciliation phrase is incorrect.")
    fingerprint = _sha(request.reconciliation_handle)
    replay = session.exec(
        select(WordPressPluginUpgradeAudit).where(
            WordPressPluginUpgradeAudit.reconciliation_handle_fingerprint
            == fingerprint
        )
    ).one_or_none()
    if replay is not None:
        raise HTTPException(409, "The reconciliation handle was already consumed.")

    entry = _consume(request.reconciliation_handle)
    if entry.audit_id != AUDIT_ID:
        raise HTTPException(409, "The reconciliation handle is bound to another audit.")
    audit = session.exec(
        select(WordPressPluginUpgradeAudit)
        .where(WordPressPluginUpgradeAudit.id == entry.audit_id)
        .with_for_update()
    ).one_or_none()
    if audit is None:
        raise HTTPException(404, "Plugin-upgrade audit not found.")
    inspected, gates, backup = _inspect(session, entry.request, audit)
    if not all(gate.passed for gate in gates):
        raise HTTPException(
            409,
            {
                "reason_code": "plugin_upgrade_reconciliation_gate_drift",
                "message": "A reconciliation gate changed after preflight.",
            },
        )
    binding_hash = _hash(
        _binding(entry.request, audit, inspected, backup, entry.expires_at)
    )
    if not hmac.compare_digest(binding_hash, entry.binding_hash):
        raise HTTPException(
            409,
            {
                "reason_code": "plugin_upgrade_reconciliation_binding_drift",
                "message": "The reconciliation binding changed after preflight.",
            },
        )

    original_history = list(audit.transition_history)
    original_gate_results = deepcopy(audit.gate_results)
    original_findings = deepcopy(audit.verification_findings)
    original_post_snapshot_hash = _hash(audit.post_snapshot or {})
    original_final_inventories = deepcopy(audit.final_inventories)
    now = datetime.now(UTC)

    audit.status = "verified"
    audit.reconciliation_reason = RECONCILIATION_REASON
    audit.reconciliation_handle_fingerprint = fingerprint
    audit.reconciliation_binding_hash = entry.binding_hash
    audit.reconciled_at = now
    audit.completed_at = now
    audit.transition_history = [*original_history, RECONCILIATION_REASON]
    audit.reconciliation_snapshot = {
        "reason": RECONCILIATION_REASON,
        "inspected_state": inspected,
        "gate_results": [gate.model_dump(mode="json") for gate in gates],
        "original_history": original_history,
        "original_gate_results": original_gate_results,
        "original_verification_findings": original_findings,
        "original_post_snapshot_sha256": original_post_snapshot_hash,
        "original_final_inventories": original_final_inventories,
        "wordpress_write_count": 0,
        "plugin_write_count": 0,
        "cache_write_count": 0,
    }
    audit.atlas_write_count += 1
    audit.atlas_write_scope = [
        *audit.atlas_write_scope,
        "finalize only WordPressPluginUpgradeAudit 3 after fresh GET-only reconciliation",
    ]
    audit.recovery_recommendation = "no_action"
    audit.error_code = None
    audit.error_message = None
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return WordPressPluginUpgradeReconciliationResult(
        state_history=audit.transition_history,
        binding_hash=entry.binding_hash,
        reconciliation_handle_fingerprint=fingerprint,
        cumulative_atlas_write_count=audit.atlas_write_count,
        inspected_state=inspected,
        gate_results=gates,
    )


def _inspect(session, request, audit):
    readiness = deployment_readiness()
    release = readiness.get("release") or {}
    expected_runtime = request.expected_runtime_identity.model_dump(mode="json")
    actual_runtime = {
        "atlas_version": release.get("atlas_version"),
        "atlas_commit": release.get("atlas_commit"),
        "atlas_tag": release.get("atlas_tag"),
        "manifest_sha256": release.get("manifest_sha256"),
        "source_compatibility_id": release.get("source_compatibility_id"),
    }
    runtime_exact = bool(
        readiness.get("release_status") == "verified"
        and release.get("runtime_identity_verified") is True
        and release.get("manifest_integrity_verified") is True
        and release.get("expected_release_matched") is True
        and expected_runtime == actual_runtime
        and release.get("atlas_version") == RELEASE_VERSION
        and release.get("source_compatibility_id") == SOURCE_COMPATIBILITY_ID
    )
    evidence = request.manual_browser_evidence
    evidence_valid, evidence_reason = validate_manual_browser_evidence(
        evidence,
        os.environ.get("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", ""),
    )
    evidence_valid = bool(
        evidence_valid
        and evidence.evidence_schema_version == 1
        and audit is not None
        and evidence.evidence_id != audit.browser_evidence_id
    )
    if evidence.evidence_schema_version != 1:
        evidence_reason = "Reconciliation requires fresh schema-v1 evidence."
    elif audit is not None and evidence.evidence_id == audit.browser_evidence_id:
        evidence_reason = "Reconciliation evidence must be freshly captured."

    observed = (
        _observe(session, request)
        if runtime_exact and evidence_valid
        else upgrade._unavailable_observation(
            evidence_reason or "runtime_identity_unavailable"
        )
    )
    plugin_status = (
        upgrade._read_plugin_status(session)
        if observed.get("wordpress_request_performed")
        else {"_error": "observation_unavailable"}
    )
    bootstrap_status = (
        upgrade._read_bootstrap_status(session)
        if observed.get("wordpress_request_performed")
        else {"_error": "observation_unavailable"}
    )
    states = list(
        session.exec(
            select(WordPressMetadataState).where(
                WordPressMetadataState.generated_page_id == 41
            )
        )
    )
    sync_audits = list(
        session.exec(
            select(WordPressMetadataSyncAudit).where(
                WordPressMetadataSyncAudit.generated_page_id == 41
            )
        )
    )
    audit_one = session.get(WordPressBootstrapEstablishmentAudit, 1)
    audit_two = session.get(WordPressBootstrapEstablishmentAudit, 2)
    backup, backup_gates = _backup(request, release, audit)
    post = audit.post_snapshot if audit and isinstance(audit.post_snapshot, dict) else {}
    rendered = observed.get("rendered", {})
    historical_rendered = post.get("rendered", {}) if isinstance(post, dict) else {}
    matches = _matching_reconciliation_plugins(observed.get("plugins", []))
    bootstrap_matches = [
        item
        for item in observed.get("plugins", [])
        if str(item.get("plugin", "")).removesuffix(".php") == BOOTSTRAP_ENTRY.removesuffix(".php")
    ]
    status_snapshot = (
        plugin_status.get("snapshot", {})
        if isinstance(plugin_status.get("snapshot"), dict)
        else {}
    )
    state = states[0] if len(states) == 1 else None
    failure_codes = {
        item.get("code")
        for item in (audit.gate_results if audit else [])
        if item.get("passed") is False
    }
    cache_comparison = (
        upgrade.compare_upgrade_cache_boundary(audit.pre_snapshot, observed)
        if audit and isinstance(audit.pre_snapshot, dict)
        else {"compatible": False, "reason_code": "historical_snapshot_unavailable"}
    )
    gates = [
        _gate(
            "runtime_identity",
            "v0.59.96 runtime and independently expected identity are exact",
            runtime_exact,
            "The loaded runtime identity is unavailable or differs.",
        ),
        _gate(
            "repository_identity",
            "Repository identity, main branch, clean tree, and protected paths are exact",
            request.repository_head
            == request.repository_origin_main
            == request.expected_runtime_identity.atlas_commit
            and request.repository_tag == RELEASE_VERSION
            and request.repository_branch == "main"
            and request.repository_working_tree_clean
            and request.protected_paths_unchanged,
            "Repository identity or cleanliness differs.",
        ),
        _gate(
            "fresh_evidence",
            "Fresh signed schema-v1 evidence is valid and differs from historical evidence",
            evidence_valid,
            evidence_reason or "Fresh signed schema-v1 evidence is invalid.",
        ),
        _gate(
            "read_only_observation",
            "Authenticated WordPress observation succeeded using GET requests only",
            observed.get("wordpress_request_performed") is True
            and observed.get("wordpress_request_methods") == ["GET"]
            and observed.get("read_only") is True,
            "Authenticated GET-only WordPress observation is unavailable.",
        ),
        _gate(
            "audit_identity",
            "Upgrade Audit ID 3 is bound to Atlas page 41 and WordPress page 8",
            bool(
                audit
                and audit.id == AUDIT_ID
                and audit.generated_page_id == 41
                and audit.wordpress_post_id == 8
            ),
            "The selected upgrade audit identity differs.",
        ),
        _gate(
            "prior_audits",
            "Audit ID 1 remains authorization-retired and Audit ID 2 remains verified",
            bool(
                audit_one
                and audit_one.status == "authorization_retired"
                and audit_one.retirement_reason == RETIREMENT_REASON
                and audit_two
                and audit_two.status == "verified"
            ),
            "Required historical audit status changed.",
        ),
        _gate(
            "known_failure",
            "Audit ID 3 is the exact cache-boundary-only verification failure",
            bool(
                audit
                and audit.status == "verification_failed"
                and audit.transition_history == ["pending", "verification_failed"]
                and failure_codes == {"cache_boundary"}
                and audit.error_code == "verification_failed"
            ),
            "Audit status, history, or failed-gate signature differs.",
        ),
        _gate(
            "original_upgrade_write",
            "Exactly one original fixed Metadata Bridge replacement write is preserved",
            bool(
                audit
                and audit.wordpress_write_count == 1
                and audit.wordpress_write_scope == upgrade.UPGRADE_WORDPRESS_SCOPE
            ),
            "The original upgrade write record differs.",
        ),
        _gate(
            "upgrade_identity",
            "The original upgrade remains exactly 0.57.6 to 0.57.7 with locked artifacts",
            bool(
                audit
                and audit.previous_version == upgrade.CURRENT_VERSION
                and audit.target_version == upgrade.TARGET_VERSION
                and audit.previous_artifact_sha256 == upgrade.CURRENT_ZIP_SHA256
                and audit.target_artifact_sha256 == upgrade.ZIP_SHA256
            ),
            "The original version or artifact identity differs.",
        ),
        _gate(
            "not_previously_reconciled",
            "Audit ID 3 has not already been reconciled",
            bool(
                audit
                and audit.reconciliation_reason is None
                and audit.reconciliation_handle_fingerprint is None
                and audit.reconciliation_binding_hash is None
                and audit.reconciliation_snapshot is None
                and audit.reconciled_at is None
            ),
            "Audit ID 3 was already reconciled.",
        ),
        _gate(
            "metadata_bridge",
            "Metadata Bridge 0.57.7 remains installed once, active, and checksum-exact",
            len(matches) == 1
            and matches[0].get("version") == upgrade.TARGET_VERSION
            and matches[0].get("status") == "active"
            and plugin_status.get("version") == upgrade.TARGET_VERSION
            and plugin_status.get("active") is True
            and plugin_status.get("checksum") == upgrade._target_entry_sha256(),
            "Metadata Bridge identity, version, active status, or checksum differs.",
        ),
        _gate(
            "plugin_inventories",
            "Complete and active plugin inventories remain at the verified post-upgrade values",
            bool(
                audit
                and observed.get("plugin_inventory_hash")
                == (audit.final_inventories or {}).get("plugins")
                and observed.get("active_plugin_inventory_hash")
                == (audit.final_inventories or {}).get("active_plugins")
            ),
            "Plugin inventory changed after the upgrade.",
        ),
        _gate(
            "bootstrap",
            "Bootstrap 0.3.0 remains installed once, ordinary-active, and checksum-exact",
            len(bootstrap_matches) == 1
            and bootstrap_matches[0].get("version") == BOOTSTRAP_VERSION
            and bootstrap_matches[0].get("status") == "active"
            and bootstrap_status.get("bootstrap_version") == BOOTSTRAP_VERSION
            and bootstrap_status.get("bootstrap_checksum") == BOOTSTRAP_ENTRY_SHA256
            and bootstrap_status.get("request_method") == "GET",
            "Bootstrap identity, active status, or checksum differs.",
        ),
        _gate(
            "metadata_state",
            "Payload, revision, rendering, and Atlas metadata rows remain exact",
            len(states) == 1
            and len(sync_audits) == 0
            and bool(
                state
                and state.status == "staged"
                and state.payload_hash == upgrade.EXPECTED_PAYLOAD_HASH
                and str(state.wordpress_revision) == "1"
            )
            and status_snapshot.get("rendering_enabled") is False
            and status_snapshot.get("payload_hash") == upgrade.EXPECTED_PAYLOAD_HASH
            and str(status_snapshot.get("revision")) == "1",
            "Payload, revision, rendering, or Atlas metadata rows changed.",
        ),
        _gate(
            "page_body_media_settings",
            "Page, body, media, Site Title, Tagline, and settings remain exact",
            bool(post)
            and observed.get("page_snapshot_hash") == post.get("page_snapshot_hash")
            and observed.get("page_body_hash")
            == post.get("page_body_hash")
            == EXPECTED_CORRECTED_BODY_HASH
            and observed.get("media31_snapshot_hash")
            == post.get("media31_snapshot_hash")
            and observed.get("media32_snapshot_hash")
            == post.get("media32_snapshot_hash")
            and observed.get("site") == post.get("site") == {"name": "My WordPress", "description": ""}
            and observed.get("page_references_media32") is False,
            "Page, body, media, or site settings changed.",
        ),
        _gate(
            "rendered_identity",
            "Fresh public rendering preserves URL, H1, media, metadata absence, and signed identities",
            rendered.get("verified") is True
            and rendered.get("signature_validated") is True
            and rendered.get("evidence_schema_version") == 1
            and rendered.get("browser_evidence_identifier") == evidence.evidence_id
            and rendered.get("final_url") == EXPECTED_URL
            and rendered.get("redirect_count") == 0
            and rendered.get("status_code") == 200
            and rendered.get("h1") == [EXPECTED_H1]
            and rendered.get("featured_image_url") == EXPECTED_MEDIA_URL
            and rendered.get("featured_image_alt") == EXPECTED_MEDIA_ALT
            and rendered.get("head_hash")
            == audit.browser_evidence_hashes.get("rendered_head")
            == historical_rendered.get("head_hash")
            and rendered.get("visible_hash")
            == audit.browser_evidence_hashes.get("visible_content")
            == historical_rendered.get("visible_hash")
            and upgrade._rendered_metadata_absent(rendered)
            and not rendered.get("atlas_metadata_marker_present", False)
            and not rendered.get("media32_reference_present", False),
            "Rendered public identity, metadata absence, or privacy evidence differs.",
        ),
        _gate(
            "cache_boundary",
            "Durable provider, origin, privacy, security, and page identity remain exact while recognized HIT/MISS diagnostics may vary",
            cache_comparison.get("compatible") is True,
            f"Cache boundary is incompatible: {cache_comparison.get('reason_code')}.",
        ),
        _gate(
            "purge_count",
            "No cache purge occurred",
            observed.get("cache_purge_count", 0)
            == post.get("cache_purge_count", 0)
            == 0,
            "Cache purge count changed.",
        ),
        _gate(
            "pending_operations",
            "No Atlas lifecycle mutation is pending",
            not _pending_operation_exists(session),
            "Another Atlas lifecycle mutation is pending.",
        ),
        *backup_gates,
    ]
    inspected = {
        **observed,
        "plugin_status": _safe_plugin_status(plugin_status),
        "bootstrap_status": upgrade._safe_bootstrap_status(bootstrap_status),
        "cache_boundary_comparison": cache_comparison,
        "metadata_state_rows": len(states),
        "metadata_sync_audit_rows": len(sync_audits),
        "reconciliation_wordpress_write_count": 0,
        "reconciliation_plugin_write_count": 0,
        "reconciliation_cache_write_count": 0,
        "reconciliation_atlas_write_count": 0,
    }
    return inspected, gates, backup


def _backup(request, release, audit):
    summary = {
        "file_name": request.atlas_data_backup_file,
        "sha256": request.atlas_data_backup_sha256,
        "size": request.atlas_data_backup_size,
        "created_at": (
            request.atlas_data_backup_created_at.astimezone(UTC).isoformat()
            if request.atlas_data_backup_created_at.tzinfo
            else None
        ),
        "onedrive_path": request.atlas_data_backup_onedrive_path,
        "onedrive_synced": request.atlas_data_backup_onedrive_synced,
    }
    path = payload = None
    try:
        path = resolve_backup_download(request.atlas_data_backup_file)
        payload = load_backup(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        structural = True
    except (BackupValidationError, OSError, KeyError, TypeError, ValueError):
        digest = None
        structural = False
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    records = (
        payload.get("data", {}).get("wordpress_plugin_upgrade_audits", [])
        if isinstance(payload, dict)
        else []
    )
    backup_audit = next(
        (item for item in records if item.get("id") == AUDIT_ID),
        None,
    )
    try:
        created_at = _timestamp(metadata.get("created_at"))
        runtime_generated_at = _timestamp(release.get("generated_at"))
    except (TypeError, ValueError):
        created_at = runtime_generated_at = None
    onedrive_name = PureWindowsPath(request.atlas_data_backup_onedrive_path).name
    gates = [
        _gate(
            "atlas_data_backup_structure",
            "Fresh Atlas Data backup is structurally valid",
            structural,
            "Atlas Data backup is unavailable or structurally invalid.",
        ),
        _gate(
            "atlas_data_backup_identity",
            "Atlas Data backup filename, size, and SHA-256 are exact",
            bool(
                path
                and path.name == request.atlas_data_backup_file
                and onedrive_name == request.atlas_data_backup_file
                and path.stat().st_size == request.atlas_data_backup_size
                and digest == request.atlas_data_backup_sha256
            ),
            "Atlas Data backup filename, size, or checksum differs.",
        ),
        _gate(
            "atlas_data_backup_fresh",
            "Atlas Data backup was created after the loaded v0.59.96 runtime",
            bool(
                created_at
                and runtime_generated_at
                and request.atlas_data_backup_created_at.tzinfo
                and created_at == request.atlas_data_backup_created_at.astimezone(UTC)
                and created_at >= runtime_generated_at
            ),
            "Atlas Data backup predates the corrected runtime or has a mismatched timestamp.",
        ),
        _gate(
            "atlas_data_backup_audit",
            "Atlas Data backup preserves exact Audit ID 3 before reconciliation",
            bool(
                audit
                and backup_audit
                and backup_audit.get("status") == "verification_failed"
                and backup_audit.get("wordpress_write_count") == 1
                and backup_audit.get("atlas_write_count") == audit.atlas_write_count
                and backup_audit.get("transition_history") == audit.transition_history
                and backup_audit.get("reconciliation_reason") is None
            ),
            "Atlas Data backup does not preserve exact pre-reconciliation Audit ID 3.",
        ),
        _gate(
            "atlas_data_backup_onedrive",
            "OneDrive path and synchronization are explicitly confirmed",
            request.atlas_data_backup_onedrive_synced
            and onedrive_name == request.atlas_data_backup_file,
            "OneDrive backup synchronization is unconfirmed.",
        ),
    ]
    return summary, gates


def _binding(request, audit, inspected, backup, expires_at):
    rendered = inspected.get("rendered", {})
    public = rendered.get("public_http_observation", {})
    return {
        "action": "reconcile_metadata_bridge_upgrade_audit_3_without_wordpress_write",
        "audit": {
            "id": audit.id if audit else None,
            "status": audit.status if audit else None,
            "history": audit.transition_history if audit else None,
            "wordpress_write_count": audit.wordpress_write_count if audit else None,
            "atlas_write_count": audit.atlas_write_count if audit else None,
            "row_identity": _audit_identity(audit),
        },
        "runtime": request.expected_runtime_identity.model_dump(mode="json"),
        "repository": {
            "head": request.repository_head,
            "origin_main": request.repository_origin_main,
            "tag": request.repository_tag,
            "branch": request.repository_branch,
            "clean": request.repository_working_tree_clean,
            "protected": request.protected_paths_unchanged,
        },
        "backup": backup,
        "evidence": {
            "id": request.manual_browser_evidence.evidence_id,
            "signature": request.manual_browser_evidence.helper_signature,
            "expires_at": str(request.manual_browser_evidence.expires_at),
            "head_hash": request.manual_browser_evidence.rendered_head_hash,
            "visible_hash": request.manual_browser_evidence.visible_content_hash,
        },
        "durable_observation": {
            "plugin_inventory": inspected.get("plugin_inventory_hash"),
            "active_inventory": inspected.get("active_plugin_inventory_hash"),
            "page": inspected.get("page_snapshot_hash"),
            "body": inspected.get("page_body_hash"),
            "media31": inspected.get("media31_snapshot_hash"),
            "media32": inspected.get("media32_snapshot_hash"),
            "site": inspected.get("site"),
            "head_hash": rendered.get("head_hash"),
            "visible_hash": rendered.get("visible_hash"),
            "origin": public.get("origin"),
            "provider_family": public.get("provider_family"),
            "privacy": public.get("privacy_classification"),
            "response_source": public.get("response_source"),
            "status_code": rendered.get("status_code"),
            "final_url": rendered.get("final_url"),
            "redirect_count": rendered.get("redirect_count"),
            "plugin_status": inspected.get("plugin_status"),
            "bootstrap_status": inspected.get("bootstrap_status"),
        },
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


def _audit_identity(audit):
    if audit is None:
        return None
    return _hash(
        {
            "id": audit.id,
            "status": audit.status,
            "history": audit.transition_history,
            "binding_hash": audit.binding_hash,
            "handle_fingerprint": audit.handle_fingerprint,
            "versions": [audit.previous_version, audit.target_version],
            "artifacts": [
                audit.previous_artifact_sha256,
                audit.target_artifact_sha256,
            ],
            "wordpress_write_count": audit.wordpress_write_count,
            "atlas_write_count": audit.atlas_write_count,
            "post_snapshot": audit.post_snapshot,
            "gate_results": audit.gate_results,
            "verification_findings": audit.verification_findings,
        }
    )


def _safe_plugin_status(value):
    return {
        key: value.get(key)
        for key in ("plugin", "version", "checksum", "active", "snapshot")
        if key in value
    }


def _target(page_id, audit_id):
    if page_id != 41:
        raise HTTPException(404, "Upgrade reconciliation is limited to Atlas page 41.")
    if audit_id != AUDIT_ID:
        raise HTTPException(404, "Upgrade reconciliation is limited to Audit ID 3.")


def _store(request, audit_id, binding_hash, expires_at):
    handle = secrets.token_urlsafe(32)
    entry = _ReconciliationHandle(
        request=request.model_copy(deep=True),
        audit_id=audit_id,
        binding_hash=binding_hash,
        expires_at=expires_at,
    )
    with _lock:
        _handles[handle] = entry
        timer = Timer(
            max(0.0, (expires_at - datetime.now(UTC)).total_seconds()),
            _discard,
            args=(handle,),
        )
        timer.daemon = True
        _timers[handle] = timer
        timer.start()
    return handle


def _consume(handle):
    with _lock:
        entry = _handles.pop(handle, None)
        timer = _timers.pop(handle, None)
        if timer:
            timer.cancel()
    if entry is None:
        raise HTTPException(
            422,
            "Upgrade reconciliation handle is unknown, expired, consumed, "
            "cross-operation, or restart-invalidated.",
        )
    if entry.expires_at <= datetime.now(UTC):
        raise HTTPException(422, "Upgrade reconciliation handle expired.")
    return entry


def _discard(handle):
    with _lock:
        _handles.pop(handle, None)
        timer = _timers.pop(handle, None)
        if timer:
            timer.cancel()


def _clear_reconciliation_handles():
    with _lock:
        for timer in _timers.values():
            timer.cancel()
        _handles.clear()
        _timers.clear()


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp is unavailable.")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware.")
    return parsed.astimezone(UTC)


def _hash(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
