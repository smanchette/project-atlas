"""Audited manual bootstrap handoff plus one fixed-entry guarded activation.

Atlas never uploads plugin bytes.  The sole WordPress mutation in this module is
the hard-coded activation of the locked 0.3.0 bootstrap entry.  The inactive
entry cannot be checksummed through WordPress core, so it remains quarantined
until its fixed authenticated status route proves the executable checksum.
"""

from __future__ import annotations

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

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    WordPressActivationAudit,
    WordPressBootstrapCleanupAudit,
    WordPressBootstrapEstablishmentAudit,
    WordPressCacheAwareRenderingAudit,
    WordPressMetadataLifecycleAudit,
    WordPressMetadataState,
    WordPressMetadataSyncAudit,
    WordPressPluginUpgradeAudit,
)
from app.db.backup import BackupValidationError, load_backup, resolve_backup_download
from app.schemas.wordpress import (
    WordPressBootstrapActivationApplyRequest,
    WordPressBootstrapActivationReconciliationApplyRequest,
    WordPressBootstrapActivationReconciliationPreflight,
    WordPressBootstrapActivationReconciliationRequest,
    WordPressBootstrapActivationReconciliationResult,
    WordPressBootstrapAuthorizationRetirementApplyRequest,
    WordPressBootstrapAuthorizationRetirementPreflight,
    WordPressBootstrapAuthorizationRetirementRequest,
    WordPressBootstrapAuthorizationRetirementResult,
    WordPressBootstrapBackupRenewalApplyRequest,
    WordPressBootstrapBackupRenewalPreflight,
    WordPressBootstrapBackupRenewalRecovery,
    WordPressBootstrapBackupRenewalRecoveryRequest,
    WordPressBootstrapBackupRenewalRequest,
    WordPressBootstrapBackupRenewalResult,
    WordPressBootstrapEstablishmentPreflight,
    WordPressBootstrapEstablishmentResult,
    WordPressBootstrapManualInstallAuthorizeRequest,
    WordPressBootstrapManualInstallPreflightRequest,
    WordPressBootstrapManualInstallVerifyRequest,
    WordPressBootstrapInstalledInactiveAuthorizeRequest,
    WordPressBootstrapRecoveryAssessment,
    WordPressDraftGateResult,
)
from app.services import wordpress_plugin_upgrade_0577 as upgrade
from app.services import wordpress_cache_aware_rendering as cache_binding
from app.services.wordpress_deployment import _canonical_plugins, _gate, _observe, deployment_readiness
from app.services.wordpress_http import wordpress_basic_auth, wordpress_http_client
from app.services.wordpress_sandbox import get_wordpress_application_password, read_wordpress_settings


BOOTSTRAP_SLUG = "project-atlas-upgrade-bootstrap"
BOOTSTRAP_DIRECTORY = BOOTSTRAP_SLUG
BOOTSTRAP_ENTRY = f"{BOOTSTRAP_DIRECTORY}/project-atlas-upgrade-bootstrap.php"
BOOTSTRAP_REST_ID = BOOTSTRAP_ENTRY.removesuffix(".php")
BOOTSTRAP_VERSION = "0.3.0"
BOOTSTRAP_ZIP = "project-atlas-upgrade-bootstrap-0.3.0.zip"
BOOTSTRAP_ZIP_SHA256 = "de5bfb7875b6f84f2009ef2043c1c86c7f9d20f0f973a5cb16b478fe37e83bef"
BOOTSTRAP_ENTRY_SHA256 = "a977c077573ab732213a06d17dcc317b09854564777ce9cb24c869383972cd53"
MANUAL_PHRASE = "AUTHORIZE MANUAL UPLOAD OF PROJECT ATLAS UPGRADE BOOTSTRAP 0.3.0"
ACTIVATION_PHRASE = "ACTIVATE PROJECT ATLAS UPGRADE BOOTSTRAP 0.3.0"
ACTIVATION_RECONCILIATION_PHRASE = (
    "RECONCILE PROJECT ATLAS BOOTSTRAP ACTIVATION FOR AUDIT 2 "
    "WITHOUT ANOTHER WORDPRESS WRITE"
)
ACTIVATION_RECONCILIATION_REASON = (
    "post_activation_verifier_contract_defect_reconciled"
)
ACTIVATION_RECONCILIATION_HISTORY = ACTIVATION_RECONCILIATION_REASON
BACKUP_RENEWAL_PHRASE_PREFIX = "RENEW PROJECT ATLAS BOOTSTRAP HANDOFF BACKUP FOR AUDIT"
RETIREMENT_REASON = "manual_install_verification_genuine_transport_drift"
RETIREMENT_PHRASE_PREFIX = "RETIRE PROJECT ATLAS BOOTSTRAP AUTHORIZATION FOR AUDIT"
INSTALLED_INACTIVE_PHRASE = "AUTHORIZE PROJECT ATLAS EXISTING EXACT INACTIVE BOOTSTRAP 0.3.0"
MANUAL_BINDING_REASON_CODES = frozenset({
    "manual_upload_stable_observation_mismatch",
    "manual_upload_observation_expired",
    "manual_upload_observation_before_preflight",
    "manual_upload_observation_window_exceeded",
    "manual_upload_public_identity_drift",
    "manual_upload_rendered_hash_drift",
    "manual_upload_runtime_drift",
    "manual_upload_backup_drift",
    "manual_upload_volatile_timestamp_change_allowed",
})
HANDLE_TTL = timedelta(minutes=10)
BACKUP_WINDOW = timedelta(hours=4)
MAX_BACKUP_RENEWALS = 3
ACTIVATION_SCOPE = [
    f"POST /wp-json/wp/v2/plugins/{BOOTSTRAP_REST_ID}",
    'request JSON keys exactly ["status"] with value "active"',
]
ATLAS_SCOPE = [
    "create or update only one WordPressBootstrapEstablishmentAudit",
    "record state transitions and read-only verification findings",
]
_BASE_IGNORED_GATE_CODES = {
    "upgrade_bootstrap",
    "bootstrap_establishment_audit",
    "plugin_inventory",
    "active_inventory",
    "expected_post_inventory",
}
_VERIFICATION_FINGERPRINT_KEY = "_atlas_manual_install_verification_fingerprint"
_VERIFICATION_PROOF_KEY = "_atlas_manual_install_verification_proof"
_AUTHORIZATION_EVIDENCE_KEY = "_atlas_authorization_evidence"
_VERIFICATION_EVIDENCE_KEY = "_atlas_verification_evidence"
TRANSPORT_IDENTITY_VERSION = "project-atlas-public-transport-identity-v2"
TRANSPORT_COMPATIBILITY_REASON = "manual_install_verification_transport_compatibility_applied"


@dataclass(frozen=True)
class _Handle:
    request: WordPressBootstrapManualInstallPreflightRequest | WordPressBootstrapManualInstallVerifyRequest
    binding_hash: str
    expires_at: datetime
    audit_id: int | None
    stable_rendered_fingerprint: str
    stable_rendered_observation: dict[str, Any]
    preflight_observed_at: datetime
    evidence_expires_at: datetime
    backup_deadline: datetime
    issued_at: datetime
    maximum_interval: timedelta
    clock_reversal_tolerance: timedelta


@dataclass(frozen=True)
class _RenewalHandle:
    request: WordPressBootstrapBackupRenewalRequest
    audit_id: int
    binding_hash: str
    expires_at: datetime
    fingerprint: str


@dataclass(frozen=True)
class _RetirementHandle:
    request: WordPressBootstrapAuthorizationRetirementRequest
    audit_id: int
    binding_hash: str
    expires_at: datetime


@dataclass(frozen=True)
class _ActivationReconciliationHandle:
    request: WordPressBootstrapActivationReconciliationRequest
    audit_id: int
    binding_hash: str
    expires_at: datetime


_lock = RLock()
_manual_handles: dict[str, _Handle] = {}
_activation_handles: dict[str, _Handle] = {}
_renewal_handles: dict[str, _RenewalHandle] = {}
_installed_handles: dict[str, _Handle] = {}
_retirement_handles: dict[str, _RetirementHandle] = {}
_activation_reconciliation_handles: dict[str, _ActivationReconciliationHandle] = {}
_timers: dict[tuple[str, str], Timer] = {}


def manual_install_preflight(session: Session, page_id: int, request: WordPressBootstrapManualInstallPreflightRequest) -> WordPressBootstrapEstablishmentPreflight:
    base = upgrade.plugin_upgrade_preflight(session, page_id, request, issue_handle=False)
    classification = _classify(base.inspected_state.get("plugins", []))
    temporal = _preflight_temporal_contract(request, base.inspected_state, base.backup_deadline)
    gates = _base_gates(base) + [
        _gate("bootstrap_absent", "No bootstrap is installed before manual upload", classification["classification"] == "no_upload_yet", "A bootstrap or conflicting installation already exists."),
        _gate("establishment_clear", "No unresolved bootstrap-establishment audit exists", not _unresolved(session), "An unresolved bootstrap-establishment audit already exists."),
        *temporal["gates"],
    ]
    ready = all(g.passed for g in gates)
    expires_at = _expiry(request) if ready else None
    stable = _stable_rendered_observation(base.inspected_state, request.manual_browser_evidence)
    stable_fingerprint = _hash(stable)
    binding = _binding(
        request, base.inspected_state, None, "manual_upload", expires_at,
        stable_rendered_fingerprint=stable_fingerprint,
        preflight_observed_at=temporal["observed_at"],
        evidence_expires_at=temporal["evidence_expires_at"],
        backup_deadline=temporal["backup_deadline"],
    )
    handle = _store(
        "manual", request, _hash(binding), expires_at, None,
        stable_rendered_fingerprint=stable_fingerprint,
        stable_rendered_observation=stable,
        preflight_observed_at=temporal["observed_at"],
        evidence_expires_at=temporal["evidence_expires_at"],
        backup_deadline=temporal["backup_deadline"],
    ) if ready and expires_at and temporal["complete"] else None
    return _preflight_response(
        "bootstrap_manual_install_preflight", ready, "manual_install_preflight_ready" if ready else "manual_install_preflight_blocked",
        base, gates, binding, handle, expires_at, classification,
        instructions=[
            f"Open WordPress Admin, then Plugins -> Add New Plugin -> Upload Plugin.",
            f"Choose only {BOOTSTRAP_ZIP} (SHA-256 {BOOTSTRAP_ZIP_SHA256}) and install it.",
            "Do not activate the plugin. Return to Atlas and run read-only verification.",
            "Do not upload a different ZIP and do not delete or replace another plugin.",
        ] if ready else [],
    )


def authorize_manual_install(session: Session, page_id: int, request: WordPressBootstrapManualInstallAuthorizeRequest) -> WordPressBootstrapEstablishmentResult:
    if page_id != 41:
        raise HTTPException(404, "Bootstrap establishment is limited to Atlas page 41.")
    if not hmac.compare_digest(request.confirmation_phrase, MANUAL_PHRASE):
        raise HTTPException(422, "The manual bootstrap-upload authorization phrase is incorrect.")
    entry = _consume("manual", request.manual_install_handle)
    base = upgrade.plugin_upgrade_preflight(session, page_id, entry.request, issue_handle=False)
    classification = _classify(base.inspected_state.get("plugins", []))
    gates = _base_gates(base) + [
        _gate("bootstrap_absent", "No bootstrap is installed before manual upload", classification["classification"] == "no_upload_yet", "A bootstrap or conflicting installation already exists."),
        _gate("establishment_clear", "No unresolved bootstrap-establishment audit exists", not _unresolved(session), "An unresolved bootstrap-establishment audit already exists."),
    ]
    rerun_stable = _stable_rendered_observation(base.inspected_state, entry.request.manual_browser_evidence)
    rerun_fingerprint = _hash(rerun_stable)
    rerun_observed_at = _rendered_observed_at(base.inspected_state)
    conflict = _stable_rendered_conflict(entry.stable_rendered_observation, rerun_stable)
    if conflict:
        _raise_manual_conflict(conflict, "Stable rendered-page identity changed after manual-upload preflight.")
    temporal_conflict = _manual_temporal_conflict(entry, rerun_observed_at)
    if temporal_conflict:
        _raise_manual_conflict(temporal_conflict, "The authorization observation is outside the bound temporal contract.")
    rerun_binding = _hash(_binding(
        entry.request, base.inspected_state, None, "manual_upload", entry.expires_at,
        stable_rendered_fingerprint=rerun_fingerprint,
        preflight_observed_at=entry.preflight_observed_at,
        evidence_expires_at=entry.evidence_expires_at,
        backup_deadline=entry.backup_deadline,
    ))
    if not all(g.passed for g in gates):
        _raise_manual_conflict(_manual_gate_conflict(gates), "A live authorization gate changed after preflight.")
    if rerun_fingerprint != entry.stable_rendered_fingerprint or rerun_binding != entry.binding_hash:
        _raise_manual_conflict("manual_upload_stable_observation_mismatch", "A stable runtime, backup, plugin, payload, page, media, audit, or rendered binding changed.")
    if rerun_observed_at != entry.preflight_observed_at:
        gates.append(_gate("manual_upload_volatile_timestamp_change_allowed", "Authorization observation timestamp advanced inside the bound window", True, ""))
    evidence = entry.request.manual_browser_evidence
    audit = WordPressBootstrapEstablishmentAudit(
        generated_page_id=41, wordpress_post_id=8,
        installation_audit_id=entry.request.installation_audit_id,
        activation_audit_id=entry.request.activation_audit_id,
        authorization_mode="manual_upload",
        status="awaiting_manual_bootstrap_installation", operator=entry.request.operator,
        bootstrap_slug=BOOTSTRAP_SLUG, bootstrap_directory=BOOTSTRAP_DIRECTORY,
        bootstrap_path=BOOTSTRAP_ENTRY, bootstrap_version=BOOTSTRAP_VERSION,
        bootstrap_zip_filename=BOOTSTRAP_ZIP, bootstrap_zip_sha256=BOOTSTRAP_ZIP_SHA256,
        bootstrap_entry_sha256=BOOTSTRAP_ENTRY_SHA256,
        manual_phrase_hash=_sha(MANUAL_PHRASE), activation_phrase_hash=_sha(ACTIVATION_PHRASE),
        manual_handle_fingerprint=_sha(request.manual_install_handle), manual_binding_hash=entry.binding_hash,
        release_identity=entry.request.expected_runtime_identity.model_dump(mode="json"),
        backup_evidence=_backup(entry.request), browser_evidence_id=evidence.evidence_id if evidence else "",
        pre_snapshot={
            **base.inspected_state,
            _AUTHORIZATION_EVIDENCE_KEY: _evidence_record(
                evidence, base.inspected_state, result="authorization_committed"
            ),
        },
        source_inventories=_inventories(base.inspected_state),
        protected_state=_protected(base.inspected_state),
        gate_results=[g.model_dump(mode="json") for g in gates],
        inactive_checksum_verifiable=False, approved_residual_risk=True,
        atlas_write_count=1, atlas_write_scope=ATLAS_SCOPE,
        transition_history=["awaiting_manual_bootstrap_installation"],
        recovery_recommendation="continue_manual_upload",
    )
    session.add(audit); session.commit(); session.refresh(audit)
    return _result(
        audit, "manual_upload_authorized", gates, base.inspected_state, "continue_manual_upload",
        request_atlas_write_count=1, reason_code="manual_upload_authorization_committed",
    )


def installed_inactive_preflight(
    session: Session, page_id: int, request: WordPressBootstrapManualInstallPreflightRequest,
) -> WordPressBootstrapEstablishmentPreflight:
    base = upgrade.plugin_upgrade_preflight(session, page_id, request, issue_handle=False)
    classification = _classify(base.inspected_state.get("plugins", []))
    temporal = _preflight_temporal_contract(request, base.inspected_state, base.backup_deadline)
    retired = list(session.exec(select(WordPressBootstrapEstablishmentAudit).where(
        WordPressBootstrapEstablishmentAudit.status == "authorization_retired"
    )))
    reused_evidence, reused_backup = _retired_identity_reuse(retired, request)
    current_transport = _stable_verification_observation(base.inspected_state).get("public_transport", {})
    gates = _base_gates(base) + [
        _gate("bootstrap_exact_inactive", "The exact Bootstrap 0.3.0 is installed once and inactive", classification["classification"] == "exact_inactive", "The installed Bootstrap is missing, active, duplicated, conflicting, or the wrong version."),
        _gate("establishment_clear", "No unresolved bootstrap-establishment audit exists", not _unresolved(session), "An unresolved bootstrap-establishment audit already exists."),
        _gate("retired_history", "A prior stale authorization is preserved as retired history", bool(retired), "No retired authorization history is available."),
        _gate("fresh_evidence_identity", "Fresh authorization evidence is not reused", not reused_evidence, "Browser evidence was used by a retired authorization."),
        _gate("fresh_backup_identity", "Fresh authorization backups are not reused", not reused_backup, "Backup identity was used by a retired authorization."),
        _gate("current_public_transport", "Current transport is provider-verified HTTP 200 cached public HTML", _current_cached_public_transport(current_transport), "Current transport is not the required SiteGround/nginx cached-public identity."),
        *temporal["gates"],
    ]
    ready = all(g.passed for g in gates)
    expires_at = _expiry(request) if ready else None
    stable = _stable_rendered_observation(base.inspected_state, request.manual_browser_evidence)
    binding = _binding(
        request, base.inspected_state, None, "existing_exact_inactive_bootstrap", expires_at,
        stable_rendered_fingerprint=_hash(stable), preflight_observed_at=temporal["observed_at"],
        evidence_expires_at=temporal["evidence_expires_at"], backup_deadline=temporal["backup_deadline"],
    )
    handle = _store(
        "installed", request, _hash(binding), expires_at, None,
        stable_rendered_fingerprint=_hash(stable), stable_rendered_observation=stable,
        preflight_observed_at=temporal["observed_at"], evidence_expires_at=temporal["evidence_expires_at"],
        backup_deadline=temporal["backup_deadline"],
    ) if ready and expires_at and temporal["complete"] else None
    return _preflight_response(
        "bootstrap_installed_inactive_preflight", ready,
        "installed_inactive_authorization_ready" if ready else "installed_inactive_authorization_blocked",
        base, gates, binding, handle, expires_at, classification,
        instructions=[
            "Do not upload, reinstall, replace, delete, or activate Bootstrap.",
            "Authorize the already-installed exact inactive Bootstrap only, then capture separate fresh evidence for inventory verification.",
        ] if ready else [],
    ).model_copy(update={"confirmation_phrase": INSTALLED_INACTIVE_PHRASE if ready else None})


