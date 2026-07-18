from __future__ import annotations

from datetime import UTC, datetime, timedelta
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.main import app
from app.models.entities import WordPressMetadataLifecycleAudit, WordPressMetadataState
from app.schemas.wordpress import WordPressMetadataLifecycleApplyRequest
from app.services import wordpress_metadata_lifecycle as lifecycle
from app.services.wordpress_deployment_release import resolve_program_root


def gate_map(gates):
    return {gate.code: gate for gate in gates}


def empty_rendered():
    return {
        "atlas_metadata_marker_present": False,
        "metadata_inventory": {
            "meta_descriptions": [], "open_graph": [], "twitter": [],
            "json_ld": [], "atlas_ownership_markers": [],
        },
    }


def observation(rendered=None):
    return {"rendered": rendered or empty_rendered(), "cache_headers": {}}


EXECUTABLE_CHECKSUM = "64a20b6d6a03cef5430dd19fdc1e7eebfd6a3a0f8dcb201eaae5ee30250a3d5c"
ZIP_CHECKSUM = "09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7"


def optimistic_snapshot(**changes):
    value = {
        "plugin": "project-atlas-metadata-bridge",
        "version": "0.57.6",
        "checksum": EXECUTABLE_CHECKSUM,
        "active": True,
        "rendering_enabled": False,
        "enabled_metadata_state": False,
        "activation_generation": "92888df7-5bb2-40b6-924d-f35dfd040518",
        "plugin_checksum": EXECUTABLE_CHECKSUM,
        "payload_hash": "",
        "revision": "0",
        "payload": None,
    }
    value.update(changes)
    return value


def failed_staging_audit(audit_id=1, **changes):
    before = optimistic_snapshot()
    value = {
        "id": audit_id,
        "action_type": "stage_metadata_payload",
        "status": "failed",
        "transition_history": ["pending", "failed"],
        "wordpress_write_count": 1,
        "atlas_write_count": 2,
        "previous_revision": "0",
        "final_revision": "0",
        "previous_rendering_enabled": False,
        "final_rendering_enabled": False,
        "pre_snapshot": deepcopy(before),
        "post_snapshot": deepcopy(before),
        "gate_results": [{"code": "wordpress_response", "passed": False, "message": "optimistic_snapshot_hash_mismatch"}],
        "completed_at": datetime.now(UTC),
        "error_code": "failed",
    }
    value.update(changes)
    return SimpleNamespace(**value)


def test_routes_are_separate_post_only_surfaces():
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    expected = {
        "/api/wordpress/metadata/staging/preflight/{page_id}",
        "/api/wordpress/metadata/staging/apply/{page_id}",
        "/api/wordpress/metadata/rendering/preflight/{page_id}",
        "/api/wordpress/metadata/rendering/apply/{page_id}",
        "/api/wordpress/metadata/rendering/disable/preflight/{page_id}",
        "/api/wordpress/metadata/rendering/disable/apply/{page_id}",
        "/api/wordpress/metadata/staging/rollback/preflight/{page_id}",
        "/api/wordpress/metadata/staging/rollback/apply/{page_id}",
    }
    assert {(path, "POST") for path in expected} <= routes


def test_approved_payload_is_exact_and_deterministic():
    payload = lifecycle.approved_payload().model_dump(mode="json")
    assert payload["meta_description"] == "Flo-Zone Pest And Termite Solutions Inc provides professional drywood termite tenting services for homes and properties in Orlando, Florida."
    assert set(payload) == {"schema_version", "page_id", "wordpress_post_id", "meta_description", "json_ld"}
    assert [node["@type"] for node in payload["json_ld"]["@graph"]] == ["Organization", "Service"]
    assert payload["json_ld"]["@graph"][0]["telephone"] == "(844) 600-8368"
    assert payload["json_ld"]["@graph"][0]["email"] == "Office@Flo-ZoneTenting.com"
    assert payload["json_ld"]["@graph"][0]["identifier"]["value"] == "JB360566"
    assert payload["json_ld"]["@graph"][1]["areaServed"] == "Orlando, Florida"
    assert lifecycle.payload_sha256() == lifecycle.payload_sha256(lifecycle.approved_payload())
    encoded = str(payload)
    for forbidden in ("LocalBusiness", "WebSite", "WebPage", "Person", "ImageObject", "BreadcrumbList", "FAQPage", "Product", "Review", "AggregateRating"):
        assert forbidden not in encoded
    assert "media" not in encoded.lower()


def test_staging_requires_empty_disabled_revision_zero():
    valid = {"payload": None, "payload_hash": "", "revision": "0", "rendering_enabled": False}
    assert all(g.passed for g in lifecycle._operation_gates("stage_metadata_payload", valid, None, [], lifecycle.payload_sha256(), observation()))
    for key, value in (("payload", {}), ("payload_hash", "a" * 64), ("revision", "1"), ("rendering_enabled", True)):
        changed = {**valid, key: value}
        assert not gate_map(lifecycle._operation_gates("stage_metadata_payload", changed, None, [], lifecycle.payload_sha256(), observation()))["live_metadata_state_not_initial"].passed


