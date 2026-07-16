from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import inspect

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.main import app
from app.models import (
    WordPressActivationAudit,
    WordPressDeploymentAudit,
    WordPressDeploymentTransition,
    WordPressMetadataState,
)
from app.schemas.wordpress import (
    WordPressActivationApplyRequest,
    WordPressActivationPreflightRequest,
    WordPressDeploymentBackupEvidence,
)
from app.services import wordpress_activation as activation
from app.services import wordpress_deployment as deployment
from app.services.wordpress_rendered_state import build_manual_browser_evidence


KEY = "v0.59.51-local-activation-test-signing-key-more-than-32-bytes"
VERSION = "v0.59.48"
COMMIT = "9" * 40
MANIFEST = "8" * 64
SOURCE_COMPATIBILITY = "project-atlas-release-identity-v0.59.55"
PAGE_HASH = "4" * 64
MEDIA31_HASH = "6" * 64
MEDIA32_HASH = "2" * 64

HTML = """<!doctype html><html><head>
<title>Drywood Termite Tenting in Orlando, FL – My WordPress</title>
<link rel="canonical" href="https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/">
</head><body><h1 class="wp-block-post-title">Drywood Termite Tenting in Orlando, FL</h1>
<img class="wp-post-image" src="https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png" alt="Two-story Orlando Florida home professionally covered for drywood termite tenting">
<h2>Drywood Termite Tenting in Orlando, Florida</h2><p>Visible copy.</p></body></html>"""


@pytest.fixture(autouse=True)
def clear_handles(monkeypatch):
    activation._clear_activation_handles()
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    yield
    activation._clear_activation_handles()


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'activation.sqlite3').as_posix()}")
    SQLModel.metadata.create_all(engine)
    return engine


def evidence(**changes):
    value = build_manual_browser_evidence(
        HTML,
        final_url="https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/",
        evidence_identifier="orlando-v0-59-51-activation-test",
        signing_key=KEY,
    )
    value.update(changes)
    return value


def proof():
    return WordPressDeploymentBackupEvidence(
        atlas_data_backup_file="atlas-backup-2026-07-16-031142.json",
        atlas_media_backup_file="atlas-media-backup-2026-07-16-031143.zip",
        atlas_program_backup_file="atlas-program-backup-2026-07-16-031147.zip",
        wordpress_backup_method="SiteGround on-demand full-site backup",
        wordpress_backup_reference="Atlas Backup",
        wordpress_backup_completed_at=datetime.now(UTC) - timedelta(hours=1),
        wordpress_database_included_attestation=True,
        wordpress_plugins_included_attestation=True,
        wordpress_restore_capability_attestation=True,
        confirmer_identity="Shawn Manchette",
        php_error_log_findings="No findings",
        observed_write_summary="No relevant WordPress change after backup",
        manual_browser_evidence=evidence(),
    )


def inactive_observation():
    plugins = [
        {"plugin": "project-atlas-metadata-bridge/project-atlas-metadata-bridge", "version": deployment.PLUGIN_VERSION, "status": "inactive"},
        {"plugin": "safe/example", "version": "1.0", "status": "active"},
    ]
    active_plugins = ["safe/example"]
    return {
        "plugins": plugins,
        "active_plugins": active_plugins,
        "plugin_inventory_hash": activation._hash(plugins),
        "active_plugin_inventory_hash": activation._hash(active_plugins),
        "page": {"id": 8, "status": "publish", "slug": "drywood-termite-tenting-orlando-fl", "link": "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/", "featured_media": 31},
        "page_snapshot_hash": PAGE_HASH,
        "page_body_hash": deployment.EXPECTED_CORRECTED_BODY_HASH,
        "page_body_begins_expected_h2": True,
        "page_title": "Drywood Termite Tenting in Orlando, FL",
        "page_excerpt": "Locked excerpt",
        "page_canonical": "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/",
        "media31": {"id": 31},
        "media31_snapshot_hash": MEDIA31_HASH,
        "media32": {"id": 32, "post": None},
        "media32_snapshot_hash": MEDIA32_HASH,
        "site": {"name": "My WordPress", "description": ""},
        "rendered": {
            "verified": True,
            "signature_validated": True,
            "h1": ["Drywood Termite Tenting in Orlando, FL"],
            "head_hash": "a" * 64,
            "visible_hash": "b" * 64,
            "atlas_metadata_marker_present": False,
            "media32_reference_present": False,
            "metadata_inventory": {"meta_descriptions": [], "open_graph": [], "twitter": [], "json_ld": [], "atlas_ownership_markers": []},
            "cache_headers": {},
        },
        "page_references_media32": False,
        "cache_headers": {},
        "wordpress_request_performed": True,
        "wordpress_request_methods": ["GET"],
        "read_only": True,
    }


