from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine, select

from app.main import app
from app.models import WordPressBootstrapEstablishmentAudit
from app.db.backup import export_backup
from app.schemas.wordpress import (
    WordPressBootstrapAuthorizationRetirementApplyRequest,
    WordPressBootstrapAuthorizationRetirementRequest,
    WordPressBootstrapInstalledInactiveAuthorizeRequest,
    WordPressBootstrapManualInstallVerifyRequest,
)
from app.services import wordpress_bootstrap_establishment as establishment
from app.services import wordpress_plugin_upgrade_0577 as upgrade
from app.services.wordpress_rendered_state import build_manual_browser_evidence
from test_wordpress_bootstrap_establishment import authorized_audit, base_snapshot, proof, snapshot
from test_wordpress_bootstrap_backup_renewal import request as renewal_request
from test_wordpress_bootstrap_transport_identity import _historical_403
from test_wordpress_plugin_upgrade import HTML, KEY


@pytest.fixture(autouse=True)
def handles(monkeypatch):
    establishment._clear_establishment_handles()
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    monkeypatch.setattr(establishment, "_retirement_runtime_matches", lambda request: True)
    yield
    establishment._clear_establishment_handles()


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'retirement.sqlite3').as_posix()}")
    SQLModel.metadata.create_all(engine)
    return engine


def current_hit(state="inactive"):
    value = snapshot(state)
    value["rendered"]["outcome"] = "public_html_verified"
    value["rendered"]["public_http_observation"].update({
        "outcome": "public_html_verified",
        "status_code": 200,
        "cache_headers": {"server": "nginx", "x-cache-enabled": "True", "x-proxy-cache": "HIT"},
        "head_hash": value["rendered"]["head_hash"],
        "visible_hash": value["rendered"]["visible_hash"],
    })
    return value


def retirement_request(audit_id):
    return WordPressBootstrapAuthorizationRetirementRequest(
        establishment_audit_id=audit_id,
        retirement_reason=establishment.RETIREMENT_REASON,
        expected_runtime_identity=proof().expected_runtime_identity,
    )


def stale_audit(db, monkeypatch):
    audit_id, _ = authorized_audit(db, monkeypatch)
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        audit.pre_snapshot = _historical_403(audit.pre_snapshot)
        audit.protected_state = establishment._protected(audit.pre_snapshot)
        audit.backup_renewals = [{"sequence": 1, "replacement": {"reference": "one"}}, {"sequence": 2, "replacement": {"reference": "two"}}]
        audit.atlas_write_count = 3
        audit.transition_history = ["awaiting_manual_bootstrap_installation", "backup_renewal_1_committed", "backup_renewal_2_committed"]
        session.add(audit); session.commit()
    monkeypatch.setattr(establishment, "_observe", lambda *args, **kwargs: base_snapshot(deepcopy(current_hit()), "inactive").inspected_state)
    return audit_id


def test_genuine_403_to_200_hit_retirement_is_atomic_and_history_preserving(db, monkeypatch):
    audit_id = stale_audit(db, monkeypatch)
    request = retirement_request(audit_id)
    with Session(db) as session:
        before = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        snapshot_hash = establishment._hash(before.pre_snapshot)
        renewals_hash = establishment._hash(before.backup_renewals)
        preflight = establishment.retirement_preflight(session, 41, request)
        assert preflight.ready is True
        assert preflight.transport_comparison["authorization"]["status_code"] == 403
        assert preflight.transport_comparison["current"]["status_code"] == 200
        assert preflight.transport_comparison["current"]["cache_state"] == "hit"
        result = establishment.apply_retirement(session, 41, WordPressBootstrapAuthorizationRetirementApplyRequest(
            retirement_handle=preflight.retirement_handle,
            confirmation_phrase=preflight.confirmation_phrase,
        ))
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert result.status == audit.status == "authorization_retired"
        assert audit.retirement_reason == establishment.RETIREMENT_REASON
        assert audit.transition_history[-1] == "authorization_retired"
        assert audit.atlas_write_count == 4 and result.request_atlas_write_count == 1
        assert result.wordpress_write_count == result.plugin_write_count == result.cache_write_count == 0
        assert establishment._hash(audit.pre_snapshot) == snapshot_hash
        assert establishment._hash(audit.backup_renewals) == renewals_hash
        assert establishment._unresolved(session) is False


