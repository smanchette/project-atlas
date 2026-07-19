from __future__ import annotations

from datetime import UTC, datetime, timedelta
import inspect
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.wordpress import (
    WordPressCacheAwareRenderingPreflightRequest,
    WordPressCachePurgePreflightRequest,
)
from app.services import wordpress_cache_aware_rendering as cache


def observation(at: datetime, *, status: int = 200, headers=None, **changes):
    value = {
        "status_code": status,
        "final_url": cache.CANONICAL_URL,
        "redirect_count": 0,
        "content_type": "text/html; charset=UTF-8",
        "cache_headers": headers or {
            "server": "nginx",
            "x-cache-enabled": "true",
            "x-proxy-cache": "HIT",
            "x-proxy-cache-info": "DT:1",
            "age": "12",
            "expires": "Sun, 19 Jul 2026 10:00:00 GMT",
        },
        "body_sha256": "a" * 64,
        "head_hash": "b" * 64,
        "visible_hash": "c" * 64,
        "parsed": {"meta": [], "canonicals": [cache.CANONICAL_URL], "h1": [cache.EXPECTED_H1]},
        "outcome": "public_html_verified" if status == 200 else "unavailable",
        "challenge_page_detected": False,
        "error_page_detected": False,
        "admin_page_detected": False,
        "login_page_detected": False,
        "authenticated_context_detected": False,
        "observation_started_at": (at - timedelta(milliseconds=50)).isoformat(),
        "observation_completed_at": at.isoformat(),
        "observed_at": at.isoformat(),
        "elapsed_ms": 50,
        "generated_at": at.isoformat(),
        "request_id": "ephemeral-one",
    }
    value.update(changes)
    return value


def evidence(*, evidence_id="evidence-one", page_identity=None):
    identity = page_identity or {
        "document_title": "Drywood Termite Tenting in Orlando, FL – My WordPress",
        "h1": cache.EXPECTED_H1,
        "canonical_url": cache.CANONICAL_URL,
        "featured_image_url": "https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png",
        "featured_image_alt": "Two-story Orlando Florida home professionally covered for drywood termite tenting",
    }
    return SimpleNamespace(
        evidence_id=evidence_id,
        rendered_head_hash="d" * 64,
        visible_content_hash="e" * 64,
        metadata_inventory_hash="f" * 64,
        page_identity=identity,
        model_dump=lambda **_: {
            "evidence_id": evidence_id,
            "rendered_head_hash": "d" * 64,
            "visible_content_hash": "e" * 64,
            "metadata_inventory_hash": "f" * 64,
            "page_identity": identity,
        },
    )


def test_stable_fingerprint_allows_later_timestamp_age_date_and_transport_ids():
    t1 = datetime(2026, 7, 19, 6, 0, tzinfo=UTC)
    first = observation(t1)
    second = observation(
        t1 + timedelta(seconds=20),
        headers={
            **first["cache_headers"],
            "age": "32",
            "expires": "Sun, 19 Jul 2026 10:00:20 GMT",
            "last-modified": "Sun, 19 Jul 2026 05:59:59 GMT",
            "date": "Sun, 19 Jul 2026 06:00:20 GMT",
        },
        elapsed_ms=71,
        generated_at=(t1 + timedelta(seconds=21)).isoformat(),
        request_id="ephemeral-two",
    )
    assert cache._stable_public_observation_fingerprint(first, evidence()) == cache._stable_public_observation_fingerprint(second, evidence())
    assert cache._stable_observation_conflict(
        cache._stable_public_observation(first, evidence()),
        cache._stable_public_observation(second, evidence()),
    ) is None


def test_production_shaped_provider_verified_403_has_stable_transport_fingerprint():
    t1 = datetime(2026, 7, 19, 6, 5, tzinfo=UTC)
    first = observation(t1, status=403, headers={"server": "nginx", "x-proxy-cache-info": "DT:1", "age": "4"})
    second = observation(t1 + timedelta(seconds=15), status=403, headers={"server": "NGINX", "x-proxy-cache-info": "DT:9", "age": "19"})
    stable = cache._stable_public_observation(first, evidence())
    assert stable["response_classification"] == "provider_verified_status_blocked"
    assert stable["body_sha256"] is None
    assert cache._stable_public_observation_fingerprint(first, evidence()) == cache._stable_public_observation_fingerprint(second, evidence())


