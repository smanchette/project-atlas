from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import WordPressBootstrapEstablishmentAudit
from app.schemas.wordpress import (
    WordPressBootstrapActivationApplyRequest,
    WordPressBootstrapManualInstallAuthorizeRequest,
    WordPressBootstrapManualInstallPreflightRequest,
    WordPressBootstrapManualInstallVerifyRequest,
)
from app.services import wordpress_bootstrap_establishment as establishment
from app.services import wordpress_plugin_upgrade_0577 as upgrade
from app.db import backup as backup_service
from test_wordpress_plugin_upgrade_0577 import observation, request as upgrade_request


@pytest.fixture(autouse=True)
def clear_handles():
    establishment._clear_establishment_handles()
    yield
    establishment._clear_establishment_handles()


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'establishment.sqlite3').as_posix()}")
    SQLModel.metadata.create_all(engine)
    return engine


def proof():
    return WordPressBootstrapManualInstallPreflightRequest.model_validate(upgrade_request().model_dump())


def verify_proof(audit_id):
    return WordPressBootstrapManualInstallVerifyRequest(**proof().model_dump(), establishment_audit_id=audit_id)


def verified_audit(db, monkeypatch):
    current = {"state": "absent"}
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base(current["state"]))
    monkeypatch.setattr(establishment, "_expiry", lambda request: datetime.now(UTC) + timedelta(minutes=5))
    with Session(db) as session:
        preflight = establishment.manual_install_preflight(session, 41, proof())
        authorization = establishment.authorize_manual_install(
            session,
            41,
            WordPressBootstrapManualInstallAuthorizeRequest(
                manual_install_handle=preflight.handle,
                confirmation_phrase=establishment.MANUAL_PHRASE,
            ),
        )
        audit_id = authorization.establishment_audit_id
    current["state"] = "inactive"
    request = verify_proof(audit_id)
    with Session(db) as session:
        first = establishment.verify_manual_install(session, 41, request)
    return current, audit_id, request, first


def authorized_audit(db, monkeypatch):
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base("absent"))
    monkeypatch.setattr(establishment, "_expiry", lambda request: datetime.now(UTC) + timedelta(minutes=5))
    with Session(db) as session:
        preflight = establishment.manual_install_preflight(session, 41, proof())
        authorization = establishment.authorize_manual_install(
            session,
            41,
            WordPressBootstrapManualInstallAuthorizeRequest(
                manual_install_handle=preflight.handle,
                confirmation_phrase=establishment.MANUAL_PHRASE,
            ),
        )
    return authorization.establishment_audit_id, verify_proof(authorization.establishment_audit_id)


def snapshot(state="absent"):
    value = observation()
    value["plugins"] = [item for item in value["plugins"] if not item["plugin"].startswith(establishment.BOOTSTRAP_DIRECTORY)]
    value["active_plugins"] = sorted(item["plugin"] for item in value["plugins"] if item["status"] == "active")
    if state in {"inactive", "active"}:
        item = {"plugin": establishment.BOOTSTRAP_REST_ID, "version": "0.3.0", "status": state}
        value["plugins"].append(item)
        if state == "active":
            value["active_plugins"].append(establishment.BOOTSTRAP_REST_ID)
            value["active_plugins"].sort()
    value["plugin_inventory_hash"] = upgrade._hash(value["plugins"])
    value["active_plugin_inventory_hash"] = upgrade._hash(value["active_plugins"])
    value["plugin_status"] = {"snapshot": {"rendering_enabled": False, "payload_hash": upgrade.EXPECTED_PAYLOAD_HASH, "revision": "1", "payload": {"locked": True}}}
    return value


def base(state="absent"):
    return SimpleNamespace(
        inspected_state=snapshot(state), artifact={}, backup_deadline=datetime.now(UTC) + timedelta(hours=3),
        gate_results=[
            establishment._gate("release_identity", "Release", True, ""),
            establishment._gate("upgrade_bootstrap", "Bootstrap", False, "absent"),
            establishment._gate("bootstrap_establishment_audit", "Establishment", False, "not established yet"),
            establishment._gate("plugin_inventory", "Inventory", state == "absent", "changed"),
            establishment._gate("read_only_preflight", "Read only", True, ""),
        ],
    )


