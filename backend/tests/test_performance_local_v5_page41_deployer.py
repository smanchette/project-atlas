from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from app.schemas.performance_local_v5 import (
    PerformanceLocalV5LogoIdentity,
    PerformanceLocalV5MediaIdentity,
    PerformanceLocalV5PreparedPayload,
    PerformanceLocalV5SourceBindings,
    PerformanceLocalV5VerifiedMediaMap,
)
from app.services.performance_local_v5_payload import (
    finalize_performance_local_v5_staging_payload,
    performance_local_v5_payload_sha256,
)
from scripts import build_performance_local_v5_page41_deployer as deployer


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ACCEPTED_PACKAGE = (
    REPOSITORY_ROOT
    / ".runtime"
    / "performance-local-v5-page41-media-preparation"
    / "20260831T164234EDT"
)


class _MigrationResult:
    def one(self) -> tuple[str]:
        return (deployer.EXPECTED_ALEMBIC_REVISION,)


class _ReadOnlySession:
    def exec(self, _statement):
        return _MigrationResult()


def _prepared_payload() -> PerformanceLocalV5PreparedPayload:
    manifest = json.loads(
        (ACCEPTED_PACKAGE / "page41-media-manifest.json").read_text(encoding="utf-8")
    )
    page_media: list[PerformanceLocalV5MediaIdentity] = []
    logos: list[PerformanceLocalV5LogoIdentity] = []
    tokens: dict[str, str] = {}
    for item in manifest["assets"]:
        if item["asset_class"] == "REQUIRED_PAGE_MEDIA":
            authorization = item["authorization_identity"]
            identity = PerformanceLocalV5MediaIdentity(
                requirement_id=item["requirement_id"],
                placement_key=item["placement_key"],
                target_component_instance_key=item["target_component_instance_key"],
                assignment_id=item["assignment_id"],
                assignment_version=item["assignment_version"],
                image_metadata_id=item["governed_asset_id"],
                media_key=item["media_key"],
                media_version=item["media_version"],
                source_filename=item["source_filename"],
                source_mime_type=item["mime_type"],
                source_width=item["width"],
                source_height=item["height"],
                checksum_sha256=item["sha256"],
                authorization_id=authorization["id"],
                authorization_version=authorization["version"],
                authorization_fingerprint=authorization["fingerprint_sha256"],
            )
            page_media.append(identity)
            tokens[item["placement_key"]] = deployer._prepared_token(
                "page_requirement", item["requirement_id"], item["source_filename"]
            )
        else:
            identity = PerformanceLocalV5LogoIdentity(
                role=item["placement_key"],
                target_component_instance_key=item["target_component_instance_key"],
                assignment_id=item["assignment_id"],
                assignment_version=item["assignment_version"],
                brand_asset_id=item["governed_asset_id"],
                asset_key=item["asset_key"],
                asset_version=item["asset_version"],
                checksum_sha256=item["sha256"],
                source_filename=item["source_filename"],
                source_mime_type=item["mime_type"],
                source_width=item["width"],
                source_height=item["height"],
                governed_asset_url=f"atlas-governed://brand-asset/{item['governed_asset_id']}",
            )
            logos.append(identity)
            tokens[item["placement_key"]] = deployer._prepared_token(
                "brand_role", item["placement_key"], item["source_filename"]
            )

    bindings = PerformanceLocalV5SourceBindings(
        generated_page_revision_id=64,
        generated_page_revision_hash="1" * 64,
        page_composition_id=41,
        composition_version=10,
        page_composition_revision_id=122,
        page_composition_revision_hash="2" * 64,
        composition_source_hash="3" * 64,
        qa_result_id=136,
        qa_result_hash="4" * 64,
    )
    template = {
        "schema_version": "project-atlas-performance-local-v5-wordpress@1",
        "surface": "city_service",
        "rehearsal_only": True,
        "payload_identity": {
            "fixture_key": "city_service",
            "source_page": "generated-page:41",
            "source_composition": "composition:41:v10",
            "source_hash": bindings.composition_source_hash,
            "frozen_inputs": [
                {"path": "atlas/planned-page/41", "sha256": "5" * 64},
                {
                    "path": deployer.MAPPING_FROZEN_PATH,
                    "sha256": deployer.PREPARED_MAPPING_SHA256,
                },
            ],
        },
        "page": {
            "title": "Drywood Termite Tenting in Orlando, FL",
            "slug": "drywood-termite-tenting-orlando-fl",
        },
        "website": {
            "identity": "website:1",
            "header_logo": {"src": tokens["header_logo"]},
            "footer_logo": {"src": tokens["footer_logo"]},
        },
        "hero": {"media": {"src": tokens["city-service-hero"]}},
        "numeric_tokens": {"fractional": 1.5, "preserved_zero": 16.0},
        "sections": [
            {
                "key": "why_it_matters",
                "media": {"src": tokens["city-service-process"]},
            },
            {
                "key": "what_to_look_for",
                "media": {"src": tokens["city-service-evidence"]},
            },
            {"key": "how_service_works", "media": None},
            {"key": "preparing_the_property", "media": None},
            {"key": "coordinated_service", "media": None},
            {"key": "final_conversion", "media": None},
        ],
        "footer": {"logo": {"src": tokens["footer_logo"]}},
    }
    preparation = {
        "website_id": 1,
        "planned_page_id": 41,
        "generated_page_id": 41,
        "wordpress_post_id": 8,
        "metadata_key": "_project_atlas_performance_local_v5_v1",
        "payload_schema": "project-atlas-performance-local-v5-wordpress@1",
        "payload_template": template,
        "source_bindings": bindings.model_dump(mode="json"),
        "required_media": [item.model_dump(mode="json") for item in page_media],
        "required_logo_media": [item.model_dump(mode="json") for item in logos],
    }
    return PerformanceLocalV5PreparedPayload(
        website_id=1,
        planned_page_id=41,
        generated_page_id=41,
        wordpress_post_id=8,
        metadata_key="_project_atlas_performance_local_v5_v1",
        payload_schema="project-atlas-performance-local-v5-wordpress@1",
        payload_template=template,
        template_sha256=performance_local_v5_payload_sha256(template),
        preparation_sha256=performance_local_v5_payload_sha256(preparation),
        source_bindings=bindings,
        required_media=page_media,
        required_logo_media=logos,
    )


