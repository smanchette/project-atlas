from datetime import UTC, datetime, timedelta
import inspect
import json

import pytest
from pydantic import ValidationError
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.services import wordpress_metadata as metadata
from app.services.wordpress_deployment_release import SOURCE_EXPECTATIONS, resolve_program_root


PLUGIN = resolve_program_root() / "wordpress" / SOURCE_EXPECTATIONS.plugin_entry_path


def test_metadata_routes_are_fixed_one_page_actions_without_bulk_routes() -> None:
    with TestClient(app) as client:
        response = client.post("/api/wordpress/metadata/dry-run/42")
    assert response.status_code == 404
    routes = {(route.path, method) for route in app.routes for method in (getattr(route, "methods", None) or set())}
    expected = {
        ("/api/wordpress/metadata/dry-run/{page_id}", "POST"),
        ("/api/wordpress/metadata/apply/{page_id}", "POST"),
        ("/api/wordpress/metadata/verify/{page_id}", "POST"),
        ("/api/wordpress/metadata/rollback/dry-run/{page_id}", "POST"),
        ("/api/wordpress/metadata/rollback/apply/{page_id}", "POST"),
    }
    assert expected <= routes
    assert not any("bulk" in path or "delete" in path for path, _ in routes if "/wordpress/metadata/" in path)


def test_locked_payload_has_exact_identity_and_six_node_graph() -> None:
    payload = metadata.build_orlando_metadata_payload().model_dump(mode="json")
    assert payload["meta_description"] == metadata.META_DESCRIPTION
    assert len(payload["meta_description"]) == 140
    graph = payload["json_ld"]["@graph"]
    assert [node["@type"] for node in graph] == ["WebSite", "Organization", "Person", "ImageObject", "Service", "WebPage"]
    organization = graph[1]
    assert organization["name"] == "Flo-Zone Pest And Termite Solutions Inc"
    assert organization["telephone"] == "(844) 600-8368"
    assert organization["email"] == "Office@Flo-ZoneTenting.com"
    assert organization["identifier"]["value"] == "JB360566"


def test_person_node_is_deliberately_limited() -> None:
    person = metadata.build_orlando_metadata_payload().json_ld["@graph"][2]
    assert person == {"@type": "Person", "@id": "https://www.drywoodtenting.com/#jordan-ward", "name": "Jordan Ward", "jobTitle": "Certified Operator", "worksFor": {"@id": "https://www.drywoodtenting.com/#organization"}}
    assert "license" not in json.dumps(person).lower()


def test_website_reference_resolves_and_organization_type_is_not_local_business() -> None:
    graph = metadata.build_orlando_metadata_payload().json_ld["@graph"]
    ids = {node.get("@id") for node in graph}
    assert "https://www.drywoodtenting.com/#website" in ids
    assert graph[-1]["isPartOf"]["@id"] in ids
    assert graph[1]["@type"] == "Organization"


def test_media_31_is_canonical_everywhere_and_media_32_is_excluded() -> None:
    payload = metadata.build_orlando_metadata_payload().model_dump(mode="json")
    encoded = json.dumps(payload)
    assert payload["media_id"] == 31 and payload["excluded_media_ids"] == [32]
    assert payload["open_graph"]["og:image"] == metadata.EXPECTED_MEDIA_URL
    assert payload["twitter"]["twitter:image"] == metadata.EXPECTED_MEDIA_URL
    assert metadata.EXPECTED_MEDIA_URL in encoded
    assert "orlando-drywood-termite-tenting-hero-1.png" not in encoded