def test_manual_handoff_and_fixed_activation_success(db, monkeypatch):
    current = {"state": "absent"}
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base(current["state"]))
    monkeypatch.setattr(establishment, "_expiry", lambda request: datetime.now(UTC) + timedelta(minutes=5))
    monkeypatch.setattr(establishment, "_activate_fixed_entry", lambda session: current.update(state="active") or {"accepted": True, "request_performed": True, "request_keys": ["status"], "status_code": 200})
    monkeypatch.setattr(upgrade, "_read_bootstrap_status", lambda session: {
        "bootstrap": establishment.BOOTSTRAP_SLUG, "bootstrap_version": "0.3.0",
        "bootstrap_checksum": establishment.BOOTSTRAP_ENTRY_SHA256,
        "operation": "upgrade_metadata_bridge_0.57.6_to_0.57.7",
        "target_plugin": "project-atlas-metadata-bridge/project-atlas-metadata-bridge.php",
        "current_version": "0.57.6", "target_version": "0.57.7",
        "target_zip_sha256": "ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62",
        "status_code": 200, "request_method": "GET",
    })
    with Session(db) as session:
        preflight = establishment.manual_install_preflight(session, 41, proof())
        assert preflight.ready and preflight.handle and preflight.wordpress_write_count == 0
        authorization = establishment.authorize_manual_install(session, 41, WordPressBootstrapManualInstallAuthorizeRequest(manual_install_handle=preflight.handle, confirmation_phrase=establishment.MANUAL_PHRASE))
        assert authorization.status == "awaiting_manual_bootstrap_installation"
        assert authorization.wordpress_write_count == 0
        assert authorization.request_atlas_write_count == 1
        current["state"] = "inactive"
        verified = establishment.verify_manual_install(session, 41, verify_proof(authorization.establishment_audit_id))
        assert verified.status == "manual_installation_inventory_verified"
        assert verified.request_atlas_write_count == 1
        activation = establishment.activation_preflight(session, 41, verify_proof(authorization.establishment_audit_id))
        assert activation.ready and activation.handle and activation.handle != preflight.handle
        result = establishment.apply_activation(session, 41, WordPressBootstrapActivationApplyRequest(activation_handle=activation.handle, confirmation_phrase=establishment.ACTIVATION_PHRASE))
        assert result.status == "verified"
        assert result.request_atlas_write_count == 2
        assert result.wordpress_write_count == 1
        assert result.wordpress_write_scope == establishment.ACTIVATION_SCOPE
        audit = session.exec(select(WordPressBootstrapEstablishmentAudit)).one()
        assert audit.checksum_verification_result == "matched"
        assert audit.inactive_checksum_verifiable is False and audit.approved_residual_risk is True


def test_no_upload_remains_waiting(db, monkeypatch):
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base("absent"))
    monkeypatch.setattr(establishment, "_expiry", lambda request: datetime.now(UTC) + timedelta(minutes=5))
    with Session(db) as session:
        preflight = establishment.manual_install_preflight(session, 41, proof())
        auth = establishment.authorize_manual_install(session, 41, WordPressBootstrapManualInstallAuthorizeRequest(manual_install_handle=preflight.handle, confirmation_phrase=establishment.MANUAL_PHRASE))
        result = establishment.verify_manual_install(session, 41, verify_proof(auth.establishment_audit_id))
        assert result.status == "awaiting_manual_bootstrap_installation"
        assert result.wordpress_write_count == result.cache_write_count == 0