def _script_config(script: str) -> dict:
    match = re.search(r"const CONFIG = (\{.*\});\nconst RESULT_NAME", script, re.DOTALL)
    assert match is not None
    return json.loads(match.group(1))


NODE_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const {webcrypto, randomUUID, createHash} = require("node:crypto");
process.on("unhandledRejection", () => {});
const source = fs.readFileSync(process.argv[2], "utf8");
const match = source.match(/const CONFIG = (\{.*\});\nconst RESULT_NAME/s);
if (!match) throw new Error("generated CONFIG not found");
const CONFIG = JSON.parse(match[1]);

function canonical(value) {
  if (value === null) return "null";
  if (value === true) return "true";
  if (value === false) return "false";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" && Number.isSafeInteger(value)) return String(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  throw new Error("unsupported canonical value");
}
function sha(value) { return createHash("sha256").update(value).digest("hex"); }
function imageDimensions(bytes, mime) {
  const data = Buffer.from(bytes);
  if (mime === "image/png") return {width: data.readUInt32BE(16), height: data.readUInt32BE(20)};
  if (mime === "image/webp" && data.toString("ascii", 12, 16) === "VP8 ") {
    return {width: data.readUInt16LE(26) & 0x3fff, height: data.readUInt16LE(28) & 0x3fff};
  }
  throw new Error("unsupported disposable image");
}

