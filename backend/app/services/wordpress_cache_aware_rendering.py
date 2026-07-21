from __future__ import annotations

from copy import deepcopy
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
from typing import Any, Literal
import zipfile

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    WordPressCacheAwareRenderingAudit,
    WordPressMetadataLifecycleAudit,
    WordPressMetadataState,
)
from app.schemas.wordpress import (
    WordPressCacheAwareRenderingApplyRequest,
    WordPressCacheAwareRenderingPreflight,
    WordPressCacheAwareRenderingPreflightRequest,
    WordPressCacheAwareRenderingResult,
    WordPressCachePurgeApplyRequest,
    WordPressCachePurgePreflight,
    WordPressCachePurgePreflightRequest,
    WordPressDeploymentBackupEvidence,
)
from app.services.wordpress_deployment import (
    EXPECTED_CORRECTED_BODY_HASH,
    _backup_deadline,
    _backup_gates,
    _gate,
    _hash,
    _normalize_plugin_identifier,
    _observe,
    _rendered_metadata_absent,
    _target,
)
from app.services.wordpress_deployment_release import (
    DeploymentReleaseError,
    resolve_program_root,
    verify_runtime_release_identity,
)
from app.services.wordpress_metadata import _parse_html
from app.services.wordpress_metadata_lifecycle import approved_payload, payload_sha256
from app.services.wordpress_http import wordpress_basic_auth, wordpress_http_client
from app.services.wordpress_rendered_state import (
    EXPECTED_H1,
    sanitize_public_response_headers,
    validate_manual_browser_evidence,
)
from app.services.wordpress_sandbox import get_wordpress_application_password, read_wordpress_settings


PLUGIN_VERSION = "0.57.7"
PLUGIN_ZIP_NAME = "project-atlas-metadata-bridge-0.57.7.zip"
PLUGIN_ZIP_SHA256 = "ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62"
PLUGIN_SLUG = "project-atlas-metadata-bridge"
PLUGIN_ENTRY = f"{PLUGIN_SLUG}/project-atlas-metadata-bridge.php"
CANONICAL_URL = "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/"
RENDERING_PHRASE = "ENABLE PROJECT ATLAS METADATA RENDERING"
CACHE_PHRASE = "PURGE SITEGROUND CACHE FOR PROJECT ATLAS PAGE 8"
RENDERING_PATH = "/wp-json/project-atlas/v2/pages/8/metadata/rendering/enable"
PREVIEW_PATH = "/wp-json/project-atlas/v3/pages/8/metadata/rendering/preview"
CACHE_PATH = "/wp-json/project-atlas/v3/pages/8/cache/siteground/purge"
CACHE_PROVIDER = "siteground_speed_optimizer"
CACHE_SCOPE = "single_canonical_url"
HANDLE_TTL = timedelta(minutes=10)
MAX_OBSERVATION_INTERVAL = timedelta(minutes=2)
CLOCK_REVERSAL_TOLERANCE = timedelta(seconds=1)
VOLATILE_PUBLIC_OBSERVATION_FIELDS = frozenset({
    "observed_at", "observation_started_at", "observation_completed_at",
    "elapsed_ms", "generated_at", "request_id",
})
VOLATILE_CACHE_HEADERS = frozenset({"age", "expires", "last-modified"})
BINDING_REASON_CODES = frozenset({
    "stable_public_observation_mismatch",
    "public_observation_expired",
    "apply_observation_before_preflight",
    "observation_window_exceeded",
    "cache_provider_drift",
    "public_url_drift",
    "volatile_timestamp_change_allowed",
    "volatile_cache_age_change_allowed",
    "public_identity_drift",
})
ALLOWED_SCHEMA_TYPES = ["Organization", "Service"]
REASON_CODES = {
    "origin_metadata_verified", "origin_metadata_missing", "public_cache_hit_stale",
    "cache_bypass_unproven", "cache_provider_unavailable", "cache_purge_scope_unsupported",
    "cache_purge_ready", "cache_purge_failed", "public_metadata_verified",
    "public_metadata_still_stale", "public_metadata_mismatch",
    "unapproved_schema_node_present", "duplicate_metadata_present",
}
CACHE_OBSERVATION_REASON_CODES = {
    "siteground_cache_provider_verified",
    "cache_headers_missing",
    "cache_provider_unrecognized",
    "cache_header_value_invalid",
    "cache_status_hit",
    "cache_status_miss",
    "cache_status_bypass",
    "stale_public_cache_confirmed",
    "direct_cache_hit_verified",
    "direct_cache_miss_verified",
    "provider_verified_status_blocked",
    "browser_public_state_verified",
    "browser_public_state_verified_cache_provider_bound",
    "public_observation_mismatch",
    "challenge_response_rejected",
}


@dataclass(frozen=True)
class _RenderingHandle:
    request: WordPressCacheAwareRenderingPreflightRequest
    binding_hash: str
    expires_at: datetime
    stable_public_observation_fingerprint: str = ""
    preflight_observed_at: datetime | None = None
    evidence_captured_at: datetime | None = None
    evidence_expires_at: datetime | None = None
    backup_deadline: datetime | None = None
    preflight_public_observation: dict[str, Any] | None = None


@dataclass(frozen=True)
class _CacheHandle:
    audit_id: int
    binding_hash: str
    expires_at: datetime
    stable_public_observation_fingerprint: str = ""
    preflight_observed_at: datetime | None = None
    backup_deadline: datetime | None = None
    preflight_public_observation: dict[str, Any] | None = None


_lock = Lock()
_rendering_handles: dict[str, _RenderingHandle] = {}
_cache_handles: dict[str, _CacheHandle] = {}
_timers: dict[tuple[str, str], Timer] = {}


def _stable_provider_headers(headers: dict[str, Any]) -> dict[str, str]:
    """Normalize provider identity while excluding naturally volatile cache timing."""

    stable: dict[str, str] = {}
    for name, raw_value in _cache_headers(headers).items():
        if name in VOLATILE_CACHE_HEADERS:
            continue
        value = raw_value.strip()
        if name in {"x-cache", "x-proxy-cache", "x-sg-cache", "cf-cache-status"}:
            value = value.upper()
        elif name == "x-cache-enabled":
            value = value.lower()
        elif name == "x-proxy-cache-info":
            value = re.sub(r"(?i)(?:^|(?<=[\s,;]))DT:\d+(?=$|[\s,;])", "DT:*", value)
        elif name in {"server", "via"}:
            value = value.lower()
        stable[name] = value
    return stable


def _evidence_value(evidence: Any) -> dict[str, Any]:
    if hasattr(evidence, "model_dump"):
        return evidence.model_dump(mode="json", exclude_none=True)
    if isinstance(evidence, dict):
        return evidence
    if hasattr(evidence, "__dict__"):
        return vars(evidence)
    return {}


def _stable_public_observation(observation: dict[str, Any], evidence: Any | None = None) -> dict[str, Any]:
    """Return only immutable transport/provider and signed public-identity facts."""

    evidence_value = _evidence_value(evidence) if evidence is not None else {}
    headers = observation.get("cache_headers", {}) if isinstance(observation, dict) else {}
    provider = _siteground_cache_evidence(headers if isinstance(headers, dict) else {})
    status = observation.get("status_code") if isinstance(observation, dict) else None
    if status == 403 and provider.get("verified"):
        response_classification = "provider_verified_status_blocked"
    elif status == 200 and provider.get("verified"):
        response_classification = provider.get("status_reason_code") or "siteground_cache_provider_verified"
    else:
        response_classification = f"http_{status}" if isinstance(status, int) else "status_unavailable"
    parsed = observation.get("parsed", {}) if isinstance(observation, dict) else {}
    stable = {
        "request_url": CANONICAL_URL,
        "final_url": observation.get("final_url") if isinstance(observation, dict) else None,
        "redirect_count": observation.get("redirect_count") if isinstance(observation, dict) else None,
        "status_code": status,
        "response_classification": response_classification,
        "content_type_class": "html" if "text/html" in str(observation.get("content_type", "")).lower() else "other",
        "provider": {
            "verified": provider.get("verified") is True,
            "reason_code": provider.get("reason_code"),
            "status_reason_code": provider.get("status_reason_code"),
            "headers": _stable_provider_headers(headers if isinstance(headers, dict) else {}),
        },
        "challenge_error": {
            key: bool(observation.get(key))
            for key in (
                "challenge_page_detected", "error_page_detected", "admin_page_detected",
                "login_page_detected", "authenticated_context_detected",
            )
        },
        "outcome": observation.get("outcome") if isinstance(observation, dict) else None,
        "body_sha256": observation.get("body_sha256") if status == 200 else None,
        "public_rendered_hashes": {
            "head": observation.get("head_hash") if status == 200 else None,
            "visible": observation.get("visible_hash") if status == 200 else None,
            "metadata_inventory": _hash(parsed) if status == 200 and isinstance(parsed, dict) else None,
        },
    }
    if evidence_value:
        stable["signed_browser_identity"] = {
            "evidence_id": evidence_value.get("evidence_id"),
            "rendered_head_hash": evidence_value.get("rendered_head_hash"),
            "visible_content_hash": evidence_value.get("visible_content_hash"),
            "metadata_inventory_hash": evidence_value.get("metadata_inventory_hash"),
            "page_identity_hash": _hash(evidence_value.get("page_identity", {})),
        }
    return stable