@pytest.mark.parametrize("audits", [
    [],
    [failed_staging_audit()],
    [failed_staging_audit(1), failed_staging_audit(2)],
])
def test_staging_history_allows_only_zero_mutation_failed_attempts(audits):
    result = lifecycle._staging_history_eligibility(audits)
    assert result["eligible"] is True
    assert result["reason_code"] == "historical_failed_attempts_only"
    assert all(item["accepted_metadata_mutation_count"] == 0 for item in result["audit_summaries"])
    assert all(item["recovery_recommendation"] == "no_action" for item in result["audit_summaries"])


def test_current_production_shaped_failed_audit_is_eligible_without_rewrite():
    audit = failed_staging_audit()
    audit.pre_snapshot["plugin_checksum"] = None
    audit.post_snapshot["plugin_checksum"] = None
    audit.gate_results[0]["message"] = "HTTP 409"
    original = deepcopy(vars(audit))
    result = lifecycle._staging_history_eligibility([audit])
    assert result["eligible"] is True
    assert result["audit_summaries"] == [{
        "audit_id": 1,
        "action_type": "stage_metadata_payload",
        "status": "failed",
        "transition_history": ["pending", "failed"],
        "attempted_wordpress_write_count": 1,
        "accepted_metadata_mutation_count": 0,
        "recovery_recommendation": "no_action",
    }]
    assert vars(audit) == original


def test_generic_http_409_is_not_safe_for_current_snapshot_contract():
    audit = failed_staging_audit()
    audit.gate_results[0]["message"] = "HTTP 409"
    result = lifecycle._staging_history_eligibility([audit])
    assert result["eligible"] is False
    assert result["reason_code"] == "prior_mutation_outcome_uncertain"


@pytest.mark.parametrize(("changes", "reason"), [
    ({"status": "pending", "transition_history": ["pending"]}, "pending_lifecycle_audit"),
    ({"status": "verified", "transition_history": ["pending", "verified"]}, "prior_verified_staging_exists"),
    ({"wordpress_write_count": None}, "prior_mutation_outcome_uncertain"),
    ({"wordpress_write_count": 2}, "prior_mutation_outcome_uncertain"),
    ({"status": "verification_failed", "transition_history": ["pending", "verification_failed"]}, "prior_mutation_outcome_uncertain"),
    ({"action_type": "enable_metadata_rendering"}, "conflicting_lifecycle_history"),
    ({"action_type": "disable_metadata_rendering"}, "conflicting_lifecycle_history"),
    ({"action_type": "rollback_metadata_payload"}, "conflicting_lifecycle_history"),
    ({"action_type": "unknown"}, "conflicting_lifecycle_history"),
    ({"status": "unknown"}, "conflicting_lifecycle_history"),
    ({"transition_history": ["pending", "verified", "failed"]}, "conflicting_lifecycle_history"),
    ({"post_snapshot": None}, "prior_mutation_outcome_uncertain"),
    ({"gate_results": []}, "prior_mutation_outcome_uncertain"),
    ({"gate_results": [{"code": "wordpress_response", "passed": False, "message": "ReadTimeout"}]}, "prior_mutation_outcome_uncertain"),
    ({"completed_at": None}, "prior_mutation_outcome_uncertain"),
])
def test_staging_history_rejects_unsafe_or_ambiguous_audits(changes, reason):
    result = lifecycle._staging_history_eligibility([failed_staging_audit(**changes)])
    assert result["eligible"] is False
    assert result["reason_code"] == reason


@pytest.mark.parametrize("post_change", [
    {"revision": "1"},
    {"payload_hash": "a" * 64},
    {"payload": {}},
    {"rendering_enabled": True},
    {"enabled_metadata_state": True},
])
def test_failed_audit_with_changed_metadata_state_is_rejected(post_change):
    audit = failed_staging_audit()
    audit.post_snapshot.update(post_change)
    result = lifecycle._staging_history_eligibility([audit])
    assert result["eligible"] is False
    assert result["reason_code"] == "prior_failed_attempt_mutated_state"


def test_one_unsafe_audit_blocks_an_otherwise_safe_history():
    unsafe = failed_staging_audit(2, status="pending", transition_history=["pending"])
    result = lifecycle._staging_history_eligibility([failed_staging_audit(1), unsafe])
    assert result["eligible"] is False
    assert result["reason_code"] == "pending_lifecycle_audit"


@pytest.mark.parametrize(("state", "sync_audits"), [(object(), ()), (None, (object(),))])
def test_metadata_state_or_sync_rows_block_initial_staging(state, sync_audits):
    result = lifecycle._staging_history_eligibility([], state, sync_audits)
    assert result["eligible"] is False
    assert result["reason_code"] == "live_metadata_state_not_initial"


def test_operation_gates_allow_new_preflight_after_safe_failed_history():
    gates = gate_map(lifecycle._operation_gates(
        "stage_metadata_payload",
        {"payload": None, "payload_hash": "", "revision": "0", "rendering_enabled": False},
        None,
        [failed_staging_audit()],
        lifecycle.payload_sha256(),
        observation(),
    ))
    assert gates["initial_state_ready"].passed
    assert gates["historical_failed_attempts_only"].passed
    assert gates["metadata_absent"].passed


