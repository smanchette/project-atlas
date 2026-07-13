from __future__ import annotations

import base64, hashlib, hmac, json, re, secrets
from collections import Counter
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.backup import BackupValidationError, load_backup, resolve_backup_download
from app.models import Business, GeneratedPage, ImageMetadata, WordPressMetadataState, WordPressMetadataSyncAudit
from app.schemas.wordpress import (
    WordPressDraftGateResult, WordPressMetadataApplyRequest, WordPressMetadataApplyResult,
    WordPressMetadataBackupProof, WordPressMetadataDryRun, WordPressMetadataPayload,
    WordPressMetadataReconciliationDryRun, WordPressMetadataReconciliationRequest,
    WordPressMetadataReconciliationResult, WordPressMetadataRollbackDryRun,
    WordPressMetadataRollbackRequest, WordPressMetadataRollbackResult, WordPressMetadataVerification,
)
from app.services.wordpress_sandbox import get_wordpress_application_password, read_wordpress_settings

TARGET_PAGE_ID, TARGET_POST_ID, TARGET_MEDIA_ID, EXCLUDED_MEDIA_ID = 41, 8, 31, 32
EXPECTED_SLUG = "drywood-termite-tenting-orlando-fl"
EXPECTED_URL = "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/"
EXPECTED_MEDIA_URL = "https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png"
EXPECTED_MEDIA_CHECKSUM = "9f94d1ba555c2f3655bd600a61aac3247ab2a1a951a6cf73b1152d94fe40b2a0"
META_DESCRIPTION = "Flo-Zone Pest And Termite Solutions Inc provides professional drywood termite tenting services for homes and properties in Orlando, Florida."
ORGANIZATION_NAME = "Flo-Zone Pest And Termite Solutions Inc"
PLUGIN_VERSION = "0.57.4"
# Updated after the final plugin source is frozen.
PLUGIN_CHECKSUM = "5b33659b9fab81ff5aa6d6c8e0d5b89037b5d62fa454e0939f9b3ca91d32cab2"
APPLY_PHRASE = "APPLY ORLANDO METADATA TO WORDPRESS"
ROLLBACK_PHRASE = "ROLL BACK ORLANDO METADATA"
RECONCILE_PHRASE = "FINALIZE VERIFIED ORLANDO METADATA IN ATLAS"
TOKEN_TTL_MINUTES, BACKUP_MAX_AGE = 15, timedelta(hours=24)
_secret = secrets.token_bytes(32)


def build_orlando_metadata_payload() -> WordPressMetadataPayload:
    title, image_id = "Drywood Termite Tenting in Orlando, FL", f"{EXPECTED_URL}#primaryimage"
    graph = [
        {"@type":"WebSite","@id":"https://www.drywoodtenting.com/#website","url":"https://www.drywoodtenting.com/","name":ORGANIZATION_NAME},
        {"@type":"Organization","@id":"https://www.drywoodtenting.com/#organization","name":ORGANIZATION_NAME,"url":"https://www.drywoodtenting.com/","telephone":"(844) 600-8368","email":"Office@Flo-ZoneTenting.com","identifier":{"@type":"PropertyValue","name":"License identifier","value":"JB360566"}},
        {"@type":"Person","@id":"https://www.drywoodtenting.com/#jordan-ward","name":"Jordan Ward","jobTitle":"Certified Operator","worksFor":{"@id":"https://www.drywoodtenting.com/#organization"}},
        {"@type":"ImageObject","@id":image_id,"url":EXPECTED_MEDIA_URL,"contentUrl":EXPECTED_MEDIA_URL,"caption":"Two-story Orlando Florida home professionally covered for drywood termite tenting"},
        {"@type":"Service","@id":f"{EXPECTED_URL}#service","name":title,"serviceType":"Drywood termite tenting","areaServed":{"@type":"City","name":"Orlando","containedInPlace":{"@type":"State","name":"Florida"}},"provider":{"@id":"https://www.drywoodtenting.com/#organization"},"image":{"@id":image_id}},
        {"@type":"WebPage","@id":f"{EXPECTED_URL}#webpage","url":EXPECTED_URL,"name":title,"description":META_DESCRIPTION,"isPartOf":{"@id":"https://www.drywoodtenting.com/#website"},"about":{"@id":f"{EXPECTED_URL}#service"},"primaryImageOfPage":{"@id":image_id}},
    ]
    return WordPressMetadataPayload(meta_description=META_DESCRIPTION,
        open_graph={"og:title":title,"og:description":META_DESCRIPTION,"og:image":EXPECTED_MEDIA_URL,"og:url":EXPECTED_URL,"og:type":"website"},
        twitter={"twitter:card":"summary_large_image","twitter:title":title,"twitter:description":META_DESCRIPTION,"twitter:image":EXPECTED_MEDIA_URL},
        json_ld={"@context":"https://schema.org","@graph":graph})


