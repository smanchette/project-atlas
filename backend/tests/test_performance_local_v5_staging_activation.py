from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError

from app.schemas.performance_local_v5_staging import (
    PerformanceLocalV5MediaReadiness,
    PerformanceLocalV5PageIdentity,
    PerformanceLocalV5RegistrationIdentity,
    PerformanceLocalV5RemoteApplyResult,
    PerformanceLocalV5RemoteInspection,
    PerformanceLocalV5StagingApplyRequest,
    PerformanceLocalV5StagingDryRunRequest,
)
from app.services import performance_local_v5_staging as service


SHA = "a" * 64
MEDIA_SHA = "b" * 64
SITE = "https://staging.example.test"
REQUEST_ID_1 = "11111111-1111-4111-8111-111111111111"
REQUEST_ID_2 = "22222222-2222-4222-8222-222222222222"
REQUEST_ID_3 = "33333333-3333-4333-8333-333333333333"


def _identity() -> PerformanceLocalV5PageIdentity:
    return PerformanceLocalV5PageIdentity(
        website_id=1,
        planned_page_id=19,
        generated_page_id=41,
        generated_page_revision_id=82,
        composition_id=9,
        composition_version=4,
        immutable_composition_revision_id=33,
        qa_result_id=121,
        wordpress_post_id=8,
        wordpress_post_status="publish",
        page_title="Drywood Termite Tenting in Orlando, Florida",
        page_slug="drywood-termite-tenting-orlando-fl",
    )


def _local() -> service._LocalContext:
    return service._LocalContext(
        identity=_identity(),
        payload={
            "schema": "project-atlas-performance-local-v5-wordpress@1",
            "website": {"identity": "website:1"},
            "payload_identity": {"source_page": "generated-page:41"},
        },
        payload_sha256=SHA,
        required_media=[],
    )


def _registration(*, ready: bool = True) -> PerformanceLocalV5RegistrationIdentity:
    return PerformanceLocalV5RegistrationIdentity(
        theme_family_id=2 if ready else None,
        theme_family_version_id=5 if ready else None,
        theme_family_version=5 if ready else None,
        website_theme_configuration_id=7 if ready else None,
        materialized_theme_id=11 if ready else None,
        website_theme_selection_id=13 if ready else None,
        ready=ready,
    )


def _media(
    *,
    ready: bool = True,
    independently_verified_logo_transport: bool = False,
) -> list[PerformanceLocalV5MediaReadiness]:
    """Return page media plus an explicit future logo-proof test seam.

    Production code has no durable logo transport proof today.  Downstream
    token/apply tests must opt in explicitly when simulating a future proof.
    """

    return [
        PerformanceLocalV5MediaReadiness(
            requirement_id=257,
            assignment_id=88,
            asset_id=4,
            authorization_id=14,
            authorization_version=2,
            authorization_fingerprint="d" * 64,
            asset_sha256=MEDIA_SHA,
            source_file_name="page-41-hero.jpg",
            source_mime_type="image/jpeg",
            source_width=1440,
            source_height=1000,
            wordpress_media_id=31 if ready else None,
            wordpress_media_url=(
                "https://staging.example.test/wp-content/uploads/hero.jpg" if ready else None
            ),
            wordpress_media_status="verified" if ready else None,
            wordpress_media_checksum=MEDIA_SHA if ready else None,
            ready=ready,
            blocker=None if ready else "REMOTE_MEDIA_SYNC_REQUIRED",
        ),
        PerformanceLocalV5MediaReadiness(
            identity_kind="brand_asset",
            requirement_id=None,
            asset_id=12,
            brand_asset_id=12,
            role="header_logo",
            asset_key="primary-logo",
            asset_version=3,
            asset_sha256=MEDIA_SHA,
            source_file_name="flo-zone-logo.png",
            source_mime_type="image/png",
            source_width=640,
            source_height=320,
            governed_asset_url=(
                f"{SITE}/wp-content/uploads/atlas-v5/flo-zone-logo.png"
            ),
            wordpress_media_url=(
                f"{SITE}/wp-content/uploads/atlas-v5/flo-zone-logo.png"
                if independently_verified_logo_transport
                else None
            ),
            wordpress_media_status=(
                "verified"
                if independently_verified_logo_transport
                else None
            ),
            wordpress_media_checksum=(
                MEDIA_SHA if independently_verified_logo_transport else None
            ),
            ready=independently_verified_logo_transport,
            blocker=(
                None
                if independently_verified_logo_transport
                else "REMOTE_MEDIA_SYNC_REQUIRED"
            ),
        ),
    ]


def _remote(*, metadata_exists: bool = False) -> PerformanceLocalV5RemoteInspection:
    return PerformanceLocalV5RemoteInspection(
        route_schema="project-atlas-performance-local-v5-page-payload-route@1",
        metadata_bridge_version="0.57.10",
        environment_type="staging",
        home=SITE,
        siteurl=SITE,
        blog_public=0,
        post_id=8,
        post_type="page",
        post_status="publish",
        post_title=_identity().page_title,
        post_slug=_identity().page_slug,
        metadata_exists=metadata_exists,
        metadata_sha256=SHA if metadata_exists else None,
        metadata_valid=metadata_exists,
        atlas_identity=None,
    )


def _applied(request_identity: str) -> PerformanceLocalV5RemoteApplyResult:
    return PerformanceLocalV5RemoteApplyResult(
        route_schema="project-atlas-performance-local-v5-page-payload-route@1",
        metadata_bridge_version="0.57.10",
        status="APPLIED",
        post_id=8,
        prior_sha256=None,
        resulting_sha256=SHA,
        website_id=1,
        planned_page_id=19,
        generated_page_id=41,
        request_identity=request_identity,
        metadata_valid=True,
    )


def _request(host: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": (host, 50000),
            "server": ("localhost", 8000),
        }
    )


class _Result:
    def __init__(self, first=None, all_values=None):
        self._first = first
        self._all = [] if all_values is None else all_values

    def first(self):
        return self._first

    def all(self):
        return self._all


class _NoWriteSession:
    def __init__(self):
        self.commits = 0
        self.adds = []

    def commit(self):
        self.commits += 1

    def add(self, value):
        self.adds.append(value)


