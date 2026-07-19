from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import inspect
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    WordPressBootstrapCleanupAudit,
    WordPressMetadataLifecycleAudit,
    WordPressMetadataState,
    WordPressPluginUpgradeAudit,
)
from app.schemas.wordpress import WordPressPluginUpgradeApplyRequest, WordPressPluginUpgradePreflightRequest
from app.services import wordpress_deployment as deployment
from app.services import wordpress_metadata_lifecycle as lifecycle
from app.services import wordpress_plugin_upgrade_0577 as upgrade
from test_wordpress_plugin_upgrade import (
    COMMIT,
    KEY,
    MANIFEST,
    MEDIA31_HASH,
    MEDIA32_HASH,
    PAGE_HASH,
    evidence,
    proof,
    seed as seed_installation_and_activation,
)


VERSION = "v0.59.80"
SOURCE_COMPATIBILITY = "project-atlas-release-identity-v0.59.80"
PAYLOAD = lifecycle.approved_payload().model_dump(mode="json")
PAYLOAD_HASH = lifecycle.payload_sha256(PAYLOAD)


@pytest.fixture(autouse=True)
def clear_handles(monkeypatch):
    upgrade._clear_upgrade_handles()
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    yield
    upgrade._clear_upgrade_handles()


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'upgrade-0576.sqlite3').as_posix()}")
    SQLModel.metadata.create_all(engine)
    return engine


def observation(version=upgrade.CURRENT_VERSION):
    plugins = [
        {"plugin": "project-atlas-metadata-bridge/project-atlas-metadata-bridge", "version": version, "status": "active"},
        {"plugin": "project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap", "version": upgrade.BOOTSTRAP_VERSION, "status": "active"},
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
        "media31_snapshot_hash": MEDIA31_HASH,
        "media32_snapshot_hash": MEDIA32_HASH,
        "page_references_media32": False,
        "site": {"name": "My WordPress", "description": ""},
        "rendered": {
            "verified": True,
            "signature_validated": True,
            "h1": ["Drywood Termite Tenting in Orlando, FL"],
            "atlas_metadata_marker_present": False,
            "media32_reference_present": False,
            "metadata_inventory": {"meta_descriptions": [], "open_graph": [], "twitter": [], "json_ld": [], "atlas_ownership_markers": []},
            "cache_headers": {},
        },
        "cache_headers": {},
        "cache_purge_count": 0,
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
            "payload": deepcopy(PAYLOAD),
            "payload_hash": PAYLOAD_HASH,
            "revision": "1",
        },
    }


