from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.main import app
from app.models import (
    WordPressDeploymentAudit,
    WordPressDeploymentNonce,
    WordPressDeploymentTransition,
)
from app.schemas.wordpress import (
    WordPressDeploymentBackupEvidence,
    WordPressDeploymentReconciliationApplyRequest,
    WordPressDeploymentReconciliationVerifyRequest,
)
from app.services import wordpress_deployment as deployment
from app.services.wordpress_rendered_state import acquire_rendered_state, build_manual_browser_evidence


KEY = "v0.59.48-local-test-signing-key-with-more-than-32-bytes"
VERSION = "v0.59.48"
COMMIT = "e" * 40
MANIFEST = "d" * 64
SOURCE_COMPATIBILITY = "project-atlas-release-identity-v0.59.54"
PLUGIN_INVENTORY = "9" * 64
ACTIVE_INVENTORY = "8" * 64
LIVE_ACTIVE_INVENTORY = "9e2d39fce63cd085dc6da2df89bc2a1016c2ad298f86a570c0a8136f4eeaa862"
PAGE_SNAPSHOT = "4" * 64
MEDIA31_SNAPSHOT = "6" * 64
MEDIA32_SNAPSHOT = "2" * 64

HTML = """<!doctype html><html><head>
<title>Drywood Termite Tenting in Orlando, FL – My WordPress</title>
<link rel="canonical" href="https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/">
</head><body><h1 class="wp-block-post-title">Drywood Termite Tenting in Orlando, FL</h1>
<img class="wp-post-image" src="https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png" alt="Two-story Orlando Florida home professionally covered for drywood termite tenting">
<h2>Drywood Termite Tenting in Orlando, Florida</h2><p>Visible copy.</p></body></html>"""


@pytest.fixture(autouse=True)
def clear_handles():
    deployment._clear_reconciliation_handles()
    yield
    deployment._clear_reconciliation_handles()


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'reconcile.sqlite3').as_posix()}")
    SQLModel.metadata.create_all(engine)
    return engine


def evidence(**changes):
    value = build_manual_browser_evidence(
        HTML,
        final_url="https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/",
        evidence_identifier="orlando-v0-59-46-test",
        signing_key=KEY,
    )
    value.update(changes)
    return value


def request(**changes):
    value = {
        "audit_id": 1,
        "manual_browser_evidence": evidence(),
        "expected_plugin_slug": deployment.PLUGIN_SLUG,
        "expected_plugin_path": deployment.PLUGIN_FILE,
        "expected_plugin_version": deployment.PLUGIN_VERSION,
        "expected_zip_sha256": deployment.ZIP_SHA256,
        "expected_plugin_inventory_hash": PLUGIN_INVENTORY,
        "expected_active_plugin_inventory_hash": ACTIVE_INVENTORY,
        "expected_page_snapshot_hash": PAGE_SNAPSHOT,
        "expected_body_hash": deployment.EXPECTED_CORRECTED_BODY_HASH,
        "expected_media31_snapshot_hash": MEDIA31_SNAPSHOT,
        "expected_media32_snapshot_hash": MEDIA32_SNAPSHOT,
        "expected_runtime_identity": {
            "atlas_version": VERSION,
            "atlas_commit": COMMIT,
            "atlas_tag": VERSION,
            "manifest_sha256": MANIFEST,
            "source_compatibility_id": SOURCE_COMPATIBILITY,
        },
    }
    value.update(changes)
    return WordPressDeploymentReconciliationVerifyRequest(**value)


def artifact(**changes):
    value = {
        "atlas_version": VERSION,
        "atlas_commit": COMMIT,
        "atlas_tag": VERSION,
        "release_manifest_sha256": MANIFEST,
        "release_source_compatibility_id": SOURCE_COMPATIBILITY,
        "release_runtime_identity_verified": True,
        "release_manifest_integrity_verified": True,
        "release_expected_identity_matched": True,
        "plugin_slug": deployment.PLUGIN_SLUG,
        "plugin_path": deployment.PLUGIN_FILE,
        "plugin_version": deployment.PLUGIN_VERSION,
        "zip_sha256": deployment.ZIP_SHA256,
        "plugin_source_sha256": deployment.SOURCE_SHA256,
    }
    value.update(changes)
    return value


