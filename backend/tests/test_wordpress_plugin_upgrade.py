from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import inspect

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.main import app
from app.db import backup as backup_service
from app.models import (
    WordPressActivationAudit,
    WordPressDeploymentAudit,
    WordPressMetadataLifecycleAudit,
    WordPressMetadataState,
    WordPressPluginUpgradeAudit,
)
from app.schemas.wordpress import (
    WordPressDeploymentBackupEvidence,
    WordPressPluginUpgradeApplyRequest,
    WordPressPluginUpgradePreflightRequest,
)
from app.services import wordpress_deployment as deployment
from app.services import wordpress_plugin_upgrade as upgrade
from app.services.wordpress_rendered_state import build_manual_browser_evidence


KEY = "v0.59.55-upgrade-test-signing-key-longer-than-thirty-two-bytes"
VERSION = "v0.59.54"
COMMIT = "5" * 40
MANIFEST = "4" * 64
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
    upgrade._clear_upgrade_handles()
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    yield
    upgrade._clear_upgrade_handles()


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'upgrade.sqlite3').as_posix()}")
    SQLModel.metadata.create_all(engine)
    return engine


def evidence(**changes):
    value = build_manual_browser_evidence(
        HTML,
        final_url="https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/",
        evidence_identifier="orlando-v0-59-55-upgrade",
        signing_key=KEY,
    )
    value.update(changes)
    return value


def observation(version=upgrade.CURRENT_VERSION):
    plugins = [
        {"plugin": "project-atlas-metadata-bridge/project-atlas-metadata-bridge", "version": version, "status": "active"},
        {"plugin": "safe/example", "version": "1.0", "status": "active"},
    ]
    active = sorted(item["plugin"] for item in plugins)
    return {
        "plugins": plugins,
        "active_plugins": active,
        "plugin_inventory_hash": upgrade._hash(plugins),
        "active_plugin_inventory_hash": upgrade._hash(active),
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
            "verified": True, "signature_validated": True,
            "h1": ["Drywood Termite Tenting in Orlando, FL"],
            "head_hash": "a" * 64, "visible_hash": "b" * 64,
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


def status(version=upgrade.CURRENT_VERSION):
    checksum = upgrade._verify_current_artifact()[0]["entry_sha256"] if version == upgrade.CURRENT_VERSION else upgrade._target_entry_sha256()
    return {
        "plugin": deployment.PLUGIN_SLUG,
        "version": version,
        "checksum": checksum,
        "active": True,
        "snapshot": {
            "rendering_enabled": False,
            "enabled_metadata_state": False,
            "payload": None,
            "payload_hash": "",
            "revision": "0",
        },
    }


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
        "plugin_version": upgrade.TARGET_VERSION,
        "zip_file_name": deployment.ZIP_NAME,
        "zip_sha256": deployment.ZIP_SHA256,
        "plugin_source_sha256": deployment.SOURCE_SHA256,
    }


def proof():
    return {
        "atlas_data_backup_file": "atlas-backup-2026-07-16-061052.json",
        "atlas_media_backup_file": "atlas-media-backup-2026-07-16-061053.zip",
        "atlas_program_backup_file": "atlas-program-backup-2026-07-16-061057.zip",
        "wordpress_backup_method": "SiteGround on-demand full-site backup",
        "wordpress_backup_reference": "Atlas Upgrade Backup",
        "wordpress_backup_completed_at": datetime.now(UTC) - timedelta(hours=1),
        "wordpress_database_included_attestation": True,
        "wordpress_plugins_included_attestation": True,
        "wordpress_restore_capability_attestation": True,
        "confirmer_identity": "Shawn Manchette",
        "php_error_log_findings": "No findings",
        "observed_write_summary": "No relevant WordPress change after backup",
        "manual_browser_evidence": evidence(),
    }