def test_two_manual_install_verifications_finalize_once(db, monkeypatch):
    current = {"state": "absent"}
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base(current["state"]))
    monkeypatch.setattr(establishment, "_expiry", lambda request: datetime.now(UTC) + timedelta(minutes=5))
    with Session(db) as session:
        preflight = establishment.manual_install_preflight(session, 41, proof())
        authorization = establishment.authorize_manual_install(
            session,
            41,
            WordPressBootstrapManualInstallAuthorizeRequest(
                manual_install_handle=preflight.handle,
                confirmation_phrase=establishment.MANUAL_PHRASE,
            ),
        )
        audit_id = authorization.establishment_audit_id
    current["state"] = "inactive"
    request = verify_proof(audit_id)

    def verify_once():
        with Session(db) as session:
            return establishment.verify_manual_install(session, 41, request.model_copy(deep=True)).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: verify_once(), range(2)))

    assert statuses == ["manual_installation_inventory_verified"] * 2
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert audit.transition_history.count("manual_installation_inventory_verified") == 1
        assert audit.atlas_write_count == 2


def test_second_and_third_equivalent_retries_are_zero_write(db, monkeypatch):
    _, audit_id, request, first = verified_audit(db, monkeypatch)
    assert first.request_atlas_write_count == 1 and first.idempotent_replay is False
    for _ in range(2):
        with Session(db) as session:
            replay = establishment.verify_manual_install(session, 41, request)
            assert replay.status == "manual_installation_inventory_verified"
            assert replay.idempotent_replay is True
            assert replay.request_atlas_write_count == 0
            assert replay.reason_code == "manual_install_verification_idempotent_replay"
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert audit.transition_history.count("manual_installation_inventory_verified") == 1
        assert audit.atlas_write_count == 2


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("protected", "manual_install_protected_state_drift"),
        ("inventory", "manual_install_inventory_drift"),
        ("backup", "manual_install_backup_identity_drift"),
        ("evidence", "manual_install_evidence_mismatch"),
        ("backup_expired", "manual_install_request_stale"),
        ("evidence_expired", "manual_install_request_stale"),
        ("runtime", "manual_install_retry_not_equivalent"),
    ],
)
def test_non_equivalent_retry_after_success_is_zero_write_conflict(db, monkeypatch, change, reason):
    _, audit_id, request, _ = verified_audit(db, monkeypatch)
    retry = request.model_copy(deep=True)
    observed = base("inactive")
    if change == "protected":
        observed.inspected_state["page_body_hash"] = "f" * 64
    elif change == "inventory":
        observed.inspected_state["plugins"].append({"plugin": "unrelated/drift", "version": "1.0", "status": "inactive"})
        observed.inspected_state["plugin_inventory_hash"] = upgrade._hash(observed.inspected_state["plugins"])
    elif change == "backup":
        retry.wordpress_backup_reference = "different-backup-reference"
    elif change == "evidence":
        retry.manual_browser_evidence.evidence_id = "orlando-different-evidence"
    elif change == "backup_expired":
        monkeypatch.setattr(establishment, "_expired", lambda value: True)
    elif change == "evidence_expired":
        retry.manual_browser_evidence.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    elif change == "runtime":
        retry.expected_runtime_identity.atlas_commit = "f" * 40
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: observed)

    with Session(db) as session:
        with pytest.raises(HTTPException) as caught:
            establishment.verify_manual_install(session, 41, retry)
        assert caught.value.status_code == 409
        assert caught.value.detail["reason_code"] == reason
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert audit.status == "manual_installation_inventory_verified"
        assert audit.transition_history.count("manual_installation_inventory_verified") == 1
        assert audit.atlas_write_count == 2


def test_three_simultaneous_equivalent_verifications_commit_once(db, monkeypatch):
    current = {"state": "absent"}
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base(current["state"]))
    monkeypatch.setattr(establishment, "_expiry", lambda request: datetime.now(UTC) + timedelta(minutes=5))
    with Session(db) as session:
        preflight = establishment.manual_install_preflight(session, 41, proof())
        authorization = establishment.authorize_manual_install(
            session, 41,
            WordPressBootstrapManualInstallAuthorizeRequest(
                manual_install_handle=preflight.handle, confirmation_phrase=establishment.MANUAL_PHRASE,
            ),
        )
        audit_id = authorization.establishment_audit_id
    current["state"] = "inactive"
    request = verify_proof(audit_id)

    def verify_once():
        with Session(db) as session:
            return establishment.verify_manual_install(session, 41, request.model_copy(deep=True))

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: verify_once(), range(3)))
    assert sum(result.request_atlas_write_count for result in results) == 1
    assert sum(result.idempotent_replay for result in results) == 2
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert audit.status == "manual_installation_inventory_verified"
        assert audit.transition_history.count("manual_installation_inventory_verified") == 1
        assert audit.atlas_write_count == 2


