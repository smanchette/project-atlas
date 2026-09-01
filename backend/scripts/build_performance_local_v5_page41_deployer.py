"""Build the self-contained, browser-session Page 41 V5 staging deployer.

This generator is deliberately narrow.  It reads current governed Page 41
state and the accepted five-file media package, prepares (but does not deploy)
the current V5 payload, and writes ignored operator artifacts.  It performs no
WordPress request and persists no media mapping in Atlas.
"""

from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, create_engine

from app.services.performance_local_v5_payload import (
    canonical_performance_local_v5_json,
    prepare_performance_local_v5_staging_payload,
)


DATABASE_URL_ENV = "ATLAS_PAGE41_DEPLOYER_DATABASE_URL"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_ALEMBIC_REVISION = "20260820_0048"
EXPECTED_ORIGIN = "https://www.staging3.drywoodtenting.com"
EXPECTED_PAGE_ID = 41
EXPECTED_POST_ID = 8
EXPECTED_BRIDGE_VERSION = "0.57.11"
ACTIVATION_PHRASE = "ACTIVATE PERFORMANCE LOCAL V5 ON FLO-ZONE STAGING PAGE 8"
MAPPING_SCHEMA = "project-atlas-performance-local-v5-verified-media-map@1"
MAPPING_FROZEN_PATH = "browser/verified-media-map/" + MAPPING_SCHEMA
PREPARED_MAPPING_SHA256 = "PROJECT_ATLAS_UNFINALIZED_VERIFIED_MEDIA_MAP"
ACCEPTED_MANIFEST_SHA256 = (
    "0518e440f5b2232bb2e1617a4085c04db055c1ffd6be8285681236257007912d"
)
ACCEPTED_MANIFEST_SIZE = 13_746
EXPECTED_MEDIA_COUNT = 5
EXPECTED_MEDIA_BYTES = 2_791_091
PRIVATE_TOKENS = (
    '"recipient_email"',
    '"from_email"',
    '"smtp_',
    '"application_password"',
)


