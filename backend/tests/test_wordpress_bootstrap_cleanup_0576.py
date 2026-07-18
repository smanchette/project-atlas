from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import WordPressBootstrapCleanupAudit, WordPressPluginUpgradeAudit
from app.schemas.wordpress import (
    WordPressBootstrapCleanupApplyRequest,
    WordPressBootstrapCleanupPreflightRequest,
    WordPressBootstrapDeletionPreflightRequest,
)
from app.services import wordpress_bootstrap_cleanup_0576 as cleanup
from app.services import wordpress_plugin_upgrade_0576 as upgrade
from test_wordpress_plugin_upgrade_0576 import (
    COMMIT,
    KEY,
    MANIFEST,
    MEDIA31_HASH,
    MEDIA32_HASH,
    PAGE_HASH,
    PAYLOAD_HASH,
    SOURCE_COMPATIBILITY,
    VERSION,
    artifact,
    bootstrap_status,
    observation as upgrade_observation,
    proof,
    seed as seed_upgrade_dependencies,
    status,
)


@pytest.fixture(autouse=True)
def clear_handles(monkeypatch):
    cleanup._clear_cleanup_handles()
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    yield
    cleanup._clear_cleanup_handles()


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'cleanup-0576.sqlite3').as_posix()}")
    SQLModel.metadata.create_all(engine)
    return engine


def observation(bootstrap_state="active"):
    value = upgrade_observation(upgrade.TARGET_VERSION)
    bridge = value["plugins"][0]
    value["plugins"] = [bridge, {"plugin": "safe/example", "version": "1.0", "status": "active"}]
    if bootstrap_state is not None:
        value["plugins"].append({"plugin": "project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap", "version": upgrade.BOOTSTRAP_VERSION, "status": bootstrap_state})
    value["active_plugins"] = sorted(item["plugin"] for item in value["plugins"] if item["status"] in {"active", "network-active"})
    value["plugin_inventory_hash"] = cleanup._hash(value["plugins"])
    value["active_plugin_inventory_hash"] = cleanup._hash(value["active_plugins"])
    return value


