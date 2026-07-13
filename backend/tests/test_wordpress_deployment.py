from datetime import UTC, datetime, timedelta
import inspect
import json
from pathlib import Path
import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.main import app
from app.db.backup import BackupValidationError, export_backup, load_backup, restore_backup
from app.db.session import engine as app_engine
from app.models import WordPressDeploymentAudit, WordPressDeploymentNonce, WordPressDeploymentTransition
from app.schemas.wordpress import (
    WordPressDeploymentAuthorizeRequest,
    WordPressDeploymentBackupEvidence,
    WordPressDeploymentInstallDryRun,
    WordPressDeploymentManualCompleteRequest,
    WordPressDeploymentVerifyRequest,
)
from app.services import wordpress_deployment as deployment


def proof(**extra):
    value = dict(
        atlas_data_backup_file="atlas-backup-2026-07-12-120000.json",
        atlas_media_backup_file="atlas-media-backup-2026-07-12-120000.zip",
        atlas_program_backup_file="atlas-program-backup-2026-07-12-120000.zip",
        wordpress_backup_method="SiteGround on-demand full-site backup",
        wordpress_backup_reference="sg-backup-123",
        wordpress_backup_completed_at=datetime.now(UTC) - timedelta(minutes=5),
        wordpress_database_included_attestation=True,
        wordpress_plugins_included_attestation=True,
        wordpress_restore_capability_attestation=True,
        confirmer_identity="Shawn Manchette",
        php_error_log_findings="No findings",
        observed_write_summary="No WordPress write performed by Atlas",
    )
    value.update(extra)
    return value


def snapshot(*, installed=False, active=False, version=deployment.PLUGIN_VERSION, path=deployment.PLUGIN_FILE, extra=None):
    base = [{"plugin":"akismet/akismet.php","version":"1.0","status":"inactive"}]
    plugins = [*base]
    if installed: plugins.append({"plugin":path,"version":version,"status":"active" if active else "inactive"})
    if extra: plugins.append(extra)
    active_plugins = [path] if installed and active else []
    return {
        "plugins":plugins, "active_plugins":active_plugins,
        "plugin_inventory_hash":deployment._hash(plugins), "active_plugin_inventory_hash":deployment._hash(active_plugins),
        "page":{"id":8,"status":"publish","slug":"drywood-termite-tenting-orlando-fl","featured_media":31}, "page_snapshot_hash":"page",
        "media31":{"id":31}, "media31_snapshot_hash":"m31", "media32":{"id":32,"post":0,"source_url":"media32.jpg"}, "media32_snapshot_hash":"m32",
        "site":{"name":"My WordPress","description":""}, "rendered":{"head_hash":"head","visible_hash":"visible","atlas_metadata_marker_present":False,"media32_reference_present":False},
        "page_references_media32":False, "locked_state_hash":"locked", "cache_headers":{"cache-control":"no-cache"}, "read_only":True,
    }


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path/'deployment.sqlite3').as_posix()}", connect_args={"check_same_thread":False})
    SQLModel.metadata.create_all(engine)
    return engine


def authorize_request(pre, reference="sg-backup-123"):
    values = proof(wordpress_backup_reference=reference)
    model = WordPressDeploymentAuthorizeRequest(**values, confirmation_token="placeholder", confirmation_phrase=deployment.INSTALL_PHRASE, operator="Shawn Manchette", shawn_approved_at=datetime.now(UTC), evidence_directory="docs/deployment-records/wordpress/orlando-page-8/2026/2026-07-12/v0.59-install")
    artifact = {"plugin_slug":deployment.PLUGIN_SLUG,"plugin_path":deployment.PLUGIN_FILE,"plugin_version":deployment.PLUGIN_VERSION,"zip_file_name":deployment.ZIP_NAME,"zip_sha256":deployment.ZIP_SHA256}
    context = deployment._bound_context(pre, model, artifact)
    model.confirmation_token = deployment._sign_context("authorize_manual_plugin_install", context, datetime.now(UTC)+timedelta(minutes=10))
    dry = WordPressDeploymentInstallDryRun(status="preflight_ready",ready=True,artifact=artifact,inspected_state=pre,gate_results=[])
    return model, dry