def active_observation():
    value = deepcopy(inactive_observation())
    value["plugins"][0]["status"] = "active"
    value["active_plugins"] = sorted([*value["active_plugins"], value["plugins"][0]["plugin"]])
    value["plugin_inventory_hash"] = activation._hash(value["plugins"])
    value["active_plugin_inventory_hash"] = activation._hash(value["active_plugins"])
    return value


def artifact():
    return {
        "atlas_version": VERSION,
        "atlas_commit": COMMIT,
        "atlas_tag": VERSION,
        "release_manifest_sha256": MANIFEST,
        "release_source_compatibility_id": SOURCE_COMPATIBILITY,
        "release_runtime_identity_verified": True,
        "release_manifest_integrity_verified": True,
        "release_expected_identity_matched": True,
        "plugin_source_sha256": deployment.SOURCE_SHA256,
    }


def seed(session, *, status="verified", completion="installed_inactive_reconciliation"):
    p = proof()
    audit = WordPressDeploymentAudit(
        id=1,
        generated_page_id=41,
        wordpress_post_id=8,
        action_type="install_metadata_bridge",
        status=status,
        operator="Shawn Manchette",
        shawn_approved_at=datetime.now(UTC) - timedelta(hours=2),
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
        backup_completed_at=p.wordpress_backup_completed_at,
        backup_deadline=p.wordpress_backup_completed_at + timedelta(hours=4),
        authorization_jti="1" * 32,
        deployment_key="2" * 64,
        backup_evidence=p.model_dump(mode="json"),
        pre_snapshot={"cache_headers": {}},
        post_snapshot={"inactive_metadata_safety": {"verification_source": "corroborated_inactive_inventory_atlas_rows_and_rendered_absence", "direct_payload_or_revision_claimed": False}, "reconciliation_cache_purge_count": 0},
        evidence_summary={"completion_mode": completion},
        evidence_directory="docs/deployment-records/wordpress/orlando-page-8/2026/2026-07-15/v0.59-install",
    )
    session.add(audit)
    session.commit()
    for previous, new, suffix in ((None, "installation_authorized", "a"), ("installation_authorized", "awaiting_manual_installation", "b"), ("awaiting_manual_installation", "verified", "c")):
        session.add(WordPressDeploymentTransition(audit_id=1, previous_state=previous, new_state=new, actor="Shawn Manchette", reason="locked history", request_identifier=suffix * 32))
    session.commit()


