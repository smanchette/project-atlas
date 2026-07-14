from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import zipfile

import httpx
import pytest

from app.schemas.wordpress import WordPressDeploymentBackupEvidence
from app.services import wordpress_deployment as deployment
from app.services import wordpress_deployment_release as release
from app.services.wordpress_rendered_state import (
    EXPECTED_MEDIA_URL,
    EXPECTED_URL,
    acquire_rendered_state,
    build_manual_browser_evidence,
    validate_manual_browser_evidence,
)
from app.services.wordpress_rendered_state import _html_result


HTML = f"""<!doctype html><html><head><title>Drywood Termite Tenting in Orlando, FL</title><link rel="canonical" href="{EXPECTED_URL}"></head><body><h1>Drywood Termite Tenting in Orlando, FL</h1><img src="{EXPECTED_MEDIA_URL}"><p>Orlando service content.</p></body></html>"""


def atlas_layout(root: Path, *, artifact: bool = True, source: bool = True) -> Path:
    (root / "backend" / "app").mkdir(parents=True)
    (root / "wordpress" / "dist").mkdir(parents=True)
    if source:
        directory = root / release.SOURCE_EXPECTATIONS.source_relative_path
        directory.mkdir(parents=True)
        (directory / "project-atlas-metadata-bridge.php").write_text("plugin", encoding="utf-8")
    if artifact:
        (root / release.SOURCE_EXPECTATIONS.artifact_relative_path).write_bytes(b"zip")
    return root


def test_program_root_explicit_container_windows_and_host_fallback(tmp_path):
    container = atlas_layout(tmp_path / "atlas-program")
    assert release.resolve_program_root({}, container_root=container) == container.resolve()
    assert release.resolve_program_root({"ATLAS_PROGRAM_ROOT": str(container)}, container_root=tmp_path / "none") == container.resolve()
    fake_module = container / "backend/app/services/release.py"
    fake_module.parent.mkdir(parents=True, exist_ok=True)
    assert release.resolve_program_root({}, module_file=fake_module, container_root=tmp_path / "none") == container.resolve()


@pytest.mark.skipif(os.name != "nt", reason="Windows path semantics require a Windows host")
def test_windows_repository_root_override_resolves_with_native_path_semantics(tmp_path):
    root = atlas_layout(tmp_path / "Atlas Repository")
    assert release.resolve_program_root({"ATLAS_PROGRAM_ROOT": str(root)}) == root.resolve()


@pytest.mark.parametrize("configured", ["/", ".", "../outside"])
def test_program_root_rejects_root_relative_and_traversal(configured):
    with pytest.raises(release.DeploymentReleaseError):
        release.resolve_program_root({"ATLAS_PROGRAM_ROOT": configured}, container_root="/__missing__")


