from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session

from app.models import WordPressBootstrapEstablishmentAudit
from app.schemas.wordpress import (
    WordPressBootstrapBackupRenewalApplyRequest,
    WordPressBootstrapBackupRenewalRecoveryRequest,
    WordPressBootstrapBackupRenewalRequest,
)
from app.services import wordpress_bootstrap_establishment as establishment
from app.services import wordpress_plugin_upgrade_0577 as upgrade
from test_wordpress_bootstrap_establishment import authorized_audit, base, db, verify_proof
from test_wordpress_plugin_upgrade import KEY


METHOD = "SiteGround on-demand full-site backup — Site Tools → Security → Backups → Create & Restore"


@pytest.fixture(autouse=True)
def renewal_runtime(monkeypatch):
    establishment._clear_establishment_handles()
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    monkeypatch.setattr(establishment, "_runtime_verified", lambda: True)
    monkeypatch.setattr(establishment, "_pending_operation_exists", lambda session: False)
    yield
    establishment._clear_establishment_handles()


def request(audit_id: int, *, completed: datetime | None = None, reference: str = "Atlas Backup Renewal 1"):
    completed = completed or datetime.now(UTC) - timedelta(minutes=5)
    return WordPressBootstrapBackupRenewalRequest(
        establishment_audit_id=audit_id,
        atlas_data_backup_file="atlas-data-renewal.json",
        atlas_media_backup_file="atlas-media-renewal.zip",
        atlas_program_backup_file="atlas-program-renewal.zip",
        replacement_backup_method=METHOD,
        replacement_backup_reference=reference,
        replacement_backup_completed_at=completed,
        replacement_backup_deadline=completed + timedelta(hours=4),
        database_included_attestation=True,
        plugins_included_attestation=True,
        restore_capability_attestation=True,
        no_relevant_wordpress_change_after_backup=True,
        confirmer_identity="Shawn Manchette",
    )


def expired_authorized_audit(engine, monkeypatch):
    audit_id, verification = authorized_audit(engine, monkeypatch)
    with Session(engine) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        original = dict(audit.backup_evidence)
        original["wordpress_backup_reference"] = "Atlas Backup"
        original["wordpress_backup_completed_at"] = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
        audit.backup_evidence = original
        session.add(audit)
        session.commit()
    return audit_id, verification, original


def apply_once(engine, monkeypatch):
    audit_id, verification, original = expired_authorized_audit(engine, monkeypatch)
    renewal = request(audit_id)
    with Session(engine) as session:
        preflight = establishment.backup_renewal_preflight(session, 41, renewal)
        assert preflight.ready and preflight.reason_code == "bootstrap_backup_renewal_ready"
        result = establishment.apply_backup_renewal(
            session,
            41,
            WordPressBootstrapBackupRenewalApplyRequest(
                renewal_handle_fingerprint=preflight.renewal_handle_fingerprint,
                confirmation_phrase=f"{establishment.BACKUP_RENEWAL_PHRASE_PREFIX} {audit_id}",
            ),
        )
    return audit_id, verification, original, renewal, result


def test_expired_original_backup_can_be_renewed_without_wordpress_write(db, monkeypatch):
    audit_id, _, original, renewal, result = apply_once(db, monkeypatch)
    assert result.status == "backup_renewed_awaiting_manual_verification"
    assert result.request_atlas_write_count == 1
    assert result.wordpress_write_count == result.cache_write_count == 0
    assert result.renewal_sequence == 1
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert audit.backup_evidence == original
        assert audit.active_backup_evidence["wordpress_backup_reference"] == renewal.replacement_backup_reference
        assert audit.transition_history[-1] == "backup_renewal_1_committed"
        assert audit.status == "awaiting_manual_bootstrap_installation"
        assert audit.atlas_write_count == 2