const corePage = {id: CONFIG.wordpress_post_id, type: "page", status: "publish", slug: CONFIG.expected_post.slug, title: {raw: CONFIG.expected_post.title}, content: {raw: "Protected body"}, excerpt: {raw: "Protected excerpt"}, featured_media: 41, author: 1, parent: 0, menu_order: 0, template: ""};
const remote = {media: [], payload: null, payloadCanonical: null, mediaWrites: 0, metadataWrites: 0, metadataPostCalls: 0, apiCalls: 0, mode: "normal", coreReads: 0, dimensionReads: 0};
function atlasIdentity() {
  if (!remote.payload) return null;
  return {
    website_id: Number(remote.payload.website.identity.split(":")[1]),
    generated_page_id: Number(remote.payload.payload_identity.source_page.split(":")[1]),
    source_composition: remote.payload.payload_identity.source_composition,
    source_sha256: remote.payload.payload_identity.source_hash,
  };
}
async function apiFetch(options) {
  remote.apiCalls += 1;
  if (options.path === `/wp/v2/pages/${CONFIG.wordpress_post_id}?context=edit` && options.method === "GET") {
    remote.coreReads += 1;
    const value = JSON.parse(JSON.stringify(corePage));
    if (remote.mode === "core-race" && remote.coreReads === 2) value.content.raw += " raced";
    return value;
  }
  if (options.path === CONFIG.private_route && options.method === "GET") {
    const digest = remote.payloadCanonical === null ? null : sha(remote.payloadCanonical);
    const inspection = {
      route_schema: "project-atlas-performance-local-v5-page-payload-route@1",
      metadata_bridge_version: CONFIG.expected_bridge_version,
      environment_type: "staging", blog_public: 0,
      home: CONFIG.expected_origin, siteurl: CONFIG.expected_origin,
      post_id: CONFIG.wordpress_post_id, post_type: CONFIG.expected_post.type,
      post_status: CONFIG.expected_post.status, post_title: CONFIG.expected_post.title,
      post_slug: CONFIG.expected_post.slug, metadata_exists: remote.payload !== null,
      metadata_sha256: digest, metadata_valid: remote.payload !== null,
      atlas_identity: atlasIdentity(),
    };
    if (remote.mode === "production-env") inspection.environment_type = "production";
    if (remote.mode === "wrong-post-identity") inspection.post_id = 9;
    if (remote.mode === "unexpected-metadata") { inspection.metadata_sha256 = "f".repeat(64); inspection.metadata_valid = true; }
    if (remote.mode === "inconsistent-absent") { inspection.metadata_exists = false; inspection.metadata_sha256 = "f".repeat(64); inspection.metadata_valid = false; inspection.atlas_identity = null; }
    return inspection;
  }
  if (options.path.startsWith("/wp/v2/media?") && options.method === "GET") {
    let records = remote.media.map(item => item.record);
    if (remote.mode === "ambiguous-media" && records.length) records = [...records, {...records[0], id: 999}];
    if (remote.mode === "unsafe-media-url" && records.length) records = [{...records[0], source_url: "https://evil.example.invalid/asset.webp"}, ...records.slice(1)];
    return {ok: true, json: async () => records, headers: {get: name => name.toLowerCase() === "x-wp-totalpages" && remote.mode !== "missing-pagination" ? "1" : null}};
  }
  if (options.path === "/wp/v2/media" && options.method === "POST") {
    const file = options.body.get("file");
    const bytes = Buffer.from(await file.arrayBuffer());
    const dimensions = imageDimensions(bytes, file.type);
    const id = 100 + remote.media.length;
    const filename = file.name;
    const sourceUrl = `${CONFIG.expected_origin}/wp-content/uploads/2026/08/${filename}`;
    const record = {id, source_url: sourceUrl, mime_type: file.type, slug: filename.replace(/\.[^.]+$/, ""), media_details: dimensions};
    remote.media.push({record, bytes}); remote.mediaWrites += 1;
    return record;
  }
  if (options.path === CONFIG.private_route && options.method === "POST") {
    remote.metadataPostCalls += 1;
    if (typeof options.body !== "string" || options.headers["Content-Type"] !== "application/json") throw new Error("raw JSON body contract changed");
    const envelope = JSON.parse(options.body);
    const payloadPrefix = '"payload":';
    const payloadStart = options.body.indexOf(payloadPrefix);
    const payloadEnd = options.body.lastIndexOf(`,"planned_page_id":${CONFIG.planned_page_id},"request_identity":`);
    if (payloadStart < 0 || payloadEnd <= payloadStart + payloadPrefix.length) throw new Error("raw canonical payload boundary changed");
    const payloadCanonical = options.body.slice(payloadStart + payloadPrefix.length, payloadEnd);
    if (JSON.stringify(JSON.parse(payloadCanonical)) !== JSON.stringify(envelope.payload)) throw new Error("raw canonical payload value changed");
    const digest = sha(payloadCanonical);
    const unchanged = remote.payloadCanonical !== null && remote.payloadCanonical === payloadCanonical;
    if (!unchanged) { remote.payload = envelope.payload; remote.payloadCanonical = payloadCanonical; remote.metadataWrites += 1; }
    return {route_schema: "project-atlas-performance-local-v5-page-payload-route@1", status: unchanged ? "UNCHANGED" : "APPLIED", post_id: CONFIG.wordpress_post_id, prior_sha256: unchanged ? digest : null, resulting_sha256: digest, website_id: CONFIG.website_id, planned_page_id: CONFIG.planned_page_id, generated_page_id: CONFIG.generated_page_id, request_identity: envelope.request_identity, metadata_valid: true, metadata_bridge_version: CONFIG.expected_bridge_version};
  }
  throw new Error(`unexpected apiFetch ${options.method} ${options.path}`);
}