def request(before=None, **changes):
    before = before or observation()
    expected_post = upgrade._expected_post_upgrade(before)
    value = {
        **proof(),
        "installation_audit_id": 1,
        "activation_audit_id": 1,
        "operator": "Shawn Manchette",
        "current_plugin_version": upgrade.CURRENT_VERSION,
        "target_plugin_version": upgrade.TARGET_VERSION,
        "current_plugin_slug": deployment.PLUGIN_SLUG,
        "current_plugin_path": deployment.PLUGIN_FILE,
        "current_zip_filename": upgrade.CURRENT_ZIP_NAME,
        "current_zip_sha256": upgrade.CURRENT_ZIP_SHA256,
        "target_zip_filename": deployment.ZIP_NAME,
        "target_zip_sha256": deployment.ZIP_SHA256,
        "expected_plugin_inventory_hash": before["plugin_inventory_hash"],
        "expected_active_plugin_inventory_hash": before["active_plugin_inventory_hash"],
        "expected_post_plugin_inventory_hash": expected_post.get("plugin_inventory_hash"),
        "expected_post_active_plugin_inventory_hash": expected_post.get("active_plugin_inventory_hash"),
        "expected_page_snapshot_hash": PAGE_HASH,
        "expected_body_hash": deployment.EXPECTED_CORRECTED_BODY_HASH,
        "expected_media31_snapshot_hash": MEDIA31_HASH,
        "expected_media32_snapshot_hash": MEDIA32_HASH,
        "expected_runtime_identity": {"atlas_version": VERSION, "atlas_commit": COMMIT, "atlas_tag": VERSION, "manifest_sha256": MANIFEST, "source_compatibility_id": SOURCE_COMPATIBILITY},
        "repository_head": COMMIT,
        "repository_origin_main": COMMIT,
        "repository_tag": VERSION,
        "repository_branch": "main",
        "repository_working_tree_clean": True,
        "protected_paths_unchanged": True,
        "no_relevant_wordpress_change_after_backup": True,
        "browser_console_findings": "No findings",
    }
    value.update(changes)
    return WordPressPluginUpgradePreflightRequest(**value)


def seed(session):
    stored_proof = WordPressDeploymentBackupEvidence(**proof()).model_dump(mode="json")
    session.add(WordPressDeploymentAudit(
        id=1, generated_page_id=41, wordpress_post_id=8,
        action_type="install_metadata_bridge", status="verified",
        operator="Shawn Manchette", shawn_approved_at=datetime.now(UTC),
        confirmation_phrase_hash="a" * 64, atlas_version=VERSION,
        atlas_commit=COMMIT, atlas_tag=VERSION,
        plugin_version=upgrade.CURRENT_VERSION, plugin_slug=deployment.PLUGIN_SLUG,
        plugin_path=deployment.PLUGIN_FILE, zip_file_name=upgrade.CURRENT_ZIP_NAME,
        zip_sha256=upgrade.CURRENT_ZIP_SHA256, plugin_source_sha256="b" * 64,
        backup_reference="Atlas Backup", backup_completed_at=datetime.now(UTC),
        backup_deadline=datetime.now(UTC) + timedelta(hours=3),
        authorization_jti="c" * 32, deployment_key="d" * 64,
        backup_evidence=stored_proof, pre_snapshot={}, post_snapshot={},
        evidence_summary={"completion_mode": "installed_inactive_reconciliation"},
        evidence_directory="docs/deployment-records/test",
    ))
    session.commit()
    session.add(WordPressActivationAudit(
        id=1, generated_page_id=41, wordpress_post_id=8,
        installation_audit_id=1, status="verified", operator="Shawn Manchette",
        confirmation_phrase_hash="a" * 64, handle_fingerprint="b" * 64,
        binding_hash="c" * 64, atlas_version=VERSION, atlas_commit=COMMIT,
        atlas_tag=VERSION, manifest_sha256=MANIFEST,
        plugin_slug=deployment.PLUGIN_SLUG, plugin_path=deployment.PLUGIN_FILE,
        plugin_version=upgrade.CURRENT_VERSION, zip_sha256=upgrade.CURRENT_ZIP_SHA256,
        backup_evidence=stored_proof, browser_evidence_id="activation",
        browser_evidence_schema="project-atlas-manual-browser-evidence",
        browser_evidence_schema_version=1, pre_snapshot={}, post_snapshot={},
        gate_results=[], wordpress_write_count=1, transition_history=["pending", "verified"],
    ))
    session.commit()