def _stub_local_dry_run(
    monkeypatch,
    *,
    registration_ready=True,
    media_ready=True,
    independently_verified_logo_transport=False,
):
    monkeypatch.setattr(service, "_current_migration", lambda session: "20260820_0048")
    monkeypatch.setattr(service, "_build_local_context", lambda session, page_id: _local())
    monkeypatch.setattr(
        service,
        "_registration_state",
        lambda session, website_id: (
            _registration(ready=registration_ready),
            [],
            [] if registration_ready else ["V5_REGISTRATION_REQUIRED"],
        ),
    )
    monkeypatch.setattr(
        service,
        "_media_readiness",
        lambda session, required, **kwargs: _media(
            ready=media_ready,
            independently_verified_logo_transport=(
                independently_verified_logo_transport
            ),
        ),
    )
    monkeypatch.setattr(service, "_payload_is_public", lambda session, website_id, payload: True)
    monkeypatch.setattr(
        service,
        "read_wordpress_settings",
        lambda session, **kwargs: SimpleNamespace(
            site_url=SITE,
            username="atlas",
            publishing_mode="sandbox",
            has_application_password=True,
        ),
    )


def test_apply_request_rejects_browser_payload_and_unknown_fields():
    with pytest.raises(ValidationError):
        PerformanceLocalV5StagingApplyRequest.model_validate(
            {
                "confirmation_token": "x" * 64,
                "confirmation_phrase": "APPLY PERFORMANCE LOCAL V5 TO STAGING PAGE 8",
                "payload": {"forbidden": True},
            }
        )