def authorize_installed_inactive(
    session: Session, page_id: int, request: WordPressBootstrapInstalledInactiveAuthorizeRequest,
) -> WordPressBootstrapEstablishmentResult:
    if page_id != 41:
        raise HTTPException(404, "Bootstrap establishment is limited to Atlas page 41.")
    if not hmac.compare_digest(request.confirmation_phrase, INSTALLED_INACTIVE_PHRASE):
        raise HTTPException(422, "The installed-inactive Bootstrap authorization phrase is incorrect.")
    entry = _consume("installed", request.installed_bootstrap_handle)
    base = upgrade.plugin_upgrade_preflight(session, page_id, entry.request, issue_handle=False)
    classification = _classify(base.inspected_state.get("plugins", []))
    retired = list(session.exec(select(WordPressBootstrapEstablishmentAudit).where(
        WordPressBootstrapEstablishmentAudit.status == "authorization_retired"
    )))
    reused_evidence, reused_backup = _retired_identity_reuse(retired, entry.request)
    stable = _stable_rendered_observation(base.inspected_state, entry.request.manual_browser_evidence)
    gates = _base_gates(base) + [
        _gate("bootstrap_exact_inactive", "The exact Bootstrap 0.3.0 remains installed once and inactive", classification["classification"] == "exact_inactive", "Installed Bootstrap state changed."),
        _gate("establishment_clear", "No unresolved bootstrap-establishment audit exists", not _unresolved(session), "An unresolved audit exists."),
        _gate("fresh_evidence_identity", "Evidence remains fresh and distinct", not reused_evidence, "Evidence identity was reused."),
        _gate("fresh_backup_identity", "Backup identity remains fresh and distinct", not reused_backup, "Backup identity was reused."),
        _gate("current_public_transport", "Current transport remains provider-verified HTTP 200 cached public HTML", _current_cached_public_transport(_stable_verification_observation(base.inspected_state).get("public_transport", {})), "Current transport changed."),
    ]
    binding = _hash(_binding(
        entry.request, base.inspected_state, None, "existing_exact_inactive_bootstrap", entry.expires_at,
        stable_rendered_fingerprint=_hash(stable), preflight_observed_at=entry.preflight_observed_at,
        evidence_expires_at=entry.evidence_expires_at, backup_deadline=entry.backup_deadline,
    ))
    if not all(g.passed for g in gates) or binding != entry.binding_hash:
        raise HTTPException(409, "Installed-inactive authorization state changed; no audit was created.")
    evidence = entry.request.manual_browser_evidence
    audit = WordPressBootstrapEstablishmentAudit(
        generated_page_id=41, wordpress_post_id=8,
        installation_audit_id=entry.request.installation_audit_id,
        activation_audit_id=entry.request.activation_audit_id,
        authorization_mode="existing_exact_inactive_bootstrap",
        status="awaiting_manual_bootstrap_installation", operator=entry.request.operator,
        bootstrap_slug=BOOTSTRAP_SLUG, bootstrap_directory=BOOTSTRAP_DIRECTORY,
        bootstrap_path=BOOTSTRAP_ENTRY, bootstrap_version=BOOTSTRAP_VERSION,
        bootstrap_zip_filename=BOOTSTRAP_ZIP, bootstrap_zip_sha256=BOOTSTRAP_ZIP_SHA256,
        bootstrap_entry_sha256=BOOTSTRAP_ENTRY_SHA256,
        manual_phrase_hash=_sha(INSTALLED_INACTIVE_PHRASE), activation_phrase_hash=_sha(ACTIVATION_PHRASE),
        manual_handle_fingerprint=_sha(request.installed_bootstrap_handle), manual_binding_hash=entry.binding_hash,
        release_identity=entry.request.expected_runtime_identity.model_dump(mode="json"),
        backup_evidence=_backup(entry.request), browser_evidence_id=evidence.evidence_id if evidence else "",
        pre_snapshot={**base.inspected_state, _AUTHORIZATION_EVIDENCE_KEY: _evidence_record(evidence, base.inspected_state, result="installed_inactive_authorization_committed")},
        source_inventories=_inventories(base.inspected_state), protected_state=_protected(base.inspected_state),
        gate_results=[g.model_dump(mode="json") for g in gates], inactive_checksum_verifiable=False,
        approved_residual_risk=True, atlas_write_count=1, atlas_write_scope=ATLAS_SCOPE,
        transition_history=["awaiting_manual_bootstrap_installation"],
        recovery_recommendation="capture_fresh_evidence_then_verify_installed_inventory",
    )
    session.add(audit); session.commit(); session.refresh(audit)
    return _result(audit, "installed_inactive_authorization_committed", gates, base.inspected_state,
                   "capture_fresh_evidence_then_verify_installed_inventory", request_atlas_write_count=1,
                   reason_code="installed_inactive_authorization_committed")


def retirement_preflight(
    session: Session, page_id: int, request: WordPressBootstrapAuthorizationRetirementRequest,
) -> WordPressBootstrapAuthorizationRetirementPreflight:
    if page_id != 41:
        raise HTTPException(404, "Bootstrap establishment is limited to Atlas page 41.")
    audit = _audit(session, request.establishment_audit_id)
    observed = _observe(session, None)
    classification = _classify(observed.get("plugins", []))
    comparison_snapshot = _retirement_comparison_snapshot(audit, observed)
    comparison = _verification_stable_comparison(audit, comparison_snapshot)
    genuine = _genuine_transport_retirement_drift(audit, comparison_snapshot, comparison)
    runtime_matches = _retirement_runtime_matches(request)
    gates = [
        _gate("audit_status", "Audit awaits pre-activation manual verification", audit.status == "awaiting_manual_bootstrap_installation", "Audit is not retirement-eligible."),
        _gate("reason", "Retirement reason is the supported genuine-transport reason", request.retirement_reason == RETIREMENT_REASON, "Retirement reason is unsupported."),
        _gate("authorization_snapshot", "Original authorization snapshot is preserved", bool(audit.pre_snapshot), "Authorization snapshot is missing."),
        _gate("verification_absent", "Verification evidence is absent", _verification_evidence_record(audit) is None, "Verification evidence already exists."),
        _gate("activation_absent", "Activation and checksum quarantine never started", not audit.activation_handle_fingerprint and not audit.checksum_verification_result, "Activation or checksum verification started."),
        _gate("pending_operation", "No conflicting Atlas operation is pending", not _pending_operation_exists(session), "Another operation is pending."),
        _gate("runtime_identity", "The independently expected runtime identity is verified and exact", runtime_matches, "Runtime identity is unavailable or mismatched."),
        _gate("credentials", "Authenticated WordPress GET observations are available", "_error" not in observed and observed.get("wordpress_request_performed") is True, "WordPress application-password credentials are unavailable."),
        _gate("read_only", "Every WordPress observation is GET-only", observed.get("read_only") is True and observed.get("wordpress_request_methods") == ["GET"], "A non-read-only observation was attempted."),
        _gate("bootstrap_exact_inactive", "Bootstrap is exact, single, and inactive", classification["classification"] == "exact_inactive", "Bootstrap is not exact inactive."),
        _gate("public_identity", "Current public HTML hashes match the preserved signed page identity", _retirement_public_identity_matches(audit, observed), "Current unsigned public HTML cannot be bound to the preserved signed identity."),
        _gate("genuine_transport_drift", "Durable 403 block and current 200 HIT are canonically incompatible", genuine, "Genuine canonical transport drift is not proven."),
        _gate("zero_mutation", "Retirement requires no WordPress, plugin, or cache mutation", True, ""),
    ]
    ready = all(g.passed for g in gates)
    expires_at = datetime.now(UTC) + HANDLE_TTL if ready else None
    phrase = _retirement_phrase(audit.id or 0)
    binding = _retirement_binding(audit, request, comparison, expires_at)
    handle = _store_retirement(request, audit.id or 0, _hash(binding), expires_at) if ready and expires_at else None
    return WordPressBootstrapAuthorizationRetirementPreflight(
        establishment_audit_id=audit.id or 0, ready=ready,
        status="authorization_retirement_ready" if ready else "authorization_retirement_blocked",
        current_status=audit.status, retirement_reason=request.retirement_reason,
        transport_comparison=_safe_transport_retirement_summary(audit, comparison_snapshot, comparison),
        expected_transition=[audit.status, "authorization_retired"],
        confirmation_phrase=phrase if ready else None, retirement_handle=handle,
        handle_fingerprint=_sha(handle) if handle else None, expires_at=expires_at,
        gate_results=gates,
    )


def apply_retirement(
    session: Session, page_id: int, request: WordPressBootstrapAuthorizationRetirementApplyRequest,
) -> WordPressBootstrapAuthorizationRetirementResult:
    if page_id != 41:
        raise HTTPException(404, "Bootstrap establishment is limited to Atlas page 41.")
    entry = _consume_retirement(request.retirement_handle)
    if not hmac.compare_digest(request.confirmation_phrase, _retirement_phrase(entry.audit_id)):
        raise HTTPException(422, "The bootstrap-authorization retirement phrase is incorrect.")
    with _lock:
        audit = _audit_for_update(session, entry.audit_id)
        if audit.status == "authorization_retired" and audit.retirement_reason == RETIREMENT_REASON:
            return _retirement_result(audit, idempotent=True)
        rerun = retirement_preflight(session, page_id, entry.request)
        _discard_retirement(rerun.retirement_handle)
        if not rerun.ready or _hash(_retirement_binding(audit, entry.request, {"reason_code": rerun.transport_comparison.get("reason_code")}, entry.expires_at)) != entry.binding_hash:
            raise HTTPException(409, "Retirement state changed after preflight; no audit transition occurred.")
        original_snapshot = _hash(audit.pre_snapshot)
        original_renewals = _hash(audit.backup_renewals or [])
        audit.status = "authorization_retired"
        audit.retirement_reason = RETIREMENT_REASON
        audit.transition_history = [*audit.transition_history, "authorization_retired"]
        audit.atlas_write_count += 1
        audit.atlas_write_scope = [*audit.atlas_write_scope, "retire stale authorization without WordPress mutation"]
        audit.recovery_recommendation = "fresh_authorization_required"
        audit.completed_at = datetime.now(UTC)
        session.add(audit); session.commit(); session.refresh(audit)
        if _hash(audit.pre_snapshot) != original_snapshot or _hash(audit.backup_renewals or []) != original_renewals:
            raise RuntimeError("Retirement altered immutable authorization history.")
        return _retirement_result(audit, request_atlas_write_count=1)


def verify_manual_install(session: Session, page_id: int, request: WordPressBootstrapManualInstallVerifyRequest) -> WordPressBootstrapEstablishmentResult:
    if page_id != 41:
        raise HTTPException(404, "Bootstrap establishment is limited to Atlas page 41.")
    # Serialize the complete decision and durable transition in this backend
    # process, while SELECT ... FOR UPDATE provides the corresponding database
    # row lock on PostgreSQL. SQLite ignores the row-lock clause in tests, so
    # the process lock supplies the equivalent serialization there.
    with _lock:
        audit = _audit_for_update(session, request.establishment_audit_id)
        if audit.status not in {"awaiting_manual_bootstrap_installation", "manual_installation_inventory_verified"}:
            raise HTTPException(409, "The establishment audit is not awaiting manual-upload verification.")
        _require_fresh_verification_evidence(audit, request)
        base, gates, classification = _inspect_against_audit(session, page_id, request, audit, require_inactive=True)
        kind = classification["classification"]

        if audit.status == "manual_installation_inventory_verified":
            retry_fingerprint = _verification_fingerprint(request, base.inspected_state, classification, audit)
            committed_fingerprint = _committed_verification_fingerprint(audit)
            if (
                all(g.passed for g in gates)
                and kind == "exact_inactive"
                and not _retry_stale(request)
                and hmac.compare_digest(retry_fingerprint, committed_fingerprint)
            ):
                return _result(
                    audit, "bootstrap_manual_install_verification", gates,
                    {**base.inspected_state, "bootstrap_classification": classification, "inactive_checksum_verifiable": False},
                    "proceed_to_guarded_activation", idempotent_replay=True,
                    reason_code="manual_install_verification_idempotent_replay",
                )
            reason = _retry_conflict_reason(request, base.inspected_state, classification, audit, gates)
            raise HTTPException(
                409,
                detail={
                    "reason_code": reason,
                    "message": "Manual-install verification already finalized; the retry is not equivalent and made no durable change.",
                },
            )

        # Before the monotonic success checkpoint, retain the established
        # fail-closed state transitions for genuine upload failures.
        if kind == "no_upload_yet":
            return _result(audit, "bootstrap_manual_install_verification", gates, {**base.inspected_state, "bootstrap_classification": classification}, "continue_manual_upload", reason_code="manual_install_upload_not_observed")
        if kind == "exact_active":
            return _transition(session, audit, "manual_activation_detected", gates, base.inspected_state, "reconcile_manual_activation")
        if not all(g.passed for g in gates):
            if kind == "exact_inactive":
                _raise_verification_conflict(
                    _verification_stable_drift_reason(audit, base.inspected_state)
                    or _verification_gate_reason(gates),
                    "Fresh manual-install verification did not match the authorized stable state.",
                )
            status = "installation_partial" if kind == "installation_partial" else "manual_installation_mismatch"
            recommendation = "siteground_restore" if not _protected_equal(audit, base.inspected_state) else "guarded_bootstrap_recovery"
            return _transition(session, audit, status, gates, base.inspected_state, recommendation)

        proof = _verification_proof(request, base.inspected_state, classification, audit)
        fingerprint = _hash(proof)
        comparison = _verification_stable_comparison(audit, base.inspected_state)
        verification_evidence = _evidence_record(
            request.manual_browser_evidence,
            base.inspected_state,
            result="stable_identity_matched",
            comparison=comparison,
        )
        audit.upload_snapshot = {
            **base.inspected_state,
            _VERIFICATION_PROOF_KEY: proof,
            _VERIFICATION_FINGERPRINT_KEY: fingerprint,
            _VERIFICATION_EVIDENCE_KEY: verification_evidence,
        }
        audit.upload_inventories = _inventories(base.inspected_state)
        audit.status = "manual_installation_inventory_verified"
        audit.transition_history = [*audit.transition_history, audit.status]
        audit.atlas_write_count += 1
        audit.recovery_recommendation = "proceed_to_guarded_activation"
        audit.gate_results = [g.model_dump(mode="json") for g in gates]
        session.add(audit); session.commit(); session.refresh(audit)
        return _result(
            audit, "bootstrap_manual_install_verification", gates,
            {**base.inspected_state, "bootstrap_classification": classification, "inactive_checksum_verifiable": False},
            "proceed_to_guarded_activation", request_atlas_write_count=1,
            reason_code="manual_install_verification_committed",
        )


def backup_renewal_preflight(
    session: Session,
    page_id: int,
    request: WordPressBootstrapBackupRenewalRequest,
) -> WordPressBootstrapBackupRenewalPreflight:
    if page_id != 41:
        raise HTTPException(404, "Bootstrap backup renewal is limited to Atlas page 41.")
    audit = _audit(session, request.establishment_audit_id)
    replacement = _replacement_backup(request)
    duplicate = _latest_renewal_matches(audit, replacement)
    gates = _backup_renewal_gates(session, audit, request, duplicate=duplicate)
    ready = all(gate.passed for gate in gates)
    expires_at = min(datetime.now(UTC) + HANDLE_TTL, _timestamp(replacement["deadline"])) if ready else None
    fingerprint = _store_renewal(request, audit, expires_at) if ready and expires_at else None
    reason = (
        "bootstrap_backup_renewal_already_finalized"
        if ready and duplicate
        else "bootstrap_backup_renewal_ready"
        if ready
        else _backup_renewal_failure_reason(gates)
    )
    return WordPressBootstrapBackupRenewalPreflight(
        establishment_audit_id=audit.id or 0,
        status="bootstrap_backup_renewal_preflight_ready" if ready else "bootstrap_backup_renewal_preflight_blocked",
        ready=ready,
        reason_code=reason,
        renewal_handle_fingerprint=fingerprint,
        expires_at=expires_at,
        confirmation_phrase=_backup_renewal_phrase(audit.id or 0) if ready else None,
        original_backup=_original_backup(audit),
        active_backup=_active_backup(audit),
        proposed_replacement=replacement,
        renewal_sequence=len(audit.backup_renewals or []) + (0 if duplicate else 1),
        gate_results=gates,
    )