def dry_run_wordpress_metadata(session: Session, page_id: int, proof: WordPressMetadataBackupProof | None = None) -> WordPressMetadataDryRun:
    _require_target(page_id); payload = build_orlando_metadata_payload(); desired_hash = _hash(payload.model_dump(mode="json"))
    observed = _observe(session,include_html=True); page, business, image = observed["page"], observed["business"], observed["image"]
    plugin, post, media, validation = observed["plugin"], observed["post"], observed["media"], observed["validation"]
    snapshot = plugin.get("snapshot") if isinstance(plugin.get("snapshot"), dict) else plugin
    gates = _local_gates(page, business, image, observed["settings"], observed["password"]) + [
        _gate("plugin_installed","Metadata bridge is installed",plugin.get("plugin")=="project-atlas-metadata-bridge","The exact bridge must respond."),
        _gate("plugin_version","Plugin version is exact",plugin.get("version")==PLUGIN_VERSION,f"Plugin version must be {PLUGIN_VERSION}."),
        _gate("plugin_checksum","Plugin checksum is exact",plugin.get("checksum")==PLUGIN_CHECKSUM,"Plugin source checksum changed."),
        _gate("plugin_active","Plugin is active",plugin.get("active") is True,"Activation is a separate action."),
        _gate("non_rendering","Current activation is disabled",snapshot.get("rendering_enabled") is False,"Dry-run requires disabled rendering."),
        _gate("activation_generation","Activation generation exists",bool(snapshot.get("activation_generation")),"Activation safety generation is required."),
        _gate("live_post","Post identity is unchanged",_post_fixed(post),"Post 8 identity changed."),
        _gate("media_31","Media 31 identity is unchanged",media.get("id")==31 and media.get("source_url")==EXPECTED_MEDIA_URL,"Only media 31 is allowed."),
        _gate("plugin_validation","Plugin independently accepts payload",validation.get("valid") is True and validation.get("payload_hash")==desired_hash,"Plugin validation failed."),
    ]
    if proof is None: gates.append(_gate("backup_proof","Complete backup proof supplied",False,"Dry-run must include all backup identities and attestations."))
    else: gates.extend(_backup_gates(proof))
    context = _apply_context(session, observed, proof, desired_hash)
    ready = all(g.passed for g in gates); token = expires_at = None
    if ready:
        expires = datetime.now(UTC)+timedelta(minutes=TOKEN_TTL_MINUTES); token = _sign_context("apply_metadata", context, expires); expires_at=expires.isoformat()
    return WordPressMetadataDryRun(page_id=41,wordpress_post_id=8,status="metadata_ready" if ready else "blocked",ready=ready,
        plugin_version=PLUGIN_VERSION,plugin_installed=plugin.get("plugin")=="project-atlas-metadata-bridge",plugin_active=plugin.get("active") is True,
        plugin_rendering_enabled=snapshot.get("rendering_enabled") is True,payload=payload,payload_hash=desired_hash,current_snapshot=snapshot,
        gate_results=gates,confirmation_token=token,confirmation_phrase=APPLY_PHRASE if ready else None,expires_at=expires_at,bound_state_hash=_hash(context))