@pytest.mark.parametrize("change", ["matching", "network", "representation", "public_identity", "runtime", "active", "verified", "evidence", "checksum"])
def test_retirement_rejects_noneligible_states(db, monkeypatch, change):
    audit_id = stale_audit(db, monkeypatch)
    current = current_hit()
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        if change == "matching":
            current = deepcopy(audit.pre_snapshot)
            current["plugins"] = current_hit()["plugins"]
        elif change == "network":
            current["rendered"]["public_http_observation"].update({"status_code": None, "cache_headers": {}, "outcome": "network_failed"})
        elif change == "representation":
            current = _historical_403(current)
            current["rendered"]["public_http_observation"]["cache_headers"]["x-proxy-cache-info"] = "DT:999"
        elif change == "public_identity":
            current["rendered"]["public_http_observation"]["head_hash"] = "0" * 64
        elif change == "runtime":
            monkeypatch.setattr(establishment, "_retirement_runtime_matches", lambda request: False)
        elif change == "active":
            current = current_hit("active")
        elif change == "verified":
            audit.status = "verified"
        elif change == "evidence":
            audit.upload_snapshot = {establishment._VERIFICATION_EVIDENCE_KEY: {"id": "existing"}}
        elif change == "checksum":
            audit.checksum_verification_result = "matched"
        session.add(audit); session.commit()
    monkeypatch.setattr(establishment, "_observe", lambda *args, **kwargs: base_snapshot(deepcopy(current), "inactive").inspected_state)
    with Session(db) as session:
        result = establishment.retirement_preflight(session, 41, retirement_request(audit_id))
        assert result.ready is False
        assert result.retirement_handle is None
        assert session.get(WordPressBootstrapEstablishmentAudit, audit_id).status != "authorization_retired"


@pytest.mark.parametrize("cache_state", ["EXPIRED", "MISS", "BYPASS"])
def test_retirement_requires_a_current_siteground_hit(db, monkeypatch, cache_state):
    audit_id = stale_audit(db, monkeypatch)
    current = current_hit()
    current["rendered"]["public_http_observation"]["cache_headers"]["x-proxy-cache"] = cache_state
    monkeypatch.setattr(
        establishment,
        "_observe",
        lambda *args, **kwargs: base_snapshot(deepcopy(current), "inactive").inspected_state,
    )
    with Session(db) as session:
        before = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        writes = before.atlas_write_count
        result = establishment.retirement_preflight(session, 41, retirement_request(audit_id))
        after = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
    assert result.ready is False
    assert result.retirement_handle is None
    assert result.transport_comparison["current"]["cache_state"] == cache_state.lower()
    assert after.atlas_write_count == writes
    assert after.status == "awaiting_manual_bootstrap_installation"


def test_retirement_transport_failure_is_not_reported_as_origin_drift(db, monkeypatch):
    audit_id = stale_audit(db, monkeypatch)
    current = current_hit()
    current["rendered"]["public_http_observation"].update({
        "status_code": None,
        "final_url": None,
        "cache_headers": {},
        "outcome": "dns_failed",
        "transport_category": "dns_failed",
        "transport_reason_code": "public_transport_dns_failed",
    })
    monkeypatch.setattr(
        establishment,
        "_observe",
        lambda *args, **kwargs: base_snapshot(deepcopy(current), "inactive").inspected_state,
    )
    with Session(db) as session:
        before = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        writes = before.atlas_write_count
        result = establishment.retirement_preflight(session, 41, retirement_request(audit_id))
        after = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
    assert result.ready is False
    assert result.retirement_handle is None
    assert result.transport_comparison["reason_code"] == (
        "manual_install_verification_transport_acquisition_failed"
    )
    assert result.transport_comparison["current"]["transport_category"] == "dns_failed"
    assert after.atlas_write_count == writes
    assert after.status == "awaiting_manual_bootstrap_installation"


def test_retirement_phrase_handle_and_replay_fail_closed(db, monkeypatch):
    audit_id = stale_audit(db, monkeypatch)
    with Session(db) as session:
        first = establishment.retirement_preflight(session, 41, retirement_request(audit_id))
        with pytest.raises(HTTPException):
            establishment.apply_retirement(session, 41, WordPressBootstrapAuthorizationRetirementApplyRequest(
                retirement_handle=first.retirement_handle, confirmation_phrase="wrong",
            ))
        second = establishment.retirement_preflight(session, 41, retirement_request(audit_id))
        establishment.apply_retirement(session, 41, WordPressBootstrapAuthorizationRetirementApplyRequest(
            retirement_handle=second.retirement_handle, confirmation_phrase=second.confirmation_phrase,
        ))
        with pytest.raises(HTTPException):
            establishment.apply_retirement(session, 41, WordPressBootstrapAuthorizationRetirementApplyRequest(
                retirement_handle=second.retirement_handle, confirmation_phrase=second.confirmation_phrase,
            ))


