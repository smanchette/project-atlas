from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    WordPressBootstrapEstablishmentAudit,
    WordPressPluginUpgradeAudit,
)
from app.schemas.wordpress import (
    WordPressDeploymentExpectedRuntimeIdentity,
    WordPressPluginUpgradeReconciliationApplyRequest,
    WordPressPluginUpgradeReconciliationRequest,
)
from app.services import wordpress_plugin_upgrade_0577 as upgrade
from app.services import wordpress_plugin_upgrade_reconciliation as reconciliation
from test_wordpress_plugin_upgrade import COMMIT, KEY, MEDIA31_HASH, MEDIA32_HASH, PAGE_HASH
from test_wordpress_plugin_upgrade_0577 import (
    PAYLOAD_HASH,
    bootstrap_status,
    observation,
    seed,
    status,
)
from app.services.wordpress_rendered_state import build_manual_browser_evidence


HTML = """<!doctype html><html><head>
<title>Drywood Termite Tenting in Orlando, FL – My WordPress</title>
<link rel="canonical" href="https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/">
</head><body><h1>Drywood Termite Tenting in Orlando, FL</h1>
<img src="https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png"
alt="Two-story Orlando Florida home professionally covered for drywood termite tenting">
Orlando content</body></html>"""


@pytest.fixture(autouse=True)
def clear_handles(monkeypatch):
    reconciliation._clear_reconciliation_handles()
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    yield
    reconciliation._clear_reconciliation_handles()


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'upgrade-reconciliation.sqlite3').as_posix()}")
    SQLModel.metadata.create_all(engine)
    return engine


def evidence(identifier="orlando-fresh-upgrade-reconciliation", captured_at=None):
    return build_manual_browser_evidence(
        HTML,
        final_url="https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/",
        evidence_identifier=identifier,
        signing_key=KEY,
        captured_at=captured_at,
    )


def request(**changes):
    value = {
        "upgrade_audit_id": 3,
        "operator": "Shawn Manchette",
        "manual_browser_evidence": evidence(),
        "expected_runtime_identity": WordPressDeploymentExpectedRuntimeIdentity(
            atlas_version="v0.59.99",
            atlas_commit=COMMIT,
            atlas_tag="v0.59.99",
            manifest_sha256="b" * 64,
            source_compatibility_id="project-atlas-release-identity-v0.59.96",
        ),
        "repository_head": COMMIT,
        "repository_origin_main": COMMIT,
        "repository_tag": "v0.59.99",
        "repository_branch": "main",
        "repository_working_tree_clean": True,
        "protected_paths_unchanged": True,
        "atlas_data_backup_file": "atlas-backup-fresh.json",
        "atlas_data_backup_sha256": "c" * 64,
        "atlas_data_backup_size": 1024,
        "atlas_data_backup_created_at": datetime.now(UTC),
        "atlas_data_backup_onedrive_path": (
            r"C:\Users\offic\OneDrive\Atlas\atlas-backup-fresh.json"
        ),
        "atlas_data_backup_onedrive_synced": True,
    }
    value.update(changes)
    return WordPressPluginUpgradeReconciliationRequest(**value)


def establishment(audit_id, status_value):
    retired = status_value == "authorization_retired"
    return WordPressBootstrapEstablishmentAudit(
        id=audit_id,
        generated_page_id=41,
        wordpress_post_id=8,
        installation_audit_id=1,
        activation_audit_id=1,
        status=status_value,
        retirement_reason=(
            reconciliation.RETIREMENT_REASON if retired else None
        ),
        operator="Shawn Manchette",
        bootstrap_slug="project-atlas-upgrade-bootstrap",
        bootstrap_directory="project-atlas-upgrade-bootstrap",
        bootstrap_path=reconciliation.BOOTSTRAP_ENTRY,
        bootstrap_version="0.3.0",
        bootstrap_zip_filename="project-atlas-upgrade-bootstrap-0.3.0.zip",
        bootstrap_zip_sha256=upgrade.BOOTSTRAP_ZIP_SHA256,
        bootstrap_entry_sha256=upgrade.BOOTSTRAP_ENTRY_SHA256,
        manual_phrase_hash=str(audit_id) * 64,
        activation_phrase_hash=hex(audit_id)[2:] * 64,
        manual_handle_fingerprint=chr(96 + audit_id) * 64,
        activation_handle_fingerprint=(chr(100 + audit_id) * 64 if not retired else None),
        manual_binding_hash=chr(102 + audit_id) * 64,
        activation_binding_hash=(chr(104 + audit_id) * 64 if not retired else None),
        release_identity={},
        backup_evidence={},
        browser_evidence_id=f"bootstrap-{audit_id}",
        pre_snapshot={},
        upload_snapshot={},
        final_snapshot={},
        source_inventories={},
        upload_inventories={},
        final_inventories={},
        protected_state={},
        gate_results=[],
        checksum_verification_source=(upgrade.BOOTSTRAP_STATUS_ROUTE if not retired else None),
        checksum_verification_result=("matched" if not retired else None),
        wordpress_write_count=(1 if not retired else 0),
        atlas_write_count=(6 if not retired else 4),
        transition_history=(
            ["awaiting_manual_bootstrap_installation", "authorization_retired"]
            if retired
            else [
                "awaiting_manual_bootstrap_installation",
                "manual_installation_inventory_verified",
                "activation_pending_checksum_verification",
                "verification_failed",
                "recovery_required",
                "post_activation_verifier_contract_defect_reconciled",
            ]
        ),
        completed_at=datetime.now(UTC),
    )


