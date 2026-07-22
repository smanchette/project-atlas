from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models import WordPressBootstrapEstablishmentAudit
from app.services import wordpress_bootstrap_establishment as establishment
from app.services import wordpress_plugin_upgrade_0577 as upgrade
from test_wordpress_bootstrap_establishment import (
    authorized_audit,
    base_snapshot,
    snapshot,
)
from test_wordpress_plugin_upgrade import KEY


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    establishment._clear_establishment_handles()
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    yield
    establishment._clear_establishment_handles()


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'transport-identity.sqlite3').as_posix()}")
    SQLModel.metadata.create_all(engine)
    return engine


def _historical_403(value):
    historical = deepcopy(value)
    historical["rendered"]["outcome"] = "signed_browser_evidence_after_public_403"
    historical["rendered"]["public_http_observation"].update({
        "outcome": "unavailable",
        "status_code": 403,
        "redirect_count": 0,
        "content_type": "text/html; charset=UTF-8",
        "cache_headers": {
            "etag": 'W/"6a27b6bb-34"',
            "server": "nginx",
            "x-proxy-cache-info": "DT:1",
        },
        "body_sha256": None,
    })
    return historical


def _current_200(value):
    current = deepcopy(value)
    current["rendered"]["outcome"] = "public_html_verified"
    current["rendered"]["public_http_observation"].update({
        "outcome": "public_html_verified",
        "status_code": 200,
        "redirect_count": 0,
        "content_type": "text/html; charset=UTF-8",
        "cache_headers": {
            "server": "nginx",
            "x-proxy-cache-info": "DT:9",
        },
        "body_sha256": "9" * 64,
        "head_hash": current["rendered"]["head_hash"],
        "visible_hash": current["rendered"]["visible_hash"],
    })
    return current


def _current_403(value):
    current = _historical_403(value)
    current["rendered"]["outcome"] = "signed_browser_evidence_after_public_403"
    current["rendered"]["public_http_observation"].update({
        "outcome": "provider_html_blocked",
        "cache_headers": {
            "server": "NGINX",
            "x-proxy-cache-info": "DT:9",
            "etag": 'W/"different-diagnostic-etag"',
        },
        "http_client_identity": "centralized_httpx_client",
        "user_agent": "Project-Atlas-WordPress/v0.59.90",
        "transport_policy_version": "v2",
    })
    return current


def _comparison(before, after):
    audit = SimpleNamespace(pre_snapshot=before)
    return establishment._verification_stable_comparison(audit, after)


def test_historical_and_current_verified_siteground_403_representations_are_compatible():
    before = _historical_403(snapshot("absent"))
    before["rendered"]["public_http_observation"].update({
        "http_client_identity": "legacy_httpx_client",
        "user_agent": "Project-Atlas-WordPress/v0.59.84",
        "transport_policy_version": "v1",
    })
    after = _current_403(snapshot("inactive"))
    result = _comparison(before, after)

    assert result["compatible"] is True
    assert result["compatibility_applied"] is True
    assert result["version"] == establishment.TRANSPORT_IDENTITY_VERSION
    assert result["reason_code"] == establishment.TRANSPORT_COMPATIBILITY_REASON
    assert len(result["canonical_fingerprint"]) == 64
    assert result["authorization_stable_fingerprint"] != result["verification_stable_fingerprint"]


def test_compatibility_ignores_only_transport_artifacts_not_signed_identity():
    before = _historical_403(snapshot("absent"))
    after = _current_403(snapshot("inactive"))
    before["rendered"]["public_http_observation"]["cache_headers"].update({
        "age": "1",
        "date": "old",
        "x-request-id": "old-request",
    })
    after["rendered"]["public_http_observation"]["cache_headers"].update({
        "age": "999",
        "date": "new",
        "x-request-id": "new-request",
    })

    assert _comparison(before, after)["compatible"] is True


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("origin", "manual_install_verification_origin_drift"),
        ("redirect", "manual_install_verification_origin_drift"),
        ("challenge", "manual_install_verification_privacy_transport_drift"),
        ("provider", "manual_install_verification_provider_identity_drift"),
        ("cache_state", "manual_install_verification_provider_identity_drift"),
        ("status_202", "manual_install_verification_response_source_drift"),
        ("status_200", "manual_install_verification_response_source_drift"),
        ("head_hash", "manual_install_verification_rendered_hash_drift"),
        ("privacy", "manual_install_verification_privacy_transport_drift"),
        ("title", "manual_install_verification_stable_page_identity_mismatch"),
    ],
)
def test_cross_release_transport_compatibility_remains_fail_closed(mutation, reason):
    before = _historical_403(snapshot("absent"))
    after = _current_403(snapshot("inactive"))
    public = after["rendered"]["public_http_observation"]
    if mutation == "origin":
        public["final_url"] = "https://example.invalid/"
    elif mutation == "redirect":
        public["redirect_count"] = 1
    elif mutation == "challenge":
        public["challenge_page_detected"] = True
    elif mutation == "provider":
        public["cache_headers"] = {"server": "other", "x-proxy-cache-info": "DT:9"}
    elif mutation == "cache_state":
        public["cache_headers"]["x-proxy-cache"] = "HIT"
    elif mutation == "status_202":
        public["status_code"] = 202
    elif mutation == "status_200":
        public["status_code"] = 200
        public["head_hash"] = after["rendered"]["head_hash"]
        public["visible_hash"] = after["rendered"]["visible_hash"]
    elif mutation == "head_hash":
        after["rendered"]["head_hash"] = "0" * 64
    elif mutation == "privacy":
        after["rendered"]["privacy_attestations"] = {"cookies_stored": True}
    elif mutation == "title":
        after["rendered"]["document_title"] = ["Changed"]

    result = _comparison(before, after)
    assert result["compatible"] is False
    assert result["compatibility_applied"] is False
    assert result["reason_code"] == reason