def test_staging_routes_return_sanitized_404_before_service_for_non_loopback(monkeypatch):
    from app.api import wordpress_routes
    from app.services import form_submission_gateway

    monkeypatch.setattr(
        form_submission_gateway,
        "get_settings",
        lambda: SimpleNamespace(frontend_origin="http://localhost:5173"),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        wordpress_routes,
        "dry_run_performance_local_v5_staging",
        lambda *args, **kwargs: calls.append("dry-run"),
    )
    monkeypatch.setattr(
        wordpress_routes,
        "apply_performance_local_v5_staging",
        lambda *args, **kwargs: calls.append("apply"),
    )
    denied = _request("203.0.113.10")
    apply_payload = PerformanceLocalV5StagingApplyRequest(
        confirmation_token="x" * 64,
        confirmation_phrase="APPLY PERFORMANCE LOCAL V5 TO STAGING PAGE 8",
    )

    for call in (
        lambda: wordpress_routes.performance_local_v5_staging_dry_run(
            41,
            PerformanceLocalV5StagingDryRunRequest(no_network=True),
            denied,
            object(),
        ),
        lambda: wordpress_routes.performance_local_v5_staging_apply(
            41,
            apply_payload,
            denied,
            object(),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404
        assert exc.value.detail == {
            "code": "local_staging_route_unavailable",
            "message": "The local staging route is unavailable.",
        }
    assert calls == []


@pytest.mark.parametrize("host", ["127.0.0.1", "testclient"])
def test_staging_routes_accept_loopback_and_testclient(monkeypatch, host):
    from app.api import wordpress_routes
    from app.services import form_submission_gateway

    monkeypatch.setattr(
        form_submission_gateway,
        "get_settings",
        lambda: SimpleNamespace(frontend_origin="http://localhost:5173"),
    )
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        wordpress_routes,
        "dry_run_performance_local_v5_staging",
        lambda session, page_id, **kwargs: calls.append(("dry-run", page_id)) or "dry",
    )
    monkeypatch.setattr(
        wordpress_routes,
        "apply_performance_local_v5_staging",
        lambda session, page_id, payload: calls.append(("apply", page_id)) or "apply",
    )
    accepted = _request(host)
    apply_payload = PerformanceLocalV5StagingApplyRequest(
        confirmation_token="x" * 64,
        confirmation_phrase="APPLY PERFORMANCE LOCAL V5 TO STAGING PAGE 8",
    )

    assert wordpress_routes.performance_local_v5_staging_dry_run(
        41,
        PerformanceLocalV5StagingDryRunRequest(no_network=True),
        accepted,
        object(),
    ) == "dry"
    assert wordpress_routes.performance_local_v5_staging_apply(
        41,
        apply_payload,
        accepted,
        object(),
    ) == "apply"
    assert calls == [("dry-run", 41), ("apply", 41)]


def test_no_network_dry_run_is_tokenless_and_never_touches_http_or_password(monkeypatch):
    session = _NoWriteSession()
    _stub_local_dry_run(monkeypatch, registration_ready=False, media_ready=False)
    monkeypatch.setattr(
        service,
        "_lock_staging_source_tables",
        lambda session: pytest.fail("no-network dry-run acquired an apply fence"),
    )
    monkeypatch.setattr(
        service,
        "get_wordpress_application_password",
        lambda: pytest.fail("no-network dry-run obtained the application password"),
    )
    monkeypatch.setattr(
        service,
        "_remote_get",
        lambda *args, **kwargs: pytest.fail("no-network dry-run attempted HTTP"),
    )

    result = service.dry_run_performance_local_v5_staging(session, 41, no_network=True)

    assert result.status == "BLOCKED"
    assert result.no_network is True
    assert result.confirmation_token is None
    assert result.confirmation_phrase is None
    assert "V5_REGISTRATION_REQUIRED" in result.blockers
    assert "REMOTE_MEDIA_SYNC_REQUIRED" in result.blockers
    assert "PRIVATE_DATA_IN_PUBLIC_PAYLOAD" not in result.blockers
    assert "REMOTE_INSPECTION_REQUIRED" in result.blockers
    assert session.commits == 0
    assert session.adds == []


def test_no_network_uses_real_settings_reader_without_secret_accessor(monkeypatch):
    from app.services import wordpress_sandbox

    class SettingsSession(_NoWriteSession):
        def exec(self, statement):
            return _Result(
                all_values=[
                    SimpleNamespace(
                        setting_key=wordpress_sandbox.SITE_URL_KEY,
                        setting_value=SITE,
                    ),
                    SimpleNamespace(
                        setting_key=wordpress_sandbox.USERNAME_KEY,
                        setting_value="atlas",
                    ),
                    SimpleNamespace(
                        setting_key=wordpress_sandbox.MODE_KEY,
                        setting_value="sandbox",
                    ),
                ]
            )

    session = SettingsSession()
    _stub_local_dry_run(monkeypatch)
    monkeypatch.setattr(service, "read_wordpress_settings", wordpress_sandbox.read_wordpress_settings)
    monkeypatch.setattr(
        wordpress_sandbox,
        "_get_application_password",
        lambda: pytest.fail("settings reader probed the process-memory secret"),
    )
    monkeypatch.setattr(
        service,
        "get_wordpress_application_password",
        lambda: pytest.fail("no-network dry-run obtained the application password"),
    )
    monkeypatch.setattr(
        service,
        "_remote_get",
        lambda *args, **kwargs: pytest.fail("no-network dry-run attempted HTTP"),
    )

    result = service.dry_run_performance_local_v5_staging(session, 41, no_network=True)

    assert result.status == "BLOCKED"
    assert result.target_staging_url == SITE
    assert "STAGING_CREDENTIALS_REQUIRED" in result.blockers
    assert "REMOTE_INSPECTION_REQUIRED" in result.blockers


def test_local_gate_failure_withholds_credentials_and_remote_inspection(monkeypatch):
    session = _NoWriteSession()
    _stub_local_dry_run(monkeypatch, registration_ready=False)
    monkeypatch.setattr(
        service,
        "get_wordpress_application_password",
        lambda: pytest.fail("credentials were read before all local gates passed"),
    )
    monkeypatch.setattr(
        service,
        "_remote_get",
        lambda *args, **kwargs: pytest.fail("remote GET ran before all local gates passed"),
    )

    result = service.dry_run_performance_local_v5_staging(session, 41)

    assert result.status == "BLOCKED"
    assert "V5_REGISTRATION_REQUIRED" in result.blockers
    assert "STAGING_CREDENTIALS_REQUIRED" in result.blockers
    assert "REMOTE_INSPECTION_REQUIRED" in result.blockers


def test_http_staging_target_is_rejected_before_credentials_or_remote_get(monkeypatch):
    session = _NoWriteSession()
    _stub_local_dry_run(monkeypatch)
    monkeypatch.setattr(
        service,
        "read_wordpress_settings",
        lambda session, **kwargs: SimpleNamespace(
            site_url="http://staging.example.test",
            username="atlas",
            publishing_mode="sandbox",
            has_application_password=False,
        ),
    )
    monkeypatch.setattr(
        service,
        "get_wordpress_application_password",
        lambda: pytest.fail("credentials were read for a non-HTTPS target"),
    )
    monkeypatch.setattr(
        service,
        "_remote_get",
        lambda *args, **kwargs: pytest.fail("remote GET ran for a non-HTTPS target"),
    )

    result = service.dry_run_performance_local_v5_staging(session, 41)

    assert result.status == "BLOCKED"
    assert result.target_staging_url is None
    assert result.route is None
    assert "STAGING_CREDENTIALS_REQUIRED" in result.blockers
    assert "REMOTE_INSPECTION_REQUIRED" in result.blockers
    assert service._normalized_site_url("http://staging.example.test") is None


def test_live_dry_run_issues_state_bound_token_only_after_exact_private_get(monkeypatch):
    session = _NoWriteSession()
    _stub_local_dry_run(
        monkeypatch,
        independently_verified_logo_transport=True,
    )
    monkeypatch.setattr(service, "get_wordpress_application_password", lambda: "not-returned")
    monkeypatch.setattr(service, "_remote_get", lambda session, route: _remote())

    result = service.dry_run_performance_local_v5_staging(session, 41)

    assert result.status == "DRY_RUN_READY"
    assert result.confirmation_phrase == "APPLY PERFORMANCE LOCAL V5 TO STAGING PAGE 8"
    assert result.confirmation_token
    decoded = service._decode_token(result.confirmation_token, action=service.TOKEN_ACTION)
    assert decoded["page_id"] == 41
    parsed_request_identity = UUID(decoded["request_identity"])
    assert parsed_request_identity.version == 4
    assert str(parsed_request_identity) == decoded["request_identity"]
    assert decoded["context"]["identity"]["planned_page_id"] == 19
    assert decoded["context"]["identity"]["generated_page_id"] == 41
    assert decoded["context"]["payload_sha256"] == SHA
    assert decoded["context"]["prior_metadata_sha256"] is None
    assert "payload" not in decoded["context"]
    public_artifacts = json.dumps(
        {"response": result.model_dump(mode="json"), "token": decoded},
        sort_keys=True,
    )
    assert "private-recipient@example.test" not in public_artifacts
    assert "private-from@example.test" not in public_artifacts
    assert session.commits == 0
    assert session.adds == []


@pytest.mark.parametrize(
    ("replacement", "blocker"),
    [
        ({"environment_type": "production"}, "REMOTE_TARGET_NOT_PRIVATE_STAGING"),
        ({"blog_public": 1}, "REMOTE_TARGET_NOT_PRIVATE_STAGING"),
        ({"post_slug": "wrong"}, "REMOTE_POST_IDENTITY_MISMATCH"),
        ({"post_status": "draft"}, "REMOTE_POST_IDENTITY_MISMATCH"),
        (
            {"metadata_exists": True, "metadata_sha256": "c" * 64, "metadata_valid": True},
            "REMOTE_METADATA_CONFLICT",
        ),
    ],
)
def test_remote_target_or_state_mismatch_never_issues_token(monkeypatch, replacement, blocker):
    session = _NoWriteSession()
    _stub_local_dry_run(
        monkeypatch,
        independently_verified_logo_transport=True,
    )
    monkeypatch.setattr(service, "get_wordpress_application_password", lambda: "not-returned")
    observed = _remote().model_copy(update=replacement)
    monkeypatch.setattr(service, "_remote_get", lambda session, route: observed)

    result = service.dry_run_performance_local_v5_staging(session, 41)

    assert result.ready is False
    assert result.confirmation_token is None
    assert blocker in result.blockers


def test_postgres_apply_fence_uses_share_lock_over_every_gate_source_table():
    class FenceSession:
        def __init__(self):
            self.statements = []

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def exec(self, statement):
            self.statements.append(str(statement))

    session = FenceSession()
    service._lock_staging_source_tables(session)

    assert session.statements == [
        "LOCK TABLE "
        + ", ".join(service._STAGING_SOURCE_TABLES)
        + " IN SHARE MODE"
    ]
    required = {
        # Migration and exact Page/revision/composition/QA sources.
        "alembic_version",
        "generatedpage",
        "plannedpage",
        "generatedpagerevision",
        "generatedpageqaresult",
        "pagecomposition",
        "pagecompositionrevision",
        # Theme registration/configuration/selection sources.
        "theme",
        "themefamily",
        "themefamilyversion",
        "websitethemeconfiguration",
        "websitethemecomponentconfiguration",
        "websitethemeselection",
        # Governed page, media, Website, Business, Brand, and settings sources.
        "website",
        "business",
        "brand",
        "brandasset",
        "imagemetadata",
        "pageimageassignment",
        "plannedpagemediarequirement",
        "scopedmediaauthorization",
        "setting",
        # Private form-source privacy gates.
        "websiteformdeliverymoderevision",
        "websiteformrecipientrevision",
    }
    assert required <= set(service._STAGING_SOURCE_TABLES)


def test_apply_fence_is_a_noop_outside_postgres():
    class SqliteSession:
        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def exec(self, statement):
            pytest.fail("SQLite apply fence executed SQL")

    service._lock_staging_source_tables(SqliteSession())


class _ApplySession(_NoWriteSession):
    def __init__(
        self,
        *,
        replay=False,
        prior_attempt=None,
        commit_failures: int = 0,
    ):
        super().__init__()
        self.exec_count = 0
        self.flushes = 0
        self.rollbacks = 0
        self.commit_failures = commit_failures
        prior = prior_attempt
        if replay and prior is None:
            prior = SimpleNamespace(status="applied")
        self._results = [
            _Result(first=SimpleNamespace(id=41)),
            _Result(first=prior),
        ]

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def exec(self, statement):
        self.exec_count += 1
        return self._results.pop(0)

    def flush(self):
        self.flushes += 1
        if self.adds and getattr(self.adds[-1], "id", None) is None:
            self.adds[-1].id = 77

    def commit(self):
        self.commits += 1
        if self.commit_failures:
            self.commit_failures -= 1
            raise RuntimeError("synthetic audit commit failure")

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, value):
        if getattr(value, "id", None) is None:
            value.id = 77