def apply_wordpress_metadata(session: Session, page_id: int, request: WordPressMetadataApplyRequest) -> WordPressMetadataApplyResult:
    token=_verify(request.confirmation_token,"apply_metadata",page_id)
    if not hmac.compare_digest(request.confirmation_phrase,APPLY_PHRASE): raise HTTPException(422,"The metadata confirmation phrase is incorrect.")
    dry=dry_run_wordpress_metadata(session,page_id,request)
    if not dry.ready or token.get("bound_state_hash")!=dry.bound_state_hash: raise HTTPException(409,"Metadata or backup state changed. Run a new dry run.")
    settings=read_wordpress_settings(session); snapshot=dry.current_snapshot or {}; gates=dry.gate_results
    audit=WordPressMetadataSyncAudit(generated_page_id=41,wordpress_post_id=8,action_type="apply_metadata",status="pending",wordpress_site_url=settings.site_url,
        payload_hash=dry.payload_hash,payload_snapshot=dry.payload.model_dump(mode="json"),previous_snapshot=snapshot,gate_results=[g.model_dump(mode="json") for g in gates]+[{"code":"bound_context","context":token["context"]}],
        data_backup_file_name=request.confirmed_data_backup_file,wordpress_backup_reference=request.wordpress_backup_reference,plugin_version=PLUGIN_VERSION)
    session.add(audit);session.commit();session.refresh(audit)
    try:
        result=_send_json(settings.site_url,settings.username,get_wordpress_application_password() or "","/wp-json/project-atlas/v1/pages/8/metadata","PUT",
            {"payload":dry.payload.model_dump(mode="json"),"payload_hash":dry.payload_hash,"expected_revision":str(snapshot.get("revision","0")),
             "expected_snapshot_hash":_hash(snapshot),"activation_generation":snapshot.get("activation_generation"),"plugin_checksum":PLUGIN_CHECKSUM})
        if result.get("payload_hash")!=dry.payload_hash or not result.get("revision"): raise RuntimeError("WordPress apply response mismatch.")
        verification=verify_wordpress_metadata(session,41,require_atlas_state=False)
        if not verification.metadata_correct: raise RuntimeError("Rendered verification failed after WordPress apply.")
        after=_observe(session,include_validation=False,include_html=True);after_core=_core_post_snapshot(after["post"]);after_core["h1"]=_parse_html(after["html"]).get("h1")
        if after_core!=token["context"]["post_snapshot"]: raise RuntimeError("Core WordPress post state changed after dry-run.")
    except Exception as exc:
        audit.status="reconciliation_required";audit.completed_at=datetime.now(UTC);audit.error_message=str(exc);session.add(audit);session.commit()
        raise HTTPException(502,"WordPress may have accepted metadata; do not retry. Run reconciliation dry-run.") from exc
    try:
        _finalize_apply(session,audit,str(result["revision"]),dry.payload.model_dump(mode="json"),dry.payload_hash,result)
    except Exception as exc:
        session.rollback()
        try:
            persisted=session.get(WordPressMetadataSyncAudit,audit.id)
            if persisted: persisted.status="reconciliation_required"; persisted.error_message=f"Atlas finalization failed: {exc}"; session.add(persisted); session.commit()
        except Exception: session.rollback()
        raise HTTPException(500,"WordPress verified, but Atlas finalization failed. Use reconciliation.") from exc
    return WordPressMetadataApplyResult(page_id=41,wordpress_post_id=8,status="metadata_applied",payload_hash=dry.payload_hash,wordpress_revision=str(result["revision"]),audit_id=audit.id or 0,verification=verification.model_dump(mode="json"))


def verify_wordpress_metadata(session: Session,page_id:int,*,require_atlas_state:bool=True)->WordPressMetadataVerification:
    _require_target(page_id); approved=build_orlando_metadata_payload().model_dump(mode="json"); approved_hash=_hash(approved)
    observed=_observe(session,include_validation=False,include_html=True); plugin=observed["plugin"]; snapshot=plugin.get("snapshot") if isinstance(plugin.get("snapshot"),dict) else plugin
    post,html=observed["post"],observed["html"]; parsed=_parse_html(html); state=_metadata_state(session)
    gates=[]
    if require_atlas_state: gates.append(_gate("atlas_state","Atlas state independently matches",bool(state and state.status=="applied" and state.payload==approved and _hash(state.payload)==approved_hash and state.payload_hash==approved_hash),"Atlas state must equal the approved payload."))
    gates += _render_gates(parsed,post,approved)
    audit=session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id==41,WordPressMetadataSyncAudit.action_type=="apply_metadata").order_by(WordPressMetadataSyncAudit.attempted_at.desc())).first()
    baseline=next((item.get("context") for item in (audit.gate_results if audit else []) if item.get("code")=="bound_context"),None)
    current_core=_core_post_snapshot(post);current_core["h1"]=parsed.get("h1")
    gates.append(_gate("bound_core_invariants","Title, H1, visible content, excerpt, slug, URL, status, and featured media unchanged",bool(baseline and baseline.get("post_snapshot")==current_core and baseline.get("visible_content_hash")==parsed.get("visible_hash")),"Rendered/core page state differs from the dry-run baseline."))
    gates += [_gate("stored_payload","Complete stored payload matches",snapshot.get("payload")==approved and _hash(snapshot.get("payload"))==approved_hash,"Stored payload mismatch."),
        _gate("stored_hash","Stored payload hash recomputes",snapshot.get("payload_hash")==approved_hash,"Stored hash mismatch."),
        _gate("authorized_generation","Current activation authorizes rendering",snapshot.get("rendering_enabled") is True and bool(snapshot.get("activation_generation")),"Rendering authorization invalid."),
        _gate("plugin_identity","Plugin version/checksum exact",plugin.get("version")==PLUGIN_VERSION and plugin.get("checksum")==PLUGIN_CHECKSUM,"Plugin identity changed.")]
    correct=all(g.passed for g in gates)
    return WordPressMetadataVerification(page_id=41,wordpress_post_id=8,status="verified" if correct else ("not_applied" if state is None else "failed"),apply_needed=not correct,metadata_correct=correct,payload_hash=approved_hash,live_payload_hash=snapshot.get("payload_hash"),rendered={"snapshot":snapshot,"html":parsed},gate_results=gates)