def observed(**changes):
    inventory = {
        "plugins": [{"plugin": deployment.PLUGIN_FILE.removesuffix(".php"), "version": deployment.PLUGIN_VERSION, "status": "inactive"}],
        "active_plugins": [],
        "plugin_inventory_hash": PLUGIN_INVENTORY,
        "active_plugin_inventory_hash": ACTIVE_INVENTORY,
        "page": {"id": 8, "status": "publish", "slug": "drywood-termite-tenting-orlando-fl", "link": "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/", "featured_media": 31},
        "page_snapshot_hash": PAGE_SNAPSHOT,
        "page_body_hash": deployment.EXPECTED_CORRECTED_BODY_HASH,
        "page_title": "Drywood Termite Tenting in Orlando, FL",
        "page_excerpt": "",
        "page_canonical": "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/",
        "media31": {"id": 31, "post": 8, "source_url": "https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png"},
        "media31_snapshot_hash": MEDIA31_SNAPSHOT,
        "media32": {"id": 32, "post": 0, "source_url": "https://example.test/media32.png"},
        "media32_snapshot_hash": MEDIA32_SNAPSHOT,
        "site": {"name": "My WordPress", "description": ""},
        "rendered": {
            "verified": True,
            "source": "manual_browser_evidence",
            "outcome": "manual_browser_evidence_verified",
            "signature_validated": True,
            "evidence_schema_version": 1,
            "browser_evidence_identifier": "orlando-v0-59-46-test",
            "h1": ["Drywood Termite Tenting in Orlando, FL"],
            "canonical": ["https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/"],
            "featured_image_url": "https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png",
            "featured_image_alt": "Two-story Orlando Florida home professionally covered for drywood termite tenting",
            "head_hash": "a" * 64,
            "visible_hash": "b" * 64,
            "metadata_inventory": {"meta_descriptions": [], "open_graph": [], "twitter": [], "json_ld": [], "media32_references": [], "unexpected_metadata_owners": [], "duplicates": []},
            "atlas_metadata_marker_present": False,
            "media32_reference_present": False,
            "cache_headers": {},
        },
        "page_references_media32": False,
        "cache_headers": {},
        "wordpress_request_performed": True,
        "wordpress_request_methods": ["GET"],
        "read_only": True,
    }
    value = {**inventory, **changes}
    return value


def backup():
    return WordPressDeploymentBackupEvidence(
        atlas_data_backup_file="atlas-backup-2026-07-15-120000.json",
        atlas_media_backup_file="atlas-media-backup-2026-07-15-120000.zip",
        atlas_program_backup_file="atlas-program-backup-2026-07-15-120000.zip",
        wordpress_backup_method="SiteGround on-demand full-site backup",
        wordpress_backup_reference="Atlas Backup",
        wordpress_backup_completed_at=datetime.now(UTC) - timedelta(hours=8),
        wordpress_database_included_attestation=True,
        wordpress_plugins_included_attestation=True,
        wordpress_restore_capability_attestation=True,
        confirmer_identity="Shawn Manchette",
        php_error_log_findings="No findings",
        observed_write_summary="Manual installation and guarded deactivation recorded externally",
    )


def seed(session: Session, *, status="awaiting_manual_installation", nonce=True, transitions=True):
    proof = backup()
    audit = WordPressDeploymentAudit(
        id=1,
        generated_page_id=41,
        wordpress_post_id=8,
        action_type="install_metadata_bridge",
        status=status,
        operator="Shawn Manchette",
        shawn_approved_at=datetime.now(UTC) - timedelta(hours=8),
        confirmation_phrase_hash="a" * 64,
        atlas_version=VERSION,
        atlas_commit=COMMIT,
        atlas_tag=VERSION,
        plugin_version=deployment.PLUGIN_VERSION,
        plugin_slug=deployment.PLUGIN_SLUG,
        plugin_path=deployment.PLUGIN_FILE,
        zip_file_name=deployment.ZIP_NAME,
        zip_sha256=deployment.ZIP_SHA256,
        plugin_source_sha256=deployment.SOURCE_SHA256,
        backup_reference="Atlas Backup",
        backup_completed_at=proof.wordpress_backup_completed_at,
        backup_deadline=proof.wordpress_backup_completed_at + timedelta(hours=4),
        authorization_jti="1" * 32,
        deployment_key="2" * 64,
        backup_evidence=proof.model_dump(mode="json"),
        pre_snapshot={"active_plugin_inventory_hash": ACTIVE_INVENTORY, "cache_headers": {}},
        evidence_directory="docs/deployment-records/wordpress/orlando-page-8/2026/2026-07-15/v0.59-install",
    )
    session.add(audit)
    session.commit()
    if nonce:
        session.add(WordPressDeploymentNonce(jti="1" * 32, token_fingerprint="3" * 64, action_type="install_metadata_bridge", audit_id=1))
    if transitions:
        session.add(WordPressDeploymentTransition(audit_id=1, previous_state=None, new_state="installation_authorized", actor="Shawn Manchette", reason="authorized", request_identifier="4" * 32))
        session.add(WordPressDeploymentTransition(audit_id=1, previous_state="installation_authorized", new_state="awaiting_manual_installation", actor="Shawn Manchette", reason="awaiting", request_identifier="5" * 32))
    session.commit()
    return audit