def _stable_public_observation_fingerprint(observation: dict[str, Any], evidence: Any | None = None) -> str:
    return _hash(_stable_public_observation(observation, evidence))


def _public_observed_at(observation: dict[str, Any]) -> datetime:
    value = observation.get("observation_completed_at", observation.get("observed_at"))
    return _timestamp(value)


def _temporal_conflict(
    *,
    preflight_observed_at: datetime,
    apply_observed_at: datetime,
    evidence_expires_at: datetime | None,
    handle_expires_at: datetime,
    backup_deadline: datetime,
    now: datetime | None = None,
) -> str | None:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    preflight = _timestamp(preflight_observed_at)
    apply = _timestamp(apply_observed_at)
    handle_expiry = _timestamp(handle_expires_at)
    backup_expiry = _timestamp(backup_deadline)
    evidence_expiry = _timestamp(evidence_expires_at) if evidence_expires_at is not None else None
    if apply > current + CLOCK_REVERSAL_TOLERANCE:
        return "public_observation_expired"
    if apply + CLOCK_REVERSAL_TOLERANCE < preflight:
        return "apply_observation_before_preflight"
    if apply - preflight > MAX_OBSERVATION_INTERVAL:
        return "observation_window_exceeded"
    if evidence_expiry is not None and (apply > evidence_expiry or current > evidence_expiry):
        return "public_observation_expired"
    if apply > handle_expiry or current > handle_expiry:
        return "public_observation_expired"
    if apply > backup_expiry or current > backup_expiry:
        return "public_observation_expired"
    return None


def _stable_observation_conflict(before: dict[str, Any], after: dict[str, Any]) -> str | None:
    if before.get("final_url") != after.get("final_url") or after.get("final_url") != CANONICAL_URL:
        return "public_url_drift"
    if before.get("redirect_count") != after.get("redirect_count"):
        return "stable_public_observation_mismatch"
    if before.get("provider") != after.get("provider"):
        return "cache_provider_drift"
    if before.get("signed_browser_identity") != after.get("signed_browser_identity"):
        return "public_identity_drift"
    if (
        before.get("body_sha256") != after.get("body_sha256")
        or before.get("public_rendered_hashes") != after.get("public_rendered_hashes")
    ):
        return "public_identity_drift"
    if before != after:
        return "stable_public_observation_mismatch"
    return None


def _volatile_observation_gates(before: dict[str, Any], after: dict[str, Any]) -> list[Any]:
    before_headers = _cache_headers(before.get("cache_headers", {}))
    after_headers = _cache_headers(after.get("cache_headers", {}))
    timestamp_changed = before.get("observed_at") != after.get("observed_at") or before.get("observation_completed_at") != after.get("observation_completed_at")
    cache_age_changed = before_headers.get("age") != after_headers.get("age")
    return [
        _gate("volatile_timestamp_change_allowed", "Apply observation timestamp may advance inside the bound window", True, ""),
        _gate("volatile_cache_age_change_allowed", "Cache Age may change without weakening provider identity", True, ""),
    ] if timestamp_changed or cache_age_changed else []


def _raise_binding_conflict(code: str, message: str) -> None:
    raise HTTPException(409, detail={"code": code, "message": message})


def _preflight_conflict_code(gates: list[Any]) -> str:
    failed = {gate.code for gate in gates if not gate.passed}
    if failed & {"evidence", "public_observation_fresh", "lifetime", "backup_window"}:
        return "public_observation_expired"
    if failed & {
        "cache_provider", "cache_headers_missing", "cache_provider_unrecognized",
        "cache_header_value_invalid", "browser_public_state_verified_cache_provider_bound",
    }:
        return "cache_provider_drift"
    if "browser_public_state_verified" in failed:
        return "public_identity_drift"
    return "stable_public_observation_mismatch"


def _rendering_binding_hash(
    request: WordPressCacheAwareRenderingPreflightRequest,
    *,
    snapshot: dict[str, Any],
    artifact: dict[str, Any],
    page_media: dict[str, Any],
    audit_history: dict[str, Any],
    stable_public_fingerprint: str,
    preflight_observed_at: datetime,
    expires_at: datetime | None,
    backup_deadline: datetime,
) -> str:
    return _hash({
        "action": "cache_aware_rendering",
        "request": request.model_dump(mode="json", exclude={"manual_browser_evidence"}),
        "evidence": _evidence_summary(request),
        "plugin": _public_status(snapshot),
        "artifact": artifact,
        "page_media": page_media,
        "audit_history": audit_history,
        "stable_public_observation_fingerprint": stable_public_fingerprint,
        "temporal_contract": {
            "preflight_observed_at": _timestamp(preflight_observed_at).isoformat(),
            "maximum_interval_seconds": int(MAX_OBSERVATION_INTERVAL.total_seconds()),
            "clock_reversal_tolerance_seconds": int(CLOCK_REVERSAL_TOLERANCE.total_seconds()),
            "evidence_captured_at": _timestamp(request.manual_browser_evidence.captured_at).isoformat(),
            "evidence_expires_at": _timestamp(request.manual_browser_evidence.expires_at).isoformat(),
            "handle_expires_at": _timestamp(expires_at).isoformat() if expires_at else None,
            "backup_deadline": _timestamp(backup_deadline).isoformat(),
        },
    })


def _cache_binding_hash(
    *,
    audit: WordPressCacheAwareRenderingAudit | None,
    status: dict[str, Any],
    preview: dict[str, Any],
    stable_public_fingerprint: str,
    preflight_observed_at: datetime,
    expires_at: datetime | None,
    backup_deadline: datetime,
) -> str:
    return _hash({
        "audit": _audit_binding(audit),
        "plugin": _public_status(status),
        "origin": preview,
        "stable_public_observation_fingerprint": stable_public_fingerprint,
        "temporal_contract": {
            "preflight_observed_at": _timestamp(preflight_observed_at).isoformat(),
            "maximum_interval_seconds": int(MAX_OBSERVATION_INTERVAL.total_seconds()),
            "clock_reversal_tolerance_seconds": int(CLOCK_REVERSAL_TOLERANCE.total_seconds()),
            "handle_expires_at": _timestamp(expires_at).isoformat() if expires_at else None,
            "backup_deadline": _timestamp(backup_deadline).isoformat(),
        },
    })


