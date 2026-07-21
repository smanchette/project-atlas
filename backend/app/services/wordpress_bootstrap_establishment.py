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
import secrets
from threading import Lock, Timer
from typing import Any

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import WordPressBootstrapEstablishmentAudit
from app.schemas.wordpress import (
    WordPressBootstrapActivationApplyRequest,
    WordPressBootstrapEstablishmentPreflight,
    WordPressBootstrapEstablishmentResult,
    WordPressBootstrapManualInstallAuthorizeRequest,
    WordPressBootstrapManualInstallPreflightRequest,
    WordPressBootstrapManualInstallVerifyRequest,
    WordPressBootstrapRecoveryAssessment,
    WordPressDraftGateResult,
)
from app.services import wordpress_plugin_upgrade_0577 as upgrade
from app.services import wordpress_cache_aware_rendering as cache_binding
from app.services.wordpress_deployment import _canonical_plugins, _gate
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
ACTIVATION_SCOPE = [
    f"POST /wp-json/wp/v2/plugins/{BOOTSTRAP_REST_ID}",
    'request JSON keys exactly ["status"] with value "active"',
]
ATLAS_SCOPE = [
    "create or update only one WordPressBootstrapEstablishmentAudit",
    "record state transitions and read-only verification findings",
]
_BASE_IGNORED_GATE_CODES = {"upgrade_bootstrap", "bootstrap_establishment_audit", "plugin_inventory", "expected_post_inventory"}
_VERIFICATION_FINGERPRINT_KEY = "_atlas_manual_install_verification_fingerprint"
_VERIFICATION_PROOF_KEY = "_atlas_manual_install_verification_proof"
_AUTHORIZATION_EVIDENCE_KEY = "_atlas_authorization_evidence"
_VERIFICATION_EVIDENCE_KEY = "_atlas_verification_evidence"


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