def mock_inspection(monkeypatch, state=None, release=None):
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    monkeypatch.setattr(deployment, "_verify_artifact", lambda: (release or artifact(), [deployment._gate("program_root", "root", True, ""), deployment._gate("artifact_hash", "hash", True, ""), deployment._gate("artifact_portable", "portable", True, ""), deployment._gate("release_identity", "release", True, "")]))
    monkeypatch.setattr(deployment, "_observe", lambda *_: state or observed())


@pytest.mark.parametrize(
    ("raw", "posix", "extensionless"),
    [
        ("project-atlas-metadata-bridge/project-atlas-metadata-bridge", "project-atlas-metadata-bridge/project-atlas-metadata-bridge", True),
        (deployment.PLUGIN_FILE, deployment.PLUGIN_FILE, False),
        (r"project-atlas-metadata-bridge\project-atlas-metadata-bridge", "project-atlas-metadata-bridge/project-atlas-metadata-bridge", True),
        (r"project-atlas-metadata-bridge\project-atlas-metadata-bridge.php", deployment.PLUGIN_FILE, False),
    ],
)
def test_locked_plugin_identifier_normalizes_without_changing_raw(raw, posix, extensionless):
    identity = deployment._normalize_plugin_identifier(raw)
    assert identity.valid
    assert identity.raw_identifier == raw
    assert identity.posix_identifier == posix
    assert identity.plugin_directory == identity.plugin_slug == deployment.PLUGIN_SLUG
    assert identity.authorized_entry_path == deployment.PLUGIN_FILE
    assert identity.extensionless_rest_identifier is extensionless


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "/project-atlas-metadata-bridge/project-atlas-metadata-bridge",
        "project-atlas-metadata-bridge/project-atlas-metadata-bridge/",
        "project-atlas-metadata-bridge//project-atlas-metadata-bridge",
        "project-atlas-metadata-bridge/../project-atlas-metadata-bridge",
        "../project-atlas-metadata-bridge/project-atlas-metadata-bridge",
        r"C:\project-atlas-metadata-bridge\project-atlas-metadata-bridge",
        "project-atlas-metadata-bridge/\x00project-atlas-metadata-bridge",
        "project-atlas-metadata-bridge/project atlas metadata bridge",
        " project-atlas-metadata-bridge/project-atlas-metadata-bridge",
    ],
)
def test_malformed_plugin_identifiers_fail_closed(raw):
    identity = deployment._normalize_plugin_identifier(raw)
    assert not identity.valid
    assert identity.raw_identifier == raw
    assert identity.authorized_entry_path is None


@pytest.mark.parametrize(
    "raw",
    [
        "project-atlas-metadata-bridge/different-entry",
        "project-atlas-metadata-bridge/different-entry.php",
        "project-atlas-metadata-bridge-extra/project-atlas-metadata-bridge",
        "unrelated/unrelated",
        "single-file-plugin",
    ],
)
def test_unrelated_identifiers_are_not_rewritten_to_the_authorized_entry(raw):
    identity = deployment._normalize_plugin_identifier(raw)
    assert identity.valid
    assert identity.raw_identifier == raw
    assert identity.authorized_entry_path is None