def bootstrap_status(*, available=True, plugin_version=upgrade.CURRENT_VERSION):
    return {
        "bootstrap": "project-atlas-upgrade-bootstrap",
        "bootstrap_version": upgrade.BOOTSTRAP_VERSION,
        "bootstrap_checksum": upgrade.BOOTSTRAP_ENTRY_SHA256,
        "operation": "upgrade_metadata_bridge_0.57.6_to_0.57.7",
        "application_password_compatible": True,
        "target_plugin": deployment.PLUGIN_FILE,
        "current_version": upgrade.CURRENT_VERSION,
        "target_version": upgrade.TARGET_VERSION,
        "target_zip": deployment.ZIP_NAME,
        "target_zip_sha256": deployment.ZIP_SHA256,
        "available": available,
        "metadata": {"payload_present": True, "payload_hash": PAYLOAD_HASH, "revision": "1", "rendering_enabled": False},
        "plugin": {"installed": True, "active": True, "version": plugin_version},
        "status_code": 200,
        "request_method": "GET",
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


def request(before=None, **changes):
    before = before or observation()
    expected_post = upgrade._expected_post_upgrade(before)
    value = {
        **proof(),
        "installation_audit_id": 1,
        "activation_audit_id": 1,
        "previous_upgrade_audit_id": 2,
        "bootstrap_cleanup_audit_id": 2,
        "staging_audit_id": 2,
        "recovery_disable_audit_id": 5,
        "expected_payload_hash": PAYLOAD_HASH,
        "expected_revision": "1",
        "expected_metadata_state_status": "staged",
        "expected_metadata_state_rows": 1,
        "expected_metadata_sync_audit_rows": 0,
        "expected_cache_purge_count": 0,
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
        "expected_post_plugin_inventory_hash": expected_post["plugin_inventory_hash"],
        "expected_post_active_plugin_inventory_hash": expected_post["active_plugin_inventory_hash"],
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


def lifecycle_audit(audit_id, action, status_value, final_rendering, *, payload_hash=PAYLOAD_HASH):
    return WordPressMetadataLifecycleAudit(
        id=audit_id, generated_page_id=41, wordpress_post_id=8, installation_audit_id=1, activation_audit_id=1,
        action_type=action, status=status_value, operator="Shawn Manchette", confirmation_phrase_hash=str(audit_id) * 64,
        handle_fingerprint=hex(audit_id)[2:] * 64, binding_hash=chr(96 + audit_id) * 64,
        release_identity={}, backup_evidence={}, browser_evidence_id=f"evidence-{audit_id}", browser_evidence_hashes={},
        payload_hash=payload_hash, previous_revision="1", final_revision="1", previous_rendering_enabled=not final_rendering,
        final_rendering_enabled=final_rendering, pre_snapshot={}, post_snapshot={}, page_media_snapshots={}, gate_results=[],
        wordpress_write_count=1, atlas_write_count=2, transition_history=["pending", status_value], completed_at=datetime.now(UTC),
    )


def seed(session):
    seed_installation_and_activation(session)
    session.add(WordPressPluginUpgradeAudit(
        id=1, generated_page_id=41, wordpress_post_id=8, installation_audit_id=1, activation_audit_id=1,
        status="verified", operator="Shawn Manchette", confirmation_phrase_hash="a" * 64, handle_fingerprint="b" * 64,
        binding_hash="c" * 64, previous_version="0.57.4", target_version="0.57.5",
        previous_artifact_sha256="9" * 64, target_artifact_sha256="09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7",
        release_identity={}, backup_evidence={}, browser_evidence_id="prior-upgrade", browser_evidence_hashes={},
        pre_snapshot={}, post_snapshot={}, previous_inventories={}, final_inventories={}, metadata_rendering_state={},
        page_media_snapshots={}, gate_results=[], wordpress_write_count=1, atlas_write_count=2,
        recovery_recommendation="no_action", transition_history=["pending", "verified"], completed_at=datetime.now(UTC),
    ))
    session.add(WordPressPluginUpgradeAudit(
        id=2, generated_page_id=41, wordpress_post_id=8, installation_audit_id=1, activation_audit_id=1,
        status="verified", operator="Shawn Manchette", confirmation_phrase_hash="4" * 64, handle_fingerprint="5" * 64,
        binding_hash="6" * 64, previous_version="0.57.5", target_version="0.57.6",
        previous_artifact_sha256="09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7",
        target_artifact_sha256=upgrade.CURRENT_ZIP_SHA256,
        release_identity={}, backup_evidence={}, browser_evidence_id="prior-upgrade-0576", browser_evidence_hashes={},
        pre_snapshot={}, post_snapshot={}, previous_inventories={}, final_inventories={}, metadata_rendering_state={},
        page_media_snapshots={}, gate_results=[], wordpress_write_count=1, atlas_write_count=2,
        recovery_recommendation="no_action", transition_history=["pending", "verified"], completed_at=datetime.now(UTC),
    ))
    session.add(WordPressBootstrapCleanupAudit(
        id=1, generated_page_id=41, wordpress_post_id=8, installation_audit_id=1, activation_audit_id=1, upgrade_audit_id=1,
        status="verified", operator="Shawn Manchette", bootstrap_slug="project-atlas-upgrade-bootstrap",
        bootstrap_path="project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap.php", bootstrap_version="0.1.0",
        bootstrap_zip_sha256="4c8b4b0c697b2b352a10f405950c7b6a750236be96aec81fcd45176ece1189bd", bridge_version="0.57.5",
        deactivation_phrase_hash="d" * 64, deletion_phrase_hash="e" * 64, deactivation_handle_fingerprint="f" * 64,
        deletion_handle_fingerprint="1" * 64, deactivation_binding_hash="2" * 64, deletion_binding_hash="3" * 64,
        release_identity={}, backup_evidence={}, browser_evidence_id="cleanup", browser_evidence_hashes={}, pre_snapshot={},
        deactivated_snapshot={}, final_snapshot={}, previous_inventories={}, deactivated_inventories={}, final_inventories={},
        metadata_rendering_state={}, page_media_snapshots={}, gate_results=[], wordpress_write_count=2, atlas_write_count=4,
        recovery_recommendation="no_action", transition_history=["pending", "deactivated", "verified"], completed_at=datetime.now(UTC),
    ))
    session.add(WordPressBootstrapCleanupAudit(
        id=2, generated_page_id=41, wordpress_post_id=8, installation_audit_id=1, activation_audit_id=1, upgrade_audit_id=2,
        status="verified", operator="Shawn Manchette", bootstrap_slug="project-atlas-upgrade-bootstrap",
        bootstrap_path="project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap.php", bootstrap_version="0.2.0",
        bootstrap_zip_sha256="873701da2ed42212e7d7c9b12816eeb0560d2751d7494c2b706008c0d5c1383a", bridge_version="0.57.6",
        deactivation_phrase_hash="7" * 64, deletion_phrase_hash="8" * 64, deactivation_handle_fingerprint="9" * 64,
        deletion_handle_fingerprint="a" * 64, deactivation_binding_hash="b" * 64, deletion_binding_hash="c" * 64,
        release_identity={}, backup_evidence={}, browser_evidence_id="cleanup-0576", browser_evidence_hashes={}, pre_snapshot={},
        deactivated_snapshot={}, final_snapshot={}, previous_inventories={}, deactivated_inventories={}, final_inventories={},
        metadata_rendering_state={}, page_media_snapshots={}, gate_results=[], wordpress_write_count=2, atlas_write_count=4,
        recovery_recommendation="no_action", transition_history=["pending", "deactivated", "verified"], completed_at=datetime.now(UTC),
    ))
    session.add(lifecycle_audit(1, "stage_metadata_payload", "failed", False))
    session.add(lifecycle_audit(2, "stage_metadata_payload", "verified", False))
    session.add(lifecycle_audit(3, "enable_metadata_rendering", "verification_failed", True))
    session.add(lifecycle_audit(4, "disable_metadata_rendering", "verified", False))
    session.add(lifecycle_audit(5, "disable_metadata_rendering", "verified", False))
    session.add(WordPressMetadataState(generated_page_id=41, wordpress_post_id=8, status="staged", payload=deepcopy(PAYLOAD), payload_hash=PAYLOAD_HASH, wordpress_revision="1"))
    session.commit()


def configure(monkeypatch, before=None):
    before = before or observation()
    monkeypatch.setattr(upgrade, "_observe", lambda session, backup: deepcopy(before))
    monkeypatch.setattr(upgrade, "_read_plugin_status", lambda session: status(before["plugins"][0]["version"]))
    monkeypatch.setattr(upgrade, "_read_bootstrap_status", lambda session: bootstrap_status())
    monkeypatch.setattr(upgrade, "_verify_artifact", lambda: (artifact(), [upgrade._gate("release_identity", "release", True, "")]))
    monkeypatch.setattr(upgrade, "_backup_gates", lambda backup: [upgrade._gate("backups", "backups", True, "")])
    return before


def test_0576_preflight_is_zero_write_and_profile_is_exact(monkeypatch, db):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        result = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        assert result.plugin_upgrade_preflight_ready and result.upgrade_handle
        assert result.current_version == "0.57.6" and result.target_version == "0.57.7"
        assert result.confirmation_phrase == upgrade.UPGRADE_PHRASE
        assert result.wordpress_write_count == result.atlas_write_count == 0
        assert session.exec(select(WordPressPluginUpgradeAudit)).all()[0].target_version == "0.57.5"


def test_0576_apply_preserves_staged_state_and_defers_preview_output(monkeypatch, db):
    before = configure(monkeypatch)
    after = observation(upgrade.TARGET_VERSION)
    calls = {"observe": 0, "write": 0}
    monkeypatch.setattr(upgrade, "_observe", lambda session, backup: deepcopy(before if (calls.__setitem__("observe", calls["observe"] + 1) or calls["observe"] <= 2) else after))
    monkeypatch.setattr(upgrade, "_read_plugin_status", lambda session: status(upgrade.CURRENT_VERSION) if calls["observe"] <= 2 else status(upgrade.TARGET_VERSION))
    monkeypatch.setattr(upgrade, "_read_bootstrap_status", lambda session: bootstrap_status(available=calls["observe"] <= 2, plugin_version=upgrade.CURRENT_VERSION if calls["observe"] <= 2 else upgrade.TARGET_VERSION))
    monkeypatch.setattr(upgrade, "_send_fixed_upgrade", lambda session: calls.__setitem__("write", calls["write"] + 1) or {"status_code": 200, "accepted": True})
    monkeypatch.setattr(upgrade, "_read_route_registry", lambda session: {"routes": sorted(upgrade.LIFECYCLE_ROUTES | {upgrade.PREVIEW_ROUTE, upgrade.CACHE_PURGE_ROUTE, upgrade.LEGACY_ROUTE}), "legacy_route_registered": True, "request_method": "GET"})
    monkeypatch.setattr(upgrade, "_read_disabled_preview_contract", lambda session: {"status_code": 409, "code": "atlas_rendering_preview_unavailable", "request_method": "GET", "output_verification_deferred": True})
    monkeypatch.setattr(upgrade, "_target_artifact_preview_contract", lambda: True)
    with Session(db) as session:
        seed(session)
        preflight = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        result = upgrade.apply_plugin_upgrade(session, 41, WordPressPluginUpgradeApplyRequest(upgrade_handle=preflight.upgrade_handle, confirmation_phrase=upgrade.UPGRADE_PHRASE))
        assert result.status == "verified" and result.recovery_recommendation == "no_action"
        assert result.previous_version == "0.57.6" and result.target_version == "0.57.7"
        assert calls["write"] == 1 and result.wordpress_write_count == 1
        assert result.inspected_state["plugin_status"]["snapshot"]["payload_hash"] == PAYLOAD_HASH
        assert result.inspected_state["disabled_preview_contract"]["output_verification_deferred"] is True


@pytest.mark.parametrize("change,gate", [
    ({"current_plugin_version": "0.57.4"}, "current_version"),
    ({"target_plugin_version": "0.57.5"}, "target_version"),
    ({"expected_payload_hash": "f" * 64}, "staging_audit"),
    ({"expected_revision": "0"}, "metadata_state"),
    ({"expected_metadata_state_status": "not_applied"}, "metadata_state"),
    ({"repository_working_tree_clean": False}, "repository_clean"),
])
def test_0576_profile_drift_blocks_without_audit(monkeypatch, db, change, gate):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        result = upgrade.plugin_upgrade_preflight(session, 41, request(before, **change))
        assert not result.plugin_upgrade_preflight_ready and result.upgrade_handle is None
        assert gate in {item.code for item in result.gate_results if not item.passed}
        assert len(session.exec(select(WordPressPluginUpgradeAudit)).all()) == 2


def test_0576_handle_phrase_replay_and_preview_contract_fail_closed(monkeypatch, db):
    before = configure(monkeypatch)
    with Session(db) as session:
        seed(session)
        preflight = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        with pytest.raises(HTTPException, match="phrase"):
            upgrade.apply_plugin_upgrade(session, 41, WordPressPluginUpgradeApplyRequest(upgrade_handle=preflight.upgrade_handle, confirmation_phrase="WRONG"))
        assert preflight.upgrade_handle in upgrade._handles
        upgrade._clear_upgrade_handles()
        with pytest.raises(HTTPException, match="invalidated by restart"):
            upgrade.apply_plugin_upgrade(session, 41, WordPressPluginUpgradeApplyRequest(upgrade_handle=preflight.upgrade_handle, confirmation_phrase=upgrade.UPGRADE_PHRASE))


def test_0576_expired_and_consumed_handles_fail_closed(monkeypatch, db):
    before = configure(monkeypatch)
    monkeypatch.setattr(upgrade, "_send_fixed_upgrade", lambda session: {"_error": "simulated"})
    with Session(db) as session:
        seed(session)
        expired = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        upgrade._handles[expired.upgrade_handle] = replace(
            upgrade._handles[expired.upgrade_handle], expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )
        with pytest.raises(HTTPException, match="expired"):
            upgrade.apply_plugin_upgrade(session, 41, WordPressPluginUpgradeApplyRequest(upgrade_handle=expired.upgrade_handle, confirmation_phrase=upgrade.UPGRADE_PHRASE))

        consumed = upgrade.plugin_upgrade_preflight(session, 41, request(before))
        first = WordPressPluginUpgradeApplyRequest(upgrade_handle=consumed.upgrade_handle, confirmation_phrase=upgrade.UPGRADE_PHRASE)
        result = upgrade.apply_plugin_upgrade(session, 41, first)
        assert result.status == "failed"
        with pytest.raises(HTTPException, match="unknown, expired, consumed"):
            upgrade.apply_plugin_upgrade(session, 41, first)


@pytest.mark.parametrize("case,failed_gate", [
    ("preview_route_missing", "lifecycle_routes"),
    ("preview_output_returned", "preview_disabled_contract"),
    ("preview_wrong_code", "preview_disabled_contract"),
    ("cache_route_missing", "lifecycle_routes"),
    ("payload_changed", "payload_preserved"),
    ("rendering_enabled", "rendering_disabled"),
    ("page_changed", "page_snapshot"),
    ("media_changed", "media31"),
    ("cache_purged", "cache_boundary"),
])
def test_0576_post_upgrade_drift_fails_verification(case, failed_gate):
    before = observation()
    before["plugin_status"] = status(upgrade.CURRENT_VERSION)
    after = observation(upgrade.TARGET_VERSION)
    plugin_status = status(upgrade.TARGET_VERSION)
    routes = set(upgrade.LIFECYCLE_ROUTES | {upgrade.PREVIEW_ROUTE, upgrade.CACHE_PURGE_ROUTE, upgrade.LEGACY_ROUTE})
    preview = {"status_code": 409, "code": "atlas_rendering_preview_unavailable", "request_method": "GET", "output_verification_deferred": True}
    if case == "preview_route_missing":
        routes.remove(upgrade.PREVIEW_ROUTE)
    elif case == "preview_output_returned":
        preview.update(status_code=200, code=None)
    elif case == "preview_wrong_code":
        preview["code"] = "wrong_disabled_contract"
    elif case == "cache_route_missing":
        routes.remove(upgrade.CACHE_PURGE_ROUTE)
    elif case == "payload_changed":
        plugin_status["snapshot"]["payload_hash"] = "f" * 64
    elif case == "rendering_enabled":
        plugin_status["snapshot"]["rendering_enabled"] = True
    elif case == "page_changed":
        after["page_snapshot_hash"] = "f" * 64
    elif case == "media_changed":
        after["media31_snapshot_hash"] = "f" * 64
    elif case == "cache_purged":
        after["cache_purge_count"] = 1
    state = SimpleNamespace(status="staged", payload_hash=PAYLOAD_HASH, wordpress_revision="1", payload=deepcopy(PAYLOAD))
    gates = upgrade._post_upgrade_gates(
        request(before), before, after, plugin_status,
        bootstrap_status(available=False, plugin_version=upgrade.TARGET_VERSION),
        {"routes": sorted(routes), "legacy_route_registered": True, "request_method": "GET"},
        preview, [state], [],
    )
    assert failed_gate in {gate.code for gate in gates if not gate.passed}


@pytest.mark.parametrize("case,failed_gate", [
    ("bootstrap_010", "upgrade_bootstrap"),
    ("page", "page_snapshot"),
    ("media", "media31"),
    ("audit", "previous_upgrade_audit"),
    ("runtime", "repository_identity"),
])
def test_0576_bound_preflight_failures_issue_no_handle(monkeypatch, db, case, failed_gate):
    before = configure(monkeypatch)
    changes = {}
    if case == "bootstrap_010":
        wrong = bootstrap_status()
        wrong["bootstrap_version"] = "0.1.0"
        monkeypatch.setattr(upgrade, "_read_bootstrap_status", lambda session: wrong)
    elif case == "page":
        changes["expected_page_snapshot_hash"] = "f" * 64
    elif case == "media":
        changes["expected_media31_snapshot_hash"] = "f" * 64
    elif case == "audit":
        changes["previous_upgrade_audit_id"] = 99
    elif case == "runtime":
        changes["repository_tag"] = "v0.59.70"
    with Session(db) as session:
        seed(session)
        result = upgrade.plugin_upgrade_preflight(session, 41, request(before, **changes))
        assert not result.plugin_upgrade_preflight_ready and result.upgrade_handle is None
        assert failed_gate in {gate.code for gate in result.gate_results if not gate.passed}
        assert len(session.exec(select(WordPressPluginUpgradeAudit)).all()) == 2


def test_bootstrap_020_and_target_artifacts_are_exact_and_portable():
    bootstrap, gates = upgrade._verify_bootstrap_artifact()
    assert all(g.passed for g in gates)
    assert bootstrap["zip_sha256"] == upgrade.BOOTSTRAP_ZIP_SHA256
    current, current_gates = upgrade._verify_current_artifact()
    assert all(g.passed for g in current_gates)
    assert current["zip_sha256"] == upgrade.CURRENT_ZIP_SHA256
    assert deployment.ZIP_SHA256 == "ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62"
    with zipfile.ZipFile(upgrade.resolve_program_root() / "wordpress/dist" / upgrade.BOOTSTRAP_ZIP_NAME) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist())) == 2
        php = archive.read("project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap.php").decode()
    assert "0.57.6_to_0.57.7" in php and "ATLAS_UPGRADE_BOOTSTRAP_PAYLOAD_SHA256" in php
    assert "overwrite_package' => true" in php and "is_uploaded_file" in php
    for forbidden in ("wp_remote_get", "download_url", "ftp_", "ssh", "activate_plugin(", "deactivate_plugins("):
        assert forbidden not in php


def test_0576_write_surface_is_one_fixed_bootstrap_request():
    source = inspect.getsource(upgrade._send_fixed_upgrade)
    assert "client.post" in source and "BOOTSTRAP_UPGRADE_ROUTE" in source and 'files={"artifact"' in source
    for forbidden in ("wp/v2/pages", "wp/v2/media", "rendering/enable", "purge", "client.put", "client.patch", "DELETE", "cookie"):
        assert forbidden not in source
    preflight = inspect.getsource(upgrade.plugin_upgrade_preflight)
    assert "session.commit" not in preflight and "_send_fixed_upgrade" not in preflight