def apply_backup_renewal(
    session: Session,
    page_id: int,
    request: WordPressBootstrapBackupRenewalApplyRequest,
) -> WordPressBootstrapBackupRenewalResult:
    if page_id != 41:
        raise HTTPException(404, "Bootstrap backup renewal is limited to Atlas page 41.")
    entry = _consume_renewal(request.renewal_handle_fingerprint)
    phrase = _backup_renewal_phrase(entry.audit_id)
    if not hmac.compare_digest(request.confirmation_phrase, phrase):
        raise HTTPException(422, detail={"reason_code": "bootstrap_backup_renewal_conflict", "message": "The backup-renewal phrase is incorrect."})
    with _lock:
        audit = _audit_for_update(session, entry.audit_id)
        replacement = _replacement_backup(entry.request)
        duplicate = _latest_renewal_matches(audit, replacement)
        gates = _backup_renewal_gates(session, audit, entry.request, duplicate=duplicate)
        if not all(gate.passed for gate in gates):
            raise HTTPException(409, detail={"reason_code": _backup_renewal_failure_reason(gates), "message": "Backup-renewal state changed after preflight; no durable mutation occurred."})
        if duplicate:
            return _backup_renewal_result(audit, idempotent=True)
        binding = _backup_renewal_binding(audit, replacement)
        if not hmac.compare_digest(_hash(binding), entry.binding_hash):
            raise HTTPException(409, detail={"reason_code": "bootstrap_backup_renewal_state_drift", "message": "The renewal binding changed after preflight."})
        sequence = len(audit.backup_renewals or []) + 1
        record = {
            "sequence": sequence,
            "replacement": replacement,
            "previous_active_identity": _hash(_active_backup(audit)),
            "current_active_identity": _hash(replacement),
            "renewal_handle_fingerprint": entry.fingerprint,
            "approved_at": datetime.now(UTC).isoformat(),
            "status": "committed",
        }
        audit.backup_renewals = [*(audit.backup_renewals or []), record]
        audit.active_backup_evidence = replacement
        audit.transition_history = [*audit.transition_history, f"backup_renewal_{sequence}_committed"]
        audit.atlas_write_count += 1
        audit.atlas_write_scope = ["append one immutable bootstrap backup-renewal event", "advance only the active backup pointer"]
        audit.recovery_recommendation = "proceed_to_manual_verification"
        session.add(audit)
        session.commit()
        session.refresh(audit)
        return _backup_renewal_result(audit, request_atlas_write_count=1)


def assess_backup_renewal_recovery(
    session: Session,
    page_id: int,
    request: WordPressBootstrapBackupRenewalRecoveryRequest,
) -> WordPressBootstrapBackupRenewalRecovery:
    if page_id != 41:
        raise HTTPException(404, "Bootstrap backup renewal is limited to Atlas page 41.")
    audit = _audit(session, request.establishment_audit_id)
    now = datetime.now(UTC)
    original = _original_backup_for_recovery(audit)
    active = _active_backup_for_recovery(audit, original)
    original_expiration = _backup_expiration(original, now)
    active_expiration = _backup_expiration(active, now)
    renewals = audit.backup_renewals or []
    renewal_count = len(renewals)
    source = _active_backup_source(audit, original, active)
    active_sequence = _active_renewal_sequence(renewals, source)
    verification_present = _verification_evidence_record(audit) is not None
    activation_started = bool(
        audit.activation_handle_fingerprint
        or audit.activation_binding_hash
        or audit.status == "activation_pending_checksum_verification"
    )
    checksum_quarantine = bool(
        audit.checksum_verification_result
        or audit.checksum_verification_source
        or audit.status in {"checksum_mismatch", "checksum_unavailable"}
    )
    pending_operation = _pending_operation_exists(session)
    protected = _protected(audit.pre_snapshot or {}) == audit.protected_state
    if not protected:
        classification, reason, recommendation, next_action = (
            "protected_state_drift", "bootstrap_backup_renewal_protected_state_drift",
            "siteground_restore", "request_separately_approved_guarded_recovery",
        )
    elif audit.status == "manual_installation_inventory_verified" or verification_present:
        classification, reason, recommendation, next_action = (
            "manual_verification_completed", "bootstrap_backup_renewal_verification_complete",
            "no_action", "proceed_to_guarded_activation_when_separately_approved",
        )
    elif checksum_quarantine:
        classification, reason, recommendation, next_action = (
            "checksum_quarantine_active", "bootstrap_backup_renewal_checksum_quarantine_active",
            "guarded_bootstrap_recovery", "resolve_checksum_quarantine_through_guarded_recovery",
        )
    elif activation_started:
        classification, reason, recommendation, next_action = (
            "activation_started", "bootstrap_backup_renewal_activation_started",
            "guarded_bootstrap_recovery", "complete_or_reconcile_guarded_activation",
        )
    elif pending_operation:
        classification, reason, recommendation, next_action = (
            "pending_operation", "bootstrap_backup_renewal_pending_operation",
            "guarded_bootstrap_recovery", "resolve_pending_operation_before_renewal",
        )
    elif audit.status != "awaiting_manual_bootstrap_installation":
        classification, reason, recommendation, next_action = (
            "audit_state_no_longer_eligible", "bootstrap_backup_renewal_audit_ineligible",
            "guarded_bootstrap_recovery", "review_durable_audit_state_before_any_action",
        )
    elif renewal_count >= MAX_BACKUP_RENEWALS:
        classification, reason, recommendation, next_action = (
            "renewal_limit_reached", "bootstrap_backup_renewal_limit_reached",
            "guarded_bootstrap_recovery", "request_separately_approved_guarded_recovery",
        )
    elif source == "replacement" and active_expiration["expired"] is True:
        classification, reason, recommendation, next_action = (
            "replacement_backup_expired", "bootstrap_backup_renewal_replacement_required",
            "renew_backup_again", "create_fresh_siteground_backup_then_run_guarded_backup_renewal",
        )
    elif source == "replacement" and active_expiration["expired"] is False:
        classification, reason, recommendation, next_action = (
            "valid_renewal_recorded", "bootstrap_backup_renewal_active_replacement_valid",
            "proceed_to_manual_verification", "capture_fresh_evidence_and_run_manual_install_verification",
        )
    elif source == "none":
        classification, reason, recommendation, next_action = (
            "backup_identity_unavailable", "bootstrap_backup_renewal_backup_identity_unavailable",
            "guarded_bootstrap_recovery", "review_audit_backup_identity_before_any_action",
        )
    elif active_expiration["expired"] is True:
        classification, reason, recommendation, next_action = (
            "renewal_required", "bootstrap_backup_renewal_replacement_required",
            "create_fresh_siteground_backup", "create_fresh_siteground_backup_then_run_guarded_backup_renewal",
        )
    elif active_expiration["expired"] is False:
        classification, reason, recommendation, next_action = (
            "no_renewal_required", "bootstrap_backup_renewal_original_still_valid",
            "no_action", "complete_manual_install_verification_before_backup_deadline",
        )
    else:
        classification, reason, recommendation, next_action = (
            "backup_expiration_unavailable", "bootstrap_backup_renewal_backup_expiration_unavailable",
            "guarded_bootstrap_recovery", "review_backup_timestamp_evidence_before_any_action",
        )
    renewal_eligible = classification in {"renewal_required", "replacement_backup_expired"}
    return WordPressBootstrapBackupRenewalRecovery(
        establishment_audit_id=audit.id or 0,
        audit_status=audit.status,
        classification=classification,
        reason_code=reason,
        recommendation=recommendation,
        next_required_action=next_action,
        renewal_eligible=renewal_eligible,
        renewal_blocked=not renewal_eligible,
        original_backup=original,
        original_backup_expired=original_expiration["expired"],
        original_backup_expiration_status=original_expiration["status"],
        original_backup_remaining_seconds=original_expiration["remaining_seconds"],
        active_backup=active,
        active_backup_source=source,
        active_backup_expired=active_expiration["expired"],
        active_backup_expiration_status=active_expiration["status"],
        active_backup_remaining_seconds=active_expiration["remaining_seconds"],
        active_renewal_sequence=active_sequence,
        renewal_history=_renewal_history_for_recovery(renewals, now, active_sequence),
        renewal_count=renewal_count,
        maximum_renewals=MAX_BACKUP_RENEWALS,
        renewals_remaining=max(0, MAX_BACKUP_RENEWALS - renewal_count),
        renewal_limit_reached=renewal_count >= MAX_BACKUP_RENEWALS,
        bootstrap_manually_uploaded=True if audit.upload_snapshot is not None else None,
        verification_evidence_present=verification_present,
        activation_started=activation_started,
        checksum_quarantine_active=checksum_quarantine,
        pending_operation=pending_operation,
    )


def activation_preflight(session: Session, page_id: int, request: WordPressBootstrapManualInstallVerifyRequest) -> WordPressBootstrapEstablishmentPreflight:
    audit = _audit(session, request.establishment_audit_id)
    _require_fresh_verification_evidence(audit, request)
    base, gates, classification = _inspect_against_audit(session, page_id, request, audit, require_inactive=True)
    gates += [
        _gate("audit_upload_verified", "The selected audit records exact inactive upload verification", audit.status == "manual_installation_inventory_verified", "Manual upload has not been verified."),
        _gate("upload_inventory_bound", "The complete inactive inventory matches the verified upload", audit.upload_inventories == _inventories(base.inspected_state), "Plugin inventory changed after upload verification."),
    ]
    temporal = _preflight_temporal_contract(request, base.inspected_state, base.backup_deadline)
    gates += temporal["gates"]
    ready = all(g.passed for g in gates)
    expires_at = _expiry(request) if ready else None
    stable = _stable_rendered_observation(base.inspected_state, request.manual_browser_evidence)
    stable_fingerprint = _hash(stable)
    binding = _binding(
        request, base.inspected_state, audit, "activate_fixed_bootstrap", expires_at,
        stable_rendered_fingerprint=stable_fingerprint,
        preflight_observed_at=temporal["observed_at"],
        evidence_expires_at=temporal["evidence_expires_at"],
        backup_deadline=temporal["backup_deadline"],
    )
    handle = _store(
        "activation", request, _hash(binding), expires_at, audit.id,
        stable_rendered_fingerprint=stable_fingerprint,
        stable_rendered_observation=stable,
        preflight_observed_at=temporal["observed_at"],
        evidence_expires_at=temporal["evidence_expires_at"],
        backup_deadline=temporal["backup_deadline"],
    ) if ready and expires_at and temporal["complete"] else None
    return _preflight_response(
        "bootstrap_activation_preflight", ready, "bootstrap_activation_preflight_ready" if ready else "bootstrap_activation_preflight_blocked",
        base, gates, binding, handle, expires_at, classification, audit_id=audit.id,
    )


def apply_activation(session: Session, page_id: int, request: WordPressBootstrapActivationApplyRequest) -> WordPressBootstrapEstablishmentResult:
    if page_id != 41:
        raise HTTPException(404, "Bootstrap establishment is limited to Atlas page 41.")
    if not hmac.compare_digest(request.confirmation_phrase, ACTIVATION_PHRASE):
        raise HTTPException(422, "The bootstrap activation phrase is incorrect.")
    entry = _consume("activation", request.activation_handle)
    if entry.audit_id is None:
        raise HTTPException(422, "Activation handle has no establishment audit binding.")
    audit = _audit(session, entry.audit_id)
    base, gates, classification = _inspect_against_audit(session, page_id, entry.request, audit, require_inactive=True)
    gates += [
        _gate("audit_upload_verified", "The selected audit records exact inactive upload verification", audit.status == "manual_installation_inventory_verified", "Manual upload has not been verified."),
        _gate("upload_inventory_bound", "The complete inactive inventory matches the verified upload", audit.upload_inventories == _inventories(base.inspected_state), "Plugin inventory changed after upload verification."),
    ]
    rerun_stable = _stable_rendered_observation(base.inspected_state, entry.request.manual_browser_evidence)
    rerun_fingerprint = _hash(rerun_stable)
    rerun_observed_at = _rendered_observed_at(base.inspected_state)
    conflict = _stable_rendered_conflict(entry.stable_rendered_observation, rerun_stable)
    if conflict:
        _raise_activation_conflict(_activation_stable_conflict(conflict), "Stable rendered-page identity changed after bootstrap activation preflight.")
    temporal_conflict = _activation_temporal_conflict(entry, rerun_observed_at)
    if temporal_conflict:
        _raise_activation_conflict(temporal_conflict, "The activation observation is outside the bound temporal contract.")
    rerun_binding = _hash(_binding(
        entry.request, base.inspected_state, audit, "activate_fixed_bootstrap", entry.expires_at,
        stable_rendered_fingerprint=rerun_fingerprint,
        preflight_observed_at=entry.preflight_observed_at,
        evidence_expires_at=entry.evidence_expires_at,
        backup_deadline=entry.backup_deadline,
    ))
    if not all(g.passed for g in gates):
        _raise_activation_conflict("bootstrap_activation_gate_drift", "A live activation gate changed after preflight.")
    if rerun_fingerprint != entry.stable_rendered_fingerprint or rerun_binding != entry.binding_hash:
        _raise_activation_conflict("bootstrap_activation_stable_observation_mismatch", "A stable activation binding changed after preflight.")
    if rerun_observed_at != entry.preflight_observed_at:
        gates.append(_gate("bootstrap_activation_volatile_timestamp_change_allowed", "Activation observation timestamp advanced inside the bound window", True, ""))
    audit.status = "activation_pending_checksum_verification"
    audit.activation_handle_fingerprint = _sha(request.activation_handle)
    audit.activation_binding_hash = entry.binding_hash
    audit.transition_history = [*audit.transition_history, audit.status]
    audit.atlas_write_count += 1
    audit.atlas_write_scope = ATLAS_SCOPE
    audit.recovery_recommendation = "guarded_bootstrap_recovery"
    session.add(audit); session.commit(); session.refresh(audit)

    outcome = _activate_fixed_entry(session)
    if outcome.get("request_performed"):
        audit.wordpress_write_count = 1
        audit.wordpress_write_scope = ACTIVATION_SCOPE
    if not outcome.get("accepted"):
        audit.error_code = "activation_unconfirmed"
        audit.error_message = "The one fixed activation request was not conclusively accepted."
        return _transition(
            session, audit, "recovery_required", gates, base.inspected_state,
            "guarded_bootstrap_recovery", request_atlas_write_count=2,
        )
    base, post_gates, classification = _inspect_against_audit(session, page_id, entry.request, audit, require_inactive=False)
    status = upgrade._read_bootstrap_status(session)
    checksum = status.get("bootstrap_checksum")
    checksum_well_formed = isinstance(checksum, str) and len(checksum) == 64 and all(c in "0123456789abcdef" for c in checksum)
    status_gates = [
        _gate("bootstrap_active", "The exact bootstrap is active exactly once", classification["classification"] == "exact_active", "The fixed bootstrap is not the sole active installation."),
        _gate("checksum_route", "The fixed authenticated bootstrap status route responded", status.get("status_code") == 200 and status.get("request_method") == "GET", "Bootstrap checksum route is unavailable."),
        _gate("bootstrap_source_identity", "Bootstrap status reports the locked source identity", status.get("bootstrap") == BOOTSTRAP_SLUG and status.get("bootstrap_version") == BOOTSTRAP_VERSION and status.get("operation") == "upgrade_metadata_bridge_0.57.6_to_0.57.7" and status.get("target_plugin") == "project-atlas-metadata-bridge/project-atlas-metadata-bridge.php" and status.get("current_version") == "0.57.6" and status.get("target_version") == "0.57.7" and status.get("target_zip_sha256") == "ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62", "Bootstrap source identity differs."),
        _gate("bootstrap_checksum", "Active bootstrap executable checksum is exact", checksum_well_formed and checksum == BOOTSTRAP_ENTRY_SHA256, "Bootstrap executable checksum is missing or differs."),
        _gate("quarantine_read_only", "Only activation and immediate read-only checksum verification occurred", outcome.get("request_keys") == ["status"] and status.get("request_method") == "GET", "Quarantine boundary was not preserved."),
    ]
    all_gates = post_gates + status_gates
    audit.checksum_verification_source = upgrade.BOOTSTRAP_STATUS_ROUTE
    audit.checksum_verification_result = "matched" if status_gates[3].passed else ("mismatch" if checksum_well_formed else "unavailable")
    if all(g.passed for g in all_gates):
        return _transition(
            session, audit, "verified", all_gates,
            {**base.inspected_state, "bootstrap_status": upgrade._safe_bootstrap_status(status)},
            "proceed_to_bridge_upgrade", completed=True, request_atlas_write_count=2,
        )
    intermediate = "checksum_mismatch" if checksum_well_formed and checksum != BOOTSTRAP_ENTRY_SHA256 else "checksum_unavailable" if not status_gates[1].passed or not checksum_well_formed else "verification_failed"
    audit.status = intermediate
    audit.transition_history = [*audit.transition_history, intermediate]
    session.add(audit); session.commit(); session.refresh(audit)
    recommendation = (
        "siteground_restore"
        if not _protected_equal(
            audit,
            base.inspected_state,
            allow_post_mutation_cache_variation=True,
        )
        else "guarded_bootstrap_recovery"
    )
    return _transition(
        session, audit, "recovery_required", all_gates,
        {**base.inspected_state, "bootstrap_status": upgrade._safe_bootstrap_status(status)},
        recommendation, request_atlas_write_count=3,
    )


def activation_reconciliation_preflight(
    session: Session,
    page_id: int,
    request: WordPressBootstrapActivationReconciliationRequest,
) -> WordPressBootstrapActivationReconciliationPreflight:
    if page_id != 41:
        raise HTTPException(404, "Bootstrap activation reconciliation is limited to Atlas page 41.")
    audit = _audit(session, request.establishment_audit_id)
    inspected, gates, backup = _activation_reconciliation_inspect(
        session,
        request,
        audit,
    )
    ready = all(gate.passed for gate in gates)
    expires_at = None
    if ready:
        evidence_expiry = upgrade._evidence_expiry(
            request.manual_browser_evidence.expires_at
        )
        expires_at = min(datetime.now(UTC) + HANDLE_TTL, evidence_expiry)
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
    binding = _activation_reconciliation_binding(
        request,
        audit,
        inspected,
        backup,
        expires_at,
    )
    binding_hash = _hash(binding)
    handle = (
        _store_activation_reconciliation(
            request,
            audit.id or 0,
            binding_hash,
            expires_at,
        )
        if ready and expires_at
        else None
    )
    return WordPressBootstrapActivationReconciliationPreflight(
        status=(
            "bootstrap_activation_reconciliation_ready"
            if ready
            else "bootstrap_activation_reconciliation_blocked"
        ),
        reconciliation_ready=ready,
        reconciliation_handle=handle,
        reconciliation_handle_fingerprint=_sha(handle) if handle else None,
        binding_hash=binding_hash if ready else None,
        confirmation_phrase=ACTIVATION_RECONCILIATION_PHRASE if ready else None,
        expires_at=expires_at,
        atlas_data_backup=backup,
        inspected_state=inspected,
        gate_results=gates,
    )