@pytest.fixture
def lifecycle_db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'lifecycle.sqlite3').as_posix()}")
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def persisted_failed_staging_audit():
    before = optimistic_snapshot()
    return WordPressMetadataLifecycleAudit(
        generated_page_id=41,
        wordpress_post_id=8,
        installation_audit_id=1,
        activation_audit_id=1,
        action_type="stage_metadata_payload",
        status="failed",
        operator="Shawn Manchette",
        confirmation_phrase_hash="a" * 64,
        handle_fingerprint="b" * 64,
        binding_hash="c" * 64,
        release_identity={},
        backup_evidence={},
        browser_evidence_id="historical-evidence",
        browser_evidence_hashes={},
        payload_hash=lifecycle.payload_sha256(),
        previous_revision="0",
        final_revision="0",
        previous_rendering_enabled=False,
        final_rendering_enabled=False,
        pre_snapshot=deepcopy(before),
        post_snapshot=deepcopy(before),
        page_media_snapshots={},
        gate_results=[{"code": "wordpress_response", "passed": False, "message": "optimistic_snapshot_hash_mismatch"}],
        wordpress_write_count=1,
        wordpress_write_scope=["one rejected staging request"],
        atlas_write_count=2,
        atlas_write_scope=["pending audit", "failed audit"],
        transition_history=["pending", "failed"],
        completed_at=datetime.now(UTC),
        error_code="failed",
    )


class DummyRuntimeIdentity:
    def model_dump(self, mode="json"):
        return {"atlas_version": "v0.59.64", "atlas_commit": "d" * 40, "atlas_tag": "v0.59.64"}


class DummyLifecycleRequest:
    installation_audit_id = 1
    activation_audit_id = 1
    operator = "Shawn Manchette"
    expected_runtime_identity = DummyRuntimeIdentity()
    manual_browser_evidence = SimpleNamespace(
        evidence_id="fresh-evidence",
        rendered_head_hash="e" * 64,
        visible_content_hash="f" * 64,
        evidence_schema_version=1,
    )

    def model_dump(self, mode="json", include=None, exclude=None):
        value = {
            "atlas_data_backup_file": "atlas-data.json",
            "atlas_media_backup_file": "atlas-media.zip",
            "atlas_program_backup_file": "atlas-program.zip",
            "wordpress_backup_method": "SiteGround on-demand full-site backup",
            "wordpress_backup_reference": "Atlas Backup",
            "wordpress_backup_completed_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            "wordpress_database_included_attestation": True,
            "wordpress_plugins_included_attestation": True,
            "wordpress_restore_capability_attestation": True,
            "confirmer_identity": "Shawn Manchette",
            "php_error_log_findings": "No findings",
            "observed_write_summary": "No relevant changes",
            "manual_browser_evidence": None,
        }
        if include is not None:
            value = {key: item for key, item in value.items() if key in include}
        for key in exclude or ():
            value.pop(key, None)
        return value