def dry_run_wordpress_metadata_reconciliation(session:Session,page_id:int,proof:WordPressMetadataBackupProof|None=None)->WordPressMetadataReconciliationDryRun:
    _require_target(page_id); audit=_reconcilable_audit(session); verification=verify_wordpress_metadata(session,page_id,require_atlas_state=False)
    gates=[_gate("original_audit","Original uncertain apply exists",audit is not None,"A pending/failed apply audit is required."),
        _gate("audit_payload","Audit binds approved payload",bool(audit and audit.payload_hash==verification.payload_hash),"Audit payload mismatch."),
        _gate("rendered_verified","WordPress already renders approved metadata",verification.metadata_correct,"Rendered verification failed.")]
    gates += _backup_gates(proof) if proof else [_gate("backup_proof","Complete backup proof supplied",False,"All backup proof is required.")]
    context={"audit_id":audit.id if audit else None,"audit_payload_hash":audit.payload_hash if audit else None,"verification_hash":_hash(verification.model_dump(mode="json")),"backup":_proof_dict(proof)}
    ready=all(g.passed for g in gates); token=expires_at=None
    if ready:
        expires=datetime.now(UTC)+timedelta(minutes=TOKEN_TTL_MINUTES); token=_sign_context("reconcile_metadata",context,expires);expires_at=expires.isoformat()
    return WordPressMetadataReconciliationDryRun(page_id=41,wordpress_post_id=8,status="safe_to_finalize" if ready else "blocked",safe_to_finalize=ready,original_audit_id=audit.id if audit else None,verification=verification,gate_results=gates,confirmation_token=token,confirmation_phrase=RECONCILE_PHRASE if ready else None,expires_at=expires_at)


def reconcile_wordpress_metadata(session:Session,page_id:int,request:WordPressMetadataReconciliationRequest)->WordPressMetadataReconciliationResult:
    token=_verify(request.confirmation_token,"reconcile_metadata",page_id)
    if not hmac.compare_digest(request.confirmation_phrase,RECONCILE_PHRASE): raise HTTPException(422,"The reconciliation phrase is incorrect.")
    dry=dry_run_wordpress_metadata_reconciliation(session,page_id,request)
    current_context={"audit_id":dry.original_audit_id,"audit_payload_hash":dry.verification.payload_hash if dry.original_audit_id else None,"verification_hash":_hash(dry.verification.model_dump(mode="json")),"backup":_proof_dict(request)}
    if not dry.safe_to_finalize or token.get("bound_state_hash")!=_hash(current_context): raise HTTPException(409,"Reconciliation state changed.")
    audit=session.get(WordPressMetadataSyncAudit,dry.original_audit_id)
    if not audit or audit.id!=token["context"]["audit_id"]: raise HTTPException(409,"Original audit changed.")
    snapshot=(dry.verification.rendered or {}).get("snapshot",{}); _finalize_apply(session,audit,str(snapshot.get("revision","")),build_orlando_metadata_payload().model_dump(mode="json"),dry.verification.payload_hash,snapshot)
    return WordPressMetadataReconciliationResult(page_id=41,wordpress_post_id=8,status="metadata_reconciled",original_audit_id=audit.id or 0)