def apply_activation_reconciliation(
    session: Session,
    page_id: int,
    request: WordPressBootstrapActivationReconciliationApplyRequest,
) -> WordPressBootstrapActivationReconciliationResult:
    if page_id != 41:
        raise HTTPException(404, "Bootstrap activation reconciliation is limited to Atlas page 41.")
    if not hmac.compare_digest(
        request.confirmation_phrase,
        ACTIVATION_RECONCILIATION_PHRASE,
    ):
        raise HTTPException(422, "The Bootstrap activation reconciliation phrase is incorrect.")
    fingerprint = _sha(request.reconciliation_handle)
    replay = session.exec(
        select(WordPressBootstrapEstablishmentAudit).where(
            WordPressBootstrapEstablishmentAudit.reconciliation_handle_fingerprint
            == fingerprint
        )
    ).one_or_none()
    if replay is not None:
        if (
            replay.id == 2
            and replay.status == "verified"
            and replay.reconciliation_reason == ACTIVATION_RECONCILIATION_REASON
        ):
            return _activation_reconciliation_result(
                replay,
                inspected=replay.final_snapshot or {},
                gates=[
                    WordPressDraftGateResult.model_validate(item)
                    for item in (
                        (replay.final_snapshot or {})
                        .get("activation_reconciliation", {})
                        .get("gate_results", [])
                    )
                ],
                request_atlas_write_count=0,
                idempotent=True,
            )
        raise HTTPException(409, "The reconciliation handle fingerprint conflicts with another audit.")

    entry = _consume_activation_reconciliation(request.reconciliation_handle)
    if entry.audit_id != 2:
        raise HTTPException(409, "The reconciliation handle is bound to another audit.")
    audit = _audit_for_update(session, entry.audit_id)
    if audit is None:
        raise HTTPException(404, "Bootstrap-establishment audit not found.")
    inspected, gates, backup = _activation_reconciliation_inspect(
        session,
        entry.request,
        audit,
    )
    binding = _activation_reconciliation_binding(
        entry.request,
        audit,
        inspected,
        backup,
        entry.expires_at,
    )
    if not all(gate.passed for gate in gates):
        raise HTTPException(
            409,
            {
                "reason_code": "bootstrap_activation_reconciliation_gate_drift",
                "message": "A reconciliation gate changed after preflight.",
            },
        )
    if not hmac.compare_digest(_hash(binding), entry.binding_hash):
        raise HTTPException(
            409,
            {
                "reason_code": "bootstrap_activation_reconciliation_binding_drift",
                "message": "The reconciliation binding changed after preflight.",
            },
        )

    now = datetime.now(UTC)
    previous_history = list(audit.transition_history)
    original_failure_gates = list(audit.gate_results)
    original_recovery_snapshot = json.loads(
        json.dumps(audit.final_snapshot or {}, sort_keys=True, default=str)
    )
    original_recovery_inventories = json.loads(
        json.dumps(audit.final_inventories or {}, sort_keys=True, default=str)
    )
    audit.status = "verified"
    audit.reconciliation_reason = ACTIVATION_RECONCILIATION_REASON
    audit.reconciliation_handle_fingerprint = fingerprint
    audit.reconciliation_binding_hash = entry.binding_hash
    audit.reconciled_at = now
    audit.completed_at = now
    audit.transition_history = [
        *previous_history,
        ACTIVATION_RECONCILIATION_HISTORY,
    ]
    audit.final_snapshot = {
        **inspected,
        "activation_reconciliation": {
            "reason": ACTIVATION_RECONCILIATION_REASON,
            "original_failure_history_preserved": True,
            "original_recovery_snapshot": original_recovery_snapshot,
            "original_recovery_inventories": original_recovery_inventories,
            "wordpress_write_count": 0,
            "plugin_write_count": 0,
            "cache_write_count": 0,
            "original_failure_gate_results": original_failure_gates,
            "gate_results": [gate.model_dump(mode="json") for gate in gates],
        },
    }
    audit.final_inventories = _inventories(inspected)
    audit.atlas_write_count += 1
    audit.atlas_write_scope = [
        "finalize only WordPressBootstrapEstablishmentAudit 2 after read-only reconciliation",
        "preserve the original activation write, checksum result, and complete failure history",
    ]
    audit.recovery_recommendation = "no_action"
    audit.error_code = None
    audit.error_message = None
    session.add(audit)
    session.commit()
    session.refresh(audit)
    return _activation_reconciliation_result(
        audit,
        inspected=audit.final_snapshot or inspected,
        gates=gates,
        request_atlas_write_count=1,
        idempotent=False,
    )


def assess_recovery(session: Session, page_id: int, request: WordPressBootstrapManualInstallVerifyRequest) -> WordPressBootstrapRecoveryAssessment:
    audit = _audit(session, request.establishment_audit_id)
    base, gates, classification = _inspect_against_audit(session, page_id, request, audit, require_inactive=False)
    kind = classification["classification"]
    status = upgrade._read_bootstrap_status(session) if kind == "exact_active" else {"_error": "inactive_or_absent"}
    checksum = status.get("bootstrap_checksum")
    protected = _protected_equal(
        audit,
        base.inspected_state,
        allow_post_mutation_cache_variation=True,
    )
    if not protected:
        recommendation = "siteground_restore"
    elif kind == "no_upload_yet":
        recommendation = "retry_from_fresh_backup" if _expired(request) else "no_action"
    elif kind == "exact_inactive":
        recommendation = "guarded_bootstrap_cleanup" if audit.status == "recovery_required" else "no_action"
    elif kind == "exact_active" and checksum == BOOTSTRAP_ENTRY_SHA256 and audit.status == "verified":
        recommendation = "proceed_to_bridge_upgrade"
    else:
        recommendation = "guarded_bootstrap_recovery"
    return WordPressBootstrapRecoveryAssessment(
        establishment_audit_id=audit.id or 0,
        status="recovery_assessment_complete" if base.inspected_state.get("wordpress_request_performed") else "recovery_assessment_blocked",
        classification=kind if kind != "exact_active" else ("exact_active_checksum_match" if checksum == BOOTSTRAP_ENTRY_SHA256 else "exact_active_checksum_unavailable" if not checksum else "exact_active_checksum_mismatch"),
        recommendation=recommendation, gate_results=gates,
        inspected_state={**base.inspected_state, "bootstrap_classification": classification, "bootstrap_status": upgrade._safe_bootstrap_status(status)},
    )


def _activation_reconciliation_inspect(session, request, audit):
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
    )
    evidence = request.manual_browser_evidence
    evidence_valid, evidence_reason = upgrade.validate_manual_browser_evidence(
        evidence,
        os.environ.get("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", ""),
    )
    evidence_valid = bool(
        evidence_valid
        and evidence.evidence_schema_version == 1
        and evidence.evidence_id
        not in {
            audit.browser_evidence_id,
            (_verification_evidence_record(audit) or {}).get("evidence_id"),
        }
    )
    if evidence.evidence_schema_version != 1:
        evidence_reason = "Reconciliation requires fresh schema-v1 evidence."
    elif evidence.evidence_id in {
        audit.browser_evidence_id,
        (_verification_evidence_record(audit) or {}).get("evidence_id"),
    }:
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
    metadata_states = list(
        session.exec(
            select(WordPressMetadataState).where(
                WordPressMetadataState.generated_page_id == 41
            )
        )
    )
    metadata_sync_audits = list(
        session.exec(
            select(WordPressMetadataSyncAudit).where(
                WordPressMetadataSyncAudit.generated_page_id == 41
            )
        )
    )
    metadata_state = metadata_states[0] if len(metadata_states) == 1 else None
    observed = {
        **observed,
        "plugin_status": {
            key: plugin_status.get(key)
            for key in ("plugin", "version", "checksum", "active", "snapshot")
            if key in plugin_status
        },
        "bootstrap_status": upgrade._safe_bootstrap_status(bootstrap_status),
        "metadata_state_rows": len(metadata_states),
        "metadata_sync_audit_rows": len(metadata_sync_audits),
        "metadata_state_record": (
            {
                "status": metadata_state.status,
                "payload_hash": metadata_state.payload_hash,
                "wordpress_revision": metadata_state.wordpress_revision,
            }
            if metadata_state
            else None
        ),
    }
    classification = _classify(observed.get("plugins", []))
    expected_post = _expected_post_activation_inventories(audit)
    comparison = _verification_stable_comparison(
        audit,
        observed,
        allow_post_mutation_cache_variation=True,
    )
    backup, backup_gates = _activation_reconciliation_backup(
        request,
        release,
        audit,
    )
    failed_codes = {
        item.get("code")
        for item in (audit.gate_results or [])
        if item.get("passed") is False
    }
    expected_history = [
        "awaiting_manual_bootstrap_installation",
        "manual_installation_inventory_verified",
        "activation_pending_checksum_verification",
        "verification_failed",
        "recovery_required",
    ]
    audit_one = session.get(WordPressBootstrapEstablishmentAudit, 1)
    other_unresolved = [
        item
        for item in session.exec(select(WordPressBootstrapEstablishmentAudit))
        if item.id != audit.id
        and item.status not in {"verified", "authorization_retired"}
    ]
    status_snapshot = (
        plugin_status.get("snapshot", {})
        if isinstance(plugin_status.get("snapshot"), dict)
        else {}
    )
    metadata_state_record = observed.get("metadata_state_record") or {}
    gates = [
        _gate(
            "runtime_identity",
            "v0.59.93 runtime and independently expected identity are exact",
            runtime_exact
            and release.get("atlas_version") == "v0.59.93",
            "The loaded runtime identity is unavailable or differs.",
        ),
        _gate(
            "repository_identity",
            "Repository identity and protected-path attestations are exact",
            request.repository_head
            == request.repository_origin_main
            == request.expected_runtime_identity.atlas_commit
            and request.repository_tag == "v0.59.93"
            and request.repository_branch == "main"
            and request.repository_working_tree_clean
            and request.protected_paths_unchanged,
            "Repository identity, cleanliness, or protected paths differ.",
        ),
        _gate(
            "fresh_evidence",
            "Fresh signed schema-v1 browser evidence is valid",
            evidence_valid,
            evidence_reason or "Fresh signed schema-v1 evidence is invalid.",
        ),
        _gate(
            "read_only_observation",
            "WordPress observation succeeded using GET requests only",
            observed.get("wordpress_request_performed") is True
            and observed.get("wordpress_request_methods") == ["GET"],
            "Authenticated WordPress read-only observation is unavailable.",
        ),
        _gate(
            "audit_identity",
            "Audit ID 2 is bound to Atlas page 41 and WordPress page 8",
            audit.id == 2
            and audit.generated_page_id == 41
            and audit.wordpress_post_id == 8,
            "The selected audit identity differs.",
        ),
        _gate(
            "retired_audit_preserved",
            "Historical Audit ID 1 remains authorization-retired",
            bool(
                audit_one
                and audit_one.status == "authorization_retired"
                and audit_one.retirement_reason == RETIREMENT_REASON
            ),
            "Historical Audit ID 1 is missing or no longer authorization-retired.",
        ),
        _gate(
            "audit_recovery_state",
            "Audit ID 2 is the exact known recovery-required activation incident",
            audit.status == "recovery_required"
            and audit.transition_history == expected_history
            and failed_codes
            == {
                "active_inventory",
                "protected_state",
                "verification_stable_identity",
            }
            and audit.error_code == "recovery_required",
            "Audit status, history, or verifier-defect signature differs.",
        ),
        _gate(
            "original_activation_write",
            "Exactly one original fixed Bootstrap activation write is preserved",
            audit.wordpress_write_count == 1
            and audit.wordpress_write_scope == ACTIVATION_SCOPE,
            "The original activation write record is missing or differs.",
        ),
        _gate(
            "activation_handle_consumed",
            "No raw activation handle remains in process memory",
            not _activation_handles,
            "An activation handle remains live.",
        ),
        _gate(
            "checksum_record",
            "The durable checksum result and source remain exact",
            audit.checksum_verification_result == "matched"
            and audit.checksum_verification_source
            == upgrade.BOOTSTRAP_STATUS_ROUTE,
            "The durable checksum result or source differs.",
        ),
        _gate(
            "bootstrap_inventory_shape",
            "Bootstrap 0.3.0 is installed once, ordinary-active, and not network-active",
            classification["classification"] == "exact_active"
            and classification["count"] == 1
            and classification["conflict_count"] == 0,
            "Bootstrap identity, count, version, path, or active status differs.",
        ),
        _gate(
            "bootstrap_checksum",
            "Bootstrap executable checksum remains exact",
            bootstrap_status.get("status_code") == 200
            and bootstrap_status.get("request_method") == "GET"
            and bootstrap_status.get("bootstrap_checksum")
            == BOOTSTRAP_ENTRY_SHA256,
            "Bootstrap checksum is unavailable or differs.",
        ),
        _gate(
            "plugin_inventory",
            "Only the authorized Bootstrap inactive-to-active transition changed full inventory",
            observed.get("plugin_inventory_hash") == expected_post.get("plugins")
            and _without_bootstrap(observed.get("plugins", []))
            == _without_bootstrap((audit.upload_snapshot or {}).get("plugins", [])),
            "Full plugin inventory contains an unexpected change.",
        ),
        _gate(
            "active_inventory",
            "Active inventory is the exact deterministic post-activation inventory",
            observed.get("active_plugin_inventory_hash")
            == expected_post.get("active"),
            "Active inventory differs from the one authorized activation.",
        ),
        _gate(
            "metadata_bridge",
            "Metadata Bridge remains active at version 0.57.6",
            plugin_status.get("version") == "0.57.6"
            and plugin_status.get("active") is True,
            "Metadata Bridge version or active state differs.",
        ),
        _gate(
            "metadata_state",
            "Payload, revision, rendering, and Atlas metadata rows remain exact",
            status_snapshot.get("rendering_enabled") is False
            and status_snapshot.get("payload_hash")
            == "fe24398ee322ca8557814feb034a0ccff0302d5d26b6ea47b11001567854711d"
            and str(status_snapshot.get("revision")) == "1"
            and observed.get("metadata_state_rows") == 1
            and observed.get("metadata_sync_audit_rows") == 0
            and metadata_state_record.get("status") == "staged"
            and metadata_state_record.get("payload_hash")
            == "fe24398ee322ca8557814feb034a0ccff0302d5d26b6ea47b11001567854711d"
            and str(metadata_state_record.get("wordpress_revision")) == "1",
            "Metadata payload, revision, rendering, or Atlas row counts differ.",
        ),
        _gate(
            "durable_protected_state",
            "Page, body, media, settings, payload, revision, rendering, and purge count remain exact",
            _protected_non_rendered(observed)
            == _protected_non_rendered(
                audit.protected_state,
                already_protected=True,
            ),
            "Durable protected state changed.",
        ),
        _gate(
            "stable_public_identity",
            "Origin, URL, HTTP status, provider family, privacy, and signed page identity remain exact",
            comparison["compatible"] is True,
            f"Stable public identity differs: {comparison.get('reason_code')}.",
        ),
        _gate(
            "pending_operations",
            "No other Atlas lifecycle mutation is pending",
            not _pending_operation_exists(session),
            "Another lifecycle mutation is pending.",
        ),
        _gate(
            "conflicting_audit",
            "No conflicting Bootstrap-establishment audit is unresolved",
            not other_unresolved,
            "Another Bootstrap-establishment audit is unresolved.",
        ),
        _gate(
            "not_previously_reconciled",
            "Audit ID 2 has not already been reconciled",
            audit.reconciliation_reason is None
            and audit.reconciliation_handle_fingerprint is None
            and audit.reconciled_at is None,
            "Audit ID 2 was already reconciled.",
        ),
        *backup_gates,
    ]
    inspected = {
        **observed,
        "bootstrap_classification": classification,
        "post_activation_transport_identity": comparison,
        "expected_post_inventories": {
            "plugins": expected_post.get("plugins"),
            "active": expected_post.get("active"),
        },
        "reconciliation_wordpress_write_count": 0,
        "reconciliation_plugin_write_count": 0,
        "reconciliation_cache_write_count": 0,
        "reconciliation_atlas_write_count": 0,
    }
    return inspected, gates, backup