def request(observed=None, **changes):
    observed = observed or inactive_observation()
    p = proof().model_dump(mode="json")
    value = {
        **p,
        "installation_audit_id": 1,
        "operator": "Shawn Manchette",
        "expected_plugin_slug": deployment.PLUGIN_SLUG,
        "expected_plugin_path": deployment.PLUGIN_FILE,
        "expected_plugin_version": deployment.PLUGIN_VERSION,
        "expected_zip_sha256": deployment.ZIP_SHA256,
        "expected_plugin_inventory_hash": observed["plugin_inventory_hash"],
        "expected_active_plugin_inventory_hash": observed["active_plugin_inventory_hash"],
        "expected_page_snapshot_hash": PAGE_HASH,
        "expected_body_hash": deployment.EXPECTED_CORRECTED_BODY_HASH,
        "expected_media31_snapshot_hash": MEDIA31_HASH,
        "expected_media32_snapshot_hash": MEDIA32_HASH,
        "expected_runtime_identity": {"atlas_version": VERSION, "atlas_commit": COMMIT, "atlas_tag": VERSION, "manifest_sha256": MANIFEST, "source_compatibility_id": SOURCE_COMPATIBILITY},
        "repository_head": COMMIT,
        "repository_origin_main": COMMIT,
        "repository_tag": VERSION,
        "repository_working_tree_clean": True,
        "protected_paths_unchanged": True,
        "no_relevant_wordpress_change_after_backup": True,
        "browser_console_findings": "No findings",
    }
    value.update(changes)
    return WordPressActivationPreflightRequest(**value)


def configure(monkeypatch, before=None):
    before = before or inactive_observation()
    monkeypatch.setattr(activation, "_observe", lambda session, proof: deepcopy(before))
    monkeypatch.setattr(activation, "_verify_artifact", lambda: (artifact(), [activation._gate("release_identity", "release", True, "")]))
    monkeypatch.setattr(activation, "_backup_gates", lambda proof: [activation._gate("backups", "backups", True, "")])
    return before


def test_activation_routes_are_distinct_and_post_only():
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert ("/api/wordpress/deployment/metadata-bridge/activation/preflight/{page_id}", "POST") in routes
    assert ("/api/wordpress/deployment/metadata-bridge/activation/apply/{page_id}", "POST") in routes


def test_preflight_is_zero_write_and_returns_bound_handle(monkeypatch, db):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        result = activation.activation_preflight(session, 41, request(before))
        assert result.status == "activation_preflight_ready"
        assert result.activation_preflight_ready and result.activation_handle
        assert result.confirmation_phrase == activation.ACTIVATION_PHRASE
        assert result.wordpress_write_count == result.atlas_write_count == 0
        assert result.token_issued is result.nonce_consumed is result.activation_audit_created is False
        assert len(result.activation_handle_fingerprint) == 64
        assert result.expected_post_plugin_inventory_hash == active_observation()["plugin_inventory_hash"]
        assert session.exec(select(WordPressActivationAudit)).first() is None


def test_apply_uses_one_activation_write_and_finalizes_audit(monkeypatch, db):
    before = configure(monkeypatch)
    calls = {"observe": 0, "activate": 0}
    def observe(session, proof):
        calls["observe"] += 1
        return deepcopy(before if calls["observe"] <= 2 else active_observation())
    def activate_plugin(session):
        calls["activate"] += 1
        pending = session.exec(select(WordPressActivationAudit)).one()
        assert pending.status == "pending" and pending.wordpress_write_count == 0
        return {"plugin": deployment.PLUGIN_FILE.removesuffix(".php"), "status": "active", "version": deployment.PLUGIN_VERSION}
    monkeypatch.setattr(activation, "_observe", observe)
    monkeypatch.setattr(activation, "_activate_plugin", activate_plugin)
    monkeypatch.setattr(activation, "_read_plugin_status", lambda session: {"active": True, "snapshot": {"rendering_enabled": False, "enabled_metadata_state": False, "payload": None, "payload_hash": "", "revision": "0"}})
    with Session(db) as session:
        seed(session)
        preflight = activation.activation_preflight(session, 41, request(before))
        result = activation.apply_activation(session, 41, WordPressActivationApplyRequest(activation_handle=preflight.activation_handle, confirmation_phrase=preflight.confirmation_phrase))
        assert result.status == "verified"
        assert result.wordpress_write_count == 1 and result.atlas_write_count == 2
        assert calls == {"observe": 3, "activate": 1}
        saved = session.get(WordPressActivationAudit, result.activation_audit_id)
        assert saved.status == "verified" and saved.transition_history == ["pending", "verified"]
        assert session.get(WordPressDeploymentAudit, 1).status == "verified"