def test_later_apply_creates_new_verified_audit_and_preserves_failed_audit(monkeypatch, lifecycle_db):
    before = optimistic_snapshot()
    payload = lifecycle.approved_payload().model_dump(mode="json")
    payload_hash = lifecycle.payload_sha256()
    after = optimistic_snapshot(payload=payload, payload_hash=payload_hash, revision="1")
    inspected = {
        "plugin_status": before,
        "page_snapshot_hash": "1" * 64,
        "page_body_hash": "2" * 64,
        "media31_snapshot_hash": "3" * 64,
        "media32_snapshot_hash": "4" * 64,
        "site": {"name": "My WordPress", "description": ""},
        "cache_headers": {},
    }
    rerun = SimpleNamespace(
        preflight_ready=True,
        binding_hash="5" * 64,
        inspected_state=inspected,
        canonical_payload=lifecycle.approved_payload(),
        payload_sha256=payload_hash,
        gate_results=[],
    )
    entry = SimpleNamespace(
        request=DummyLifecycleRequest(),
        binding_hash=rerun.binding_hash,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    observed_after = {
        **{key: inspected[key] for key in ("page_snapshot_hash", "page_body_hash", "media31_snapshot_hash", "media32_snapshot_hash", "site", "cache_headers")},
        "wordpress_request_methods": ["GET"],
        "rendered": empty_rendered(),
    }
    monkeypatch.setattr(lifecycle, "_consume_handle", lambda handle, action: entry)
    monkeypatch.setattr(lifecycle, "lifecycle_preflight", lambda *args, **kwargs: rerun)
    monkeypatch.setattr(lifecycle, "_send_operation", lambda *args, **kwargs: {"status": "metadata_staged", "revision": "1", "rendering_enabled": False})
    monkeypatch.setattr(lifecycle, "_read_status", lambda session: deepcopy(after))
    monkeypatch.setattr(lifecycle, "_observe", lambda session, proof: deepcopy(observed_after))

    with Session(lifecycle_db) as session:
        historical = persisted_failed_staging_audit()
        session.add(historical)
        session.commit()
        session.refresh(historical)
        original = {
            "status": historical.status,
            "history": deepcopy(historical.transition_history),
            "pre": deepcopy(historical.pre_snapshot),
            "post": deepcopy(historical.post_snapshot),
        }
        result = lifecycle.apply_lifecycle(
            session,
            41,
            WordPressMetadataLifecycleApplyRequest(
                lifecycle_handle="h" * 32,
                confirmation_phrase=lifecycle.PHRASES["stage_metadata_payload"],
            ),
            "stage_metadata_payload",
        )
        audits = list(session.exec(select(WordPressMetadataLifecycleAudit).order_by(WordPressMetadataLifecycleAudit.id)))
        assert [audit.id for audit in audits] == [1, 2]
        assert result.lifecycle_audit_id == 2 and result.status == "verified"
        assert audits[1].transition_history == ["pending", "verified"]
        assert audits[1].wordpress_write_count == 1 and audits[1].atlas_write_count == 2
        assert audits[1].final_revision == "1" and audits[1].final_rendering_enabled is False
        assert {"status": audits[0].status, "history": audits[0].transition_history, "pre": audits[0].pre_snapshot, "post": audits[0].post_snapshot} == original
        state = session.exec(select(WordPressMetadataState)).one()
        assert state.status == "staged" and state.wordpress_revision == "1"
        assert state.payload_hash == payload_hash and state.payload == payload


def test_recovery_disable_creates_new_audit_and_preserves_failed_enable(monkeypatch, lifecycle_db):
    payload = lifecycle.approved_payload().model_dump(mode="json")
    payload_hash = lifecycle.payload_sha256()
    before = optimistic_snapshot(
        payload=payload,
        payload_hash=payload_hash,
        revision="1",
        rendering_enabled=True,
        enabled_metadata_state=True,
    )
    after = optimistic_snapshot(
        payload=payload,
        payload_hash=payload_hash,
        revision="1",
        rendering_enabled=False,
        enabled_metadata_state=False,
    )
    inspected = {
        "plugin_status": before,
        "page_snapshot_hash": "1" * 64,
        "page_body_hash": "2" * 64,
        "media31_snapshot_hash": "3" * 64,
        "media32_snapshot_hash": "4" * 64,
        "site": {"name": "My WordPress", "description": ""},
        "cache_headers": {},
    }
    rerun = SimpleNamespace(
        preflight_ready=True,
        binding_hash="5" * 64,
        completion_mode=lifecycle.RECOVERY_DISABLE_MODE,
        inspected_state=inspected,
        canonical_payload=lifecycle.approved_payload(),
        payload_sha256=payload_hash,
        gate_results=[],
    )
    entry = SimpleNamespace(
        request=DummyLifecycleRequest(),
        binding_hash=rerun.binding_hash,
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    observed_after = {
        **{
            key: inspected[key]
            for key in (
                "page_snapshot_hash",
                "page_body_hash",
                "media31_snapshot_hash",
                "media32_snapshot_hash",
                "site",
                "cache_headers",
            )
        },
        "wordpress_request_methods": ["GET"],
        "rendered": empty_rendered(),
    }
    source = failed_enable_audit()
    historical = WordPressMetadataLifecycleAudit(
        id=3,
        generated_page_id=41,
        wordpress_post_id=8,
        installation_audit_id=1,
        activation_audit_id=1,
        action_type=source.action_type,
        completion_mode=lifecycle.STANDARD_MODE,
        status=source.status,
        operator="Shawn Manchette",
        confirmation_phrase_hash="a" * 64,
        handle_fingerprint="b" * 64,
        binding_hash="c" * 64,
        release_identity={},
        backup_evidence={},
        browser_evidence_id="failed-enable-evidence",
        browser_evidence_hashes={},
        payload_hash=payload_hash,
        previous_revision="1",
        final_revision="1",
        previous_rendering_enabled=False,
        final_rendering_enabled=True,
        pre_snapshot=source.pre_snapshot,
        post_snapshot=source.post_snapshot,
        page_media_snapshots=source.page_media_snapshots,
        gate_results=source.gate_results,
        wordpress_write_count=1,
        wordpress_write_scope=lifecycle.WORDPRESS_SCOPES["enable_metadata_rendering"],
        atlas_write_count=2,
        atlas_write_scope=lifecycle.ATLAS_SCOPE,
        transition_history=["pending", "verification_failed"],
        completed_at=datetime.now(UTC),
        error_code="verification_failed",
        recovery_recommendation=None,
    )
    monkeypatch.setattr(lifecycle, "_consume_handle", lambda handle, action: entry)
    monkeypatch.setattr(lifecycle, "lifecycle_preflight", lambda *args, **kwargs: rerun)
    monkeypatch.setattr(
        lifecycle,
        "_send_operation",
        lambda *args, **kwargs: {"status": "metadata_rendering_disabled", "revision": "1", "rendering_enabled": False},
    )
    monkeypatch.setattr(lifecycle, "_read_status", lambda session: deepcopy(after))
    monkeypatch.setattr(lifecycle, "_observe", lambda session, proof: deepcopy(observed_after))

    with Session(lifecycle_db) as session:
        session.add(historical)
        session.add(
            WordPressMetadataState(
                generated_page_id=41,
                wordpress_post_id=8,
                status="staged",
                payload=payload,
                payload_hash=payload_hash,
                wordpress_revision="1",
            )
        )
        session.commit()
        original = deepcopy(session.get(WordPressMetadataLifecycleAudit, 3).model_dump())
        result = lifecycle.apply_lifecycle(
            session,
            41,
            WordPressMetadataLifecycleApplyRequest(
                lifecycle_handle="h" * 32,
                confirmation_phrase=lifecycle.PHRASES["disable_metadata_rendering"],
            ),
            "disable_metadata_rendering",
        )
        preserved = session.get(WordPressMetadataLifecycleAudit, 3)
        created = session.get(WordPressMetadataLifecycleAudit, result.lifecycle_audit_id)
        assert preserved.model_dump() == original
        assert created.id != 3 and created.status == "verified"
        assert created.completion_mode == lifecycle.RECOVERY_DISABLE_MODE
        assert created.wordpress_write_scope == lifecycle.WORDPRESS_SCOPES["disable_metadata_rendering"]
        assert created.wordpress_write_count == 1 and created.atlas_write_count == 2
        assert result.completion_mode == lifecycle.RECOVERY_DISABLE_MODE
        assert result.rendering_enabled is False and result.wordpress_revision == "1"
        assert result.payload_hash == payload_hash
        state = session.exec(select(WordPressMetadataState)).one()
        assert state.status == "staged" and state.payload == payload
        assert state.payload_hash == payload_hash and state.wordpress_revision == "1"


def audit(action, status="verified", audit_id=1, **changes):
    value = {"id": audit_id, "action_type": action, "status": status}
    value.update(changes)
    return SimpleNamespace(**value)


def staged_snapshot(enabled=False):
    return {"payload": lifecycle.approved_payload().model_dump(mode="json"), "payload_hash": lifecycle.payload_sha256(), "revision": "1", "rendering_enabled": enabled}


def metadata_state(status="staged"):
    return SimpleNamespace(
        status=status,
        payload=lifecycle.approved_payload().model_dump(mode="json"),
        payload_hash=lifecycle.payload_sha256(),
        wordpress_revision="1",
    )


def recovery_observation(*, metadata_present=False, drift=None):
    value = {
        "page_snapshot_hash": "1" * 64,
        "page_body_hash": "2" * 64,
        "media31_snapshot_hash": "3" * 64,
        "media32_snapshot_hash": "4" * 64,
        "cache_headers": {},
        "rendered": empty_rendered(),
    }
    if metadata_present:
        value["rendered"]["metadata_inventory"]["meta_descriptions"] = [lifecycle.approved_payload().meta_description]
    if drift:
        value[drift] = "9" * 64
    return value


def failed_enable_audit(**changes):
    payload = lifecycle.approved_payload().model_dump(mode="json")
    payload_hash = lifecycle.payload_sha256()
    pre = optimistic_snapshot(payload=payload, payload_hash=payload_hash, revision="1", rendering_enabled=False)
    post = optimistic_snapshot(payload=payload, payload_hash=payload_hash, revision="1", rendering_enabled=True, enabled_metadata_state=True)
    value = {
        "id": 3,
        "action_type": "enable_metadata_rendering",
        "status": "verification_failed",
        "transition_history": ["pending", "verification_failed"],
        "wordpress_write_count": 1,
        "wordpress_write_scope": lifecycle.WORDPRESS_SCOPES["enable_metadata_rendering"],
        "atlas_write_count": 2,
        "previous_revision": "1",
        "final_revision": "1",
        "previous_rendering_enabled": False,
        "final_rendering_enabled": True,
        "pre_snapshot": pre,
        "post_snapshot": post,
        "page_media_snapshots": {
            "page_snapshot_hash": "1" * 64,
            "page_body_hash": "2" * 64,
            "media31_snapshot_hash": "3" * 64,
            "media32_snapshot_hash": "4" * 64,
            "cache_headers": {},
        },
        "gate_results": [
            {"code": "plugin_state", "passed": True},
            {"code": "page", "passed": True},
            {"code": "media", "passed": True},
            {"code": "cache", "passed": True},
            {"code": "rendered_exact", "passed": False},
        ],
        "completed_at": datetime.now(UTC),
        "recovery_recommendation": None,
    }
    value.update(changes)
    return SimpleNamespace(**value)


def test_enable_requires_verified_staging_and_does_not_accept_drift():
    gates = gate_map(lifecycle._operation_gates("enable_metadata_rendering", staged_snapshot(), object(), [audit("stage_metadata_payload")], lifecycle.payload_sha256(), observation()))
    assert gates["staged"].passed
    assert not gate_map(lifecycle._operation_gates("enable_metadata_rendering", staged_snapshot(), object(), [], lifecycle.payload_sha256(), observation()))["staged"].passed


def test_disable_preserves_payload_contract():
    audits = [audit("stage_metadata_payload", audit_id=1), audit("enable_metadata_rendering", audit_id=2)]
    gates = gate_map(lifecycle._operation_gates("disable_metadata_rendering", staged_snapshot(True), metadata_state("rendering_enabled"), audits, lifecycle.payload_sha256(), observation()))
    assert gates["verified_enable_ready"].passed
    assert lifecycle._expected_revision("disable_metadata_rendering") == "1"


def test_recovery_disable_allows_current_production_shaped_failed_enable():
    audits = [audit("stage_metadata_payload", audit_id=2), failed_enable_audit()]
    result = lifecycle._disable_eligibility(
        staged_snapshot(True), metadata_state(), audits, lifecycle.payload_sha256(), recovery_observation()
    )
    assert result == {
        "eligible": True,
        "reason_code": "recovery_disable_ready",
        "message": "The conclusively accepted failed-verification enablement is eligible for recovery disablement.",
        "completion_mode": "recovery_after_failed_enable_verification",
        "source_enable_audit_id": 3,
    }


@pytest.mark.parametrize(
    ("audit_changes", "snapshot_changes", "state_changes", "observation_changes", "reason"),
    [
        ({"wordpress_write_count": 0}, {}, {}, {}, "enable_mutation_not_proven"),
        ({"wordpress_write_count": None}, {}, {}, {}, "enable_mutation_not_proven"),
        ({"wordpress_write_count": 2}, {}, {}, {}, "enable_mutation_not_proven"),
        ({"wordpress_write_scope": ["PUT /wrong"]}, {}, {}, {}, "enable_mutation_not_proven"),
        ({"post_snapshot": None}, {}, {}, {}, "enable_outcome_uncertain"),
        ({"transition_history": ["pending", "verified", "verification_failed"]}, {}, {}, {}, "enable_outcome_uncertain"),
        ({"recovery_recommendation": "siteground_restore"}, {}, {}, {}, "recovery_recommendation_mismatch"),
        ({}, {"rendering_enabled": False}, {}, {}, "rendering_not_enabled"),
        ({}, {"payload_hash": "9" * 64}, {}, {}, "staged_payload_drift"),
        ({}, {"revision": "2"}, {}, {}, "staged_payload_drift"),
        ({}, {}, {"status": "rendering_enabled"}, {}, "staged_payload_drift"),
        ({}, {}, {}, {"metadata_present": True}, "public_metadata_unexpectedly_present"),
        ({}, {}, {}, {"drift": "media31_snapshot_hash"}, "enable_outcome_uncertain"),
    ],
)
def test_recovery_disable_fails_closed(audit_changes, snapshot_changes, state_changes, observation_changes, reason):
    candidate = failed_enable_audit(**audit_changes)
    snapshot = staged_snapshot(True)
    snapshot.update(snapshot_changes)
    state = metadata_state()
    for key, value in state_changes.items():
        setattr(state, key, value)
    observed = recovery_observation(**observation_changes)
    result = lifecycle._disable_eligibility(
        snapshot,
        state,
        [audit("stage_metadata_payload", audit_id=2), candidate],
        lifecycle.payload_sha256(),
        observed,
    )
    assert result["eligible"] is False
    assert result["reason_code"] == reason


def test_recovery_disable_blocks_pending_later_enable_and_completed_recovery():
    base = [audit("stage_metadata_payload", audit_id=2), failed_enable_audit()]
    cases = [
        (base + [audit("enable_metadata_rendering", "pending", 4)], "pending_rendering_operation"),
        (base + [audit("disable_metadata_rendering", "verified", 4)], "recovery_already_completed"),
        (base + [audit("rollback_metadata_payload", "failed", 4)], "conflicting_rendering_history"),
    ]
    for audits, reason in cases:
        result = lifecycle._disable_eligibility(
            staged_snapshot(True), metadata_state(), audits, lifecycle.payload_sha256(), recovery_observation()
        )
        assert result["eligible"] is False and result["reason_code"] == reason


def test_later_verified_enable_uses_ordinary_mode_not_recovery_mode():
    audits = [
        audit("stage_metadata_payload", audit_id=2),
        failed_enable_audit(),
        audit("enable_metadata_rendering", "verified", 4),
    ]
    result = lifecycle._disable_eligibility(
        staged_snapshot(True),
        metadata_state("rendering_enabled"),
        audits,
        lifecycle.payload_sha256(),
        recovery_observation(),
    )
    assert result["eligible"] is True
    assert result["reason_code"] == "verified_enable_ready"
    assert result["completion_mode"] == "ordinary_after_verified_enable"


def test_rendering_source_diagnostics_are_read_only_and_find_public_hook_contract():
    result = lifecycle.rendering_source_diagnostics()
    assert result["read_only"] is True
    assert result["wordpress_write_count"] == result["atlas_write_count"] == 0
    assert result["hook"] == "wp_head" and result["hook_priority"] == 20
    assert result["hook_priority_exact"] is True
    assert result["page_target"] == "is_page(8)"
    assert result["payload_post_id"] == result["enabled_state_post_id"] == 8
    assert result["normal_public_request_reachable"] is True
    assert result["root_cause_classification"] == "other_exactly_described_condition"


def test_rollback_fails_closed_while_rendering_enabled():
    audits = [audit("stage_metadata_payload"), audit("enable_metadata_rendering"), audit("disable_metadata_rendering")]
    assert not gate_map(lifecycle._operation_gates("rollback_metadata_payload", staged_snapshot(True), object(), audits, lifecycle.payload_sha256(), observation()))["disabled"].passed
    assert all(g.passed for g in lifecycle._operation_gates("rollback_metadata_payload", staged_snapshot(False), object(), audits, lifecycle.payload_sha256(), observation()))
    assert lifecycle._expected_revision("rollback_metadata_payload") == "0"


@pytest.mark.parametrize("action", list(lifecycle.PHRASES))
def test_handle_is_short_lived_single_use_and_action_bound(action):
    lifecycle._clear_lifecycle_handles()
    request = object()
    handle = lifecycle._store_handle(action, request, "b" * 64, datetime.now(UTC) + timedelta(minutes=1))
    entry = lifecycle._consume_handle(handle, action)
    assert entry.action == action and entry.request is request
    with pytest.raises(HTTPException): lifecycle._consume_handle(handle, action)


def test_handle_rejects_wrong_action_and_restart():
    lifecycle._clear_lifecycle_handles()
    handle = lifecycle._store_handle("stage_metadata_payload", object(), "b" * 64, datetime.now(UTC) + timedelta(minutes=1))
    with pytest.raises(HTTPException): lifecycle._consume_handle(handle, "enable_metadata_rendering")
    handle = lifecycle._store_handle("stage_metadata_payload", object(), "b" * 64, datetime.now(UTC) + timedelta(minutes=1))
    lifecycle._clear_lifecycle_handles()
    with pytest.raises(HTTPException): lifecycle._consume_handle(handle, "stage_metadata_payload")


def test_plugin_contract_has_four_isolated_mutations_and_disables_legacy_apply():
    source = (resolve_program_root() / "wordpress/project-atlas-metadata-bridge/project-atlas-metadata-bridge.php").read_text(encoding="utf-8")
    assert "Version: 0.57.5" in source
    assert "atlas_legacy_combined_apply_disabled" in source
    for callback in ("atlas_metadata_stage", "atlas_metadata_rendering_enable", "atlas_metadata_rendering_disable", "atlas_metadata_stage_rollback"):
        assert f"function {callback}" in source
    stage = source[source.index("function atlas_metadata_stage("):source.index("function atlas_metadata_rendering_enable(")]
    enable = source[source.index("function atlas_metadata_rendering_enable("):source.index("function atlas_metadata_rendering_disable(")]
    disable = source[source.index("function atlas_metadata_rendering_disable("):source.index("function atlas_metadata_stage_rollback(")]
    rollback = source[source.index("function atlas_metadata_stage_rollback("):source.index("function atlas_metadata_rollback(")]
    assert "enabled'=>true" not in stage and "_atlas_metadata_enabled', '1'" not in stage
    assert "update_post_meta(8, '_atlas_metadata_payload'" not in enable
    assert "_atlas_metadata_payload'" not in disable and "_atlas_metadata_payload_hash'" not in disable
    assert "atlas_rollback_rendering_enabled" in rollback


def test_backend_and_plugin_optimistic_snapshot_fields_are_identical():
    source = (resolve_program_root() / "wordpress/project-atlas-metadata-bridge/project-atlas-metadata-bridge.php").read_text(encoding="utf-8")
    function = source[source.index("function atlas_metadata_snapshot_hash("):source.index("function atlas_metadata_lifecycle_request(")]
    plugin_fields = tuple(re.findall(r"'([^']+)'", function[function.index("foreach ("):function.index("] as $key")]))
    assert plugin_fields == lifecycle.OPTIMISTIC_SNAPSHOT_FIELDS
    assert tuple(lifecycle._canonical_optimistic_snapshot(optimistic_snapshot())) == plugin_fields


def test_snapshot_hash_matches_plugin_canonical_json_contract():
    value = optimistic_snapshot()
    canonical = {key: value[key] for key in lifecycle.OPTIMISTIC_SNAPSHOT_FIELDS}
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    expected = hashlib.sha256(encoded).hexdigest()
    assert expected == "6d555136d773d25739b8669a49b8fdbb6712e4914b72ca87d2e070557059e4a8"
    assert lifecycle._snapshot_hash(value) == expected
    assert lifecycle._snapshot_hash(dict(reversed(list(value.items())))) == expected


def test_snapshot_hash_is_whitespace_independent_and_unicode_stable():
    payload = {"label": "Orlando – Florida", "nested": {"b": 2, "a": 1}}
    value = optimistic_snapshot(payload=payload, payload_hash="a" * 64, revision="1")
    compact = lifecycle._snapshot_hash(value)
    round_trip = json.loads(json.dumps(value, indent=4, ensure_ascii=False))
    assert lifecycle._snapshot_hash(round_trip) == compact
    encoded = json.dumps(
        lifecycle._canonical_optimistic_snapshot(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    assert "\\u2013" in encoded


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"plugin_checksum": ""}, "plugin_checksum_missing"),
        ({"plugin_checksum": "f" * 64}, "plugin_checksum_mismatch"),
        ({"plugin_checksum": ZIP_CHECKSUM}, "plugin_checksum_mismatch"),
        ({"version": "0.57.4"}, "snapshot_field_mismatch"),
        ({"active": False}, "snapshot_field_mismatch"),
        ({"rendering_enabled": 0}, "snapshot_field_mismatch"),
        ({"enabled_metadata_state": 1}, "snapshot_field_mismatch"),
        ({"revision": 0}, "snapshot_field_mismatch"),
        ({"revision": "01"}, "snapshot_field_mismatch"),
        ({"payload": ""}, "snapshot_field_mismatch"),
    ],
)
def test_snapshot_contract_fails_closed(changes, reason):
    with pytest.raises(ValueError, match=reason):
        lifecycle._snapshot_hash(optimistic_snapshot(**changes))