def dry_run_wordpress_metadata_rollback(session:Session,page_id:int,proof:WordPressMetadataBackupProof|None=None)->WordPressMetadataRollbackDryRun:
    _require_target(page_id); audit=session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id==41,WordPressMetadataSyncAudit.action_type=="apply_metadata",WordPressMetadataSyncAudit.status=="applied").order_by(WordPressMetadataSyncAudit.attempted_at.desc())).first()
    verification=verify_wordpress_metadata(session,page_id); snapshot=((verification.rendered or {}).get("snapshot") or {}); state=_metadata_state(session)
    gates=[_gate("applied_audit","Exact successful apply audit exists",audit is not None,"Successful audit required."),_gate("current_state","Current metadata verified",verification.metadata_correct,"Current metadata mismatch."),_gate("previous_snapshot","Previous snapshot exists",bool(audit and audit.previous_snapshot is not None),"Restore snapshot required.")]
    gates += _backup_gates(proof) if proof else [_gate("backup_proof","Complete backup proof supplied",False,"All backup proof is required.")]
    context={"successful_apply_audit_id":audit.id if audit else None,"metadata_state_id":state.id if state else None,"activation_generation":snapshot.get("activation_generation"),"plugin_revision":snapshot.get("revision"),"plugin_version":PLUGIN_VERSION,"plugin_checksum":PLUGIN_CHECKSUM,"previous_snapshot_hash":_hash(audit.previous_snapshot) if audit else None,"current_snapshot_hash":_hash(snapshot),"current_payload_hash":snapshot.get("payload_hash"),"rollback_payload_hash":_hash(audit.previous_snapshot or {}) if audit else None,"rendered_head_hash":((verification.rendered or {}).get("html") or {}).get("head_hash"),"backup":_proof_dict(proof)}
    ready=all(g.passed for g in gates);token=expires_at=None
    if ready:
        expires=datetime.now(UTC)+timedelta(minutes=TOKEN_TTL_MINUTES);token=_sign_context("rollback_metadata",context,expires);expires_at=expires.isoformat()
    return WordPressMetadataRollbackDryRun(page_id=41,wordpress_post_id=8,status="rollback_ready" if ready else "blocked",ready=ready,current_payload_hash=audit.payload_hash if audit else None,restore_snapshot=audit.previous_snapshot if audit else None,gate_results=gates,confirmation_token=token,confirmation_phrase=ROLLBACK_PHRASE if ready else None,expires_at=expires_at,successful_apply_audit_id=audit.id if audit else None,bound_state_hash=_hash(context))


def rollback_wordpress_metadata(session:Session,page_id:int,request:WordPressMetadataRollbackRequest)->WordPressMetadataRollbackResult:
    token=_verify(request.confirmation_token,"rollback_metadata",page_id)
    if not hmac.compare_digest(request.confirmation_phrase,ROLLBACK_PHRASE): raise HTTPException(422,"The rollback phrase is incorrect.")
    dry=dry_run_wordpress_metadata_rollback(session,page_id,request)
    if not dry.ready or token.get("bound_state_hash")!=dry.bound_state_hash or token["context"].get("successful_apply_audit_id")!=dry.successful_apply_audit_id: raise HTTPException(409,"Rollback state changed.")
    settings=read_wordpress_settings(session); c=token["context"]
    result=_send_json(settings.site_url,settings.username,get_wordpress_application_password() or "","/wp-json/project-atlas/v1/pages/8/metadata/rollback","PUT",{"current_payload_hash":c["current_payload_hash"],"snapshot":dry.restore_snapshot,"expected_revision":str(c["plugin_revision"]),"activation_generation":c["activation_generation"],"expected_current_snapshot_hash":c["current_snapshot_hash"],"rollback_payload_hash":c["rollback_payload_hash"]})
    if result.get("rendering_enabled") is not False: raise HTTPException(502,"Rollback verification failed.")
    state=_metadata_state(session)
    if state: state.status="rolled_back";state.payload=None;state.payload_hash=None;state.wordpress_revision=str(result.get("revision",''));session.add(state)
    audit=WordPressMetadataSyncAudit(generated_page_id=41,wordpress_post_id=8,action_type="rollback_metadata",status="rolled_back",wordpress_site_url=settings.site_url,payload_hash=c["current_payload_hash"],payload_snapshot=dry.restore_snapshot or {},previous_snapshot=None,returned_snapshot=result,gate_results=[g.model_dump(mode="json") for g in dry.gate_results],data_backup_file_name=request.confirmed_data_backup_file,wordpress_backup_reference=request.wordpress_backup_reference,plugin_version=PLUGIN_VERSION,completed_at=datetime.now(UTC));session.add(audit);session.commit();session.refresh(audit)
    return WordPressMetadataRollbackResult(page_id=41,wordpress_post_id=8,status="metadata_rolled_back",audit_id=audit.id or 0,wordpress_revision=str(result.get("revision",'')))


class _HTML(HTMLParser):
    def __init__(self): super().__init__(); self.titles=[];self.h1=[];self.meta=[];self.canon=[];self.scripts=[];self.visible=[];self._tag="";self._atlas_script=False;self._head=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);self._tag=tag
        if tag in ("title","meta","link","script"): self._head.append((tag,sorted(attrs)))
        if tag=="meta": self.meta.append(a)
        if tag=="link" and a.get("rel")=="canonical": self.canon.append(a.get("href",""))
        self._atlas_script=tag=="script" and a.get("type")=="application/ld+json" and a.get("data-project-atlas")=="metadata"
    def handle_endtag(self,tag): self._tag=""; self._atlas_script=False
    def handle_data(self,data):
        value=data.strip()
        if not value:return
        if self._tag=="title":self.titles.append(value)
        elif self._tag=="h1":self.h1.append(value)
        elif self._atlas_script:self.scripts.append(value)
        elif self._tag not in ("script","style"):self.visible.append(value)