def rendering_preflight(
    session: Session,
    page_id: int,
    request: WordPressCacheAwareRenderingPreflightRequest,
    *,
    issue_handle: bool = True,
    bound_expiry: datetime | None = None,
) -> WordPressCacheAwareRenderingPreflight:
    """Inspect the exact disabled staged state. This function performs zero writes."""
    from app.services.wordpress_bootstrap_establishment import assert_no_establishment_quarantine
    assert_no_establishment_quarantine(session)
    _target(page_id)
    proof = _backup_proof(request)
    evidence_ok, evidence_reason = validate_manual_browser_evidence(
        request.manual_browser_evidence, os.getenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", "")
    )
    evidence_ok = bool(evidence_ok and request.manual_browser_evidence.evidence_schema_version == 1)
    observed = _observe(session, proof) if evidence_ok else _unavailable(evidence_reason)
    status = _read_plugin_status(session) if "_error" not in observed else {"_error": "observation_unavailable"}
    snapshot = status.get("snapshot") if isinstance(status.get("snapshot"), dict) else status
    staging = session.get(WordPressMetadataLifecycleAudit, request.staging_audit_id)
    recovery = session.get(WordPressMetadataLifecycleAudit, request.recovery_disable_audit_id)
    state = session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == 41)).first()
    active = list(session.exec(select(WordPressCacheAwareRenderingAudit).where(
        WordPressCacheAwareRenderingAudit.status.in_(("pending_rendering", "origin_verified", "pending_cache_purge"))
    )))
    artifact = _artifact_identity()
    runtime = _runtime_identity()
    rendered = observed.get("rendered", {})
    public_observation = rendered.get("public_http_observation", {})
    cache_headers = _cache_headers(public_observation.get("cache_headers", {}))
    public_bound, public_reason = _public_observation_matches_evidence(
        public_observation, request.manual_browser_evidence
    )
    cache_evidence = _siteground_cache_evidence(cache_headers)
    stable_public_observation = _stable_public_observation(public_observation, request.manual_browser_evidence)
    stable_public_fingerprint = _hash(stable_public_observation)
    try:
        public_observed_at = _public_observed_at(public_observation)
    except (TypeError, ValueError, HTTPException):
        public_observed_at = None
    evidence_expires_at = _timestamp(request.manual_browser_evidence.expires_at)
    evidence_captured_at = _timestamp(request.manual_browser_evidence.captured_at)
    backup_deadline = _backup_deadline(proof.wordpress_backup_completed_at)
    current_time = datetime.now(UTC)
    public_time_valid = bool(
        public_observed_at
        and public_observed_at >= evidence_captured_at
        and public_observed_at <= evidence_expires_at
        and public_observed_at <= backup_deadline
        and public_observed_at <= current_time + CLOCK_REVERSAL_TOLERANCE
    )
    browser_public_state_verified = bool(
        evidence_ok
        and _rendered_metadata_absent(rendered)
        and not rendered.get("atlas_metadata_marker_present")
        and not rendered.get("media32_reference_present")
    )
    expected_hash = payload_sha256()
    gates = [
        *_backup_gates(proof),
        _gate("evidence", "Fresh signed credential-free schema-v1 evidence is valid", evidence_ok, evidence_reason or "Fresh schema-v1 evidence required."),
        _gate("runtime", "Runtime identity and independently expected identity are verified", _runtime_matches(runtime, request), "Runtime identity is unavailable or differs."),
        _gate("repository", "Repository and protected-path attestations remain exact", request.repository_head == request.repository_origin_main == request.expected_runtime_identity.atlas_commit and request.repository_tag == request.expected_runtime_identity.atlas_tag and request.repository_working_tree_clean and request.protected_paths_unchanged, "Repository identity or cleanliness changed."),
        _gate("artifact", "Metadata Bridge 0.57.7 source and ZIP are byte-equal and checksum-bound", artifact.get("valid") is True, artifact.get("error", "Artifact differs.")),
        _gate("post_backup", "No relevant WordPress change followed backup creation", request.no_relevant_wordpress_change_after_backup, "Fresh backup required."),
        _gate("plugin", "Metadata Bridge 0.57.7 is active exactly once", _plugin_exact(observed, status), "Required cache-aware bridge is absent, duplicated, inactive, or wrong version."),
        _gate("staged_payload", "Exact approved payload, hash, revision 1, and disabled rendering remain", snapshot.get("payload") == approved_payload().model_dump(mode="json") and snapshot.get("payload_hash") == expected_hash and str(snapshot.get("revision")) == "1" and snapshot.get("rendering_enabled") is False, "Staged metadata state drifted."),
        _gate("metadata_state", "Atlas metadata state remains staged at revision 1", bool(state and state.status == "staged" and state.payload_hash == expected_hash and str(state.wordpress_revision) == "1"), "Atlas metadata state differs."),
        _gate("staging_audit", "Staging audit ID 2 remains verified", bool(staging and staging.id == 2 and staging.action_type == "stage_metadata_payload" and staging.status == "verified"), "Verified staging audit ID 2 required."),
        _gate("failed_enable_preserved", "Rendering audit ID 3 remains verification_failed", _audit_three_preserved(session), "Failed rendering audit ID 3 changed."),
        _gate("recovery_disable", "Recovery-disable audit ID 4 remains verified", bool(recovery and recovery.id == 4 and recovery.action_type == "disable_metadata_rendering" and recovery.status == "verified" and recovery.completion_mode == "recovery_after_failed_enable_verification"), "Verified recovery-disable audit ID 4 required."),
        _gate("no_pending", "No cache-aware rendering operation is pending", not active, "A cache-aware rendering operation is already active."),
        _gate("page", "Page, body, title, status, H1, canonical, and featured media remain exact", observed.get("page_body_hash") == request.expected_body_hash == EXPECTED_CORRECTED_BODY_HASH and observed.get("page_snapshot_hash") == request.expected_page_snapshot_hash and observed.get("page", {}).get("id") == 8 and observed.get("page", {}).get("status") == "publish" and observed.get("page", {}).get("featured_media") == 31 and rendered.get("h1") == [EXPECTED_H1] and rendered.get("canonical") == [CANONICAL_URL], "Page identity changed."),
        _gate("media", "Media 31 and 32 remain exact and media 32 absent", observed.get("media31_snapshot_hash") == request.expected_media31_snapshot_hash and observed.get("media32_snapshot_hash") == request.expected_media32_snapshot_hash and not observed.get("page_references_media32") and not rendered.get("media32_reference_present"), "Media state changed."),
        _gate("site", "Site Title and Tagline remain exact", observed.get("site") == {"name": "My WordPress", "description": ""}, "Site identity changed."),
        _gate("browser_public_state_verified", "Signed browser evidence proves public metadata is absent before rendering", browser_public_state_verified, "Signed browser evidence does not prove the expected metadata-absent public state."),
        _gate(
            public_reason,
            "Direct HTTP status and sanitized provider headers are bound to the signed browser evidence",
            public_bound,
            "Direct public response status, URL, redirects, timing, challenge classification, or sanitized headers are not safely bound.",
        ),
        _gate(
            "siteground_cache_provider_verified" if cache_evidence["verified"] else cache_evidence["reason_code"],
            "Sanitized public response headers verify the SiteGround cache provider",
            cache_evidence["verified"],
            "SiteGround cache-provider headers are missing, malformed, or unrecognized.",
        ),
        _gate(
            "browser_public_state_verified_cache_provider_bound",
            "Signed browser evidence proves the metadata-absent pre-enable state and is bound to the verified SiteGround provider",
            public_bound and cache_evidence.get("verified") is True and browser_public_state_verified,
            "The signed metadata-absent browser state is not safely bound to verified SiteGround provider evidence.",
        ),
        _gate("public_observation_fresh", "Public provider observation is timezone-aware and inside evidence and backup windows", public_time_valid, "Public provider observation is missing, malformed, or expired."),
        _gate("read_only", "Inspection used WordPress GET/read operations only", observed.get("wordpress_request_methods") == ["GET"], "Inspection was not read-only."),
    ]
    ready = all(g.passed for g in gates)
    expires_at = bound_expiry
    if ready and expires_at is None:
        expires_at = min(
            datetime.now(UTC) + HANDLE_TTL,
            evidence_expires_at,
            backup_deadline,
        )
    if ready and (not expires_at or expires_at <= datetime.now(UTC)):
        ready = False
        gates.append(_gate("lifetime", "Authorization lifetime remains positive", False, "Evidence or backup expires before apply."))
    binding_observed_at = public_observed_at or datetime.min.replace(tzinfo=UTC)
    binding_hash = _rendering_binding_hash(
        request,
        snapshot=snapshot,
        artifact=artifact,
        page_media=_page_media(observed),
        audit_history={"staging": _audit_binding(staging), "recovery_disable": _audit_binding(recovery)},
        stable_public_fingerprint=stable_public_fingerprint,
        preflight_observed_at=binding_observed_at,
        expires_at=expires_at,
        backup_deadline=backup_deadline,
    )
    handle = None
    if ready and issue_handle and expires_at and public_observed_at:
        handle = _store_rendering(
            request,
            binding_hash,
            expires_at,
            stable_public_observation_fingerprint=stable_public_fingerprint,
            preflight_observed_at=public_observed_at,
            evidence_captured_at=evidence_captured_at,
            evidence_expires_at=evidence_expires_at,
            backup_deadline=backup_deadline,
            preflight_public_observation=public_observation,
        )
    return WordPressCacheAwareRenderingPreflight(
        status="cache_aware_rendering_preflight_ready" if ready else "cache_aware_rendering_preflight_blocked",
        preflight_ready=ready,
        rendering_handle=handle,
        handle_fingerprint=_fingerprint(handle),
        binding_hash=binding_hash if ready else None,
        expires_at=expires_at if ready else None,
        rendering_confirmation_phrase=RENDERING_PHRASE if ready else None,
        cache_confirmation_phrase=CACHE_PHRASE if ready else None,
        proposed_wordpress_write_scope=[f"PUT {RENDERING_PATH}", "rendering state only; payload and revision immutable"] if ready else [],
        proposed_cache_write_scope=[f"POST {CACHE_PATH}", f"one SiteGround purge for {CANONICAL_URL}"] if ready else [],
        proposed_atlas_write_scope=["create and transition one WordPressCacheAwareRenderingAudit", "finalize WordPressMetadataState only after origin and public verification"] if ready else [],
        inspected_state={"plugin_status": _public_status(snapshot), "page_media": _page_media(observed), "audit_history": {"staging": _audit_binding(staging), "recovery_disable": _audit_binding(recovery)}, "public_http_observation": public_observation, "stable_public_observation": stable_public_observation, "stable_public_observation_fingerprint": stable_public_fingerprint, "public_observation_temporal": {"observed_at": public_observed_at.isoformat() if public_observed_at else None, "maximum_interval_seconds": int(MAX_OBSERVATION_INTERVAL.total_seconds()), "evidence_captured_at": evidence_captured_at.isoformat(), "evidence_expires_at": evidence_expires_at.isoformat(), "handle_expires_at": expires_at.isoformat() if expires_at else None, "backup_deadline": backup_deadline.isoformat()}, "cache_headers": cache_headers, "cache_evidence": cache_evidence, "browser_public_state_verified": browser_public_state_verified, "artifact": artifact},
        gate_results=gates,
    )