def seed_reconciliation(session):
    seed(session)
    original = session.get(WordPressBootstrapEstablishmentAudit, 1)
    session.delete(original)
    session.flush()
    session.add(establishment(1, "authorization_retired"))
    session.add(establishment(2, "verified"))
    before = observation()
    after = observation(upgrade.TARGET_VERSION)
    after["cache_headers"]["x-proxy-cache"] = "MISS"
    after["cache_headers"]["x-proxy-cache-info"] = "0 NC:000000 UP:"
    after["rendered"]["cache_headers"] = deepcopy(after["cache_headers"])
    after["plugin_status"] = status(upgrade.TARGET_VERSION)
    session.add(
        WordPressPluginUpgradeAudit(
            id=3,
            generated_page_id=41,
            wordpress_post_id=8,
            installation_audit_id=1,
            activation_audit_id=1,
            status="verification_failed",
            operator="Shawn Manchette",
            confirmation_phrase_hash="7" * 64,
            handle_fingerprint="8" * 64,
            binding_hash="9" * 64,
            previous_version=upgrade.CURRENT_VERSION,
            target_version=upgrade.TARGET_VERSION,
            previous_artifact_sha256=upgrade.CURRENT_ZIP_SHA256,
            target_artifact_sha256=upgrade.ZIP_SHA256,
            release_identity=deepcopy(
                reconciliation.HISTORICAL_CAPTURE_RELEASE_IDENTITY
            ),
            backup_evidence={},
            browser_evidence_id="orlando-historical-upgrade",
            browser_evidence_hashes={
                "rendered_head": "1" * 64,
                "visible_content": "2" * 64,
                "metadata_inventory": "3" * 64,
            },
            pre_snapshot=before,
            post_snapshot=after,
            previous_inventories={
                "plugins": before["plugin_inventory_hash"],
                "active_plugins": before["active_plugin_inventory_hash"],
            },
            final_inventories={
                "plugins": after["plugin_inventory_hash"],
                "active_plugins": after["active_plugin_inventory_hash"],
            },
            metadata_rendering_state={
                "rendering_enabled": False,
                "payload_hash": PAYLOAD_HASH,
                "revision": "1",
            },
            page_media_snapshots={
                "page": PAGE_HASH,
                "body": upgrade.EXPECTED_CORRECTED_BODY_HASH,
                "media31": MEDIA31_HASH,
                "media32": MEDIA32_HASH,
            },
            gate_results=[
                upgrade._gate("cache_boundary", "cache", False, "volatile").model_dump(mode="json"),
                upgrade._gate("all_other_gates", "durable", True, "").model_dump(mode="json"),
            ],
            wordpress_write_count=1,
            wordpress_write_scope=upgrade.UPGRADE_WORDPRESS_SCOPE,
            atlas_write_count=2,
            atlas_write_scope=upgrade.UPGRADE_ATLAS_SCOPE,
            verification_findings={"failed_gates": ["cache_boundary"]},
            recovery_recommendation="guarded_downgrade",
            transition_history=["pending", "verification_failed"],
            completed_at=datetime.now(UTC),
            error_code="verification_failed",
            error_message="Cache observation changed.",
        )
    )
    session.commit()
    return before, after


def configure(monkeypatch, current=None):
    current = current or observation(upgrade.TARGET_VERSION)
    current["cache_headers"]["x-content-type-options"] = "nosniff"
    current["rendered"]["cache_headers"] = deepcopy(current["cache_headers"])
    current["rendered"]["public_http_observation"]["cache_headers"] = deepcopy(
        current["cache_headers"]
    )
    current["rendered"]["public_http_observation"]["provider_signals"] = deepcopy(
        current["cache_headers"]
    )
    current["rendered"].setdefault(
        "browser_evidence_identifier",
        "orlando-fresh-upgrade-reconciliation",
    )
    current["rendered"].setdefault("evidence_schema_version", 1)
    monkeypatch.setattr(reconciliation, "_observe", lambda session, request: deepcopy(current))
    repeated = deepcopy(current["rendered"])
    repeated["source"] = "public"
    monkeypatch.setattr(
        reconciliation,
        "_acquire_repeated_public_observations",
        lambda: [deepcopy(repeated), deepcopy(repeated)],
    )
    monkeypatch.setattr(
        reconciliation,
        "deployment_readiness",
        lambda: {
            "release_status": "verified",
            "release": {
                "atlas_version": "v0.59.99",
                "atlas_commit": COMMIT,
                "atlas_tag": "v0.59.99",
                "manifest_sha256": "b" * 64,
                "source_compatibility_id": "project-atlas-release-identity-v0.59.96",
                "runtime_identity_verified": True,
                "manifest_integrity_verified": True,
                "expected_release_matched": True,
                "generated_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
            },
        },
    )
    monkeypatch.setattr(
        reconciliation,
        "_backup",
        lambda request, release, audit: (
            {"file_name": request.atlas_data_backup_file, "sha256": request.atlas_data_backup_sha256},
            [upgrade._gate("atlas_data_backup", "fresh backup", True, "")],
        ),
    )
    monkeypatch.setattr(
        reconciliation.upgrade,
        "_read_plugin_status",
        lambda session: status(upgrade.TARGET_VERSION),
    )
    monkeypatch.setattr(
        reconciliation.upgrade,
        "_read_bootstrap_status",
        lambda session: bootstrap_status(
            available=False,
            plugin_version=upgrade.TARGET_VERSION,
        ),
    )
    monkeypatch.setattr(reconciliation, "_pending_operation_exists", lambda session: False)
    return current


