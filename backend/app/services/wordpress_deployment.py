from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath
import re
import secrets
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
)
from app.schemas.wordpress import (
    WordPressDeploymentAuthorizeRequest,
    WordPressDeploymentAuthorization,
    WordPressDeploymentBackupEvidence,
    WordPressDeploymentInstallDryRun,
    WordPressDeploymentManualComplete,
    WordPressDeploymentManualCompleteRequest,
    WordPressDeploymentVerification,
    WordPressDeploymentVerifyRequest,
    WordPressDraftGateResult,
)
from app.services.wordpress_metadata import _hash, _parse_html, _sign_context, _verify
from app.services.wordpress_sandbox import get_wordpress_application_password, read_wordpress_settings

ATLAS_VERSION = "v0.57.7"
ATLAS_COMMIT = "eb834904d59eb4f266e3e77393994c2d72a332ce"
ATLAS_TAG = "v0.57.7"
PLUGIN_VERSION = "0.57.4"
PLUGIN_SLUG = "project-atlas-metadata-bridge"
PLUGIN_FILE = f"{PLUGIN_SLUG}/project-atlas-metadata-bridge.php"
ZIP_NAME = "project-atlas-metadata-bridge-0.57.4.zip"
ZIP_SHA256 = "939412e6e80e8344d95274444fda65b6122fe0c8249a2ced0a8582a418c4e232"
SOURCE_SHA256 = "5b33659b9fab81ff5aa6d6c8e0d5b89037b5d62fa454e0939f9b3ca91d32cab2"
INSTALL_PHRASE = "INSTALL PROJECT ATLAS METADATA BRIDGE"
BACKUP_WINDOW = timedelta(hours=4)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_ROOT = PROJECT_ROOT / "docs" / "deployment-records" / "wordpress" / "orlando-page-8"
ZIP_PATH = PROJECT_ROOT / "wordpress" / "dist" / ZIP_NAME
SOURCE_DIR = PROJECT_ROOT / "wordpress" / PLUGIN_SLUG
ALLOWED_TRANSITIONS = {
    "installation_authorized": {"awaiting_manual_installation", "failed"},
    "awaiting_manual_installation": {"manual_installation_reported", "failed"},
    "manual_installation_reported": {"verification_pending", "failed"},
    "verification_pending": {"verified", "verification_failed", "reconciliation_required", "failed"},
    "reconciliation_required": {"failed"},
}