def _parse_html(html:str)->dict[str,Any]:
    p=_HTML();
    try:p.feed(html)
    except Exception:return {"parse_error":True,"raw_hash":_hash(html)}
    return {"titles":p.titles,"h1":p.h1,"meta":p.meta,"canonicals":p.canon,"atlas_json_ld":p.scripts,"visible_hash":_hash(" ".join(p.visible)),"head_hash":_hash(p._head),"raw_hash":_hash(html)}


def _render_gates(parsed:dict[str,Any],post:dict[str,Any],approved:dict[str,Any])->list[WordPressDraftGateResult]:
    title=((post.get("title") or {}).get("rendered") or ""); excerpt=((post.get("excerpt") or {}).get("rendered") or ""); content=((post.get("content") or {}).get("rendered") or "")
    metas=[(m.get("name") or m.get("property"),m.get("content")) for m in parsed.get("meta",[])]; counts=Counter(k for k,_ in metas)
    required={"description":approved["meta_description"],**approved["open_graph"],**approved["twitter"]}
    exact=all(counts[k]==1 and (k,v) in metas for k,v in required.items())
    try: json_ok=len(parsed.get("atlas_json_ld",[]))==1 and json.loads(parsed["atlas_json_ld"][0])==approved["json_ld"]
    except Exception: json_ok=False
    encoded=json.dumps(parsed,sort_keys=True).lower()
    return [_gate("document_title","Exactly one unchanged title",parsed.get("titles")==[title],"Title duplicate or mismatch."),
        _gate("canonical","Exactly one unchanged canonical",parsed.get("canonicals")==[EXPECTED_URL],"Canonical duplicate or mismatch."),
        _gate("metadata_tags","All required tags appear exactly once",exact,"Metadata tag duplicate/mismatch."),
        _gate("json_ld","Exactly one complete Atlas JSON-LD graph",json_ok,"JSON-LD mismatch."),
        _gate("media_only","Only media 31 is rendered",EXPECTED_MEDIA_URL in encoded and "hero-1.png" not in encoded and '32' not in json.dumps([v for k,v in metas if k and 'image' in k]),"Image safety failed."),
        _gate("h1","Exactly one unchanged H1",len(parsed.get("h1",[]))==1 and parsed["h1"][0] in content,"H1 mismatch."),
        _gate("visible_content","Visible content hash remains bound",bool(parsed.get("visible_hash")) and _hash(content) != _hash(""),"Visible content unavailable."),
        _gate("post_fields","Excerpt/slug/status/URL/featured media unchanged",post.get("excerpt",{}).get("rendered","")==excerpt and post.get("slug")==EXPECTED_SLUG and post.get("status")=="publish" and post.get("link")==EXPECTED_URL and post.get("featured_media")==31,"Core post field changed.")]


def _observe(session:Session,*,include_validation=True,include_html=False)->dict[str,Any]:
    page=session.get(GeneratedPage,41);settings=read_wordpress_settings(session);password=get_wordpress_application_password(); business=session.get(Business,page.business_id) if page else None; image=session.get(ImageMetadata,1)
    result={"page":page,"business":business,"image":image,"settings":settings,"password":password,"plugin":{},"post":{},"media":{},"validation":{},"html":""}
    if settings.site_url and settings.username and password:
        result["plugin"]=_get_json(settings.site_url,settings.username,password,"/wp-json/project-atlas/v1/status");result["post"]=_get_json(settings.site_url,settings.username,password,"/wp-json/wp/v2/pages/8?context=edit");result["media"]=_get_json(settings.site_url,settings.username,password,"/wp-json/wp/v2/media/31?context=edit")
        if include_validation:result["validation"]=_send_json(settings.site_url,settings.username,password,"/wp-json/project-atlas/v1/pages/8/metadata/validate","POST",{"payload":build_orlando_metadata_payload().model_dump(mode="json")})
        if include_html:result["html"]=_get_html(settings.site_url,settings.username,password)
    return result