@pytest.mark.parametrize(
    ("before_changes", "after_changes", "expected"),
    [
        ({}, {"final_url": "https://example.com/"}, "public_url_drift"),
        ({}, {"redirect_count": 1}, "stable_public_observation_mismatch"),
        ({}, {"cache_headers": {}}, "cache_provider_drift"),
        ({}, {"cache_headers": {"x-proxy-cache": "MISS"}}, "cache_provider_drift"),
        ({}, {"challenge_page_detected": True}, "stable_public_observation_mismatch"),
        ({}, {"body_sha256": "9" * 64}, "public_identity_drift"),
        ({}, {"parsed": {"meta": [{"name": "description", "content": "drift"}]}}, "public_identity_drift"),
    ],
)
def test_stable_drift_categories_fail_closed(before_changes, after_changes, expected):
    now = datetime(2026, 7, 19, 6, 10, tzinfo=UTC)
    before = cache._stable_public_observation(observation(now, **before_changes), evidence())
    after = cache._stable_public_observation(observation(now + timedelta(seconds=1), **after_changes), evidence())
    assert cache._stable_observation_conflict(before, after) == expected


def test_signed_page_identity_drift_is_rejected():
    now = datetime(2026, 7, 19, 6, 15, tzinfo=UTC)
    before_evidence = evidence()
    after_evidence = evidence(page_identity={**before_evidence.page_identity, "h1": "Changed"})
    before = cache._stable_public_observation(observation(now), before_evidence)
    after = cache._stable_public_observation(observation(now + timedelta(seconds=1)), after_evidence)
    assert cache._stable_observation_conflict(before, after) == "public_identity_drift"


def temporal_result(*, preflight_offset=0, apply_offset=10, evidence_offset=60, handle_offset=60, backup_offset=60, now_offset=10):
    base = datetime(2026, 7, 19, 6, 20, tzinfo=UTC)
    return cache._temporal_conflict(
        preflight_observed_at=base + timedelta(seconds=preflight_offset),
        apply_observed_at=base + timedelta(seconds=apply_offset),
        evidence_expires_at=base + timedelta(seconds=evidence_offset),
        handle_expires_at=base + timedelta(seconds=handle_offset),
        backup_deadline=base + timedelta(seconds=backup_offset),
        now=base + timedelta(seconds=now_offset),
    )


def test_temporal_contract_accepts_later_observation_inside_every_window():
    assert temporal_result() is None
    assert cache.BINDING_REASON_CODES == {
        "stable_public_observation_mismatch", "public_observation_expired",
        "apply_observation_before_preflight", "observation_window_exceeded",
        "cache_provider_drift", "public_url_drift",
        "volatile_timestamp_change_allowed", "volatile_cache_age_change_allowed",
        "public_identity_drift",
    }


@pytest.mark.parametrize(
    ("failed_code", "expected"),
    [
        ("public_observation_fresh", "public_observation_expired"),
        ("evidence", "public_observation_expired"),
        ("cache_provider_unrecognized", "cache_provider_drift"),
        ("browser_public_state_verified", "public_identity_drift"),
        ("page", "stable_public_observation_mismatch"),
    ],
)
def test_failed_rerun_gates_map_to_safe_conflict_categories(failed_code, expected):
    gates = [SimpleNamespace(code=failed_code, passed=False)]
    assert cache._preflight_conflict_code(gates) == expected


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"apply_offset": -2, "now_offset": 0}, "apply_observation_before_preflight"),
        ({"apply_offset": 121, "evidence_offset": 300, "handle_offset": 300, "backup_offset": 300, "now_offset": 121}, "observation_window_exceeded"),
        ({"evidence_offset": 5}, "public_observation_expired"),
        ({"handle_offset": 5}, "public_observation_expired"),
        ({"backup_offset": 5}, "public_observation_expired"),
        ({"apply_offset": 20, "now_offset": 10}, "public_observation_expired"),
    ],
)
def test_temporal_contract_fails_closed(kwargs, expected):
    assert temporal_result(**kwargs) == expected


