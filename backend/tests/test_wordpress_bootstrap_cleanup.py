from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import inspect

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import backup as backup_service
from app.main import app
from app.models import WordPressBootstrapCleanupAudit, WordPressPluginUpgradeAudit
from app.schemas.wordpress import (
    WordPressBootstrapCleanupApplyRequest,
    WordPressBootstrapCleanupPreflightRequest,
    WordPressBootstrapDeletionPreflightRequest,
)
from app.services import wordpress_bootstrap_cleanup as cleanup
from app.services import wordpress_plugin_upgrade as upgrade
from test_wordpress_plugin_upgrade import (
    COMMIT,
    KEY,
    MANIFEST,
    MEDIA31_HASH,
    MEDIA32_HASH,
    PAGE_HASH,
    SOURCE_COMPATIBILITY,
    VERSION,
    artifact,
    bootstrap_status,
    evidence,
    observation as upgrade_observation,
    proof,
    seed as seed_upgrade_dependencies,
    status,
)


@pytest.fixture(autouse=True)
def cleanup_handles(monkeypatch):
    cleanup._clear_cleanup_handles()
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    yield
    cleanup._clear_cleanup_handles()


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'bootstrap-cleanup.sqlite3').as_posix()}")
    SQLModel.metadata.create_all(engine)
    return engine


def observation(*, bootstrap_state: str | None = "active"):
    value = upgrade_observation(upgrade.TARGET_VERSION)
    if bootstrap_state is not None:
        value["plugins"].append(
            {
                "plugin": "project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap",
                "version": upgrade.BOOTSTRAP_VERSION,
                "status": bootstrap_state,
            }
        )
    value["active_plugins"] = sorted(
        item["plugin"]
        for item in value["plugins"]
        if item["status"] in {"active", "network-active"}
    )
    value["plugin_inventory_hash"] = cleanup._hash(value["plugins"])
    value["active_plugin_inventory_hash"] = cleanup._hash(value["active_plugins"])
    return value


def refresh_inventories(value):
    value["active_plugins"] = sorted(
        item["plugin"]
        for item in value["plugins"]
        if item["status"] in {"active", "network-active"}
    )
    value["plugin_inventory_hash"] = cleanup._hash(value["plugins"])
    value["active_plugin_inventory_hash"] = cleanup._hash(value["active_plugins"])
    return value


