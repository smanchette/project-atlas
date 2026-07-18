from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
import re
import secrets
from threading import Lock, Timer
from typing import Any, Literal

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    WordPressActivationAudit,
    WordPressDeploymentAudit,
    WordPressMetadataLifecycleAudit,
    WordPressCacheAwareRenderingAudit,
    WordPressMetadataState,
    WordPressMetadataSyncAudit,
)
from app.schemas.wordpress import (
    WordPressDeploymentBackupEvidence,
    WordPressDraftGateResult,
    WordPressMetadataLifecycleApplyRequest,
    WordPressMetadataLifecyclePreflight,
    WordPressMetadataLifecyclePreflightRequest,
    WordPressMetadataLifecycleResult,
    WordPressMetadataLifecyclePayload,
)
from app.services.wordpress_deployment import (
    EXPECTED_CORRECTED_BODY_HASH,
    _backup_deadline,
    _backup_gates,
    _gate,
    _hash,
    _clean_findings,
    _matching_reconciliation_plugins,
    _observe,
    _rendered_metadata_absent,
    _target,
    _verify_artifact as _verify_release_artifact,
)
from app.services.wordpress_deployment_release import SOURCE_EXPECTATIONS
from app.services.wordpress_deployment_release import resolve_program_root
from app.services.wordpress_rendered_state import EXPECTED_H1, validate_manual_browser_evidence
from app.services.wordpress_sandbox import get_wordpress_application_password, read_wordpress_settings


Action = Literal[
    "stage_metadata_payload",
    "enable_metadata_rendering",
    "disable_metadata_rendering",
    "rollback_metadata_payload",
]

PLUGIN_VERSION = "0.57.6"
PLUGIN_SLUG = "project-atlas-metadata-bridge"
PLUGIN_ENTRY = "project-atlas-metadata-bridge/project-atlas-metadata-bridge.php"
ATLAS_METADATA_SAFETY_OPTION_NAME = "_project_atlas_metadata_safety_v1"
HANDLE_TTL = timedelta(minutes=10)
PHRASES: dict[Action, str] = {
    "stage_metadata_payload": "STAGE PROJECT ATLAS METADATA PAYLOAD",
    "enable_metadata_rendering": "ENABLE PROJECT ATLAS METADATA RENDERING",
    "disable_metadata_rendering": "DISABLE PROJECT ATLAS METADATA RENDERING",
    "rollback_metadata_payload": "ROLL BACK PROJECT ATLAS METADATA PAYLOAD",
}
PLUGIN_PATHS: dict[Action, str] = {
    "stage_metadata_payload": "/wp-json/project-atlas/v2/pages/8/metadata/stage",
    "enable_metadata_rendering": "/wp-json/project-atlas/v2/pages/8/metadata/rendering/enable",
    "disable_metadata_rendering": "/wp-json/project-atlas/v2/pages/8/metadata/rendering/disable",
    "rollback_metadata_payload": "/wp-json/project-atlas/v2/pages/8/metadata/stage/rollback",
}
WORDPRESS_SCOPES: dict[Action, list[str]] = {
    action: [f"PUT {path}", "one plugin-owned metadata lifecycle mutation; no page, media, site identity, plugin-state, or cache write"]
    for action, path in PLUGIN_PATHS.items()
}
ATLAS_SCOPE = ["create one pending WordPressMetadataLifecycleAudit", "finalize that audit and the single page-41 WordPressMetadataState after read-only verification"]
STANDARD_MODE = "standard"
ORDINARY_DISABLE_MODE = "ordinary_after_verified_enable"
RECOVERY_DISABLE_MODE = "recovery_after_failed_enable_verification"

# This is the exact field contract enforced by
# atlas_metadata_snapshot_hash() in Metadata Bridge 0.57.6.  Repository,
# plugin identity, page, media, site, and cache bindings remain in the signed
# Atlas lifecycle binding; they are intentionally not added to this plugin-owned
# optimistic hash because the installed plugin does not hash those fields.
OPTIMISTIC_SNAPSHOT_FIELDS = (
    "rendering_enabled",
    "enabled_metadata_state",
    "activation_generation",
    "plugin_checksum",
    "payload_hash",
    "revision",
    "payload",
)

SAFE_WORDPRESS_CONFLICT_CODES = {
    "atlas_snapshot_conflict": "optimistic_snapshot_hash_mismatch",
    "atlas_revision_conflict": "snapshot_field_mismatch",
    "atlas_stage_state_conflict": "snapshot_field_mismatch",
    "atlas_enable_state_conflict": "snapshot_field_mismatch",
    "atlas_disable_state_conflict": "snapshot_field_mismatch",
    "atlas_rollback_state_conflict": "snapshot_field_mismatch",
    "atlas_post_changed": "snapshot_field_mismatch",
    "atlas_media_changed": "snapshot_field_mismatch",
    "atlas_hash_mismatch": "snapshot_field_mismatch",
}


@dataclass(frozen=True)
class _HandleEntry:
    action: Action
    request: WordPressMetadataLifecyclePreflightRequest
    binding_hash: str
    expires_at: datetime


_handle_lock = Lock()
_handles: dict[str, _HandleEntry] = {}
_timers: dict[str, Timer] = {}


def approved_payload() -> WordPressMetadataLifecyclePayload:
    """The canonical, media-free Organization + Service payload approved for Orlando."""
    organization_id = "https://www.drywoodtenting.com/#organization"
    service_id = "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/#service"
    return WordPressMetadataLifecyclePayload(
        meta_description="Flo-Zone Pest And Termite Solutions Inc provides professional drywood termite tenting services for homes and properties in Orlando, Florida.",
        json_ld={
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "Organization",
                    "@id": organization_id,
                    "name": "Flo-Zone Pest And Termite Solutions Inc",
                    "telephone": "(844) 600-8368",
                    "email": "Office@Flo-ZoneTenting.com",
                    "identifier": {"@type": "PropertyValue", "name": "License", "value": "JB360566"},
                },
                {
                    "@type": "Service",
                    "@id": service_id,
                    "serviceType": "Drywood termite tenting",
                    "areaServed": "Orlando, Florida",
                    "provider": {"@id": organization_id},
                },
            ],
        },
    )