def configure(monkeypatch, before=None):
    before = before or observation()
    monkeypatch.setattr(upgrade, "_observe", lambda session, proof: deepcopy(before))
    monkeypatch.setattr(upgrade, "_read_plugin_status", lambda session: status(before["plugins"][0]["version"]))
    monkeypatch.setattr(upgrade, "_verify_artifact", lambda: (artifact(), [upgrade._gate("release_identity", "release", True, "")]))
    monkeypatch.setattr(upgrade, "_backup_gates", lambda proof: [upgrade._gate("backups", "backups", True, "")])
    return before


def test_upgrade_routes_are_distinct_and_post_only():
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert ("/api/wordpress/deployment/metadata-bridge/upgrade/preflight/{page_id}", "POST") in routes
    assert ("/api/wordpress/deployment/metadata-bridge/upgrade/apply/{page_id}", "POST") in routes
    assert ("/api/wordpress/deployment/metadata-bridge/upgrade/recovery/assess/{page_id}", "POST") in routes


def test_preflight_is_zero_write_and_returns_one_time_handle(monkeypatch, db):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        result = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        assert result.plugin_upgrade_preflight_ready and result.upgrade_handle
        assert result.confirmation_phrase == upgrade.UPGRADE_PHRASE
        assert result.wordpress_write_count == result.atlas_write_count == 0
        assert result.token_issued is result.nonce_returned is result.audit_created is False
        assert session.exec(select(WordPressPluginUpgradeAudit)).first() is None


def test_apply_uses_one_fixed_upgrade_and_finalizes_audit(monkeypatch, db):
    before = configure(monkeypatch)
    after = observation(upgrade.TARGET_VERSION)
    calls = {"observe": 0, "upgrade": 0}
    def observe(session, proof):
        calls["observe"] += 1
        return deepcopy(before if calls["observe"] <= 2 else after)
    monkeypatch.setattr(upgrade, "_observe", observe)
    monkeypatch.setattr(upgrade, "_read_plugin_status", lambda session: status(upgrade.CURRENT_VERSION) if calls["observe"] <= 2 else status(upgrade.TARGET_VERSION))
    monkeypatch.setattr(upgrade, "_acquire_upgrade_nonce", lambda session: "nonce-not-returned")
    def send(session, nonce):
        calls["upgrade"] += 1
        pending = session.exec(select(WordPressPluginUpgradeAudit)).one()
        assert pending.status == "pending" and pending.wordpress_write_count == 0
        return {"status_code": 200, "accepted": True}
    monkeypatch.setattr(upgrade, "_send_fixed_upgrade", send)
    monkeypatch.setattr(upgrade, "_read_route_registry", lambda session: {"routes": sorted(upgrade.LIFECYCLE_ROUTES | {upgrade.LEGACY_ROUTE}), "legacy_route_registered": True, "request_method": "GET"})
    with Session(db) as session:
        seed(session)
        preflight = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        result = upgrade.apply_plugin_upgrade(session, 41, WordPressPluginUpgradeApplyRequest(
            upgrade_handle=preflight.upgrade_handle,
            confirmation_phrase=preflight.confirmation_phrase,
        ))
        assert result.status == "verified" and result.recovery_recommendation == "no_action"
        assert result.wordpress_write_count == 1 and result.atlas_write_count == 2
        assert calls["upgrade"] == 1
        saved = session.get(WordPressPluginUpgradeAudit, result.upgrade_audit_id)
        assert saved.status == "verified" and saved.transition_history == ["pending", "verified"]