def test_metadata_token_is_target_bound_tamper_evident_and_expires() -> None:
    token = metadata._sign("apply_metadata", "abc", datetime.now(UTC) + timedelta(minutes=1))
    assert metadata._verify(token, "apply_metadata", 41)["payload_hash"] == "abc"
    with pytest.raises(HTTPException): metadata._verify(token, "apply_metadata", 42)
    with pytest.raises(HTTPException): metadata._verify(token, "rollback_metadata", 41)
    with pytest.raises(HTTPException): metadata._verify(token[:-1] + ("0" if token[-1] != "0" else "1"), "apply_metadata", 41)
    expired = metadata._sign("apply_metadata", "abc", datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(HTTPException): metadata._verify(expired, "apply_metadata", 41)


def test_plugin_activation_writes_only_disabled_safety_state() -> None:
    source = PLUGIN.read_text(encoding="utf-8")
    assert "register_activation_hook(__FILE__, 'atlas_metadata_activate')" in source
    activation = source.split("function atlas_metadata_activate", 1)[1].split("register_activation_hook", 1)[0]
    assert activation.count("update_option") == 1
    assert "ATLAS_METADATA_SAFETY_OPTION" in activation
    assert "'enabled' => false" in activation
    assert "wp_generate_uuid4()" in activation
    assert "update_post_meta" not in activation and "delete_post_meta" not in activation
    assert "_atlas_metadata_enabled', '1'" in source  # apply only


def test_plugin_never_updates_core_post_or_media_fields() -> None:
    source = PLUGIN.read_text(encoding="utf-8")
    assert "wp_update_post" not in source
    assert "set_post_thumbnail" not in source
    assert "wp_delete_attachment" not in source
    assert "update_option(ATLAS_METADATA_SAFETY_OPTION" in source
    assert "update_option('" not in source
    assert "wp sg purge" not in source.lower()
    for forbidden in ("'post_title' =>", "'post_content' =>", "'post_excerpt' =>", "'post_status' =>"):
        assert forbidden not in source


def test_plugin_outputs_no_title_or_canonical_and_rejects_duplicate_image() -> None:
    source = PLUGIN.read_text(encoding="utf-8")
    render = source.split("add_action('wp_head'", 1)[1]
    assert "<title" not in render.lower()
    assert "canonical" not in render.lower()
    assert "orlando-drywood-termite-tenting-hero-1.png" in source
    assert "Excluded media 32 appears" in source


def test_verify_schema_cannot_create_confirmation_material() -> None:
    fields = metadata.WordPressMetadataVerification.model_fields
    assert fields["confirmation_token"].default is None
    assert fields["confirmation_phrase"].default is None
    source = inspect.getsource(metadata.verify_wordpress_metadata)
    assert "_sign(" not in source
    assert "session.add" not in source and "session.commit" not in source


def test_context_token_binds_every_context_field() -> None:
    context = {"revision": "7", "snapshot_hash": "a", "backup": {"media": "m"}}
    token = metadata._sign_context("apply_metadata", context, datetime.now(UTC) + timedelta(minutes=1))
    body = metadata._verify(token, "apply_metadata", 41)
    assert body["bound_state_hash"] == metadata._hash(context)
    changed = {**context, "revision": "8"}
    assert body["bound_state_hash"] != metadata._hash(changed)


def test_backup_timestamp_requires_parseable_datetime() -> None:
    from app.schemas.wordpress import WordPressMetadataBackupProof
    with pytest.raises(ValidationError):
        WordPressMetadataBackupProof.model_validate({
            "confirmed_data_backup_file": "backup.json", "confirmed_media_backup_identity": "media-1",
            "confirmed_program_backup_identity": "program-1", "wordpress_backup_reference": "wp-1",
            "wordpress_backup_timestamp": "not-a-date", "wordpress_backup_database_included": True,
            "wordpress_backup_plugin_files_included": True, "wordpress_restore_capability_confirmed": True,
        })


def test_rendered_html_duplicate_detection_and_complete_graph() -> None:
    payload = metadata.build_orlando_metadata_payload().model_dump(mode="json")
    metas = [f'<meta name="description" content="{payload["meta_description"]}">']
    metas += [f'<meta property="{k}" content="{v}">' for k, v in payload["open_graph"].items()]
    metas += [f'<meta name="{k}" content="{v}">' for k, v in payload["twitter"].items()]
    script = f'<script type="application/ld+json" data-project-atlas="metadata">{json.dumps(payload["json_ld"])}</script>'
    html = f'<html><head><title>T</title><link rel="canonical" href="{metadata.EXPECTED_URL}">{"".join(metas)}{script}</head><body><h1>H</h1><p>{metadata.EXPECTED_MEDIA_URL}</p></body></html>'
    post = {"title": {"rendered": "T"}, "excerpt": {"rendered": ""}, "content": {"rendered": "<h1>H</h1>"}, "slug": metadata.EXPECTED_SLUG, "status": "publish", "link": metadata.EXPECTED_URL, "featured_media": 31}
    assert all(g.passed for g in metadata._render_gates(metadata._parse_html(html), post, payload))
    duplicate = html.replace(metas[0], metas[0] + metas[0])
    gates = {g.code: g for g in metadata._render_gates(metadata._parse_html(duplicate), post, payload)}
    assert not gates["metadata_tags"].passed


def test_reconciliation_apply_has_no_wordpress_send_call() -> None:
    source = inspect.getsource(metadata.reconcile_wordpress_metadata)
    assert "_send_json" not in source and "_get_json" not in source and "_get_html" not in source


def test_reconciliation_apply_finalizes_atlas_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.schemas.wordpress import (
        WordPressMetadataReconciliationDryRun, WordPressMetadataReconciliationRequest,
        WordPressMetadataVerification,
    )
    proof = {
        "confirmed_data_backup_file": "atlas-backup.json",
        "confirmed_media_backup_identity": "atlas-media-backup-2026-07-12-120000.zip",
        "confirmed_program_backup_identity": "atlas-program-backup-2026-07-12-120000.zip",
        "wordpress_backup_reference": "durable-local-reference",
        "wordpress_backup_timestamp": datetime.now(UTC),
        "wordpress_backup_database_included": True,
        "wordpress_backup_plugin_files_included": True,
        "wordpress_restore_capability_confirmed": True,
    }
    verification = WordPressMetadataVerification(page_id=41, wordpress_post_id=8, status="verified", apply_needed=False,
        metadata_correct=True, payload_hash="approved", live_payload_hash="approved", rendered={"snapshot": {"revision": "1"}}, gate_results=[])
    request = WordPressMetadataReconciliationRequest(**proof, confirmation_token="pending", confirmation_phrase=metadata.RECONCILE_PHRASE)
    context = {"audit_id": 7, "audit_payload_hash": "approved", "verification_hash": metadata._hash(verification.model_dump(mode="json")), "backup": metadata._proof_dict(request)}
    token = metadata._sign_context("reconcile_metadata", context, datetime.now(UTC) + timedelta(minutes=1)); request.confirmation_token = token
    dry = WordPressMetadataReconciliationDryRun(page_id=41, wordpress_post_id=8, status="safe_to_finalize", safe_to_finalize=True,
        original_audit_id=7, verification=verification, gate_results=[], confirmation_token=token, confirmation_phrase=metadata.RECONCILE_PHRASE)
    audit = type("Audit", (), {"id": 7})()
    session = type("Session", (), {"get": lambda self, model, key: audit})()
    finalized: list[int] = []
    monkeypatch.setattr(metadata, "dry_run_wordpress_metadata_reconciliation", lambda *args: dry)
    monkeypatch.setattr(metadata, "_finalize_apply", lambda session, audit, *args: finalized.append(audit.id))
    monkeypatch.setattr(metadata, "_send_json", lambda *args, **kwargs: pytest.fail("Reconciliation retried WordPress"))
    result = metadata.reconcile_wordpress_metadata(session, 41, request)
    assert result.wordpress_write_performed is False and finalized == [7]