def _apply_context(session,observed,proof,desired_hash):
    plugin=observed["plugin"];snapshot=plugin.get("snapshot") if isinstance(plugin.get("snapshot"),dict) else plugin;post=observed["post"];state=_metadata_state(session); parsed=_parse_html(observed.get("html", ""))
    core=_core_post_snapshot(post);core["h1"]=parsed.get("h1")
    return {"activation_generation":snapshot.get("activation_generation"),"plugin_revision":snapshot.get("revision"),"metadata_state_id":state.id if state else None,"pre_apply_snapshot_hash":_hash(snapshot),"enabled_state":snapshot.get("rendering_enabled"),"current_payload_hash":snapshot.get("payload_hash"),"rendered_head_hash":parsed.get("head_hash") or snapshot.get("rendered_head_hash"),"visible_content_hash":parsed.get("visible_hash") or _hash((post.get("content") or {}).get("rendered","")),"post_snapshot":core,"desired_payload_hash":desired_hash,"backup":_proof_dict(proof)}


def _backup_gates(proof:WordPressMetadataBackupProof)->list[WordPressDraftGateResult]:
    aware=proof.wordpress_backup_timestamp.tzinfo is not None; ts=proof.wordpress_backup_timestamp.astimezone(UTC) if aware else None;now=datetime.now(UTC)
    return [_data_backup_gate(proof.confirmed_data_backup_file),_gate("atlas_media_backup","Atlas Media Backup identity format validates",_atlas_backup_identity(proof.confirmed_media_backup_identity,"media"),"Expected atlas-media-backup-YYYY-MM-DD-HHMMSS.zip identity."),_gate("atlas_program_backup","Atlas Program Backup identity format validates",_atlas_backup_identity(proof.confirmed_program_backup_identity,"program"),"Expected atlas-program-backup-YYYY-MM-DD-HHMMSS.zip identity."),_gate("wordpress_backup_reference","Durable WordPress backup reference supplied",_valid_identity(proof.wordpress_backup_reference),"Durable reference required."),_gate("wordpress_backup_timezone","Timestamp is timezone-aware",aware,"Timezone required."),_gate("wordpress_backup_not_future","Backup is not future-dated",bool(ts and ts<=now),"Future timestamp rejected."),_gate("wordpress_backup_fresh","Backup is within 24 hours",bool(ts and ts<=now and now-ts<=BACKUP_MAX_AGE),"Stale backup rejected."),_gate("wordpress_database_backup","Database inclusion attested",proof.wordpress_backup_database_included,"Database attestation required."),_gate("wordpress_plugin_backup","Plugin files inclusion attested",proof.wordpress_backup_plugin_files_included,"Plugin attestation required."),_gate("wordpress_restore","Restore capability attested",proof.wordpress_restore_capability_confirmed,"Restore attestation required.")]


def _proof_dict(proof): return proof.model_dump(mode="json",exclude={"confirmation_token","confirmation_phrase"}) if proof else None
def _valid_identity(v): return bool(v and v.strip() and len(v.strip())>=6)
def _atlas_backup_identity(v,kind): return bool(v and re.fullmatch(rf"atlas-{kind}-backup-\d{{4}}-\d{{2}}-\d{{2}}-\d{{6}}\.zip",v.strip()))
def _data_backup_gate(name):
    try: load_backup(resolve_backup_download(name));ok=True
    except (BackupValidationError,OSError,KeyError,TypeError):ok=False
    return _gate("atlas_data_backup","Atlas Data Backup validates",ok,"Data backup missing or invalid.")
def _metadata_state(session): return session.exec(select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id==41)).first()
def _reconcilable_audit(session): return session.exec(select(WordPressMetadataSyncAudit).where(WordPressMetadataSyncAudit.generated_page_id==41,WordPressMetadataSyncAudit.action_type=="apply_metadata",WordPressMetadataSyncAudit.status.in_(["pending","failed","reconciliation_required"])).order_by(WordPressMetadataSyncAudit.attempted_at.desc())).first()
def _finalize_apply(session,audit,revision,payload,payload_hash,returned):
    now=datetime.now(UTC);state=_metadata_state(session) or WordPressMetadataState(generated_page_id=41,wordpress_post_id=8);state.status="applied";state.payload=payload;state.payload_hash=payload_hash;state.wordpress_revision=revision;state.last_verified_at=now;state.last_wordpress_metadata_sync_at=now;audit.status="applied";audit.completed_at=now;audit.returned_snapshot=returned;session.add(state);session.add(audit);session.commit();session.refresh(audit)