def payload_sha256(payload: WordPressMetadataLifecyclePayload | dict[str, Any] | None = None) -> str:
    value = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    return hashlib.sha256(json.dumps(value or approved_payload().model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _verify_artifact():
    """Use release identity gates plus the separately locked 0.57.6 lifecycle artifact."""
    artifact, gates = _verify_release_artifact()
    from app.services.wordpress_cache_aware_rendering import _artifact_identity

    lifecycle_artifact = _artifact_identity()
    artifact.update(
        plugin_version=PLUGIN_VERSION,
        zip_file_name=lifecycle_artifact.get("zip_name"),
        zip_sha256=lifecycle_artifact.get("zip_sha256"),
    )
    retained = [gate for gate in gates if gate.code in {"program_root", "release_identity"}]
    retained.extend(
        [
            _gate("artifact_hash", "Lifecycle ZIP SHA-256 is locked", lifecycle_artifact.get("valid") is True, lifecycle_artifact.get("error") or "Lifecycle ZIP checksum mismatch."),
            _gate("artifact_portable", "Lifecycle ZIP is portable and byte-equal to source", lifecycle_artifact.get("byte_equal") is True and lifecycle_artifact.get("portable") is True, "Lifecycle ZIP structure/source mismatch."),
        ]
    )
    return artifact, retained


def lifecycle_preflight(
    session: Session,
    page_id: int,
    request: WordPressMetadataLifecyclePreflightRequest,
    action: Action,
    *,
    issue_handle: bool = True,
    bound_expiry: datetime | None = None,
) -> WordPressMetadataLifecyclePreflight:
    """Run the shared inspection. This function performs no Atlas or WordPress write."""
    _target(page_id)
    proof = WordPressDeploymentBackupEvidence.model_validate(
        request.model_dump(mode="json", include=set(WordPressDeploymentBackupEvidence.model_fields))
    )
    expected_payload = approved_payload()
    expected_hash = payload_sha256(expected_payload)
    evidence_ok, evidence_reason = validate_manual_browser_evidence(
        request.manual_browser_evidence,
        os.getenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", ""),
    )
    evidence_ok = bool(evidence_ok and request.manual_browser_evidence.evidence_schema_version == 1)
    if request.manual_browser_evidence.evidence_schema_version != 1:
        evidence_reason = "Metadata lifecycle requires fresh schema-v1 evidence."
    artifact, artifact_gates = _verify_artifact()
    artifact_error = "; ".join(g.message for g in artifact_gates if not g.passed) or None
    observed = _observe(session, proof) if evidence_ok and not artifact_error else _unavailable(evidence_reason or artifact_error)
    plugin_status = _read_status(session) if "_error" not in observed else {"_error": "observation_unavailable"}
    snapshot = plugin_status.get("snapshot") if isinstance(plugin_status.get("snapshot"), dict) else plugin_status
    snapshot_error = _snapshot_contract_error(plugin_status)
    installation = session.get(WordPressDeploymentAudit, request.installation_audit_id)
    activation = session.get(WordPressActivationAudit, request.activation_audit_id)
    lifecycle_audits = list(session.exec(select(WordPressMetadataLifecycleAudit).where(WordPressMetadataLifecycleAudit.generated_page_id == 41).order_by(WordPressMetadataLifecycleAudit.id)))
    cache_aware_audits = list(session.exec(select(WordPressCacheAwareRenderingAudit).where(WordPressCacheAwareRenderingAudit.generated_page_id == 41).order_by(WordPressCacheAwareRenderingAudit.id)))
    state = session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == 41)).first()
    legacy_sync_audits = list(session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id == 41)))
    disable_eligibility = (
        _disable_eligibility(snapshot, state, lifecycle_audits, expected_hash, observed, legacy_sync_audits, cache_aware_audits)
        if action == "disable_metadata_rendering"
        else None
    )
    gates = [
        _gate("artifact", "Published plugin artifact is verified", not artifact_error and artifact.get("plugin_version") == PLUGIN_VERSION and artifact.get("zip_sha256") == SOURCE_EXPECTATIONS.plugin_zip_sha256, artifact_error or "Plugin artifact identity differs."),
        *_backup_gates(proof),
        _gate("evidence", "Fresh signed schema-v1 public evidence is valid", evidence_ok, evidence_reason or "Fresh evidence required."),
        _gate("runtime", "Runtime and independent expected identity are verified", bool(artifact.get("release_runtime_identity_verified") and artifact.get("release_manifest_integrity_verified") and artifact.get("release_expected_identity_matched")), "Runtime identity is unavailable or stale."),
        _gate("repository", "Repository identity and protected-path attestations are exact", request.repository_head == request.repository_origin_main == request.expected_runtime_identity.atlas_commit and request.repository_tag == request.expected_runtime_identity.atlas_tag and request.repository_working_tree_clean and request.protected_paths_unchanged, "Repository identity, cleanliness, or protected paths differ."),
        _gate("post_backup", "No relevant WordPress change followed backup creation", request.no_relevant_wordpress_change_after_backup, "A fresh SiteGround backup is required."),
        _gate("installation_audit", "Installation audit 1 remains verified", bool(installation and installation.id == 1 and installation.status == "verified"), "Verified installation audit 1 required."),
        _gate("activation_audit", "Activation audit 1 remains verified", bool(activation and activation.id == 1 and activation.status == "verified"), "Verified activation audit 1 required."),
        _gate("plugin", "Metadata Bridge 0.57.6 is installed exactly once and active", _plugin_exact(observed), "The cache-aware lifecycle bridge must be installed once and active."),
        _gate("plugin_identity", "Expected plugin path, version, ZIP, and inventories are exact", request.expected_plugin_slug == PLUGIN_SLUG and request.expected_plugin_path == PLUGIN_ENTRY and request.expected_plugin_version == PLUGIN_VERSION and request.expected_zip_sha256 == SOURCE_EXPECTATIONS.plugin_zip_sha256 and observed.get("plugin_inventory_hash") == request.expected_plugin_inventory_hash and observed.get("active_plugin_inventory_hash") == request.expected_active_plugin_inventory_hash, "Plugin artifact or inventory identity drifted."),
        _gate("plugin_status", "Plugin status endpoint is available and exact", plugin_status.get("version") == PLUGIN_VERSION and plugin_status.get("active") is True and not plugin_status.get("_error"), "Plugin status is unavailable or mismatched."),
        _gate("optimistic_snapshot", "Plugin-owned optimistic snapshot is complete and canonical", snapshot_error is None, snapshot_error or "Optimistic snapshot is unavailable."),
        _gate("legacy_metadata_audits", "Legacy combined metadata-sync audits remain absent", not legacy_sync_audits, "A legacy combined metadata operation exists."),
        _gate("candidate_payload", "Candidate payload is exactly the canonical approved payload", request.candidate_payload.model_dump(mode="json") == expected_payload.model_dump(mode="json"), "Candidate payload includes a mismatch or unapproved schema node."),
        _gate("page", "Page 8 identity, body, title, status, slug, URL, and featured media remain exact", observed.get("page_body_hash") == request.expected_body_hash == EXPECTED_CORRECTED_BODY_HASH and observed.get("page_snapshot_hash") == request.expected_page_snapshot_hash and observed.get("page", {}).get("id") == 8 and observed.get("page", {}).get("status") == "publish" and observed.get("page", {}).get("featured_media") == 31, "Page 8 changed."),
        _gate("rendered_h1", "Exactly one unchanged visible H1 renders", observed.get("rendered", {}).get("h1") == [EXPECTED_H1], "Rendered H1 changed."),
        _gate("media31", "Media 31 snapshot remains exact", observed.get("media31_snapshot_hash") == request.expected_media31_snapshot_hash, "Media 31 changed."),
        _gate("media32", "Media 32 remains exact and absent", observed.get("media32_snapshot_hash") == request.expected_media32_snapshot_hash and not observed.get("page_references_media32") and not observed.get("rendered", {}).get("media32_reference_present"), "Media 32 changed or is referenced."),
        _gate("site", "Site Title and Tagline remain exact", observed.get("site") == {"name": "My WordPress", "description": ""}, "Site identity changed."),
        _gate("php_findings", "PHP, REST, and header findings are clean", _clean_findings(request.php_error_log_findings), "PHP, REST, or header findings require review."),
        _gate("browser_findings", "Browser-console and visible-site findings are clean", _clean_findings(request.browser_console_findings), "Browser or visible-site findings require review."),
        _gate("read_only", "Preflight performed GET/read requests only", observed.get("wordpress_request_methods") == ["GET"], "Preflight did not remain read-only."),
        *_operation_gates(
            action,
            snapshot,
            state,
            lifecycle_audits,
            expected_hash,
            observed,
            legacy_sync_audits,
            disable_eligibility=disable_eligibility,
            cache_aware_audits=cache_aware_audits,
        ),
    ]
    ready = all(g.passed for g in gates)
    expires_at = bound_expiry
    if ready and expires_at is None:
        evidence_expiry = _parse_timestamp(request.manual_browser_evidence.expires_at)
        expires_at = min(datetime.now(UTC) + HANDLE_TTL, evidence_expiry, _backup_deadline(proof.wordpress_backup_completed_at))
    if ready and (not expires_at or expires_at <= datetime.now(UTC)):
        ready = False
        gates.append(_gate("lifetime", "Handle has a positive bounded lifetime", False, "Evidence or backup expires before authorization."))
    binding = _binding(action, request, observed, snapshot, lifecycle_audits, expected_hash, expires_at, cache_aware_audits)
    binding_hash = _hash(binding)
    handle = fingerprint = None
    if ready and issue_handle and expires_at:
        handle = _store_handle(action, request, binding_hash, expires_at)
        fingerprint = hashlib.sha256(handle.encode()).hexdigest()
    return WordPressMetadataLifecyclePreflight(
        action=action,
        status="metadata_lifecycle_preflight_ready" if ready else "metadata_lifecycle_preflight_blocked",
        preflight_ready=ready,
        lifecycle_handle=handle,
        handle_fingerprint=fingerprint,
        expires_at=expires_at if ready else None,
        binding_hash=binding_hash if ready else None,
        confirmation_phrase=PHRASES[action] if ready else None,
        canonical_payload=expected_payload,
        payload_sha256=expected_hash,
        expected_revision=_expected_revision(action),
        completion_mode=(disable_eligibility or {}).get("completion_mode", STANDARD_MODE),
        inspected_state={
            **observed,
            "plugin_status": _public_status(plugin_status),
            **(
                {"staging_history": _staging_history_eligibility(lifecycle_audits, state, legacy_sync_audits)}
                if action == "stage_metadata_payload"
                else {}
            ),
            **({"disable_eligibility": disable_eligibility} if disable_eligibility is not None else {}),
        },
        gate_results=gates,
        proposed_wordpress_write_scope=WORDPRESS_SCOPES[action] if ready else [],
        proposed_atlas_write_scope=ATLAS_SCOPE if ready else [],
    )