def test_handle_is_single_use(monkeypatch, db):
    before = configure(monkeypatch)
    monkeypatch.setattr(activation, "_activate_plugin", lambda session: {"_error": "simulated"})
    with Session(db) as session:
        seed(session)
        p = activation.activation_preflight(session, 41, request(before))
        req = WordPressActivationApplyRequest(activation_handle=p.activation_handle, confirmation_phrase=p.confirmation_phrase)
        activation.apply_activation(session, 41, req)
        with pytest.raises(HTTPException, match="unknown, expired, consumed"):
            activation.apply_activation(session, 41, req)


def test_wrong_phrase_does_not_consume_handle(monkeypatch, db):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        p = activation.activation_preflight(session, 41, request(before))
        with pytest.raises(HTTPException, match="phrase"):
            activation.apply_activation(session, 41, WordPressActivationApplyRequest(activation_handle=p.activation_handle, confirmation_phrase="WRONG"))
        assert p.activation_handle in activation._handles


@pytest.mark.parametrize("mutation,failed_code", [
    ({"repository_working_tree_clean": False}, "repository_clean"),
    ({"protected_paths_unchanged": False}, "protected_paths"),
    ({"no_relevant_wordpress_change_after_backup": False}, "no_post_backup_change"),
    ({"expected_plugin_version": "0.57.3"}, "authorized_artifact"),
    ({"expected_page_snapshot_hash": "f" * 64}, "page_snapshot"),
    ({"expected_media31_snapshot_hash": "f" * 64}, "media31"),
])
def test_preflight_drift_blocks_without_writes(monkeypatch, db, mutation, failed_code):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        result = activation.activation_preflight(session, 41, request(before, **mutation))
        assert not result.activation_preflight_ready and result.activation_handle is None
        assert failed_code in {gate.code for gate in result.gate_results if not gate.passed}
        assert session.exec(select(WordPressActivationAudit)).first() is None


def test_already_active_and_duplicate_plugin_block(monkeypatch, db):
    for observed, code in ((active_observation(), "plugin_inactive"), (inactive_observation(), "plugin_singleton")):
        if code == "plugin_singleton":
            observed["plugins"].append(deepcopy(observed["plugins"][0]))
            observed["plugin_inventory_hash"] = activation._hash(observed["plugins"])
        configure(monkeypatch, observed)
        with Session(db) as session:
            seed(session)
            result = activation.activation_preflight(session, 41, request(observed))
            assert code in {gate.code for gate in result.gate_results if not gate.passed}
            session.rollback()
            for row in list(session.exec(select(WordPressDeploymentTransition))): session.delete(row)
            session.delete(session.get(WordPressDeploymentAudit, 1)); session.commit()


def test_metadata_state_blocks_preflight(monkeypatch, db):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        session.add(WordPressMetadataState(generated_page_id=41, wordpress_post_id=8, status="applied", payload={}, payload_hash="a" * 64, wordpress_revision="1"))
        session.commit()
        result = activation.activation_preflight(session, 41, request(before))
        assert "metadata_rows" in {gate.code for gate in result.gate_results if not gate.passed}


def test_missing_or_tampered_evidence_blocks_before_observation(monkeypatch, db):
    before = configure(monkeypatch)
    calls = {"observe": 0}
    monkeypatch.setattr(activation, "_observe", lambda session, proof: calls.__setitem__("observe", 1) or deepcopy(before))
    for supplied in (None, {**evidence(), "rendered_head_hash": "f" * 64}):
        with Session(db) as session:
            seed(session)
            result = activation.activation_preflight(session, 41, request(before, manual_browser_evidence=supplied))
            assert "evidence_contract" in {gate.code for gate in result.gate_results if not gate.passed}
            assert result.wordpress_write_count == result.atlas_write_count == 0
            for row in list(session.exec(select(WordPressDeploymentTransition))): session.delete(row)
            session.delete(session.get(WordPressDeploymentAudit, 1)); session.commit()
    assert calls["observe"] == 0