def _local_gates(page,business,image,settings,password): return [_gate("orlando_only","Orlando page 41 only",bool(page and page.id==41 and page.wordpress_post_id==8),"Wrong target."),_gate("page_published","Atlas page published",bool(page and page.status=="published" and page.wordpress_status=="publish" and page.page_slug==EXPECTED_SLUG),"Atlas page changed."),_gate("organization","Organization exact",bool(business and business.company_name==ORGANIZATION_NAME and business.phone=="(844) 600-8368" and business.email=="Office@Flo-ZoneTenting.com" and business.license_number=="JB360566" and business.certified_operator=="Jordan Ward"),"Business identity changed."),_gate("media_mapping","Media mapping exact",bool(image and image.wordpress_media_id==31 and image.wordpress_media_url==EXPECTED_MEDIA_URL and image.wordpress_media_checksum==EXPECTED_MEDIA_CHECKSUM),"Media mapping changed."),_gate("credentials","Sandbox credentials available",bool(settings.site_url and settings.username and password and settings.publishing_mode=="sandbox"),"Sandbox credentials required.")]
def _post_fixed(post): return post.get("id")==8 and post.get("status")=="publish" and post.get("slug")==EXPECTED_SLUG and post.get("link")==EXPECTED_URL and post.get("featured_media")==31
def _core_post_snapshot(post): return {"title":post.get("title"),"excerpt":post.get("excerpt"),"slug":post.get("slug"),"status":post.get("status"),"url":post.get("link"),"featured_media":post.get("featured_media")}
def _require_target(page_id):
    if page_id!=41: raise HTTPException(404,"The metadata flow is limited to Orlando page 41.")
def _hash(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
def _sign(action,payload_hash,expires): return _sign_context(action,{"payload_hash":payload_hash},expires)
def _sign_context(action,context,expires):
    body={"action":action,"page_id":41,"wordpress_post_id":8,"media_id":31,"excluded_media_id":32,"plugin_version":PLUGIN_VERSION,"plugin_checksum":PLUGIN_CHECKSUM,"context":context,"bound_state_hash":_hash(context),"payload_hash":context.get("payload_hash") or context.get("desired_payload_hash"),"issued_at":int(datetime.now(UTC).timestamp()),"expires_at":int(expires.timestamp()),"nonce":secrets.token_hex(16)};encoded=base64.urlsafe_b64encode(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).decode().rstrip("=");return f"{encoded}.{hmac.new(_secret,encoded.encode(),hashlib.sha256).hexdigest()}"
def _verify(value,action,page_id):
    try: encoded,signature=value.split(".",1);body=json.loads(base64.urlsafe_b64decode(encoded+"="*(-len(encoded)%4)));assert hmac.compare_digest(signature,hmac.new(_secret,encoded.encode(),hashlib.sha256).hexdigest())
    except Exception: raise HTTPException(422,"The metadata confirmation token is invalid.")
    if body.get("action")!=action or body.get("page_id")!=page_id or body.get("wordpress_post_id")!=8 or body.get("media_id")!=31 or body.get("excluded_media_id")!=32 or body.get("plugin_version")!=PLUGIN_VERSION or body.get("plugin_checksum")!=PLUGIN_CHECKSUM or body.get("bound_state_hash")!=_hash(body.get("context")): raise HTTPException(422,"The token does not match the fixed operation.")
    if int(body.get("expires_at",0))<int(datetime.now(UTC).timestamp()): raise HTTPException(422,"The token expired.")
    return body
def _token_bound_hash(token): return _verify(token,"reconcile_metadata",41)["bound_state_hash"]
def _get_json(site,user,password,path): return _send_json(site,user,password or "",path,"GET",None)
def _send_json(site,user,password,path,method,body):
    try:
        with httpx.Client(timeout=15,follow_redirects=True) as client:r=client.request(method,f"{site.rstrip('/')}{path}",json=body,auth=httpx.BasicAuth(user,password),headers={"Cache-Control":"no-cache","Pragma":"no-cache"})
        if r.status_code>=400:return {"_error":f"HTTP {r.status_code}"}
        value=r.json();return value if isinstance(value,dict) else {"_error":"Non-object response"}
    except (httpx.HTTPError,ValueError) as exc:return {"_error":exc.__class__.__name__}
def _get_html(site,user,password):
    try:
        with httpx.Client(timeout=15,follow_redirects=True) as client:r=client.get(f"{site.rstrip('/')}/drywood-termite-tenting-orlando-fl/?atlas_verify={secrets.token_hex(8)}",auth=httpx.BasicAuth(user,password),headers={"Cache-Control":"no-cache, no-store","Pragma":"no-cache"})
        return r.text if r.status_code<400 else ""
    except httpx.HTTPError:return ""
def _gate(code,label,passed,message): return WordPressDraftGateResult(code=code,label=label,passed=passed,message=message)