async function remoteFetch(value) {
  const url = new URL(value);
  if (url.pathname === CONFIG.frontend_path) {
    return {ok: true, url: url.href, text: async () => "<html><body>safe rendered page</body></html>"};
  }
  const media = remote.media.find(item => item.record.source_url === url.href);
  if (!media) return {ok: false, url: url.href, headers: {get: () => null}, arrayBuffer: async () => new ArrayBuffer(0)};
  return {
    ok: true, url: url.href,
    headers: {get: name => name.toLowerCase() === "content-type" ? (remote.mode === "remote-wrong-mime" ? "image/png" : media.record.mime_type) : name.toLowerCase() === "content-length" ? String(media.bytes.length) : null},
    arrayBuffer: async () => media.bytes.buffer.slice(media.bytes.byteOffset, media.bytes.byteOffset + media.bytes.byteLength),
  };
}

function browserContext(mode, completed, blocked) {
  remote.mode = mode; remote.coreReads = 0; remote.dimensionReads = 0;
  const exactTarget = mode !== "wrong-origin";
  const location = exactTarget
    ? {origin: CONFIG.expected_origin, hostname: "www.staging3.drywoodtenting.com", pathname: "/wp-admin/post.php", search: "?post=8&action=edit"}
    : {origin: "https://www.drywoodtenting.com", hostname: "www.drywoodtenting.com", pathname: "/wp-admin/post.php", search: "?post=8&action=edit"};
  if (mode === "wrong-page") location.search = "?post=9&action=edit";
  const window = {isSecureContext: true, location};
  window.window = window;
  window.wp = mode === "missing-api" ? {} : {apiFetch};
  window.prompt = () => mode === "decline" ? "DECLINED" : CONFIG.activation_phrase;
  window.open = () => mode === "popup-blocked" ? null : ({location: {href: "about:blank"}});
  class FakeDOMParser {
    parseFromString() {
      const payload = window.__atlasFinalizedPayload;
      const media = payload.sections.filter(value => value.media).map(value => value.media.src);
      const one = new Set(["[data-project-atlas-v5-root]", "h1", "header.performanceLocalHeader", "section.performanceLocalHero", ".performanceLocalV5StickyPhoneBar", ".performanceLocalV5StickyActionBanner", "form[data-atlas-v5-inert-form]", "footer.performanceLocalFooter", "header", "footer"]);
      return {querySelectorAll: selector => one.has(selector) ? [{}] : [], querySelector: () => ({}), images: media.map(src => ({src: CONFIG.expected_origin + src}))};
    }
  }
  const document = {body: {appendChild() {}}, createElement: () => ({hidden: false, click() {}, remove() {}})};
  const localConsole = {
    info: (label, result) => { if (String(label).includes("COMPLETE")) completed(result); },
    error: (label, result) => { if (String(label).includes("BLOCKED")) blocked(result); },
  };
  return vm.createContext({
    window, location, document, navigator: {locks: {request: async (_name, _options, callback) => callback({})}},
    console: localConsole, crypto: {subtle: webcrypto.subtle, randomUUID}, TextEncoder, TextDecoder,
    Uint8Array, ArrayBuffer, Blob, FormData, URL, URLSearchParams, DOMParser: FakeDOMParser,
    atob, fetch: remoteFetch, setTimeout: callback => { callback(); return 0; },
    createImageBitmap: async blob => {remote.dimensionReads += 1; const bytes = Buffer.from(await blob.arrayBuffer()); const value = imageDimensions(bytes, blob.type); if (remote.mode === "remote-wrong-dimensions" && remote.dimensionReads > CONFIG.assets.length) value.width += 1; return {...value, close() {}};},
  });
}