def rendering_apply(session: Session, page_id: int, request: WordPressCacheAwareRenderingApplyRequest) -> WordPressCacheAwareRenderingResult:
    """Enable only rendering, then verify the same renderer through its read-only preview."""
    _target(page_id)
    if not hmac.compare_digest(request.confirmation_phrase, RENDERING_PHRASE):
        raise HTTPException(422, "The rendering confirmation phrase is incorrect.")
    entry = _consume_rendering(request.rendering_handle)
    rerun = rendering_preflight(session, page_id, entry.request, issue_handle=False, bound_expiry=entry.expires_at)
    if not rerun.preflight_ready:
        _raise_binding_conflict(_preflight_conflict_code(rerun.gate_results), "Rendering apply rerun failed a guarded preflight gate.")
    rerun_public = rerun.inspected_state.get("public_http_observation", {})
    rerun_stable = rerun.inspected_state.get("stable_public_observation", {})
    stored_public = entry.preflight_public_observation or {}
    stored_stable = _stable_public_observation(stored_public, entry.request.manual_browser_evidence)
    conflict = _stable_observation_conflict(stored_stable, rerun_stable)
    rerun_observed_at = _public_observed_at(rerun_public)
    if conflict:
        _raise_binding_conflict(conflict, "Stable public URL, provider, response, or signed identity changed after preflight.")
    if entry.stable_public_observation_fingerprint != rerun.inspected_state.get("stable_public_observation_fingerprint"):
        _raise_binding_conflict("stable_public_observation_mismatch", "Stable public observation fingerprint changed after preflight.")
    if not entry.preflight_observed_at or not entry.backup_deadline:
        _raise_binding_conflict("stable_public_observation_mismatch", "Rendering handle lacks the bound temporal contract.")
    temporal_conflict = _temporal_conflict(
        preflight_observed_at=entry.preflight_observed_at,
        apply_observed_at=rerun_observed_at,
        evidence_expires_at=entry.evidence_expires_at,
        handle_expires_at=entry.expires_at,
        backup_deadline=entry.backup_deadline,
    )
    if temporal_conflict:
        _raise_binding_conflict(temporal_conflict, "Apply observation is outside the bound evidence, handle, backup, or elapsed-time window.")
    candidate_binding = _rendering_binding_hash(
        entry.request,
        snapshot=rerun.inspected_state["plugin_status"],
        artifact=rerun.inspected_state["artifact"],
        page_media=rerun.inspected_state["page_media"],
        audit_history=rerun.inspected_state["audit_history"],
        stable_public_fingerprint=rerun.inspected_state["stable_public_observation_fingerprint"],
        preflight_observed_at=entry.preflight_observed_at,
        expires_at=entry.expires_at,
        backup_deadline=entry.backup_deadline,
    )
    if candidate_binding != entry.binding_hash:
        _raise_binding_conflict("stable_public_observation_mismatch", "A stable runtime, backup, plugin, payload, page, media, or audit binding changed.")
    rerun.gate_results.extend(_volatile_observation_gates(stored_public, rerun_public))
    before = rerun.inspected_state["plugin_status"]
    audit = WordPressCacheAwareRenderingAudit(
        generated_page_id=41, wordpress_post_id=8, staging_audit_id=entry.request.staging_audit_id,
        recovery_disable_audit_id=entry.request.recovery_disable_audit_id, status="pending_rendering",
        operator=entry.request.operator, rendering_handle_fingerprint=_fingerprint(request.rendering_handle) or "",
        rendering_binding_hash=entry.binding_hash, rendering_phrase_hash=hashlib.sha256(RENDERING_PHRASE.encode()).hexdigest(),
        release_identity=entry.request.expected_runtime_identity.model_dump(mode="json"),
        backup_evidence=entry.request.model_dump(mode="json", include=set(WordPressDeploymentBackupEvidence.model_fields)),
        payload_hash=payload_sha256(), revision="1", page_media_snapshots=rerun.inspected_state["page_media"],
        pre_purge_headers=rerun.inspected_state["cache_headers"], gate_results=[g.model_dump(mode="json") for g in rerun.gate_results],
        wordpress_write_scope=[f"PUT {RENDERING_PATH}"], cache_write_scope=[f"POST {CACHE_PATH}", CANONICAL_URL],
        atlas_write_scope=["create and transition this audit", "finalize metadata state only after public verification"],
        transition_history=["pending_rendering"], atlas_write_count=1,
    )
    session.add(audit); session.commit(); session.refresh(audit)
    response = _send_rendering_enable(session, before)
    if response.get("_error"):
        return _finish(session, audit, "failed", response.get("reason_code", "rendering_enable_failed"), "disable_rendering", [])
    audit.wordpress_write_count = 1
    after = _read_plugin_status(session)
    preview = _read_origin_preview(session)
    gates = _origin_gates(before, after, preview)
    if all(g.passed for g in gates):
        audit.origin_verification = preview
        return _finish(session, audit, "origin_verified", "origin_metadata_verified", "retry_cache_purge", gates, complete=False)
    audit.origin_verification = preview
    return _finish(session, audit, "verification_failed", _first_reason(gates, "origin_metadata_missing"), "disable_rendering", gates)