@pytest.mark.parametrize("loser", ["protected_drift", "expired_backup"])
def test_valid_verification_racing_with_conflict_cannot_be_overwritten(db, monkeypatch, loser):
    audit_id, valid = authorized_audit(db, monkeypatch)
    conflicting = valid.model_copy(deep=True)
    conflicting.browser_console_findings = loser
    valid_entered = Event()
    release_valid = Event()

    def inspect(*args, **kwargs):
        request = args[2]
        if request.browser_console_findings != loser:
            valid_entered.set()
            assert release_valid.wait(timeout=5)
            return base("inactive")
        observed = base("inactive")
        if loser == "protected_drift":
            observed.inspected_state["page_body_hash"] = "f" * 64
        return observed

    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", inspect)
    original_expired = establishment._expired
    if loser == "expired_backup":
        monkeypatch.setattr(
            establishment,
            "_expired",
            lambda request: request.browser_console_findings == loser or original_expired(request),
        )

    def verify(request):
        with Session(db) as session:
            try:
                return establishment.verify_manual_install(session, 41, request)
            except HTTPException as exc:
                return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(verify, valid)
        assert valid_entered.wait(timeout=5)
        conflict = pool.submit(verify, conflicting)
        release_valid.set()
        winner_result = winner.result(timeout=10)
        conflict_result = conflict.result(timeout=10)

    assert winner_result.status == "manual_installation_inventory_verified"
    assert winner_result.request_atlas_write_count == 1
    assert isinstance(conflict_result, HTTPException) and conflict_result.status_code == 409
    expected_reason = "manual_install_protected_state_drift" if loser == "protected_drift" else "manual_install_request_stale"
    assert conflict_result.detail["reason_code"] == expected_reason
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert audit.status == "manual_installation_inventory_verified"
        assert audit.transition_history.count("manual_installation_inventory_verified") == 1
        assert audit.atlas_write_count == 2


def test_restart_timeout_and_transaction_retry_preserve_idempotent_success(db, monkeypatch):
    _, audit_id, request, _ = verified_audit(db, monkeypatch)
    establishment._clear_establishment_handles()
    for _ in range(3):
        with Session(db) as session:
            replay = establishment.verify_manual_install(session, 41, request)
            assert replay.idempotent_replay and replay.request_atlas_write_count == 0
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert audit.status == "manual_installation_inventory_verified"
        assert audit.atlas_write_count == 2


def test_conflicting_retry_does_not_erase_activation_eligibility(db, monkeypatch):
    _, audit_id, request, _ = verified_audit(db, monkeypatch)
    drift = base("inactive")
    drift.inspected_state["page_body_hash"] = "f" * 64
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: drift)
    with Session(db) as session:
        with pytest.raises(HTTPException):
            establishment.verify_manual_install(session, 41, request)
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base("inactive"))
    with Session(db) as session:
        activation = establishment.activation_preflight(session, 41, request)
        assert activation.ready


def test_recovery_assessment_reports_drift_without_mutating_verified_checkpoint(db, monkeypatch):
    _, audit_id, request, _ = verified_audit(db, monkeypatch)
    drift = base("inactive")
    drift.inspected_state["page_body_hash"] = "f" * 64
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: drift)
    with Session(db) as session:
        before = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        before_history = list(before.transition_history)
        before_writes = before.atlas_write_count
        result = establishment.assess_recovery(session, 41, request)
        assert result.recommendation == "siteground_restore"
    with Session(db) as session:
        after = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert after.status == "manual_installation_inventory_verified"
        assert after.transition_history == before_history
        assert after.atlas_write_count == before_writes