def test_handle_replay_wrong_phrase_expiry_and_restart_block(monkeypatch, db):
    before = configure(monkeypatch)
    monkeypatch.setattr(upgrade, "_acquire_upgrade_nonce", lambda session: "nonce")
    monkeypatch.setattr(upgrade, "_send_fixed_upgrade", lambda session, nonce: {"_error": "simulated"})
    with Session(db) as session:
        seed(session)
        preflight = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        with pytest.raises(HTTPException, match="phrase"):
            upgrade.apply_plugin_upgrade(session, 41, WordPressPluginUpgradeApplyRequest(upgrade_handle=preflight.upgrade_handle, confirmation_phrase="WRONG"))
        assert preflight.upgrade_handle in upgrade._handles
        apply = WordPressPluginUpgradeApplyRequest(upgrade_handle=preflight.upgrade_handle, confirmation_phrase=upgrade.UPGRADE_PHRASE)
        upgrade.apply_plugin_upgrade(session, 41, apply)
        with pytest.raises(HTTPException, match="unknown, expired, consumed"):
            upgrade.apply_plugin_upgrade(session, 41, apply)
        second = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        upgrade._clear_upgrade_handles()
        with pytest.raises(HTTPException, match="invalidated by restart"):
            upgrade.apply_plugin_upgrade(session, 41, WordPressPluginUpgradeApplyRequest(upgrade_handle=second.upgrade_handle, confirmation_phrase=upgrade.UPGRADE_PHRASE))


@pytest.mark.parametrize("change,failed", [
    ({"repository_working_tree_clean": False}, "repository_clean"),
    ({"protected_paths_unchanged": False}, "protected_paths"),
    ({"no_relevant_wordpress_change_after_backup": False}, "no_post_backup_change"),
    ({"expected_page_snapshot_hash": "f" * 64}, "page_snapshot"),
    ({"expected_media31_snapshot_hash": "f" * 64}, "media31"),
    ({"expected_plugin_inventory_hash": "f" * 64}, "plugin_inventory"),
])
def test_drift_blocks_without_audit_or_write(monkeypatch, db, change, failed):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        result = upgrade.plugin_upgrade_preflight(session, 41, request(before, **change))
        assert not result.plugin_upgrade_preflight_ready and result.upgrade_handle is None
        assert failed in {g.code for g in result.gate_results if not g.passed}
        assert session.exec(select(WordPressPluginUpgradeAudit)).first() is None


def test_plugin_metadata_and_audit_failures_block(monkeypatch, db):
    cases = []
    inactive = observation(); inactive["plugins"][0]["status"] = "inactive"; inactive["active_plugins"].remove(inactive["plugins"][0]["plugin"]); inactive["plugin_inventory_hash"] = upgrade._hash(inactive["plugins"]); inactive["active_plugin_inventory_hash"] = upgrade._hash(inactive["active_plugins"])
    cases.append((inactive, "plugin_active"))
    duplicate = observation(); duplicate["plugins"].append(deepcopy(duplicate["plugins"][0])); duplicate["plugin_inventory_hash"] = upgrade._hash(duplicate["plugins"])
    cases.append((duplicate, "plugin_singleton"))
    for observed, code in cases:
        configure(monkeypatch, observed)
        with Session(db) as session:
            seed(session)
            result = upgrade.plugin_upgrade_preflight(session, 41, request(observed))
            assert code in {g.code for g in result.gate_results if not g.passed}
            session.delete(session.get(WordPressActivationAudit, 1))
            session.delete(session.get(WordPressDeploymentAudit, 1))
            session.commit()


def test_metadata_rows_and_unresolved_lifecycle_block(monkeypatch, db):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        session.add(WordPressMetadataState(generated_page_id=41, wordpress_post_id=8, status="applied", payload={}, payload_hash="a" * 64, wordpress_revision="1"))
        session.commit()
        result = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        assert "metadata_rows" in {g.code for g in result.gate_results if not g.passed}


@pytest.mark.parametrize("snapshot_change,failed", [
    ({"rendering_enabled": True}, "rendering_disabled"),
    ({"payload": {"unsafe": True}}, "payload_absent"),
    ({"payload_hash": "a" * 64}, "payload_absent"),
    ({"revision": "1"}, "revision_zero"),
])
def test_metadata_safety_drift_blocks(monkeypatch, db, snapshot_change, failed):
    before = configure(monkeypatch)
    changed_status = status()
    changed_status["snapshot"].update(snapshot_change)
    monkeypatch.setattr(upgrade, "_read_plugin_status", lambda session: deepcopy(changed_status))
    with Session(db) as session:
        seed(session)
        result = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        assert failed in {g.code for g in result.gate_results if not g.passed}
        assert session.exec(select(WordPressPluginUpgradeAudit)).first() is None