def failed_codes(result):
    return {gate.code for gate in result.gate_results if not gate.passed}


def test_reconciliation_release_identity_is_exactly_v05999():
    assert reconciliation.AUDIT_ID == 3
    assert reconciliation.RELEASE_VERSION == "v0.59.99"
    assert reconciliation.RECONCILIATION_PHRASE == (
        "RECONCILE PROJECT ATLAS METADATA BRIDGE UPGRADE AUDIT 3 "
        "WITHOUT ANOTHER WORDPRESS WRITE"
    )
    assert request().repository_tag == "v0.59.99"
    assert request().expected_runtime_identity.atlas_version == "v0.59.99"
    assert request().expected_runtime_identity.atlas_tag == "v0.59.99"


@pytest.mark.parametrize(
    "repository_tag",
    ["v0.59.96", "v0.59.97", "v0.59.98", "future", ""],
)
def test_reconciliation_schema_rejects_non_v05999_repository_tags(repository_tag):
    with pytest.raises(ValidationError):
        request(repository_tag=repository_tag)


@pytest.mark.parametrize("release_version", ["v0.59.96", "v0.59.97", "v0.59.98"])
def test_reconciliation_rejects_cross_release_expected_runtime(
    monkeypatch, db, release_version
):
    configure(monkeypatch)
    cross_release = request(
        expected_runtime_identity=WordPressDeploymentExpectedRuntimeIdentity(
            atlas_version=release_version,
            atlas_commit=COMMIT,
            atlas_tag=release_version,
            manifest_sha256="b" * 64,
            source_compatibility_id="project-atlas-release-identity-v0.59.96",
        )
    )
    with Session(db) as session:
        seed_reconciliation(session)
        result = reconciliation.reconciliation_preflight(
            session, 41, cross_release
        )
        assert not result.reconciliation_ready
        assert "runtime_identity" in failed_codes(result)
        assert not reconciliation._handles


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("atlas_version", "v0.59.97"),
        ("atlas_commit", "f" * 40),
        ("atlas_tag", "v0.59.97"),
        ("manifest_integrity_verified", False),
        ("expected_release_matched", False),
    ],
)
def test_reconciliation_rejects_runtime_manifest_commit_or_tag_drift(
    monkeypatch, db, field, value
):
    configure(monkeypatch)
    release = {
        "atlas_version": "v0.59.99",
        "atlas_commit": COMMIT,
        "atlas_tag": "v0.59.99",
        "manifest_sha256": "b" * 64,
        "source_compatibility_id": "project-atlas-release-identity-v0.59.96",
        "runtime_identity_verified": True,
        "manifest_integrity_verified": True,
        "expected_release_matched": True,
        "generated_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
    }
    release[field] = value
    monkeypatch.setattr(
        reconciliation,
        "deployment_readiness",
        lambda: {"release_status": "verified", "release": release},
    )
    with Session(db) as session:
        seed_reconciliation(session)
        result = reconciliation.reconciliation_preflight(session, 41, request())
        assert not result.reconciliation_ready
        assert "runtime_identity" in failed_codes(result)
        assert not reconciliation._handles


def test_reconciliation_rejects_evidence_captured_before_loaded_runtime(
    monkeypatch, db
):
    configure(monkeypatch)
    runtime_generated_at = datetime.now(UTC) - timedelta(minutes=1)
    monkeypatch.setattr(
        reconciliation,
        "deployment_readiness",
        lambda: {
            "release_status": "verified",
            "release": {
                "atlas_version": "v0.59.99",
                "atlas_commit": COMMIT,
                "atlas_tag": "v0.59.99",
                "manifest_sha256": "b" * 64,
                "source_compatibility_id": (
                    "project-atlas-release-identity-v0.59.96"
                ),
                "runtime_identity_verified": True,
                "manifest_integrity_verified": True,
                "expected_release_matched": True,
                "generated_at": runtime_generated_at.isoformat(),
            },
        },
    )
    cross_release_evidence = evidence(
        "orlando-cross-release-evidence",
        runtime_generated_at - timedelta(minutes=1),
    )
    with Session(db) as session:
        seed_reconciliation(session)
        result = reconciliation.reconciliation_preflight(
            session,
            41,
            request(manual_browser_evidence=cross_release_evidence),
        )
        assert not result.reconciliation_ready
        assert "fresh_evidence" in failed_codes(result)
        assert not reconciliation._handles