def test_equivalent_renewal_retry_is_idempotent_and_handle_replay_fails(db, monkeypatch):
    audit_id, _, _, renewal, first = apply_once(db, monkeypatch)
    with Session(db) as session:
        preflight = establishment.backup_renewal_preflight(session, 41, renewal)
        assert preflight.ready and preflight.reason_code == "bootstrap_backup_renewal_already_finalized"
        payload = WordPressBootstrapBackupRenewalApplyRequest(
            renewal_handle_fingerprint=preflight.renewal_handle_fingerprint,
            confirmation_phrase=f"{establishment.BACKUP_RENEWAL_PHRASE_PREFIX} {audit_id}",
        )
        replay = establishment.apply_backup_renewal(session, 41, payload)
        assert replay.idempotent_replay and replay.request_atlas_write_count == 0
        assert replay.state_history == first.state_history
        with pytest.raises(HTTPException) as caught:
            establishment.apply_backup_renewal(session, 41, payload)
        assert caught.value.detail["reason_code"] == "bootstrap_backup_renewal_handle_replayed"


def test_fresh_manual_verification_uses_replacement_and_preserves_original(db, monkeypatch):
    audit_id, verification, original, renewal, _ = apply_once(db, monkeypatch)
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base("inactive"))
    fresh = verify_proof(audit_id, evidence_id="orlando-after-backup-renewal")
    fresh = fresh.model_copy(update={
        "atlas_data_backup_file": renewal.atlas_data_backup_file,
        "atlas_media_backup_file": renewal.atlas_media_backup_file,
        "atlas_program_backup_file": renewal.atlas_program_backup_file,
        "wordpress_backup_method": renewal.replacement_backup_method,
        "wordpress_backup_reference": renewal.replacement_backup_reference,
        "wordpress_backup_completed_at": renewal.replacement_backup_completed_at,
        "wordpress_database_included_attestation": True,
        "wordpress_plugins_included_attestation": True,
        "wordpress_restore_capability_attestation": True,
        "confirmer_identity": renewal.confirmer_identity,
    })
    with Session(db) as session:
        result = establishment.verify_manual_install(session, 41, fresh)
        assert result.status == "manual_installation_inventory_verified"
        assert result.verification_evidence["evidence_id"] == "orlando-after-backup-renewal"
        assert result.original_backup["wordpress_backup_reference"] == "Atlas Backup"
        assert result.active_backup["wordpress_backup_reference"] == renewal.replacement_backup_reference
        activation = establishment.activation_preflight(session, 41, fresh)
        assert activation.ready and activation.handle
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert audit.backup_evidence == original


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"database_included_attestation": False}, "bootstrap_backup_renewal_database_missing"),
        ({"plugins_included_attestation": False}, "bootstrap_backup_renewal_plugins_missing"),
        ({"restore_capability_attestation": False}, "bootstrap_backup_renewal_restore_unconfirmed"),
        ({"replacement_backup_deadline": datetime.now(UTC) - timedelta(minutes=1)}, "bootstrap_backup_renewal_replacement_expired"),
    ],
)
def test_invalid_replacement_is_zero_write_blocked(db, monkeypatch, changes, reason):
    audit_id, _, _ = expired_authorized_audit(db, monkeypatch)
    renewal = request(audit_id).model_copy(update=changes)
    with Session(db) as session:
        preflight = establishment.backup_renewal_preflight(session, 41, renewal)
        assert not preflight.ready and preflight.reason_code == reason
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert audit.backup_renewals == [] and audit.atlas_write_count == 1


def test_second_renewal_is_allowed_only_after_first_expires(db, monkeypatch):
    audit_id, _, _, _, _ = apply_once(db, monkeypatch)
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        active = dict(audit.active_backup_evidence)
        old_completed = datetime.now(UTC) - timedelta(hours=6)
        active["wordpress_backup_completed_at"] = old_completed.isoformat()
        active["deadline"] = (old_completed + timedelta(hours=4)).isoformat()
        audit.active_backup_evidence = active
        session.add(audit); session.commit()
        second = request(audit_id, reference="Atlas Backup Renewal 2")
        preflight = establishment.backup_renewal_preflight(session, 41, second)
        assert preflight.ready and preflight.renewal_sequence == 2


def test_non_equivalent_renewal_is_blocked_while_active_replacement_is_valid(db, monkeypatch):
    audit_id, _, _, _, _ = apply_once(db, monkeypatch)
    with Session(db) as session:
        blocked = establishment.backup_renewal_preflight(session, 41, request(audit_id, reference="Different Backup"))
        assert not blocked.ready
        assert blocked.reason_code == "bootstrap_backup_renewal_original_not_expired"