def test_normalized_matching_preserves_raw_inventory_and_hash_definitions():
    plugins = [
        {"plugin": "project-atlas-metadata-bridge/project-atlas-metadata-bridge", "version": deployment.PLUGIN_VERSION, "status": "inactive"},
        {"plugin": "sg-security/sg-security", "version": "1.6.5", "status": "active"},
    ]
    before = json.loads(json.dumps(plugins))
    before_hash = deployment._hash(plugins)
    matches = deployment._matching_reconciliation_plugins(plugins)
    assert matches == [plugins[0]]
    assert plugins == before
    assert deployment._hash(plugins) == before_hash
    raw_active = ["sg-ai-studio/sg-ai-studio", "sg-cachepress/sg-cachepress", "sg-security/sg-security", "wordpress-starter/siteground-wizard"]
    assert deployment._hash(raw_active) == LIVE_ACTIVE_INVENTORY


def test_real_extensionless_rest_shape_reaches_ready_with_corroborated_safety(monkeypatch, db):
    state = observed()
    raw_plugins = json.loads(json.dumps(state["plugins"]))
    mock_inspection(monkeypatch, state=state)
    with Session(db) as session:
        seed(session)
        result = deployment.verify_install_reconciliation(session, 41, request())
    gates = {gate.code: gate for gate in result.gate_results}
    assert result.reconciliation_ready
    assert gates["plugin_singleton"].passed
    assert gates["plugin_inactive"].passed
    assert gates["plugin_version"].passed
    assert gates["inactive_safety_corroboration"].passed
    assert state["plugins"] == raw_plugins
    assert result.wordpress_write_count == result.atlas_write_count == 0
    safety = result.inspected_state["inactive_metadata_safety"]
    assert safety["private_option_directly_read"] is False
    assert safety["direct_payload_or_revision_claimed"] is False


@pytest.mark.parametrize(
    "duplicate_identifier",
    [
        deployment.PLUGIN_FILE,
        r"project-atlas-metadata-bridge\project-atlas-metadata-bridge",
        r"project-atlas-metadata-bridge\project-atlas-metadata-bridge.php",
    ],
)
def test_ambiguous_normalized_plugin_identities_fail_singleton(monkeypatch, db, duplicate_identifier):
    state = observed()
    state["plugins"].append({"plugin": duplicate_identifier, "version": deployment.PLUGIN_VERSION, "status": "inactive"})
    mock_inspection(monkeypatch, state=state)
    with Session(db) as session:
        seed(session)
        result = deployment.verify_install_reconciliation(session, 41, request())
    gates = {gate.code: gate for gate in result.gate_results}
    assert not result.reconciliation_ready
    assert not gates["plugin_singleton"].passed
    assert not gates["inactive_safety_corroboration"].passed


@pytest.mark.parametrize(
    "malformed_identifier",
    [
        "/project-atlas-metadata-bridge/project-atlas-metadata-bridge",
        "project-atlas-metadata-bridge/../project-atlas-metadata-bridge",
        "project-atlas-metadata-bridge/\x00project-atlas-metadata-bridge",
        "project-atlas-metadata-bridge/",
        "project-atlas-metadata-bridge/different-entry",
    ],
)
def test_malformed_or_similar_live_inventory_cannot_match(monkeypatch, db, malformed_identifier):
    state = observed()
    state["plugins"][0]["plugin"] = malformed_identifier
    mock_inspection(monkeypatch, state=state)
    with Session(db) as session:
        seed(session)
        result = deployment.verify_install_reconciliation(session, 41, request())
    gates = {gate.code: gate for gate in result.gate_results}
    assert not result.reconciliation_ready
    assert not gates["plugin_singleton"].passed
    assert not gates["plugin_inactive"].passed
    assert not gates["plugin_version"].passed
    assert not gates["inactive_safety_corroboration"].passed