def apply_lifecycle(session: Session, page_id: int, request: WordPressMetadataLifecycleApplyRequest, action: Action) -> WordPressMetadataLifecycleResult:
    """Consume one handle and execute one fixed plugin-owned lifecycle mutation."""
    _target(page_id)
    if not hmac.compare_digest(request.confirmation_phrase, PHRASES[action]):
        raise HTTPException(422, "The metadata lifecycle confirmation phrase is incorrect.")
    entry = _consume_handle(request.lifecycle_handle, action)
    rerun = lifecycle_preflight(session, page_id, entry.request, action, issue_handle=False, bound_expiry=entry.expires_at)
    if not rerun.preflight_ready or rerun.binding_hash != entry.binding_hash:
        raise HTTPException(409, "Metadata lifecycle state changed. Run a new preflight.")
    before = rerun.inspected_state["plugin_status"]
    fingerprint = hashlib.sha256(request.lifecycle_handle.encode()).hexdigest()
    evidence = entry.request.manual_browser_evidence
    audit = WordPressMetadataLifecycleAudit(
        generated_page_id=41,
        wordpress_post_id=8,
        installation_audit_id=entry.request.installation_audit_id,
        activation_audit_id=entry.request.activation_audit_id,
        action_type=action,
        completion_mode=getattr(rerun, "completion_mode", STANDARD_MODE),
        status="pending",
        operator=entry.request.operator,
        confirmation_phrase_hash=hashlib.sha256(PHRASES[action].encode()).hexdigest(),
        handle_fingerprint=fingerprint,
        binding_hash=entry.binding_hash,
        release_identity=entry.request.expected_runtime_identity.model_dump(mode="json"),
        backup_evidence=entry.request.model_dump(mode="json", include=set(WordPressDeploymentBackupEvidence.model_fields), exclude={"manual_browser_evidence"}),
        browser_evidence_id=evidence.evidence_id,
        browser_evidence_hashes={"rendered_head_hash": evidence.rendered_head_hash, "visible_content_hash": evidence.visible_content_hash, "schema_version": evidence.evidence_schema_version},
        payload_hash=rerun.payload_sha256,
        previous_revision=str(before.get("revision", "0")),
        previous_rendering_enabled=bool(before.get("rendering_enabled")),
        pre_snapshot=before,
        page_media_snapshots=_page_media(rerun.inspected_state),
        gate_results=[g.model_dump(mode="json") for g in rerun.gate_results],
        wordpress_write_scope=WORDPRESS_SCOPES[action],
        atlas_write_scope=ATLAS_SCOPE,
        transition_history=["pending"],
    )
    session.add(audit)
    session.commit()
    session.refresh(audit)
    response = _send_operation(session, action, rerun, before)
    audit.wordpress_write_count = 1
    if response.get("_error"):
        return _finish(session, audit, "failed", [_gate("wordpress_response", "WordPress accepted the fixed lifecycle request", False, str(response["_error"]))], before)
    after = _read_status(session)
    observed_after = _observe(session, WordPressDeploymentBackupEvidence.model_validate(entry.request.model_dump(mode="json", include=set(WordPressDeploymentBackupEvidence.model_fields))))
    post_gates = _post_gates(action, before, after, rerun.inspected_state, observed_after, rerun.payload_sha256)
    status = "verified" if all(g.passed for g in post_gates) else "verification_failed"
    return _finish(session, audit, status, post_gates, after)


