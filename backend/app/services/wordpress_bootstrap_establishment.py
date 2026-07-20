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


@dataclass(frozen=True)
class _Handle:
    request: WordPressBootstrapManualInstallPreflightRequest | WordPressBootstrapManualInstallVerifyRequest
    binding_hash: str
    expires_at: datetime
    audit_id: int | None


_lock = Lock()
_manual_handles: dict[str, _Handle] = {}
_activation_handles: dict[str, _Handle] = {}
_timers: dict[tuple[str, str], Timer] = {}


def manual_install_preflight(session: Session, page_id: int, request: WordPressBootstrapManualInstallPreflightRequest) -> WordPressBootstrapEstablishmentPreflight:
    base = upgrade.plugin_upgrade_preflight(session, page_id, request, issue_handle=False)
    classification = _classify(base.inspected_state.get("plugins", []))
    gates = _base_gates(base) + [
        _gate("bootstrap_absent", "No bootstrap is installed before manual upload", classification["classification"] == "no_upload_yet", "A bootstrap or conflicting installation already exists."),
        _gate("establishment_clear", "No unresolved bootstrap-establishment audit exists", not _unresolved(session), "An unresolved bootstrap-establishment audit already exists."),
    ]
    ready = all(g.passed for g in gates)
    expires_at = _expiry(request) if ready else None
    binding = _binding(request, base.inspected_state, None, "manual_upload", expires_at)
    handle = _store("manual", request, _hash(binding), expires_at, None) if ready and expires_at else None
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
    rerun_binding = _hash(_binding(entry.request, base.inspected_state, None, "manual_upload", entry.expires_at))
    if not all(g.passed for g in gates) or rerun_binding != entry.binding_hash:
        raise HTTPException(409, "Manual-upload state changed. Run a new preflight.")
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
        pre_snapshot=base.inspected_state,
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
            status = "installation_partial" if kind == "installation_partial" else "manual_installation_mismatch"
            recommendation = "siteground_restore" if not _protected_equal(audit, base.inspected_state) else "guarded_bootstrap_recovery"
            return _transition(session, audit, status, gates, base.inspected_state, recommendation)

        proof = _verification_proof(request, base.inspected_state, classification, audit)
        fingerprint = _hash(proof)
        audit.upload_snapshot = {
            **base.inspected_state,
            _VERIFICATION_PROOF_KEY: proof,
            _VERIFICATION_FINGERPRINT_KEY: fingerprint,
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
    base, gates, classification = _inspect_against_audit(session, page_id, request, audit, require_inactive=True)
    gates += [
        _gate("audit_upload_verified", "The selected audit records exact inactive upload verification", audit.status == "manual_installation_inventory_verified", "Manual upload has not been verified."),
        _gate("upload_inventory_bound", "The complete inactive inventory matches the verified upload", audit.upload_inventories == _inventories(base.inspected_state), "Plugin inventory changed after upload verification."),
    ]
    ready = all(g.passed for g in gates)
    expires_at = _expiry(request) if ready else None
    binding = _binding(request, base.inspected_state, audit, "activate_fixed_bootstrap", expires_at)
    handle = _store("activation", request, _hash(binding), expires_at, audit.id) if ready and expires_at else None
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
    rerun_binding = _hash(_binding(entry.request, base.inspected_state, audit, "activate_fixed_bootstrap", entry.expires_at))
    if not all(g.passed for g in gates) or rerun_binding != entry.binding_hash:
        raise HTTPException(409, "Bootstrap activation state changed. Run a new activation preflight.")
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
    gates = _base_gates(base) + [
        _gate("bootstrap_inventory_shape", f"Bootstrap inventory is {expected_kind.replace('_', ' ')}", classification["classification"] == expected_kind, "Bootstrap path, version, status, count, or inventory is not exact."),
        _gate("unrelated_plugin_drift", "No unrelated plugin changed", _without_bootstrap(base.inspected_state.get("plugins", [])) == _without_bootstrap(audit.pre_snapshot.get("plugins", [])), "An unrelated plugin changed."),
        _gate("protected_state", "Page, body, media, settings, rendering, payload, revision, and cache remain bound", _protected_equal(audit, base.inspected_state), "Protected state changed."),
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
    return WordPressBootstrapEstablishmentResult(
        establishment_audit_id=audit.id or 0, stage=stage, status=audit.status,
        state_history=audit.transition_history, binding_hash=audit.activation_binding_hash or audit.manual_binding_hash,
        gate_results=gates, inspected_state=snapshot,
        wordpress_write_count=audit.wordpress_write_count, wordpress_write_scope=audit.wordpress_write_scope,
        atlas_write_count=audit.atlas_write_count, atlas_write_scope=audit.atlas_write_scope,
        request_atlas_write_count=request_atlas_write_count, idempotent_replay=idempotent_replay,
        reason_code=reason_code,
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
        "site": snapshot.get("site"), "rendered": snapshot.get("rendered"),
        "cache_headers": snapshot.get("cache_headers"), "cache_purge_count": snapshot.get("cache_purge_count", 0),
        "rendering_enabled": status.get("rendering_enabled"), "payload_hash": status.get("payload_hash"),
        "revision": str(status.get("revision")), "payload": status.get("payload"),
    }


def _protected_equal(audit, snapshot):
    return _protected(snapshot) == audit.protected_state


def _verification_fingerprint(request, snapshot, classification, audit):
    return _hash(_verification_proof(request, snapshot, classification, audit))


def _verification_proof(request, snapshot, classification, audit):
    evidence = request.manual_browser_evidence
    return {
        "audit": {"id": audit.id, "page_id": audit.generated_page_id, "wordpress_post_id": audit.wordpress_post_id},
        "artifact": {
            "slug": BOOTSTRAP_SLUG, "directory": BOOTSTRAP_DIRECTORY, "entry": BOOTSTRAP_ENTRY,
            "version": BOOTSTRAP_VERSION, "zip_sha256": BOOTSTRAP_ZIP_SHA256,
            "entry_sha256": BOOTSTRAP_ENTRY_SHA256, "status": "inactive",
        },
        "runtime": request.expected_runtime_identity.model_dump(mode="json"),
        "backup": _backup(request),
        "evidence_id": evidence.evidence_id if evidence else "",
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
    evidence = request.manual_browser_evidence
    if (evidence.evidence_id if evidence else "") != committed.get("evidence_id"):
        return "manual_install_evidence_mismatch"
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


def _binding(request, snapshot, audit, action, expires_at):
    return {
        "action": action, "targets": {"page_id": 41, "wordpress_post_id": 8, "entry": BOOTSTRAP_ENTRY},
        "artifact": {"version": BOOTSTRAP_VERSION, "zip": BOOTSTRAP_ZIP, "zip_sha256": BOOTSTRAP_ZIP_SHA256, "entry_sha256": BOOTSTRAP_ENTRY_SHA256},
        "runtime": request.expected_runtime_identity.model_dump(mode="json"), "backup": _backup(request),
        "inventory": _inventories(snapshot), "protected": _protected(snapshot),
        "audit": {"id": audit.id, "status": audit.status} if audit else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
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


def _store(kind, request, binding_hash, expires_at, audit_id):
    if not expires_at:
        return None
    handle = secrets.token_urlsafe(32)
    entry = _Handle(request, binding_hash, expires_at, audit_id)
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
