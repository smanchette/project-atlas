from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session, select

from app.db.session import engine
from app.main import app
from app.models import GeneratedPage
from app.schemas.wordpress import WordPressHeadingContract
from app.services.wordpress_heading_contract import (
    CURRENT_HEADING_FRAGMENT,
    EXPECTED_TITLE,
    EXPECTED_URL,
    FORBIDDEN_REQUEST_FIELDS,
    PROPOSED_HEADING_FRAGMENT,
    build_orlando_heading_correction_dry_run,
    propose_orlando_body_correction,
    wordpress_body_hash,
)
from app.services import wordpress_heading_contract as heading_service
from app.services.wordpress_sandbox import _content_html, wordpress_heading_contract


def _page_by_slug(session: Session, slug: str) -> GeneratedPage:
    page = session.exec(select(GeneratedPage).where(GeneratedPage.page_slug == slug)).one()
    assert page.id is not None
    return page


def _orlando_preview() -> tuple[GeneratedPage, dict]:
    with TestClient(app) as client, Session(engine) as session:
        page = _page_by_slug(session, "drywood-termite-tenting-orlando-fl")
        response = client.get(f"/api/wordpress/pages/{page.id}/payload-preview")
        assert response.status_code == 200
        session.expunge(page)
        return page, response.json()


def _locked_page_rest(current_body: str) -> dict:
    return {
        "id": 8,
        "status": "publish",
        "title": {"raw": EXPECTED_TITLE, "rendered": EXPECTED_TITLE},
        "slug": "drywood-termite-tenting-orlando-fl",
        "link": EXPECTED_URL,
        "featured_media": 31,
        "content": {"raw": current_body, "rendered": current_body},
    }


def _rendered_page(current_body: str) -> str:
    return (
        '<body class="page-template-default wp-theme-twentytwentyfive">'
        '<main><div class="wp-block-group">'
        f'<h1 class="wp-block-post-title">{EXPECTED_TITLE}</h1>'
        f'<div class="entry-content wp-block-post-content">{current_body}</div>'
        "</div></main></body>"
    )


def test_explicit_heading_contract_validates_template_ownership() -> None:
    assert wordpress_heading_contract(41) == WordPressHeadingContract(
        policy_id="template_post_title_owns_primary_h1",
        template_renders_primary_h1=True,
        body_heading_level=2,
    )
    default = wordpress_heading_contract(999999)
    assert default.template_renders_primary_h1 is False
    assert default.body_heading_level == 1
    with pytest.raises(ValidationError):
        WordPressHeadingContract(
            policy_id="invalid",
            template_renders_primary_h1=True,
            body_heading_level=1,
        )


def test_orlando_payload_uses_h2_without_rewriting_semantic_data() -> None:
    page, preview = _orlando_preview()
    content = preview["payload"]["content"]
    assert preview["heading_contract"] == {
        "policy_id": "template_post_title_owns_primary_h1",
        "template_renders_primary_h1": True,
        "body_heading_level": 2,
    }
    assert content.startswith(PROPOSED_HEADING_FRAGMENT)
    assert not content.startswith(CURRENT_HEADING_FRAGMENT)
    assert preview["payload"]["title"] == EXPECTED_TITLE
    assert preview["export_package"]["h1"] == "Drywood Termite Tenting in Orlando, Florida"
    assert page.page_title == EXPECTED_TITLE
    assert page.h1 == "Drywood Termite Tenting in Orlando, Florida"
    if page.draft_content is not None:
        assert page.draft_content["title"] == EXPECTED_TITLE
        assert page.draft_content["h1"] == "Drywood Termite Tenting in Orlando, Florida"


def test_renderer_does_not_mutate_page_title_or_h1_data() -> None:
    package = {
        "page_title": EXPECTED_TITLE,
        "h1": "Drywood Termite Tenting in Orlando, Florida",
        "content_sections": {"intro": "Body"},
        "faq_items": [],
        "cta_block": "",
    }
    before = deepcopy(package)
    content = _content_html(package, heading_contract=wordpress_heading_contract(41))
    assert content.startswith(PROPOSED_HEADING_FRAGMENT)
    assert package == before


def test_tag_change_preserves_all_following_body_content() -> None:
    _, preview = _orlando_preview()
    proposed = preview["payload"]["content"]
    current = CURRENT_HEADING_FRAGMENT + proposed[len(PROPOSED_HEADING_FRAGMENT) :]
    assert propose_orlando_body_correction(current) == proposed
    assert current[len(CURRENT_HEADING_FRAGMENT) :] == proposed[len(PROPOSED_HEADING_FRAGMENT) :]
    assert current.count("Drywood Termite Tenting in Orlando, Florida") == proposed.count(
        "Drywood Termite Tenting in Orlando, Florida"
    )