def _ready_state(request_identity: str) -> service._DryRunState:
    local = _local()
    remote = _remote()
    registration = _registration()
    media = _media(independently_verified_logo_transport=True)
    response = service.PerformanceLocalV5StagingDryRun(
        status="DRY_RUN_READY",
        ready=True,
        no_network=False,
        target_staging_url=SITE,
        route=service._route_url(SITE, 8),
        identity=local.identity,
        registration=registration,
        payload_sha256=SHA,
        media_readiness=media,
        unchanged_page_fields=list(service.UNCHANGED_PAGE_FIELDS),
        blockers=[],
        gate_results=[],
    )
    context = service._token_context(
        local,
        registration,
        media,
        remote,
        request_identity=request_identity,
    )
    return service._DryRunState(
        response=response,
        local=local,
        remote=remote,
        token_context=context,
    )


def _ready_state_with_exact_remote(request_identity: str) -> service._DryRunState:
    state = _ready_state(request_identity)
    remote = _remote(metadata_exists=True)
    return service._DryRunState(
        response=state.response.model_copy(
            update={"current_remote_metadata_sha256": SHA}
        ),
        local=state.local,
        remote=remote,
        token_context=service._token_context(
            state.local,
            state.response.registration,
            state.response.media_readiness,
            remote,
            request_identity=request_identity,
        ),
    )


def _apply_request(request_identity: str) -> PerformanceLocalV5StagingApplyRequest:
    state = _ready_state(request_identity)
    token = service._encode_token(
        action=service.TOKEN_ACTION,
        page_id=41,
        request_identity=request_identity,
        context=state.token_context or {},
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    return PerformanceLocalV5StagingApplyRequest(
        confirmation_token=token,
        confirmation_phrase="APPLY PERFORMANCE LOCAL V5 TO STAGING PAGE 8",
    )


def test_apply_rebuilds_and_posts_only_exact_custom_route_envelope(monkeypatch):
    request_identity = REQUEST_ID_1
    state = _ready_state(request_identity)
    session = _ApplySession()
    sent = {}

    events = []

    def lock(_session):
        events.append("lock")

    def evaluate(*args, **kwargs):
        assert events == ["lock"]
        assert session.exec_count == 2
        return state

    monkeypatch.setattr(service, "_lock_staging_source_tables", lock)
    monkeypatch.setattr(service, "_evaluate_dry_run", evaluate)

    def post(_session, route, envelope):
        # The pending audit has been flushed, but the GeneratedPage lock and
        # governed-state transaction must remain open through POST + GET.
        assert session.flushes == 1
        assert session.commits == 0
        sent["route"] = route
        sent["envelope"] = envelope
        return PerformanceLocalV5RemoteApplyResult(
            route_schema="project-atlas-performance-local-v5-page-payload-route@1",
            metadata_bridge_version="0.57.10",
            status="APPLIED",
            post_id=8,
            prior_sha256=None,
            resulting_sha256=SHA,
            website_id=1,
            planned_page_id=19,
            generated_page_id=41,
            request_identity=request_identity,
            metadata_valid=True,
        )

    monkeypatch.setattr(service, "_remote_post", post)
    monkeypatch.setattr(service, "_remote_get", lambda session, route: _remote(metadata_exists=True))

    result = service.apply_performance_local_v5_staging(
        session,
        41,
        _apply_request(request_identity),
    )

    assert result.status == "APPLIED"
    assert sent["route"] == f"{SITE}/wp-json/project-atlas/v4/performance-local-v5/page-payload/8"
    assert set(sent["envelope"]) == {
        "request_schema",
        "expected_prior_sha256",
        "website_id",
        "planned_page_id",
        "generated_page_id",
        "wordpress_post_id",
        "payload",
        "request_identity",
    }
    assert sent["envelope"]["payload"] == _local().payload
    assert "template" not in sent["envelope"]
    assert "_wp_page_template" not in str(sent["envelope"])
    assert len(session.adds) == 2
    assert session.adds[0] is session.adds[1]
    audit_text = str(session.adds[0].model_dump(mode="json"))
    assert "not-returned" not in audit_text
    assert "recipient_email" not in audit_text
    assert "private-recipient@example.test" not in audit_text
    assert "private-from@example.test" not in audit_text
    assert session.flushes == 1
    assert session.commits == 1
    assert result.wordpress_post_count == 1
    assert result.wordpress_verification_get_count == 1


def test_apply_failure_commits_the_same_flushed_audit_once(monkeypatch):
    request_identity = REQUEST_ID_1
    state = _ready_state(request_identity)
    session = _ApplySession()
    monkeypatch.setattr(service, "_evaluate_dry_run", lambda *args, **kwargs: state)

    def post(*args, **kwargs):
        assert session.flushes == 1
        assert session.commits == 0
        raise HTTPException(status_code=502, detail="remote_post_rejected:contract")

    monkeypatch.setattr(service, "_remote_post", post)
    monkeypatch.setattr(service, "_remote_get", lambda session, route: _remote())

    with pytest.raises(HTTPException) as exc:
        service.apply_performance_local_v5_staging(
            session,
            41,
            _apply_request(request_identity),
        )

    assert exc.value.status_code == 502
    assert session.flushes == 1
    assert session.commits == 1
    assert len(session.adds) == 2
    assert session.adds[0] is session.adds[1]
    assert session.adds[0].status == "verification_failed"


def test_apply_reconciles_a_lost_post_response_with_one_get_and_no_second_write(monkeypatch):
    request_identity = REQUEST_ID_1
    state = _ready_state(request_identity)
    session = _ApplySession()
    post_calls = 0
    get_calls = 0

    monkeypatch.setattr(service, "_evaluate_dry_run", lambda *args, **kwargs: state)

    def lost_response(*args, **kwargs):
        nonlocal post_calls
        post_calls += 1
        raise HTTPException(status_code=502, detail="remote_post_response_lost")

    def reconcile(*args, **kwargs):
        nonlocal get_calls
        get_calls += 1
        return _remote(metadata_exists=True)

    monkeypatch.setattr(service, "_remote_post", lost_response)
    monkeypatch.setattr(service, "_remote_get", reconcile)

    result = service.apply_performance_local_v5_staging(
        session,
        41,
        _apply_request(request_identity),
    )

    assert result.status == "UNCHANGED"
    assert result.wordpress_post_count == 1
    assert result.wordpress_verification_get_count == 1
    assert post_calls == 1
    assert get_calls == 1
    assert session.adds[-1].status == "unchanged"
    assert session.adds[-1].returned_snapshot["reconciled_after_uncertainty"] is True


def test_verification_failed_audit_is_reused_for_an_exact_retry(monkeypatch):
    request_identity = REQUEST_ID_2
    state = _ready_state(request_identity)
    request = _apply_request(request_identity)
    first = _ApplySession()
    monkeypatch.setattr(service, "_evaluate_dry_run", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        service,
        "_remote_post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HTTPException(status_code=502, detail="remote_post_response_lost")
        ),
    )
    monkeypatch.setattr(service, "_remote_get", lambda *args, **kwargs: _remote())

    with pytest.raises(HTTPException):
        service.apply_performance_local_v5_staging(first, 41, request)
    failed_audit = first.adds[-1]
    assert failed_audit.status == "verification_failed"

    retry = _ApplySession(prior_attempt=failed_audit)
    post_calls = 0

    def successful_post(*args, **kwargs):
        nonlocal post_calls
        post_calls += 1
        return _applied(request_identity)

    monkeypatch.setattr(service, "_remote_post", successful_post)
    monkeypatch.setattr(
        service,
        "_remote_get",
        lambda *args, **kwargs: _remote(metadata_exists=True),
    )
    result = service.apply_performance_local_v5_staging(retry, 41, request)

    assert result.status == "APPLIED"
    assert post_calls == 1
    assert retry.adds[0] is failed_audit
    assert retry.adds[-1] is failed_audit
    assert failed_audit.status == "applied"
    assert retry.commits == 1