def test_unverified_installation_audit_blocks(monkeypatch, db):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session, status="verification_failed")
        result = activation.activation_preflight(session, 41, request(before))
        assert "installation_audit" in {gate.code for gate in result.gate_results if not gate.passed}


def test_expired_backup_cannot_issue_handle(monkeypatch, db):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        result = activation.activation_preflight(
            session,
            41,
            request(before, wordpress_backup_completed_at=datetime.now(UTC) - timedelta(hours=5)),
        )
        assert not result.activation_preflight_ready and result.activation_handle is None
        assert "activation_handle_lifetime" in {gate.code for gate in result.gate_results if not gate.passed}


def test_rendering_or_site_identity_drift_blocks(monkeypatch, db):
    for observed, code in ((inactive_observation(), "rendering_disabled"), (inactive_observation(), "site_identity")):
        if code == "rendering_disabled":
            observed["rendered"]["atlas_metadata_marker_present"] = True
        else:
            observed["site"]["name"] = "Changed"
        configure(monkeypatch, observed)
        with Session(db) as session:
            seed(session)
            result = activation.activation_preflight(session, 41, request(observed))
            assert code in {gate.code for gate in result.gate_results if not gate.passed}
            for row in list(session.exec(select(WordPressDeploymentTransition))): session.delete(row)
            session.delete(session.get(WordPressDeploymentAudit, 1)); session.commit()


def test_post_activation_drift_is_recorded_without_rollback(monkeypatch, db):
    before = configure(monkeypatch)
    after = active_observation(); after["page_snapshot_hash"] = "f" * 64
    calls = {"observe": 0, "activate": 0}
    def observe(session, proof):
        calls["observe"] += 1
        return deepcopy(before if calls["observe"] <= 2 else after)
    monkeypatch.setattr(activation, "_observe", observe)
    monkeypatch.setattr(activation, "_activate_plugin", lambda session: calls.__setitem__("activate", calls["activate"] + 1) or {"status": "active"})
    monkeypatch.setattr(activation, "_read_plugin_status", lambda session: {"active": True, "snapshot": {"rendering_enabled": False, "enabled_metadata_state": False, "payload": None, "payload_hash": "", "revision": "0"}})
    with Session(db) as session:
        seed(session)
        p = activation.activation_preflight(session, 41, request(before))
        result = activation.apply_activation(session, 41, WordPressActivationApplyRequest(activation_handle=p.activation_handle, confirmation_phrase=p.confirmation_phrase))
        assert result.status == "verification_failed" and result.further_action_required
        assert calls["activate"] == 1
        assert "page_snapshot" in {gate.code for gate in result.gate_results if not gate.passed}


def test_activation_write_transport_is_narrow_and_metadata_unreachable():
    source = inspect.getsource(activation._activate_plugin)
    assert "client.post" in source
    assert 'json={"status": "active"}' in source
    assert "/wp-json/wp/v2/plugins/project-atlas-metadata-bridge/project-atlas-metadata-bridge" in source
    for forbidden in ("metadata/apply", "pages/8", "media/31", "purge", "DELETE", "PUT", "PATCH"):
        assert forbidden not in source


def test_expired_handle_fails(monkeypatch, db):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        p = activation.activation_preflight(session, 41, request(before))
        entry = activation._handles[p.activation_handle]
        activation._handles[p.activation_handle] = activation._ActivationHandleEntry(entry.request, entry.binding_hash, entry.issued_at, datetime.now(UTC) - timedelta(seconds=1))
        with pytest.raises(HTTPException, match="expired"):
            activation.apply_activation(session, 41, WordPressActivationApplyRequest(activation_handle=p.activation_handle, confirmation_phrase=p.confirmation_phrase))