def test_public_status_preserves_installed_executable_checksum():
    public = lifecycle._public_status(optimistic_snapshot())
    assert public["plugin_checksum"] == EXECUTABLE_CHECKSUM
    assert public["checksum"] == EXECUTABLE_CHECKSUM
    assert lifecycle._snapshot_contract_error(public) is None


def test_missing_snapshot_field_fails_before_wordpress_request(monkeypatch):
    called = False

    class ForbiddenClient:
        def __init__(self, *args, **kwargs):
            nonlocal called
            called = True

    monkeypatch.setattr(lifecycle.httpx, "Client", ForbiddenClient)
    value = optimistic_snapshot()
    value.pop("activation_generation")
    result = lifecycle._send_operation(None, "stage_metadata_payload", object(), value)
    assert result == {"_error": "snapshot_field_mismatch", "reason_code": "snapshot_field_mismatch", "status_code": 409}
    assert called is False


@pytest.mark.parametrize(
    ("wordpress_code", "reason"),
    [
        ("atlas_snapshot_conflict", "optimistic_snapshot_hash_mismatch"),
        ("atlas_revision_conflict", "snapshot_field_mismatch"),
        ("atlas_post_changed", "snapshot_field_mismatch"),
        ("atlas_media_changed", "snapshot_field_mismatch"),
    ],
)
def test_wordpress_409_reports_only_safe_reason_codes(monkeypatch, wordpress_code, reason):
    captured = []

    class Response:
        status_code = 409

        @staticmethod
        def json():
            return {"code": wordpress_code, "message": "must not be returned"}

    class Client:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def put(self, url, **kwargs):
            captured.append((url, kwargs))
            return Response()

    monkeypatch.setattr(lifecycle, "read_wordpress_settings", lambda session: SimpleNamespace(site_url="https://example.test", username="operator"))
    monkeypatch.setattr(lifecycle, "get_wordpress_application_password", lambda: "process-only")
    monkeypatch.setattr(lifecycle.httpx, "Client", Client)
    preflight = SimpleNamespace(canonical_payload=lifecycle.approved_payload(), payload_sha256=lifecycle.payload_sha256())
    result = lifecycle._send_operation(None, "stage_metadata_payload", preflight, optimistic_snapshot())
    assert result == {"_error": reason, "reason_code": reason, "wordpress_error_code": wordpress_code, "status_code": 409}
    assert len(captured) == 1 and "message" not in str(result)