def test_retry_reconciles_current_exact_state_without_a_second_post(monkeypatch):
    request_identity = REQUEST_ID_2
    initial = _ready_state(request_identity)
    current = _ready_state_with_exact_remote(request_identity)
    request = _apply_request(request_identity)
    first = _ApplySession()
    monkeypatch.setattr(service, "_evaluate_dry_run", lambda *args, **kwargs: initial)
    monkeypatch.setattr(
        service,
        "_remote_post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HTTPException(status_code=502, detail="remote_post_response_lost")
        ),
    )
    monkeypatch.setattr(service, "_remote_get", lambda *args, **kwargs: _remote())

    with pytest.raises(HTTPException):
        service.apply_performance_local_v5_staging(first, 41, request)
    failed_audit = first.adds[-1]

    retry = _ApplySession(prior_attempt=failed_audit)
    monkeypatch.setattr(service, "_evaluate_dry_run", lambda *args, **kwargs: current)
    monkeypatch.setattr(
        service,
        "_remote_post",
        lambda *args, **kwargs: pytest.fail("current exact retry issued a second POST"),
    )
    result = service.apply_performance_local_v5_staging(retry, 41, request)

    assert result.status == "UNCHANGED"
    assert result.wordpress_post_count == 0
    assert result.wordpress_verification_get_count == 0
    assert failed_audit.status == "unchanged"
    assert failed_audit.returned_snapshot["reconciled_after_uncertainty"] is True


def test_audit_commit_failure_retries_by_reconciling_without_a_second_post(monkeypatch):
    request_identity = REQUEST_ID_3
    initial = _ready_state(request_identity)
    current = _ready_state_with_exact_remote(request_identity)
    request = _apply_request(request_identity)
    states = iter((initial, current))
    monkeypatch.setattr(
        service,
        "_evaluate_dry_run",
        lambda *args, **kwargs: next(states),
    )
    post_calls = 0

    def successful_post(*args, **kwargs):
        nonlocal post_calls
        post_calls += 1
        return _applied(request_identity)

    monkeypatch.setattr(service, "_remote_post", successful_post)
    monkeypatch.setattr(
        service,
        "_remote_get",
        lambda *args, **kwargs: _remote(metadata_exists=True),
    )
    first = _ApplySession(commit_failures=1)
    with pytest.raises(HTTPException) as exc:
        service.apply_performance_local_v5_staging(first, 41, request)
    assert exc.value.status_code == 503
    assert first.rollbacks == 1
    assert post_calls == 1

    retry = _ApplySession()
    result = service.apply_performance_local_v5_staging(retry, 41, request)

    assert result.status == "UNCHANGED"
    assert result.wordpress_post_count == 0
    assert post_calls == 1
    assert retry.commits == 1


def test_consumed_token_is_rejected_before_any_remote_post(monkeypatch):
    request_identity = REQUEST_ID_2
    state = _ready_state(request_identity)
    session = _ApplySession(replay=True)
    monkeypatch.setattr(service, "_evaluate_dry_run", lambda *args, **kwargs: state)
    monkeypatch.setattr(
        service,
        "_remote_post",
        lambda *args, **kwargs: pytest.fail("replayed token reached WordPress"),
    )

    with pytest.raises(HTTPException) as exc:
        service.apply_performance_local_v5_staging(
            session,
            41,
            _apply_request(request_identity),
        )

    assert exc.value.status_code == 409
    assert "already consumed" in str(exc.value.detail)
    assert session.commits == 0


def test_apply_rejects_token_context_media_change_before_remote_post(monkeypatch):
    original = _ready_state(REQUEST_ID_3)
    changed_media = [
        original.response.media_readiness[0].model_copy(update={"source_width": 1441})
    ]
    changed = service._DryRunState(
        response=original.response.model_copy(update={"media_readiness": changed_media}),
        local=original.local,
        remote=original.remote,
        token_context=None,
    )
    session = _ApplySession()
    monkeypatch.setattr(service, "_evaluate_dry_run", lambda *args, **kwargs: changed)
    monkeypatch.setattr(
        service,
        "_remote_post",
        lambda *args, **kwargs: pytest.fail("changed token context reached WordPress"),
    )

    with pytest.raises(HTTPException) as exc:
        service.apply_performance_local_v5_staging(
            session,
            41,
            _apply_request(REQUEST_ID_3),
        )

    assert exc.value.status_code == 409
    assert "changed after dry-run" in str(exc.value.detail)
    assert session.commits == 0
    assert session.adds == []