def audit_model(status="awaiting_manual_installation", deadline=None):
    backup = proof(); completed=backup["wordpress_backup_completed_at"]
    return WordPressDeploymentAudit(generated_page_id=41,wordpress_post_id=8,action_type="install_metadata_bridge",status=status,operator="Shawn Manchette",shawn_approved_at=datetime.now(UTC),confirmation_phrase_hash="a"*64,atlas_version="v0.57.7",atlas_commit="e"*40,atlas_tag="v0.57.7",plugin_version=deployment.PLUGIN_VERSION,plugin_slug=deployment.PLUGIN_SLUG,plugin_path=deployment.PLUGIN_FILE,zip_file_name=deployment.ZIP_NAME,zip_sha256=deployment.ZIP_SHA256,plugin_source_sha256=deployment.SOURCE_SHA256,backup_reference=backup["wordpress_backup_reference"],backup_completed_at=completed,backup_deadline=deadline or completed+timedelta(hours=4),authorization_jti="1"*32,deployment_key="2"*64,backup_evidence=WordPressDeploymentBackupEvidence(**backup).model_dump(mode="json"),pre_snapshot=snapshot(),evidence_directory="docs/deployment-records/wordpress/orlando-page-8/2026/2026-07-12/v0.59-install")


def test_install_routes_are_fixed_and_no_activation_or_upload_route():
    routes={(route.path,method) for route in app.routes for method in (getattr(route,"methods",None) or set())}; prefix="/api/wordpress/deployment/metadata-bridge/install/"
    assert {(prefix+f"{action}/{{page_id}}","POST") for action in ("dry-run","authorize","report-manual-complete","verify")} <= routes
    assert not any(term in path for path,_ in routes if prefix in path for term in ("activate","upload","remove","delete"))
    request=proof();request["wordpress_backup_completed_at"]=request["wordpress_backup_completed_at"].isoformat()
    with TestClient(app) as client: assert client.post(prefix+"dry-run/42",json=request).status_code==404


def test_authorization_consumes_nonce_and_preserves_exact_initial_sequence(monkeypatch,db):
    pre=snapshot();request,dry=authorize_request(pre);monkeypatch.setattr(deployment,"install_dry_run",lambda *_:dry)
    with Session(db) as session:
        result=deployment.authorize_manual_install(session,41,request)
        audit=session.get(WordPressDeploymentAudit,result.audit_id);nonce=session.exec(select(WordPressDeploymentNonce)).one()
        assert result.state_history==["installation_authorized","awaiting_manual_installation"]
        assert audit.status=="awaiting_manual_installation" and nonce.audit_id==audit.id
        assert audit.confirmation_phrase_hash != deployment.INSTALL_PHRASE and request.confirmation_token not in str(audit.model_dump())


def test_nonce_replay_and_duplicate_deployment_are_blocked(monkeypatch,db):
    pre=snapshot();request,dry=authorize_request(pre);monkeypatch.setattr(deployment,"install_dry_run",lambda *_:dry)
    with Session(db) as session: deployment.authorize_manual_install(session,41,request)
    with Session(db) as session:
        with pytest.raises(HTTPException) as error: deployment.authorize_manual_install(session,41,request)
        assert error.value.status_code==409
    second,second_dry=authorize_request(pre);monkeypatch.setattr(deployment,"install_dry_run",lambda *_:second_dry)
    with Session(db) as session:
        with pytest.raises(HTTPException): deployment.authorize_manual_install(session,41,second)


def test_concurrent_duplicate_authorization_has_one_winner(monkeypatch,db):
    pre=snapshot();request,dry=authorize_request(pre);monkeypatch.setattr(deployment,"install_dry_run",lambda *_:dry)
    barrier=threading.Barrier(2); outcomes=[]
    def worker():
        with Session(db) as session:
            barrier.wait()
            try: deployment.authorize_manual_install(session,41,request);outcomes.append("ok")
            except HTTPException: outcomes.append("blocked")
    threads=[threading.Thread(target=worker) for _ in range(2)]
    [thread.start() for thread in threads];[thread.join() for thread in threads]
    assert sorted(outcomes)==["blocked","ok"]
    with Session(db) as session: assert len(session.exec(select(WordPressDeploymentAudit)).all())==1