def staging_preflight(session, page_id, request): return lifecycle_preflight(session, page_id, request, "stage_metadata_payload")
def staging_apply(session, page_id, request): return apply_lifecycle(session, page_id, request, "stage_metadata_payload")
def rendering_preflight(session, page_id, request): return lifecycle_preflight(session, page_id, request, "enable_metadata_rendering")
def rendering_apply(session, page_id, request): return apply_lifecycle(session, page_id, request, "enable_metadata_rendering")
def disable_preflight(session, page_id, request): return lifecycle_preflight(session, page_id, request, "disable_metadata_rendering")
def disable_apply(session, page_id, request): return apply_lifecycle(session, page_id, request, "disable_metadata_rendering")
def rollback_preflight(session, page_id, request): return lifecycle_preflight(session, page_id, request, "rollback_metadata_payload")
def rollback_apply(session, page_id, request): return apply_lifecycle(session, page_id, request, "rollback_metadata_payload")


def _operation_gates(
    action,
    snapshot,
    state,
    audits,
    expected_hash,
    observed,
    sync_audits=(),
    *,
    disable_eligibility=None,
    cache_aware_audits=(),
):
    revision, enabled, payload, live_hash = str(snapshot.get("revision", "0")), bool(snapshot.get("rendering_enabled")), snapshot.get("payload"), snapshot.get("payload_hash") or ""
    verified = {audit.action_type for audit in audits if audit.status == "verified"}
    metadata_absent = not observed.get("rendered", {}).get("atlas_metadata_marker_present", False) and _rendered_metadata_absent(observed.get("rendered", {}))
    common = [_gate("cache", "No cache purge is requested or observed", observed.get("cache_headers") == observed.get("rendered", {}).get("cache_headers", {}), "Cache observation changed.")]
    if action == "stage_metadata_payload":
        live_initial = payload is None and not live_hash and revision == "0" and not enabled and state is None and not sync_audits
        history = _staging_history_eligibility(audits, state, sync_audits)
        return common + [
            _gate(
                "initial_state_ready" if live_initial else "live_metadata_state_not_initial",
                "Payload is null, hash empty, revision 0, rendering disabled, and metadata rows absent",
                live_initial,
                "Live payload, payload hash, revision, rendering state, metadata state, or sync-audit rows are not initial.",
            ),
            _gate(
                "historical_failed_attempts_only" if history["eligible"] else history["reason_code"],
                "Lifecycle history contains only terminal zero-mutation failed staging attempts",
                history["eligible"],
                history["message"],
            ),
            _gate("metadata_absent", "No Atlas metadata currently renders", metadata_absent, "Metadata already renders."),
        ]
    if action == "enable_metadata_rendering":
        return common + [_gate("staged", "Verified staging exists with exact payload at revision 1", "stage_metadata_payload" in verified and payload == approved_payload().model_dump(mode="json") and live_hash == expected_hash and revision == "1" and not enabled, "A verified exact staged payload is required."), _gate("metadata_absent", "Fresh evidence proves metadata remains absent", metadata_absent, "Metadata renders before enablement.")]
    if action == "disable_metadata_rendering":
        eligibility = disable_eligibility or _disable_eligibility(
            snapshot, state, audits, expected_hash, observed, sync_audits, cache_aware_audits
        )
        return common + [
            _gate(
                eligibility["reason_code"],
                "Verified enablement or conclusively proven failed-verification recovery is eligible",
                eligibility["eligible"],
                eligibility["message"],
            )
        ]
    return common + [_gate("disabled", "Rendering is disabled before rollback", not enabled, "Disable rendering before payload rollback."), _gate("staged_payload", "Exact staged payload and revision 1 remain", payload == approved_payload().model_dump(mode="json") and live_hash == expected_hash and revision == "1", "Staged payload drifted."), _gate("disable_history", "A verified disable audit exists after enablement", "disable_metadata_rendering" in verified, "Verified rendering disablement required.")]