def test_pre_success_failure_still_records_approved_transition(db, monkeypatch):
    current = {"state": "absent"}
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base(current["state"]))
    monkeypatch.setattr(establishment, "_expiry", lambda request: datetime.now(UTC) + timedelta(minutes=5))
    with Session(db) as session:
        preflight = establishment.manual_install_preflight(session, 41, proof())
        authorization = establishment.authorize_manual_install(session, 41, WordPressBootstrapManualInstallAuthorizeRequest(manual_install_handle=preflight.handle, confirmation_phrase=establishment.MANUAL_PHRASE))
        current["state"] = "active"
        result = establishment.verify_manual_install(session, 41, verify_proof(authorization.establishment_audit_id))
        assert result.status == "manual_activation_detected"
        assert result.request_atlas_write_count == 1


@pytest.mark.parametrize("field", ["verification_fingerprint", "status", "transition_history", "atlas_write_count"])
def test_verify_request_rejects_caller_controlled_audit_fields(field):
    with pytest.raises(Exception):
        WordPressBootstrapManualInstallVerifyRequest(**proof().model_dump(), establishment_audit_id=1, **{field: "attacker"})


def test_rollback_before_verification_commit_does_not_create_false_success(db, monkeypatch):
    current = {"state": "absent"}
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base(current["state"]))
    monkeypatch.setattr(establishment, "_expiry", lambda request: datetime.now(UTC) + timedelta(minutes=5))
    with Session(db) as session:
        preflight = establishment.manual_install_preflight(session, 41, proof())
        authorization = establishment.authorize_manual_install(session, 41, WordPressBootstrapManualInstallAuthorizeRequest(manual_install_handle=preflight.handle, confirmation_phrase=establishment.MANUAL_PHRASE))
        audit_id = authorization.establishment_audit_id
    current["state"] = "inactive"
    with Session(db) as session:
        real_commit = session.commit
        session.commit = lambda: (_ for _ in ()).throw(RuntimeError("synthetic commit failure"))
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            establishment.verify_manual_install(session, 41, verify_proof(audit_id))
        session.rollback()
        session.commit = real_commit
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert audit.status == "awaiting_manual_bootstrap_installation"
        assert "manual_installation_inventory_verified" not in audit.transition_history
        assert audit.atlas_write_count == 1


def test_manual_activation_is_classified_without_an_automatic_write(db, monkeypatch):
    current = {"state": "absent"}
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base(current["state"]))
    monkeypatch.setattr(establishment, "_expiry", lambda request: datetime.now(UTC) + timedelta(minutes=5))
    with Session(db) as session:
        preflight = establishment.manual_install_preflight(session, 41, proof())
        auth = establishment.authorize_manual_install(session, 41, WordPressBootstrapManualInstallAuthorizeRequest(manual_install_handle=preflight.handle, confirmation_phrase=establishment.MANUAL_PHRASE))
        current["state"] = "active"
        result = establishment.verify_manual_install(session, 41, verify_proof(auth.establishment_audit_id))
        assert result.status == "manual_activation_detected"
        assert result.wordpress_write_count == result.cache_write_count == 0
        assert result.recovery_recommendation == "reconcile_manual_activation"