def test_transition_helper_rejects_skips(db):
    with Session(db) as session:
        audit=audit_model(status="awaiting_manual_installation");session.add(audit);session.commit();session.refresh(audit)
        with pytest.raises(HTTPException): deployment._transition(session,audit,"verified","actor","skip","request")


def test_manual_acknowledgment_records_both_states_and_verification_reuse_is_blocked(monkeypatch,db):
    monkeypatch.setattr(deployment,"_stored_backup_gates",lambda *_:[deployment._gate("backup","backup",True,"")]);monkeypatch.setattr(deployment,"_observe",lambda *_:snapshot(installed=True))
    with Session(db) as session:
        audit=audit_model();session.add(audit);session.commit();session.refresh(audit)
        result=deployment.report_manual_complete(session,41,WordPressDeploymentManualCompleteRequest(audit_id=audit.id,operator="Shawn Manchette",manual_upload_completed_attestation=True))
        assert result.state_history[-2:]==["manual_installation_reported","verification_pending"]
        verify=deployment.verify_manual_install(session,41,WordPressDeploymentVerifyRequest(audit_id=audit.id,operator="Shawn Manchette",php_error_log_findings="No findings"))
        assert verify.verified and verify.state_history[-1]=="verified"
        with pytest.raises(HTTPException): deployment.verify_manual_install(session,41,WordPressDeploymentVerifyRequest(audit_id=audit.id,operator="Shawn Manchette",php_error_log_findings="No findings"))


def test_manual_before_authorization_and_verification_before_acknowledgment_rejected(monkeypatch,db):
    monkeypatch.setattr(deployment,"_observe",lambda *_:snapshot(installed=True))
    with Session(db) as session:
        audit=audit_model(status="installation_authorized");session.add(audit);session.commit();session.refresh(audit)
        with pytest.raises(HTTPException): deployment.report_manual_complete(session,41,WordPressDeploymentManualCompleteRequest(audit_id=audit.id,operator="Shawn Manchette",manual_upload_completed_attestation=True))
        with pytest.raises(HTTPException): deployment.verify_manual_install(session,41,WordPressDeploymentVerifyRequest(audit_id=audit.id,operator="Shawn Manchette",php_error_log_findings="No findings"))


@pytest.mark.parametrize("phase",["ack","verify"])
def test_four_hour_expiry_blocks_acknowledgment_and_verification(monkeypatch,db,phase):
    monkeypatch.setattr(deployment,"_observe",lambda *_:snapshot(installed=True));monkeypatch.setattr(deployment,"_backup_gates",lambda *_:[])
    status="awaiting_manual_installation" if phase=="ack" else "verification_pending"
    with Session(db) as session:
        audit=audit_model(status=status,deadline=datetime.now(UTC)-timedelta(seconds=1));session.add(audit);session.commit();session.refresh(audit)
        if phase=="ack":
            with pytest.raises(HTTPException): deployment.report_manual_complete(session,41,WordPressDeploymentManualCompleteRequest(audit_id=audit.id,operator="Shawn Manchette",manual_upload_completed_attestation=True))
            session.refresh(audit);assert audit.status=="failed"
        else:
            result=deployment.verify_manual_install(session,41,WordPressDeploymentVerifyRequest(audit_id=audit.id,operator="Shawn Manchette",php_error_log_findings="No findings"));assert not result.verified