def _disable_eligibility(snapshot, state, audits, expected_hash, observed, sync_audits=(), cache_aware_audits=()):
    """Classify ordinary or recovery disablement without relaxing any mutation binding."""
    payload = approved_payload().model_dump(mode="json")
    revision = str(snapshot.get("revision", "0"))
    live_hash = snapshot.get("payload_hash") or ""
    if snapshot.get("rendering_enabled") is not True:
        return _disable_result(False, "rendering_not_enabled", "Rendering is not enabled.")
    if snapshot.get("payload") != payload or live_hash != expected_hash or revision != "1":
        return _disable_result(False, "staged_payload_drift", "The staged payload, hash, or revision drifted.")
    if sync_audits:
        return _disable_result(False, "conflicting_rendering_history", "Legacy metadata sync history exists.")
    if any(getattr(audit, "status", None) == "pending" for audit in audits):
        return _disable_result(False, "pending_rendering_operation", "A lifecycle audit remains pending.")

    staging = [
        audit
        for audit in audits
        if getattr(audit, "action_type", None) == "stage_metadata_payload"
        and getattr(audit, "status", None) == "verified"
    ]
    if not staging:
        return _disable_result(False, "conflicting_rendering_history", "A verified staging audit is required.")

    cache_candidate = cache_aware_audits[-1] if cache_aware_audits else None
    if cache_candidate and getattr(cache_candidate, "status", None) in {"verification_failed", "failed"}:
        final = getattr(cache_candidate, "final_state", None) or {}
        transitions = getattr(cache_candidate, "transition_history", None) or []
        eligible_transition = transitions in (
            ["pending_rendering", "verification_failed"],
            ["pending_rendering", "failed"],
            ["pending_rendering", "origin_verified", "verification_failed"],
            ["pending_rendering", "origin_verified", "failed"],
            ["pending_rendering", "origin_verified", "pending_cache_purge", "verification_failed"],
            ["pending_rendering", "origin_verified", "pending_cache_purge", "failed"],
        )
        fixed_scope = getattr(cache_candidate, "wordpress_write_scope", None) == [f"PUT {PLUGIN_PATHS['enable_metadata_rendering']}"]
        invariant_snapshots = getattr(cache_candidate, "page_media_snapshots", None) or {}
        page_media_unchanged = all(
            invariant_snapshots.get(key) == observed.get(key)
            for key in ("page_snapshot_hash", "page_body_hash", "media31_snapshot_hash", "media32_snapshot_hash")
        )
        if (
            eligible_transition
            and getattr(cache_candidate, "wordpress_write_count", None) == 1
            and fixed_scope
            and getattr(cache_candidate, "recovery_recommendation", None) == "disable_rendering"
            and final.get("rendering_enabled") is True
            and final.get("payload_hash") == expected_hash
            and str(final.get("revision")) == "1"
            and page_media_unchanged
            and _metadata_state_matches(state, "staged", payload, expected_hash, "1")
        ):
            return _disable_result(
                True,
                "cache_aware_recovery_disable_ready",
                "The failed cache-aware verification proves one accepted enablement and is eligible for guarded disablement.",
                RECOVERY_DISABLE_MODE,
                getattr(cache_candidate, "id", None),
            )
        return _disable_result(False, "cache_aware_enable_outcome_uncertain", "The cache-aware failure does not conclusively prove the fixed enablement and unchanged protected state.")

    relevant = [
        audit
        for audit in audits
        if getattr(audit, "action_type", None)
        in {"enable_metadata_rendering", "disable_metadata_rendering", "rollback_metadata_payload"}
    ]
    if any(
        getattr(audit, "action_type", None) == "disable_metadata_rendering"
        and getattr(audit, "status", None) == "verified"
        for audit in relevant
    ):
        return _disable_result(False, "recovery_already_completed", "A verified rendering disablement already exists.")
    if any(getattr(audit, "action_type", None) == "rollback_metadata_payload" for audit in relevant):
        return _disable_result(False, "conflicting_rendering_history", "Payload rollback history conflicts with disablement.")

    verified_enables = [
        audit
        for audit in relevant
        if getattr(audit, "action_type", None) == "enable_metadata_rendering"
        and getattr(audit, "status", None) == "verified"
    ]
    failed_enables = [
        audit
        for audit in relevant
        if getattr(audit, "action_type", None) == "enable_metadata_rendering"
        and getattr(audit, "status", None) == "verification_failed"
    ]
    latest = relevant[-1] if relevant else None
    if latest in verified_enables:
        if not _metadata_state_matches(state, "rendering_enabled", payload, expected_hash, "1"):
            return _disable_result(False, "staged_payload_drift", "Atlas metadata state differs from verified rendering state.")
        return _disable_result(
            True,
            "verified_enable_ready",
            "A verified rendering enablement is eligible for ordinary disablement.",
            ORDINARY_DISABLE_MODE,
            getattr(latest, "id", None),
        )
    if not failed_enables or latest not in failed_enables:
        return _disable_result(False, "conflicting_rendering_history", "No eligible latest rendering enablement exists.")
    candidate = latest
    if verified_enables:
        return _disable_result(False, "conflicting_rendering_history", "A later failed enablement conflicts with verified enablement history.")
    if getattr(candidate, "transition_history", None) != ["pending", "verification_failed"]:
        return _disable_result(False, "enable_outcome_uncertain", "The failed enablement transition history is malformed.")
    if getattr(candidate, "wordpress_write_count", None) != 1:
        return _disable_result(False, "enable_mutation_not_proven", "Exactly one accepted rendering-enable mutation is required.")
    if getattr(candidate, "wordpress_write_scope", None) != WORDPRESS_SCOPES["enable_metadata_rendering"]:
        return _disable_result(False, "enable_mutation_not_proven", "The accepted mutation was not the fixed rendering-enable endpoint.")
    if not _failed_enable_outcome_is_conclusive(candidate, payload, expected_hash, observed):
        return _disable_result(False, "enable_outcome_uncertain", "The failed enablement does not prove an exact accepted mutation.")
    recommendation = _failed_enable_recovery_recommendation(candidate)
    if recommendation != "disable_rendering":
        return _disable_result(False, "recovery_recommendation_mismatch", "The durable recovery recommendation is not disable_rendering.")
    rendered = observed.get("rendered", {})
    if rendered.get("atlas_metadata_marker_present") or not _rendered_metadata_absent(rendered):
        return _disable_result(False, "public_metadata_unexpectedly_present", "Public Atlas metadata is present.")
    if not _metadata_state_matches(state, "staged", payload, expected_hash, "1"):
        return _disable_result(False, "staged_payload_drift", "Atlas staged metadata state drifted.")
    return _disable_result(
        True,
        "recovery_disable_ready",
        "The conclusively accepted failed-verification enablement is eligible for recovery disablement.",
        RECOVERY_DISABLE_MODE,
        getattr(candidate, "id", None),
    )


def _disable_result(eligible, reason_code, message, completion_mode=STANDARD_MODE, source_audit_id=None):
    return {
        "eligible": bool(eligible),
        "reason_code": reason_code,
        "message": message,
        "completion_mode": completion_mode,
        "source_enable_audit_id": source_audit_id,
    }


def _metadata_state_matches(state, status, payload, payload_hash, revision):
    return bool(
        state
        and getattr(state, "status", None) == status
        and getattr(state, "payload", None) == payload
        and getattr(state, "payload_hash", None) == payload_hash
        and str(getattr(state, "wordpress_revision", "")) == revision
    )


def _failed_enable_outcome_is_conclusive(audit, payload, payload_hash, observed):
    pre = getattr(audit, "pre_snapshot", None)
    post = getattr(audit, "post_snapshot", None)
    if not isinstance(pre, dict) or not isinstance(post, dict):
        return False
    if not (
        getattr(audit, "completed_at", None) is not None
        and getattr(audit, "atlas_write_count", None) == 2
        and getattr(audit, "final_revision", None) == "1"
        and getattr(audit, "previous_rendering_enabled", None) is False
        and getattr(audit, "final_rendering_enabled", None) is True
        and pre.get("rendering_enabled") is False
        and post.get("rendering_enabled") is True
        and pre.get("payload") == post.get("payload") == payload
        and pre.get("payload_hash") == post.get("payload_hash") == payload_hash
        and str(pre.get("revision")) == str(post.get("revision")) == "1"
        and post.get("active") is True
        and post.get("version") == PLUGIN_VERSION
    ):
        return False
    failed = [gate.get("code") for gate in (getattr(audit, "gate_results", None) or []) if gate.get("passed") is False]
    if failed != ["rendered_exact"]:
        return False
    recorded = getattr(audit, "page_media_snapshots", None) or {}
    return all(
        recorded.get(key) == observed.get(key)
        for key in ("page_snapshot_hash", "page_body_hash", "media31_snapshot_hash", "media32_snapshot_hash", "cache_headers")
    )