def _activation_reconciliation_backup(request, release, audit):
    summary = {
        "file_name": request.atlas_data_backup_file,
        "sha256": request.atlas_data_backup_sha256,
        "size": request.atlas_data_backup_size,
        "created_at": request.atlas_data_backup_created_at.astimezone(UTC).isoformat()
        if request.atlas_data_backup_created_at.tzinfo
        else None,
        "onedrive_path": request.atlas_data_backup_onedrive_path,
        "onedrive_synced": request.atlas_data_backup_onedrive_synced,
    }
    path = None
    payload = None
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
        payload.get("data", {}).get("wordpress_bootstrap_establishment_audits", [])
        if isinstance(payload, dict)
        else []
    )
    backup_audit = next(
        (item for item in records if item.get("id") == audit.id),
        None,
    )
    try:
        created_at = _timestamp(metadata.get("created_at"))
        runtime_generated_at = _timestamp(release.get("generated_at"))
    except (TypeError, ValueError):
        created_at = runtime_generated_at = None
    onedrive_name = PureWindowsPath(
        request.atlas_data_backup_onedrive_path
    ).name
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
            "Atlas Data backup was created after the loaded v0.59.93 runtime",
            bool(
                created_at
                and runtime_generated_at
                and request.atlas_data_backup_created_at.tzinfo
                and created_at
                == request.atlas_data_backup_created_at.astimezone(UTC)
                and created_at >= runtime_generated_at
            ),
            "Atlas Data backup predates the loaded v0.59.93 runtime or has a mismatched timestamp.",
        ),
        _gate(
            "atlas_data_backup_audit",
            "Atlas Data backup preserves Audit ID 2 before reconciliation",
            bool(
                backup_audit
                and backup_audit.get("status") == "recovery_required"
                and backup_audit.get("wordpress_write_count") == 1
                and backup_audit.get("atlas_write_count") == audit.atlas_write_count
                and backup_audit.get("transition_history")
                == audit.transition_history
            ),
            "Atlas Data backup does not preserve the exact pre-reconciliation audit.",
        ),
        _gate(
            "atlas_data_backup_onedrive",
            "OneDrive backup path and synchronization are explicitly confirmed",
            request.atlas_data_backup_onedrive_synced
            and bool(onedrive_name == request.atlas_data_backup_file),
            "OneDrive backup synchronization is unconfirmed.",
        ),
    ]
    return summary, gates


def _activation_reconciliation_binding(request, audit, inspected, backup, expires_at):
    comparison = inspected.get("post_activation_transport_identity", {})
    return {
        "action": "reconcile_bootstrap_activation_without_wordpress_write",
        "audit": {
            "id": audit.id,
            "status": audit.status,
            "history": audit.transition_history,
            "wordpress_write_count": audit.wordpress_write_count,
            "atlas_write_count": audit.atlas_write_count,
            "checksum_result": audit.checksum_verification_result,
            "row_identity": _activation_reconciliation_audit_identity(audit),
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
            "schema": request.manual_browser_evidence.evidence_schema,
            "version": request.manual_browser_evidence.evidence_schema_version,
            "head_hash": request.manual_browser_evidence.rendered_head_hash,
            "visible_hash": request.manual_browser_evidence.visible_content_hash,
            "expires_at": request.manual_browser_evidence.expires_at,
        },
        "current": {
            "inventories": _inventories(inspected),
            "protected": _protected_non_rendered(inspected),
            "bootstrap_checksum": inspected.get("bootstrap_status", {}).get(
                "bootstrap_checksum"
            ),
            "transport_identity": comparison.get("canonical_fingerprint"),
        },
        "reason": ACTIVATION_RECONCILIATION_REASON,
        "expected_final_status": "verified",
        "expected_history_append": ACTIVATION_RECONCILIATION_HISTORY,
        "expected_writes": {
            "wordpress": 0,
            "plugin": 0,
            "cache": 0,
            "atlas": 1,
        },
        "expires_at": expires_at.astimezone(UTC).isoformat()
        if expires_at
        else None,
    }


def _activation_reconciliation_audit_identity(audit):
    return _hash(
        {
            "id": audit.id,
            "status": audit.status,
            "history": audit.transition_history,
            "wordpress_write_count": audit.wordpress_write_count,
            "wordpress_write_scope": audit.wordpress_write_scope,
            "atlas_write_count": audit.atlas_write_count,
            "checksum_result": audit.checksum_verification_result,
            "checksum_source": audit.checksum_verification_source,
            "failed_gates": [
                item.get("code")
                for item in audit.gate_results
                if item.get("passed") is False
            ],
            "reconciliation_reason": audit.reconciliation_reason,
        }
    )


def _activation_reconciliation_result(
    audit,
    *,
    inspected,
    gates,
    request_atlas_write_count,
    idempotent,
):
    return WordPressBootstrapActivationReconciliationResult(
        state_history=audit.transition_history,
        binding_hash=audit.reconciliation_binding_hash or "",
        reconciliation_handle_fingerprint=(
            audit.reconciliation_handle_fingerprint or ""
        ),
        request_atlas_write_count=request_atlas_write_count,
        cumulative_atlas_write_count=audit.atlas_write_count,
        idempotent_replay=idempotent,
        inspected_state=inspected,
        gate_results=gates,
    )


def latest_verified_establishment(session: Session) -> WordPressBootstrapEstablishmentAudit | None:
    audits = list(session.exec(select(WordPressBootstrapEstablishmentAudit).order_by(WordPressBootstrapEstablishmentAudit.id.desc())))
    return next((item for item in audits if item.status == "verified" and item.checksum_verification_result == "matched"), None)


def assert_no_establishment_quarantine(session: Session) -> None:
    """Block unrelated mutation workflows while a bootstrap is unverified."""
    if not isinstance(session, Session):
        return
    latest = session.exec(
        select(WordPressBootstrapEstablishmentAudit).order_by(WordPressBootstrapEstablishmentAudit.id.desc())
    ).first()
    if isinstance(latest, WordPressBootstrapEstablishmentAudit) and not (
        latest.status == "verified" and latest.checksum_verification_result == "matched"
    ):
        raise HTTPException(
            409,
            "Upgrade bootstrap is quarantined pending exact executable-checksum verification or separately approved recovery.",
        )


def _inspect_against_audit(session, page_id, request, audit, *, require_inactive):
    base = upgrade.plugin_upgrade_preflight(session, page_id, request, issue_handle=False)
    classification = _classify(base.inspected_state.get("plugins", []))
    expected_kind = "exact_inactive" if require_inactive else "exact_active"
    verification_comparison = _verification_stable_comparison(
        audit,
        base.inspected_state,
        allow_post_mutation_cache_variation=not require_inactive,
    )
    verification_drift = verification_comparison["reason_code"] if not verification_comparison["compatible"] else None
    expected_post = _expected_post_activation_inventories(audit)
    base.inspected_state["manual_install_transport_identity"] = verification_comparison
    gates = _base_gates(base) + [
        _gate("bootstrap_inventory_shape", f"Bootstrap inventory is {expected_kind.replace('_', ' ')}", classification["classification"] == expected_kind, "Bootstrap path, version, status, count, or inventory is not exact."),
        _gate("unrelated_plugin_drift", "No unrelated plugin changed", _without_bootstrap(base.inspected_state.get("plugins", [])) == _without_bootstrap(audit.pre_snapshot.get("plugins", [])), "An unrelated plugin changed."),
        _gate("protected_state", "Page, body, media, settings, rendering, payload, revision, and cache-purge count remain bound", _protected_non_rendered(base.inspected_state) == _protected_non_rendered(audit.protected_state, already_protected=True), "Protected state changed."),
        _gate("verification_stable_identity", "Fresh evidence matches the authorized stable public identity", verification_drift is None, "Fresh rendered evidence changed stable public identity."),
        _gate("verification_rendered_hashes", "Fresh rendered hashes match authorization", verification_drift != "manual_install_verification_rendered_hash_drift", "Rendered-head, visible-content, or raw-DOM identity changed."),
        _gate("verification_privacy", "Fresh evidence preserves the credential-free privacy classification", verification_drift != "manual_install_verification_privacy_transport_drift", "Cookie, authentication, admin, login, challenge, or error classification changed."),
        _gate("active_backup_binding", "The request uses the current audit-bound replacement backup", not (audit.backup_renewals or []) or _normalized_backup(_backup(request)) == _normalized_backup(_active_backup(audit, include_deadline=False)), "The request does not use the current guarded replacement backup identity."),
        _gate(
            "plugin_inventory",
            "Full plugin inventory matches the exact lifecycle state",
            (
                base.inspected_state.get("plugin_inventory_hash")
                == audit.upload_inventories.get("plugins")
            )
            if require_inactive and audit.upload_inventories
            else (
                base.inspected_state.get("plugin_inventory_hash")
                == expected_post.get("plugins")
            )
            if not require_inactive
            else True,
            "Full plugin inventory differs from the exact authorized lifecycle state.",
        ),
        _gate(
            "active_inventory",
            "Active inventory matches the exact lifecycle state",
            (
                base.inspected_state.get("active_plugin_inventory_hash")
                == audit.source_inventories.get("active")
            )
            if require_inactive
            else (
                base.inspected_state.get("active_plugin_inventory_hash")
                == expected_post.get("active")
            ),
            "Active inventory differs from the exact authorized lifecycle state.",
        ),
    ]
    return base, gates, classification


def _base_gates(base):
    return [gate for gate in base.gate_results if gate.code not in _BASE_IGNORED_GATE_CODES]


def _classify(plugins):
    candidates = []
    conflicts = []
    for item in plugins:
        raw = item.get("plugin")
        posix = raw.replace("\\", "/") if isinstance(raw, str) else ""
        if posix in {BOOTSTRAP_ENTRY, BOOTSTRAP_REST_ID}:
            candidates.append(item)
        elif posix.startswith(f"{BOOTSTRAP_DIRECTORY}/") or posix.startswith("project-atlas-upgrade-bootstrap"):
            conflicts.append(item)
    if not candidates and not conflicts:
        kind = "no_upload_yet"
    elif len(candidates) > 1:
        kind = "duplicate_bootstrap"
    elif conflicts:
        kind = "installation_partial" if not candidates else "conflicting_bootstrap"
    elif candidates[0].get("version") != BOOTSTRAP_VERSION:
        kind = "wrong_version"
    elif candidates[0].get("status") == "inactive":
        kind = "exact_inactive"
    elif candidates[0].get("status") == "active" and candidates[0].get("network_only") is False:
        kind = "exact_active"
    elif candidates[0].get("status") == "network-active" or candidates[0].get("network_only") is True:
        kind = "network_active"
    else:
        kind = "installation_partial"
    return {"classification": kind, "count": len(candidates), "conflict_count": len(conflicts), "entry": candidates[0] if len(candidates) == 1 else None}