def cache_preflight(
    session: Session,
    page_id: int,
    request: WordPressCachePurgePreflightRequest,
    *,
    issue_handle: bool = True,
    bound_expiry: datetime | None = None,
) -> WordPressCachePurgePreflight:
    """Prove origin correctness and public staleness without writing."""
    from app.services.wordpress_bootstrap_establishment import assert_no_establishment_quarantine
    assert_no_establishment_quarantine(session)
    _target(page_id)
    audit = session.get(WordPressCacheAwareRenderingAudit, request.cache_aware_audit_id)
    status = _read_plugin_status(session) if audit else {"_error": "audit_unavailable"}
    preview = _read_origin_preview(session) if audit else {"_error": "audit_unavailable"}
    observed = _observe(session, _audit_proof(audit)) if audit else _unavailable("audit_unavailable")
    public = _read_public_page()
    stable_public_observation = _stable_public_observation(public)
    stable_public_fingerprint = _hash(stable_public_observation)
    try:
        public_observed_at = _public_observed_at(public)
    except (TypeError, ValueError, HTTPException):
        public_observed_at = None
    backup_deadline = _backup_deadline(_stored_backup_timestamp(audit)) if audit else datetime.min.replace(tzinfo=UTC)
    public_time_valid = bool(public_observed_at and public_observed_at <= backup_deadline and public_observed_at <= datetime.now(UTC) + CLOCK_REVERSAL_TOLERANCE)
    gates = [
        _gate("audit", "Selected cache-aware audit is origin_verified", bool(audit and audit.status == "origin_verified"), "Origin-verified audit required."),
        _gate("rendering", "Rendering remains enabled with exact payload hash and revision 1", status.get("rendering_enabled") is True and status.get("payload_hash") == payload_sha256() and str(status.get("revision")) == "1", "Rendering or staged payload drifted."),
        *_origin_gates(audit.origin_verification if audit else {}, status, preview),
        _gate("public_cache_hit_stale", "Public response remains a stale SiteGround cache hit", public.get("status_code") == 200 and public.get("final_url") == CANONICAL_URL and _siteground_cache_hit(public.get("cache_headers", {})) and _public_metadata_absent(public), "Public response is not the expected stale cache hit."),
        _gate("page_media", "Authenticated page, body, media, and site snapshots remain exact", bool(audit and _page_media(observed) == audit.page_media_snapshots), "Page, media, or site identity changed."),
        _gate("read_only", "Cache preflight used GET/read operations only", observed.get("wordpress_request_methods") == ["GET"], "Cache preflight was not read-only."),
        _gate("cache_provider", "Fixed SiteGround single-URL purge route is available", preview.get("cache_provider") == CACHE_PROVIDER and preview.get("cache_purge_available") is True and preview.get("cache_purge_scope") == CACHE_SCOPE, "Cache provider or route is unavailable."),
        _gate("public_observation_fresh", "Cache observation is timezone-aware and inside the backup window", public_time_valid, "Cache observation is missing, malformed, or outside the backup window."),
    ]
    ready = all(g.passed for g in gates)
    expires_at = bound_expiry
    if ready and expires_at is None and audit:
        expires_at = min(datetime.now(UTC) + HANDLE_TTL, backup_deadline)
    if ready and (not expires_at or expires_at <= datetime.now(UTC)):
        ready = False
        gates.append(_gate("backup_window", "SiteGround backup remains within four hours", False, "Backup deadline expired."))
    binding_observed_at = public_observed_at or datetime.min.replace(tzinfo=UTC)
    binding_hash = _cache_binding_hash(
        audit=audit,
        status=status,
        preview=preview,
        stable_public_fingerprint=stable_public_fingerprint,
        preflight_observed_at=binding_observed_at,
        expires_at=expires_at,
        backup_deadline=backup_deadline,
    )
    handle = _store_cache(
        audit.id,
        binding_hash,
        expires_at,
        stable_public_observation_fingerprint=stable_public_fingerprint,
        preflight_observed_at=public_observed_at,
        backup_deadline=backup_deadline,
        preflight_public_observation=public,
    ) if ready and issue_handle and audit and expires_at and public_observed_at else None
    return WordPressCachePurgePreflight(
        status="cache_purge_preflight_ready" if ready else "cache_purge_preflight_blocked",
        preflight_ready=ready, cache_handle=handle, handle_fingerprint=_fingerprint(handle),
        binding_hash=binding_hash if ready else None, expires_at=expires_at if ready else None,
        confirmation_phrase=CACHE_PHRASE if ready else None, cache_target=CANONICAL_URL, gate_results=gates,
        inspected_state={"plugin_status": _public_status(status), "origin_preview": preview, "public_http_observation": public, "stable_public_observation": stable_public_observation, "stable_public_observation_fingerprint": stable_public_fingerprint, "public_observation_temporal": {"observed_at": public_observed_at.isoformat() if public_observed_at else None, "maximum_interval_seconds": int(MAX_OBSERVATION_INTERVAL.total_seconds()), "handle_expires_at": expires_at.isoformat() if expires_at else None, "backup_deadline": backup_deadline.isoformat()}},
    )


def cache_apply(session: Session, page_id: int, request: WordPressCachePurgeApplyRequest) -> WordPressCacheAwareRenderingResult:
    """Perform one fixed URL purge and verify two credential-free public responses."""
    _target(page_id)
    if not hmac.compare_digest(request.confirmation_phrase, CACHE_PHRASE):
        raise HTTPException(422, "The SiteGround cache-purge confirmation phrase is incorrect.")
    entry = _consume_cache(request.cache_handle)
    rerun = cache_preflight(session, page_id, WordPressCachePurgePreflightRequest(cache_aware_audit_id=entry.audit_id), issue_handle=False, bound_expiry=entry.expires_at)
    if not rerun.preflight_ready:
        _raise_binding_conflict(_preflight_conflict_code(rerun.gate_results), "Cache apply rerun failed a guarded preflight gate.")
    audit = session.get(WordPressCacheAwareRenderingAudit, entry.audit_id)
    if not audit:
        raise HTTPException(404, "Cache-aware rendering audit not found.")
    rerun_public = rerun.inspected_state.get("public_http_observation", {})
    rerun_stable = rerun.inspected_state.get("stable_public_observation", {})
    stored_public = entry.preflight_public_observation or {}
    stored_stable = _stable_public_observation(stored_public)
    conflict = _stable_observation_conflict(stored_stable, rerun_stable)
    rerun_observed_at = _public_observed_at(rerun_public)
    if conflict:
        _raise_binding_conflict(conflict, "Stable public URL, provider, response, or identity changed after cache preflight.")
    if entry.stable_public_observation_fingerprint != rerun.inspected_state.get("stable_public_observation_fingerprint"):
        _raise_binding_conflict("stable_public_observation_mismatch", "Stable cache observation fingerprint changed after preflight.")
    if not entry.preflight_observed_at or not entry.backup_deadline:
        _raise_binding_conflict("stable_public_observation_mismatch", "Cache handle lacks the bound temporal contract.")
    temporal_conflict = _temporal_conflict(
        preflight_observed_at=entry.preflight_observed_at,
        apply_observed_at=rerun_observed_at,
        evidence_expires_at=None,
        handle_expires_at=entry.expires_at,
        backup_deadline=entry.backup_deadline,
    )
    if temporal_conflict:
        _raise_binding_conflict(temporal_conflict, "Cache apply observation is outside the handle, backup, or elapsed-time window.")
    candidate_binding = _cache_binding_hash(
        audit=audit,
        status=rerun.inspected_state["plugin_status"],
        preview=rerun.inspected_state["origin_preview"],
        stable_public_fingerprint=rerun.inspected_state["stable_public_observation_fingerprint"],
        preflight_observed_at=entry.preflight_observed_at,
        expires_at=entry.expires_at,
        backup_deadline=entry.backup_deadline,
    )
    if candidate_binding != entry.binding_hash:
        _raise_binding_conflict("stable_public_observation_mismatch", "A stable audit, plugin, origin, provider, or backup binding changed.")
    rerun.gate_results.extend(_volatile_observation_gates(stored_public, rerun_public))
    audit.status = "pending_cache_purge"; audit.cache_handle_fingerprint = _fingerprint(request.cache_handle)
    audit.cache_binding_hash = entry.binding_hash; audit.cache_phrase_hash = hashlib.sha256(CACHE_PHRASE.encode()).hexdigest()
    audit.cache_provider = CACHE_PROVIDER; audit.cache_scope = CACHE_SCOPE; audit.cache_target = CANONICAL_URL
    audit.transition_history = [*audit.transition_history, "pending_cache_purge"]; audit.atlas_write_count += 1
    session.add(audit); session.commit()
    purge = _send_cache_purge(session)
    if purge.get("_error"):
        return _finish(session, audit, "failed", purge.get("reason_code", "cache_purge_failed"), "retry_cache_purge", [])
    audit.cache_write_count = 1
    first = _read_public_page(); second = _read_public_page()
    status = _read_plugin_status(session)
    observed_after = _observe(session, _audit_proof(audit))
    gates = _public_gates(first, second, status, audit, observed_after)
    audit.post_purge_headers = first.get("cache_headers", {})
    audit.public_verification = {"first": _safe_public(first), "second": _safe_public(second)}
    audit.public_evidence = [{"source": "isolated_credential_free_http", "head_hash": item.get("head_hash"), "visible_hash": item.get("visible_hash"), "cache_headers": item.get("cache_headers", {})} for item in (first, second)]
    if all(g.passed for g in gates):
        state = session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == 41)).first()
        if state:
            state.status = "rendering_enabled"; state.last_verified_at = datetime.now(UTC); session.add(state)
        return _finish(session, audit, "verified", "public_metadata_verified", "no_action", gates)
    return _finish(session, audit, "verification_failed", _first_reason(gates, "public_metadata_mismatch"), "disable_rendering", gates)