class Page41DeployerBuildError(RuntimeError):
    """The current governed source or accepted package failed closed."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: Any) -> bytes:
    return canonical_performance_local_v5_json(value)


def _file_identity(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
    }


def _load_accepted_manifest(package_dir: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = package_dir / "page41-media-manifest.json"
    data = manifest_path.read_bytes()
    if len(data) != ACCEPTED_MANIFEST_SIZE or sha256_bytes(data) != ACCEPTED_MANIFEST_SHA256:
        raise Page41DeployerBuildError("The accepted Page 41 media manifest identity changed.")
    try:
        manifest = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Page41DeployerBuildError("The accepted media manifest is invalid JSON.") from exc
    if (
        manifest.get("manifest_schema")
        != "project-atlas-page41-media-upload-manifest@1"
        or manifest.get("required_asset_count") != EXPECTED_MEDIA_COUNT
        or manifest.get("required_upload_bytes") != EXPECTED_MEDIA_BYTES
        or (manifest.get("target") or {}).get("generated_page_id") != EXPECTED_PAGE_ID
        or (manifest.get("target") or {}).get("wordpress_post_id") != EXPECTED_POST_ID
        or (manifest.get("target") or {}).get("accepted_wordpress_home") != EXPECTED_ORIGIN
    ):
        raise Page41DeployerBuildError("The accepted media manifest target differs.")
    return manifest, manifest_path


def _prepared_token(token_class: str, token_identity: int | str, source_filename: str) -> str:
    suffix = Path(source_filename).suffix.lower()
    return (
        "project-atlas-unfinalized-media:"
        f"{token_class}_{token_identity}{suffix}"
    )


def _asset_configuration(
    prepared: Any,
    manifest: dict[str, Any],
    package_dir: Path,
) -> list[dict[str, Any]]:
    expected: dict[tuple[str, int], Any] = {
        ("page_media", item.image_metadata_id): item
        for item in prepared.required_media
    }
    expected.update(
        {
            ("brand_asset", item.brand_asset_id): item
            for item in prepared.required_logo_media
        }
    )
    if len(expected) != EXPECTED_MEDIA_COUNT:
        raise Page41DeployerBuildError("Current Page 41 does not require exactly five V5 assets.")

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    total_bytes = 0
    for manifest_asset in manifest.get("assets") or []:
        manifest_class = manifest_asset.get("asset_class")
        asset_class = (
            "page_media"
            if manifest_class == "REQUIRED_PAGE_MEDIA"
            else "brand_asset" if manifest_class == "REQUIRED_BRAND_MEDIA" else None
        )
        governed_id = manifest_asset.get("governed_asset_id")
        key = (asset_class, governed_id)
        if asset_class is None or key not in expected or key in seen:
            raise Page41DeployerBuildError("The media manifest has an unknown or duplicate asset.")
        identity = expected[key]
        upload_filename = manifest_asset.get("upload_filename")
        if not isinstance(upload_filename, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*", upload_filename
        ):
            raise Page41DeployerBuildError("A prepared upload filename is unsafe.")
        upload_path = package_dir / "upload" / upload_filename
        source_path = Path(str(manifest_asset.get("source_path") or ""))
        if not source_path.is_absolute():
            source_path = REPOSITORY_ROOT / source_path
        source_path = source_path.resolve(strict=True)
        if not source_path.is_relative_to(REPOSITORY_ROOT):
            raise Page41DeployerBuildError("A governed media source escaped the repository.")
        upload_bytes = upload_path.read_bytes()
        source_bytes = source_path.read_bytes()
        expected_size = manifest_asset.get("bytes")
        expected_sha = manifest_asset.get("sha256")
        if (
            upload_bytes != source_bytes
            or len(upload_bytes) != expected_size
            or sha256_bytes(upload_bytes) != expected_sha
        ):
            raise Page41DeployerBuildError(
                f"Governed media bytes changed for {upload_filename}."
            )
        if asset_class == "page_media":
            expected_entry = {
                "governed_asset_class": asset_class,
                "requirement_id": identity.requirement_id,
                "placement_key": identity.placement_key,
                "target_component_instance_key": identity.target_component_instance_key,
                "assignment_id": identity.assignment_id,
                "assignment_version": identity.assignment_version,
                "authorization_id": identity.authorization_id,
                "authorization_version": identity.authorization_version,
                "authorization_fingerprint": identity.authorization_fingerprint,
                "governed_asset_id": identity.image_metadata_id,
                "governed_asset_key": identity.media_key,
                "governed_asset_version": identity.media_version,
                "expected_sha256": identity.checksum_sha256,
                "expected_mime_type": identity.source_mime_type,
                "expected_width": identity.source_width,
                "expected_height": identity.source_height,
            }
            token = _prepared_token(
                "page_requirement", identity.requirement_id, identity.source_filename
            )
        else:
            if identity.assignment_id is None or identity.assignment_version is None:
                raise Page41DeployerBuildError(
                    f"Current {identity.role} has no exact active identity assignment."
                )
            expected_entry = {
                "governed_asset_class": asset_class,
                "requirement_id": None,
                "placement_key": identity.role,
                "target_component_instance_key": identity.target_component_instance_key,
                "assignment_id": identity.assignment_id,
                "assignment_version": identity.assignment_version,
                "authorization_id": None,
                "authorization_version": None,
                "authorization_fingerprint": None,
                "governed_asset_id": identity.brand_asset_id,
                "governed_asset_key": identity.asset_key,
                "governed_asset_version": identity.asset_version,
                "expected_sha256": identity.checksum_sha256,
                "expected_mime_type": identity.source_mime_type,
                "expected_width": identity.source_width,
                "expected_height": identity.source_height,
            }
            token = _prepared_token(
                "brand_role", identity.role, identity.source_filename
            )
        manifest_expected = {
            "expected_sha256": manifest_asset.get("sha256"),
            "expected_mime_type": manifest_asset.get("mime_type"),
            "expected_width": manifest_asset.get("width"),
            "expected_height": manifest_asset.get("height"),
        }
        if any(expected_entry[name] != value for name, value in manifest_expected.items()):
            raise Page41DeployerBuildError(
                f"Manifest and current Atlas identity differ for {upload_filename}."
            )
        if manifest_asset.get("assignment_id") != expected_entry["assignment_id"]:
            raise Page41DeployerBuildError(
                f"Manifest assignment changed for {upload_filename}."
            )
        if asset_class == "page_media":
            authorization = manifest_asset.get("authorization_identity") or {}
            if (
                manifest_asset.get("requirement_id") != expected_entry["requirement_id"]
                or authorization.get("id") != expected_entry["authorization_id"]
                or authorization.get("version") != expected_entry["authorization_version"]
                or authorization.get("fingerprint_sha256")
                != expected_entry["authorization_fingerprint"]
            ):
                raise Page41DeployerBuildError(
                    f"Manifest governance changed for {upload_filename}."
                )
        alt_text = manifest_asset.get("alt_text")
        if not isinstance(alt_text, str) or not alt_text.strip():
            raise Page41DeployerBuildError("A governed media alt text is missing.")
        expected_occurrences = 2 if expected_entry["placement_key"] == "footer_logo" else 1
        result.append(
            {
                "upload_filename": upload_filename,
                "title": alt_text,
                "alt_text": alt_text,
                "bytes": len(upload_bytes),
                "base64": base64.b64encode(upload_bytes).decode("ascii"),
                "prepared_token": token,
                "expected_occurrences": expected_occurrences,
                "mapping": expected_entry,
            }
        )
        total_bytes += len(upload_bytes)
        seen.add(key)
    if seen != set(expected) or total_bytes != EXPECTED_MEDIA_BYTES:
        raise Page41DeployerBuildError("The exact five-file media subset is incomplete.")
    return result


def build_deployer(
    session: Session,
    *,
    package_dir: Path,
    output_dir: Path,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    revision = session.exec(text("SELECT version_num FROM alembic_version")).one()
    if str(revision[0]) != EXPECTED_ALEMBIC_REVISION:
        raise Page41DeployerBuildError("Active Atlas migration identity differs.")
    prepared = prepare_performance_local_v5_staging_payload(session, EXPECTED_PAGE_ID)
    if prepared.wordpress_post_id != EXPECTED_POST_ID:
        raise Page41DeployerBuildError("Page 41 no longer targets WordPress post 8.")
    manifest, accepted_manifest_path = _load_accepted_manifest(package_dir)
    accepted_manifest_bytes = accepted_manifest_path.read_bytes()
    assets = _asset_configuration(prepared, manifest, package_dir)
    template_bytes = canonical_json(prepared.payload_template)
    template_text = template_bytes.decode("utf-8")
    if template_text.count(json.dumps(PREPARED_MAPPING_SHA256)) != 1:
        raise Page41DeployerBuildError("Prepared map-hash sentinel count differs.")
    for asset in assets:
        count = template_text.count(json.dumps(asset["prepared_token"]))
        if count != asset["expected_occurrences"]:
            raise Page41DeployerBuildError(
                f"Prepared token count differs for {asset['upload_filename']}."
            )
    created = created_at or datetime.now(UTC)
    config = {
        "deployer_schema": "project-atlas-performance-local-v5-page41-one-shot@1",
        "expected_origin": EXPECTED_ORIGIN,
        "expected_bridge_version": EXPECTED_BRIDGE_VERSION,
        "private_route": "/project-atlas/v4/performance-local-v5/page-payload/8",
        "frontend_path": "/drywood-termite-tenting-orlando-fl/",
        "activation_phrase": ACTIVATION_PHRASE,
        "metadata_key": prepared.metadata_key,
        "payload_schema": prepared.payload_schema,
        "website_id": prepared.website_id,
        "planned_page_id": prepared.planned_page_id,
        "generated_page_id": prepared.generated_page_id,
        "wordpress_post_id": prepared.wordpress_post_id,
        "expected_post": {
            "title": prepared.payload_template["page"]["title"],
            "slug": prepared.payload_template["page"]["slug"],
            "status": "publish",
            "type": "page",
        },
        "source_bindings": prepared.source_bindings.model_dump(mode="json"),
        "mapping_schema": MAPPING_SCHEMA,
        "mapping_frozen_path": MAPPING_FROZEN_PATH,
        "prepared_mapping_sha256": PREPARED_MAPPING_SHA256,
        "accepted_media_manifest": {
            "bytes": len(accepted_manifest_bytes),
            "sha256": sha256_bytes(accepted_manifest_bytes),
            "base64": base64.b64encode(accepted_manifest_bytes).decode("ascii"),
        },
        "payload_template_canonical": template_text,
        "payload_template_sha256": sha256_bytes(template_bytes),
        "media_count": EXPECTED_MEDIA_COUNT,
        "embedded_media_bytes": EXPECTED_MEDIA_BYTES,
        "assets": assets,
        "unchanged_page_fields": [
            "title",
            "slug",
            "content",
            "excerpt",
            "status",
            "featured_image",
            "author",
            "parent",
            "menu_order",
            "_wp_page_template",
        ],
        "generated_at": created.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
    config_text = canonical_json(config).decode("utf-8")
    lowered = config_text.lower()
    forbidden = [token for token in PRIVATE_TOKENS if token.lower() in lowered]
    if forbidden:
        raise Page41DeployerBuildError(
            "The generated deployer configuration contains a forbidden private token."
        )
    script_text = JS_TEMPLATE.replace("__ATLAS_CONFIG_JSON__", config_text)
    if script_text.count(config_text) != 1 or "__ATLAS_CONFIG_JSON__" in script_text:
        raise Page41DeployerBuildError("The deployer template substitution failed.")
    output_dir.mkdir(parents=True, exist_ok=False)
    script_path = output_dir / "deploy-page41-v5.js"
    script_path.write_text(script_text, encoding="utf-8", newline="\n")
    loader = (
        "(()=>{const i=document.createElement('input');i.type='file';i.accept='.js';"
        "i.onchange=async()=>{const f=i.files&&i.files[0];if(!f)return;"
        "const u=URL.createObjectURL(f);try{await import(u)}finally{URL.revokeObjectURL(u)}};"
        "i.click()})()"
    )
    instructions = "\n".join(
        [
            "PROJECT ATLAS — PAGE 41 PERFORMANCE LOCAL V5 STAGING DEPLOYER",
            "",
            f"Required Metadata Bridge: {EXPECTED_BRIDGE_VERSION}",
            f"Required staging origin: {EXPECTED_ORIGIN}",
            "Expected runtime: usually 2–8 minutes, depending on media upload speed.",
            "",
            "1. Install/replace Metadata Bridge 0.57.11 on staging and verify it is active.",
            "2. Open the logged-in WordPress Page 8 editor on staging.",
            "3. Open DevTools Console and paste this one line:",
            loader,
            "4. Select deploy-page41-v5.js.",
            "5. Review the displayed summary and enter this exact phrase:",
            ACTIVATION_PHRASE,
            "6. Wait for COMPLETE. The completed staging page opens in a new tab.",
            "",
            "The browser downloads page41-staging-activation-result.json. COMPLETE means five exact media originals are verified, V5 metadata is valid and exact, and front-end markers pass. A failure result is resumable: do not delete uploaded media; rerun the same deployer so it reuses exact hashes. Never run this file on production.",
            "",
        ]
    )
    instructions_path = output_dir / "DEPLOY-PAGE41-INSTRUCTIONS.txt"
    instructions_path.write_text(instructions, encoding="utf-8", newline="\n")
    deployment_manifest = {
        "manifest_schema": "project-atlas-page41-one-shot-deployment-manifest@1",
        "created_at": config["generated_at"],
        "target": {
            "origin": EXPECTED_ORIGIN,
            "wordpress_post_id": EXPECTED_POST_ID,
            "generated_page_id": EXPECTED_PAGE_ID,
        },
        "source_bindings": config["source_bindings"],
        "bridge_version": EXPECTED_BRIDGE_VERSION,
        "payload_template_sha256": config["payload_template_sha256"],
        "embedded_media_count": EXPECTED_MEDIA_COUNT,
        "embedded_media_bytes": EXPECTED_MEDIA_BYTES,
        "accepted_media_manifest": _file_identity(accepted_manifest_path),
        "artifacts": {
            "deployer": _file_identity(script_path),
            "instructions": _file_identity(instructions_path),
        },
        "assertions": {
            "real_wordpress_request_performed": False,
            "active_atlas_write_count": 0,
            "private_delivery_values_present": False,
            "credential_values_present": False,
        },
    }
    manifest_path = output_dir / "deployment-manifest.json"
    manifest_path.write_bytes(canonical_json(deployment_manifest) + b"\n")
    return {
        "status": "BUILT",
        "output_directory": str(output_dir),
        "deployer": _file_identity(script_path),
        "instructions": _file_identity(instructions_path),
        "manifest": _file_identity(manifest_path),
        "loader": loader,
        "activation_phrase": ACTIVATION_PHRASE,
        "source_bindings": config["source_bindings"],
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    database_url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if not database_url:
        raise Page41DeployerBuildError(f"{DATABASE_URL_ENV} is required.")
    package_dir = Path(args.media_package).resolve(strict=True)
    output_dir = Path(args.output_directory).resolve()
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            session.exec(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            try:
                return build_deployer(
                    session,
                    package_dir=package_dir,
                    output_dir=output_dir,
                )
            finally:
                session.rollback()
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-package", required=True)
    parser.add_argument("--output-directory", required=True)
    args = parser.parse_args()
    print(json.dumps(execute(args), indent=2, sort_keys=True))


JS_TEMPLATE = r'''(() => {
"use strict";
const CONFIG = __ATLAS_CONFIG_JSON__;
const RESULT_NAME = "page41-staging-activation-result.json";
const LOCK_NAME = "project-atlas-page41-v5-staging-deployment";
const encoder = new TextEncoder();
const state = {attachments_created: [], attachments_reused: [], post_calls: 0, writes_started: false};

function fail(code, message, details = {}) {
  const error = new Error(message);
  error.atlasCode = code;
  error.atlasDetails = details;
  throw error;
}
function canonical(value) {
  if (value === null) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) fail("UNSAFE_MAPPING_NUMBER", "Mapping numbers must be safe integers.");
    return String(value);
  }
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") {
    return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
  }
  fail("UNSUPPORTED_CANONICAL_VALUE", "Unsupported canonical mapping value.");
}
async function sha256(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
}
function decodeBase64(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}
async function dimensions(bytes, mime) {
  const blob = new Blob([bytes], {type: mime});
  if (typeof createImageBitmap !== "function") fail("IMAGE_DECODER_MISSING", "The browser cannot verify image dimensions.");
  const image = await createImageBitmap(blob);
  try { return {width: image.width, height: image.height}; }
  finally { if (typeof image.close === "function") image.close(); }
}
function safeUploadPath(path) {
  if (typeof path !== "string" || path.includes("%") || path.includes("\\") || /[<>\u0000-\u001f\u007f]/.test(path)) return false;
  return /^\/wp-content\/uploads\/(?:atlas-v5\/[A-Za-z0-9][A-Za-z0-9._-]*(?:\/[A-Za-z0-9][A-Za-z0-9._-]*)*|[1-9][0-9]{3}\/(?:0[1-9]|1[0-2])\/[A-Za-z0-9][A-Za-z0-9._-]*)\.(?:avif|jpe?g|png|svg|webp)$/i.test(path);
}
function verifiedOriginalUrl(value) {
  let url;
  try { url = new URL(value); } catch { fail("UNSAFE_MEDIA_URL", "A WordPress original URL is invalid."); }
  if (url.protocol !== "https:" || url.origin !== CONFIG.expected_origin || url.username || url.password || url.search || url.hash || !safeUploadPath(url.pathname)) {
    fail("UNSAFE_MEDIA_URL", "A WordPress original URL is outside the verified uploads contract.", {url: String(value)});
  }
  return url;
}
async function api(options) {
  if (!window.wp || typeof window.wp.apiFetch !== "function") fail("WP_API_FETCH_MISSING", "window.wp.apiFetch is unavailable.");
  return window.wp.apiFetch(options);
}
function assertInspection(value) {
  const post = CONFIG.expected_post;
  if (!value || value.route_schema !== "project-atlas-performance-local-v5-page-payload-route@1" || value.metadata_bridge_version !== CONFIG.expected_bridge_version || value.environment_type !== "staging" || value.blog_public !== 0 || value.home !== CONFIG.expected_origin || value.siteurl !== CONFIG.expected_origin || value.post_id !== CONFIG.wordpress_post_id || value.post_type !== post.type || value.post_status !== post.status || value.post_title !== post.title || value.post_slug !== post.slug) {
    fail("STAGING_INSPECTION_MISMATCH", "The private staging inspection identity differs.");
  }
  if (typeof value.metadata_exists !== "boolean" || (!value.metadata_exists && (value.metadata_sha256 !== null || value.metadata_valid !== false || value.atlas_identity !== null))) fail("STAGING_METADATA_STATE_INVALID", "The private staging inspection returned an inconsistent absent metadata state.");
  return value;
}
async function inspectPrivateRoute() {
  return assertInspection(await api({path: CONFIG.private_route, method: "GET"}));
}
async function inspectCorePage() {
  const value = await api({path: `/wp/v2/pages/${CONFIG.wordpress_post_id}?context=edit`, method: "GET"});
  const raw = field => value && value[field] && typeof value[field].raw === "string" ? value[field].raw : null;
  const snapshot = value && {
    title: raw("title"), slug: value.slug, content: raw("content"), excerpt: raw("excerpt"),
    status: value.status, featured_image: value.featured_media, author: value.author,
    parent: value.parent, menu_order: value.menu_order, _wp_page_template: value.template,
  };
  if (!snapshot || value.id !== CONFIG.wordpress_post_id || value.type !== CONFIG.expected_post.type || snapshot.title !== CONFIG.expected_post.title || snapshot.slug !== CONFIG.expected_post.slug || snapshot.status !== CONFIG.expected_post.status || typeof snapshot.content !== "string" || typeof snapshot.excerpt !== "string" || !Number.isInteger(snapshot.featured_image) || !Number.isInteger(snapshot.author) || !Number.isInteger(snapshot.parent) || !Number.isInteger(snapshot.menu_order) || typeof snapshot._wp_page_template !== "string") fail("CORE_PAGE_INSPECTION_MISMATCH", "The editable core Page 8 identity or protected fields differ.");
  return snapshot;
}
async function listAllMedia() {
  const all = [];
  let page = 1;
  let totalPages = 1;
  do {
    if (page > 200) fail("MEDIA_PAGINATION_LIMIT", "WordPress media pagination exceeded the safety limit.");
    const response = await api({path: `/wp/v2/media?media_type=image&per_page=100&page=${page}&context=edit`, method: "GET", parse: false});
    if (!response || !response.ok) fail("MEDIA_LIST_FAILED", "WordPress media listing failed.");
    const rows = await response.json();
    if (!Array.isArray(rows)) fail("MEDIA_LIST_INVALID", "WordPress media listing returned an invalid body.");
    all.push(...rows);
    const header = response.headers && response.headers.get("X-WP-TotalPages");
    if (typeof header !== "string" || !/^(0|[1-9][0-9]*)$/.test(header)) fail("MEDIA_PAGINATION_INVALID", "WordPress omitted or returned an invalid media pagination header.");
    totalPages = Number(header);
    if (totalPages === 0 && page === 1) return all;
    if (!Number.isInteger(totalPages) || totalPages < page || totalPages > 200) fail("MEDIA_PAGINATION_INVALID", "WordPress media pagination is invalid.");
    page += 1;
  } while (page <= totalPages);
  return all;
}
function candidateHint(asset, media) {
  const source = typeof media.source_url === "string" ? media.source_url : "";
  const basename = source.split("/").pop() || "";
  const stem = asset.upload_filename.replace(/\.[^.]+$/, "").toLowerCase();
  const mime = String(media.mime_type || "").toLowerCase();
  const details = media.media_details || {};
  return (basename.toLowerCase().includes(stem) || String(media.slug || "").toLowerCase().includes(stem))
    || (mime === asset.mapping.expected_mime_type && details.width === asset.mapping.expected_width && details.height === asset.mapping.expected_height);
}
async function inspectRemoteAttachment(asset, media) {
  if (!media || !Number.isInteger(media.id) || media.id <= 0 || typeof media.source_url !== "string") return null;
  if (!candidateHint(asset, media)) return null;
  const url = verifiedOriginalUrl(media.source_url);
  const response = await fetch(url.href, {credentials: "same-origin", redirect: "error", cache: "no-store"});
  if (!response.ok || response.url !== url.href) return null;
  const contentType = String(response.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase();
  const length = Number(response.headers.get("content-length") || 0);
  if (length && length !== asset.bytes) return null;
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength !== asset.bytes) return null;
  const observedSha = await sha256(bytes);
  const observedDimensions = await dimensions(bytes, asset.mapping.expected_mime_type);
  if (observedSha !== asset.mapping.expected_sha256 || contentType !== asset.mapping.expected_mime_type || observedDimensions.width !== asset.mapping.expected_width || observedDimensions.height !== asset.mapping.expected_height) return null;
  return {id: media.id, source_url: url.href, observed_sha256: observedSha, observed_mime_type: contentType, observed_width: observedDimensions.width, observed_height: observedDimensions.height};
}
async function discoverExact(asset) {
  const media = await listAllMedia();
  const exact = [];
  for (const item of media) {
    const candidate = await inspectRemoteAttachment(asset, item);
    if (candidate) exact.push(candidate);
  }
  if (exact.length > 1) fail("AMBIGUOUS_EXACT_MEDIA", "More than one exact WordPress original matches a governed asset.", {filename: asset.upload_filename, attachment_ids: exact.map(v => v.id)});
  return exact[0] || null;
}
async function verifyEmbeddedAsset(asset) {
  const bytes = decodeBase64(asset.base64);
  if (bytes.byteLength !== asset.bytes || await sha256(bytes) !== asset.mapping.expected_sha256) fail("EMBEDDED_MEDIA_HASH_MISMATCH", "Embedded governed media bytes differ.", {filename: asset.upload_filename});
  const observed = await dimensions(bytes, asset.mapping.expected_mime_type);
  if (observed.width !== asset.mapping.expected_width || observed.height !== asset.mapping.expected_height) fail("EMBEDDED_MEDIA_DIMENSION_MISMATCH", "Embedded governed media dimensions differ.", {filename: asset.upload_filename});
  return bytes;
}
async function verifyEmbeddedManifest() {
  const identity = CONFIG.accepted_media_manifest;
  if (!identity || identity.bytes !== 13746 || identity.sha256 !== "0518e440f5b2232bb2e1617a4085c04db055c1ffd6be8285681236257007912d") fail("EMBEDDED_MANIFEST_IDENTITY_MISMATCH", "The accepted media manifest identity differs.");
  const bytes = decodeBase64(identity.base64);
  if (bytes.byteLength !== identity.bytes || await sha256(bytes) !== identity.sha256) fail("EMBEDDED_MANIFEST_HASH_MISMATCH", "The embedded accepted media manifest bytes differ.");
  let manifest;
  try { manifest = JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes)); }
  catch { fail("EMBEDDED_MANIFEST_INVALID", "The embedded accepted media manifest is invalid JSON."); }
  if (manifest.manifest_schema !== "project-atlas-page41-media-upload-manifest@1" || manifest.required_asset_count !== CONFIG.media_count || manifest.required_upload_bytes !== CONFIG.embedded_media_bytes || !manifest.target || manifest.target.generated_page_id !== CONFIG.generated_page_id || manifest.target.wordpress_post_id !== CONFIG.wordpress_post_id || manifest.target.accepted_wordpress_home !== CONFIG.expected_origin || !Array.isArray(manifest.assets) || manifest.assets.length !== CONFIG.media_count) fail("EMBEDDED_MANIFEST_TARGET_MISMATCH", "The embedded accepted media manifest target differs.");
  const byFilename = new Map();
  for (const item of manifest.assets) {
    if (!item || typeof item.upload_filename !== "string" || byFilename.has(item.upload_filename)) fail("EMBEDDED_MANIFEST_ASSET_MISMATCH", "The embedded accepted media manifest has an invalid or duplicate asset.");
    byFilename.set(item.upload_filename, item);
  }
  const configFilenames = new Set(CONFIG.assets.map(asset => asset && asset.upload_filename));
  if (CONFIG.assets.length !== CONFIG.media_count || configFilenames.size !== CONFIG.media_count || byFilename.size !== CONFIG.media_count || Array.from(byFilename.keys()).some(filename => !configFilenames.has(filename))) fail("EMBEDDED_MANIFEST_ASSET_SET_MISMATCH", "The deployer asset set differs from the exact embedded accepted manifest.");
  for (const asset of CONFIG.assets) {
    const item = byFilename.get(asset.upload_filename);
    const mapping = asset.mapping;
    const manifestClass = mapping.governed_asset_class === "page_media" ? "REQUIRED_PAGE_MEDIA" : "REQUIRED_BRAND_MEDIA";
    const governedKey = mapping.governed_asset_class === "page_media" ? item && item.media_key : item && item.asset_key;
    const governedVersion = mapping.governed_asset_class === "page_media" ? item && item.media_version : item && item.asset_version;
    const authorization = item && item.authorization_identity;
    if (!item || item.asset_class !== manifestClass || item.governed_asset_id !== mapping.governed_asset_id || governedKey !== mapping.governed_asset_key || governedVersion !== mapping.governed_asset_version || item.requirement_id !== mapping.requirement_id || item.placement_key !== mapping.placement_key || item.target_component_instance_key !== mapping.target_component_instance_key || item.assignment_id !== mapping.assignment_id || item.assignment_version !== mapping.assignment_version || item.bytes !== asset.bytes || item.sha256 !== mapping.expected_sha256 || item.mime_type !== mapping.expected_mime_type || item.width !== mapping.expected_width || item.height !== mapping.expected_height || item.alt_text !== asset.alt_text || (mapping.governed_asset_class === "page_media" && (!authorization || authorization.id !== mapping.authorization_id || authorization.version !== mapping.authorization_version || authorization.fingerprint_sha256 !== mapping.authorization_fingerprint)) || (mapping.governed_asset_class === "brand_asset" && authorization !== null)) fail("EMBEDDED_MANIFEST_ASSET_MISMATCH", "A deployer asset differs from the exact embedded accepted manifest.", {filename: asset.upload_filename});
  }
}
async function uploadAsset(asset, bytes) {
  const prior = await discoverExact(asset);
  if (prior) return {remote: prior, disposition: "reused"};
  const form = new FormData();
  form.append("file", new Blob([bytes], {type: asset.mapping.expected_mime_type}), asset.upload_filename);
  form.append("title", asset.title);
  form.append("alt_text", asset.alt_text);
  state.writes_started = true;
  let response;
  try { response = await api({path: "/wp/v2/media", method: "POST", body: form}); }
  catch (error) { fail("MEDIA_UPLOAD_UNCERTAIN", "A media upload response was lost or rejected. Stop and rerun so the hash can be rediscovered.", {filename: asset.upload_filename, cause: String(error && error.message || error)}); }
  if (!response || !Number.isInteger(response.id) || response.id <= 0) fail("MEDIA_UPLOAD_INVALID", "WordPress returned an invalid media identity.");
  const verified = await inspectRemoteAttachment(asset, response);
  if (!verified) fail("MEDIA_UPLOAD_VERIFICATION_FAILED", "The uploaded WordPress original failed exact verification.", {attachment_id: response.id});
  return {remote: verified, disposition: "created"};
}
function buildMapping(remotes) {
  const entries = CONFIG.assets.map((asset, index) => ({
    ...asset.mapping,
    wordpress_attachment_id: remotes[index].id,
    wordpress_original_url: remotes[index].source_url,
    observed_sha256: remotes[index].observed_sha256,
    observed_mime_type: remotes[index].observed_mime_type,
    observed_width: remotes[index].observed_width,
    observed_height: remotes[index].observed_height,
  }));
  const mapping = {
    mapping_schema: CONFIG.mapping_schema,
    context: {website_id: CONFIG.website_id, planned_page_id: CONFIG.planned_page_id, generated_page_id: CONFIG.generated_page_id, wordpress_post_id: CONFIG.wordpress_post_id, staging_origin: CONFIG.expected_origin, source_bindings: CONFIG.source_bindings},
    entries,
  };
  const ids = new Map();
  const urls = new Map();
  for (const entry of entries) {
    if (entry.expected_sha256 !== entry.observed_sha256 || entry.expected_mime_type !== entry.observed_mime_type || entry.expected_width !== entry.observed_width || entry.expected_height !== entry.observed_height) fail("INVALID_VERIFIED_MAPPING", "A verified media entry differs from its governed identity.");
    verifiedOriginalUrl(entry.wordpress_original_url);
    const key = `${entry.governed_asset_class}:${entry.governed_asset_id}`;
    if ((ids.has(entry.wordpress_attachment_id) && ids.get(entry.wordpress_attachment_id) !== key) || (urls.has(entry.wordpress_original_url) && urls.get(entry.wordpress_original_url) !== key)) fail("INVALID_VERIFIED_MAPPING", "Different governed assets share one WordPress original.");
    ids.set(entry.wordpress_attachment_id, key); urls.set(entry.wordpress_original_url, key);
  }
  const header = entries.find(v => v.placement_key === "header_logo");
  const footer = entries.find(v => v.placement_key === "footer_logo");
  if (!header || !footer || header.wordpress_attachment_id === footer.wordpress_attachment_id || header.wordpress_original_url === footer.wordpress_original_url) fail("INVALID_VERIFIED_MAPPING", "Header and footer logos are not distinct.");
  return mapping;
}
function replaceExact(source, needle, replacement, expectedCount) {
  const pieces = source.split(needle);
  if (pieces.length - 1 !== expectedCount) fail("PAYLOAD_TEMPLATE_MISMATCH", "A prepared payload sentinel count differs.");
  return pieces.join(replacement);
}
async function finalizePayload(mapping) {
  if (await sha256(encoder.encode(CONFIG.payload_template_canonical)) !== CONFIG.payload_template_sha256) fail("PAYLOAD_TEMPLATE_HASH_MISMATCH", "The embedded prepared payload template differs.");
  const normalizedMapping = {...mapping, entries: mapping.entries.slice().sort((left, right) => {
    const leftKey = left.governed_asset_class === "page_media" ? [0, left.requirement_id || 0, left.governed_asset_id] : [1, left.placement_key === "header_logo" ? 0 : 1, left.governed_asset_id];
    const rightKey = right.governed_asset_class === "page_media" ? [0, right.requirement_id || 0, right.governed_asset_id] : [1, right.placement_key === "header_logo" ? 0 : 1, right.governed_asset_id];
    return leftKey[0] - rightKey[0] || leftKey[1] - rightKey[1] || leftKey[2] - rightKey[2];
  })};
  const mappingCanonical = canonical(normalizedMapping);
  const mapSha = await sha256(encoder.encode(mappingCanonical));
  let finalCanonical = CONFIG.payload_template_canonical;
  CONFIG.assets.forEach((asset, index) => {
    const path = verifiedOriginalUrl(mapping.entries[index].wordpress_original_url).pathname;
    finalCanonical = replaceExact(finalCanonical, JSON.stringify(asset.prepared_token), JSON.stringify(path), asset.expected_occurrences);
  });
  finalCanonical = replaceExact(finalCanonical, JSON.stringify(CONFIG.prepared_mapping_sha256), JSON.stringify(mapSha), 1);
  if (finalCanonical.includes("project-atlas-unfinalized-media:") || finalCanonical.includes(CONFIG.prepared_mapping_sha256)) fail("PAYLOAD_TEMPLATE_MISMATCH", "A prepared payload sentinel remains.");
  const payload = JSON.parse(finalCanonical);
  const privateText = finalCanonical.toLowerCase();
  for (const token of ["\"recipient_email\"", "\"from_email\"", "\"smtp_", "\"application_password\"", "\"authorization\""]) if (privateText.includes(token)) fail("PRIVATE_DATA_IN_PUBLIC_PAYLOAD", "A forbidden private delivery value entered the payload.");
  if (payload.schema_version !== CONFIG.payload_schema || !Array.isArray(payload.payload_identity.frozen_inputs) || !payload.payload_identity.frozen_inputs.some(v => v.path === CONFIG.mapping_frozen_path && v.sha256 === mapSha)) fail("INVALID_FINAL_PAYLOAD", "The finalized payload identity is invalid.");
  return {payload, canonical: finalCanonical, sha256: await sha256(encoder.encode(finalCanonical)), mapping_sha256: mapSha};
}
function rawPostEnvelope(finalized, expectedPrior, requestIdentity) {
  return "{" + [
    `\"generated_page_id\":${CONFIG.generated_page_id}`,
    `\"expected_prior_sha256\":${expectedPrior === null ? "null" : JSON.stringify(expectedPrior)}`,
    `\"payload\":${finalized.canonical}`,
    `\"planned_page_id\":${CONFIG.planned_page_id}`,
    `\"request_identity\":${JSON.stringify(requestIdentity)}`,
    `\"request_schema\":\"project-atlas-performance-local-v5-page-payload-request@1\"`,
    `\"website_id\":${CONFIG.website_id}`,
    `\"wordpress_post_id\":${CONFIG.wordpress_post_id}`,
  ].join(",") + "}";
}
function sanitizedMedia(mapping, dispositions) {
  return mapping.entries.map((entry, index) => ({governed_asset_class: entry.governed_asset_class, requirement_id: entry.requirement_id, placement_key: entry.placement_key, assignment_id: entry.assignment_id, authorization_id: entry.authorization_id, governed_asset_id: entry.governed_asset_id, wordpress_attachment_id: entry.wordpress_attachment_id, wordpress_original_url: entry.wordpress_original_url, observed_sha256: entry.observed_sha256, observed_mime_type: entry.observed_mime_type, observed_width: entry.observed_width, observed_height: entry.observed_height, disposition: dispositions[index]}));
}
function downloadResult(result) {
  const safe = JSON.stringify(result, null, 2);
  const blob = new Blob([safe + "\n"], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = RESULT_NAME; link.hidden = true;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function verifyFrontend() {
  const reviewUrl = `${CONFIG.expected_origin}${CONFIG.frontend_path}?atlas-v5-review=${Date.now()}`;
  const response = await fetch(reviewUrl, {credentials: "same-origin", redirect: "error", cache: "no-store"});
  if (!response.ok || new URL(response.url).origin !== CONFIG.expected_origin) fail("FRONTEND_FETCH_FAILED", "The completed staging page could not be fetched.");
  const html = await response.text();
  const doc = new DOMParser().parseFromString(html, "text/html");
  const payload = window.__atlasFinalizedPayload;
  const governedSections = payload.sections.map(section => section.key);
  const governedSectionMedia = payload.sections.filter(section => section.media && typeof section.media.src === "string").map(section => section.media.src);
  const checks = {
    renderer_marker: doc.querySelectorAll("[data-project-atlas-v5-root]").length === 1,
    one_h1: doc.querySelectorAll("h1").length === 1,
    header: doc.querySelectorAll("header.performanceLocalHeader").length === 1,
    hero: doc.querySelectorAll("section.performanceLocalHero").length === 1,
    sticky_phone: doc.querySelectorAll(".performanceLocalV5StickyPhoneBar").length === 1,
    sticky_estimate: doc.querySelectorAll(".performanceLocalV5StickyActionBanner").length === 1,
    governed_sections: governedSections.length === 6 && governedSections.every(key => doc.querySelector(`[data-source-section-key=\"${key}\"]`)),
    process_image: governedSectionMedia.length === 2 && Array.from(doc.images).some(image => image.src.includes(governedSectionMedia[0])),
    evidence_image: governedSectionMedia.length === 2 && Array.from(doc.images).some(image => image.src.includes(governedSectionMedia[1])),
    final_form: doc.querySelectorAll("form[data-atlas-v5-inert-form]").length === 1,
    footer: doc.querySelectorAll("footer.performanceLocalFooter").length === 1,
    no_duplicate_theme_wrapper: doc.querySelectorAll("header").length === 1 && doc.querySelectorAll("footer").length === 1,
    no_private_delivery: !/recipient_email|from_email|smtp_password|smtp_username/i.test(html),
    no_credentials_strip: !/JB360566|Jordan Ward|Certified Operator/i.test(html),
    no_raw_payload: !html.includes(CONFIG.payload_schema),
  };
  if (Object.values(checks).some(value => value !== true)) fail("FRONTEND_MARKER_FAILED", "The completed staging page failed one or more V5 render markers.", {checks});
  return {url: reviewUrl, checks};
}
async function deployment() {
  const targetQuery = new URLSearchParams(location.search);
  if (location.origin !== CONFIG.expected_origin || location.pathname !== "/wp-admin/post.php" || location.hostname !== "www.staging3.drywoodtenting.com" || targetQuery.getAll("post").length !== 1 || targetQuery.get("post") !== String(CONFIG.wordpress_post_id) || targetQuery.getAll("action").length !== 1 || targetQuery.get("action") !== "edit") fail("WRONG_BROWSER_TARGET", "Open the logged-in staging Page 8 editor before running this deployer.");
  if (!window.isSecureContext || !crypto || !crypto.subtle || !crypto.randomUUID) fail("BROWSER_CRYPTO_MISSING", "A secure browser crypto context is required.");
  if (!navigator.locks || typeof navigator.locks.request !== "function") fail("BROWSER_LOCK_MISSING", "The browser cannot acquire the exclusive deployment lock.");
  await verifyEmbeddedManifest();
  const initial = await inspectPrivateRoute();
  const protectedBefore = await inspectCorePage();
  const embedded = [];
  for (const asset of CONFIG.assets) embedded.push(await verifyEmbeddedAsset(asset));
  const summary = [`Staging: ${CONFIG.expected_origin}`, `Page 8: ${CONFIG.expected_post.title}`, `Governed media: ${CONFIG.media_count} (${CONFIG.embedded_media_bytes} bytes)`, `Metadata key: ${CONFIG.metadata_key}`, `Page fields changed: none`, "", `Type exactly: ${CONFIG.activation_phrase}`].join("\n");

  const existing = [];
  for (const asset of CONFIG.assets) existing.push(await discoverExact(asset));
  if (initial.metadata_exists && existing.some(value => value === null)) fail("EXISTING_METADATA_WITH_MISSING_MEDIA", "Existing V5 metadata cannot be validated before media writes.");
  if (initial.metadata_exists) {
    const currentMap = buildMapping(existing);
    const currentFinal = await finalizePayload(currentMap);
    if (!initial.metadata_valid || initial.metadata_sha256 !== currentFinal.sha256) fail("REMOTE_METADATA_CONFLICT", "Existing V5 metadata differs from the intended exact payload.");
  }
  const entered = window.prompt(summary, "");
  if (entered !== CONFIG.activation_phrase) fail("OPERATOR_DECLINED", "The exact activation phrase was not confirmed.");
  const reviewWindow = window.open("about:blank", "_blank");
  if (!reviewWindow) fail("REVIEW_WINDOW_BLOCKED", "Allow the staging review tab, then rerun before any media or metadata write.");
  reviewWindow.opener = null;
  const remotes = [];
  const dispositions = [];
  for (let index = 0; index < CONFIG.assets.length; index += 1) {
    const asset = CONFIG.assets[index];
    const outcome = existing[index] ? {remote: existing[index], disposition: "reused"} : await uploadAsset(asset, embedded[index]);
    remotes.push(outcome.remote); dispositions.push(outcome.disposition);
    (outcome.disposition === "created" ? state.attachments_created : state.attachments_reused).push(outcome.remote.id);
  }
  const finalRemotes = [];
  for (const asset of CONFIG.assets) {
    const exact = await discoverExact(asset);
    if (!exact) fail("FINAL_MEDIA_RECHECK_FAILED", "An exact media original disappeared before metadata apply.");
    finalRemotes.push(exact);
  }
  const mapping = buildMapping(finalRemotes);
  const finalized = await finalizePayload(mapping);
  window.__atlasFinalizedPayload = finalized.payload;
  const immediatelyBefore = await inspectPrivateRoute();
  if ((initial.metadata_exists !== immediatelyBefore.metadata_exists || initial.metadata_sha256 !== immediatelyBefore.metadata_sha256) && immediatelyBefore.metadata_sha256 !== finalized.sha256) fail("REMOTE_METADATA_CHANGED", "V5 metadata changed before the one allowed POST.");
  const protectedImmediatelyBefore = await inspectCorePage();
  const preWritePageFieldsChanged = CONFIG.unchanged_page_fields.filter(field => canonical(protectedBefore[field]) !== canonical(protectedImmediatelyBefore[field]));
  if (preWritePageFieldsChanged.length) fail("CORE_PAGE_FIELDS_CHANGED", "One or more protected Page 8 fields changed before metadata apply.", {page_fields_changed: preWritePageFieldsChanged});
  const requestIdentity = crypto.randomUUID();
  state.post_calls += 1;
  if (state.post_calls !== 1) fail("MULTIPLE_METADATA_POSTS", "More than one metadata POST was attempted.");
  state.writes_started = true;
  const applyResult = await api({path: CONFIG.private_route, method: "POST", body: rawPostEnvelope(finalized, initial.metadata_sha256, requestIdentity), headers: {"Content-Type": "application/json"}});
  if (!applyResult || applyResult.route_schema !== "project-atlas-performance-local-v5-page-payload-route@1" || !["APPLIED", "UNCHANGED"].includes(applyResult.status) || applyResult.post_id !== CONFIG.wordpress_post_id || applyResult.prior_sha256 !== initial.metadata_sha256 || applyResult.resulting_sha256 !== finalized.sha256 || applyResult.website_id !== CONFIG.website_id || applyResult.planned_page_id !== CONFIG.planned_page_id || applyResult.generated_page_id !== CONFIG.generated_page_id || applyResult.request_identity !== requestIdentity || applyResult.metadata_valid !== true || applyResult.metadata_bridge_version !== CONFIG.expected_bridge_version) fail("METADATA_APPLY_INVALID", "The private route returned an invalid apply result.");
  const verified = await inspectPrivateRoute();
  if (!verified.metadata_exists || !verified.metadata_valid || verified.metadata_sha256 !== finalized.sha256 || !verified.atlas_identity || verified.atlas_identity.generated_page_id !== CONFIG.generated_page_id || verified.atlas_identity.website_id !== CONFIG.website_id || verified.atlas_identity.source_composition !== finalized.payload.payload_identity.source_composition || verified.atlas_identity.source_sha256 !== CONFIG.source_bindings.composition_source_hash) fail("METADATA_POSTCHECK_FAILED", "The private metadata postcheck differs.");
  const protectedAfter = await inspectCorePage();
  const pageFieldsChanged = CONFIG.unchanged_page_fields.filter(field => canonical(protectedBefore[field]) !== canonical(protectedAfter[field]));
  if (pageFieldsChanged.length) fail("CORE_PAGE_FIELDS_CHANGED", "One or more protected Page 8 fields changed during deployment.", {page_fields_changed: pageFieldsChanged});
  const frontend = await verifyFrontend();
  reviewWindow.location.href = frontend.url;
  const result = {result_schema: "project-atlas-page41-staging-activation-result@1", timestamp: new Date().toISOString(), deployment_status: "COMPLETE", staging_origin: CONFIG.expected_origin, page: {wordpress_post_id: CONFIG.wordpress_post_id, title: CONFIG.expected_post.title, slug: CONFIG.expected_post.slug}, atlas: {...CONFIG.source_bindings, website_id: CONFIG.website_id, planned_page_id: CONFIG.planned_page_id, generated_page_id: CONFIG.generated_page_id}, media: sanitizedMedia(mapping, dispositions), payload_sha256: finalized.sha256, verified_media_mapping_sha256: finalized.mapping_sha256, post_result: {status: applyResult.status, request_identity: requestIdentity, resulting_sha256: applyResult.resulting_sha256}, get_verification: {metadata_exists: verified.metadata_exists, metadata_valid: verified.metadata_valid, metadata_sha256: verified.metadata_sha256}, frontend, page_fields_changed: [], metadata_key_changed: CONFIG.metadata_key, attachments_created: state.attachments_created, attachments_reused: state.attachments_reused};
  downloadResult(result);
  console.info("PROJECT ATLAS PAGE 41 DEPLOYMENT: COMPLETE", result);
  return result;
}

async function run() {
  let delivered = false;
  try {
    if (!navigator.locks || typeof navigator.locks.request !== "function") fail("BROWSER_LOCK_MISSING", "The browser cannot acquire the exclusive deployment lock.");
    const result = await navigator.locks.request(LOCK_NAME, {mode: "exclusive", ifAvailable: true}, async lock => {
      if (!lock) fail("DEPLOYMENT_ALREADY_RUNNING", "Another Page 41 deployment is running in this browser profile.");
      return deployment();
    });
    delivered = true;
    return result;
  } catch (error) {
    const result = {result_schema: "project-atlas-page41-staging-activation-result@1", timestamp: new Date().toISOString(), deployment_status: "RESUMABLE_BLOCKER", blocker: String(error && error.atlasCode || "UNEXPECTED_FAILURE"), message: String(error && error.message || error), details: error && error.atlasDetails || {}, staging_origin: location.origin, attachments_created: state.attachments_created, attachments_reused: state.attachments_reused, metadata_post_count: state.post_calls, page_fields_changed: null};
    if (!delivered) downloadResult(result);
    console.error("PROJECT ATLAS PAGE 41 DEPLOYMENT: BLOCKED", result);
    throw error;
  }
}
void run();
})();
'''


if __name__ == "__main__":
    main()