@pytest.mark.parametrize(("checksum", "expected_transition"), [("f" * 64, "checksum_mismatch"), (None, "checksum_unavailable")])
def test_post_activation_checksum_failure_enters_recovery_without_cleanup(db, monkeypatch, checksum, expected_transition):
    current = {"state": "absent"}
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base(current["state"]))
    monkeypatch.setattr(establishment, "_expiry", lambda request: datetime.now(UTC) + timedelta(minutes=5))
    monkeypatch.setattr(establishment, "_activate_fixed_entry", lambda session: current.update(state="active") or {"accepted": True, "request_performed": True, "request_keys": ["status"], "status_code": 200})
    monkeypatch.setattr(upgrade, "_read_bootstrap_status", lambda session: {
        "bootstrap": establishment.BOOTSTRAP_SLUG, "bootstrap_version": "0.3.0", "bootstrap_checksum": checksum,
        "operation": "upgrade_metadata_bridge_0.57.6_to_0.57.7", "target_plugin": "project-atlas-metadata-bridge/project-atlas-metadata-bridge.php",
        "current_version": "0.57.6", "target_version": "0.57.7", "target_zip_sha256": "ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62",
        "status_code": 200 if checksum else 404, "request_method": "GET",
    })
    with Session(db) as session:
        manual = establishment.manual_install_preflight(session, 41, proof())
        auth = establishment.authorize_manual_install(session, 41, WordPressBootstrapManualInstallAuthorizeRequest(manual_install_handle=manual.handle, confirmation_phrase=establishment.MANUAL_PHRASE))
        current["state"] = "inactive"
        establishment.verify_manual_install(session, 41, verify_proof(auth.establishment_audit_id))
        preflight = establishment.activation_preflight(session, 41, verify_proof(auth.establishment_audit_id))
        result = establishment.apply_activation(session, 41, WordPressBootstrapActivationApplyRequest(activation_handle=preflight.handle, confirmation_phrase=establishment.ACTIVATION_PHRASE))
        assert result.status == "recovery_required"
        assert expected_transition in result.state_history
        assert result.wordpress_write_count == 1 and result.cache_write_count == 0
        assert result.recovery_recommendation == "guarded_bootstrap_recovery"


@pytest.mark.parametrize(("items", "expected"), [
    ([], "no_upload_yet"),
    ([{"plugin": establishment.BOOTSTRAP_ENTRY, "version": "0.3.0", "status": "inactive"}], "exact_inactive"),
    ([{"plugin": establishment.BOOTSTRAP_REST_ID, "version": "0.3.0", "status": "active"}], "exact_active"),
    ([{"plugin": establishment.BOOTSTRAP_REST_ID, "version": "0.2.0", "status": "inactive"}], "wrong_version"),
    ([{"plugin": establishment.BOOTSTRAP_REST_ID, "version": "0.3.0", "status": "inactive"}, {"plugin": establishment.BOOTSTRAP_ENTRY, "version": "0.3.0", "status": "inactive"}], "duplicate_bootstrap"),
    ([{"plugin": "project-atlas-upgrade-bootstrap/wrong", "version": "0.3.0", "status": "inactive"}], "installation_partial"),
    ([{"plugin": establishment.BOOTSTRAP_REST_ID, "version": "0.3.0", "status": "inactive"}, {"plugin": "project-atlas-upgrade-bootstrap/other", "version": "0.3.0", "status": "inactive"}], "conflicting_bootstrap"),
])
def test_inventory_classifications(items, expected):
    assert establishment._classify(items)["classification"] == expected


@pytest.mark.parametrize("field", ["plugin_slug", "plugin_path", "directory", "entry", "version", "checksum", "url", "filesystem_path"])
def test_activation_request_rejects_caller_selected_target(field):
    with pytest.raises(Exception):
        WordPressBootstrapActivationApplyRequest(activation_handle="h" * 32, confirmation_phrase=establishment.ACTIVATION_PHRASE, **{field: "attacker"})


def test_handle_is_single_use_and_restart_invalidates(monkeypatch):
    expiry = datetime.now(UTC) + timedelta(minutes=5)
    handle = establishment._store("manual", proof(), "a" * 64, expiry, None)
    assert establishment._consume("manual", handle).binding_hash == "a" * 64
    with pytest.raises(HTTPException): establishment._consume("manual", handle)
    handle = establishment._store("manual", proof(), "b" * 64, expiry, None)
    establishment._clear_establishment_handles()
    with pytest.raises(HTTPException): establishment._consume("manual", handle)


def test_wrong_phrases_fail_before_audit_or_write(db):
    with Session(db) as session:
        with pytest.raises(HTTPException):
            establishment.authorize_manual_install(session, 41, WordPressBootstrapManualInstallAuthorizeRequest(manual_install_handle="x" * 32, confirmation_phrase="wrong"))
        with pytest.raises(HTTPException):
            establishment.apply_activation(session, 41, WordPressBootstrapActivationApplyRequest(activation_handle="x" * 32, confirmation_phrase="wrong"))
        assert session.exec(select(WordPressBootstrapEstablishmentAudit)).first() is None