def test_post_apply_verification_rejects_original_target_url_drift():
    drifted = _remote(metadata_exists=True).model_copy(
        update={
            "home": "https://other-staging.example.test",
            "siteurl": "https://other-staging.example.test",
        }
    )

    with pytest.raises(HTTPException) as exc:
        service._verify_post_apply_inspection(drifted, _local(), SITE)

    assert exc.value.status_code == 502
    assert "REMOTE_TARGET_NOT_PRIVATE_STAGING" in str(exc.value.detail)


def test_all_missing_registration_is_an_explicit_required_state(monkeypatch):
    from app.schemas.performance_local_v5 import PerformanceLocalV5RegistrationIdentity as PlanIdentity
    from app.services import performance_local_v5_registration as registration_service

    monkeypatch.setattr(
        registration_service,
        "plan_performance_local_v5_registration",
        lambda session, website_id: SimpleNamespace(
            status="PLANNED",
            identity=PlanIdentity(),
            expected_source_commit="e" * 40,
            expected_contract_fingerprint="f" * 64,
            blockers=[],
        ),
    )

    registration, gates, blockers = service._registration_state(object(), 1)

    assert registration.ready is False
    assert registration.theme_family_id is None
    assert blockers == ["V5_REGISTRATION_REQUIRED"]
    assert gates[0].passed is False


def test_missing_wordpress_media_identity_is_exact_sync_blocker():
    image = SimpleNamespace(
        file_name="page-41-hero.jpg",
        mime_type="image/jpeg",
        width=1440,
        height=1000,
        wordpress_media_status=None,
        wordpress_media_checksum=None,
        wordpress_media_id=None,
        wordpress_media_url=None,
        checksum_sha256=MEDIA_SHA,
    )
    session = SimpleNamespace(get=lambda model, identity: image)
    required = [
        {
            "requirement_id": 257,
            "assignment_id": 88,
            "image_metadata_id": 4,
            "checksum_sha256": MEDIA_SHA,
            "wordpress_media_id": None,
            "wordpress_media_url": None,
            "payload_src": "/media/hero.jpg",
            "authorization_id": 14,
            "authorization_version": 2,
            "authorization_fingerprint": "d" * 64,
        }
    ]

    result = service._media_readiness(session, required, target_origin=SITE)

    assert result[0].ready is False
    assert result[0].blocker == "REMOTE_MEDIA_SYNC_REQUIRED"


def test_exact_reconciled_media_mapping_binds_full_source_identity():
    url = f"{SITE}/wp-content/uploads/atlas-v5/page-41-hero.jpg"
    image = SimpleNamespace(
        file_name="page-41-hero.jpg",
        mime_type="image/jpeg",
        width=1440,
        height=1000,
        wordpress_media_status="reconciled",
        wordpress_media_checksum=MEDIA_SHA,
        wordpress_media_id=31,
        wordpress_media_url=url,
        checksum_sha256=MEDIA_SHA,
    )
    session = SimpleNamespace(get=lambda model, identity: image)
    required = [
        {
            "requirement_id": 257,
            "assignment_id": 88,
            "image_metadata_id": 4,
            "checksum_sha256": MEDIA_SHA,
            "wordpress_media_id": 31,
            "wordpress_media_url": url,
            "payload_src": "/wp-content/uploads/atlas-v5/page-41-hero.jpg",
            "authorization_id": 14,
            "authorization_version": 2,
            "authorization_fingerprint": "d" * 64,
        }
    ]

    result = service._media_readiness(session, required, target_origin=SITE)

    assert result[0].ready is True
    assert result[0].blocker is None
    assert result[0].source_file_name == "page-41-hero.jpg"
    assert result[0].source_mime_type == "image/jpeg"
    assert (result[0].source_width, result[0].source_height) == (1440, 1000)


def test_governed_logo_url_without_transport_proof_is_blocked_but_identity_is_bound():
    logo_url = f"{SITE}/wp-content/uploads/atlas-v5/flo-zone-logo.png"
    asset = SimpleNamespace(
        status="approved",
        asset_key="primary-logo",
        version=3,
        checksum_sha256=MEDIA_SHA,
        original_filename="flo-zone-logo.png",
        mime_type="image/png",
        width=640,
        height=320,
        optimized_url=logo_url,
        asset_url="https://unused.example.test/original.png",
    )
    session = SimpleNamespace(get=lambda model, identity: asset)
    required = [
        {
            "role": "header_logo",
            "brand_asset_id": 12,
            "asset_key": "primary-logo",
            "asset_version": 3,
            "checksum_sha256": MEDIA_SHA,
            "source_filename": "flo-zone-logo.png",
            "source_mime_type": "image/png",
            "source_width": 640,
            "source_height": 320,
            "governed_asset_url": logo_url,
            "payload_src": "/wp-content/uploads/atlas-v5/flo-zone-logo.png",
            "ready": True,
        }
    ]

    observed = service._media_readiness(session, required, target_origin=SITE)[0]

    assert observed.identity_kind == "brand_asset"
    assert observed.requirement_id is None
    assert observed.asset_id == 12
    assert observed.brand_asset_id == 12
    assert observed.role == "header_logo"
    assert observed.asset_key == "primary-logo"
    assert observed.asset_version == 3
    assert observed.governed_asset_url == logo_url
    assert observed.wordpress_media_url is None
    assert observed.ready is False
    assert observed.blocker == "REMOTE_MEDIA_SYNC_REQUIRED"
    context = service._token_context(
        _local(),
        _registration(),
        [observed],
        _remote(),
        request_identity=REQUEST_ID_1,
    )
    changed_context = service._token_context(
        _local(),
        _registration(),
        [observed.model_copy(update={"source_width": 641})],
        _remote(),
        request_identity=REQUEST_ID_1,
    )
    assert context["media_identity_sha256"] != changed_context["media_identity_sha256"]