def test_staging_request_uses_matching_hash_and_cannot_enable_rendering(monkeypatch):
    captured = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"status": "metadata_staged", "revision": "1", "rendering_enabled": False}

    class Client:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def put(self, url, **kwargs):
            captured.append((url, kwargs["json"]))
            return Response()

    monkeypatch.setattr(lifecycle, "read_wordpress_settings", lambda session: SimpleNamespace(site_url="https://example.test", username="operator"))
    monkeypatch.setattr(lifecycle, "get_wordpress_application_password", lambda: "process-only")
    monkeypatch.setattr(lifecycle.httpx, "Client", Client)
    preflight = SimpleNamespace(canonical_payload=lifecycle.approved_payload(), payload_sha256=lifecycle.payload_sha256())
    before = optimistic_snapshot()
    result = lifecycle._send_operation(None, "stage_metadata_payload", preflight, before)
    assert result == {"status": "metadata_staged", "revision": "1", "rendering_enabled": False}
    assert captured == [("https://example.test/wp-json/project-atlas/v2/pages/8/metadata/stage", {
        "expected_revision": "0",
        "expected_snapshot_hash": lifecycle._snapshot_hash(before),
        "payload": lifecycle.approved_payload().model_dump(mode="json"),
        "payload_hash": lifecycle.payload_sha256(),
    })]
    assert "rendering_enabled" not in captured[0][1]


def test_write_scope_functions_have_no_page_media_site_or_cache_mutation():
    source = inspect.getsource(lifecycle._send_operation)
    assert "PLUGIN_PATHS[action]" in source
    assert "client.put" in source
    for forbidden in ("wp/v2/pages", "wp/v2/media", "/options", "/cache", "/plugins"):
        assert forbidden not in source


def test_preflight_source_contains_no_commit_or_wordpress_write():
    source = inspect.getsource(lifecycle.lifecycle_preflight)
    assert "session.commit" not in source
    assert "client.put" not in source and "client.post" not in source
    assert "_store_handle" in source


def test_phrases_and_write_scopes_are_operation_specific():
    assert len(set(lifecycle.PHRASES.values())) == 4
    assert lifecycle.PHRASES == {
        "stage_metadata_payload": "STAGE PROJECT ATLAS METADATA PAYLOAD",
        "enable_metadata_rendering": "ENABLE PROJECT ATLAS METADATA RENDERING",
        "disable_metadata_rendering": "DISABLE PROJECT ATLAS METADATA RENDERING",
        "rollback_metadata_payload": "ROLL BACK PROJECT ATLAS METADATA PAYLOAD",
    }
    assert len(set(lifecycle.PLUGIN_PATHS.values())) == 4