def _failed_enable_recovery_recommendation(audit):
    explicit = getattr(audit, "recovery_recommendation", None)
    if explicit:
        return explicit
    # v0.59.64 audit 3 predates the dedicated column. Its exact, sole failed
    # rendered_exact gate plus a conclusively enabled snapshot deterministically
    # maps to the already reported disable_rendering recommendation.
    failed = [gate.get("code") for gate in (getattr(audit, "gate_results", None) or []) if gate.get("passed") is False]
    if failed == ["rendered_exact"] and getattr(audit, "final_rendering_enabled", None) is True:
        return "disable_rendering"
    return None


def _staging_history_eligibility(audits, state=None, sync_audits=()):
    """Classify whether durable history proves another initial staging attempt is safe."""
    summaries = []
    if state is not None or sync_audits:
        return _history_result(False, "live_metadata_state_not_initial", summaries, "Atlas metadata state or sync-audit rows already exist.")
    for audit in audits:
        summary = {
            "audit_id": getattr(audit, "id", None),
            "action_type": getattr(audit, "action_type", None),
            "status": getattr(audit, "status", None),
            "transition_history": getattr(audit, "transition_history", None),
            "attempted_wordpress_write_count": getattr(audit, "wordpress_write_count", None),
            "accepted_metadata_mutation_count": None,
            "recovery_recommendation": None,
        }
        summaries.append(summary)
        action = summary["action_type"]
        status = summary["status"]
        if status == "pending":
            return _history_result(False, "pending_lifecycle_audit", summaries, f"Lifecycle audit {summary['audit_id']} remains pending.")
        if action == "stage_metadata_payload" and status == "verified":
            return _history_result(False, "prior_verified_staging_exists", summaries, f"Lifecycle audit {summary['audit_id']} already verified staging.")
        if status == "verification_failed":
            return _history_result(False, "prior_mutation_outcome_uncertain", summaries, f"Lifecycle audit {summary['audit_id']} has an uncertain verification result.")
        if action != "stage_metadata_payload" or status != "failed":
            return _history_result(False, "conflicting_lifecycle_history", summaries, f"Lifecycle audit {summary['audit_id']} has a conflicting action or status.")
        if summary["transition_history"] != ["pending", "failed"]:
            return _history_result(False, "conflicting_lifecycle_history", summaries, f"Lifecycle audit {summary['audit_id']} has conflicting transition history.")
        attempted = summary["attempted_wordpress_write_count"]
        if type(attempted) is not int or attempted not in {0, 1}:
            return _history_result(False, "prior_mutation_outcome_uncertain", summaries, f"Lifecycle audit {summary['audit_id']} lacks trustworthy mutation-count evidence.")
        pre = getattr(audit, "pre_snapshot", None)
        post = getattr(audit, "post_snapshot", None)
        rejected_before_mutation = any(
            isinstance(gate, dict)
            and gate.get("code") == "wordpress_response"
            and gate.get("passed") is False
            and (
                gate.get("message") in set(SAFE_WORDPRESS_CONFLICT_CODES.values())
                or (
                    gate.get("message") == "HTTP 409"
                    and isinstance(pre, dict)
                    and isinstance(post, dict)
                    and pre.get("plugin_checksum") is None
                    and post.get("plugin_checksum") is None
                )
            )
            for gate in (getattr(audit, "gate_results", None) or [])
        )
        finalized = (
            getattr(audit, "completed_at", None) is not None
            and getattr(audit, "atlas_write_count", None) == 2
            and getattr(audit, "error_code", None) == "failed"
        )
        if not isinstance(pre, dict) or not isinstance(post, dict) or not finalized or (attempted == 1 and not rejected_before_mutation):
            return _history_result(False, "prior_mutation_outcome_uncertain", summaries, f"Lifecycle audit {summary['audit_id']} does not prove a completed rejected request.")
        unchanged = (
            pre == post
            and _metadata_snapshot_is_initial(pre)
            and _metadata_snapshot_is_initial(post)
            and getattr(audit, "previous_revision", None) == "0"
            and getattr(audit, "final_revision", None) == "0"
            and getattr(audit, "previous_rendering_enabled", None) is False
            and getattr(audit, "final_rendering_enabled", None) is False
        )
        if not unchanged:
            return _history_result(False, "prior_failed_attempt_mutated_state", summaries, f"Lifecycle audit {summary['audit_id']} does not prove unchanged initial metadata state.")
        summary["accepted_metadata_mutation_count"] = 0
        summary["recovery_recommendation"] = "no_action"
    return _history_result(True, "historical_failed_attempts_only", summaries, "Only terminal zero-mutation failed staging attempts exist.")


def _metadata_snapshot_is_initial(snapshot):
    return (
        snapshot.get("payload") is None
        and snapshot.get("payload_hash") == ""
        and snapshot.get("revision") == "0"
        and snapshot.get("rendering_enabled") is False
        and snapshot.get("enabled_metadata_state") is False
    )


def _history_result(eligible, reason_code, summaries, message):
    return {"eligible": eligible, "reason_code": reason_code, "audit_summaries": summaries, "message": message}


def _post_gates(action, before, after, original, observed, expected_hash):
    expected = {
        "stage_metadata_payload": (expected_hash, "1", False, approved_payload().model_dump(mode="json")),
        "enable_metadata_rendering": (expected_hash, "1", True, approved_payload().model_dump(mode="json")),
        "disable_metadata_rendering": (expected_hash, "1", False, approved_payload().model_dump(mode="json")),
        "rollback_metadata_payload": ("", "0", False, None),
    }[action]
    payload_hash, revision, enabled, payload = expected
    gates = [
        _gate("plugin_state", "Plugin lifecycle state matches exactly", after.get("payload_hash", "") == payload_hash and str(after.get("revision", "0")) == revision and bool(after.get("rendering_enabled")) is enabled and after.get("payload") == payload, "Plugin state differs after the one write."),
        _gate("plugin_active", "Plugin remains active at version 0.57.6", after.get("active") is True and after.get("version") == PLUGIN_VERSION, "Plugin activation or identity changed."),
        _gate("page", "Page and body remain unchanged", observed.get("page_snapshot_hash") == original.get("page_snapshot_hash") and observed.get("page_body_hash") == original.get("page_body_hash"), "Page changed."),
        _gate("media", "Media 31 and 32 remain unchanged", observed.get("media31_snapshot_hash") == original.get("media31_snapshot_hash") and observed.get("media32_snapshot_hash") == original.get("media32_snapshot_hash"), "Media changed."),
        _gate("site", "Site Title and Tagline remain unchanged", observed.get("site") == original.get("site"), "Site identity changed."),
        _gate("cache", "No cache purge occurred", observed.get("cache_headers") == original.get("cache_headers"), "Cache observation changed."),
        _gate("read_only_verification", "Post-write verification used GET/read requests only", observed.get("wordpress_request_methods") == ["GET"], "Verification attempted a write."),
    ]
    rendered = observed.get("rendered", {})
    if action in {"stage_metadata_payload", "disable_metadata_rendering", "rollback_metadata_payload"}:
        gates.append(_gate("rendered_absent", "Atlas metadata does not render", not rendered.get("atlas_metadata_marker_present", False) and _rendered_metadata_absent(rendered), "Metadata unexpectedly renders."))
    else:
        gates.append(_gate("rendered_exact", "Only the approved description and Organization plus Service schema render", _rendered_exact(rendered), "Rendered metadata differs or contains an extra node."))
    return gates


