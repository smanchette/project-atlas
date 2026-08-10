from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import page_media_planning_routes
from app.db.session import get_session
from app.schemas.scoped_media_authorizations import ScopedMediaAuthorizationRead


NOW = datetime(2026, 8, 10, 16, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _serialized_authorization() -> ScopedMediaAuthorizationRead:
    return ScopedMediaAuthorizationRead(
        id=901,
        website_id=11,
        site_plan_id=21,
        planned_page_id=31,
        generated_page_id=41,
        media_requirement_id=51,
        requirement_version=3,
        placement_key="city-service-hero",
        placement_contract_version=2,
        image_metadata_id=61,
        media_version=4,
        asset_checksum_sha256=SHA_A,
        approval_version=2,
        asset_approved_by="Asset Approver",
        asset_approved_at=NOW,
        approval_fingerprint=SHA_B,
        page_image_assignment_id=71,
        assignment_version=5,
        reuse_policy="requirement_only",
        authorization_terms=[
            "no_reuse",
            "representative_nonlocalized",
            "visible_branding_allowed",
        ],
        authorized_by="Usage Approver",
        authorization_rationale="Approved for this exact governed requirement only.",
        authorized_at=NOW,
        authorization_version=1,
        authorization_fingerprint=SHA_C,
        lifecycle_status="current",
        supersedes_authorization_id=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _app(session_sentinel: object) -> FastAPI:
    app = FastAPI()
    app.include_router(page_media_planning_routes.router, prefix="/api")
    app.dependency_overrides[get_session] = lambda: session_sentinel
    return app


def test_scoped_authorization_post_and_get_serialize_exact_typed_evidence(
    monkeypatch,
) -> None:
    session_sentinel = object()
    durable = _serialized_authorization()
    calls: list[tuple[str, object, int, object]] = []

    def create_stub(session, plan_id, payload):
        calls.append(("post", session, plan_id, payload))
        return durable

    def list_stub(
        session,
        plan_id,
        *,
        media_requirement_id=None,
        image_metadata_id=None,
    ):
        calls.append(
            (
                "get",
                session,
                plan_id,
                (media_requirement_id, image_metadata_id),
            )
        )
        return [durable]

    monkeypatch.setattr(
        page_media_planning_routes,
        "create_scoped_media_authorization",
        create_stub,
    )
    monkeypatch.setattr(
        page_media_planning_routes,
        "list_scoped_media_authorizations",
        list_stub,
    )

    request_payload = {
        "media_requirement_id": 51,
        "expected_requirement_version": 3,
        "expected_placement_contract_version": 2,
        "image_metadata_id": 61,
        "expected_media_version": 4,
        "expected_asset_checksum_sha256": SHA_A,
        "expected_approval_version": 2,
        "expected_approval_fingerprint": SHA_B,
        "page_image_assignment_id": 71,
        "expected_assignment_version": 5,
        "reuse_policy": "requirement_only",
        "authorization_terms": [
            "visible_branding_allowed",
            "representative_nonlocalized",
            "no_reuse",
        ],
        "authorized_by": "Usage Approver",
        "authorization_rationale": (
            "Approved for this exact governed requirement only."
        ),
    }

    with TestClient(_app(session_sentinel)) as client:
        post_response = client.post(
            "/api/site-plans/21/page-media/authorizations",
            json=request_payload,
        )
        get_response = client.get(
            "/api/site-plans/21/page-media/authorizations",
            params={
                "media_requirement_id": 51,
                "image_metadata_id": 61,
            },
        )

    assert post_response.status_code == 201
    assert get_response.status_code == 200
    expected_json = durable.model_dump(mode="json")
    assert post_response.json() == expected_json
    assert get_response.json() == [expected_json]

    post_call, get_call = calls
    assert post_call[:3] == ("post", session_sentinel, 21)
    posted = post_call[3]
    assert posted.authorization_terms == [
        "no_reuse",
        "representative_nonlocalized",
        "visible_branding_allowed",
    ]
    assert posted.expected_current_authorization_fingerprint is None
    assert get_call == ("get", session_sentinel, 21, (51, 61))


def test_scoped_authorization_http_errors_are_fail_closed(monkeypatch) -> None:
    def reject(*_args, **_kwargs):
        raise page_media_planning_routes.ScopedMediaAuthorizationError(
            "Authorization scope is stale."
        )

    monkeypatch.setattr(
        page_media_planning_routes,
        "create_scoped_media_authorization",
        reject,
    )
    with TestClient(_app(object())) as client:
        response = client.post(
            "/api/site-plans/21/page-media/authorizations",
            json={
                "media_requirement_id": 51,
                "expected_requirement_version": 3,
                "expected_placement_contract_version": 2,
                "image_metadata_id": 61,
                "expected_media_version": 4,
                "expected_asset_checksum_sha256": SHA_A,
                "expected_approval_version": 2,
                "expected_approval_fingerprint": SHA_B,
                "reuse_policy": "requirement_only",
                "authorization_terms": ["no_reuse"],
                "authorized_by": "Usage Approver",
                "authorization_rationale": "Exact scope only.",
            },
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Authorization scope is stale."}