def test_reconciliation_rejects_backup_created_before_loaded_runtime(
    monkeypatch, db, tmp_path
):
    backup_path = tmp_path / "atlas-backup-cross-release.json"
    backup_path.write_bytes(b"cross-release-backup")
    runtime_generated_at = datetime.now(UTC)
    backup_created_at = runtime_generated_at - timedelta(minutes=1)
    with Session(db) as session:
        seed_reconciliation(session)
        audit = session.get(WordPressPluginUpgradeAudit, 3)
        backup_payload = {
            "metadata": {"created_at": backup_created_at.isoformat()},
            "data": {
                "wordpress_plugin_upgrade_audits": [
                    {
                        "id": 3,
                        "status": audit.status,
                        "wordpress_write_count": audit.wordpress_write_count,
                        "atlas_write_count": audit.atlas_write_count,
                        "transition_history": audit.transition_history,
                        "reconciliation_reason": audit.reconciliation_reason,
                    }
                ]
            },
        }
        monkeypatch.setattr(
            reconciliation,
            "resolve_backup_download",
            lambda file_name: backup_path,
        )
        monkeypatch.setattr(
            reconciliation,
            "load_backup",
            lambda path: backup_payload,
        )
        backup_request = request(
            atlas_data_backup_file=backup_path.name,
            atlas_data_backup_sha256=hashlib.sha256(
                backup_path.read_bytes()
            ).hexdigest(),
            atlas_data_backup_size=backup_path.stat().st_size,
            atlas_data_backup_created_at=backup_created_at,
            atlas_data_backup_onedrive_path=(
                rf"C:\Users\offic\OneDrive\Atlas\{backup_path.name}"
            ),
        )
        _, gates = reconciliation._backup(
            backup_request,
            {"generated_at": runtime_generated_at.isoformat()},
            audit,
        )
        by_code = {gate.code: gate for gate in gates}
        assert by_code["atlas_data_backup_structure"].passed
        assert by_code["atlas_data_backup_identity"].passed
        assert not by_code["atlas_data_backup_fresh"].passed
        assert by_code["atlas_data_backup_audit"].passed
        assert by_code["atlas_data_backup_onedrive"].passed


def test_reconciliation_preflight_is_fresh_read_only_and_zero_write(monkeypatch, db):
    current = configure(monkeypatch)
    with Session(db) as session:
        seed_reconciliation(session)
        before = session.get(WordPressPluginUpgradeAudit, 3).model_dump()
        result = reconciliation.reconciliation_preflight(session, 41, request())
        assert result.reconciliation_ready is True, [
            (gate.code, gate.message) for gate in result.gate_results if not gate.passed
        ]
        assert result.reconciliation_handle
        assert result.confirmation_phrase == reconciliation.RECONCILIATION_PHRASE
        assert result.expected_wordpress_write_count == 0
        assert result.expected_plugin_write_count == 0
        assert result.expected_cache_write_count == 0
        assert result.expected_atlas_write_count == 1
        assert session.get(WordPressPluginUpgradeAudit, 3).model_dump() == before
        assert current["wordpress_request_methods"] == ["GET"]