def test_retired_audit_cannot_be_verified_renewed_or_activated(db, monkeypatch):
    audit_id = stale_audit(db, monkeypatch)
    with Session(db) as session:
        preflight = establishment.retirement_preflight(session, 41, retirement_request(audit_id))
        establishment.apply_retirement(session, 41, WordPressBootstrapAuthorizationRetirementApplyRequest(
            retirement_handle=preflight.retirement_handle,
            confirmation_phrase=preflight.confirmation_phrase,
        ))
        verification = WordPressBootstrapManualInstallVerifyRequest(
            **fresh_proof().model_dump(), establishment_audit_id=audit_id
        )
        with pytest.raises(HTTPException, match="not awaiting"):
            establishment.verify_manual_install(session, 41, verification)
        activation = establishment.activation_preflight(session, 41, verification)
        assert activation.ready is False and activation.handle is None
        renewal = establishment.backup_renewal_preflight(session, 41, renewal_request(audit_id))
        assert renewal.ready is False and renewal.renewal_handle_fingerprint is None


def fresh_proof():
    value = proof().model_dump()
    value["operator"] = "Shawn Manchette"
    value["atlas_data_backup_file"] = "fresh-atlas-data.json"
    value["atlas_media_backup_file"] = "fresh-atlas-media.zip"
    value["atlas_program_backup_file"] = "fresh-atlas-program.zip"
    value["wordpress_backup_reference"] = "Fresh SiteGround full-site backup"
    value["wordpress_backup_completed_at"] = datetime.now(UTC) - timedelta(minutes=5)
    value["manual_browser_evidence"] = build_manual_browser_evidence(
        HTML,
        final_url="https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/",
        evidence_identifier="orlando-fresh-installed-inactive-authorization",
        signing_key=KEY,
    )
    return type(proof())(**value)


def test_retired_audit_allows_distinct_installed_inactive_authorization(db, monkeypatch):
    audit_id = stale_audit(db, monkeypatch)
    with Session(db) as session:
        first = establishment.retirement_preflight(session, 41, retirement_request(audit_id))
        establishment.apply_retirement(session, 41, WordPressBootstrapAuthorizationRetirementApplyRequest(
            retirement_handle=first.retirement_handle, confirmation_phrase=first.confirmation_phrase,
        ))
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base_snapshot(deepcopy(current_hit()), "inactive"))
    request = fresh_proof()
    with Session(db) as session:
        preflight = establishment.installed_inactive_preflight(session, 41, request)
        assert preflight.ready and preflight.handle
        result = establishment.authorize_installed_inactive(session, 41, WordPressBootstrapInstalledInactiveAuthorizeRequest(
            installed_bootstrap_handle=preflight.handle,
            confirmation_phrase=establishment.INSTALLED_INACTIVE_PHRASE,
        ))
        audits = list(session.exec(select(WordPressBootstrapEstablishmentAudit).order_by(WordPressBootstrapEstablishmentAudit.id)))
        assert result.establishment_audit_id != audit_id
        assert [item.status for item in audits] == ["authorization_retired", "awaiting_manual_bootstrap_installation"]
        assert audits[-1].authorization_mode == "existing_exact_inactive_bootstrap"
        assert result.wordpress_write_count == result.cache_write_count == 0


def test_installed_inactive_authorization_rejects_retired_evidence_and_backup_reuse(db, monkeypatch):
    audit_id = stale_audit(db, monkeypatch)
    with Session(db) as session:
        first = establishment.retirement_preflight(session, 41, retirement_request(audit_id))
        establishment.apply_retirement(session, 41, WordPressBootstrapAuthorizationRetirementApplyRequest(
            retirement_handle=first.retirement_handle, confirmation_phrase=first.confirmation_phrase,
        ))
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base_snapshot(deepcopy(current_hit()), "inactive"))
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        reused_payload = proof().model_dump()
        reused_payload.update({
            key: value for key, value in audit.backup_evidence.items()
            if key in type(proof()).model_fields
        })
        reused = type(proof()).model_validate(reused_payload)
        result = establishment.installed_inactive_preflight(session, 41, reused)
        failed = {gate.code for gate in result.gate_results if not gate.passed}
        assert {"fresh_evidence_identity", "fresh_backup_identity"} <= failed
        assert result.ready is False and result.handle is None