def request(before=None, **changes):
    before = before or observation()
    value = {
        **proof(),
        "installation_audit_id": 1,
        "activation_audit_id": 1,
        "upgrade_audit_id": 2,
        "operator": "Shawn Manchette",
        "expected_bridge_slug": cleanup.PLUGIN_SLUG,
        "expected_bridge_path": cleanup.PLUGIN_FILE,
        "expected_bridge_version": upgrade.TARGET_VERSION,
        "expected_bridge_zip_sha256": artifact()["zip_sha256"],
        "expected_bootstrap_slug": cleanup.BOOTSTRAP_SLUG,
        "expected_bootstrap_path": cleanup.BOOTSTRAP_ENTRY,
        "expected_bootstrap_version": upgrade.BOOTSTRAP_VERSION,
        "expected_bootstrap_zip_sha256": upgrade.BOOTSTRAP_ZIP_SHA256,
        "expected_payload_hash": PAYLOAD_HASH,
        "expected_revision": "1",
        "expected_metadata_state_status": "staged",
        "expected_plugin_inventory_hash": before["plugin_inventory_hash"],
        "expected_active_plugin_inventory_hash": before["active_plugin_inventory_hash"],
        "expected_page_snapshot_hash": PAGE_HASH,
        "expected_body_hash": cleanup.EXPECTED_CORRECTED_BODY_HASH,
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
    return WordPressBootstrapCleanupPreflightRequest(**value)


def seed(session):
    seed_upgrade_dependencies(session)
    session.add(WordPressPluginUpgradeAudit(
        id=2, generated_page_id=41, wordpress_post_id=8, installation_audit_id=1, activation_audit_id=1,
        status="verified", operator="Shawn Manchette", confirmation_phrase_hash="4" * 64, handle_fingerprint="5" * 64,
        binding_hash="6" * 64, previous_version="0.57.5", target_version="0.57.6",
        previous_artifact_sha256=upgrade.CURRENT_ZIP_SHA256, target_artifact_sha256=artifact()["zip_sha256"],
        release_identity={}, backup_evidence={}, browser_evidence_id="upgrade-0576", browser_evidence_hashes={},
        pre_snapshot={}, post_snapshot={}, previous_inventories={}, final_inventories={}, metadata_rendering_state={},
        page_media_snapshots={}, gate_results=[], wordpress_write_count=1, atlas_write_count=2,
        recovery_recommendation="no_action", transition_history=["pending", "verified"], completed_at=datetime.now(UTC),
    ))
    session.commit()


def configure(monkeypatch, states):
    queue = [deepcopy(item) for item in states]
    current = {"value": deepcopy(queue[0])}
    def observe(session, backup):
        if queue:
            current["value"] = queue.pop(0)
        return deepcopy(current["value"])
    def bootstrap_read(session):
        found = cleanup._bootstrap_matches(current["value"])
        if found and found[0]["status"] in {"active", "network-active"}:
            return bootstrap_status(available=False, plugin_version=upgrade.TARGET_VERSION)
        return {"status_code": 404, "request_method": "GET", "_error": "not_found"}
    def route_read(session):
        found = cleanup._bootstrap_matches(current["value"])
        routes = set(upgrade.LIFECYCLE_ROUTES) | {upgrade.PREVIEW_ROUTE, upgrade.CACHE_PURGE_ROUTE, upgrade.LEGACY_ROUTE}
        if found and found[0]["status"] in {"active", "network-active"}:
            routes |= {upgrade.BOOTSTRAP_STATUS_ROUTE, upgrade.BOOTSTRAP_UPGRADE_ROUTE}
        return {"routes": sorted(routes), "legacy_route_registered": True, "request_method": "GET", "status_code": 200}
    monkeypatch.setattr(cleanup, "_observe", observe)
    monkeypatch.setattr(cleanup, "_read_plugin_status", lambda session: status(upgrade.TARGET_VERSION))
    monkeypatch.setattr(cleanup, "_read_bootstrap_status", bootstrap_read)
    monkeypatch.setattr(cleanup, "_read_route_registry", route_read)
    monkeypatch.setattr(cleanup, "_verify_artifact", lambda: (artifact(), [cleanup._gate("release_identity", "release", True, "")]))
    monkeypatch.setattr(cleanup, "_verify_bootstrap_artifact", lambda: ({"zip_sha256": upgrade.BOOTSTRAP_ZIP_SHA256, "entry_sha256": upgrade.BOOTSTRAP_ENTRY_SHA256}, [cleanup._gate("bootstrap", "bootstrap", True, "")]))
    monkeypatch.setattr(cleanup, "_backup_gates", lambda backup: [cleanup._gate("backups", "backups", True, "")])


def test_cleanup_020_deactivation_and_deletion_are_separately_phrase_gated(monkeypatch, db):
    active, inactive, absent = observation("active"), observation("inactive"), observation(None)
    configure(monkeypatch, [active, active, inactive])
    with Session(db) as session:
        seed(session)
        preflight = cleanup.cleanup_preflight(session, 41, request(active))
        assert preflight.bootstrap_cleanup_preflight_ready
        assert preflight.confirmation_phrase == "DEACTIVATE PROJECT ATLAS UPGRADE BOOTSTRAP 0.2.0"
        monkeypatch.setattr(cleanup, "_send_deactivation", lambda session: {"status_code": 200, "accepted": True})
        deactivated = cleanup.deactivate_bootstrap(session, 41, WordPressBootstrapCleanupApplyRequest(cleanup_handle=preflight.cleanup_handle, confirmation_phrase=cleanup.DEACTIVATION_PHRASE))
        assert deactivated.status == "deactivated" and deactivated.wordpress_write_count == 1

        configure(monkeypatch, [inactive, inactive, absent])
        deletion_request = WordPressBootstrapDeletionPreflightRequest(**request(inactive).model_dump(), cleanup_audit_id=deactivated.cleanup_audit_id)
        deletion = cleanup.deletion_preflight(session, 41, deletion_request)
        assert deletion.bootstrap_cleanup_preflight_ready
        assert deletion.confirmation_phrase == "DELETE PROJECT ATLAS UPGRADE BOOTSTRAP 0.2.0"
        monkeypatch.setattr(cleanup, "_send_deletion", lambda session: {"status_code": 200, "accepted": True})
        result = cleanup.delete_bootstrap(session, 41, WordPressBootstrapCleanupApplyRequest(cleanup_handle=deletion.cleanup_handle, confirmation_phrase=cleanup.DELETION_PHRASE))
        assert result.status == "verified" and result.wordpress_write_count == 1
        assert session.get(WordPressBootstrapCleanupAudit, deactivated.cleanup_audit_id).transition_history == [
            "pending",
            "deactivated",
            "pending",
            "verified",
        ]


def test_cleanup_020_rejects_010_identity_and_payload_drift(monkeypatch, db):
    before = observation()
    configure(monkeypatch, [before])
    with Session(db) as session:
        seed(session)
        wrong_identity = cleanup.cleanup_preflight(
            session,
            41,
            request(
                before,
                expected_bootstrap_version="0.1.0",
                expected_bootstrap_zip_sha256=upgrade.BOOTSTRAP_ZIP_SHA256,
            ),
        )
        assert not wrong_identity.bootstrap_cleanup_preflight_ready
        assert any(g.code == "bootstrap_artifact" and not g.passed for g in wrong_identity.gate_results)
        result = cleanup.cleanup_preflight(session, 41, request(before, expected_payload_hash="f" * 64))
        assert not result.bootstrap_cleanup_preflight_ready
        assert "metadata_state" in {gate.code for gate in result.gate_results if not gate.passed}
        assert session.exec(select(WordPressBootstrapCleanupAudit)).first() is not None  # historical cleanup only