def test_reconciliation_accepts_real_evidence_backed_rendered_state(monkeypatch, db):
    signed = evidence("orlando-real-acquire-rendered-state")

    def public_response(request_value):
        return httpx.Response(
            200,
            request=request_value,
            headers={
                "content-type": "text/html; charset=UTF-8",
                "server": "nginx",
                "x-cache-enabled": "True",
                "x-proxy-cache": "HIT",
                "x-content-type-options": "nosniff",
            },
            text=HTML,
        )

    with httpx.Client(transport=httpx.MockTransport(public_response)) as client:
        rendered = reconciliation.acquire_rendered_state(
            "unused",
            "unused",
            manual_evidence=signed,
            evidence_signing_key=KEY,
            client=client,
        )
    assert rendered["source"] == "manual_browser_evidence"
    assert rendered["signature_validated"] is True
    current = observation(upgrade.TARGET_VERSION)
    current["rendered"] = rendered
    current["cache_headers"] = deepcopy(rendered["cache_headers"])
    configure(monkeypatch, current)

    with Session(db) as session:
        seed_reconciliation(session)
        audit = session.get(WordPressPluginUpgradeAudit, 3)
        pre_snapshot = deepcopy(audit.pre_snapshot)
        post_snapshot = deepcopy(audit.post_snapshot)
        for field in (
            "document_title",
            "h1",
            "canonical",
            "featured_image_url",
            "featured_image_alt",
            "metadata_inventory",
            "atlas_metadata_marker_present",
            "media32_reference_present",
            "admin_page_detected",
            "login_page_detected",
            "authenticated_context_detected",
            "challenge_page_detected",
            "error_page_detected",
            "admin_detection_signals",
            "head_hash",
            "visible_hash",
        ):
            pre_snapshot["rendered"][field] = deepcopy(rendered.get(field))
            post_snapshot["rendered"][field] = deepcopy(rendered.get(field))
        for field in ("content_type", "body_sha256"):
            pre_snapshot["rendered"]["public_http_observation"][field] = deepcopy(
                rendered["public_http_observation"].get(field)
            )
        audit.pre_snapshot = pre_snapshot
        audit.post_snapshot = post_snapshot
        audit.browser_evidence_hashes = {
            **audit.browser_evidence_hashes,
            "rendered_head": rendered["head_hash"],
            "visible_content": rendered["visible_hash"],
        }
        session.add(audit)
        session.commit()
        preflight = reconciliation.reconciliation_preflight(
            session,
            41,
            request(manual_browser_evidence=signed),
        )
        assert preflight.reconciliation_ready is True, [
            (gate.code, gate.message)
            for gate in preflight.gate_results
            if not gate.passed
        ]
        assert (
            preflight.inspected_state["cache_boundary_comparison"][
                "current_public_observation_count"
            ]
            == 3
        )


@pytest.mark.parametrize(
    "current_value",
    [None, "NO-SNIFF", "nosniff, nosniff", "nosniff, deny", ""],
)
def test_reconciliation_rejects_noncanonical_current_nosniff(
    monkeypatch, db, current_value
):
    current = configure(monkeypatch)
    locations = (
        current["cache_headers"],
        current["rendered"]["cache_headers"],
        current["rendered"]["public_http_observation"]["cache_headers"],
        current["rendered"]["public_http_observation"]["provider_signals"],
    )
    for location in locations:
        if current_value is None:
            location.pop("x-content-type-options", None)
        else:
            location["x-content-type-options"] = current_value
    monkeypatch.setattr(
        reconciliation,
        "_observe",
        lambda session, request_value: deepcopy(current),
    )
    with Session(db) as session:
        seed_reconciliation(session)
        result = reconciliation.reconciliation_preflight(session, 41, request())
        assert not result.reconciliation_ready
        assert "cache_boundary" in failed_codes(result)
        assert (
            result.inspected_state["cache_boundary_comparison"]["reason_code"]
            == "current_x_content_type_options_not_exact_nosniff"
        )
        assert not reconciliation._handles


def test_reconciliation_rejects_wrong_historical_release_identity(monkeypatch, db):
    configure(monkeypatch)
    with Session(db) as session:
        seed_reconciliation(session)
        audit = session.get(WordPressPluginUpgradeAudit, 3)
        audit.release_identity = {
            **audit.release_identity,
            "atlas_version": "v0.59.96",
            "atlas_tag": "v0.59.96",
        }
        session.add(audit)
        session.commit()
        result = reconciliation.reconciliation_preflight(session, 41, request())
        assert not result.reconciliation_ready
        assert (
            result.inspected_state["cache_boundary_comparison"]["reason_code"]
            == "historical_capture_identity_mismatch"
        )


def test_historical_header_exception_is_rejected_for_another_audit(monkeypatch, db):
    current = configure(monkeypatch)
    with Session(db) as session:
        seed_reconciliation(session)
        audit_data = session.get(WordPressPluginUpgradeAudit, 3).model_dump()
        audit_data["id"] = 4
        audit = WordPressPluginUpgradeAudit(**audit_data)
        repeated = deepcopy(current["rendered"])
        repeated["source"] = "public"
        result = reconciliation._compare_reconciliation_cache_boundary(
            audit,
            current,
            [deepcopy(repeated), deepcopy(repeated)],
        )
        assert result == {
            "compatible": False,
            "reason_code": "historical_capture_identity_mismatch",
            "current_public_observation_count": 0,
        }


def test_reconciliation_rejects_historical_header_that_was_collected(monkeypatch, db):
    configure(monkeypatch)
    with Session(db) as session:
        seed_reconciliation(session)
        audit = session.get(WordPressPluginUpgradeAudit, 3)
        pre_snapshot = deepcopy(audit.pre_snapshot)
        pre_snapshot["cache_headers"]["x-content-type-options"] = "nosniff"
        audit.pre_snapshot = pre_snapshot
        session.add(audit)
        session.commit()
        result = reconciliation.reconciliation_preflight(session, 41, request())
        assert not result.reconciliation_ready
        assert (
            result.inspected_state["cache_boundary_comparison"]["reason_code"]
            == "historical_header_not_proven_uncollected"
        )