def _origin_gates(before: dict[str, Any], after: dict[str, Any], preview: dict[str, Any]):
    return [
        _gate("origin_metadata_verified", "Plugin-owned public-head renderer returns exact approved metadata", _origin_exact(preview), "Authoritative origin metadata is missing or mismatched."),
        _gate("origin_read_only", "Origin preview is read-only", preview.get("read_only") is True, "Origin preview is not proven read-only."),
        _gate("state", "Only rendering changed; payload hash and revision remain exact", after.get("rendering_enabled") is True and after.get("payload_hash") == payload_sha256() and str(after.get("revision")) == "1" and after.get("payload") == approved_payload().model_dump(mode="json"), "Metadata state drifted."),
        _gate("plugin", "Metadata Bridge 0.57.7 remains active", after.get("active") is True and after.get("version") == PLUGIN_VERSION, "Plugin state changed."),
    ]


def _public_gates(first, second, status, audit, observed=None):
    exact_first, reason_first = _public_exact(first)
    exact_second, reason_second = _public_exact(second)
    refreshed = _cache_refreshed(audit.pre_purge_headers, first.get("cache_headers", {}))
    return [
        _gate("cache_refresh", "Old cached object is no longer served", refreshed, "Cache MISS, reset age, or changed cache identity was not proven."),
        _gate(reason_first, "First credential-free public response contains exact approved metadata", exact_first, "First public response metadata differs."),
        _gate(reason_second, "Second credential-free response serves the same correct metadata", exact_second and first.get("head_hash") == second.get("head_hash"), "Second cached response differs."),
        _gate("state_unchanged", "Payload, revision, and rendering remain exact", status.get("payload_hash") == payload_sha256() and str(status.get("revision")) == "1" and status.get("rendering_enabled") is True, "Metadata state drifted."),
        _gate("page_media_unchanged", "Page, body, media, and site snapshots remain exact", bool(observed and _page_media(observed) == audit.page_media_snapshots), "Page, media, or site identity changed."),
        _gate("read_only_verification", "Post-purge verification used GET/read operations only", bool(observed and observed.get("wordpress_request_methods") == ["GET"]), "Post-purge verification was not read-only."),
        _gate("write_count", "Exactly one fixed cache operation occurred", audit.cache_write_count == 1, "Cache write count differs."),
    ]


def _origin_exact(value):
    return value.get("source") == "plugin_owned_public_head_renderer" and value.get("read_only") is True and value.get("canonical_url") == CANONICAL_URL and value.get("meta_descriptions") == [approved_payload().meta_description] and value.get("json_ld_types") == ALLOWED_SCHEMA_TYPES and len(value.get("json_ld", [])) == 1 and value.get("snapshot", {}).get("payload_hash") == payload_sha256() and value.get("snapshot", {}).get("revision") == "1" and value.get("snapshot", {}).get("rendering_enabled") is True


def _public_exact(value):
    if value.get("status_code") != 200 or value.get("final_url") != CANONICAL_URL:
        return False, "public_metadata_mismatch"
    parsed = value.get("parsed", {})
    descriptions = [item.get("content") for item in parsed.get("meta", []) if item.get("name") == "description"]
    if len(descriptions) != 1:
        return False, "duplicate_metadata_present" if len(descriptions) > 1 else "public_metadata_still_stale"
    scripts = parsed.get("atlas_json_ld", [])
    if len(scripts) != 1:
        return False, "duplicate_metadata_present" if len(scripts) > 1 else "public_metadata_still_stale"
    try:
        graph = json.loads(scripts[0]).get("@graph", [])
        types = [node.get("@type") for node in graph]
    except (ValueError, AttributeError):
        return False, "public_metadata_mismatch"
    if types != ALLOWED_SCHEMA_TYPES:
        return False, "unapproved_schema_node_present"
    exact = descriptions == [approved_payload().meta_description] and parsed.get("canonicals") == [CANONICAL_URL] and parsed.get("h1") == [EXPECTED_H1] and not value.get("media32_reference_present")
    return exact, "public_metadata_verified" if exact else "public_metadata_mismatch"


def _read_public_page():
    started_at = datetime.now(UTC)
    try:
        with wordpress_http_client(CANONICAL_URL, timeout=20, follow_redirects=False, client_factory=httpx.Client) as client:
            response = client.get(CANONICAL_URL)
        completed_at = datetime.now(UTC)
        parsed = _parse_html(response.text)
        return {
            "status_code": response.status_code,
            "final_url": str(response.url),
            "redirect_count": len(response.history),
            "content_type": response.headers.get("content-type", ""),
            "cache_headers": _cache_headers(response.headers.multi_items()),
            "body_sha256": hashlib.sha256(response.content).hexdigest(),
            "parsed": parsed,
            "head_hash": parsed.get("head_hash"),
            "visible_hash": parsed.get("visible_hash"),
            "media32_reference_present": "orlando-drywood-termite-tenting-hero-1.png" in response.text,
            "observation_started_at": started_at.isoformat(),
            "observation_completed_at": completed_at.isoformat(),
            "observed_at": completed_at.isoformat(),
            "elapsed_ms": max(0, int((completed_at - started_at).total_seconds() * 1000)),
        }
    except httpx.HTTPError as exc:
        completed_at = datetime.now(UTC)
        return {"_error": exc.__class__.__name__, "status_code": None, "final_url": None, "cache_headers": {}, "parsed": {}, "observation_started_at": started_at.isoformat(), "observation_completed_at": completed_at.isoformat(), "observed_at": completed_at.isoformat(), "elapsed_ms": max(0, int((completed_at - started_at).total_seconds() * 1000))}


def _read_plugin_status(session): return _authenticated_json(session, "GET", "/wp-json/project-atlas/v1/status")
def _read_origin_preview(session): return _authenticated_json(session, "GET", PREVIEW_PATH)


def _send_rendering_enable(session, before):
    body = {"expected_revision": "1", "expected_snapshot_hash": _snapshot_hash(before), "payload_hash": payload_sha256()}
    return _authenticated_json(session, "PUT", RENDERING_PATH, body)


def _send_cache_purge(session):
    value = _authenticated_json(session, "POST", CACHE_PATH, {})
    if value.get("cache_write_count") != 1 or value.get("scope") != CACHE_SCOPE or value.get("canonical_url") != CANONICAL_URL:
        return {"_error": "cache_purge_scope_unsupported", "reason_code": "cache_purge_scope_unsupported"}
    return value