def test_successful_verify_and_phrase_gated_atlas_only_apply(monkeypatch, db):
    mock_inspection(monkeypatch)
    with Session(db) as session:
        seed(session)
        before = json.dumps(session.get(WordPressDeploymentNonce, 1).model_dump(mode="json"), sort_keys=True)
        verification = deployment.verify_install_reconciliation(session, 41, request())
        assert verification.reconciliation_ready and verification.reconciliation_handle
        assert verification.wordpress_write_count == verification.atlas_write_count == 0
        assert verification.confirmation_phrase == deployment.RECONCILIATION_PHRASE
        assert session.get(WordPressDeploymentAudit, 1).status == "awaiting_manual_installation"
        result = deployment.apply_install_reconciliation(session, 41, WordPressDeploymentReconciliationApplyRequest(reconciliation_handle=verification.reconciliation_handle, confirmation_phrase=deployment.RECONCILIATION_PHRASE))
        audit = session.get(WordPressDeploymentAudit, 1)
        assert result.status == audit.status == "verified"
        assert result.wordpress_write_count == 0 and result.atlas_write_count == 2
        assert audit.evidence_summary["completion_mode"] == "installed_inactive_reconciliation"
        assert audit.evidence_summary["reconciliation"]["wordpress_write_count"] == 0
        assert json.dumps(session.get(WordPressDeploymentNonce, 1).model_dump(mode="json"), sort_keys=True) == before
        assert result.state_history == ["installation_authorized", "awaiting_manual_installation", "verified"]


def test_reconciliation_handle_is_single_use_and_raw_install_token_is_never_returned(monkeypatch, db):
    mock_inspection(monkeypatch)
    with Session(db) as session:
        seed(session)
        verification = deployment.verify_install_reconciliation(session, 41, request())
        encoded = json.dumps(verification.model_dump(mode="json"))
        assert "confirmation_token" not in encoded and "authorization_jti" not in encoded
        apply_request = WordPressDeploymentReconciliationApplyRequest(reconciliation_handle=verification.reconciliation_handle, confirmation_phrase=deployment.RECONCILIATION_PHRASE)
        deployment.apply_install_reconciliation(session, 41, apply_request)
        with pytest.raises(HTTPException):
            deployment.apply_install_reconciliation(session, 41, apply_request)


def test_restart_and_expiry_invalidate_handles(monkeypatch, db):
    mock_inspection(monkeypatch)
    with Session(db) as session:
        seed(session)
        handle = deployment.verify_install_reconciliation(session, 41, request()).reconciliation_handle
        deployment._clear_reconciliation_handles()
        with pytest.raises(HTTPException):
            deployment.apply_install_reconciliation(session, 41, WordPressDeploymentReconciliationApplyRequest(reconciliation_handle=handle, confirmation_phrase=deployment.RECONCILIATION_PHRASE))
        expired = deployment._ReconciliationHandleEntry(request=request(), binding_hash="a" * 64, issued_at=datetime.now(UTC) - timedelta(minutes=20), expires_at=datetime.now(UTC) - timedelta(minutes=10))
        deployment._reconciliation_handles["x" * 43] = expired
        with pytest.raises(HTTPException):
            deployment._consume_reconciliation_handle("x" * 43)


def test_wrong_phrase_does_not_finalize(monkeypatch, db):
    mock_inspection(monkeypatch)
    with Session(db) as session:
        seed(session)
        handle = deployment.verify_install_reconciliation(session, 41, request()).reconciliation_handle
        with pytest.raises(HTTPException):
            deployment.apply_install_reconciliation(session, 41, WordPressDeploymentReconciliationApplyRequest(reconciliation_handle=handle, confirmation_phrase="WRONG"))
        assert session.get(WordPressDeploymentAudit, 1).status == "awaiting_manual_installation"