def test_reconciliation_rejects_other_security_header_drift(monkeypatch, db):
    current = configure(monkeypatch)
    for location in (
        current["cache_headers"],
        current["rendered"]["cache_headers"],
        current["rendered"]["public_http_observation"]["cache_headers"],
        current["rendered"]["public_http_observation"]["provider_signals"],
    ):
        location["x-frame-options"] = "DENY"
    monkeypatch.setattr(
        reconciliation,
        "_observe",
        lambda session, request_value: deepcopy(current),
    )
    repeated = deepcopy(current["rendered"])
    repeated["source"] = "public"
    monkeypatch.setattr(
        reconciliation,
        "_acquire_repeated_public_observations",
        lambda: [deepcopy(repeated), deepcopy(repeated)],
    )
    with Session(db) as session:
        seed_reconciliation(session)
        audit = session.get(WordPressPluginUpgradeAudit, 3)
        for location in (
            audit.pre_snapshot["cache_headers"],
            audit.pre_snapshot["rendered"]["cache_headers"],
        ):
            location["x-frame-options"] = "SAMEORIGIN"
        session.add(audit)
        session.commit()
        result = reconciliation.reconciliation_preflight(session, 41, request())
        assert not result.reconciliation_ready
        assert (
            result.inspected_state["cache_boundary_comparison"]["reason_code"]
            == "durable_header_changed:x-frame-options"
        )


def test_reconciliation_rejects_unstable_repeated_public_observation(monkeypatch, db):
    current = configure(monkeypatch)
    stable = deepcopy(current["rendered"])
    stable["source"] = "public"
    drifted = deepcopy(stable)
    drifted["visible_hash"] = "f" * 64
    monkeypatch.setattr(
        reconciliation,
        "_acquire_repeated_public_observations",
        lambda: [deepcopy(stable), deepcopy(drifted)],
    )
    with Session(db) as session:
        seed_reconciliation(session)
        result = reconciliation.reconciliation_preflight(session, 41, request())
        assert not result.reconciliation_ready
        assert (
            result.inspected_state["cache_boundary_comparison"]["reason_code"]
            == "repeated_public_page_identity_drift"
        )


def test_general_upgrade_comparator_still_rejects_absent_to_present_header():
    before = observation()
    after = deepcopy(before)
    after["cache_headers"]["x-content-type-options"] = "nosniff"
    after["rendered"]["cache_headers"] = deepcopy(after["cache_headers"])
    result = upgrade.compare_upgrade_cache_boundary(before, after)
    assert result == {
        "compatible": False,
        "reason_code": "durable_header_changed:x-content-type-options",
    }


def test_reconciliation_accepts_legacy_null_transport_projection(monkeypatch, db):
    configure(monkeypatch)
    with Session(db) as session:
        seed_reconciliation(session)
        audit = session.get(WordPressPluginUpgradeAudit, 3)
        audit.pre_snapshot["rendered"]["status_code"] = None
        audit.pre_snapshot["rendered"]["redirect_count"] = None
        session.add(audit)
        session.commit()

        preflight = reconciliation.reconciliation_preflight(session, 41, request())
        assert preflight.reconciliation_ready is True, [
            (gate.code, gate.message)
            for gate in preflight.gate_results
            if not gate.passed
        ]
        result = reconciliation.apply_reconciliation(
            session,
            41,
            WordPressPluginUpgradeReconciliationApplyRequest(
                reconciliation_handle=preflight.reconciliation_handle,
                confirmation_phrase=reconciliation.RECONCILIATION_PHRASE,
            ),
        )

        assert result.status == "verified"
        assert result.wordpress_write_count == 0
        assert result.plugin_write_count == 0
        assert result.cache_write_count == 0
        assert result.request_atlas_write_count == 1


def test_reconciliation_apply_is_one_atomic_atlas_update_and_preserves_history(monkeypatch, db):
    configure(monkeypatch)
    with Session(db) as session:
        seed_reconciliation(session)
        audit_one_before = session.get(WordPressBootstrapEstablishmentAudit, 1).model_dump()
        audit_two_before = session.get(WordPressBootstrapEstablishmentAudit, 2).model_dump()
        audit_before = session.get(WordPressPluginUpgradeAudit, 3)
        post_before = deepcopy(audit_before.post_snapshot)
        gates_before = deepcopy(audit_before.gate_results)
        findings_before = deepcopy(audit_before.verification_findings)
        preflight = reconciliation.reconciliation_preflight(session, 41, request())
        assert preflight.reconciliation_ready, [
            (gate.code, gate.message) for gate in preflight.gate_results if not gate.passed
        ]
        result = reconciliation.apply_reconciliation(
            session,
            41,
            WordPressPluginUpgradeReconciliationApplyRequest(
                reconciliation_handle=preflight.reconciliation_handle,
                confirmation_phrase=reconciliation.RECONCILIATION_PHRASE,
            ),
        )
        audit = session.get(WordPressPluginUpgradeAudit, 3)
        assert result.status == audit.status == "verified"
        assert audit.transition_history == [
            "pending",
            "verification_failed",
            reconciliation.RECONCILIATION_REASON,
        ]
        assert audit.atlas_write_count == 3
        assert audit.wordpress_write_count == 1
        assert audit.post_snapshot == post_before
        assert audit.gate_results == gates_before
        assert audit.verification_findings == findings_before
        assert audit.reconciliation_snapshot["original_history"] == [
            "pending",
            "verification_failed",
        ]
        assert result.wordpress_write_count == result.plugin_write_count == result.cache_write_count == 0
        assert result.request_atlas_write_count == 1
        assert session.get(WordPressBootstrapEstablishmentAudit, 1).model_dump() == audit_one_before
        assert session.get(WordPressBootstrapEstablishmentAudit, 2).model_dump() == audit_two_before
        assert len(session.exec(select(WordPressPluginUpgradeAudit)).all()) == 3
        assert not reconciliation._handles