@pytest.mark.parametrize(("change","failed_gate"),[("extra","plugin_delta"),("active","active_inventory"),("locked","locked_state"),("cache","cache_headers")])
def test_bound_state_and_plugin_inventory_mutations_fail(change,failed_gate):
    before=snapshot();after=snapshot(installed=True)
    if change=="extra": after=snapshot(installed=True,extra={"plugin":"new/new.php","version":"1","status":"inactive"})
    if change=="active": after["active_plugin_inventory_hash"]="changed"
    if change=="locked": after["locked_state_hash"]="changed"
    if change=="cache": after["cache_headers"]={"age":"1"}
    gates={gate.code:gate for gate in deployment._expected_install_delta_gates(before,after)}
    assert not gates[failed_gate].passed


def test_exact_inactive_atlas_only_delta_passes_without_operator_booleans():
    gates=deployment._expected_install_delta_gates(snapshot(),snapshot(installed=True))
    assert all(gate.passed for gate in gates)
    assert not {"safety_option_absent_attestation","atlas_post_meta_absent_attestation","installer_writes_only_attestation","cache_purge_absent_attestation"} & set(WordPressDeploymentVerifyRequest.model_fields)


@pytest.mark.parametrize(("mutation","gate"),[("missing","exact_plugin"),("wrong_path","exact_plugin"),("wrong_version","exact_plugin"),("active","inactive"),("changed","media32_unchanged"),("attached","media32_unattached"),("featured","media32_unattached"),("rendered","media32_unreferenced"),("page","media32_unreferenced")])
def test_plugin_and_media32_strictness(mutation,gate):
    after=snapshot(installed=True)
    if mutation=="missing": after=snapshot()
    elif mutation=="wrong_path": after=snapshot(installed=True,path="wrong/plugin.php")
    elif mutation=="wrong_version": after=snapshot(installed=True,version="0.57.3")
    elif mutation=="active": after=snapshot(installed=True,active=True)
    elif mutation=="changed": after["media32_snapshot_hash"]="changed"
    elif mutation=="attached": after["media32"]["post"]=8
    elif mutation=="featured": after["page"]["featured_media"]=32
    elif mutation=="rendered": after["rendered"]["media32_reference_present"]=True
    elif mutation=="page": after["page_references_media32"]=True
    gates={item.code:item for item in deployment._expected_install_delta_gates(snapshot(),after)}
    assert not gates[gate].passed


@pytest.mark.parametrize("value",["/docs/deployment-records/wordpress/orlando-page-8/2026/2026-07-12/v0.59-install",r"C:\docs\deployment-records",r"\\server\share",r"docs\deployment-records\wordpress\orlando-page-8\2026\2026-07-12\v0.59-install","docs/deployment-records/wordpress/orlando-page-8/2026/../v0.59-install","docs/deployment-records/wordpress/orlando-page-8/2026/%2e%2e/v0.59-install","docs/deployment-records/wordpress/orlando-page-9/2026/2026-07-12/v0.59-install","docs/deployment-records/wordpress/orlando-page-8/2026/2026-07-12/v0.60-install"])
def test_evidence_path_rejects_unsafe_or_wrong_scope(value):
    with pytest.raises(HTTPException): deployment._safe_evidence_path(value)


def test_evidence_path_resolved_symlink_escape_rejected(monkeypatch,tmp_path):
    project=tmp_path/"project";root=project/"docs/deployment-records/wordpress/orlando-page-8";outside=tmp_path/"outside";root.mkdir(parents=True);outside.mkdir()
    year=root/"2026"
    try:
        year.symlink_to(outside,target_is_directory=True)
    except OSError:
        original_resolve=Path.resolve
        def simulated_resolve(path,strict=False):
            if str(path).startswith(str(year)): return outside/"2026-07-12/v0.59-install"
            return original_resolve(path,strict=strict)
        monkeypatch.setattr(Path,"resolve",simulated_resolve)
    monkeypatch.setattr(deployment,"PROJECT_ROOT",project);monkeypatch.setattr(deployment,"EVIDENCE_ROOT",root)
    with pytest.raises(HTTPException): deployment._safe_evidence_path("docs/deployment-records/wordpress/orlando-page-8/2026/2026-07-12/v0.59-install")