def test_rendering_and_cache_bindings_ignore_apply_time_but_bind_original_time():
    t1 = datetime(2026, 7, 19, 6, 30, tzinfo=UTC)
    t2 = t1 + timedelta(seconds=30)
    first = observation(t1)
    second = observation(t2, headers={**first["cache_headers"], "age": "42"})
    stable_first = cache._stable_public_observation_fingerprint(first)
    stable_second = cache._stable_public_observation_fingerprint(second)
    assert stable_first == stable_second
    audit = SimpleNamespace(id=1, status="origin_verified")
    status = {"plugin": cache.PLUGIN_SLUG, "version": cache.PLUGIN_VERSION, "active": True}
    preview = {"cache_provider": cache.CACHE_PROVIDER, "cache_purge_available": True, "cache_purge_scope": cache.CACHE_SCOPE}
    expiry = t1 + timedelta(minutes=5)
    backup = t1 + timedelta(hours=1)
    assert cache._cache_binding_hash(audit=audit, status=status, preview=preview, stable_public_fingerprint=stable_first, preflight_observed_at=t1, expires_at=expiry, backup_deadline=backup) == cache._cache_binding_hash(audit=audit, status=status, preview=preview, stable_public_fingerprint=stable_second, preflight_observed_at=t1, expires_at=expiry, backup_deadline=backup)
    browser = SimpleNamespace(
        evidence_id="evidence-one",
        evidence_schema_version=1,
        rendered_head_hash="d" * 64,
        visible_content_hash="e" * 64,
        captured_at=t1 - timedelta(minutes=1),
        expires_at=expiry,
    )
    request = SimpleNamespace(
        manual_browser_evidence=browser,
        model_dump=lambda **_: {"locked_request": True},
    )
    rendering_args = {
        "snapshot": status,
        "artifact": {"valid": True, "zip_sha256": cache.PLUGIN_ZIP_SHA256},
        "page_media": {"page_body_hash": cache.EXPECTED_CORRECTED_BODY_HASH},
        "audit_history": {"staging": {"id": 2, "status": "verified"}, "recovery_disable": {"id": 4, "status": "verified"}},
        "preflight_observed_at": t1,
        "expires_at": expiry,
        "backup_deadline": backup,
    }
    assert cache._rendering_binding_hash(request, stable_public_fingerprint=stable_first, **rendering_args) == cache._rendering_binding_hash(request, stable_public_fingerprint=stable_second, **rendering_args)


def test_callers_cannot_inject_observation_timestamp_or_fingerprint():
    with pytest.raises(ValidationError):
        WordPressCachePurgePreflightRequest.model_validate({
            "cache_aware_audit_id": 1,
            "observed_at": "2026-07-19T06:00:00.000000Z",
            "stable_public_observation_fingerprint": "a" * 64,
        })
    fields = WordPressCacheAwareRenderingPreflightRequest.model_fields
    assert "observed_at" not in fields
    assert "stable_public_observation_fingerprint" not in fields


def test_apply_paths_rerun_gates_and_final_public_403_remains_rejected():
    rendering_source = inspect.getsource(cache.rendering_apply)
    cache_source = inspect.getsource(cache.cache_apply)
    assert "rendering_preflight(" in rendering_source
    assert "cache_preflight(" in cache_source
    assert "_temporal_conflict(" in rendering_source and "_stable_observation_conflict(" in rendering_source
    assert "_temporal_conflict(" in cache_source and "_stable_observation_conflict(" in cache_source
    assert rendering_source.count("_send_rendering_enable(session, before)") == 1
    assert cache_source.count("_send_cache_purge(session)") == 1
    assert cache._public_exact(observation(datetime.now(UTC), status=403))[0] is False