def test_reconciliation_phrase_replay_altered_cross_operation_and_restart_fail_closed(monkeypatch, db):
    configure(monkeypatch)
    with Session(db) as session:
        seed_reconciliation(session)
        preflight = reconciliation.reconciliation_preflight(session, 41, request())
        with pytest.raises(HTTPException, match="phrase"):
            reconciliation.apply_reconciliation(
                session,
                41,
                WordPressPluginUpgradeReconciliationApplyRequest(
                    reconciliation_handle=preflight.reconciliation_handle,
                    confirmation_phrase="WRONG",
                ),
            )
        assert preflight.reconciliation_handle in reconciliation._handles
        with pytest.raises(HTTPException, match="unknown"):
            reconciliation.apply_reconciliation(
                session,
                41,
                WordPressPluginUpgradeReconciliationApplyRequest(
                    reconciliation_handle=preflight.reconciliation_handle + "altered",
                    confirmation_phrase=reconciliation.RECONCILIATION_PHRASE,
                ),
            )
        entry = reconciliation._handles[preflight.reconciliation_handle]
        reconciliation._handles[preflight.reconciliation_handle] = replace(entry, audit_id=4)
        with pytest.raises(HTTPException, match="another audit"):
            reconciliation.apply_reconciliation(
                session,
                41,
                WordPressPluginUpgradeReconciliationApplyRequest(
                    reconciliation_handle=preflight.reconciliation_handle,
                    confirmation_phrase=reconciliation.RECONCILIATION_PHRASE,
                ),
            )
        replacement = reconciliation.reconciliation_preflight(session, 41, request())
        reconciliation._clear_reconciliation_handles()
        with pytest.raises(HTTPException, match="restart-invalidated"):
            reconciliation.apply_reconciliation(
                session,
                41,
                WordPressPluginUpgradeReconciliationApplyRequest(
                    reconciliation_handle=replacement.reconciliation_handle,
                    confirmation_phrase=reconciliation.RECONCILIATION_PHRASE,
                ),
            )
        assert session.get(WordPressPluginUpgradeAudit, 3).status == "verification_failed"