def test_dry_run_does_not_create_evidence_directory(monkeypatch,tmp_path):
    monkeypatch.setattr(deployment,"PROJECT_ROOT",tmp_path);monkeypatch.setattr(deployment,"EVIDENCE_ROOT",tmp_path/"docs/deployment-records/wordpress/orlando-page-8")
    path="docs/deployment-records/wordpress/orlando-page-8/2026/2026-07-12/v0.59-install";deployment._safe_evidence_path(path)
    assert not (tmp_path/path).exists()


def test_database_constraints_lengths_and_history_tables(db):
    inspector=sa_inspect(db);tables=set(inspector.get_table_names())
    assert {"wordpressdeploymentaudit","wordpressdeploymentnonce","wordpressdeploymenttransition"} <= tables
    columns={column["name"]:column for column in inspector.get_columns("wordpressdeploymentaudit")}
    assert columns["status"]["type"].length==40 and columns["operator"]["type"].length==200 and columns["evidence_directory"]["type"].length==500
    assert inspector.get_unique_constraints("wordpressdeploymentaudit") and inspector.get_check_constraints("wordpressdeploymentaudit")


def test_v031_backup_restores_audit_nonce_and_transition_history_idempotently(tmp_path):
    with TestClient(app):
        with Session(app_engine) as session:
            audit=audit_model();session.add(audit);session.commit();session.refresh(audit)
            session.add(WordPressDeploymentNonce(jti=audit.authorization_jti,token_fingerprint="f"*64,action_type=audit.action_type,audit_id=audit.id))
            session.add(WordPressDeploymentTransition(audit_id=audit.id,previous_state=None,new_state="installation_authorized",actor="Shawn Manchette",reason="authorized",request_identifier="a"*32))
            session.add(WordPressDeploymentTransition(audit_id=audit.id,previous_state="installation_authorized",new_state="awaiting_manual_installation",actor="Shawn Manchette",reason="awaiting",request_identifier="b"*32))
            session.commit(); exported=export_backup(session,backup_dir=tmp_path)
            session.exec(delete(WordPressDeploymentTransition));session.exec(delete(WordPressDeploymentNonce));session.exec(delete(WordPressDeploymentAudit));session.commit()
            restore_backup(session,exported["path"]);restore_backup(session,exported["path"])
            restored=session.exec(select(WordPressDeploymentAudit)).one()
            assert restored.operator=="Shawn Manchette" and restored.evidence_directory.endswith("v0.59-install")
            assert len(session.exec(select(WordPressDeploymentNonce)).all())==1
            assert [item.new_state for item in session.exec(select(WordPressDeploymentTransition).order_by(WordPressDeploymentTransition.id)).all()]==["installation_authorized","awaiting_manual_installation"]


def test_v030_backup_compatibility_and_unknown_future_version(tmp_path):
    with TestClient(app):
        with Session(app_engine) as session: exported=export_backup(session,backup_dir=tmp_path)
    payload=json.loads(Path(exported["path"]).read_text(encoding="utf-8"));payload["metadata"]["version"]="0.30"
    for group in ("wordpress_deployment_audits","wordpress_deployment_nonces","wordpress_deployment_transitions"):
        payload["data"].pop(group,None);payload["metadata"]["table_counts"].pop(group,None)
    legacy=tmp_path/"v030.json";legacy.write_text(json.dumps(payload),encoding="utf-8")
    loaded=load_backup(legacy);assert loaded["data"]["wordpress_deployment_transitions"]==[]
    payload["metadata"]["version"]="9.99";future=tmp_path/"future.json";future.write_text(json.dumps(payload),encoding="utf-8")
    with pytest.raises(BackupValidationError): load_backup(future)


def test_no_hidden_upload_activation_transport_or_secret_fields():
    source=inspect.getsource(deployment)
    assert 'method != "GET"' in source
    for forbidden in ("wp-admin/update.php","multipart","application/octet-stream","activate=true","wp plugin install","plugin delete"):
        assert forbidden not in source.lower()
    request_fields=set(WordPressDeploymentAuthorizeRequest.model_fields)|set(WordPressDeploymentVerifyRequest.model_fields)
    assert not request_fields & {"password","cookie","cookies","nonce","application_password","wordpress_password"}