def _rendered_exact(rendered):
    inventory = rendered.get("metadata_inventory", {})
    json_ld = inventory.get("json_ld", [])
    types = []
    for item in json_ld:
        value = item.get("parsed") if isinstance(item, dict) else None
        graph = value.get("@graph", []) if isinstance(value, dict) else []
        types.extend(node.get("@type") for node in graph if isinstance(node, dict))
    descriptions = inventory.get("meta_descriptions", [])
    return rendered.get("verified") is True and descriptions == [approved_payload().meta_description] and types == ["Organization", "Service"] and not inventory.get("open_graph") and not inventory.get("twitter")


def _send_operation(session, action, preflight, before):
    try:
        snapshot_hash = _snapshot_hash(before)
    except ValueError as exc:
        return {"_error": str(exc), "reason_code": str(exc), "status_code": 409}
    body: dict[str, Any] = {"expected_revision": str(before.get("revision", "0")), "expected_snapshot_hash": snapshot_hash}
    if action == "stage_metadata_payload": body.update(payload=preflight.canonical_payload.model_dump(mode="json"), payload_hash=preflight.payload_sha256)
    elif action in {"enable_metadata_rendering", "disable_metadata_rendering"}: body.update(payload_hash=preflight.payload_sha256)
    else: body.update(payload_hash=preflight.payload_sha256, rollback_revision="0")
    settings = read_wordpress_settings(session); password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password): return {"_error": "credentials_unavailable"}
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            response = client.put(f"{settings.site_url.rstrip('/')}{PLUGIN_PATHS[action]}", json=body, auth=httpx.BasicAuth(settings.username, password), headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
        if response.status_code >= 400:
            try:
                value = response.json()
            except ValueError:
                value = {}
            wordpress_code = value.get("code") if isinstance(value, dict) else None
            reason_code = SAFE_WORDPRESS_CONFLICT_CODES.get(wordpress_code, f"wordpress_http_{response.status_code}")
            return {
                "_error": reason_code,
                "reason_code": reason_code,
                "wordpress_error_code": wordpress_code if wordpress_code in SAFE_WORDPRESS_CONFLICT_CODES else None,
                "status_code": response.status_code,
            }
        value = response.json(); return value if isinstance(value, dict) else {"_error": "non_object_response"}
    except (httpx.HTTPError, ValueError) as exc: return {"_error": exc.__class__.__name__}


def _read_status(session):
    settings = read_wordpress_settings(session); password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password): return {"_error": "credentials_unavailable"}
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get(f"{settings.site_url.rstrip('/')}/wp-json/project-atlas/v1/status", auth=httpx.BasicAuth(settings.username, password), headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
        if response.status_code >= 400: return {"_error": f"HTTP {response.status_code}"}
        value = response.json(); return value if isinstance(value, dict) else {"_error": "non_object_response"}
    except (httpx.HTTPError, ValueError) as exc: return {"_error": exc.__class__.__name__}


def _finish(session, audit, status, gates, snapshot):
    audit.status=status; audit.post_snapshot=_public_status(snapshot); audit.final_revision=str(snapshot.get("revision", audit.previous_revision)); audit.final_rendering_enabled=bool(snapshot.get("rendering_enabled")); audit.gate_results=[g.model_dump(mode="json") for g in gates]; audit.atlas_write_count=2; audit.transition_history=[*audit.transition_history,status]; audit.completed_at=datetime.now(UTC); audit.error_code=None if status=="verified" else status; audit.error_message=None if status=="verified" else "; ".join(g.message for g in gates if not g.passed)[:2000]
    if audit.action_type == "enable_metadata_rendering" and status == "verification_failed":
        audit.recovery_recommendation = _failed_enable_recovery_recommendation(audit)
    elif audit.action_type == "disable_metadata_rendering" and status == "verified":
        audit.recovery_recommendation = "no_action"
    state=session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id==41)).first()
    if status=="verified":
        state=state or WordPressMetadataState(generated_page_id=41,wordpress_post_id=8)
        state.status={"stage_metadata_payload":"staged","enable_metadata_rendering":"rendering_enabled","disable_metadata_rendering":"staged","rollback_metadata_payload":"not_applied"}[audit.action_type]
        state.payload=snapshot.get("payload"); state.payload_hash=snapshot.get("payload_hash") or None; state.wordpress_revision=str(snapshot.get("revision","0")); state.last_verified_at=datetime.now(UTC); state.last_wordpress_metadata_sync_at=datetime.now(UTC); session.add(state)
    session.add(audit); session.commit(); session.refresh(audit)
    return WordPressMetadataLifecycleResult(lifecycle_audit_id=audit.id or 0,action=audit.action_type,status=status,binding_hash=audit.binding_hash,state_history=audit.transition_history,completion_mode=audit.completion_mode,payload_hash=snapshot.get("payload_hash") or "",wordpress_revision=str(snapshot.get("revision",audit.previous_revision)),rendering_enabled=bool(snapshot.get("rendering_enabled")),inspected_state=_public_status(snapshot),gate_results=gates,wordpress_write_scope=audit.wordpress_write_scope,atlas_write_scope=audit.atlas_write_scope,further_action_required=status!="verified")


def _plugin_exact(observed):
    matches=_matching_reconciliation_plugins(observed.get("plugins",[]))
    return len(matches)==1 and matches[0].get("status") in {"active","network-active"} and matches[0].get("version")==PLUGIN_VERSION