def test_backend_restart_invalidates_renewal_handle(db, monkeypatch):
    audit_id, _, _ = expired_authorized_audit(db, monkeypatch)
    renewal = request(audit_id)
    with Session(db) as session:
        preflight = establishment.backup_renewal_preflight(session, 41, renewal)
        establishment._clear_establishment_handles()
        with pytest.raises(HTTPException) as caught:
            establishment.apply_backup_renewal(session, 41, WordPressBootstrapBackupRenewalApplyRequest(
                renewal_handle_fingerprint=preflight.renewal_handle_fingerprint,
                confirmation_phrase=f"{establishment.BACKUP_RENEWAL_PHRASE_PREFIX} {audit_id}",
            ))
        assert caught.value.detail["reason_code"] == "bootstrap_backup_renewal_handle_replayed"


def test_renewal_is_prohibited_after_verification_or_activation(db, monkeypatch):
    audit_id, _, _ = expired_authorized_audit(db, monkeypatch)
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        audit.status = "manual_installation_inventory_verified"
        session.add(audit); session.commit()
        blocked = establishment.backup_renewal_preflight(session, 41, request(audit_id))
        assert not blocked.ready
        assert blocked.reason_code == "bootstrap_backup_renewal_audit_ineligible"


def test_recovery_classifies_required_recorded_and_expired(db, monkeypatch):
    audit_id, _, _ = expired_authorized_audit(db, monkeypatch)
    recovery_request = WordPressBootstrapBackupRenewalRecoveryRequest(establishment_audit_id=audit_id)
    with Session(db) as session:
        before = establishment.assess_backup_renewal_recovery(session, 41, recovery_request)
        assert before.classification == "renewal_required"
        assert before.recommendation == "create_fresh_siteground_backup"
    apply_once_result = None
    # Use the existing audit rather than creating a second establishment audit.
    renewal = request(audit_id)
    with Session(db) as session:
        preflight = establishment.backup_renewal_preflight(session, 41, renewal)
        apply_once_result = establishment.apply_backup_renewal(session, 41, WordPressBootstrapBackupRenewalApplyRequest(
            renewal_handle_fingerprint=preflight.renewal_handle_fingerprint,
            confirmation_phrase=f"{establishment.BACKUP_RENEWAL_PHRASE_PREFIX} {audit_id}",
        ))
        assert apply_once_result.renewal_sequence == 1
        after = establishment.assess_backup_renewal_recovery(session, 41, recovery_request)
        assert after.classification == "valid_renewal_recorded"
        assert after.recommendation == "proceed_to_manual_verification"


def test_caller_cannot_inject_original_backup_pointer_or_sequence():
    payload = request(1).model_dump()
    for field in ("original_backup", "active_backup", "renewal_sequence", "protected_state_hash"):
        with pytest.raises(ValidationError):
            WordPressBootstrapBackupRenewalRequest.model_validate({**payload, field: "caller"})


def test_migration_0024_adds_only_separate_renewal_storage():
    from pathlib import Path

    migration = (Path(__file__).resolve().parents[1] / "alembic/versions/20260720_0024_bootstrap_backup_renewals.py").read_text(encoding="utf-8")
    assert 'revision = "20260720_0024"' in migration
    assert 'down_revision = "20260719_0023"' in migration
    assert '"backup_renewals"' in migration
    assert '"active_backup_evidence"' in migration


def test_concurrent_equivalent_preflights_commit_once(db, monkeypatch):
    audit_id, _, _ = expired_authorized_audit(db, monkeypatch)
    renewal = request(audit_id)
    with Session(db) as session:
        preflights = [establishment.backup_renewal_preflight(session, 41, renewal) for _ in range(2)]

    def apply(preflight):
        with Session(db) as session:
            try:
                return establishment.apply_backup_renewal(session, 41, WordPressBootstrapBackupRenewalApplyRequest(
                    renewal_handle_fingerprint=preflight.renewal_handle_fingerprint,
                    confirmation_phrase=f"{establishment.BACKUP_RENEWAL_PHRASE_PREFIX} {audit_id}",
                ))
            except HTTPException as exc:
                return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, preflights))
    successes = [item for item in results if not isinstance(item, HTTPException)]
    assert len(successes) == 2
    assert sum(item.request_atlas_write_count for item in successes) == 1
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert len(audit.backup_renewals) == 1
        assert audit.transition_history.count("backup_renewal_1_committed") == 1