def test_production_dry_run_blocks_unverified_logo_before_credentials_or_remote_get(
    monkeypatch,
):
    page_url = f"{SITE}/wp-content/uploads/atlas-v5/page-41-hero.jpg"
    logo_url = f"{SITE}/wp-content/uploads/atlas-v5/flo-zone-logo.png"
    page_image = SimpleNamespace(
        file_name="page-41-hero.jpg",
        mime_type="image/jpeg",
        width=1440,
        height=1000,
        wordpress_media_status="reconciled",
        wordpress_media_checksum=MEDIA_SHA,
        wordpress_media_id=31,
        wordpress_media_url=page_url,
        checksum_sha256=MEDIA_SHA,
    )
    logo_asset = SimpleNamespace(
        status="approved",
        asset_key="primary-logo",
        version=3,
        checksum_sha256=MEDIA_SHA,
        original_filename="flo-zone-logo.png",
        mime_type="image/png",
        width=640,
        height=320,
        optimized_url=logo_url,
        asset_url="https://unused.example.test/original.png",
    )

    class Session(_NoWriteSession):
        def get(self, model, identity):
            if model is service.ImageMetadata:
                return page_image
            if model is service.BrandAsset:
                return logo_asset
            return None

    local = service._LocalContext(
        identity=_identity(),
        payload=_local().payload,
        payload_sha256=SHA,
        required_media=[
            {
                "requirement_id": 257,
                "assignment_id": 88,
                "image_metadata_id": 4,
                "checksum_sha256": MEDIA_SHA,
                "wordpress_media_id": 31,
                "wordpress_media_url": page_url,
                "payload_src": "/wp-content/uploads/atlas-v5/page-41-hero.jpg",
                "authorization_id": 14,
                "authorization_version": 2,
                "authorization_fingerprint": "d" * 64,
            },
            {
                "role": "header_logo",
                "brand_asset_id": 12,
                "asset_key": "primary-logo",
                "asset_version": 3,
                "checksum_sha256": MEDIA_SHA,
                "source_filename": "flo-zone-logo.png",
                "source_mime_type": "image/png",
                "source_width": 640,
                "source_height": 320,
                "governed_asset_url": logo_url,
                "payload_src": "/wp-content/uploads/atlas-v5/flo-zone-logo.png",
            },
        ],
    )
    session = Session()
    monkeypatch.setattr(service, "_current_migration", lambda session: "20260820_0048")
    monkeypatch.setattr(service, "_build_local_context", lambda session, page_id: local)
    monkeypatch.setattr(
        service,
        "_registration_state",
        lambda session, website_id: (_registration(), [], []),
    )
    monkeypatch.setattr(service, "_payload_is_public", lambda *args: True)
    monkeypatch.setattr(
        service,
        "read_wordpress_settings",
        lambda session, **kwargs: SimpleNamespace(
            site_url=SITE,
            username="atlas",
            publishing_mode="sandbox",
            has_application_password=True,
        ),
    )
    monkeypatch.setattr(
        service,
        "get_wordpress_application_password",
        lambda: pytest.fail("logo-blocked dry-run obtained staging credentials"),
    )
    monkeypatch.setattr(
        service,
        "_remote_get",
        lambda *args, **kwargs: pytest.fail("logo-blocked dry-run attempted HTTP"),
    )

    result = service.dry_run_performance_local_v5_staging(session, 41)

    assert result.status == "BLOCKED"
    assert result.payload_sha256 == SHA
    assert result.confirmation_token is None
    assert "REMOTE_MEDIA_SYNC_REQUIRED" in result.blockers
    logo = next(
        item for item in result.media_readiness if item.identity_kind == "brand_asset"
    )
    assert logo.brand_asset_id == 12
    assert logo.governed_asset_url == logo_url
    assert logo.wordpress_media_url is None
    assert logo.ready is False
    assert logo.blocker == "REMOTE_MEDIA_SYNC_REQUIRED"
    assert session.commits == 0
    assert session.adds == []


def test_local_context_consumes_page_and_logo_media_from_the_same_payload_build(monkeypatch):
    from app.services import performance_local_v5_payload as payload_service

    page_media = SimpleNamespace(requirement_id=257, image_metadata_id=4)
    logo_media = SimpleNamespace(role="header_logo", brand_asset_id=12)
    records = SimpleNamespace(
        planned=SimpleNamespace(id=19, website_id=1),
        generated=SimpleNamespace(id=41, wordpress_post_id=8),
        revision=SimpleNamespace(id=82, draft_hash_after="e" * 64),
        composition=SimpleNamespace(id=9, composition_version=4, source_hash="f" * 64),
        immutable=SimpleNamespace(id=33, revision_hash="1" * 64),
        qa=SimpleNamespace(id=121, result_hash="2" * 64),
        identity=_identity(),
    )
    bindings = SimpleNamespace(
        generated_page_revision_id=82,
        generated_page_revision_hash="e" * 64,
        page_composition_id=9,
        composition_version=4,
        page_composition_revision_id=33,
        page_composition_revision_hash="1" * 64,
        composition_source_hash="f" * 64,
        qa_result_id=121,
        qa_result_hash="2" * 64,
    )
    built = SimpleNamespace(
        website_id=1,
        planned_page_id=19,
        generated_page_id=41,
        wordpress_post_id=8,
        metadata_key=service.V5_META_KEY,
        payload_schema=service.V5_PAYLOAD_SCHEMA,
        template_value=None,
        payload=_local().payload,
        payload_sha256=SHA,
        source_bindings=bindings,
        required_media=[page_media],
        required_logo_media=[logo_media],
    )
    monkeypatch.setattr(service, "_current_page_records", lambda session, page_id: records)
    monkeypatch.setattr(
        payload_service,
        "build_performance_local_v5_staging_payload",
        lambda session, page_id: built,
    )

    local = service._build_local_context(object(), 41)

    assert local.required_media == [page_media, logo_media]


def test_private_recipient_and_from_values_are_rejected_without_returning_them():
    class Value:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class PrivacySession:
        def __init__(self):
            self.results = [
                Value(
                    [
                        SimpleNamespace(
                            email="private-recipient@example.test",
                            normalized_email="private-recipient@example.test",
                        )
                    ]
                ),
                Value(
                    [
                        SimpleNamespace(
                            configuration_payload={
                                "mail": {"from_email": "private-from@example.test"}
                            },
                            destination_identity=None,
                        )
                    ]
                ),
            ]

        def exec(self, statement):
            return self.results.pop(0)

    private_payload = {
        "form": {"public_contact": "private-from@example.test"},
    }
    assert service._payload_is_public(PrivacySession(), 1, private_payload) is False

    public_payload = {
        "form": {"public_contact": "public-business@example.test"},
    }
    assert service._payload_is_public(PrivacySession(), 1, public_payload) is True