def _binding(action,request,observed,snapshot,audits,payload_hash,expires,cache_aware_audits=()): return {"action":action,"request":request.model_dump(mode="json",exclude={"manual_browser_evidence"}),"evidence":{"id":request.manual_browser_evidence.evidence_id,"head":request.manual_browser_evidence.rendered_head_hash,"visible":request.manual_browser_evidence.visible_content_hash,"expires":request.manual_browser_evidence.expires_at},"state":{"plugin":_public_status(snapshot),"page":observed.get("page_snapshot_hash"),"body":observed.get("page_body_hash"),"media31":observed.get("media31_snapshot_hash"),"media32":observed.get("media32_snapshot_hash"),"cache":_hash(observed.get("cache_headers",{})),"audit_history":[[a.id,a.action_type,a.status] for a in audits],"cache_aware_history":[[a.id,a.status,a.wordpress_write_count,a.cache_write_count,a.recovery_recommendation] for a in cache_aware_audits]},"payload_hash":payload_hash,"expires_at":expires.isoformat() if expires else None}
def _page_media(value): return {key:value.get(key) for key in ("page_snapshot_hash","page_body_hash","media31_snapshot_hash","media32_snapshot_hash","cache_headers")}
def _public_status(value): return {key:value.get(key) for key in ("plugin","version","checksum","active","rendering_enabled","enabled_metadata_state","activation_generation","plugin_checksum","payload_hash","revision","payload","_error") if key in value}


def rendering_source_diagnostics() -> dict[str, Any]:
    """Inspect the locked plugin source without WordPress or Atlas writes."""
    source_path = resolve_program_root() / "wordpress/project-atlas-metadata-bridge-0.57.6/project-atlas-metadata-bridge.php"
    source = source_path.read_text(encoding="utf-8")
    hook_registered = "add_action('wp_head'" in source
    hook_priority_exact = "}, 20);" in source[source.index("add_action('wp_head'") :]
    page_target_exact = "if (!is_page(8)) { return ''; }" in source or "if (!is_page(8)) { return; }" in source
    payload_lookup_exact = "get_post_meta(ATLAS_METADATA_POST_ID, '_atlas_metadata_payload', true)" in source
    enabled_lookup_exact = "get_post_meta(ATLAS_METADATA_POST_ID, '_atlas_metadata_enabled', true) === '1'" in source
    safety_lookup_exact = "get_option(ATLAS_METADATA_SAFETY_OPTION, [])" in source
    normal_public_reachable = all(
        (
            hook_registered,
            hook_priority_exact,
            page_target_exact,
            payload_lookup_exact,
            enabled_lookup_exact,
            safety_lookup_exact,
            "<meta name=\"description\"" in source,
            "application/ld+json" in source,
        )
    )
    return {
        "read_only": True,
        "wordpress_write_count": 0,
        "atlas_write_count": 0,
        "hook": "wp_head",
        "hook_priority": 20,
        "document_title_parts_hook": False,
        "admin_only": False,
        "rest_only": False,
        "page_target": "is_page(8)",
        "payload_post_id": 8,
        "enabled_state_post_id": 8,
        "safety_option": ATLAS_METADATA_SAFETY_OPTION_NAME,
        "hook_registered": hook_registered,
        "hook_priority_exact": hook_priority_exact,
        "page_target_exact": page_target_exact,
        "payload_lookup_exact": payload_lookup_exact,
        "enabled_lookup_exact": enabled_lookup_exact,
        "safety_lookup_exact": safety_lookup_exact,
        "normal_public_request_reachable": normal_public_reachable,
        "root_cause_classification": "other_exactly_described_condition",
        "finding": (
            "The local 0.57.6 source registers the expected public wp_head hook and exact page/state lookups; "
            "source inspection alone cannot distinguish cache or optimizer delivery from a runtime hook failure."
        ),
    }


def _canonical_optimistic_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    """Return the exact normalized object hashed by Metadata Bridge 0.57.6."""
    if "plugin_checksum" not in value or not value.get("plugin_checksum"):
        raise ValueError("plugin_checksum_missing")
    checksum = value["plugin_checksum"]
    if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
        raise ValueError("plugin_checksum_mismatch")
    installed_checksum = value.get("checksum")
    if installed_checksum is not None and checksum != installed_checksum:
        raise ValueError("plugin_checksum_mismatch")
    if value.get("version") is not None and value.get("version") != PLUGIN_VERSION:
        raise ValueError("snapshot_field_mismatch")
    if value.get("active") is not None and value.get("active") is not True:
        raise ValueError("snapshot_field_mismatch")
    if any(key not in value for key in OPTIMISTIC_SNAPSHOT_FIELDS):
        raise ValueError("snapshot_field_mismatch")
    if type(value["rendering_enabled"]) is not bool or type(value["enabled_metadata_state"]) is not bool:
        raise ValueError("snapshot_field_mismatch")
    if not isinstance(value["activation_generation"], str) or not isinstance(value["payload_hash"], str):
        raise ValueError("snapshot_field_mismatch")
    if not isinstance(value["revision"], str) or re.fullmatch(r"0|[1-9][0-9]*", value["revision"]) is None:
        raise ValueError("snapshot_field_mismatch")
    if value["payload"] is not None and not isinstance(value["payload"], dict):
        raise ValueError("snapshot_field_mismatch")
    return {key: value[key] for key in OPTIMISTIC_SNAPSHOT_FIELDS}


def _snapshot_contract_error(value: dict[str, Any]) -> str | None:
    try:
        _canonical_optimistic_snapshot(value)
    except ValueError as exc:
        return str(exc)
    return None


def _snapshot_hash(value):
    canonical = _canonical_optimistic_snapshot(value)
    # wp_json_encode() retains PHP's default Unicode escaping because the
    # plugin passes JSON_UNESCAPED_SLASHES, not JSON_UNESCAPED_UNICODE.
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()
def _expected_revision(action): return "1" if action!="rollback_metadata_payload" else "0"
def _parse_timestamp(value):
    parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    if parsed.tzinfo is None: raise HTTPException(422,"Evidence timestamp must be timezone-aware.")
    return parsed.astimezone(UTC)
def _unavailable(reason): return {"_error":reason or "unavailable","plugins":[],"rendered":{"verified":False},"wordpress_request_methods":[],"read_only":True}
def _store_handle(action,request,binding_hash,expires_at):
    handle=secrets.token_urlsafe(32); entry=_HandleEntry(action,request,binding_hash,expires_at)
    with _handle_lock:
        _handles[handle]=entry; timer=Timer(max(0.0,(expires_at-datetime.now(UTC)).total_seconds()),_expire,args=(handle,));timer.daemon=True;_timers[handle]=timer;timer.start()
    return handle
def _consume_handle(handle,action):
    with _handle_lock:
        entry=_handles.pop(handle,None);timer=_timers.pop(handle,None)
        if timer:timer.cancel()
    if not entry or entry.action!=action: raise HTTPException(422,"Lifecycle handle is unknown, expired, consumed, or bound to another action.")
    if entry.expires_at<=datetime.now(UTC): raise HTTPException(422,"Lifecycle handle expired.")
    return entry
def _expire(handle):
    with _handle_lock:_handles.pop(handle,None);_timers.pop(handle,None)
def _clear_lifecycle_handles():
    with _handle_lock:
        for timer in _timers.values():timer.cancel()
        _handles.clear();_timers.clear()