def test_current_200_to_later_403_is_not_compatible():
    result = _comparison(_current_200(snapshot("absent")), _current_403(snapshot("inactive")))
    assert result["compatible"] is False
    assert result["reason_code"] == "manual_install_verification_response_source_drift"


def test_manual_verification_commits_derived_compatibility_without_rewriting_history(db, monkeypatch):
    audit_id, request = authorized_audit(db, monkeypatch)
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        historical = _historical_403(audit.pre_snapshot)
        historical_record = deepcopy(historical[establishment._AUTHORIZATION_EVIDENCE_KEY])
        historical_record["stable_fingerprint"] = establishment._stable_verification_fingerprint(historical)
        historical[establishment._AUTHORIZATION_EVIDENCE_KEY] = historical_record
        audit.pre_snapshot = historical
        session.add(audit)
        session.commit()

    current = _current_403(snapshot("inactive"))
    monkeypatch.setattr(
        upgrade,
        "plugin_upgrade_preflight",
        lambda *args, **kwargs: base_snapshot(deepcopy(current), "inactive"),
    )
    with Session(db) as session:
        result = establishment.verify_manual_install(session, 41, request)
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        activation = establishment.activation_preflight(session, 41, request)
        replay = establishment.verify_manual_install(session, 41, request)

    assert result.status == "manual_installation_inventory_verified"
    assert result.stable_evidence_match is True
    assert result.wordpress_write_count == result.cache_write_count == 0
    assert result.request_atlas_write_count == 1
    assert activation.ready is True
    assert activation.handle
    assert replay.idempotent_replay is True
    assert replay.request_atlas_write_count == 0
    verification = audit.upload_snapshot[establishment._VERIFICATION_EVIDENCE_KEY]
    assert verification["transport_identity_version"] == establishment.TRANSPORT_IDENTITY_VERSION
    assert verification["transport_compatibility_applied"] is True
    assert verification["transport_comparison_reason"] == establishment.TRANSPORT_COMPATIBILITY_REASON
    assert audit.pre_snapshot["rendered"]["public_http_observation"]["status_code"] == 403
    assert audit.upload_snapshot["rendered"]["public_http_observation"]["status_code"] == 403
    assert audit.transition_history == [
        "awaiting_manual_bootstrap_installation",
        "manual_installation_inventory_verified",
    ]


def test_failed_cross_release_comparison_is_zero_write_and_preserves_audit(db, monkeypatch):
    audit_id, request = authorized_audit(db, monkeypatch)
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        audit.pre_snapshot = _historical_403(audit.pre_snapshot)
        session.add(audit)
        session.commit()

    current = _current_403(snapshot("inactive"))
    current["rendered"]["public_http_observation"]["redirect_count"] = 1
    monkeypatch.setattr(
        upgrade,
        "plugin_upgrade_preflight",
        lambda *args, **kwargs: base_snapshot(deepcopy(current), "inactive"),
    )
    with Session(db) as session:
        before = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        writes = before.atlas_write_count
        with pytest.raises(Exception) as caught:
            establishment.verify_manual_install(session, 41, request)
        assert caught.value.detail["reason_code"] == "manual_install_verification_origin_drift"
    with Session(db) as session:
        audit = session.get(WordPressBootstrapEstablishmentAudit, audit_id)
        assert audit.status == "awaiting_manual_bootstrap_installation"
        assert audit.atlas_write_count == writes
        assert audit.upload_snapshot in (None, {})