def test_missing_media_builder_error_preserves_governed_identity_without_payload(monkeypatch):
    required_media = [
        {
            "requirement_id": 257,
            "placement_key": "hero",
            "target_component_instance_key": "hero.primary",
            "assignment_id": 88,
            "assignment_version": 3,
            "image_metadata_id": 4,
            "media_key": "orlando-hero",
            "media_version": 2,
            "checksum_sha256": MEDIA_SHA,
            "authorization_id": 14,
            "authorization_version": 2,
            "authorization_fingerprint": "d" * 64,
            "wordpress_media_id": None,
            "wordpress_media_url": None,
            "payload_src": None,
        }
    ]
    logo_url = f"{SITE}/wp-content/uploads/atlas-v5/flo-zone-logo.png"
    required_logo_media = [
        {
            "role": "header_logo",
            "brand_asset_id": 12,
            "asset_key": "primary-logo",
            "asset_version": 3,
            "checksum_sha256": MEDIA_SHA,
            "source_filename": "flo-zone-logo.png",
            "source_mime_type": "image/png",
            "source_width": 640,
            "source_height": 320,
            "governed_asset_url": logo_url,
            "payload_src": "/wp-content/uploads/atlas-v5/flo-zone-logo.png",
            "ready": False,
            "blocker": "REMOTE_MEDIA_SYNC_REQUIRED",
        }
    ]

    class MissingMedia(ValueError):
        code = "REMOTE_MEDIA_SYNC_REQUIRED"

        def __init__(self):
            super().__init__("private diagnostic must not be returned")
            self.required_media = required_media
            self.required_logo_media = required_logo_media
            self.source_identity = SimpleNamespace(
                website_id=1,
                planned_page_id=19,
                generated_page_id=41,
                wordpress_post_id=8,
                source_bindings=SimpleNamespace(
                    generated_page_revision_id=82,
                    generated_page_revision_hash="e" * 64,
                    page_composition_id=9,
                    composition_version=4,
                    page_composition_revision_id=33,
                    page_composition_revision_hash="1" * 64,
                    composition_source_hash="f" * 64,
                    qa_result_id=121,
                    qa_result_hash="2" * 64,
                ),
            )

    class Session(_NoWriteSession):
        def get(self, model, identity):
            if model is service.BrandAsset:
                return SimpleNamespace(
                    id=12,
                    status="approved",
                    asset_key="primary-logo",
                    version=3,
                    checksum_sha256=MEDIA_SHA,
                    original_filename="flo-zone-logo.png",
                    mime_type="image/png",
                    width=640,
                    height=320,
                    optimized_url=logo_url,
                    asset_url="https://unused.example.test/original.png",
                )
            return SimpleNamespace(
                file_name="page-41-hero.jpg",
                mime_type="image/jpeg",
                width=1440,
                height=1000,
                wordpress_media_status=None,
                wordpress_media_checksum=None,
                wordpress_media_id=None,
                wordpress_media_url=None,
                checksum_sha256=MEDIA_SHA,
            )

    session = Session()
    monkeypatch.setattr(service, "_current_migration", lambda session: "20260820_0048")
    monkeypatch.setattr(service, "_build_local_context", lambda *args: (_ for _ in ()).throw(MissingMedia()))
    monkeypatch.setattr(
        service,
        "_current_page_records",
        lambda session, page_id: SimpleNamespace(
            identity=_identity(),
            revision=SimpleNamespace(id=82, draft_hash_after="e" * 64),
            composition=SimpleNamespace(id=9, composition_version=4, source_hash="f" * 64),
            immutable=SimpleNamespace(id=33, revision_hash="1" * 64),
            qa=SimpleNamespace(id=121, result_hash="2" * 64),
        ),
    )
    monkeypatch.setattr(service, "_website_id_for_page", lambda session, page_id: 1)
    monkeypatch.setattr(
        service,
        "_registration_state",
        lambda session, website_id: (_registration(ready=False), [], ["V5_REGISTRATION_REQUIRED"]),
    )
    monkeypatch.setattr(
        service,
        "read_wordpress_settings",
        lambda session, **kwargs: SimpleNamespace(
            site_url=SITE,
            username="atlas",
            publishing_mode="sandbox",
            has_application_password=True,
        ),
    )

    result = service.dry_run_performance_local_v5_staging(session, 41, no_network=True)

    assert result.payload_sha256 is None
    assert result.confirmation_token is None
    assert result.identity == _identity()
    assert "REMOTE_MEDIA_SYNC_REQUIRED" in result.blockers
    assert "PRIVATE_DATA_IN_PUBLIC_PAYLOAD" not in result.blockers
    assert len(result.media_readiness) == 2
    observed = next(
        item for item in result.media_readiness if item.identity_kind == "page_media"
    )
    assert observed.requirement_id == 257
    assert observed.assignment_id == 88
    assert observed.assignment_version == 3
    assert observed.asset_id == 4
    assert observed.asset_sha256 == MEDIA_SHA
    assert observed.source_file_name == "page-41-hero.jpg"
    assert observed.source_mime_type == "image/jpeg"
    assert (observed.source_width, observed.source_height) == (1440, 1000)
    assert observed.authorization_id == 14
    assert observed.authorization_version == 2
    assert observed.authorization_fingerprint == "d" * 64
    logo = next(
        item for item in result.media_readiness if item.identity_kind == "brand_asset"
    )
    assert logo.requirement_id is None
    assert logo.asset_id == 12
    assert logo.brand_asset_id == 12
    assert logo.role == "header_logo"
    assert logo.asset_key == "primary-logo"
    assert logo.asset_version == 3
    assert logo.asset_sha256 == MEDIA_SHA
    assert logo.source_file_name == "flo-zone-logo.png"
    assert logo.source_mime_type == "image/png"
    assert (logo.source_width, logo.source_height) == (640, 320)
    assert logo.governed_asset_url == logo_url
    assert logo.ready is False
    assert logo.blocker == "REMOTE_MEDIA_SYNC_REQUIRED"
    assert "private diagnostic" not in json.dumps(result.model_dump(mode="json"))


def _signed_token_body(body):
    encoded = base64.urlsafe_b64encode(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(
        service._token_secret,
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


@pytest.mark.parametrize(
    "change",
    [
        {"issued_at_offset": 10},
        {"expires_at_offset": 901},
        {"nonce": "bad"},
        {"request_identity": "not-a-uuid"},
        {"request_identity": "11111111-1111-1111-8111-111111111111"},
    ],
)
def test_signed_token_requires_exact_time_nonce_and_request_identity(change):
    now = int(datetime.now(UTC).timestamp())
    request_identity = change.get("request_identity", REQUEST_ID_3)
    body = {
        "action": service.TOKEN_ACTION,
        "page_id": 41,
        "request_identity": request_identity,
        "context": {"request_identity": request_identity},
        "issued_at": now + change.get("issued_at_offset", 0),
        "expires_at": now + change.get("expires_at_offset", 300),
        "nonce": change.get("nonce", "4" * 32),
    }

    with pytest.raises(HTTPException) as exc:
        service._decode_token(_signed_token_body(body), action=service.TOKEN_ACTION)

    assert exc.value.status_code == 422