@pytest.mark.parametrize("state", ["absent", "active", "wrong_version", "duplicate", "conflict"])
def test_installed_inactive_authorization_requires_exact_inactive(db, monkeypatch, state):
    audit_id = stale_audit(db, monkeypatch)
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        audit.status = "authorization_retired"
        audit.retirement_reason = establishment.RETIREMENT_REASON
        session.add(audit); session.commit()
    observed = deepcopy(current_hit("active") if state == "active" else current_hit())
    if state == "absent":
        observed = snapshot("absent")
    elif state == "wrong_version":
        observed["plugins"][-1]["version"] = "0.2.0"
    elif state == "duplicate":
        observed["plugins"].append(deepcopy(observed["plugins"][-1]))
    elif state == "conflict":
        observed["plugins"].append({"plugin": "project-atlas-upgrade-bootstrap/alternate.php", "version": "0.3.0", "status": "inactive"})
    monkeypatch.setattr(upgrade, "plugin_upgrade_preflight", lambda *args, **kwargs: base_snapshot(deepcopy(observed), state))
    with Session(db) as session:
        result = establishment.installed_inactive_preflight(session, 41, fresh_proof())
        assert result.ready is False and result.handle is None


def test_data_backup_039_serializes_retirement_and_renewals(db, monkeypatch, tmp_path):
    audit_id = stale_audit(db, monkeypatch)
    with Session(db) as session:
        preflight = establishment.retirement_preflight(session, 41, retirement_request(audit_id))
        establishment.apply_retirement(session, 41, WordPressBootstrapAuthorizationRetirementApplyRequest(
            retirement_handle=preflight.retirement_handle,
            confirmation_phrase=preflight.confirmation_phrase,
        ))
        result = export_backup(session, backup_dir=tmp_path)
        payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        record = next(item for item in payload["data"]["wordpress_bootstrap_establishment_audits"] if item["id"] == audit_id)
        assert payload["metadata"]["version"] == "0.40"
        assert record["authorization_mode"] == "manual_upload"
        assert record["retirement_reason"] == establishment.RETIREMENT_REASON
        assert len(record["backup_renewals"]) == 2
        restored = WordPressBootstrapEstablishmentAudit.model_validate({key: value for key, value in record.items() if key != "id"})
        assert restored.status == "authorization_retired"
        assert restored.retirement_reason == establishment.RETIREMENT_REASON
        assert restored.transition_history[-1] == "authorization_retired"
        assert len(restored.backup_renewals) == 2


def test_data_backup_038_record_defaults_remain_compatible(db, monkeypatch, tmp_path):
    audit_id, _ = authorized_audit(db, monkeypatch)
    with Session(db) as session:
        result = export_backup(session, backup_dir=tmp_path)
        path = Path(result["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["metadata"]["version"] = "0.38"
        for record in payload["data"]["wordpress_bootstrap_establishment_audits"]:
            record.pop("authorization_mode", None)
            record.pop("retirement_reason", None)
        path.write_text(json.dumps(payload), encoding="utf-8")
        record = next(item for item in payload["data"]["wordpress_bootstrap_establishment_audits"] if item["id"] == audit_id)
        restored = WordPressBootstrapEstablishmentAudit.model_validate({key: value for key, value in record.items() if key != "id"})
        assert restored.authorization_mode == "manual_upload"
        assert restored.retirement_reason is None


def test_retirement_contract_has_dedicated_routes_and_rejects_later_phase_proof():
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert ("/api/wordpress/deployment/upgrade-bootstrap/authorization/retirement/preflight/{page_id}", "POST") in routes
    assert ("/api/wordpress/deployment/upgrade-bootstrap/authorization/retirement/apply/{page_id}", "POST") in routes
    assert ("/api/wordpress/deployment/upgrade-bootstrap/installed-inactive/preflight/{page_id}", "POST") in routes
    assert ("/api/wordpress/deployment/upgrade-bootstrap/installed-inactive/authorize/{page_id}", "POST") in routes
    payload = retirement_request(1).model_dump()
    for forbidden in ("manual_browser_evidence", "atlas_data_backup_file", "wordpress_backup_reference"):
        with pytest.raises(ValidationError):
            WordPressBootstrapAuthorizationRetirementRequest.model_validate({**payload, forbidden: "forbidden"})


def test_frontend_separates_retirement_and_existing_inactive_authorization():
    frontend = (upgrade.resolve_program_root() / "frontend/src/pages/WordPressMetadataBridgeInstallPage.tsx").read_text(encoding="utf-8")
    assert "/authorization/retirement/preflight/" in frontend
    assert "/authorization/retirement/apply/" in frontend
    assert "Retire authorization and preserve history" in frontend
    assert "/installed-inactive/preflight/" in frontend
    assert "/installed-inactive/authorize/" in frontend
    assert "Run existing exact inactive Bootstrap preflight" in frontend
    assert "Atlas history only—no WordPress change" in frontend
    assert "localStorage" not in frontend