async function execute(mode = "normal") {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`timeout in ${mode}`)), 30000);
    const finish = value => {clearTimeout(timer); resolve(value);};
    const context = browserContext(mode, result => finish({kind: "complete", result}), result => finish({kind: "blocked", result}));
    let executable = source;
    if (mode === "tampered-manifest") executable = source.replace(CONFIG.accepted_media_manifest.base64, "A" + CONFIG.accepted_media_manifest.base64.slice(1));
    if (mode === "tampered-asset") executable = source.replace(CONFIG.assets[0].mapping.expected_sha256, "0".repeat(64));
    if (mode === "tampered-template") executable = source.replace(JSON.stringify(CONFIG.payload_template_canonical), JSON.stringify(CONFIG.payload_template_canonical.replace(CONFIG.expected_post.title, CONFIG.expected_post.title + " tampered")));
    if (mode === "tampered-embedded-base64") executable = source.replace(CONFIG.assets[0].base64, (CONFIG.assets[0].base64[0] === "A" ? "B" : "A") + CONFIG.assets[0].base64.slice(1));
    if (mode === "missing-config-asset") executable = source.replace(JSON.stringify(CONFIG.assets[0]) + ",", "");
    if (mode === "unknown-config-asset") { const extra = {...CONFIG.assets[0], upload_filename: "unknown-extra.webp"}; executable = source.replace(JSON.stringify(CONFIG.assets.at(-1)) + "]", JSON.stringify(CONFIG.assets.at(-1)) + "," + JSON.stringify(extra) + "]"); }
    if (mode === "tampered-mime") executable = source.replace(CONFIG.assets[0].mapping.expected_mime_type, "image/png");
    if (mode === "tampered-dimensions") executable = source.replace(`\"expected_width\":${CONFIG.assets[0].mapping.expected_width}`, `\"expected_width\":${CONFIG.assets[0].mapping.expected_width + 1}`);
    if (mode === "incomplete-map") executable = source.replace(CONFIG.mapping_schema, CONFIG.mapping_schema + "-tampered");
    if (mode === "invalid-payload" || mode === "private-payload") {
      const changed = mode === "invalid-payload" ? CONFIG.payload_template_canonical.replace(CONFIG.payload_schema, "invalid-schema") : CONFIG.payload_template_canonical.replace(`{`, `{\"recipient_email\":\"private@example.invalid\",`);
      executable = source.replace(JSON.stringify(CONFIG.payload_template_canonical), JSON.stringify(changed)).replace(CONFIG.payload_template_sha256, sha(changed));
    }
    vm.runInContext(executable, context, {filename: "deploy-page41-v5.js"});
  });
}