_lock = Lock()
_manual_handles: dict[str, _Handle] = {}
_activation_handles: dict[str, _Handle] = {}
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
                    _verification_gate_reason(gates),
                    "Fresh manual-install verification did not match the authorized stable state.",
                )
            status = "installation_partial" if kind == "installation_partial" else "manual_installation_mismatch"
            recommendation = "siteground_restore" if not _protected_equal(audit, base.inspected_state) else "guarded_bootstrap_recovery"
            return _transition(session, audit, status, gates, base.inspected_state, recommendation)

        proof = _verification_proof(request, base.inspected_state, classification, audit)
        fingerprint = _hash(proof)
        verification_evidence = _evidence_record(
            request.manual_browser_evidence,
            base.inspected_state,
            result="stable_identity_matched",
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
    recommendation = "siteground_restore" if not _protected_equal(audit, base.inspected_state) else "guarded_bootstrap_recovery"
    return _transition(
        session, audit, "recovery_required", all_gates,
        {**base.inspected_state, "bootstrap_status": upgrade._safe_bootstrap_status(status)},
        recommendation, request_atlas_write_count=3,
    )


def assess_recovery(session: Session, page_id: int, request: WordPressBootstrapManualInstallVerifyRequest) -> WordPressBootstrapRecoveryAssessment:
    audit = _audit(session, request.establishment_audit_id)
    base, gates, classification = _inspect_against_audit(session, page_id, request, audit, require_inactive=False)
    kind = classification["classification"]
    status = upgrade._read_bootstrap_status(session) if kind == "exact_active" else {"_error": "inactive_or_absent"}
    checksum = status.get("bootstrap_checksum")
    protected = _protected_equal(audit, base.inspected_state)
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
    verification_drift = _verification_stable_drift_reason(audit, base.inspected_state)
    gates = _base_gates(base) + [
        _gate("bootstrap_inventory_shape", f"Bootstrap inventory is {expected_kind.replace('_', ' ')}", classification["classification"] == expected_kind, "Bootstrap path, version, status, count, or inventory is not exact."),
        _gate("unrelated_plugin_drift", "No unrelated plugin changed", _without_bootstrap(base.inspected_state.get("plugins", [])) == _without_bootstrap(audit.pre_snapshot.get("plugins", [])), "An unrelated plugin changed."),
        _gate("protected_state", "Page, body, media, settings, rendering, payload, revision, and cache remain bound", _protected_non_rendered(base.inspected_state) == _protected_non_rendered(audit.protected_state, already_protected=True), "Protected state changed."),
        _gate("verification_stable_identity", "Fresh evidence matches the authorized stable public identity", verification_drift is None, "Fresh rendered evidence changed stable public identity."),
        _gate("verification_rendered_hashes", "Fresh rendered hashes match authorization", verification_drift != "manual_install_verification_rendered_hash_drift", "Rendered-head, visible-content, or raw-DOM identity changed."),
        _gate("verification_privacy", "Fresh evidence preserves the credential-free privacy classification", verification_drift != "manual_install_verification_privacy_drift", "Cookie, authentication, admin, login, challenge, or error classification changed."),
        _gate("active_inventory", "Active inventory matches the required lifecycle state", (base.inspected_state.get("active_plugin_inventory_hash") == audit.source_inventories.get("active")) if require_inactive else True, "Active inventory changed before guarded activation."),
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
    elif candidates[0].get("status") in {"active", "network-active"}:
        kind = "exact_active"
    else:
        kind = "installation_partial"
    return {"classification": kind, "count": len(candidates), "conflict_count": len(conflicts), "entry": candidates[0] if len(candidates) == 1 else None}


def _activate_fixed_entry(session):
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password):
        return {"accepted": False, "request_performed": False, "_error": "credentials_unavailable", "request_keys": ["status"]}
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.post(
                f"{settings.site_url.rstrip('/')}/wp-json/wp/v2/plugins/{BOOTSTRAP_REST_ID}",
                json={"status": "active"}, auth=httpx.BasicAuth(settings.username, password),
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
        payload = response.json() if response.status_code == 200 else {}
        accepted = isinstance(payload, dict) and response.status_code == 200 and payload.get("status") in {"active", "network-active"} and payload.get("version") == BOOTSTRAP_VERSION and str(payload.get("plugin", "")).replace("\\", "/") in {BOOTSTRAP_ENTRY, BOOTSTRAP_REST_ID}
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
            and authorization_evidence.get("stable_fingerprint")
            == verification_evidence.get("stable_fingerprint")
        ),
        fresh_evidence_required=audit.status == "awaiting_manual_bootstrap_installation",
        backup_deadline_valid=_audit_backup_deadline_valid(audit),
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
    return any(a.status != "verified" for a in session.exec(select(WordPressBootstrapEstablishmentAudit)))


def _inventories(snapshot):
    return {"plugins": snapshot.get("plugin_inventory_hash"), "active": snapshot.get("active_plugin_inventory_hash")}


def _protected(snapshot):
    status = snapshot.get("plugin_status", {}).get("snapshot", {})
    return {
        "page": snapshot.get("page_snapshot_hash"), "body": snapshot.get("page_body_hash"),
        "media31": snapshot.get("media31_snapshot_hash"), "media32": snapshot.get("media32_snapshot_hash"),
        "site": snapshot.get("site"), "rendered": _protected_rendered(snapshot.get("rendered")),
        "cache_headers": _stable_diagnostic_headers(snapshot.get("cache_headers")), "cache_purge_count": snapshot.get("cache_purge_count", 0),
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


def _evidence_record(evidence, snapshot, *, result):
    value = _evidence_value(evidence)
    return {
        "evidence_id": value.get("evidence_id"),
        "captured_at": value.get("captured_at"),
        "expires_at": value.get("expires_at"),
        "schema": value.get("evidence_schema"),
        "schema_version": value.get("evidence_schema_version"),
        "capture_helper_version": value.get("capture_helper_version"),
        "stable_fingerprint": _stable_verification_fingerprint(snapshot),
        "result": result,
    }


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


def _authorization_stable_fingerprint(audit):
    return str(_authorization_evidence_record(audit).get("stable_fingerprint") or "")


def _verification_stable_drift_reason(audit, snapshot):
    before = _stable_verification_observation(audit.pre_snapshot or {})
    after = _stable_verification_observation(snapshot)
    hash_keys = ("rendered_head_hash", "visible_content_hash", "raw_dom_hash")
    if any(before.get(key) != after.get(key) for key in hash_keys):
        return "manual_install_verification_rendered_hash_drift"
    if (
        before.get("privacy_attestations") != after.get("privacy_attestations")
        or before.get("classifications") != after.get("classifications")
        or before.get("public_transport", {}).get("challenge_error")
        != after.get("public_transport", {}).get("challenge_error")
    ):
        return "manual_install_verification_privacy_drift"
    if before != after:
        return "manual_install_verification_stable_identity_mismatch"
    return None


def _audit_backup_deadline_valid(audit):
    try:
        completed = (audit.backup_evidence or {}).get("wordpress_backup_completed_at")
        parsed = cache_binding._timestamp(completed) if completed else None
        return bool(parsed and upgrade._backup_deadline(parsed) > datetime.now(UTC))
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
        return "manual_install_verification_privacy_drift"
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


def _stable_diagnostic_headers(headers):
    if not isinstance(headers, dict):
        return headers
    volatile = {"age", "date", "expires", "last-modified"}
    return {
        str(key).lower(): value
        for key, value in headers.items()
        if str(key).lower() not in volatile
    }


def _protected_rendered(rendered):
    if not isinstance(rendered, dict):
        return rendered
    value = json.loads(json.dumps(rendered, sort_keys=True, default=str))
    public = value.get("public_http_observation")
    if isinstance(public, dict):
        public.pop("observed_at", None)
        public.pop("observation_completed_at", None)
        public["cache_headers"] = _stable_diagnostic_headers(public.get("cache_headers"))
    value["cache_headers"] = _stable_diagnostic_headers(value.get("cache_headers"))
    return value


def _protected_equal(audit, snapshot):
    return (
        _protected_non_rendered(snapshot)
        == _protected_non_rendered(audit.protected_state, already_protected=True)
        and _stable_verification_fingerprint(snapshot)
        == _authorization_stable_fingerprint(audit)
    )


def _verification_fingerprint(request, snapshot, classification, audit):
    return _hash(_verification_proof(request, snapshot, classification, audit))


def _verification_proof(request, snapshot, classification, audit):
    return {
        "audit": {"id": audit.id, "page_id": audit.generated_page_id, "wordpress_post_id": audit.wordpress_post_id},
        "artifact": {
            "slug": BOOTSTRAP_SLUG, "directory": BOOTSTRAP_DIRECTORY, "entry": BOOTSTRAP_ENTRY,
            "version": BOOTSTRAP_VERSION, "zip_sha256": BOOTSTRAP_ZIP_SHA256,
            "entry_sha256": BOOTSTRAP_ENTRY_SHA256, "status": "inactive",
        },
        "runtime": request.expected_runtime_identity.model_dump(mode="json"),
        "backup": _backup(request),
        "evidence_stable_fingerprint": _stable_verification_fingerprint(snapshot),
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
    if _protected(snapshot) != audit.protected_state:
        return "manual_install_protected_state_drift"
    if classification.get("classification") != "exact_inactive" or _inventories(snapshot) != audit.upload_inventories:
        return "manual_install_inventory_drift"
    if _backup(request) != committed.get("backup"):
        return "manual_install_backup_identity_drift"
    if _stable_verification_fingerprint(snapshot) != committed.get("evidence_stable_fingerprint"):
        return "manual_install_verification_stable_identity_mismatch"
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
    table = _manual_handles if kind == "manual" else _activation_handles
    with _lock:
        table[handle] = entry
        timer = Timer(max(0.0, (expires_at - datetime.now(UTC)).total_seconds()), _expire, args=(kind, handle))
        timer.daemon = True; _timers[(kind, handle)] = timer; timer.start()
    return handle


def _consume(kind, handle):
    table = _manual_handles if kind == "manual" else _activation_handles
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
        table = _manual_handles if kind == "manual" else _activation_handles
        with _lock:
            table.pop(handle, None); timer = _timers.pop((kind, handle), None)
            if timer: timer.cancel()


def _expire(kind, handle):
    _discard(kind, handle)


def _clear_establishment_handles():
    with _lock:
        for timer in _timers.values(): timer.cancel()
        _manual_handles.clear(); _activation_handles.clear(); _timers.clear()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()
