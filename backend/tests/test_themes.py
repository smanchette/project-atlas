from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.session import get_session
from app.main import app
from app.models import Brand, Business, Theme, Website, WebsiteThemeSelection
from app.schemas.themes import ThemeCreate
from app.services.themes import (
    DEFAULT_THEME_TOKENS,
    ThemeError,
    approve_theme,
    canonical_token_hash,
    create_theme,
    resolve_website_theme,
    retire_theme,
    select_website_theme,
    validate_theme_accessibility,
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


def _website(session: Session, suffix: str) -> Website:
    business = Business(
        company_name=f"Company {suffix}",
        business_type="test",
        state="FL",
    )
    session.add(business)
    session.commit()
    session.refresh(business)
    brand = Brand(
        business_id=business.id,
        brand_name=f"Brand {suffix}",
        status="active",
    )
    session.add(brand)
    session.commit()
    session.refresh(brand)
    website = Website(
        business_id=business.id,
        brand_id=brand.id,
        website_name=f"Website {suffix}",
        domain=f"{suffix.lower()}.example.test",
        public_url=f"https://{suffix.lower()}.example.test",
        status="active",
    )
    session.add(website)
    session.commit()
    session.refresh(website)
    return website


def _payload(*, replaces_theme_id: int | None = None) -> ThemeCreate:
    return ThemeCreate(
        theme_key="governed-default",
        theme_name="Governed Default",
        description="A test-only governed Theme.",
        token_contract_version=1,
        design_tokens=DEFAULT_THEME_TOKENS.model_copy(deep=True),
        created_by="Theme Operator",
        provenance_type="operator_configured",
        provenance_notes="Configured from approved Website presentation decisions.",
        replaces_theme_id=replaces_theme_id,
    )


def _same_business_website(session: Session, source: Website, suffix: str) -> Website:
    brand = Brand(
        business_id=source.business_id,
        brand_name=f"Brand {suffix}",
        status="active",
    )
    session.add(brand)
    session.commit()
    session.refresh(brand)
    website = Website(
        business_id=source.business_id,
        brand_id=brand.id,
        website_name=f"Website {suffix}",
        domain=f"{suffix.lower()}.example.test",
        public_url=f"https://{suffix.lower()}.example.test",
        status="active",
    )
    session.add(website)
    session.commit()
    session.refresh(website)
    return website


def test_neutral_fallback_is_deterministic_accessible_and_nonpersistent(session: Session) -> None:
    website = _website(session, "Fallback")

    first = resolve_website_theme(session, website.id)
    second = resolve_website_theme(session, website.id)

    assert first.fallback_used is True
    assert first.theme is None
    assert first.selection is None
    assert first.accessibility.valid is True
    assert first.source_identity == second.source_identity
    assert first.source_identity["mode"] == "neutral_fallback"
    assert first.source_identity["token_hash_sha256"] == canonical_token_hash(DEFAULT_THEME_TOKENS)
    assert session.exec(select(Theme)).all() == []
    assert session.exec(select(WebsiteThemeSelection)).all() == []


def test_theme_approval_selection_and_exact_retries_are_idempotent(session: Session) -> None:
    website = _website(session, "Primary")
    theme = create_theme(session, website.id, _payload())

    approved = approve_theme(session, theme.id, approved_by="Approver")
    approved_again = approve_theme(session, theme.id, approved_by="Approver")
    assert approved_again.id == approved.id
    assert approved_again.approved_at == approved.approved_at

    selection = select_website_theme(
        session,
        website.id,
        theme_id=theme.id,
        selected_by="Selector",
        rationale="Use the approved Website Theme.",
    )
    selection_again = select_website_theme(
        session,
        website.id,
        theme_id=theme.id,
        selected_by="Selector",
        rationale="Use the approved Website Theme.",
    )
    assert selection_again.id == selection.id
    assert len(session.exec(select(WebsiteThemeSelection)).all()) == 1

    resolved = resolve_website_theme(session, website.id)
    assert resolved.fallback_used is False
    assert resolved.source_identity == {
        "mode": "selected",
        "website_id": website.id,
        "theme_id": theme.id,
        "theme_key": "governed-default",
        "theme_version": 1,
        "token_contract_version": 1,
        "token_hash_sha256": theme.token_hash_sha256,
        "selection_id": selection.id,
        "selection_version": 1,
    }


def test_replacement_history_retirement_and_website_isolation(session: Session) -> None:
    first_website = _website(session, "First")
    second_website = _same_business_website(session, first_website, "SecondBrand")
    first = create_theme(session, first_website.id, _payload())
    approve_theme(session, first.id, approved_by="Approver")

    with pytest.raises(ThemeError, match="does not belong"):
        select_website_theme(
            session,
            second_website.id,
            theme_id=first.id,
            selected_by="Selector",
            rationale="Invalid cross-Website selection.",
        )

    select_website_theme(
        session,
        first_website.id,
        theme_id=first.id,
        selected_by="Selector",
        rationale="Select version one.",
    )
    replacement = create_theme(
        session,
        first_website.id,
        _payload(replaces_theme_id=first.id),
    )
    approve_theme(session, replacement.id, approved_by="Approver")
    select_website_theme(
        session,
        first_website.id,
        theme_id=replacement.id,
        selected_by="Selector",
        rationale="Select approved replacement.",
    )

    history = session.exec(
        select(WebsiteThemeSelection)
        .where(WebsiteThemeSelection.website_id == first_website.id)
        .order_by(WebsiteThemeSelection.version)
    ).all()
    assert [(item.version, item.status, item.theme_id) for item in history] == [
        (1, "replaced", first.id),
        (2, "active", replacement.id),
    ]
    retired = retire_theme(
        session,
        first.id,
        retired_by="Retirement Operator",
        rationale="Version one was replaced.",
    )
    retired_again = retire_theme(
        session,
        first.id,
        retired_by="Retirement Operator",
        rationale="Version one was replaced.",
    )
    assert retired_again.id == retired.id
    assert retired_again.retired_at == retired.retired_at
    with pytest.raises(ThemeError, match="active Website Theme"):
        retire_theme(
            session,
            replacement.id,
            retired_by="Retirement Operator",
            rationale="Cannot retire an active Theme.",
        )


def test_contrast_failure_blocks_approval_and_token_tampering_fails_closed(session: Session) -> None:
    website = _website(session, "Contrast")
    low_contrast = deepcopy(DEFAULT_THEME_TOKENS.model_dump(mode="json"))
    low_contrast["colors"]["text"] = low_contrast["colors"]["background"]
    payload_data = _payload().model_dump(mode="json")
    payload_data["design_tokens"] = low_contrast
    payload = ThemeCreate.model_validate(payload_data)
    theme = create_theme(session, website.id, payload)

    result = validate_theme_accessibility(payload.design_tokens)
    assert result.valid is False
    assert any("body_text_on_background" in item for item in result.failures)
    with pytest.raises(ThemeError, match="accessibility validation"):
        approve_theme(session, theme.id, approved_by="Approver")

    valid_theme = create_theme(
        session,
        website.id,
        _payload().model_copy(update={"theme_key": "tamper-test"}),
    )
    valid_theme.token_hash_sha256 = "0" * 64
    session.add(valid_theme)
    session.commit()
    with pytest.raises(ThemeError, match="token hash"):
        approve_theme(session, valid_theme.id, approved_by="Approver")


def test_operator_api_create_approve_select_list_and_resolve_contract() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as setup:
        website = _website(setup, "Api")
        website_id = website.id

    def override_session():
        with Session(engine) as value:
            yield value

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        create_response = client.post(
            f"/api/websites/{website_id}/themes",
            json=_payload().model_dump(mode="json"),
        )
        assert create_response.status_code == 201, create_response.text
        created = create_response.json()
        assert created["approval_status"] == "pending_review"
        assert created["lifecycle_status"] == "draft"

        approve_response = client.post(
            f"/api/themes/{created['id']}/approve",
            json={"approved_by": "API Approver"},
        )
        assert approve_response.status_code == 200, approve_response.text
        assert approve_response.json()["approval_status"] == "approved"

        select_response = client.post(
            f"/api/websites/{website_id}/theme-selection",
            json={
                "theme_id": created["id"],
                "selected_by": "API Selector",
                "rationale": "Use the approved governed Theme.",
            },
        )
        assert select_response.status_code == 201, select_response.text
        assert select_response.json()["status"] == "active"

        list_response = client.get(f"/api/websites/{website_id}/themes")
        assert list_response.status_code == 200
        assert [item["id"] for item in list_response.json()] == [created["id"]]

        resolve_response = client.get(f"/api/websites/{website_id}/theme")
        assert resolve_response.status_code == 200, resolve_response.text
        resolved = resolve_response.json()
        assert resolved["fallback_used"] is False
        assert resolved["theme"]["id"] == created["id"]
        assert resolved["source_identity"]["mode"] == "selected"
        assert resolved["accessibility"]["valid"] is True

        state_response = client.get(f"/api/websites/{website_id}/theme-selection")
        assert state_response.status_code == 200
        assert len(state_response.json()["history"]) == 1
    finally:
        client.close()
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()