def test_source_contains_no_upload_or_generic_activation_capability():
    source = __import__("inspect").getsource(establishment)
    assert "files={" not in source
    assert "wp-admin" not in source.lower()
    assert "BOOTSTRAP_REST_ID" in source
    assert 'json={"status": "active"}' in source
    assert "caller" not in __import__("inspect").signature(establishment._activate_fixed_entry).parameters
    frontend = (upgrade.resolve_program_root() / "frontend/src/pages/WordPressMetadataBridgeInstallPage.tsx").read_text(encoding="utf-8")
    assert "localStorage" not in frontend
    assert establishment.MANUAL_PHRASE in source and establishment.ACTIVATION_PHRASE in source
    assert "/deployment/upgrade-bootstrap/manual-install/preflight/{page_id}" in (__import__("pathlib").Path(__file__).resolve().parents[1] / "app/api/wordpress_routes.py").read_text(encoding="utf-8")


def test_migration_and_program_backup_include_dedicated_audit():
    migration = (__import__("pathlib").Path(__file__).resolve().parents[1] / "alembic/versions/20260719_0023_wordpress_bootstrap_establishment_audits.py").read_text(encoding="utf-8")
    assert 'revision = "20260719_0023"' in migration
    assert 'down_revision = "20260717_0022"' in migration
    assert "wordpressbootstrapestablishmentaudit" in migration
    assert backup_service.BACKUP_VERSION == "0.38"
    assert backup_service.BACKUP_MODELS["wordpress_bootstrap_establishment_audits"] is WordPressBootstrapEstablishmentAudit


def test_quarantine_blocks_unrelated_workflows_until_checksum_verified(db):
    audit = WordPressBootstrapEstablishmentAudit(
        generated_page_id=41, wordpress_post_id=8, installation_audit_id=1, activation_audit_id=1,
        status="activation_pending_checksum_verification", operator="Shawn Manchette",
        bootstrap_slug=establishment.BOOTSTRAP_SLUG, bootstrap_directory=establishment.BOOTSTRAP_DIRECTORY,
        bootstrap_path=establishment.BOOTSTRAP_ENTRY, bootstrap_version=establishment.BOOTSTRAP_VERSION,
        bootstrap_zip_filename=establishment.BOOTSTRAP_ZIP, bootstrap_zip_sha256=establishment.BOOTSTRAP_ZIP_SHA256,
        bootstrap_entry_sha256=establishment.BOOTSTRAP_ENTRY_SHA256, manual_phrase_hash="a" * 64,
        activation_phrase_hash="b" * 64, manual_handle_fingerprint="c" * 64, manual_binding_hash="d" * 64,
        release_identity={}, backup_evidence={}, browser_evidence_id="evidence", pre_snapshot={},
        source_inventories={}, protected_state={}, gate_results=[], transition_history=["activation_pending_checksum_verification"],
    )
    with Session(db) as session:
        session.add(audit); session.commit(); session.refresh(audit)
        with pytest.raises(HTTPException, match="quarantined"):
            establishment.assert_no_establishment_quarantine(session)
        audit.status = "verified"; audit.checksum_verification_result = "matched"
        session.add(audit); session.commit()
        establishment.assert_no_establishment_quarantine(session)


def test_quarantine_guard_is_wired_to_rendering_cache_lifecycle_and_cleanup():
    root = upgrade.resolve_program_root() / "backend/app/services"
    assert "assert_no_establishment_quarantine" in (root / "wordpress_metadata_lifecycle.py").read_text(encoding="utf-8")
    cache_source = (root / "wordpress_cache_aware_rendering.py").read_text(encoding="utf-8")
    assert cache_source.count("assert_no_establishment_quarantine(session)") >= 2
    cleanup_source = (root / "wordpress_bootstrap_cleanup.py").read_text(encoding="utf-8")
    assert cleanup_source.count("assert_no_establishment_quarantine(session)") == 4