(async () => {
  const first = await execute();
  if (first.kind !== "complete") throw new Error(JSON.stringify(first));
  const second = await execute();
  if (second.kind !== "complete") throw new Error(JSON.stringify(second));
  const beforeFailures = {mediaWrites: remote.mediaWrites, metadataWrites: remote.metadataWrites, metadataPostCalls: remote.metadataPostCalls};
  const wrongOrigin = await execute("wrong-origin");
  const wrongPage = await execute("wrong-page");
  const missingApi = await execute("missing-api");
  const missingPagination = await execute("missing-pagination");
  const inconsistentAbsent = await execute("inconsistent-absent");
  const productionEnv = await execute("production-env");
  const wrongPostIdentity = await execute("wrong-post-identity");
  const ambiguousMedia = await execute("ambiguous-media");
  const unsafeMediaUrl = await execute("unsafe-media-url");
  const tamperedManifest = await execute("tampered-manifest");
  const tamperedAsset = await execute("tampered-asset");
  const tamperedTemplate = await execute("tampered-template");
  const tamperedEmbeddedBase64 = await execute("tampered-embedded-base64");
  const missingConfigAsset = await execute("missing-config-asset");
  const unknownConfigAsset = await execute("unknown-config-asset");
  const remoteWrongMime = await execute("remote-wrong-mime");
  const remoteWrongDimensions = await execute("remote-wrong-dimensions");
  const tamperedMime = await execute("tampered-mime");
  const tamperedDimensions = await execute("tampered-dimensions");
  const incompleteMap = await execute("incomplete-map");
  const invalidPayload = await execute("invalid-payload");
  const privatePayload = await execute("private-payload");
  const unexpectedMetadata = await execute("unexpected-metadata");
  const coreRace = await execute("core-race");
  const declined = await execute("decline");
  const popupBlocked = await execute("popup-blocked");
  const afterFailures = {mediaWrites: remote.mediaWrites, metadataWrites: remote.metadataWrites, metadataPostCalls: remote.metadataPostCalls};
  process.stdout.write(JSON.stringify({first: first.result, second: second.result, wrongOrigin: wrongOrigin.result, wrongPage: wrongPage.result, missingApi: missingApi.result, missingPagination: missingPagination.result, inconsistentAbsent: inconsistentAbsent.result, productionEnv: productionEnv.result, wrongPostIdentity: wrongPostIdentity.result, ambiguousMedia: ambiguousMedia.result, unsafeMediaUrl: unsafeMediaUrl.result, tamperedManifest: tamperedManifest.result, tamperedAsset: tamperedAsset.result, tamperedTemplate: tamperedTemplate.result, tamperedEmbeddedBase64: tamperedEmbeddedBase64.result, missingConfigAsset: missingConfigAsset.result, unknownConfigAsset: unknownConfigAsset.result, remoteWrongMime: remoteWrongMime.result, remoteWrongDimensions: remoteWrongDimensions.result, tamperedMime: tamperedMime.result, tamperedDimensions: tamperedDimensions.result, incompleteMap: incompleteMap.result, invalidPayload: invalidPayload.result, privatePayload: privatePayload.result, unexpectedMetadata: unexpectedMetadata.result, coreRace: coreRace.result, declined: declined.result, popupBlocked: popupBlocked.result, beforeFailures, afterFailures, mediaCount: remote.media.length, mediaWrites: remote.mediaWrites, metadataWrites: remote.metadataWrites, metadataPostCalls: remote.metadataPostCalls}));
})().catch(error => {console.error(error); process.exitCode = 1;});
"""


def test_generated_deployer_first_and_second_runs_are_exact_and_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepared = _prepared_payload()
    monkeypatch.setattr(
        deployer,
        "prepare_performance_local_v5_staging_payload",
        lambda _session, page_id: prepared if page_id == 41 else None,
    )
    output = tmp_path / "one-shot"
    built = deployer.build_deployer(
        _ReadOnlySession(),
        package_dir=ACCEPTED_PACKAGE,
        output_dir=output,
        created_at=datetime(2026, 8, 31, 20, 0, tzinfo=UTC),
    )
    script_path = output / "deploy-page41-v5.js"
    script = script_path.read_text(encoding="utf-8")
    config = _script_config(script)

    assert built["status"] == "BUILT"
    assert config["media_count"] == 5
    assert config["embedded_media_bytes"] == 2_791_091
    assert config["expected_bridge_version"] == "0.57.11"
    assert config["expected_origin"] == "https://www.staging3.drywoodtenting.com"
    assert config["accepted_media_manifest"]["bytes"] == 13_746
    assert (
        config["accepted_media_manifest"]["sha256"]
        == "0518e440f5b2232bb2e1617a4085c04db055c1ffd6be8285681236257007912d"
    )
    assert len(config["assets"]) == 5
    assert sum(item["bytes"] for item in config["assets"]) == 2_791_091
    assert "__ATLAS_CONFIG_JSON__" not in script
    serialized_config = json.dumps(config, sort_keys=True, separators=(",", ":"))
    assert '"recipient_email":' not in serialized_config
    assert '"from_email":' not in serialized_config
    assert '"smtp_' not in serialized_config
    assert '"application_password":' not in serialized_config

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable; generated-browser runtime proof is environment-specific.")

    syntax = subprocess.run(
        [node, "--check", str(script_path)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert syntax.returncode == 0, syntax.stderr

    harness_path = tmp_path / "browser-harness.cjs"
    harness_path.write_text(NODE_HARNESS, encoding="utf-8", newline="\n")
    rehearsal = subprocess.run(
        [node, str(harness_path), str(script_path)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert rehearsal.returncode == 0, rehearsal.stderr
    observed = json.loads(rehearsal.stdout)

    first = observed["first"]
    second = observed["second"]
    assert first["deployment_status"] == "COMPLETE"
    assert first["post_result"]["status"] == "APPLIED"
    assert len(first["attachments_created"]) == 5
    assert first["attachments_reused"] == []
    assert second["deployment_status"] == "COMPLETE"
    assert second["post_result"]["status"] == "UNCHANGED"
    assert second["attachments_created"] == []
    assert len(second["attachments_reused"]) == 5
    assert first["payload_sha256"] == second["payload_sha256"]
    assert first["verified_media_mapping_sha256"] == second["verified_media_mapping_sha256"]
    assert observed["mediaCount"] == 5
    assert observed["mediaWrites"] == 5
    assert observed["metadataWrites"] == 1
    assert observed["metadataPostCalls"] == 2
    assert observed["wrongOrigin"]["blocker"] == "WRONG_BROWSER_TARGET"
    assert observed["wrongPage"]["blocker"] == "WRONG_BROWSER_TARGET"
    assert observed["missingApi"]["blocker"] == "WP_API_FETCH_MISSING"
    assert observed["missingPagination"]["blocker"] == "MEDIA_PAGINATION_INVALID"
    assert observed["inconsistentAbsent"]["blocker"] == "STAGING_METADATA_STATE_INVALID"
    assert observed["productionEnv"]["blocker"] == "STAGING_INSPECTION_MISMATCH"
    assert observed["wrongPostIdentity"]["blocker"] == "STAGING_INSPECTION_MISMATCH"
    assert observed["ambiguousMedia"]["blocker"] == "AMBIGUOUS_EXACT_MEDIA"
    assert observed["unsafeMediaUrl"]["blocker"] == "UNSAFE_MEDIA_URL"
    assert observed["tamperedManifest"]["blocker"] == "EMBEDDED_MANIFEST_HASH_MISMATCH"
    assert observed["tamperedAsset"]["blocker"] == "EMBEDDED_MANIFEST_ASSET_MISMATCH"
    assert observed["tamperedTemplate"]["blocker"] == "PAYLOAD_TEMPLATE_HASH_MISMATCH"
    assert observed["tamperedEmbeddedBase64"]["blocker"] == "EMBEDDED_MEDIA_HASH_MISMATCH"
    assert observed["missingConfigAsset"]["blocker"] == "EMBEDDED_MANIFEST_ASSET_SET_MISMATCH"
    assert observed["unknownConfigAsset"]["blocker"] == "EMBEDDED_MANIFEST_ASSET_SET_MISMATCH"
    assert observed["remoteWrongMime"]["blocker"] == "EXISTING_METADATA_WITH_MISSING_MEDIA"
    assert observed["remoteWrongDimensions"]["blocker"] == "EXISTING_METADATA_WITH_MISSING_MEDIA"
    assert observed["tamperedMime"]["blocker"] == "EMBEDDED_MANIFEST_ASSET_MISMATCH"
    assert observed["tamperedDimensions"]["blocker"] == "EMBEDDED_MANIFEST_ASSET_MISMATCH"
    assert observed["incompleteMap"]["blocker"] == "INVALID_FINAL_PAYLOAD"
    assert observed["invalidPayload"]["blocker"] == "INVALID_FINAL_PAYLOAD"
    assert observed["privatePayload"]["blocker"] == "PRIVATE_DATA_IN_PUBLIC_PAYLOAD"
    assert observed["unexpectedMetadata"]["blocker"] == "REMOTE_METADATA_CONFLICT"
    assert observed["coreRace"]["blocker"] == "CORE_PAGE_FIELDS_CHANGED"
    assert observed["declined"]["blocker"] == "OPERATOR_DECLINED"
    assert observed["popupBlocked"]["blocker"] == "REVIEW_WINDOW_BLOCKED"
    assert observed["beforeFailures"] == observed["afterFailures"]

    entries = []
    for asset, result in zip(config["assets"], first["media"], strict=True):
        entries.append(
            {
                **asset["mapping"],
                "wordpress_attachment_id": result["wordpress_attachment_id"],
                "wordpress_original_url": result["wordpress_original_url"],
                "observed_sha256": result["observed_sha256"],
                "observed_mime_type": result["observed_mime_type"],
                "observed_width": result["observed_width"],
                "observed_height": result["observed_height"],
            }
        )
    mapping_value = {
        "mapping_schema": config["mapping_schema"],
        "context": {
            "website_id": config["website_id"],
            "planned_page_id": config["planned_page_id"],
            "generated_page_id": config["generated_page_id"],
            "wordpress_post_id": config["wordpress_post_id"],
            "staging_origin": config["expected_origin"],
            "source_bindings": config["source_bindings"],
        },
        "entries": entries,
    }
    finalized = finalize_performance_local_v5_staging_payload(
        prepared,
        mapping_value,
        expected_staging_origin=config["expected_origin"],
    )
    mapping = PerformanceLocalV5VerifiedMediaMap.model_validate(mapping_value)
    normalized = mapping.model_copy(
        update={
            "entries": sorted(
                mapping.entries,
                key=lambda entry: (
                    (0, entry.requirement_id or 0, entry.governed_asset_id)
                    if entry.governed_asset_class == "page_media"
                    else (
                        1,
                        0 if entry.placement_key == "header_logo" else 1,
                        entry.governed_asset_id,
                    )
                ),
            )
        }
    )
    assert finalized.payload_sha256 == first["payload_sha256"]
    assert (
        performance_local_v5_payload_sha256(normalized.model_dump(mode="json"))
        == first["verified_media_mapping_sha256"]
    )
    assert all(
        item["wordpress_original_url"].startswith(
            "https://www.staging3.drywoodtenting.com/wp-content/uploads/2026/08/"
        )
        for item in first["media"]
    )


def test_generator_rejects_existing_output_directory_without_overwrite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prepared = _prepared_payload()
    monkeypatch.setattr(
        deployer,
        "prepare_performance_local_v5_staging_payload",
        lambda _session, _page_id: prepared,
    )
    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "preserved.txt"
    marker.write_text("preserve", encoding="utf-8")

    try:
        deployer.build_deployer(
            _ReadOnlySession(), package_dir=ACCEPTED_PACKAGE, output_dir=output
        )
    except FileExistsError:
        pass
    else:
        raise AssertionError("the append-only output boundary accepted an existing directory")

    assert marker.read_text(encoding="utf-8") == "preserve"
    assert sorted(path.name for path in output.iterdir()) == ["preserved.txt"]