def _authenticated_json(session, method, path, body=None):
    settings = read_wordpress_settings(session); password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password): return {"_error": "credentials_unavailable"}
    try:
        with wordpress_http_client(settings.site_url, timeout=20, follow_redirects=False, client_factory=httpx.Client) as client:
            response = client.request(method, f"{settings.site_url.rstrip('/')}{path}", json=body if method != "GET" else None, auth=wordpress_basic_auth(settings.username, password), headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
        if response.status_code >= 400:
            code = "cache_provider_unavailable" if response.status_code in {404, 503} and path == CACHE_PATH else f"wordpress_http_{response.status_code}"
            return {"_error": code, "reason_code": code, "status_code": response.status_code}
        value = response.json(); return value if isinstance(value, dict) else {"_error": "non_object_response"}
    except (httpx.HTTPError, ValueError) as exc:
        return {"_error": exc.__class__.__name__, "reason_code": exc.__class__.__name__}


def _finish(session, audit, status, reason, recommendation, gates, *, complete=True):
    audit.status = status; audit.gate_results = [g.model_dump(mode="json") for g in gates]
    audit.transition_history = [*audit.transition_history, status] if audit.transition_history[-1:] != [status] else audit.transition_history
    audit.recovery_recommendation = recommendation; audit.error_code = None if status in {"origin_verified", "verified"} else reason
    audit.error_message = None if audit.error_code is None else "; ".join(g.message for g in gates if not g.passed)[:2000]
    audit.atlas_write_count += 1; audit.completed_at = datetime.now(UTC) if complete else None
    audit.final_state = _public_status(_read_plugin_status(session)); session.add(audit); session.commit(); session.refresh(audit)
    return WordPressCacheAwareRenderingResult(cache_aware_audit_id=audit.id or 0, status=status, transition_history=audit.transition_history, payload_hash=audit.payload_hash, wordpress_revision=audit.revision, rendering_enabled=bool((audit.final_state or {}).get("rendering_enabled")), cache_provider=audit.cache_provider, cache_scope=audit.cache_scope, cache_target=audit.cache_target, reason_code=reason, gate_results=gates, wordpress_write_count=audit.wordpress_write_count, cache_write_count=audit.cache_write_count, atlas_write_count=audit.atlas_write_count, wordpress_write_scope=audit.wordpress_write_scope, cache_write_scope=audit.cache_write_scope, atlas_write_scope=audit.atlas_write_scope, recovery_recommendation=recommendation, further_action_required=status != "verified")


def _artifact_identity():
    try:
        root = resolve_program_root(); source = root / "wordpress" / f"{PLUGIN_SLUG}-0.57.7"; archive_path = root / "wordpress" / "dist" / PLUGIN_ZIP_NAME
        actual_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        with zipfile.ZipFile(archive_path) as archive:
            actual = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
        expected = {f"{PLUGIN_SLUG}/{path.relative_to(source).as_posix()}": path.read_bytes() for path in source.rglob("*") if path.is_file()}
        portable = set(actual) == set(expected) and actual == expected and all(".." not in PurePosixPath(name).parts and "\\" not in name for name in actual)
        valid = actual_sha == PLUGIN_ZIP_SHA256 and portable
        return {"valid": valid, "version": PLUGIN_VERSION, "zip_sha256": actual_sha, "zip_name": PLUGIN_ZIP_NAME, "byte_equal": actual == expected, "portable": portable, "error": None if valid else "Plugin ZIP checksum or source bytes differ."}
    except (OSError, zipfile.BadZipFile, DeploymentReleaseError) as exc:
        return {"valid": False, "error": exc.__class__.__name__}


def _runtime_identity():
    try:
        value = verify_runtime_release_identity(resolve_program_root())
        return {"version": value.atlas_version, "commit": value.atlas_commit, "tag": value.atlas_tag, "manifest_sha256": value.manifest_sha256, "verified": value.runtime_identity_verified and value.manifest_integrity_verified and value.expected_release_matched}
    except DeploymentReleaseError:
        return {"verified": False}


def _runtime_matches(value, request):
    expected = request.expected_runtime_identity
    return value.get("verified") is True and value.get("version") == expected.atlas_version and value.get("commit") == expected.atlas_commit and value.get("tag") == expected.atlas_tag and value.get("manifest_sha256") == expected.manifest_sha256


def _plugin_exact(observed, status):
    """Match through the shared fail-closed normalizer without rewriting inventories."""

    plugins = observed.get("plugins", [])
    if not isinstance(plugins, list) or any(not isinstance(item, dict) for item in plugins):
        return False
    normalized = [_normalize_plugin_identifier(item.get("plugin")) for item in plugins]
    if any(not identity.valid for identity in normalized):
        return False
    matches = [
        item
        for item, identity in zip(plugins, normalized, strict=True)
        if identity.authorized_entry_path == PLUGIN_ENTRY
    ]
    return (
        len(matches) == 1
        and _normalize_plugin_identifier(matches[0].get("plugin")).plugin_slug == PLUGIN_SLUG
        and matches[0].get("status") in {"active", "network-active"}
        and matches[0].get("version") == PLUGIN_VERSION
        and status.get("plugin") == PLUGIN_SLUG
        and status.get("version") == PLUGIN_VERSION
        and status.get("active") is True
    )


def _audit_three_preserved(session):
    audit = session.get(WordPressMetadataLifecycleAudit, 3)
    return bool(audit and audit.action_type == "enable_metadata_rendering" and audit.status == "verification_failed")


def _siteground_cache_evidence(headers):
    sanitized = _cache_headers(headers)
    if not sanitized:
        return {"verified": False, "reason_code": "cache_headers_missing", "status_reason_code": None, "headers": {}}

    enabled = sanitized.get("x-cache-enabled", "").lower()
    if enabled and enabled not in {"true", "false"}:
        return {"verified": False, "reason_code": "cache_header_value_invalid", "status_reason_code": None, "headers": sanitized}

    raw_status = sanitized.get("x-proxy-cache", sanitized.get("x-sg-cache", sanitized.get("x-cache", "")))
    status = raw_status.strip().upper()
    status_codes = {
        "HIT": "cache_status_hit",
        "MISS": "cache_status_miss",
        "BYPASS": "cache_status_bypass",
    }
    if status and status not in status_codes:
        return {"verified": False, "reason_code": "cache_header_value_invalid", "status_reason_code": None, "headers": sanitized}

    proxy_info = sanitized.get("x-proxy-cache-info", "")
    proxy_info_valid = bool(re.search(r"(?:^|[\s,;])DT:\d+(?:$|[\s,;])", proxy_info, re.I)) if proxy_info else False
    if proxy_info and not proxy_info_valid:
        return {"verified": False, "reason_code": "cache_header_value_invalid", "status_reason_code": None, "headers": sanitized}

    verified = enabled == "true" or status in status_codes or proxy_info_valid
    return {
        "verified": verified,
        "reason_code": "siteground_cache_provider_verified" if verified else "cache_provider_unrecognized",
        "status_reason_code": status_codes.get(status),
        "supporting_nginx": "nginx" in sanitized.get("server", "").lower(),
        "headers": sanitized,
    }


def _siteground_cache_present(headers): return _siteground_cache_evidence(headers)["verified"]
def _siteground_cache_hit(headers): return _siteground_cache_evidence(headers).get("status_reason_code") == "cache_status_hit"
def _cache_headers(headers): return sanitize_public_response_headers(headers)
def _audit_binding(audit):
    if audit is None:
        return None
    return {
        key: getattr(audit, key, None)
        for key in (
            "id", "action_type", "status", "transition_history",
            "wordpress_write_count", "cache_write_count", "atlas_write_count",
        )
    }


def _public_observation_matches_evidence(observation, evidence):
    """Bind transport/provider facts without treating direct HTTP as rendered evidence.

    The signed browser capture is authoritative for DOM and metadata.  This
    direct observation contributes only transport, timing, body-hash, and
    sanitized cache-provider facts.  A provider-identified HTTP 403 is allowed
    only at the pre-enable gate; final public verification remains in
    ``_public_exact`` and still requires HTTP 200 with exact rendered metadata.
    """

    if not isinstance(observation, dict) or not observation:
        return False, "public_observation_mismatch"
    if hasattr(evidence, "model_dump"):
        evidence = evidence.model_dump(mode="json", exclude_none=True)
    elif not isinstance(evidence, dict) and hasattr(evidence, "__dict__"):
        evidence = vars(evidence)
    if not _browser_evidence_safe_for_public_binding(evidence):
        return False, "public_observation_mismatch"
    if observation.get("source") != "public":
        return False, "public_observation_mismatch"
    if observation.get("final_url") != evidence.get("final_url") or observation.get("final_url") != CANONICAL_URL:
        return False, "public_observation_mismatch"
    if observation.get("redirect_count") != 0:
        return False, "public_observation_mismatch"
    try:
        observed_at = _timestamp(observation.get("observed_at"))
        captured_at = _timestamp(evidence.get("captured_at"))
        expires_at = _timestamp(evidence.get("expires_at"))
    except (TypeError, ValueError, HTTPException):
        return False, "public_observation_mismatch"
    if not captured_at <= observed_at <= expires_at:
        return False, "public_observation_mismatch"
    headers = observation.get("cache_headers", {})
    if not isinstance(headers, dict) or headers != _cache_headers(headers):
        return False, "public_observation_mismatch"
    status = observation.get("status_code")
    if status == 202 or observation.get("challenge_page_detected") or observation.get("outcome") == "bot_protection_blocked":
        return False, "challenge_response_rejected"
    if observation.get("outcome") in {"error_page_detected", "unexpected_redirect", "network_failed"}:
        return False, "public_observation_mismatch"
    if any(observation.get(field) for field in ("admin_page_detected", "login_page_detected", "authenticated_context_detected", "error_page_detected")):
        return False, "public_observation_mismatch"
    if not isinstance(observation.get("body_sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", observation["body_sha256"]) is None:
        return False, "public_observation_mismatch"

    provider = _siteground_cache_evidence(headers)
    if status == 403:
        if not provider.get("verified"):
            return False, provider.get("reason_code", "public_observation_mismatch")
        return True, "provider_verified_status_blocked"
    if status != 200 or "text/html" not in str(observation.get("content_type", "")).lower():
        return False, "public_observation_mismatch"
    if not provider.get("verified"):
        return False, provider.get("reason_code", "public_observation_mismatch")
    status_reason = provider.get("status_reason_code")
    if status_reason == "cache_status_hit":
        return True, "direct_cache_hit_verified"
    if status_reason == "cache_status_miss":
        return True, "direct_cache_miss_verified"
    return True, "siteground_cache_provider_verified"


def _browser_evidence_safe_for_public_binding(evidence):
    if not isinstance(evidence, dict) and hasattr(evidence, "__dict__"):
        evidence = vars(evidence)
    if not isinstance(evidence, dict) or evidence.get("final_url") != CANONICAL_URL:
        return False
    identity = evidence.get("page_identity", {})
    if identity.get("canonical_url") != CANONICAL_URL:
        return False
    navigation = evidence.get("navigation_outcome", {})
    if (
        navigation.get("status_code") != 200
        or navigation.get("redirect_count") != 0
        or navigation.get("outcome") != "success"
        or "text/html" not in str(navigation.get("content_type", "")).lower()
        or any(
            navigation.get(field)
            for field in (
                "admin_page_detected",
                "login_page_detected",
                "authenticated_context_detected",
                "challenge_page_detected",
                "error_page_detected",
            )
        )
    ):
        return False
    privacy = evidence.get("privacy_attestations", {})
    return privacy == {
        "credentials_used": False,
        "cookies_stored": False,
        "authorization_headers_stored": False,
        "authenticated_html_stored": False,
        "admin_session_used": False,
        "secrets_detected": False,
    }
def _cache_refreshed(before, after):
    state = str(after.get("x-proxy-cache", after.get("x-cache", ""))).upper()
    if state in {"MISS", "BYPASS", "EXPIRED", "REVALIDATED"}: return True
    if before.get("etag") and after.get("etag") and before["etag"] != after["etag"]: return True
    try: return int(after.get("age", "999999")) < int(before.get("age", "999999"))
    except ValueError: return False
def _public_metadata_absent(value):
    parsed = value.get("parsed", {}); return not any(item.get("name") == "description" for item in parsed.get("meta", [])) and not parsed.get("atlas_json_ld")
def _safe_public(value): return {key: value.get(key) for key in ("status_code", "final_url", "cache_headers", "head_hash", "visible_hash", "media32_reference_present")}
def _public_status(value): return {key: value.get(key) for key in ("plugin", "version", "checksum", "active", "rendering_enabled", "enabled_metadata_state", "activation_generation", "plugin_checksum", "payload_hash", "revision", "payload", "_error") if key in value}
def _page_media(value): return {key: value.get(key) for key in ("page_snapshot_hash", "page_body_hash", "media31_snapshot_hash", "media32_snapshot_hash", "site")}
def _backup_proof(request): return WordPressDeploymentBackupEvidence.model_validate(request.model_dump(mode="json", include=set(WordPressDeploymentBackupEvidence.model_fields)))
def _audit_proof(audit): return WordPressDeploymentBackupEvidence.model_validate(audit.backup_evidence)
def _evidence_summary(request):
    e = request.manual_browser_evidence; return {"id": e.evidence_id, "schema_version": e.evidence_schema_version, "head_hash": e.rendered_head_hash, "visible_hash": e.visible_content_hash, "expires_at": str(e.expires_at)}
def _stored_backup_timestamp(audit): return datetime.fromisoformat(str(audit.backup_evidence["wordpress_backup_completed_at"]).replace("Z", "+00:00"))
def _timestamp(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise HTTPException(422, "Timestamp must be timezone-aware.")
    return parsed.astimezone(UTC)
def _snapshot_hash(value):
    keys = ("rendering_enabled", "enabled_metadata_state", "activation_generation", "plugin_checksum", "payload_hash", "revision", "payload")
    canonical = {key: value.get(key) for key in keys}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
def _first_reason(gates, fallback):
    for gate in gates:
        if not gate.passed and gate.code in REASON_CODES: return gate.code
    return fallback
def _unavailable(reason): return {"_error": reason or "unavailable", "plugins": [], "rendered": {"verified": False}, "wordpress_request_methods": [], "read_only": True}
def _fingerprint(handle): return hashlib.sha256(handle.encode()).hexdigest() if handle else None


def _store_rendering(
    request,
    binding_hash,
    expires_at,
    *,
    stable_public_observation_fingerprint="",
    preflight_observed_at=None,
    evidence_captured_at=None,
    evidence_expires_at=None,
    backup_deadline=None,
    preflight_public_observation=None,
):
    handle = secrets.token_urlsafe(32)
    with _lock:
        _rendering_handles[handle] = _RenderingHandle(
            request.model_copy(deep=True), binding_hash, expires_at,
            stable_public_observation_fingerprint, preflight_observed_at,
            evidence_captured_at, evidence_expires_at, backup_deadline,
            deepcopy(preflight_public_observation) if preflight_public_observation is not None else None,
        )
        _start_timer("rendering", handle, expires_at)
    return handle
def _store_cache(
    audit_id,
    binding_hash,
    expires_at,
    *,
    stable_public_observation_fingerprint="",
    preflight_observed_at=None,
    backup_deadline=None,
    preflight_public_observation=None,
):
    handle = secrets.token_urlsafe(32)
    with _lock:
        _cache_handles[handle] = _CacheHandle(
            audit_id, binding_hash, expires_at,
            stable_public_observation_fingerprint, preflight_observed_at,
            backup_deadline,
            deepcopy(preflight_public_observation) if preflight_public_observation is not None else None,
        )
        _start_timer("cache", handle, expires_at)
    return handle
def _consume_rendering(handle): return _consume("rendering", handle)
def _consume_cache(handle): return _consume("cache", handle)
def _consume(kind, handle):
    with _lock:
        store = _rendering_handles if kind == "rendering" else _cache_handles
        entry = store.pop(handle, None); timer = _timers.pop((kind, handle), None)
        if timer: timer.cancel()
    if not entry: raise HTTPException(422, f"{kind.title()} handle is unknown, expired, consumed, or cleared by restart.")
    if entry.expires_at <= datetime.now(UTC):
        _raise_binding_conflict("public_observation_expired", f"{kind.title()} handle expired.")
    return entry
def _start_timer(kind, handle, expires_at):
    timer = Timer(max(0, (expires_at - datetime.now(UTC)).total_seconds()), _expire, args=(kind, handle)); timer.daemon = True; _timers[(kind, handle)] = timer; timer.start()
def _expire(kind, handle):
    with _lock:
        (_rendering_handles if kind == "rendering" else _cache_handles).pop(handle, None); _timers.pop((kind, handle), None)
def _clear_cache_aware_handles():
    with _lock:
        for timer in _timers.values(): timer.cancel()
        _rendering_handles.clear(); _cache_handles.clear(); _timers.clear()