@pytest.mark.parametrize(
    ("mutation", "gate"),
    [
        ("plugin_absent", "plugin_singleton"),
        ("plugin_active", "plugin_inactive"),
        ("plugin_duplicate", "plugin_singleton"),
        ("plugin_version", "plugin_version"),
        ("plugin_inventory", "plugin_inventory"),
        ("active_inventory", "active_inventory"),
        ("page_snapshot", "page_snapshot"),
        ("body", "body_hash"),
        ("media31", "media31"),
        ("media32", "media32"),
        ("site", "site_identity"),
        ("rendering", "metadata_absent"),
        ("metadata", "metadata_absent"),
        ("media32_rendered", "media32"),
        ("wrong_h1", "rendered_h1"),
        ("evidence_invalid", "rendered_evidence"),
    ],
)
def test_observation_drift_blocks(monkeypatch, db, mutation, gate):
    state = observed()
    if mutation == "plugin_absent": state["plugins"] = []
    elif mutation == "plugin_active": state["plugins"][0]["status"] = "active"
    elif mutation == "plugin_duplicate": state["plugins"].append(dict(state["plugins"][0]))
    elif mutation == "plugin_version": state["plugins"][0]["version"] = "0.57.3"
    elif mutation == "plugin_inventory": state["plugin_inventory_hash"] = "0" * 64
    elif mutation == "active_inventory": state["active_plugin_inventory_hash"] = "0" * 64
    elif mutation == "page_snapshot": state["page_snapshot_hash"] = "0" * 64
    elif mutation == "body": state["page_body_hash"] = "0" * 64
    elif mutation == "media31": state["media31_snapshot_hash"] = "0" * 64
    elif mutation == "media32": state["media32_snapshot_hash"] = "0" * 64
    elif mutation == "site": state["site"]["name"] = "Changed"
    elif mutation == "rendering": state["rendered"]["atlas_metadata_marker_present"] = True
    elif mutation == "metadata": state["rendered"]["metadata_inventory"]["meta_descriptions"] = [{"content": "unexpected"}]
    elif mutation == "media32_rendered": state["rendered"]["media32_reference_present"] = True
    elif mutation == "wrong_h1": state["rendered"]["h1"] = ["Wrong"]
    elif mutation == "evidence_invalid": state["rendered"]["signature_validated"] = False
    mock_inspection(monkeypatch, state=state)
    with Session(db) as session:
        seed(session)
        result = deployment.verify_install_reconciliation(session, 41, request())
        gates = {item.code: item for item in result.gate_results}
        assert not result.reconciliation_ready and not gates[gate].passed


@pytest.mark.parametrize("condition", ["wrong_status", "missing_nonce", "history_drift", "metadata_state", "metadata_audit"])
def test_atlas_state_drift_blocks(monkeypatch, db, condition):
    mock_inspection(monkeypatch)
    with Session(db) as session:
        seed(session, status="failed" if condition == "wrong_status" else "awaiting_manual_installation", nonce=condition != "missing_nonce")
        if condition == "history_drift":
            session.add(WordPressDeploymentTransition(audit_id=1, previous_state="awaiting_manual_installation", new_state="failed", actor="unexpected", reason="drift", request_identifier="6" * 32))
            session.commit()
        if condition == "metadata_state":
            from app.models import WordPressMetadataState
            session.add(WordPressMetadataState(generated_page_id=41, wordpress_post_id=8))
            session.commit()
        if condition == "metadata_audit":
            from app.models import WordPressMetadataSyncAudit
            session.add(WordPressMetadataSyncAudit(generated_page_id=41, wordpress_post_id=8, action_type="test", status="pending", wordpress_site_url="https://example.test", payload_hash="a" * 64, payload_snapshot={}, gate_results=[], data_backup_file_name="test.json", wordpress_backup_reference="test", plugin_version=deployment.PLUGIN_VERSION))
            session.commit()
        result = deployment.verify_install_reconciliation(session, 41, request())
        assert not result.reconciliation_ready


@pytest.mark.parametrize("change", ["path", "zip", "runtime"])
def test_request_and_runtime_binding_mismatch_blocks(monkeypatch, db, change):
    req = request()
    release = artifact()
    if change == "path": req.expected_plugin_path = "wrong/plugin.php"
    elif change == "zip": req.expected_zip_sha256 = "0" * 64
    else: release["atlas_commit"] = "0" * 40
    mock_inspection(monkeypatch, release=release)
    with Session(db) as session:
        seed(session)
        result = deployment.verify_install_reconciliation(session, 41, req)
        assert not result.reconciliation_ready


def test_final_verification_drift_consumes_handle_without_atlas_or_wordpress_write(monkeypatch, db):
    state = observed()
    mock_inspection(monkeypatch, state=state)
    with Session(db) as session:
        seed(session)
        verification = deployment.verify_install_reconciliation(session, 41, request())
        state["plugin_inventory_hash"] = "0" * 64
        with pytest.raises(HTTPException):
            deployment.apply_install_reconciliation(session, 41, WordPressDeploymentReconciliationApplyRequest(reconciliation_handle=verification.reconciliation_handle, confirmation_phrase=deployment.RECONCILIATION_PHRASE))
        assert session.get(WordPressDeploymentAudit, 1).status == "awaiting_manual_installation"
        assert len(deployment._transition_records(session, 1)) == 2
        with pytest.raises(HTTPException):
            deployment._consume_reconciliation_handle(verification.reconciliation_handle)