def test_program_root_rejects_outside_layout_and_reports_missing_parts(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(release.DeploymentReleaseError):
        release.resolve_program_root({"ATLAS_PROGRAM_ROOT": str(outside)})
    root = atlas_layout(tmp_path / "project", artifact=False, source=False)
    diagnostics = release.readiness_diagnostics({"ATLAS_PROGRAM_ROOT": str(root)})
    assert diagnostics["artifact_exists"] is False and diagnostics["source_directory_exists"] is False
    with pytest.raises(release.DeploymentReleaseError, match="artifact is missing"):
        release.artifact_sha256(root / release.SOURCE_EXPECTATIONS.artifact_relative_path)
    with pytest.raises(release.DeploymentReleaseError):
        release._contained(root.resolve(), "../outside.zip")


def test_locked_artifact_hash_and_source_zip_are_exact():
    root = release.resolve_program_root()
    archive_path, source = release.release_paths(root)
    assert release.artifact_sha256(archive_path) == release.SOURCE_EXPECTATIONS.plugin_zip_sha256
    assert release.artifact_sha256(archive_path) != "0" * 64
    with zipfile.ZipFile(archive_path) as archive:
        actual = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    expected = {f"{release.SOURCE_EXPECTATIONS.plugin_slug}/{path.relative_to(source).as_posix()}": path.read_bytes() for path in source.rglob("*") if path.is_file()}
    assert actual == expected


def manifest_values(**overrides):
    values = {
        "manifest_schema_version": 2,
        "source_compatibility_id": release.SOURCE_EXPECTATIONS.source_compatibility_id,
        "atlas_version": "v0.59.8",
        "atlas_commit": "c" * 40,
        "atlas_tag": "v0.59.8",
        "plugin_version": "0.57.4",
        "plugin_zip_filename": "project-atlas-metadata-bridge-0.57.4.zip",
        "plugin_zip_sha256": release.SOURCE_EXPECTATIONS.plugin_zip_sha256,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    values.update(overrides)
    return values


def write_manifest(root: Path, *, expected_overrides=None, **overrides):
    path = root / ".runtime/atlas-release.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = release.canonical_manifest_bytes(manifest_values(**overrides))
    path.write_bytes(payload)
    expected = {
        "ATLAS_EXPECTED_RELEASE_VERSION": "v0.59.8",
        "ATLAS_EXPECTED_RELEASE_COMMIT": "c" * 40,
        "ATLAS_EXPECTED_RELEASE_TAG": "v0.59.8",
    }
    expected.update(expected_overrides or {})
    return {"ATLAS_RELEASE_MANIFEST_PATH": str(path.resolve()), "ATLAS_RELEASE_MANIFEST_SHA256": hashlib.sha256(payload).hexdigest(), **expected}


def add_fake_git(root: Path, *, head="c" * 40, tag="c" * 40):
    git = root / ".git"
    (git / "refs/heads").mkdir(parents=True)
    (git / "refs/tags").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    (git / "refs/heads/main").write_text(head + "\n", encoding="ascii")
    (git / "refs/tags/v0.59.8").write_text(tag + "\n", encoding="ascii")


def test_missing_and_unverified_environment_identity_block(monkeypatch):
    monkeypatch.delenv("ATLAS_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("ATLAS_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.delenv("ATLAS_EXPECTED_RELEASE_VERSION", raising=False)
    monkeypatch.delenv("ATLAS_EXPECTED_RELEASE_COMMIT", raising=False)
    monkeypatch.delenv("ATLAS_EXPECTED_RELEASE_TAG", raising=False)
    artifact, gates = deployment._verify_artifact()
    assert artifact["release_identity_status"] == "release_identity_unavailable"
    assert artifact["atlas_commit"] is None
    assert not {gate.code: gate for gate in gates}["release_identity"].passed


def test_missing_release_identity_performs_no_wordpress_observation_and_issues_no_token(monkeypatch):
    monkeypatch.delenv("ATLAS_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("ATLAS_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.setattr(deployment, "_observe", lambda *_: (_ for _ in ()).throw(AssertionError("WordPress observation must not run")))
    monkeypatch.setattr(deployment, "_backup_gates", lambda *_: [])
    monkeypatch.setattr(deployment, "_state_gates", lambda *_: [])
    proof = WordPressDeploymentBackupEvidence(
        atlas_data_backup_file="atlas-backup-2026-07-13-000000.json",
        atlas_media_backup_file="atlas-media-backup-2026-07-13-000000.zip",
        atlas_program_backup_file="atlas-program-backup-2026-07-13-000000.zip",
        wordpress_backup_method="SiteGround on-demand full-site backup",
        wordpress_backup_reference="local-test-backup",
        wordpress_backup_completed_at=datetime.now(UTC) - timedelta(minutes=1),
        wordpress_database_included_attestation=True,
        wordpress_plugins_included_attestation=True,
        wordpress_restore_capability_attestation=True,
        confirmer_identity="Local test",
        php_error_log_findings="No findings",
        observed_write_summary="No WordPress write performed",
    )
    result = deployment.install_dry_run(object(), 41, proof)
    assert not result.ready and result.confirmation_token is None
    assert result.inspected_state["_error"] == "release_identity_unavailable"
    assert result.inspected_state["wordpress_request_performed"] is False


def test_git_unavailable_checksum_verified_manifest_path(tmp_path):
    root = atlas_layout(tmp_path / "project")
    identity = release.verify_runtime_release_identity(root, write_manifest(root))
    assert identity.atlas_version == "v0.59.8" and identity.atlas_commit == "c" * 40
    assert identity.verification_source == "expected_identity_and_checksum_verified_manifest" and not identity.git_metadata_available
    assert identity.manifest_integrity_verified and identity.expected_release_matched and identity.runtime_identity_verified
    assert identity.plugin_version == "0.57.4"


def test_git_available_manifest_head_and_tag_verification(tmp_path):
    root = atlas_layout(tmp_path / "project")
    add_fake_git(root)
    identity = release.verify_runtime_release_identity(root, write_manifest(root))
    assert identity.verification_source == "git_expected_identity_and_checksum_verified_manifest" and identity.git_metadata_available


@pytest.mark.parametrize("overrides", [
    {"atlas_version": "v0.59.4", "atlas_tag": "v0.59.4"},
    {"atlas_version": "v0.59.6", "atlas_tag": "v0.59.6"},
    {"atlas_commit": "bad"},
    {"atlas_tag": "v0.59.3"},
    {"plugin_version": "0.59.4"},
])
def test_stale_malformed_or_mismatched_manifest_values_block(tmp_path, overrides):
    root = atlas_layout(tmp_path / "project")
    with pytest.raises(release.DeploymentReleaseError, match="release_identity_unavailable"):
        release.verify_runtime_release_identity(root, write_manifest(root, **overrides))


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        ("ATLAS_EXPECTED_RELEASE_VERSION", "VERSION is required"),
        ("ATLAS_EXPECTED_RELEASE_COMMIT", "COMMIT is required"),
        ("ATLAS_EXPECTED_RELEASE_TAG", "TAG is required"),
    ],
)
def test_missing_independent_expected_release_values_block(tmp_path, missing, message):
    root = atlas_layout(tmp_path / "project")
    env = write_manifest(root)
    env.pop(missing)
    with pytest.raises(release.DeploymentReleaseError, match=message):
        release.verify_runtime_release_identity(root, env)


@pytest.mark.parametrize(
    "expected_overrides",
    [
        {"ATLAS_EXPECTED_RELEASE_VERSION": "v0.59.6", "ATLAS_EXPECTED_RELEASE_TAG": "v0.59.6"},
        {"ATLAS_EXPECTED_RELEASE_COMMIT": "d" * 40},
        {"ATLAS_EXPECTED_RELEASE_TAG": "v0.59.7"},
        {"ATLAS_EXPECTED_RELEASE_COMMIT": "bad"},
    ],
)
def test_manifest_cannot_authenticate_itself_or_override_expected_release(tmp_path, expected_overrides):
    root = atlas_layout(tmp_path / "project")
    with pytest.raises(release.DeploymentReleaseError, match="release_identity_unavailable"):
        release.verify_runtime_release_identity(root, write_manifest(root, expected_overrides=expected_overrides))


def test_current_checksum_valid_v0594_schema_one_manifest_is_rejected(tmp_path):
    root = atlas_layout(tmp_path / "project")
    path = root / ".runtime/atlas-release.json"
    path.parent.mkdir(parents=True)
    values = {
        "manifest_schema_version": 1,
        "atlas_version": "v0.59.4",
        "atlas_commit": "a" * 40,
        "atlas_tag": "v0.59.4",
        "plugin_version": "0.57.4",
        "plugin_zip_filename": "project-atlas-metadata-bridge-0.57.4.zip",
        "plugin_zip_sha256": release.SOURCE_EXPECTATIONS.plugin_zip_sha256,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    payload = (json.dumps(values, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(payload)
    env = {
        "ATLAS_RELEASE_MANIFEST_PATH": str(path.resolve()),
        "ATLAS_RELEASE_MANIFEST_SHA256": hashlib.sha256(payload).hexdigest(),
        "ATLAS_EXPECTED_RELEASE_VERSION": "v0.59.8",
        "ATLAS_EXPECTED_RELEASE_COMMIT": "c" * 40,
        "ATLAS_EXPECTED_RELEASE_TAG": "v0.59.8",
    }
    with pytest.raises(release.DeploymentReleaseError, match="schema is invalid"):
        release.verify_runtime_release_identity(root, env)


def test_manifest_path_rejects_outside_traversal_missing_and_symlink_escape(tmp_path):
    root = atlas_layout(tmp_path / "project")
    env = write_manifest(root)
    outside = tmp_path / "outside.json"
    outside.write_bytes((root / ".runtime/atlas-release.json").read_bytes())

    for path, message in (
        (outside.resolve(), "outside an approved runtime directory"),
        ((root / ".runtime/../outside.json").resolve(strict=False), "outside an approved runtime directory"),
        ((root / ".runtime/missing.json").resolve(strict=False), "missing or unsafe"),
    ):
        candidate = {**env, "ATLAS_RELEASE_MANIFEST_PATH": str(path)}
        with pytest.raises(release.DeploymentReleaseError, match=message):
            release.verify_runtime_release_identity(root, candidate)

    link = root / ".runtime/escape.json"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform; Docker exercises resolved path containment.")
    candidate = {**env, "ATLAS_RELEASE_MANIFEST_PATH": str(link)}
    with pytest.raises(release.DeploymentReleaseError, match="outside an approved runtime directory"):
        release.verify_runtime_release_identity(root, candidate)


def test_schema_and_plugin_identity_mismatches_block(tmp_path):
    root = atlas_layout(tmp_path / "project")
    for overrides in (
        {"manifest_schema_version": 3},
        {"source_compatibility_id": "stale-source"},
        {"plugin_zip_sha256": "0" * 64},
    ):
        with pytest.raises(release.DeploymentReleaseError, match="release_identity_unavailable"):
            release.verify_runtime_release_identity(root, write_manifest(root, **overrides))


def test_git_head_or_tag_mismatch_blocks(tmp_path):
    root = atlas_layout(tmp_path / "project")
    add_fake_git(root, head="d" * 40)
    with pytest.raises(release.DeploymentReleaseError, match="commit or tag"):
        release.verify_runtime_release_identity(root, write_manifest(root))
    (root / ".git/refs/heads/main").write_text("c" * 40 + "\n", encoding="ascii")
    (root / ".git/refs/tags/v0.59.8").write_text("e" * 40 + "\n", encoding="ascii")
    with pytest.raises(release.DeploymentReleaseError, match="commit or tag"):
        release.verify_runtime_release_identity(root, write_manifest(root))


def test_runtime_manifest_checksum_mismatch_blocks(tmp_path):
    root = atlas_layout(tmp_path / "project")
    env = write_manifest(root)
    env["ATLAS_RELEASE_MANIFEST_SHA256"] = "0" * 64
    with pytest.raises(release.DeploymentReleaseError, match="checksum mismatch"):
        release.verify_runtime_release_identity(root, env)


def test_verified_runtime_identity_flows_to_artifact(monkeypatch):
    identity = release.RuntimeReleaseIdentity(**manifest_values(), manifest_sha256="d" * 64, verification_source="expected_identity_and_checksum_verified_manifest", git_metadata_available=False, manifest_integrity_verified=True, expected_release_matched=True, runtime_identity_verified=True)
    monkeypatch.setattr(deployment, "verify_runtime_release_identity", lambda _: identity)
    artifact, gates = deployment._verify_artifact()
    assert all(gate.passed for gate in gates)
    assert artifact["atlas_version"] == "v0.59.8" and artifact["atlas_commit"] == "c" * 40 and artifact["atlas_tag"] == "v0.59.8"
    assert artifact["release_manifest_integrity_verified"] and artifact["release_expected_identity_matched"] and artifact["release_runtime_identity_verified"]
    assert artifact["release_git_metadata_available"] is False
    assert artifact["plugin_version"] == "0.57.4"


def test_readiness_api_source_uses_the_same_verified_runtime_identity(monkeypatch):
    identity = release.RuntimeReleaseIdentity(**manifest_values(), manifest_sha256="d" * 64, verification_source="expected_identity_and_checksum_verified_manifest", git_metadata_available=False, manifest_integrity_verified=True, expected_release_matched=True, runtime_identity_verified=True)
    monkeypatch.setattr(deployment, "verify_runtime_release_identity", lambda _: identity)
    readiness = deployment.deployment_readiness()
    assert readiness["release_status"] == "verified"
    assert readiness["release"] == identity.identity()
    assert readiness["source_expectations"]["plugin_version"] == "0.57.4"


def test_wrong_checksum_and_missing_source_block_without_empty_checksum(monkeypatch, tmp_path):
    root = atlas_layout(tmp_path / "project")
    monkeypatch.setattr(deployment, "resolve_program_root", lambda: root)
    monkeypatch.setattr(deployment, "readiness_diagnostics", lambda: {"resolved_program_root": str(root), "artifact_relative_path": release.SOURCE_EXPECTATIONS.artifact_relative_path, "artifact_exists": True, "source_directory_exists": True})
    identity = release.RuntimeReleaseIdentity(**manifest_values(), manifest_sha256="d" * 64, verification_source="expected_identity_and_checksum_verified_manifest", git_metadata_available=False, manifest_integrity_verified=True, expected_release_matched=True, runtime_identity_verified=True)
    monkeypatch.setattr(deployment, "verify_runtime_release_identity", lambda _: identity)
    artifact, gates = deployment._verify_artifact()
    assert artifact["zip_sha256"] == hashlib.sha256(b"zip").hexdigest()
    assert artifact["zip_sha256"] and not {gate.code: gate for gate in gates}["artifact_hash"].passed
    source = root / release.SOURCE_EXPECTATIONS.source_relative_path
    for path in source.iterdir():
        path.unlink()
    source.rmdir()
    _, gates = deployment._verify_artifact()
    assert not {gate.code: gate for gate in gates}["artifact_portable"].passed


def response(status: int = 200, body: str = HTML, *, url: str = EXPECTED_URL, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, text=body, headers=headers or {"content-type": "text/html", "x-sg-cache": "MISS"}, request=httpx.Request("GET", url))


def sequence_client(items: list[httpx.Response]) -> httpx.Client:
    queue = list(items)
    return httpx.Client(transport=httpx.MockTransport(lambda _: queue.pop(0)), follow_redirects=False)


def test_public_authenticated_and_verified_bypass_html():
    public = acquire_rendered_state("user", "pass", client=sequence_client([response()]))
    assert public["outcome"] == "public_html_verified" and public["verified"]
    authenticated = acquire_rendered_state("user", "pass", client=sequence_client([response(403, "Forbidden"), response()]))
    assert authenticated["outcome"] == "authenticated_html_verified" and authenticated["verified"]
    bypass = acquire_rendered_state("user", "pass", verified_bypass_url=EXPECTED_URL, bypass_independently_verified=True, client=sequence_client([response()]))
    assert bypass["outcome"] == "cache_bypass_verified" and bypass["verified"]


def test_bot_protection_blocks_but_does_not_prove_page_failure_or_success():
    result = acquire_rendered_state("user", "pass", client=sequence_client([response(403, "SiteGround bot protection"), response(403, "Forbidden")]))
    assert result["outcome"] == "bot_protection_blocked"
    assert result["manual_evidence_outcome"] == "manual_browser_evidence_required"
    assert not result["verified"]


@pytest.mark.parametrize(
    ("first", "outcome"),
    [
        (response(403, "Forbidden"), "unavailable"),
        (response(404, "Not found"), "error_page_detected"),
        (response(500, "Critical error"), "error_page_detected"),
        (response(302, "", headers={"location": "/other", "content-type": "text/html"}), "unexpected_redirect"),
        (response(200, "<html><title>Login</title>wp-login.php</html>"), "error_page_detected"),
    ],
)
def test_forbidden_errors_redirects_and_login_never_pass(first, outcome):
    result = acquire_rendered_state("user", "pass", client=sequence_client([first, first]))
    assert result["outcome"] == outcome and not result["verified"]


def test_wrong_final_url_and_network_failure_are_explicit():
    wrong = response(200, HTML, url="https://www.drywoodtenting.com/wrong/")
    result = _html_result(wrong, "public_html_verified", "public")
    assert result["outcome"] == "unexpected_redirect" and not result["verified"]
    client = httpx.Client(transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("offline"))), follow_redirects=False)
    result = acquire_rendered_state("user", "pass", client=client)
    assert result["outcome"] == "network_failed" and not result["verified"]


@pytest.mark.parametrize(
    "broken",
    [
        HTML.replace("<title>Drywood Termite Tenting in Orlando, FL</title>", ""),
        HTML.replace(f'<link rel="canonical" href="{EXPECTED_URL}">', ""),
        HTML.replace("<h1>Drywood Termite Tenting in Orlando, FL</h1>", ""),
        HTML.replace(EXPECTED_MEDIA_URL, "https://example.com/wrong.jpg"),
    ],
)
def test_missing_rendered_identity_never_passes(broken):
    bad = response(200, broken)
    result = acquire_rendered_state("user", "pass", client=sequence_client([bad, bad]))
    assert result["outcome"] == "error_page_detected" and not result["verified"]


def test_manual_browser_evidence_valid_tampered_expired_wrong_url_and_secret_rejected():
    key = "local-test-evidence-key"
    evidence = build_manual_browser_evidence(HTML, final_url=EXPECTED_URL, evidence_identifier="evidence-001.json", signing_key=key)
    assert validate_manual_browser_evidence(evidence, key)[0]
    automatic = [response(403, "SiteGround bot protection"), response(403, "Forbidden")]
    result = acquire_rendered_state("user", "pass", manual_evidence=evidence, evidence_signing_key=key, client=sequence_client(automatic))
    assert result["outcome"] == "manual_browser_evidence_verified" and result["verified"]
    for field in ("rendered_head_hash", "visible_content_hash"):
        changed = {**evidence, field: "0" * 64}
        assert not validate_manual_browser_evidence(changed, key)[0]
    expired = build_manual_browser_evidence(HTML, final_url=EXPECTED_URL, evidence_identifier="old.json", signing_key=key, captured_at=datetime.now(UTC) - timedelta(minutes=16))
    assert not validate_manual_browser_evidence(expired, key)[0]
    wrong = {**evidence, "expected_final_url": "https://example.com/"}
    assert not validate_manual_browser_evidence(wrong, key)[0]
    with pytest.raises(ValueError, match="secret-bearing"):
        build_manual_browser_evidence(HTML + "Authorization: Basic secret", final_url=EXPECTED_URL, evidence_identifier="bad.json", signing_key=key)


def test_ui_has_no_independent_stale_release_constant():
    root = release.resolve_program_root()
    source = (root / "frontend/src/pages/WordPressMetadataBridgeInstallPage.tsx").read_text(encoding="utf-8")
    release_source = (root / "backend/app/services/wordpress_deployment_release.py").read_text(encoding="utf-8")
    assert "readiness?.release?.atlas_version" in source
    assert not __import__("re").search(r'atlas_commit\s*=\s*"[0-9a-f]{40}"', release_source)
    assert 'deployment_workflow_version="v0.59.4"' not in release_source