def install_dry_run(session: Session, page_id: int, proof: WordPressDeploymentBackupEvidence) -> WordPressDeploymentInstallDryRun:
    _target(page_id)
    artifact, artifact_gates = _verify_artifact()
    observed = _observe(session)
    gates = [*artifact_gates, *_backup_gates(proof), *_state_gates(session, observed)]
    context = _bound_context(observed, proof, artifact)
    ready = all(gate.passed for gate in gates)
    token = phrase = expires_at = None
    if ready:
        deadline = _backup_deadline(proof.wordpress_backup_completed_at)
        expires = min(datetime.now(UTC) + timedelta(minutes=15), deadline)
        token = _sign_context("authorize_manual_plugin_install", context, expires)
        phrase = INSTALL_PHRASE
        expires_at = expires.isoformat()
    age = _backup_age(proof.wordpress_backup_completed_at)
    return WordPressDeploymentInstallDryRun(
        status="preflight_ready" if ready else "preflight_not_started",
        ready=ready,
        artifact=artifact,
        inspected_state=observed,
        backup_age_seconds=int(age.total_seconds()) if age is not None else None,
        gate_results=gates,
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
    deployment_key = _deployment_key(request)
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
        atlas_version=ATLAS_VERSION,
        atlas_commit=ATLAS_COMMIT,
        atlas_tag=ATLAS_TAG,
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
    observed = _observe(session)
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
    observed = _observe(session)
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


def reconcile_install_audit(session: Session, page_id: int, request: WordPressDeploymentVerifyRequest) -> WordPressDeploymentVerification:
    _target(page_id)
    audit = _audit(session, request.audit_id)
    raise HTTPException(409, f"Audit {audit.id} requires a separately approved reconciliation workflow; no WordPress request was performed.")


def _observe(session: Session) -> dict[str, Any]:
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not (settings.site_url and settings.username and password):
        return {"_error": "credentials_unavailable", "plugins": []}
    root = _request(settings.site_url, settings.username, password, "GET", "/wp-json/")
    plugins = _request(settings.site_url, settings.username, password, "GET", "/wp-json/wp/v2/plugins?context=edit")
    page = _request(settings.site_url, settings.username, password, "GET", "/wp-json/wp/v2/pages/8?context=edit")
    media31 = _request(settings.site_url, settings.username, password, "GET", "/wp-json/wp/v2/media/31?context=edit")
    media32 = _request(settings.site_url, settings.username, password, "GET", "/wp-json/wp/v2/media/32?context=edit")
    rendered = _request(settings.site_url, settings.username, password, "GET", "/drywood-termite-tenting-orlando-fl/?atlas_install_verify=1", text=True)
    parsed = rendered.get("parsed", {}) if isinstance(rendered, dict) else {}
    plugin_list = plugins if isinstance(plugins, list) else []
    active_plugins = sorted(item.get("plugin") for item in plugin_list if item.get("status") in {"active", "network-active"})
    media32_url = media32.get("source_url", "") if isinstance(media32, dict) else ""
    page_encoded = json.dumps(page, sort_keys=True) if isinstance(page, dict) else ""
    rendered_encoded = json.dumps(parsed, sort_keys=True)
    locked = {
        "site_title": root.get("name") if isinstance(root, dict) else None,
        "tagline": root.get("description") if isinstance(root, dict) else None,
        "page_snapshot_hash": _hash(page),
        "media31_snapshot_hash": _hash(media31),
        "media32_snapshot_hash": _hash(media32),
        "rendered_head_hash": parsed.get("head_hash"),
        "visible_content_hash": parsed.get("visible_hash"),
    }
    return {
        "plugins": plugin_list,
        "active_plugins": active_plugins,
        "plugin_inventory_hash": _hash(plugin_list),
        "active_plugin_inventory_hash": _hash(active_plugins),
        "page": _resource_snapshot(page),
        "page_snapshot_hash": _hash(page),
        "media31": _resource_snapshot(media31),
        "media31_snapshot_hash": _hash(media31),
        "media32": _resource_snapshot(media32),
        "media32_snapshot_hash": _hash(media32),
        "site": {"name": root.get("name"), "description": root.get("description")} if isinstance(root, dict) else {},
        "rendered": {
            "head_hash": parsed.get("head_hash"),
            "visible_hash": parsed.get("visible_hash"),
            "raw_hash": parsed.get("raw_hash"),
            "atlas_metadata_marker_present": rendered.get("atlas_metadata_marker_present", False) if isinstance(rendered, dict) else False,
            "media32_reference_present": bool(media32_url and media32_url in rendered_encoded) or "hero-1.png" in rendered_encoded,
        },
        "page_references_media32": bool(media32_url and media32_url in page_encoded) or "hero-1.png" in page_encoded,
        "locked_state_hash": _hash(locked),
        "cache_headers": rendered.get("cache_headers", {}) if isinstance(rendered, dict) else {},
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
        _gate("rendered", "Rendered head and body hashes captured", bool(observed.get("rendered", {}).get("head_hash") and observed.get("rendered", {}).get("visible_hash")), "Rendered state unavailable."),
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


def _verify_artifact() -> tuple[dict[str, Any], list[WordPressDraftGateResult]]:
    sha = hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest() if ZIP_PATH.is_file() else ""
    try:
        with zipfile.ZipFile(ZIP_PATH) as archive:
            names = archive.namelist()
            expected = {f"{PLUGIN_SLUG}/{path.relative_to(SOURCE_DIR).as_posix()}": path.read_bytes() for path in SOURCE_DIR.rglob("*") if path.is_file()}
            actual = {name: archive.read(name) for name in names if not name.endswith("/")}
            valid = len(names) == len(set(names)) and all("\\" not in name and not name.startswith("/") and not re.match(r"^[A-Za-z]:", name) and ".." not in PurePosixPath(name).parts for name in names) and {PurePosixPath(name).parts[0] for name in names} == {PLUGIN_SLUG} and actual == expected and PLUGIN_FILE in names
    except (OSError, zipfile.BadZipFile):
        valid = False
    artifact = {
        "atlas_version": ATLAS_VERSION,
        "atlas_commit": ATLAS_COMMIT,
        "atlas_tag": ATLAS_TAG,
        "plugin_slug": PLUGIN_SLUG,
        "plugin_path": PLUGIN_FILE,
        "plugin_version": PLUGIN_VERSION,
        "zip_file_name": ZIP_NAME,
        "zip_sha256": sha,
        "plugin_source_sha256": SOURCE_SHA256,
    }
    return artifact, [
        _gate("artifact_hash", "ZIP SHA-256 is locked", sha == ZIP_SHA256, "ZIP checksum mismatch."),
        _gate("artifact_portable", "ZIP is portable and byte-equal to source", valid, "ZIP structure/source mismatch."),
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
    return gates


def _bound_context(observed: dict[str, Any], proof: WordPressDeploymentBackupEvidence, artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "manual_install_authorization",
        "atlas_page_id": 41,
        "wordpress_page_id": 8,
        "plugin_slug": PLUGIN_SLUG,
        "plugin_path": PLUGIN_FILE,
        "artifact": artifact,
        "atlas_release": {"version": ATLAS_VERSION, "commit": ATLAS_COMMIT, "tag": ATLAS_TAG},
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


def _deployment_key(proof: WordPressDeploymentBackupEvidence) -> str:
    return _hash({"page": 41, "wordpress_page": 8, "plugin_slug": PLUGIN_SLUG, "plugin_version": PLUGIN_VERSION, "zip_sha256": ZIP_SHA256, "backup_reference": proof.wordpress_backup_reference})


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
    candidate = (PROJECT_ROOT / value).resolve(strict=False)
    approved = EVIDENCE_ROOT.resolve(strict=False)
    if candidate != approved and approved not in candidate.parents:
        raise HTTPException(422, "Resolved evidence directory escapes the approved root.")
    return value


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