def _activate_fixed_entry(session):
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password):
        return {"accepted": False, "request_performed": False, "_error": "credentials_unavailable", "request_keys": ["status"]}
    try:
        with wordpress_http_client(settings.site_url, timeout=30, follow_redirects=False, client_factory=httpx.Client) as client:
            response = client.post(
                f"{settings.site_url.rstrip('/')}/wp-json/wp/v2/plugins/{BOOTSTRAP_REST_ID}",
                json={"status": "active"}, auth=wordpress_basic_auth(settings.username, password),
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
        payload = response.json() if response.status_code == 200 else {}
        accepted = (
            isinstance(payload, dict)
            and response.status_code == 200
            and payload.get("status") == "active"
            and payload.get("network_only") is not True
            and payload.get("version") == BOOTSTRAP_VERSION
            and str(payload.get("plugin", "")).replace("\\", "/")
            in {BOOTSTRAP_ENTRY, BOOTSTRAP_REST_ID}
        )
        return {"accepted": accepted, "request_performed": True, "status_code": response.status_code, "request_keys": ["status"]}
    except (httpx.HTTPError, ValueError):
        return {"accepted": False, "request_performed": True, "_error": "fixed_activation_unavailable", "request_keys": ["status"]}


def _preflight_response(stage, ready, status, base, gates, binding, handle, expires_at, classification, *, instructions=None, audit_id=None):
    return WordPressBootstrapEstablishmentPreflight(
        stage=stage, ready=ready, status=status, establishment_audit_id=audit_id,
        handle=handle, handle_fingerprint=_sha(handle) if handle else None,
        binding_hash=_hash(binding) if ready else None,
        confirmation_phrase=(MANUAL_PHRASE if stage == "bootstrap_manual_install_preflight" else ACTIVATION_PHRASE) if ready else None,
        expires_at=expires_at, backup_deadline=base.backup_deadline,
        artifact={"zip_filename": BOOTSTRAP_ZIP, "version": BOOTSTRAP_VERSION, "zip_sha256": BOOTSTRAP_ZIP_SHA256, "entry_path": BOOTSTRAP_ENTRY, "entry_sha256": BOOTSTRAP_ENTRY_SHA256, "inactive_entry_checksum_verifiable": False},
        inspected_state={**base.inspected_state, "bootstrap_classification": classification},
        gate_results=gates, instructions=instructions or [],
    )


def _result(audit, stage, gates, snapshot, recommendation, *, request_atlas_write_count=0, idempotent_replay=False, reason_code="bootstrap_establishment_result"):
    authorization_evidence = _authorization_evidence_record(audit)
    verification_evidence = _verification_evidence_record(audit)
    return WordPressBootstrapEstablishmentResult(
        establishment_audit_id=audit.id or 0, stage=stage, status=audit.status,
        state_history=audit.transition_history, binding_hash=audit.activation_binding_hash or audit.manual_binding_hash,
        gate_results=gates, inspected_state=snapshot,
        wordpress_write_count=audit.wordpress_write_count, wordpress_write_scope=audit.wordpress_write_scope,
        atlas_write_count=audit.atlas_write_count, atlas_write_scope=audit.atlas_write_scope,
        request_atlas_write_count=request_atlas_write_count, idempotent_replay=idempotent_replay,
        reason_code=reason_code,
        authorization_evidence=authorization_evidence,
        verification_evidence=verification_evidence,
        stable_evidence_match=bool(
            verification_evidence
            and (
                verification_evidence.get("transport_compatibility_applied") is True
                or authorization_evidence.get("stable_fingerprint")
                == verification_evidence.get("stable_fingerprint")
            )
        ),
        fresh_evidence_required=audit.status == "awaiting_manual_bootstrap_installation",
        backup_deadline_valid=_audit_backup_deadline_valid(audit),
        original_backup=_original_backup(audit),
        active_backup=_active_backup(audit),
        backup_renewals=audit.backup_renewals or [],
        recovery_recommendation=recommendation, further_action_required=audit.status != "verified",
    )


def _transition(session, audit, status, gates, snapshot, recommendation, *, completed=False, request_atlas_write_count=1):
    audit.status = status
    audit.transition_history = [*audit.transition_history, status]
    audit.final_snapshot = snapshot
    audit.final_inventories = _inventories(snapshot)
    audit.gate_results = [g.model_dump(mode="json") for g in gates]
    audit.atlas_write_count += 1
    audit.recovery_recommendation = recommendation
    audit.completed_at = datetime.now(UTC) if completed else None
    audit.error_code = None if status == "verified" else status
    audit.error_message = None if status == "verified" else "; ".join(g.message for g in gates if not g.passed)[:2000]
    session.add(audit); session.commit(); session.refresh(audit)
    return _result(
        audit, "bootstrap_post_activation_verification", gates, snapshot, recommendation,
        request_atlas_write_count=request_atlas_write_count, reason_code=status,
    )


def _audit(session, audit_id):
    audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
    if not audit or audit.generated_page_id != 41 or audit.wordpress_post_id != 8:
        raise HTTPException(404, "Bootstrap-establishment audit not found.")
    return audit


def _audit_for_update(session, audit_id):
    audit = session.exec(
        select(WordPressBootstrapEstablishmentAudit)
        .where(WordPressBootstrapEstablishmentAudit.id == audit_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if not audit or audit.generated_page_id != 41 or audit.wordpress_post_id != 8:
        raise HTTPException(404, "Bootstrap-establishment audit not found.")
    return audit


def _unresolved(session):
    return any(a.status not in {"verified", "authorization_retired"} for a in session.exec(select(WordPressBootstrapEstablishmentAudit)))


def _current_cached_public_transport(transport):
    provider = transport.get("provider", {}) if isinstance(transport, dict) else {}
    return bool(
        transport.get("status_code") == 200
        and _transport_response_source(transport) == "provider_verified_public_html"
        and _siteground_nginx_provider(provider)
        and _transport_cache_state(provider) == "hit"
        and not any((transport.get("challenge_error") or {}).values())
    )


def _retirement_comparison_snapshot(audit, observed):
    """Compare current transport while retaining the signed authorization identity.

    The retirement phase intentionally captures no new browser evidence.  The
    independently acquired public HTTP observation is therefore spliced into a
    copy of the immutable, signed authorization rendering identity.  This lets
    the comparison answer only the approved question—whether transport changed—
    without treating an unsigned response as replacement page evidence.
    """

    value = json.loads(json.dumps(observed or {}, sort_keys=True, default=str))
    historical = json.loads(json.dumps(_rendered_observation(audit.pre_snapshot or {}), sort_keys=True, default=str))
    current_public = _public_observation(observed)
    historical["public_http_observation"] = json.loads(json.dumps(current_public, sort_keys=True, default=str))
    historical["cache_headers"] = json.loads(json.dumps(current_public.get("cache_headers", {}), sort_keys=True, default=str))
    value["rendered"] = historical
    value["cache_headers"] = historical["cache_headers"]
    return value


def _retirement_runtime_matches(request):
    try:
        readiness = deployment_readiness()
        release = readiness.get("release") or {}
    except (HTTPException, TypeError, ValueError):
        return False
    actual = {
        "atlas_version": release.get("atlas_version"),
        "atlas_commit": release.get("atlas_commit"),
        "atlas_tag": release.get("atlas_tag"),
        "manifest_sha256": release.get("manifest_sha256"),
        "source_compatibility_id": release.get("source_compatibility_id"),
    }
    return bool(
        readiness.get("release_status") == "verified"
        and actual == request.expected_runtime_identity.model_dump(mode="json")
        and release.get("runtime_identity_verified") is True
        and release.get("manifest_integrity_verified") is True
        and release.get("expected_release_matched") is True
    )


def _retirement_public_identity_matches(audit, observed):
    historical = _rendered_observation(audit.pre_snapshot or {})
    current = _public_observation(observed)
    return bool(
        current.get("verified") is True
        and current.get("head_hash") == historical.get("head_hash")
        and current.get("visible_hash") == historical.get("visible_hash")
    )


def _genuine_transport_retirement_drift(audit, snapshot, comparison):
    before = _stable_verification_observation(audit.pre_snapshot or {})
    after = _stable_verification_observation(snapshot)
    old = before.get("public_transport", {})
    new = after.get("public_transport", {})
    old_provider = old.get("provider", {})
    new_provider = new.get("provider", {})
    before_identity = {key: value for key, value in before.items() if key not in {"outcome", "public_transport"}}
    after_identity = {key: value for key, value in after.items() if key not in {"outcome", "public_transport"}}
    return bool(
        comparison.get("compatible") is False
        and comparison.get("reason_code") in {
            "manual_install_verification_provider_identity_drift",
            "manual_install_verification_response_source_drift",
        }
        and before_identity == after_identity
        and old.get("status_code") == 403
        and _transport_response_source(old) == "provider_verified_html_block"
        and _siteground_nginx_provider(old_provider)
        and _transport_cache_state(old_provider) is None
        and _current_cached_public_transport(new)
    )


def _safe_transport_retirement_summary(audit, snapshot, comparison):
    old = _stable_verification_observation(audit.pre_snapshot or {}).get("public_transport", {})
    new = _stable_verification_observation(snapshot).get("public_transport", {})
    return {
        "version": TRANSPORT_IDENTITY_VERSION,
        "reason_code": comparison.get("reason_code"),
        "authorization": {
            "status_code": old.get("status_code"),
            "response_source": _transport_response_source(old),
            "provider": "siteground-nginx" if _siteground_nginx_provider(old.get("provider", {})) else "unverified",
            "cache_state": _transport_cache_state(old.get("provider", {})),
        },
        "current": {
            "status_code": new.get("status_code"),
            "response_source": _transport_response_source(new),
            "provider": "siteground-nginx" if _siteground_nginx_provider(new.get("provider", {})) else "unverified",
            "cache_state": _transport_cache_state(new.get("provider", {})),
            "transport_category": new.get("transport_category"),
            "transport_reason_code": new.get("transport_reason_code"),
        },
    }


def _retired_identity_reuse(retired, request):
    evidence_id = request.manual_browser_evidence.evidence_id if request.manual_browser_evidence else ""
    backup = _hash(_normalized_backup(_backup(request)))
    reused_evidence = any(audit.browser_evidence_id == evidence_id for audit in retired)
    reused_backup = any(
        backup in {
            _hash(_normalized_backup(_active_backup(audit, include_deadline=False))),
            _hash(_normalized_backup({key: value for key, value in _original_backup(audit).items() if key not in {"deadline", "no_relevant_wordpress_change_after_backup"}})),
        }
        for audit in retired
    )
    return reused_evidence, reused_backup


def _inventories(snapshot):
    return {"plugins": snapshot.get("plugin_inventory_hash"), "active": snapshot.get("active_plugin_inventory_hash")}


def _expected_post_activation_inventories(audit):
    snapshot = audit.upload_snapshot or audit.pre_snapshot or {}
    plugins = json.loads(json.dumps(snapshot.get("plugins", []), sort_keys=True, default=str))
    candidates = [
        item
        for item in plugins
        if str(item.get("plugin", "")).replace("\\", "/") in {BOOTSTRAP_ENTRY, BOOTSTRAP_REST_ID}
    ]
    if len(candidates) != 1:
        return {}
    candidate = candidates[0]
    if (
        candidate.get("version") != BOOTSTRAP_VERSION
        or candidate.get("status") != "inactive"
        or candidate.get("network_only") is not False
    ):
        return {}
    candidate["status"] = "active"
    active_plugins = sorted(
        str(item.get("plugin"))
        for item in plugins
        if item.get("status") == "active"
    )
    return {
        "plugins": _hash(plugins),
        "active": _hash(active_plugins),
        "plugin_records": plugins,
        "active_plugins": active_plugins,
    }


def _protected(snapshot):
    status = snapshot.get("plugin_status", {}).get("snapshot", {})
    return {
        "page": snapshot.get("page_snapshot_hash"), "body": snapshot.get("page_body_hash"),
        "media31": snapshot.get("media31_snapshot_hash"), "media32": snapshot.get("media32_snapshot_hash"),
        "site": snapshot.get("site"), "rendered": _protected_rendered(snapshot.get("rendered")),
        "cache_purge_count": snapshot.get("cache_purge_count", 0),
        "rendering_enabled": status.get("rendering_enabled"), "payload_hash": status.get("payload_hash"),
        "revision": str(status.get("revision")), "payload": status.get("payload"),
    }


def _protected_non_rendered(value, *, already_protected=False):
    protected = value if already_protected else _protected(value)
    return {
        key: item
        for key, item in protected.items()
        if key != "rendered"
    }


def _stable_verification_observation(snapshot):
    """Cross-phase public identity with evidence IDs and acquisition timing removed."""

    rendered = _rendered_observation(snapshot)
    public = cache_binding._stable_public_observation(_public_observation(snapshot), None)
    return {
        "requested_url": cache_binding.CANONICAL_URL,
        "final_url": rendered.get("final_url"),
        "outcome": rendered.get("outcome"),
        "verified": rendered.get("verified") is True,
        "schema": rendered.get("evidence_schema"),
        "schema_version": rendered.get("evidence_schema_version"),
        "capture_helper_version": rendered.get("capture_helper_version"),
        "rendered_head_hash": rendered.get("head_hash"),
        "visible_content_hash": rendered.get("visible_hash"),
        "raw_dom_hash": rendered.get("raw_dom_hash"),
        "document_title": rendered.get("document_title"),
        "ordered_h1_inventory": rendered.get("h1"),
        "canonical_inventory": rendered.get("canonical"),
        "featured_image_url": rendered.get("featured_image_url"),
        "featured_image_alt": rendered.get("featured_image_alt"),
        "metadata_inventory_hash": rendered.get("metadata_inventory_hash"),
        "privacy_attestations": rendered.get("privacy_attestations"),
        "classifications": {
            "signature_validated": rendered.get("signature_validated") is True,
            "atlas_metadata_marker_present": bool(rendered.get("atlas_metadata_marker_present")),
            "media32_reference_present": bool(rendered.get("media32_reference_present")),
        },
        "public_transport": public,
    }


def _stable_verification_fingerprint(snapshot):
    return _hash(_stable_verification_observation(snapshot))


def _evidence_record(evidence, snapshot, *, result, comparison=None):
    value = _evidence_value(evidence)
    record = {
        "evidence_id": value.get("evidence_id"),
        "captured_at": value.get("captured_at"),
        "expires_at": value.get("expires_at"),
        "schema": value.get("evidence_schema"),
        "schema_version": value.get("evidence_schema_version"),
        "capture_helper_version": value.get("capture_helper_version"),
        "stable_fingerprint": _stable_verification_fingerprint(snapshot),
        "result": result,
    }
    if isinstance(comparison, dict):
        record.update({
            "transport_identity_version": comparison.get("version"),
            "transport_compatibility_applied": comparison.get("compatibility_applied") is True,
            "transport_comparison_reason": comparison.get("reason_code"),
            "canonical_stable_fingerprint": comparison.get("canonical_fingerprint"),
            "authorization_stable_fingerprint": comparison.get("authorization_stable_fingerprint"),
            "verification_stable_fingerprint": comparison.get("verification_stable_fingerprint"),
        })
    return record


def _authorization_evidence_record(audit):
    stored = (audit.pre_snapshot or {}).get(_AUTHORIZATION_EVIDENCE_KEY)
    if isinstance(stored, dict):
        return stored
    rendered = _rendered_observation(audit.pre_snapshot or {})
    return {
        "evidence_id": audit.browser_evidence_id,
        "captured_at": rendered.get("evidence_timestamp"),
        "expires_at": rendered.get("evidence_expires_at"),
        "schema": rendered.get("evidence_schema"),
        "schema_version": rendered.get("evidence_schema_version"),
        "capture_helper_version": rendered.get("capture_helper_version"),
        "stable_fingerprint": _stable_verification_fingerprint(audit.pre_snapshot or {}),
        "result": "authorization_committed",
    }


def _verification_evidence_record(audit):
    stored = (audit.upload_snapshot or {}).get(_VERIFICATION_EVIDENCE_KEY)
    return stored if isinstance(stored, dict) else None


def _verification_stable_drift_reason(audit, snapshot):
    comparison = _verification_stable_comparison(audit, snapshot)
    return None if comparison["compatible"] else comparison["reason_code"]


def _verification_stable_comparison(
    audit,
    snapshot,
    *,
    allow_post_mutation_cache_variation=False,
):
    before = _stable_verification_observation(audit.pre_snapshot or {})
    after = _stable_verification_observation(snapshot)
    authorization_fingerprint = _hash(before)
    verification_fingerprint = _hash(after)
    result = {
        "version": TRANSPORT_IDENTITY_VERSION,
        "compatible": False,
        "compatibility_applied": False,
        "reason_code": "manual_install_verification_stable_identity_mismatch",
        "authorization_stable_fingerprint": authorization_fingerprint,
        "verification_stable_fingerprint": verification_fingerprint,
        "canonical_fingerprint": verification_fingerprint,
    }
    hash_keys = ("rendered_head_hash", "visible_content_hash", "raw_dom_hash")
    if any(before.get(key) != after.get(key) for key in hash_keys):
        return {**result, "reason_code": "manual_install_verification_rendered_hash_drift"}
    if (
        before.get("privacy_attestations") != after.get("privacy_attestations")
        or before.get("classifications") != after.get("classifications")
        or before.get("public_transport", {}).get("challenge_error")
        != after.get("public_transport", {}).get("challenge_error")
    ):
        return {**result, "reason_code": "manual_install_verification_privacy_transport_drift"}
    raw_equal = before == after
    before_identity = {key: value for key, value in before.items() if key not in {"outcome", "public_transport"}}
    after_identity = {key: value for key, value in after.items() if key not in {"outcome", "public_transport"}}
    if before_identity != after_identity:
        return {**result, "reason_code": "manual_install_verification_stable_page_identity_mismatch"}

    transport = _cross_release_transport_compatibility(
        before,
        after,
        allow_cache_variation=allow_post_mutation_cache_variation,
    )
    if not transport["compatible"]:
        if raw_equal:
            return {**result, "compatible": True, "reason_code": "manual_install_verification_stable_identity_exact"}
        return {**result, "reason_code": transport["reason_code"]}
    canonical = {
        "version": TRANSPORT_IDENTITY_VERSION,
        "signed_public_identity": after_identity,
        "transport_identity": transport["canonical_transport"],
    }
    return {
        **result,
        "compatible": True,
        "compatibility_applied": not raw_equal,
        "reason_code": (
            "manual_install_verification_stable_identity_exact"
            if raw_equal
            else TRANSPORT_COMPATIBILITY_REASON
        ),
        "canonical_fingerprint": _hash(canonical),
    }


def _cross_release_transport_compatibility(
    before,
    after,
    *,
    allow_cache_variation=False,
):
    """Canonicalize representation without weakening response security meaning.

    The historical raw observation remains immutable.  This derived comparison
    deliberately excludes the client User-Agent, response timing, ETag, body
    bytes from a blocked response, cache-age/request identifiers, diagnostic
    field order, and equivalent provider-label spelling.  HTTP status/source
    semantics are deliberately retained.
    """

    old = before.get("public_transport", {})
    new = after.get("public_transport", {})
    canonical_url = cache_binding.CANONICAL_URL
    for transport in (old, new):
        if (
            transport.get("status_code") is None
            or transport.get("transport_category") in {
                "dns_failed", "connect_timeout", "read_timeout", "tls_failed",
                "network_failed", "transport_acquisition_failed",
            }
        ):
            return {
                "compatible": False,
                "reason_code": "manual_install_verification_transport_acquisition_failed",
                "transport_category": (
                    transport.get("transport_category") or "transport_acquisition_failed"
                ),
            }
        if (
            transport.get("request_url") != canonical_url
            or transport.get("final_url") != canonical_url
            or transport.get("redirect_count") != 0
            or transport.get("content_type_class") != "html"
            or any(transport.get("challenge_error", {}).values())
        ):
            return {"compatible": False, "reason_code": "manual_install_verification_origin_drift"}

    old_provider = old.get("provider", {})
    new_provider = new.get("provider", {})
    if not (_siteground_nginx_provider(old_provider) and _siteground_nginx_provider(new_provider)):
        return {"compatible": False, "reason_code": "manual_install_verification_provider_identity_drift"}
    old_cache_state = _transport_cache_state(old_provider)
    new_cache_state = _transport_cache_state(new_provider)
    allowed_cache_states = {"hit", "miss", "expired", "bypass"}
    if old_cache_state != new_cache_state and not (
        allow_cache_variation
        and old_cache_state in allowed_cache_states
        and new_cache_state in allowed_cache_states
    ):
        return {"compatible": False, "reason_code": "manual_install_verification_provider_identity_drift"}

    old_source = _transport_response_source(old)
    new_source = _transport_response_source(new)
    if old_source is None or new_source is None or old_source != new_source:
        return {"compatible": False, "reason_code": "manual_install_verification_response_source_drift"}

    if old_source == "provider_verified_public_html":
        for stable, identity in ((old, before), (new, after)):
            public_hashes = stable.get("public_rendered_hashes", {})
            if (
                public_hashes.get("head") != identity.get("rendered_head_hash")
                or public_hashes.get("visible") != identity.get("visible_content_hash")
            ):
                return {"compatible": False, "reason_code": "manual_install_verification_rendered_hash_drift"}
    return {
        "compatible": True,
        "reason_code": TRANSPORT_COMPATIBILITY_REASON,
        "canonical_transport": {
            "request_url": canonical_url,
            "final_url": canonical_url,
            "redirect_count": 0,
            "content_type_class": "html",
            "provider": "siteground-nginx",
            "cache_state": (
                "post_mutation_cache_state_variation"
                if old_cache_state != new_cache_state
                else old_cache_state
            ),
            "response_source": old_source,
            "public_identity_source": "signed_browser_evidence",
            "head_hash": after.get("rendered_head_hash"),
            "visible_content_hash": after.get("visible_content_hash"),
        },
    }


def _transport_response_source(transport):
    status = transport.get("status_code")
    classification = transport.get("response_classification")
    if status == 403 and classification == "provider_verified_status_blocked":
        return "provider_verified_html_block"
    if status == 200 and classification in {
        "siteground_cache_provider_verified", "cache_status_hit", "cache_status_miss",
        "cache_status_bypass", "cache_status_expired",
    }:
        return "provider_verified_public_html"
    return None


def _siteground_nginx_provider(provider):
    if not isinstance(provider, dict) or provider.get("verified") is not True:
        return False
    if provider.get("reason_code") != "siteground_cache_provider_verified":
        return False
    headers = provider.get("headers", {})
    return isinstance(headers, dict) and headers.get("server") == "nginx" and any(
        name in headers for name in ("x-proxy-cache-info", "x-cache-enabled", "x-proxy-cache", "x-sg-cache", "x-cache")
    )


def _transport_cache_state(provider):
    headers = provider.get("headers", {}) if isinstance(provider, dict) else {}
    for name in ("x-proxy-cache", "x-sg-cache", "x-cache"):
        value = headers.get(name)
        if value in {"HIT", "MISS", "BYPASS", "EXPIRED"}:
            return value.lower()
    return None


def _audit_backup_deadline_valid(audit):
    try:
        deadline = _timestamp(_active_backup(audit).get("deadline"))
        return deadline > datetime.now(UTC)
    except (TypeError, ValueError):
        return False


def _require_fresh_verification_evidence(audit, request):
    evidence = request.manual_browser_evidence
    value = _evidence_value(evidence)
    evidence_id = str(value.get("evidence_id") or "")
    if evidence_id and hmac.compare_digest(evidence_id, audit.browser_evidence_id):
        _raise_verification_conflict(
            "manual_install_verification_evidence_reused",
            "Manual-install verification requires evidence captured after authorization.",
        )
    valid, reason = upgrade.validate_manual_browser_evidence(
        evidence,
        os.environ.get("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", ""),
    )
    if not valid or not evidence or value.get("evidence_schema_version") != 1:
        text = str(reason or "").lower()
        if "signature" in text:
            code = "manual_install_verification_signature_invalid"
        elif "expired" in text or "future-dated" in text or "timestamp" in text:
            code = "manual_install_verification_evidence_expired"
        else:
            code = "manual_install_verification_evidence_invalid"
        _raise_verification_conflict(code, reason or "Fresh signed schema-v1 evidence is invalid.")
    if _expired(request):
        _raise_verification_conflict(
            "manual_install_verification_backup_drift",
            "The bound SiteGround backup deadline expired; renewal is not supported by this release.",
        )


def _verification_gate_reason(gates):
    failed = {gate.code for gate in gates if not gate.passed}
    if "verification_rendered_hashes" in failed:
        return "manual_install_verification_rendered_hash_drift"
    if "verification_privacy" in failed:
        return "manual_install_verification_privacy_transport_drift"
    if "verification_stable_identity" in failed:
        return "manual_install_verification_stable_identity_mismatch"
    if failed & {"rendered_state", "page_snapshot", "page_identity", "body_hash", "media31", "media32", "site_identity"}:
        return "manual_install_verification_protected_state_drift"
    if failed & {"plugin_inventory", "active_inventory", "unrelated_plugin_drift", "bootstrap_inventory_shape"}:
        return "manual_install_verification_plugin_inventory_drift"
    if failed & {"release_identity", "expected_runtime", "repository_identity", "repository_clean", "protected_paths"}:
        return "manual_install_verification_runtime_drift"
    if failed & {
        "atlas_data_backup", "atlas_media_backup", "atlas_program_backup", "backup_method",
        "backup_reference", "backup_timezone", "backup_window", "database_attestation",
        "plugins_attestation", "restore_attestation", "confirmer", "no_post_backup_change",
    }:
        return "manual_install_verification_backup_drift"
    if "evidence_contract" in failed:
        return "manual_install_verification_signature_invalid"
    return "manual_install_verification_protected_state_drift"


def _raise_verification_conflict(code, message):
    raise HTTPException(409, detail={"reason_code": code, "message": message})


def _protected_rendered(rendered):
    if not isinstance(rendered, dict):
        return rendered
    value = json.loads(json.dumps(rendered, sort_keys=True, default=str))
    public = value.get("public_http_observation")
    if isinstance(public, dict):
        public.pop("observed_at", None)
        public.pop("observation_completed_at", None)
        public.pop("cache_headers", None)
    value.pop("cache_headers", None)
    return value


def _protected_equal(audit, snapshot, *, allow_post_mutation_cache_variation=False):
    comparison = _verification_stable_comparison(
        audit,
        snapshot,
        allow_post_mutation_cache_variation=allow_post_mutation_cache_variation,
    )
    return (
        _protected_non_rendered(snapshot)
        == _protected_non_rendered(audit.protected_state, already_protected=True)
        and comparison["compatible"]
    )


def _verification_fingerprint(request, snapshot, classification, audit):
    return _hash(_verification_proof(request, snapshot, classification, audit))


def _verification_proof(request, snapshot, classification, audit):
    comparison = _verification_stable_comparison(audit, snapshot)
    return {
        "audit": {"id": audit.id, "page_id": audit.generated_page_id, "wordpress_post_id": audit.wordpress_post_id},
        "artifact": {
            "slug": BOOTSTRAP_SLUG, "directory": BOOTSTRAP_DIRECTORY, "entry": BOOTSTRAP_ENTRY,
            "version": BOOTSTRAP_VERSION, "zip_sha256": BOOTSTRAP_ZIP_SHA256,
            "entry_sha256": BOOTSTRAP_ENTRY_SHA256, "status": "inactive",
        },
        "runtime": request.expected_runtime_identity.model_dump(mode="json"),
        "backup": _backup(request),
        "evidence_stable_fingerprint": comparison["canonical_fingerprint"],
        "transport_identity_version": comparison["version"],
        "transport_compatibility_applied": comparison["compatibility_applied"],
        "classification": classification,
        "inventories": _inventories(snapshot),
        "protected": _protected(snapshot),
    }


def _committed_verification_fingerprint(audit):
    snapshot = audit.upload_snapshot or {}
    value = snapshot.get(_VERIFICATION_FINGERPRINT_KEY)
    return value if isinstance(value, str) and len(value) == 64 else ""


def _committed_verification_proof(audit):
    snapshot = audit.upload_snapshot or {}
    value = snapshot.get(_VERIFICATION_PROOF_KEY)
    return value if isinstance(value, dict) else {}


def _retry_conflict_reason(request, snapshot, classification, audit, gates):
    committed = _committed_verification_proof(audit)
    if _protected_non_rendered(snapshot) != _protected_non_rendered(audit.protected_state, already_protected=True):
        return "manual_install_protected_state_drift"
    if classification.get("classification") != "exact_inactive" or _inventories(snapshot) != audit.upload_inventories:
        return "manual_install_inventory_drift"
    if _backup(request) != committed.get("backup"):
        return "manual_install_backup_identity_drift"
    comparison = _verification_stable_comparison(audit, snapshot)
    if comparison["canonical_fingerprint"] != committed.get("evidence_stable_fingerprint"):
        return comparison["reason_code"] if not comparison["compatible"] else "manual_install_verification_stable_identity_mismatch"
    if _retry_stale(request):
        return "manual_install_request_stale"
    if any(not gate.passed for gate in gates):
        return "manual_install_conflicting_retry"
    return "manual_install_retry_not_equivalent"


def _retry_stale(request):
    evidence = request.manual_browser_evidence
    try:
        evidence_expired = not evidence or upgrade._evidence_expiry(evidence.expires_at) <= datetime.now(UTC)
    except (TypeError, ValueError):
        evidence_expired = True
    return _expired(request) or evidence_expired


def _without_bootstrap(plugins):
    return _canonical_plugins([item for item in plugins if not str(item.get("plugin", "")).replace("\\", "/").startswith(BOOTSTRAP_DIRECTORY)])


def _evidence_value(evidence):
    if hasattr(evidence, "model_dump"):
        return evidence.model_dump(mode="json", exclude_none=True)
    return evidence if isinstance(evidence, dict) else {}


def _rendered_observation(snapshot):
    rendered = snapshot.get("rendered", {}) if isinstance(snapshot, dict) else {}
    return rendered if isinstance(rendered, dict) else {}


def _public_observation(snapshot):
    value = _rendered_observation(snapshot).get("public_http_observation", {})
    return value if isinstance(value, dict) else {}


def _rendered_observed_at(snapshot):
    try:
        return cache_binding._public_observed_at(_public_observation(snapshot))
    except (HTTPException, TypeError, ValueError):
        return None


def _stable_rendered_observation(snapshot, evidence):
    """Bind immutable rendered identity while retaining raw observations only for diagnostics."""

    rendered = _rendered_observation(snapshot)
    evidence_value = _evidence_value(evidence)
    return {
        "requested_url": cache_binding.CANONICAL_URL,
        "final_url": rendered.get("final_url"),
        "outcome": rendered.get("outcome"),
        "verified": rendered.get("verified") is True,
        "rendered_head_hash": rendered.get("head_hash"),
        "visible_content_hash": rendered.get("visible_hash"),
        "raw_dom_hash": rendered.get("raw_dom_hash") or _public_observation(snapshot).get("raw_dom_sha256"),
        "document_title": rendered.get("document_title"),
        "ordered_h1_inventory": rendered.get("h1"),
        "canonical_inventory": rendered.get("canonical"),
        "featured_image_url": rendered.get("featured_image_url"),
        "featured_image_alt": rendered.get("featured_image_alt"),
        "metadata_inventory_hash": rendered.get("metadata_inventory_hash"),
        "privacy_attestations": rendered.get("privacy_attestations"),
        "classifications": {
            "signature_validated": rendered.get("signature_validated") is True,
            "atlas_metadata_marker_present": bool(rendered.get("atlas_metadata_marker_present")),
            "media32_reference_present": bool(rendered.get("media32_reference_present")),
        },
        "evidence_identity": {
            "evidence_id": evidence_value.get("evidence_id"),
            "schema": evidence_value.get("evidence_schema"),
            "schema_version": evidence_value.get("evidence_schema_version"),
            "capture_helper_version": evidence_value.get("capture_helper_version"),
            "final_url": evidence_value.get("final_url"),
            "acquisition_source": evidence_value.get("acquisition_source"),
            "navigation_outcome": evidence_value.get("navigation_outcome"),
            "page_identity": evidence_value.get("page_identity"),
            "page_identity_hash": _hash(evidence_value.get("page_identity", {})),
            "metadata_inventory_hash": evidence_value.get("metadata_inventory_hash"),
            "rendered_head_hash": evidence_value.get("rendered_head_hash"),
            "visible_content_hash": evidence_value.get("visible_content_hash"),
            "absence_findings": evidence_value.get("absence_findings"),
            "privacy_attestations": evidence_value.get("privacy_attestations"),
            "signature": evidence_value.get("helper_signature"),
        },
        "public_transport": cache_binding._stable_public_observation(
            _public_observation(snapshot), evidence
        ),
    }


def _stable_rendered_conflict(before, after):
    if before.get("final_url") != after.get("final_url") or after.get("final_url") != cache_binding.CANONICAL_URL:
        return "manual_upload_public_identity_drift"
    before_transport = before.get("public_transport", {})
    after_transport = after.get("public_transport", {})
    if (
        before_transport.get("final_url") != after_transport.get("final_url")
        or before_transport.get("redirect_count") != after_transport.get("redirect_count")
        or before_transport.get("status_code") != after_transport.get("status_code")
        or before_transport.get("response_classification") != after_transport.get("response_classification")
    ):
        return "manual_upload_public_identity_drift"
    if (
        before.get("rendered_head_hash") != after.get("rendered_head_hash")
        or before.get("visible_content_hash") != after.get("visible_content_hash")
        or before.get("raw_dom_hash") != after.get("raw_dom_hash")
        or before_transport.get("body_sha256") != after_transport.get("body_sha256")
        or before_transport.get("public_rendered_hashes") != after_transport.get("public_rendered_hashes")
    ):
        return "manual_upload_rendered_hash_drift"
    if before != after:
        return "manual_upload_stable_observation_mismatch"
    return None


def _preflight_temporal_contract(request, snapshot, backup_deadline):
    observed_at = _rendered_observed_at(snapshot)
    try:
        evidence_value = _evidence_value(request.manual_browser_evidence)
        captured_at = cache_binding._timestamp(evidence_value.get("captured_at"))
        evidence_expires_at = cache_binding._timestamp(evidence_value.get("expires_at"))
        backup = cache_binding._timestamp(backup_deadline)
    except (TypeError, ValueError):
        captured_at = evidence_expires_at = backup = None
    now = datetime.now(UTC)
    aware = all(value is not None and value.tzinfo is not None for value in (observed_at, captured_at, evidence_expires_at, backup))
    fresh = bool(
        aware
        and captured_at <= observed_at <= evidence_expires_at
        and observed_at <= backup
        and observed_at <= now + cache_binding.CLOCK_REVERSAL_TOLERANCE
        and now <= evidence_expires_at
        and now <= backup
    )
    gates = [
        _gate("manual_upload_observation_timestamp", "Rendered observation timestamps are timezone-aware and available", aware, "Rendered observation temporal identity is unavailable."),
        _gate("manual_upload_observation_fresh", "Rendered observation is inside the evidence and backup windows", fresh, "Rendered observation is expired, future-dated, or outside a bound window."),
    ]
    return {
        "gates": gates,
        "complete": bool(aware and fresh),
        "observed_at": observed_at,
        "evidence_expires_at": evidence_expires_at,
        "backup_deadline": backup,
    }


def _manual_temporal_conflict(entry, observed_at, *, now=None):
    if observed_at is None:
        return "manual_upload_observation_expired"
    if (
        entry.maximum_interval != cache_binding.MAX_OBSERVATION_INTERVAL
        or entry.clock_reversal_tolerance != cache_binding.CLOCK_REVERSAL_TOLERANCE
    ):
        return "manual_upload_stable_observation_mismatch"
    code = cache_binding._temporal_conflict(
        preflight_observed_at=entry.preflight_observed_at,
        apply_observed_at=observed_at,
        evidence_expires_at=entry.evidence_expires_at,
        handle_expires_at=entry.expires_at,
        backup_deadline=entry.backup_deadline,
        now=now,
    )
    return {
        "public_observation_expired": "manual_upload_observation_expired",
        "apply_observation_before_preflight": "manual_upload_observation_before_preflight",
        "observation_window_exceeded": "manual_upload_observation_window_exceeded",
    }.get(code, code)


def _activation_temporal_conflict(entry, observed_at):
    code = _manual_temporal_conflict(entry, observed_at)
    return {
        "manual_upload_observation_expired": "bootstrap_activation_observation_expired",
        "manual_upload_observation_before_preflight": "bootstrap_activation_observation_before_preflight",
        "manual_upload_observation_window_exceeded": "bootstrap_activation_observation_window_exceeded",
    }.get(code, code)


def _activation_stable_conflict(code):
    return {
        "manual_upload_public_identity_drift": "bootstrap_activation_public_identity_drift",
        "manual_upload_rendered_hash_drift": "bootstrap_activation_rendered_hash_drift",
        "manual_upload_stable_observation_mismatch": "bootstrap_activation_stable_observation_mismatch",
    }.get(code, code)


def _manual_gate_conflict(gates):
    failed = {gate.code for gate in gates if not gate.passed}
    if failed & {
        "release_identity", "expected_runtime", "repository_identity", "repository_clean",
        "protected_paths",
    }:
        return "manual_upload_runtime_drift"
    if failed & {
        "atlas_data_backup", "atlas_media_backup", "atlas_program_backup", "backup_method",
        "backup_reference", "backup_timezone", "backup_window", "database_attestation",
        "plugins_attestation", "restore_attestation", "confirmer", "no_post_backup_change",
    }:
        return "manual_upload_backup_drift"
    if failed & {"evidence_contract", "rendered_state", "page_snapshot", "page_identity", "body_hash", "media31", "media32", "site_identity"}:
        return "manual_upload_public_identity_drift"
    return "manual_upload_stable_observation_mismatch"


def _raise_manual_conflict(code, message):
    raise HTTPException(409, detail={"reason_code": code, "message": message})


def _raise_activation_conflict(code, message):
    raise HTTPException(409, detail={"reason_code": code, "message": message})


def _binding(
    request, snapshot, audit, action, expires_at, *, stable_rendered_fingerprint,
    preflight_observed_at, evidence_expires_at, backup_deadline,
):
    return {
        "action": action, "targets": {"page_id": 41, "wordpress_post_id": 8, "entry": BOOTSTRAP_ENTRY},
        "artifact": {"version": BOOTSTRAP_VERSION, "zip": BOOTSTRAP_ZIP, "zip_sha256": BOOTSTRAP_ZIP_SHA256, "entry_sha256": BOOTSTRAP_ENTRY_SHA256},
        "runtime": request.expected_runtime_identity.model_dump(mode="json"), "backup": _backup(request),
        "inventory": _inventories(snapshot),
        "protected": {
            **{key: value for key, value in _protected(snapshot).items() if key != "rendered"},
            "stable_rendered_fingerprint": stable_rendered_fingerprint,
        },
        "audit": {"id": audit.id, "status": audit.status} if audit else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "temporal_contract": {
            "preflight_observed_at": preflight_observed_at.isoformat() if preflight_observed_at else None,
            "evidence_expires_at": evidence_expires_at.isoformat() if evidence_expires_at else None,
            "handle_expires_at": expires_at.isoformat() if expires_at else None,
            "backup_deadline": backup_deadline.isoformat() if backup_deadline else None,
            "maximum_interval_seconds": int(cache_binding.MAX_OBSERVATION_INTERVAL.total_seconds()),
            "clock_reversal_tolerance_seconds": int(cache_binding.CLOCK_REVERSAL_TOLERANCE.total_seconds()),
        },
    }


def _backup(request):
    names = [name for name in type(request).model_fields if name.startswith("atlas_") or name.startswith("wordpress_backup") or name.endswith("attestation") or name == "confirmer_identity"]
    return request.model_dump(mode="json", include=set(names), exclude={"manual_browser_evidence"})


def _timestamp(value: Any) -> datetime:
    parsed = cache_binding._timestamp(value)
    if parsed is None or parsed.tzinfo is None:
        raise ValueError("A timezone-aware timestamp is required.")
    return parsed.astimezone(UTC)


def _backup_expiration(backup: dict[str, Any], now: datetime) -> dict[str, Any]:
    value = backup.get("deadline")
    if value in {None, ""}:
        return {"status": "missing", "expired": None, "remaining_seconds": None}
    try:
        deadline = _timestamp(value)
    except (TypeError, ValueError):
        return {"status": "invalid", "expired": None, "remaining_seconds": None}
    remaining = int((deadline - now).total_seconds())
    expired = remaining <= 0
    return {
        "status": "expired" if expired else "valid",
        "expired": expired,
        "remaining_seconds": 0 if expired else remaining,
    }


def _original_backup_for_recovery(audit: WordPressBootstrapEstablishmentAudit) -> dict[str, Any]:
    try:
        return _original_backup(audit)
    except (TypeError, ValueError):
        return json.loads(json.dumps(audit.backup_evidence or {}, sort_keys=True, default=str))


def _active_backup_for_recovery(
    audit: WordPressBootstrapEstablishmentAudit,
    original: dict[str, Any],
) -> dict[str, Any]:
    value = audit.active_backup_evidence if audit.active_backup_evidence is not None else original
    return json.loads(json.dumps(value or {}, sort_keys=True, default=str))


def _usable_backup_identity(value: dict[str, Any]) -> bool:
    return bool(
        value.get("wordpress_backup_reference")
        and value.get("wordpress_backup_completed_at")
        and value.get("deadline")
    )


def _active_backup_source(
    audit: WordPressBootstrapEstablishmentAudit,
    original: dict[str, Any],
    active: dict[str, Any],
) -> str:
    if audit.active_backup_evidence is not None and _usable_backup_identity(active):
        return "replacement"
    if _usable_backup_identity(original):
        return "original"
    return "none"


def _active_renewal_sequence(renewals: list[dict[str, Any]], source: str) -> int | None:
    if source != "replacement" or not renewals:
        return None
    value = renewals[-1].get("sequence")
    return value if isinstance(value, int) and value >= 1 else None


def _renewal_history_for_recovery(
    renewals: list[dict[str, Any]],
    now: datetime,
    active_sequence: int | None,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for item in renewals:
        record = json.loads(json.dumps(item, sort_keys=True, default=str))
        expiration = _backup_expiration(record.get("replacement") or {}, now)
        record["replacement_expired"] = expiration["expired"]
        record["replacement_expiration_status"] = expiration["status"]
        record["replacement_remaining_seconds"] = expiration["remaining_seconds"]
        record["active"] = record.get("sequence") == active_sequence
        values.append(record)
    return values


def _original_backup(audit: WordPressBootstrapEstablishmentAudit) -> dict[str, Any]:
    value = json.loads(json.dumps(audit.backup_evidence or {}, sort_keys=True, default=str))
    completed = value.get("wordpress_backup_completed_at")
    if completed:
        value["deadline"] = upgrade._backup_deadline(_timestamp(completed)).isoformat()
    return value


def _normalized_backup(value: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(value, sort_keys=True, default=str))
    completed = normalized.get("wordpress_backup_completed_at")
    if completed:
        normalized["wordpress_backup_completed_at"] = _timestamp(completed).isoformat()
    return normalized


def _active_backup(audit: WordPressBootstrapEstablishmentAudit, *, include_deadline: bool = True) -> dict[str, Any]:
    value = audit.active_backup_evidence or _original_backup(audit)
    value = json.loads(json.dumps(value, sort_keys=True, default=str))
    if not include_deadline:
        value.pop("deadline", None)
        value.pop("no_relevant_wordpress_change_after_backup", None)
    return value


def _replacement_backup(request: WordPressBootstrapBackupRenewalRequest) -> dict[str, Any]:
    return {
        "atlas_data_backup_file": request.atlas_data_backup_file,
        "atlas_media_backup_file": request.atlas_media_backup_file,
        "atlas_program_backup_file": request.atlas_program_backup_file,
        "wordpress_backup_method": request.replacement_backup_method,
        "wordpress_backup_reference": request.replacement_backup_reference,
        "wordpress_backup_completed_at": request.replacement_backup_completed_at.astimezone(UTC).isoformat(),
        "wordpress_database_included_attestation": request.database_included_attestation,
        "wordpress_plugins_included_attestation": request.plugins_included_attestation,
        "wordpress_restore_capability_attestation": request.restore_capability_attestation,
        "confirmer_identity": request.confirmer_identity,
        "no_relevant_wordpress_change_after_backup": request.no_relevant_wordpress_change_after_backup,
        "deadline": request.replacement_backup_deadline.astimezone(UTC).isoformat(),
    }


def _backup_renewal_phrase(audit_id: int) -> str:
    return f"{BACKUP_RENEWAL_PHRASE_PREFIX} {audit_id}"


def _backup_renewal_binding(audit: WordPressBootstrapEstablishmentAudit, replacement: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_id": audit.id,
        "status": audit.status,
        "transition_history": audit.transition_history,
        "original_backup_identity": _hash(_original_backup(audit)),
        "active_backup_identity": _hash(_active_backup(audit)),
        "replacement_identity": _hash(replacement),
        "renewal_count": len(audit.backup_renewals or []),
        "authorization_evidence_id": audit.browser_evidence_id,
        "protected_state_identity": _hash(audit.protected_state),
    }


def _latest_renewal_matches(audit: WordPressBootstrapEstablishmentAudit, replacement: dict[str, Any]) -> bool:
    renewals = audit.backup_renewals or []
    return bool(renewals and _hash(renewals[-1].get("replacement", {})) == _hash(replacement))


def _pending_operation_exists(session: Session) -> bool:
    models = (
        WordPressActivationAudit,
        WordPressPluginUpgradeAudit,
        WordPressBootstrapCleanupAudit,
        WordPressMetadataLifecycleAudit,
        WordPressCacheAwareRenderingAudit,
    )
    return any(session.exec(select(model).where(model.status == "pending")).first() is not None for model in models)


def _runtime_verified() -> bool:
    try:
        from app.services.wordpress_deployment import deployment_readiness

        value = deployment_readiness()
        release = value.get("release") or {}
        return bool(
            value.get("release_status") == "verified"
            and release.get("runtime_identity_verified") is True
            and release.get("manifest_integrity_verified") is True
            and release.get("expected_release_matched") is True
        )
    except (HTTPException, TypeError, ValueError):
        return False


def _backup_renewal_gates(session, audit, request, *, duplicate: bool):
    replacement = _replacement_backup(request)
    active = _active_backup(audit)
    completed = _timestamp(replacement["wordpress_backup_completed_at"])
    deadline = _timestamp(replacement["deadline"])
    active_completed = _timestamp(active["wordpress_backup_completed_at"])
    active_deadline = _timestamp(active["deadline"])
    method = replacement["wordpress_backup_method"].lower()
    renewals = audit.backup_renewals or []
    other_unresolved = list(session.exec(select(WordPressBootstrapEstablishmentAudit).where(WordPressBootstrapEstablishmentAudit.id != audit.id)))
    other_unresolved = [item for item in other_unresolved if item.status not in {"verified", "authorization_retired", "recovery_required"}]
    return [
        _gate("runtime_identity", "The running Atlas runtime identity is verified", _runtime_verified(), "Runtime identity is unavailable or mismatched."),
        _gate("audit_eligible", "The selected audit awaits manual bootstrap verification", audit.status == "awaiting_manual_bootstrap_installation", "The selected audit state is ineligible."),
        _gate("authorization_preserved", "Original authorization evidence and transition are preserved", bool(audit.browser_evidence_id) and audit.transition_history and audit.transition_history[0] == "awaiting_manual_bootstrap_installation", "Authorization history is incomplete."),
        _gate("verification_absent", "No manual-install verification evidence is recorded", not _verification_evidence_record(audit), "Manual verification already completed."),
        _gate("activation_absent", "Activation and checksum quarantine have not started", not audit.activation_handle_fingerprint and not audit.checksum_verification_result, "Activation or checksum quarantine already started."),
        _gate("conflicting_audit", "No conflicting establishment audit exists", not other_unresolved, "Another unresolved establishment audit exists."),
        _gate("pending_operation", "No other Atlas mutation is pending", not _pending_operation_exists(session), "Another Atlas mutation is pending."),
        _gate("protected_state", "The immutable authorization baseline is internally consistent", _protected(audit.pre_snapshot or {}) == audit.protected_state, "Stored protected state drifted."),
        _gate("renewal_limit", f"Fewer than {MAX_BACKUP_RENEWALS} renewals are recorded", duplicate or len(renewals) < MAX_BACKUP_RENEWALS, "The conservative renewal-chain limit was reached."),
        _gate("original_or_active_expired", "The active backup requires renewal", duplicate or active_deadline <= datetime.now(UTC), "The active backup is still valid."),
        _gate("replacement_method", "Replacement is a SiteGround on-demand full-site backup", "siteground" in method and "on-demand" in method and "full-site" in method, "Replacement backup method is not exact."),
        _gate("replacement_newer", "Replacement backup is newer than the active backup", duplicate or completed > active_completed, "Replacement backup is not newer."),
        _gate("replacement_not_expired", "Replacement deadline is still in the future", deadline > datetime.now(UTC), "Replacement backup expired."),
        _gate("replacement_deadline", "Replacement deadline is exactly four hours after completion", deadline == completed + BACKUP_WINDOW, "Replacement backup deadline is invalid."),
        _gate("database_included", "Replacement includes the database", replacement["wordpress_database_included_attestation"] is True, "Database inclusion is missing."),
        _gate("plugins_included", "Replacement includes wp-content/plugins", replacement["wordpress_plugins_included_attestation"] is True, "Plugin inclusion is missing."),
        _gate("restore_confirmed", "Replacement restore capability is confirmed", replacement["wordpress_restore_capability_attestation"] is True, "Restore capability is unconfirmed."),
        _gate("no_post_backup_change", "No relevant WordPress change followed replacement backup", replacement["no_relevant_wordpress_change_after_backup"] is True, "Post-backup state attestation is missing."),
        _gate("atlas_backups", "Atlas Data, Media, and Program backup identities are supplied", all(replacement[key] for key in ("atlas_data_backup_file", "atlas_media_backup_file", "atlas_program_backup_file")), "Atlas backup identity is missing."),
    ]


def _backup_renewal_failure_reason(gates) -> str:
    failed = {gate.code for gate in gates if not gate.passed}
    mapping = (
        ({"audit_eligible", "authorization_preserved", "verification_absent", "activation_absent", "conflicting_audit", "pending_operation", "renewal_limit"}, "bootstrap_backup_renewal_audit_ineligible"),
        ({"original_or_active_expired"}, "bootstrap_backup_renewal_original_not_expired"),
        ({"replacement_not_expired"}, "bootstrap_backup_renewal_replacement_expired"),
        ({"replacement_newer"}, "bootstrap_backup_renewal_replacement_not_newer"),
        ({"replacement_deadline"}, "bootstrap_backup_renewal_deadline_invalid"),
        ({"restore_confirmed"}, "bootstrap_backup_renewal_restore_unconfirmed"),
        ({"plugins_included"}, "bootstrap_backup_renewal_plugins_missing"),
        ({"database_included"}, "bootstrap_backup_renewal_database_missing"),
        ({"protected_state", "runtime_identity"}, "bootstrap_backup_renewal_state_drift"),
    )
    for codes, reason in mapping:
        if failed & codes:
            return reason
    return "bootstrap_backup_renewal_conflict"


def _store_renewal(request, audit, expires_at):
    raw = secrets.token_urlsafe(32)
    fingerprint = _sha(raw)
    replacement = _replacement_backup(request)
    entry = _RenewalHandle(
        request=request.model_copy(deep=True),
        audit_id=audit.id or 0,
        binding_hash=_hash(_backup_renewal_binding(audit, replacement)),
        expires_at=expires_at,
        fingerprint=fingerprint,
    )
    with _lock:
        _renewal_handles[fingerprint] = entry
        timer = Timer(max(0.0, (expires_at - datetime.now(UTC)).total_seconds()), lambda: _expire_renewal(fingerprint))
        timer.daemon = True
        _timers[("renewal", fingerprint)] = timer
        timer.start()
    return fingerprint


def _expire_renewal(fingerprint):
    with _lock:
        _renewal_handles.pop(fingerprint, None)
        _timers.pop(("renewal", fingerprint), None)


def _consume_renewal(fingerprint):
    with _lock:
        entry = _renewal_handles.pop(fingerprint, None)
        timer = _timers.pop(("renewal", fingerprint), None)
        if timer:
            timer.cancel()
    if entry is None:
        raise HTTPException(409, detail={"reason_code": "bootstrap_backup_renewal_handle_replayed", "message": "Renewal handle is unknown, consumed, or restart-invalidated."})
    if entry.expires_at <= datetime.now(UTC):
        raise HTTPException(409, detail={"reason_code": "bootstrap_backup_renewal_handle_expired", "message": "Renewal handle expired."})
    return entry


def _backup_renewal_result(audit, *, request_atlas_write_count=0, idempotent=False):
    renewals = audit.backup_renewals or []
    return WordPressBootstrapBackupRenewalResult(
        establishment_audit_id=audit.id or 0,
        status="backup_renewed_awaiting_manual_verification",
        reason_code="bootstrap_backup_renewal_already_finalized" if idempotent else "bootstrap_backup_renewal_committed",
        renewal_sequence=len(renewals),
        original_backup=_original_backup(audit),
        active_backup=_active_backup(audit),
        renewal_history=renewals,
        state_history=audit.transition_history,
        idempotent_replay=idempotent,
        request_atlas_write_count=request_atlas_write_count,
        atlas_write_count=audit.atlas_write_count,
        recovery_recommendation="proceed_to_manual_verification",
    )


def _retirement_phrase(audit_id: int) -> str:
    return f"{RETIREMENT_PHRASE_PREFIX} {audit_id} DUE TO GENUINE TRANSPORT DRIFT"


def _retirement_binding(audit, request, comparison, expires_at):
    return {
        "audit_id": audit.id,
        "status": audit.status,
        "history": audit.transition_history,
        "atlas_write_count": audit.atlas_write_count,
        "authorization_snapshot": _hash(audit.pre_snapshot),
        "renewal_history": _hash(audit.backup_renewals or []),
        "reason": request.retirement_reason,
        "transport_reason": comparison.get("reason_code"),
        "runtime": request.expected_runtime_identity.model_dump(mode="json"),
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


def _store_retirement(request, audit_id, binding_hash, expires_at):
    if not expires_at:
        return None
    handle = secrets.token_urlsafe(32)
    with _lock:
        _retirement_handles[handle] = _RetirementHandle(request.model_copy(deep=True), audit_id, binding_hash, expires_at)
        timer = Timer(max(0.0, (expires_at - datetime.now(UTC)).total_seconds()), _discard_retirement, args=(handle,))
        timer.daemon = True
        _timers[("retirement", handle)] = timer
        timer.start()
    return handle


def _consume_retirement(handle):
    with _lock:
        entry = _retirement_handles.pop(handle, None)
        timer = _timers.pop(("retirement", handle), None)
        if timer:
            timer.cancel()
    if not entry:
        raise HTTPException(422, "Retirement handle is unknown, expired, consumed, or restart-invalidated.")
    if entry.expires_at <= datetime.now(UTC):
        raise HTTPException(422, "Retirement handle expired.")
    return entry


def _discard_retirement(handle):
    if not handle:
        return
    with _lock:
        _retirement_handles.pop(handle, None)
        timer = _timers.pop(("retirement", handle), None)
        if timer:
            timer.cancel()


def _store_activation_reconciliation(request, audit_id, binding_hash, expires_at):
    handle = secrets.token_urlsafe(32)
    entry = _ActivationReconciliationHandle(
        request=request.model_copy(deep=True),
        audit_id=audit_id,
        binding_hash=binding_hash,
        expires_at=expires_at,
    )
    with _lock:
        _activation_reconciliation_handles[handle] = entry
        timer = Timer(
            max(0.0, (expires_at - datetime.now(UTC)).total_seconds()),
            _discard_activation_reconciliation,
            args=(handle,),
        )
        timer.daemon = True
        _timers[("activation_reconciliation", handle)] = timer
        timer.start()
    return handle


def _consume_activation_reconciliation(handle):
    with _lock:
        entry = _activation_reconciliation_handles.pop(handle, None)
        timer = _timers.pop(("activation_reconciliation", handle), None)
        if timer:
            timer.cancel()
    if not entry:
        raise HTTPException(
            422,
            "Activation reconciliation handle is unknown, expired, consumed, "
            "or restart-invalidated.",
        )
    if entry.expires_at <= datetime.now(UTC):
        raise HTTPException(422, "Activation reconciliation handle expired.")
    return entry


def _discard_activation_reconciliation(handle):
    if not handle:
        return
    with _lock:
        _activation_reconciliation_handles.pop(handle, None)
        timer = _timers.pop(("activation_reconciliation", handle), None)
        if timer:
            timer.cancel()


def _retirement_result(audit, *, request_atlas_write_count=0, idempotent=False):
    return WordPressBootstrapAuthorizationRetirementResult(
        establishment_audit_id=audit.id or 0,
        retirement_reason=RETIREMENT_REASON,
        state_history=audit.transition_history,
        renewal_history=audit.backup_renewals or [],
        authorization_snapshot_preserved=bool(audit.pre_snapshot),
        verification_evidence_present=_verification_evidence_record(audit) is not None,
        activation_handle_present=bool(audit.activation_handle_fingerprint),
        checksum_quarantine_active=bool(audit.checksum_verification_result),
        pending_operation=False,
        idempotent_replay=idempotent,
        request_atlas_write_count=request_atlas_write_count,
        atlas_write_count=audit.atlas_write_count,
        fresh_authorization_permitted=True,
    )


def _expiry(request):
    now = datetime.now(UTC)
    evidence = upgrade._evidence_expiry(request.manual_browser_evidence.expires_at)
    backup = upgrade._backup_deadline(upgrade._proof(request).wordpress_backup_completed_at)
    value = min(now + HANDLE_TTL, evidence, backup)
    return value if value > now else None


def _expired(request):
    return upgrade._backup_deadline(upgrade._proof(request).wordpress_backup_completed_at) <= datetime.now(UTC)


def _store(
    kind, request, binding_hash, expires_at, audit_id, *,
    stable_rendered_fingerprint="", stable_rendered_observation=None,
    preflight_observed_at=None, evidence_expires_at=None, backup_deadline=None,
):
    if not expires_at:
        return None
    now = datetime.now(UTC)
    handle = secrets.token_urlsafe(32)
    entry = _Handle(
        request=request,
        binding_hash=binding_hash,
        expires_at=expires_at,
        audit_id=audit_id,
        stable_rendered_fingerprint=stable_rendered_fingerprint,
        stable_rendered_observation=stable_rendered_observation or {},
        preflight_observed_at=preflight_observed_at or now,
        evidence_expires_at=evidence_expires_at or expires_at,
        backup_deadline=backup_deadline or expires_at,
        issued_at=now,
        maximum_interval=cache_binding.MAX_OBSERVATION_INTERVAL,
        clock_reversal_tolerance=cache_binding.CLOCK_REVERSAL_TOLERANCE,
    )
    table = _manual_handles if kind == "manual" else _installed_handles if kind == "installed" else _activation_handles
    with _lock:
        table[handle] = entry
        timer = Timer(max(0.0, (expires_at - datetime.now(UTC)).total_seconds()), _expire, args=(kind, handle))
        timer.daemon = True; _timers[(kind, handle)] = timer; timer.start()
    return handle


def _consume(kind, handle):
    table = _manual_handles if kind == "manual" else _installed_handles if kind == "installed" else _activation_handles
    with _lock:
        entry = table.pop(handle, None); timer = _timers.pop((kind, handle), None)
        if timer: timer.cancel()
    if not entry:
        raise HTTPException(422, f"{kind.title()} handle is unknown, expired, consumed, or invalidated by restart.")
    if entry.expires_at <= datetime.now(UTC):
        raise HTTPException(422, f"{kind.title()} handle expired.")
    return entry


def _discard(kind, handle):
    if handle:
        table = _manual_handles if kind == "manual" else _installed_handles if kind == "installed" else _activation_handles
        with _lock:
            table.pop(handle, None); timer = _timers.pop((kind, handle), None)
            if timer: timer.cancel()


def _expire(kind, handle):
    _discard(kind, handle)


def _clear_establishment_handles():
    with _lock:
        for timer in _timers.values(): timer.cancel()
        _manual_handles.clear()
        _installed_handles.clear()
        _activation_handles.clear()
        _renewal_handles.clear()
        _retirement_handles.clear()
        _activation_reconciliation_handles.clear()
        _timers.clear()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()