def test_deployment_transport_has_no_wordpress_write_path():
    source = deployment.apply_install_reconciliation.__code__.co_names
    assert "_request" not in source
    with pytest.raises(RuntimeError):
        deployment._request("https://example.test", "user", "password", "POST", "/wp-json/wp/v2/plugins")


def test_reconciliation_routes_are_distinct_and_no_mutation_route_exists():
    routes = {(route.path, method) for route in app.routes for method in (getattr(route, "methods", None) or set())}
    prefix = "/api/wordpress/deployment/metadata-bridge/install/reconciliation/"
    assert (prefix + "verify/{page_id}", "POST") in routes
    assert (prefix + "apply/{page_id}", "POST") in routes
    assert not any(term in path.removeprefix(prefix) for path, _ in routes if prefix in path for term in ("activate", "deactivate", "upload", "delete", "purge", "restore"))


def test_generic_public_403_uses_fresh_signed_schema_v1_evidence():
    browser = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403, request=request, text="generic forbidden")), follow_redirects=False)
    result = acquire_rendered_state("operator", "process-only", manual_evidence=evidence(), evidence_signing_key=KEY, client=browser)
    browser.close()
    assert result["verified"] and result["source"] == "manual_browser_evidence"
    assert result["evidence_schema_version"] == 1 and result["signature_validated"] is True


@pytest.mark.parametrize("failure", ["missing", "expired", "signature", "schema", "url"])
def test_fresh_evidence_contract_failures_block_before_wordpress_reads(monkeypatch, db, failure):
    req_values = request().model_dump(mode="json")
    if failure == "missing":
        req_values.pop("manual_browser_evidence")
        with pytest.raises(Exception):
            WordPressDeploymentReconciliationVerifyRequest(**req_values)
        return
    if failure == "expired":
        req_values["manual_browser_evidence"] = build_manual_browser_evidence(HTML, final_url="https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/", evidence_identifier="expired-evidence", signing_key=KEY, captured_at=datetime.now(UTC) - timedelta(minutes=16))
    elif failure == "signature":
        req_values["manual_browser_evidence"]["helper_signature"] = "0" * 64
    elif failure == "schema":
        duplicate = HTML.replace("<h2>Drywood Termite Tenting in Orlando, Florida</h2>", '<div class="wp-block-post-content"><h1>Drywood Termite Tenting in Orlando, Florida</h1></div>')
        req_values["manual_browser_evidence"] = build_manual_browser_evidence(duplicate, final_url="https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/", evidence_identifier="schema-v2", signing_key=KEY, schema_version=2)
    else:
        req_values["manual_browser_evidence"]["final_url"] = "https://example.test/wrong/"
    req = WordPressDeploymentReconciliationVerifyRequest(**req_values)
    calls = []
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    monkeypatch.setattr(deployment, "_verify_artifact", lambda: (artifact(), [deployment._gate("release_identity", "release", True, "")]))
    monkeypatch.setattr(deployment, "_observe", lambda *_: calls.append("observed") or observed())
    with Session(db) as session:
        seed(session)
        result = deployment.verify_install_reconciliation(session, 41, req)
        assert not result.reconciliation_ready
        assert not {gate.code: gate for gate in result.gate_results}["evidence_contract"].passed
        assert calls == []


def test_plugin_file_cache_and_wordpress_method_drift_block(monkeypatch, db):
    cases = [
        (observed(), artifact(plugin_source_sha256="0" * 64), "artifact_source"),
        ({**observed(), "cache_headers": {"age": "1"}}, artifact(), "cache_boundary"),
        ({**observed(), "wordpress_request_methods": ["GET", "POST"]}, artifact(), "read_only_transport"),
    ]
    for index, (state, release, failed_gate) in enumerate(cases, start=1):
        engine = create_engine(f"sqlite:///{db.url.database}.{index}")
        SQLModel.metadata.create_all(engine)
        mock_inspection(monkeypatch, state=state, release=release)
        with Session(engine) as session:
            seed(session)
            result = deployment.verify_install_reconciliation(session, 41, request())
            assert not result.reconciliation_ready
            assert not {gate.code: gate for gate in result.gate_results}[failed_gate].passed
