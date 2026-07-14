from __future__ import annotations

from datetime import UTC, datetime, timedelta
import inspect

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session, select

from app.db.session import engine
from app.main import app
from app.models import GeneratedPage, WordPressHeadingCorrectionAudit
from app.schemas.wordpress import (
    WordPressHeadingCorrectionApplyRequest,
    WordPressHeadingCorrectionBackupIdentities,
    WordPressHeadingCorrectionDryRunRequest,
    WordPressHeadingCorrectionReconcileRequest,
    WordPressHeadingCorrectionVerifyRequest,
)
from app.services import wordpress_heading_correction as correction
from app.services import wordpress_heading_contract as heading_contract_service
from app.services.wordpress_heading_contract import (
    CURRENT_HEADING_FRAGMENT,
    EXPECTED_CURRENT_BODY_HASH,
    EXPECTED_TITLE,
    EXPECTED_URL,
    PROPOSED_HEADING_FRAGMENT,
    wordpress_body_hash,
)
from app.services.wordpress_sandbox import build_wordpress_payload_preview


def _backups(offset_seconds: int = 0) -> WordPressHeadingCorrectionBackupIdentities:
    stamp = (datetime.now(UTC) + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%d-%H%M%S")
    return WordPressHeadingCorrectionBackupIdentities(
        data_backup_file_name=f"atlas-backup-{stamp}.json",
        media_backup_file_name=f"atlas-media-backup-{stamp}.zip",
        program_backup_file_name=f"atlas-program-backup-{stamp}.zip",
    )


def _bodies(session: Session) -> tuple[str, str]:
    proposed = build_wordpress_payload_preview(session, 41).payload.content
    assert proposed.startswith(PROPOSED_HEADING_FRAGMENT)
    current = CURRENT_HEADING_FRAGMENT + proposed[len(PROPOSED_HEADING_FRAGMENT) :]
    assert wordpress_body_hash(current) == correction.EXPECTED_CURRENT_BODY_HASH
    assert wordpress_body_hash(proposed) == correction.EXPECTED_PROPOSED_BODY_HASH
    return current, proposed


def _observation(body: str, *, corrected: bool) -> dict:
    page = {
        "id": 8,
        "status": "publish",
        "title": {"raw": EXPECTED_TITLE, "rendered": EXPECTED_TITLE},
        "slug": "drywood-termite-tenting-orlando-fl",
        "link": EXPECTED_URL,
        "excerpt": {"raw": "Locked excerpt", "rendered": "Locked excerpt"},
        "featured_media": 31,
        "content": {"raw": body, "rendered": body},
    }
    theme_h1 = f'<h1 class="wp-block-post-title">{EXPECTED_TITLE}</h1>'
    html = (
        '<html><head><title>Drywood Termite Tenting in Orlando, FL – My WordPress</title>'
        f'<link rel="canonical" href="{EXPECTED_URL}"></head><body>'
        f'{theme_h1}<div class="entry-content wp-block-post-content">{body}'
        '<img class="wp-image-31" src="https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png">'
        "</div></body></html>"
    )
    snapshot = {
        "page": correction._page_snapshot(page),
        "media_31": {"id": 31, "status": "inherit", "slug": "orlando-hero", "source_url": "hero.png", "alt_text": "Hero", "modified_gmt": "2026-07-12T00:00:00"},
        "media_32": {"status_code": 404},
        "rendered": correction._rendered_snapshot(html, {"cache-control": "max-age=0"}),
    }
    expected_h1_count = 1 if corrected else 2
    assert len(snapshot["rendered"]["h1_texts"]) == expected_h1_count
    return {"page": page, "rendered_html": html, "snapshot": snapshot}


@pytest.fixture
def guarded(monkeypatch: pytest.MonkeyPatch):
    with TestClient(app):
        with Session(engine) as session:
            proposed = build_wordpress_payload_preview(session, 41).payload.content
            page = session.get(GeneratedPage, 41)
            assert page is not None
            original_post_id = page.wordpress_post_id
            page.wordpress_post_id = 8
            session.add(page)
            session.commit()
        current = CURRENT_HEADING_FRAGMENT + proposed[len(PROPOSED_HEADING_FRAGMENT) :]
        current_hash = wordpress_body_hash(current)
        proposed_hash = wordpress_body_hash(proposed)
        monkeypatch.setattr(correction, "EXPECTED_CURRENT_BODY_HASH", current_hash)
        monkeypatch.setattr(correction, "EXPECTED_PROPOSED_BODY_HASH", proposed_hash)
        monkeypatch.setattr(heading_contract_service, "EXPECTED_CURRENT_BODY_HASH", current_hash)
        monkeypatch.setattr(correction, "_release_identity", lambda: ({"atlas_version": "v0.59.19", "atlas_commit": "7" * 40, "atlas_tag": "v0.59.19", "runtime_identity_verified": True}, None))
        monkeypatch.setattr(correction, "read_wordpress_settings", lambda _session: type("S", (), {"site_url": "https://example.test", "username": "operator"})())
        monkeypatch.setattr(correction, "get_wordpress_application_password", lambda: "process-memory-only")
        yield
        with Session(engine) as session:
            page = session.get(GeneratedPage, 41)
            assert page is not None
            page.wordpress_post_id = original_post_id
            session.add(page)
            session.commit()


def test_routes_are_separate_and_scoped() -> None:
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    for suffix in ("dry-run", "apply", "verify", "reconcile"):
        assert (f"/api/wordpress/heading-correction/{suffix}/{{page_id}}", "POST") in routes


def test_production_body_hashes_are_exactly_locked() -> None:
    assert EXPECTED_CURRENT_BODY_HASH == "1144c89c046bfd74d3381560afdc5b7ec81f9a01e6de73fa929f2dc3b7ef7705"
    assert correction.EXPECTED_PROPOSED_BODY_HASH == "c031a7aa841b8e9a0316956dd3bf25178f390e64d01ceb9d9cd4273cc4aed195"


def test_dry_run_requires_exact_hashes_and_signs_locked_context(
    guarded, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        current, proposed = _bodies(session)
        monkeypatch.setattr(correction, "_observe", lambda *_: _observation(current, corrected=False))
        result = correction.dry_run_heading_correction(
            session, 41, WordPressHeadingCorrectionDryRunRequest(backups=_backups())
        )
    assert result.ready and result.token_issued, [(g.code, g.message) for g in result.gate_results if not g.passed]
    assert result.current_body_hash == correction.EXPECTED_CURRENT_BODY_HASH
    assert result.proposed_body_hash == correction.EXPECTED_PROPOSED_BODY_HASH
    assert result.request_payload == {"content": proposed}
    assert result.confirmation_phrase == correction.CONFIRMATION_PHRASE
    assert result.audit_created is False and result.wordpress_write_count == 0
    token = correction._verify_token(result.confirmation_token or "", 41)
    assert token["backup_digest"] == correction._digest(result.backup_identities.model_dump(mode="json"))


def test_dry_run_blocks_wrong_page_post_and_body_hash(
    guarded, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        current, _ = _bodies(session)
        drifted = _observation(current + "<p>drift</p>", corrected=False)
        monkeypatch.setattr(correction, "_observe", lambda *_: drifted)
        result = correction.dry_run_heading_correction(
            session, 41, WordPressHeadingCorrectionDryRunRequest(backups=_backups())
        )
        assert not result.ready
        assert {g.code: g.passed for g in result.gate_results}["body_hash"] is False
        with pytest.raises(HTTPException):
            correction.verify_heading_correction(session, 42, WordPressHeadingCorrectionVerifyRequest())


def test_dry_run_requires_the_exact_proposed_hash(
    guarded, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        current, _ = _bodies(session)
        monkeypatch.setattr(correction, "_observe", lambda *_: _observation(current, corrected=False))
        monkeypatch.setattr(correction, "EXPECTED_PROPOSED_BODY_HASH", "0" * 64)
        result = correction.dry_run_heading_correction(session, 41, WordPressHeadingCorrectionDryRunRequest(backups=_backups()))
    assert {gate.code: gate.passed for gate in result.gate_results}["proposed_body_hash"] is False
    assert result.confirmation_token is None


def test_apply_sends_exactly_one_content_only_request_and_preserves_protected_fields(
    guarded, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict] = []
    with Session(engine) as session:
        current, proposed = _bodies(session)
        observations = iter((_observation(current, corrected=False), _observation(current, corrected=False), _observation(proposed, corrected=True)))
        monkeypatch.setattr(correction, "_observe", lambda *_: next(observations))
        dry = correction.dry_run_heading_correction(session, 41, WordPressHeadingCorrectionDryRunRequest(backups=_backups()))

        class Response:
            status_code = 200
            def json(self): return _observation(proposed, corrected=True)["page"]
        class Client:
            def __init__(self, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def post(self, url, *, json, auth):
                sent.append({"url": url, "json": json, "auth_type": type(auth).__name__})
                return Response()
        monkeypatch.setattr(correction.httpx, "Client", Client)
        result = correction.apply_heading_correction(
            session,
            41,
            WordPressHeadingCorrectionApplyRequest(
                backups=dry.backup_identities,
                confirmation_token=dry.confirmation_token,
                confirmation_phrase=correction.CONFIRMATION_PHRASE,
            ),
        )
        audit = session.get(WordPressHeadingCorrectionAudit, result.audit_id)
    assert len(sent) == 1
    assert sent[0]["json"] == {"content": proposed}
    assert set(sent[0]["json"]) == {"content"}
    assert audit and audit.status == "corrected" and audit.wordpress_write_count == 1
    assert result.automatic_retry_count == 0


def test_backup_change_and_stale_token_block_before_write(
    guarded, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        current, _ = _bodies(session)
        monkeypatch.setattr(correction, "_observe", lambda *_: _observation(current, corrected=False))
        first = _backups()
        dry = correction.dry_run_heading_correction(session, 41, WordPressHeadingCorrectionDryRunRequest(backups=first))
        with pytest.raises(HTTPException) as changed:
            correction.apply_heading_correction(session, 41, WordPressHeadingCorrectionApplyRequest(backups=_backups(1), confirmation_token=dry.confirmation_token, confirmation_phrase=correction.CONFIRMATION_PHRASE))
        assert changed.value.status_code == 409
        expired = correction._sign({
            "action": "correct_orlando_duplicate_h1", "atlas_page_id": 41,
            "wordpress_post_id": 8, "expires_at": int((datetime.now(UTC) - timedelta(seconds=1)).timestamp()),
        })
        with pytest.raises(HTTPException) as stale:
            correction.apply_heading_correction(session, 41, WordPressHeadingCorrectionApplyRequest(backups=first, confirmation_token=expired, confirmation_phrase=correction.CONFIRMATION_PHRASE))
        assert stale.value.status_code == 422


def test_wordpress_success_atlas_failure_uses_read_only_reconciliation(
    guarded, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        current, proposed = _bodies(session)
        observations = iter((_observation(current, corrected=False), _observation(current, corrected=False), _observation(proposed, corrected=True)))
        monkeypatch.setattr(correction, "_observe", lambda *_: next(observations))
        dry = correction.dry_run_heading_correction(session, 41, WordPressHeadingCorrectionDryRunRequest(backups=_backups()))
        class Response:
            status_code = 200
            def json(self): return _observation(proposed, corrected=True)["page"]
        class Client:
            def __init__(self, **_kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def post(self, *_args, **_kwargs): return Response()
        monkeypatch.setattr(correction.httpx, "Client", Client)
        real_commit = session.commit
        calls = 0
        def flaky_commit():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic Atlas finalization failure")
            real_commit()
        monkeypatch.setattr(session, "commit", flaky_commit)
        with pytest.raises(HTTPException) as failed:
            correction.apply_heading_correction(session, 41, WordPressHeadingCorrectionApplyRequest(backups=dry.backup_identities, confirmation_token=dry.confirmation_token, confirmation_phrase=correction.CONFIRMATION_PHRASE))
        assert failed.value.status_code == 500
        audit_id = failed.value.detail["audit_id"]
        audit = session.get(WordPressHeadingCorrectionAudit, audit_id)
        assert audit and audit.status == "reconciliation_required" and audit.wordpress_write_count == 1
        monkeypatch.setattr(correction, "_observe", lambda *_: _observation(proposed, corrected=True))
        result = correction.reconcile_heading_correction(session, 41, WordPressHeadingCorrectionReconcileRequest(audit_id=audit_id, confirmation_phrase=correction.RECONCILIATION_PHRASE))
        assert result.status == "verified" and result.wordpress_write_count == 0


def test_verify_requires_one_h1_exact_h2_and_unchanged_media(
    guarded, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        current, proposed = _bodies(session)
        pre = _observation(current, corrected=False)["snapshot"]
        post = _observation(proposed, corrected=True)
        monkeypatch.setattr(correction, "_observe", lambda *_: post)
        audit = WordPressHeadingCorrectionAudit(
            generated_page_id=41, wordpress_post_id=8, status="reconciliation_required",
            wordpress_site_url="https://example.test", current_body_hash=correction.EXPECTED_CURRENT_BODY_HASH,
            proposed_body_hash=correction.EXPECTED_PROPOSED_BODY_HASH, token_fingerprint="a" * 64,
            backup_identities=_backups().model_dump(mode="json"), release_identity={"verified": True},
            pre_snapshot=pre, gate_results=[], wordpress_write_count=1,
        )
        session.add(audit); session.commit(); session.refresh(audit)
        result = correction.verify_heading_correction(session, 41, WordPressHeadingCorrectionVerifyRequest(audit_id=audit.id))
    assert result.verified and result.status == "reconciliation_ready"
    assert result.rendered_h1_count == 1 and result.rendered_h1_text == correction.EXPECTED_RENDERED_H1
    assert result.cache_purge_count == 0 and result.wordpress_write_count == 0


def test_verify_blocks_any_media_change(
    guarded, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        current, proposed = _bodies(session)
        pre = _observation(current, corrected=False)["snapshot"]
        post = _observation(proposed, corrected=True)
        post["snapshot"]["media_31"]["modified_gmt"] = "2026-07-14T01:02:03"
        result = correction._verify_corrected_observation(post, pre, None)
    assert not result.verified
    assert {gate.code: gate.passed for gate in result.gate_results}["media_31"] is False


def test_seven_other_drafts_remain_byte_for_byte_unchanged(
    guarded, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        others = session.exec(select(GeneratedPage).where(GeneratedPage.id != 41).order_by(GeneratedPage.id).limit(7)).all()
        before = [(p.id, p.page_title, p.h1, p.draft_content) for p in others]
        other_ids = [p.id for p in others]
        current, _ = _bodies(session)
        monkeypatch.setattr(correction, "_observe", lambda *_: _observation(current, corrected=False))
        correction.dry_run_heading_correction(session, 41, WordPressHeadingCorrectionDryRunRequest(backups=_backups()))
        after = [(p.id, p.page_title, p.h1, p.draft_content) for p in session.exec(select(GeneratedPage).where(GeneratedPage.id.in_(other_ids)).order_by(GeneratedPage.id)).all()]
    assert len(before) == 7 and after == before


def test_apply_source_has_one_post_no_retry_and_forbids_protected_payload_fields() -> None:
    source = inspect.getsource(correction.apply_heading_correction)
    assert source.count("client.post(") == 1
    assert "while " not in source and "for attempt" not in source
    assert 'WordPressHeadingContentPayload(**dry.request_payload)' in source
    for field in ("title", "slug", "status", "excerpt", "featured_media", "template", "parent", "menu_order", "metadata"):
        assert f'"{field}":' not in source


def test_apply_request_and_wordpress_payload_reject_protected_fields() -> None:
    with pytest.raises(ValidationError):
        correction.WordPressHeadingContentPayload(content="<h2>Safe</h2>", title="Forbidden")
    with pytest.raises(ValidationError):
        WordPressHeadingCorrectionApplyRequest(
            backups=_backups(),
            confirmation_token="x" * 40,
            confirmation_phrase=correction.CONFIRMATION_PHRASE,
            featured_media=31,
        )