def request(before=None, **changes):
    before = before or observation()
    value = {
        **proof(),
        "installation_audit_id": 1,
        "activation_audit_id": 1,
        "upgrade_audit_id": 1,
        "operator": "Shawn Manchette",
        "expected_bridge_slug": cleanup.PLUGIN_SLUG,
        "expected_bridge_path": cleanup.PLUGIN_FILE,
        "expected_bridge_version": upgrade.TARGET_VERSION,
        "expected_bridge_zip_sha256": cleanup._verify_artifact()[0]["zip_sha256"],
        "expected_bootstrap_slug": cleanup.BOOTSTRAP_SLUG,
        "expected_bootstrap_path": cleanup.BOOTSTRAP_ENTRY,
        "expected_bootstrap_version": upgrade.BOOTSTRAP_VERSION,
        "expected_bootstrap_zip_sha256": upgrade.BOOTSTRAP_ZIP_SHA256,
        "expected_plugin_inventory_hash": before["plugin_inventory_hash"],
        "expected_active_plugin_inventory_hash": before["active_plugin_inventory_hash"],
        "expected_page_snapshot_hash": PAGE_HASH,
        "expected_body_hash": cleanup.EXPECTED_CORRECTED_BODY_HASH,
        "expected_media31_snapshot_hash": MEDIA31_HASH,
        "expected_media32_snapshot_hash": MEDIA32_HASH,
        "expected_runtime_identity": {
            "atlas_version": VERSION,
            "atlas_commit": COMMIT,
            "atlas_tag": VERSION,
            "manifest_sha256": MANIFEST,
            "source_compatibility_id": SOURCE_COMPATIBILITY,
        },
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
    session.add(
        WordPressPluginUpgradeAudit(
            id=1,
            generated_page_id=41,
            wordpress_post_id=8,
            installation_audit_id=1,
            activation_audit_id=1,
            status="verified",
            operator="Shawn Manchette",
            confirmation_phrase_hash="a" * 64,
            handle_fingerprint="d" * 64,
            binding_hash="e" * 64,
            previous_version=upgrade.CURRENT_VERSION,
            target_version=upgrade.TARGET_VERSION,
            previous_artifact_sha256=upgrade.CURRENT_ZIP_SHA256,
            target_artifact_sha256=artifact()["zip_sha256"],
            release_identity={},
            backup_evidence={},
            browser_evidence_id="upgrade",
            browser_evidence_hashes={},
            pre_snapshot={},
            post_snapshot={},
            previous_inventories={},
            final_inventories={},
            metadata_rendering_state={},
            page_media_snapshots={},
            gate_results=[],
            wordpress_write_count=1,
            atlas_write_count=2,
            recovery_recommendation="no_action",
            transition_history=["pending", "verified"],
            completed_at=datetime.now(UTC),
        )
    )
    session.commit()


def configure(monkeypatch, states):
    queue = [deepcopy(item) for item in states]
    current = {"value": deepcopy(queue[0])}

    def observe(session, backup):
        if queue:
            current["value"] = queue.pop(0)
        return deepcopy(current["value"])

    def bootstrap_read(session):
        state = cleanup._bootstrap_matches(current["value"])
        if state and state[0]["status"] in {"active", "network-active"}:
            return bootstrap_status(available=False, plugin_version=upgrade.TARGET_VERSION)
        return {"status_code": 404, "request_method": "GET", "_error": "not_found"}

    def route_read(session):
        state = cleanup._bootstrap_matches(current["value"])
        routes = set(upgrade.LIFECYCLE_ROUTES) | {upgrade.LEGACY_ROUTE}
        if state and state[0]["status"] in {"active", "network-active"}:
            routes |= {upgrade.BOOTSTRAP_STATUS_ROUTE, upgrade.BOOTSTRAP_UPGRADE_ROUTE}
        return {
            "routes": sorted(routes),
            "legacy_route_registered": True,
            "request_method": "GET",
            "status_code": 200,
        }

    monkeypatch.setattr(cleanup, "_observe", observe)
    monkeypatch.setattr(cleanup, "_read_plugin_status", lambda session: status(upgrade.TARGET_VERSION))
    monkeypatch.setattr(cleanup, "_read_bootstrap_status", bootstrap_read)
    monkeypatch.setattr(cleanup, "_read_route_registry", route_read)
    monkeypatch.setattr(cleanup, "_verify_artifact", lambda: (artifact(), [cleanup._gate("release_identity", "release", True, "")]))
    monkeypatch.setattr(
        cleanup,
        "_verify_bootstrap_artifact",
        lambda: (
            {"zip_sha256": upgrade.BOOTSTRAP_ZIP_SHA256, "entry_sha256": upgrade.BOOTSTRAP_ENTRY_SHA256},
            [cleanup._gate("bootstrap_artifact_files", "bootstrap", True, "")],
        ),
    )
    monkeypatch.setattr(cleanup, "_backup_gates", lambda backup: [cleanup._gate("backups", "backups", True, "")])
    return current


def test_cleanup_routes_are_distinct_and_post_only():
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert ("/api/wordpress/deployment/upgrade-bootstrap/cleanup/preflight/{page_id}", "POST") in routes
    assert ("/api/wordpress/deployment/upgrade-bootstrap/cleanup/deactivate/{page_id}", "POST") in routes
    assert ("/api/wordpress/deployment/upgrade-bootstrap/cleanup/delete/preflight/{page_id}", "POST") in routes
    assert ("/api/wordpress/deployment/upgrade-bootstrap/cleanup/delete/apply/{page_id}", "POST") in routes


def test_deactivation_preflight_is_zero_write_and_returns_single_use_handle(monkeypatch, db):
    before = observation()
    configure(monkeypatch, [before])
    with Session(db) as session:
        seed(session)
        result = cleanup.cleanup_preflight(session, 41, request(before))
        assert result.bootstrap_cleanup_preflight_ready and result.cleanup_handle, [
            (gate.code, gate.message) for gate in result.gate_results if not gate.passed
        ]
        assert result.confirmation_phrase == cleanup.DEACTIVATION_PHRASE
        assert result.wordpress_write_count == result.atlas_write_count == 0
        assert result.token_issued is result.nonce_consumed is result.audit_created is False
        assert session.exec(select(WordPressBootstrapCleanupAudit)).first() is None


def test_deactivation_uses_one_fixed_write_and_keeps_bootstrap_installed(monkeypatch, db):
    before = observation()
    after = observation(bootstrap_state="inactive")
    configure(monkeypatch, [before, before, after])
    calls = []

    def send(session):
        pending = session.exec(select(WordPressBootstrapCleanupAudit)).one()
        assert pending.status == "pending" and pending.wordpress_write_count == 0
        calls.append(("POST", {"status": "inactive"}))
        return {"status_code": 200, "accepted": True, "method": "POST"}

    monkeypatch.setattr(cleanup, "_send_deactivation", send)
    with Session(db) as session:
        seed(session)
        preflight = cleanup.cleanup_preflight(session, 41, request(before))
        result = cleanup.deactivate_bootstrap(
            session,
            41,
            WordPressBootstrapCleanupApplyRequest(
                cleanup_handle=preflight.cleanup_handle,
                confirmation_phrase=cleanup.DEACTIVATION_PHRASE,
            ),
        )
        assert result.status == "deactivated" and result.wordpress_write_count == 1, [
            (gate.code, gate.message) for gate in result.gate_results if not gate.passed
        ]
        assert result.atlas_write_count == 2 and calls == [("POST", {"status": "inactive"})]
        saved = session.get(WordPressBootstrapCleanupAudit, result.cleanup_audit_id)
        assert saved.transition_history == ["pending", "deactivated"]


def test_deletion_is_separately_gated_and_uses_one_fixed_delete(monkeypatch, db):
    active = observation()
    inactive = observation(bootstrap_state="inactive")
    absent = observation(bootstrap_state=None)
    configure(monkeypatch, [active, active, inactive])
    with Session(db) as session:
        seed(session)
        first = cleanup.cleanup_preflight(session, 41, request(active))
        monkeypatch.setattr(cleanup, "_send_deactivation", lambda session: {"status_code": 200, "accepted": True})
        deactivated = cleanup.deactivate_bootstrap(
            session,
            41,
            WordPressBootstrapCleanupApplyRequest(cleanup_handle=first.cleanup_handle, confirmation_phrase=cleanup.DEACTIVATION_PHRASE),
        )

        configure(monkeypatch, [inactive, inactive, absent])
        deletion_request = WordPressBootstrapDeletionPreflightRequest(
            **request(inactive).model_dump(), cleanup_audit_id=deactivated.cleanup_audit_id
        )
        second = cleanup.deletion_preflight(session, 41, deletion_request)
        assert second.bootstrap_cleanup_preflight_ready, [
            (gate.code, gate.message) for gate in second.gate_results if not gate.passed
        ]
        assert second.confirmation_phrase == cleanup.DELETION_PHRASE
        calls = []
        monkeypatch.setattr(cleanup, "_send_deletion", lambda session: calls.append(("DELETE", None)) or {"status_code": 200, "accepted": True})
        result = cleanup.delete_bootstrap(
            session,
            41,
            WordPressBootstrapCleanupApplyRequest(cleanup_handle=second.cleanup_handle, confirmation_phrase=cleanup.DELETION_PHRASE),
        )
        assert result.status == "verified" and result.wordpress_write_count == 1
        assert calls == [("DELETE", None)]
        saved = session.get(WordPressBootstrapCleanupAudit, deactivated.cleanup_audit_id)
        assert saved.wordpress_write_count == 2
        assert saved.transition_history == ["pending", "deactivated", "pending", "verified"]


def test_wrong_phrase_replay_and_restart_fail_closed(monkeypatch, db):
    before = observation()
    configure(monkeypatch, [before])
    with Session(db) as session:
        seed(session)
        preflight = cleanup.cleanup_preflight(session, 41, request(before))
        with pytest.raises(HTTPException, match="phrase"):
            cleanup.deactivate_bootstrap(
                session,
                41,
                WordPressBootstrapCleanupApplyRequest(cleanup_handle=preflight.cleanup_handle, confirmation_phrase="WRONG"),
            )
        assert preflight.cleanup_handle in cleanup._handles
        cleanup._clear_cleanup_handles()
        with pytest.raises(HTTPException, match="invalidated by restart"):
            cleanup.deactivate_bootstrap(
                session,
                41,
                WordPressBootstrapCleanupApplyRequest(cleanup_handle=preflight.cleanup_handle, confirmation_phrase=cleanup.DEACTIVATION_PHRASE),
            )


@pytest.mark.parametrize(
    "change,failed",
    [
        ({"repository_working_tree_clean": False}, "repository_clean"),
        ({"protected_paths_unchanged": False}, "protected_paths"),
        ({"no_relevant_wordpress_change_after_backup": False}, "no_post_backup_change"),
        ({"expected_page_snapshot_hash": "f" * 64}, "page_snapshot"),
        ({"expected_plugin_inventory_hash": "f" * 64}, "plugin_inventory"),
    ],
)
def test_drift_blocks_without_handle_audit_or_write(monkeypatch, db, change, failed):
    before = observation()
    configure(monkeypatch, [before])
    with Session(db) as session:
        seed(session)
        result = cleanup.cleanup_preflight(session, 41, request(before, **change))
        assert not result.bootstrap_cleanup_preflight_ready and result.cleanup_handle is None
        assert failed in {gate.code for gate in result.gate_results if not gate.passed}
        assert session.exec(select(WordPressBootstrapCleanupAudit)).first() is None


@pytest.mark.parametrize(
    "case,failed",
    [
        ("bridge_inactive", "bridge_active"),
        ("bootstrap_missing", "bootstrap_singleton"),
        ("bootstrap_duplicate", "bootstrap_singleton"),
        ("bootstrap_wrong_version", "bootstrap_identity"),
        ("bootstrap_upgrade_available", "bootstrap_fail_closed"),
        ("upgrade_audit_unverified", "upgrade_audit"),
        ("rendering_enabled", "rendering_disabled"),
        ("payload_present", "payload_absent"),
        ("revision_changed", "revision_zero"),
    ],
)
def test_plugin_bootstrap_audit_and_metadata_failures_block(monkeypatch, db, case, failed):
    before = observation()
    if case == "bridge_inactive":
        before["plugins"][0]["status"] = "inactive"
        refresh_inventories(before)
    elif case == "bootstrap_missing":
        before = observation(bootstrap_state=None)
    elif case == "bootstrap_duplicate":
        before["plugins"].append(deepcopy(before["plugins"][-1]))
        refresh_inventories(before)
    elif case == "bootstrap_wrong_version":
        before["plugins"][-1]["version"] = "0.0.9"
        refresh_inventories(before)
    configure(monkeypatch, [before])
    if case == "bootstrap_upgrade_available":
        monkeypatch.setattr(cleanup, "_read_bootstrap_status", lambda session: bootstrap_status(available=True, plugin_version=upgrade.TARGET_VERSION))
    if case in {"rendering_enabled", "payload_present", "revision_changed", "bridge_inactive"}:
        current_status = status(upgrade.TARGET_VERSION)
        if case == "rendering_enabled":
            current_status["snapshot"]["rendering_enabled"] = True
        elif case == "payload_present":
            current_status["snapshot"]["payload"] = {"metadata": "unexpected"}
            current_status["snapshot"]["payload_hash"] = "f" * 64
        elif case == "revision_changed":
            current_status["snapshot"]["revision"] = "1"
        elif case == "bridge_inactive":
            current_status["active"] = False
        monkeypatch.setattr(cleanup, "_read_plugin_status", lambda session: current_status)
    with Session(db) as session:
        seed(session)
        if case == "upgrade_audit_unverified":
            audit = session.get(WordPressPluginUpgradeAudit, 1)
            audit.status = "verification_failed"
            session.add(audit)
            session.commit()
        result = cleanup.cleanup_preflight(session, 41, request(before))
        assert not result.bootstrap_cleanup_preflight_ready and result.cleanup_handle is None
        assert failed in {gate.code for gate in result.gate_results if not gate.passed}
        assert session.exec(select(WordPressBootstrapCleanupAudit)).first() is None


@pytest.mark.parametrize("failure", ["namespace_still_active", "unrelated_plugin_changed"])
def test_post_deactivation_drift_never_retries_or_reports_success(monkeypatch, db, failure):
    before = observation()
    after = observation(bootstrap_state="inactive")
    if failure == "unrelated_plugin_changed":
        after["plugins"].append({"plugin": "unexpected/plugin", "version": "1.0", "status": "inactive"})
        refresh_inventories(after)
    configure(monkeypatch, [before, before, after])
    if failure == "namespace_still_active":
        monkeypatch.setattr(cleanup, "_read_bootstrap_status", lambda session: bootstrap_status(available=False, plugin_version=upgrade.TARGET_VERSION))
        monkeypatch.setattr(
            cleanup,
            "_read_route_registry",
            lambda session: {
                "routes": sorted(upgrade.LIFECYCLE_ROUTES | {upgrade.LEGACY_ROUTE, upgrade.BOOTSTRAP_STATUS_ROUTE, upgrade.BOOTSTRAP_UPGRADE_ROUTE}),
                "legacy_route_registered": True,
                "request_method": "GET",
            },
        )
    calls = []
    monkeypatch.setattr(cleanup, "_send_deactivation", lambda session: calls.append("deactivate") or {"status_code": 200, "accepted": True})
    with Session(db) as session:
        seed(session)
        preflight = cleanup.cleanup_preflight(session, 41, request(before))
        result = cleanup.deactivate_bootstrap(
            session,
            41,
            WordPressBootstrapCleanupApplyRequest(cleanup_handle=preflight.cleanup_handle, confirmation_phrase=cleanup.DEACTIVATION_PHRASE),
        )
        assert result.status == "verification_failed"
        assert calls == ["deactivate"] and result.wordpress_write_count == 1
        assert result.recovery_recommendation in {"no_action", "guarded_reactivation", "siteground_restore"}


def test_fixed_wordpress_mutations_do_not_accept_caller_target_or_body():
    apply_fields = set(WordPressBootstrapCleanupApplyRequest.model_fields)
    assert apply_fields == {"cleanup_handle", "confirmation_phrase"}
    source = inspect.getsource(cleanup._fixed_plugin_request)
    assert "BOOTSTRAP_SLUG" in source
    assert 'if body is not None' in source
    assert cleanup.DEACTIVATION_WORDPRESS_SCOPE[0] == (
        "POST /wp-json/wp/v2/plugins/project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap"
    )
    assert cleanup.DEACTIVATION_WORDPRESS_SCOPE[1] == 'JSON body exactly {"status":"inactive"}'
    assert cleanup.DELETION_WORDPRESS_SCOPE[0] == (
        "DELETE /wp-json/wp/v2/plugins/project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap"
    )
    assert "body" in cleanup.DELETION_WORDPRESS_SCOPE[1]


def test_cleanup_audit_is_in_data_backup_v036_contract():
    assert backup_service.BACKUP_VERSION == "0.36"
    assert backup_service.BACKUP_MODELS["wordpress_bootstrap_cleanup_audits"] is WordPressBootstrapCleanupAudit
    assert "0.35" in backup_service.SUPPORTED_BACKUP_VERSIONS