def test_reconciliation_expired_handle_and_stale_evidence_fail(monkeypatch, db):
    configure(monkeypatch)
    with Session(db) as session:
        seed_reconciliation(session)
        stale = reconciliation.reconciliation_preflight(
            session,
            41,
            request(
                manual_browser_evidence=evidence(
                    "stale-evidence",
                    datetime.now(UTC) - timedelta(minutes=20),
                )
            ),
        )
        assert not stale.reconciliation_ready
        assert "fresh_evidence" in failed_codes(stale)

        live = reconciliation.reconciliation_preflight(session, 41, request())
        reconciliation._handles[live.reconciliation_handle] = replace(
            reconciliation._handles[live.reconciliation_handle],
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        with pytest.raises(HTTPException, match="expired"):
            reconciliation.apply_reconciliation(
                session,
                41,
                WordPressPluginUpgradeReconciliationApplyRequest(
                    reconciliation_handle=live.reconciliation_handle,
                    confirmation_phrase=reconciliation.RECONCILIATION_PHRASE,
                ),
            )


@pytest.mark.parametrize(
    ("case", "gate"),
    [
        ("wrong_audit", "audit_identity"),
        ("wrong_version", "metadata_bridge"),
        ("wrong_checksum", "metadata_bridge"),
        ("plugin_inventory", "plugin_inventories"),
        ("payload", "metadata_state"),
        ("page", "page_body_media_settings"),
        ("media", "page_body_media_settings"),
        ("rendered_head", "rendered_identity"),
        ("privacy", "cache_boundary"),
        ("provider", "cache_boundary"),
        ("redirect", "rendered_identity"),
        ("purge", "purge_count"),
        ("pending", "pending_operations"),
        ("runtime", "runtime_identity"),
        ("backup", "atlas_data_backup"),
    ],
)
def test_reconciliation_durable_drift_blocks_without_write(monkeypatch, db, case, gate):
    current = observation(upgrade.TARGET_VERSION)
    current["rendered"]["browser_evidence_identifier"] = "orlando-fresh-upgrade-reconciliation"
    current["rendered"]["evidence_schema_version"] = 1
    if case == "wrong_version":
        current["plugins"][0]["version"] = "0.57.6"
    elif case == "plugin_inventory":
        current["plugins"].append({"plugin": "unexpected/plugin", "version": "1", "status": "inactive"})
        current["plugin_inventory_hash"] = upgrade._hash(current["plugins"])
    elif case == "page":
        current["page_snapshot_hash"] = "f" * 64
    elif case == "media":
        current["media31_snapshot_hash"] = "f" * 64
    elif case == "rendered_head":
        current["rendered"]["head_hash"] = "f" * 64
    elif case == "privacy":
        current["rendered"]["public_http_observation"]["privacy_classification"] = "authenticated_transport"
    elif case == "provider":
        current["rendered"]["public_http_observation"]["provider_family"] = "other"
    elif case == "redirect":
        current["rendered"]["redirect_count"] = 1
        current["rendered"]["public_http_observation"]["redirect_count"] = 1
    elif case == "purge":
        current["cache_purge_count"] = 1
    configure(monkeypatch, current)
    if case == "wrong_checksum":
        monkeypatch.setattr(
            reconciliation.upgrade,
            "_read_plugin_status",
            lambda session: {**status(upgrade.TARGET_VERSION), "checksum": "f" * 64},
        )
    if case == "pending":
        monkeypatch.setattr(reconciliation, "_pending_operation_exists", lambda session: True)
    if case == "runtime":
        monkeypatch.setattr(
            reconciliation,
            "deployment_readiness",
            lambda: {"release_status": "blocked", "release": {}},
        )
    if case == "backup":
        monkeypatch.setattr(
            reconciliation,
            "_backup",
            lambda request, release, audit: (
                {},
                [upgrade._gate("atlas_data_backup", "fresh backup", False, "missing")],
            ),
        )
    with Session(db) as session:
        seed_reconciliation(session)
        audit = session.get(WordPressPluginUpgradeAudit, 3)
        if case == "wrong_audit":
            audit.generated_page_id = 40
        elif case == "payload":
            state_row = session.exec(select(reconciliation.WordPressMetadataState)).one()
            state_row.payload_hash = "f" * 64
            session.add(state_row)
        session.add(audit)
        session.commit()
        session.refresh(audit)
        before = audit.model_dump()
        result = reconciliation.reconciliation_preflight(session, 41, request())
        assert not result.reconciliation_ready
        assert gate in failed_codes(result)
        assert session.get(WordPressPluginUpgradeAudit, 3).model_dump() == before
        assert result.expected_wordpress_write_count == 0


def test_reconciliation_apply_gate_drift_consumes_handle_and_leaves_no_pending_state(monkeypatch, db):
    current = configure(monkeypatch)
    with Session(db) as session:
        seed_reconciliation(session)
        preflight = reconciliation.reconciliation_preflight(session, 41, request())
        current["page_body_hash"] = "f" * 64
        monkeypatch.setattr(reconciliation, "_observe", lambda session, request: deepcopy(current))
        with pytest.raises(HTTPException, match="gate changed"):
            reconciliation.apply_reconciliation(
                session,
                41,
                WordPressPluginUpgradeReconciliationApplyRequest(
                    reconciliation_handle=preflight.reconciliation_handle,
                    confirmation_phrase=reconciliation.RECONCILIATION_PHRASE,
                ),
            )
        assert not reconciliation._handles
        audit = session.get(WordPressPluginUpgradeAudit, 3)
        assert audit.status == "verification_failed"
        assert audit.atlas_write_count == 2


def test_reconciliation_cross_release_handle_replay_fails_closed(monkeypatch, db):
    configure(monkeypatch)
    with Session(db) as session:
        seed_reconciliation(session)
        preflight = reconciliation.reconciliation_preflight(
            session, 41, request()
        )
        assert preflight.reconciliation_ready
        monkeypatch.setattr(
            reconciliation,
            "deployment_readiness",
            lambda: {
                "release_status": "verified",
                "release": {
                    "atlas_version": "v0.59.99",
                    "atlas_commit": "f" * 40,
                    "atlas_tag": "v0.59.99",
                    "manifest_sha256": "e" * 64,
                    "source_compatibility_id": (
                        "project-atlas-release-identity-v0.59.96"
                    ),
                    "runtime_identity_verified": True,
                    "manifest_integrity_verified": True,
                    "expected_release_matched": True,
                    "generated_at": datetime.now(UTC).isoformat(),
                },
            },
        )
        with pytest.raises(HTTPException, match="gate changed"):
            reconciliation.apply_reconciliation(
                session,
                41,
                WordPressPluginUpgradeReconciliationApplyRequest(
                    reconciliation_handle=preflight.reconciliation_handle,
                    confirmation_phrase=reconciliation.RECONCILIATION_PHRASE,
                ),
            )
        assert not reconciliation._handles
        audit = session.get(WordPressPluginUpgradeAudit, 3)
        assert audit.status == "verification_failed"
        assert audit.atlas_write_count == 2