def test_orlando_guarded_plan_is_content_only_and_hash_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, preview = _orlando_preview()
    proposed = preview["payload"]["content"]
    current = CURRENT_HEADING_FRAGMENT + proposed[len(PROPOSED_HEADING_FRAGMENT) :]
    fixture_hash = wordpress_body_hash(current)
    monkeypatch.setattr(heading_service, "EXPECTED_CURRENT_BODY_HASH", fixture_hash)
    result = build_orlando_heading_correction_dry_run(
        _locked_page_rest(current),
        _rendered_page(current),
    )
    assert result.ready is True
    assert result.status == "dry_run_ready"
    assert result.current_body_hash == fixture_hash
    assert result.proposed_body_hash == wordpress_body_hash(proposed)
    assert result.request_payload == {"content": proposed}
    assert set(result.request_payload).isdisjoint(FORBIDDEN_REQUEST_FIELDS)
    assert result.token_issued is False and result.nonce_consumed is False
    assert result.audit_created is False
    assert result.wordpress_write_count == 0 and result.atlas_write_count == 0
    assert all(gate.passed for gate in result.gate_results)


@pytest.mark.parametrize(
    ("mutation", "failed_gate"),
    [
        ("status", "status"),
        ("title", "title"),
        ("slug", "slug"),
        ("url", "url"),
        ("featured", "featured_media"),
        ("body", "body_hash"),
        ("one_h1", "two_h1"),
        ("wrong_first", "theme_h1_first"),
        ("wrong_second", "atlas_h1_second"),
    ],
)
def test_orlando_guarded_plan_fails_closed_on_drift(mutation: str, failed_gate: str) -> None:
    _, preview = _orlando_preview()
    proposed = preview["payload"]["content"]
    current = CURRENT_HEADING_FRAGMENT + proposed[len(PROPOSED_HEADING_FRAGMENT) :]
    rest = _locked_page_rest(current)
    rendered = _rendered_page(current)
    if mutation == "status":
        rest["status"] = "draft"
    elif mutation == "title":
        rest["title"] = {"raw": "Changed"}
    elif mutation == "slug":
        rest["slug"] = "changed"
    elif mutation == "url":
        rest["link"] = "https://www.drywoodtenting.com/changed/"
    elif mutation == "featured":
        rest["featured_media"] = 32
    elif mutation == "body":
        rest["content"] = {"raw": current + "<p>Drift</p>"}
    elif mutation == "one_h1":
        rendered = rendered.replace(CURRENT_HEADING_FRAGMENT, PROPOSED_HEADING_FRAGMENT)
    elif mutation == "wrong_first":
        rendered = rendered.replace('class="wp-block-post-title"', 'class="wp-block-heading"')
    elif mutation == "wrong_second":
        rendered = rendered.replace("entry-content wp-block-post-content", "other-content")
    result = build_orlando_heading_correction_dry_run(rest, rendered)
    assert result.ready is False and result.status == "blocked"
    gates = {gate.code: gate.passed for gate in result.gate_results}
    assert gates[failed_gate] is False


def test_other_pages_keep_h1_until_they_receive_an_explicit_contract() -> None:
    with TestClient(app) as client, Session(engine) as session:
        page = session.exec(
            select(GeneratedPage)
            .where(GeneratedPage.id != 41, GeneratedPage.h1.is_not(None))
            .order_by(GeneratedPage.id)
        ).first()
        assert page and page.id is not None
        response = client.get(f"/api/wordpress/pages/{page.id}/payload-preview")
    assert response.status_code == 200
    preview = response.json()
    assert preview["heading_contract"]["policy_id"] == "body_owns_primary_h1"
    assert preview["heading_contract"]["template_renders_primary_h1"] is False
    assert preview["payload"]["content"].startswith(f"<h1>{preview['export_package']['h1']}</h1>")


def test_heading_contract_uses_no_theme_css_workaround() -> None:
    root = Path(__file__).resolve().parents[1]
    renderer = (root / "app/services/wordpress_sandbox.py").read_text(encoding="utf-8")
    assert "twentytwentyfive" not in renderer.lower()
    assert "display:none" not in renderer.replace(" ", "").lower()
    assert "visibility:hidden" not in renderer.replace(" ", "").lower()