def test_invalid_installation_or_activation_audit_blocks(monkeypatch, db):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        session.get(WordPressActivationAudit, 1).status = "verification_failed"
        session.commit()
        result = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        assert "activation_audit" in {g.code for g in result.gate_results if not g.passed}


def test_invalid_or_expired_evidence_blocks_before_observation(monkeypatch, db):
    before = configure(monkeypatch)
    calls = {"observe": 0}
    monkeypatch.setattr(upgrade, "_observe", lambda session, proof: calls.__setitem__("observe", 1) or deepcopy(before))
    with Session(db) as session:
        seed(session)
        result = upgrade.plugin_upgrade_preflight(session, 41, request(before, manual_browser_evidence={**evidence(), "rendered_head_hash": "f" * 64}))
        assert "evidence_contract" in {g.code for g in result.gate_results if not g.passed}
        assert calls["observe"] == 0


def test_post_upgrade_failure_records_recovery_without_automatic_rollback(monkeypatch, db):
    before = configure(monkeypatch)
    after = observation(upgrade.TARGET_VERSION)
    after["page_snapshot_hash"] = "f" * 64
    calls = {"observe": 0, "send": 0}
    monkeypatch.setattr(upgrade, "_observe", lambda session, proof: deepcopy(before if (calls.__setitem__("observe", calls["observe"] + 1) or calls["observe"] <= 2) else after))
    monkeypatch.setattr(upgrade, "_read_plugin_status", lambda session: status(upgrade.CURRENT_VERSION) if calls["observe"] <= 2 else status(upgrade.TARGET_VERSION))
    monkeypatch.setattr(upgrade, "_acquire_upgrade_nonce", lambda session: "nonce")
    monkeypatch.setattr(upgrade, "_send_fixed_upgrade", lambda session, nonce: calls.__setitem__("send", calls["send"] + 1) or {"status_code": 200, "accepted": True})
    monkeypatch.setattr(upgrade, "_read_route_registry", lambda session: {"routes": sorted(upgrade.LIFECYCLE_ROUTES | {upgrade.LEGACY_ROUTE}), "legacy_route_registered": True, "request_method": "GET"})
    with Session(db) as session:
        seed(session)
        preflight = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        result = upgrade.apply_plugin_upgrade(session, 41, WordPressPluginUpgradeApplyRequest(upgrade_handle=preflight.upgrade_handle, confirmation_phrase=upgrade.UPGRADE_PHRASE))
        assert result.status == "verification_failed"
        assert result.recovery_recommendation == "guarded_downgrade"
        assert calls["send"] == 1


def test_write_transport_is_fixed_and_has_no_other_mutation_surface():
    source = inspect.getsource(upgrade._send_fixed_upgrade)
    assert "client.post" in source
    assert "/wp-admin/update.php?action=upload-plugin" in source
    assert '"overwrite_package": "1"' in source
    assert "ZIP_NAME" in source
    for forbidden in ("wp/v2/pages", "wp/v2/media", "metadata/stage", "rendering/enable", "purge", "DELETE", "client.put", "client.patch"):
        assert forbidden not in source
    preflight = inspect.getsource(upgrade.plugin_upgrade_preflight)
    assert "session.commit" not in preflight
    assert "_send_fixed_upgrade" not in preflight


def test_target_and_current_zip_contracts_are_locked():
    current, gates = upgrade._verify_current_artifact()
    assert all(g.passed for g in gates)
    assert current["zip_sha256"] == upgrade.CURRENT_ZIP_SHA256
    assert upgrade._target_entry_sha256()
    assert upgrade._target_artifact_disables_legacy_route()
    assert deployment.ZIP_SHA256 == "09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7"


def test_upgrade_audit_is_in_data_backup_v035_contract():
    assert backup_service.BACKUP_VERSION == "0.35"
    assert backup_service.BACKUP_MODELS["wordpress_plugin_upgrade_audits"] is WordPressPluginUpgradeAudit
    assert "0.34" in backup_service.SUPPORTED_BACKUP_VERSIONS
