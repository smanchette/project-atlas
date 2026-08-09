from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from urllib.parse import urlsplit

from app.models import ImageMetadata, Website


@dataclass(frozen=True)
class WebsiteExternalMediaPolicy:
    """Immutable, source-controlled safety policy for one exact Website identity."""

    website_id: int
    business_id: int
    brand_id: int
    website_name: str
    expected_website_domain: str
    expected_website_public_origin: str
    expected_configuration_identity: tuple[tuple[str, str], ...]
    wordpress_source_origin: str
    version: int
    excluded_wordpress_media_ids: frozenset[int]
    reason: str


_WEBSITE_POLICIES = (
    WebsiteExternalMediaPolicy(
        website_id=1,
        business_id=1,
        brand_id=1,
        website_name="flo-zone tenting",
        expected_website_domain="www.flo-zonetenting.com",
        expected_website_public_origin="https://www.flo-zonetenting.com",
        expected_configuration_identity=(
            ("short_brand_name", "flo-zone"),
            (
                "why_knowledge_slug",
                "why-fumigation-is-most-complete-drywood-termite-treatment",
            ),
        ),
        wordpress_source_origin="https://www.drywoodtenting.com",
        version=1,
        excluded_wordpress_media_ids=frozenset({32}),
        reason=(
            "Operator-approved Flo-Zone external-media safety exclusion; WordPress "
            "attachment 32 must never be selected, reconciled, assigned, or rendered."
        ),
    ),
)


def website_external_media_policy(
    website: Website | None,
) -> WebsiteExternalMediaPolicy | None:
    if website is None:
        return None
    domain = _normalize_domain(website.domain)
    origin = _normalize_origin(website.public_url)
    name = _normalize_text(website.website_name)
    for policy in _WEBSITE_POLICIES:
        configuration = website.configuration or {}
        durable_configuration_identity_matches = all(
            _normalize_text(configuration.get(key)) == expected
            for key, expected in policy.expected_configuration_identity
        )
        stable_identity_matches = (
            domain == policy.expected_website_domain
            and origin == policy.expected_website_public_origin
            and name == policy.website_name
        )
        if durable_configuration_identity_matches or stable_identity_matches:
            return policy
    return None


def excluded_wordpress_media_ids(website: Website | None) -> frozenset[int]:
    policy = website_external_media_policy(website)
    return policy.excluded_wordpress_media_ids if policy else frozenset()


def is_wordpress_media_excluded(
    website: Website | None,
    wordpress_media_id: int | None,
) -> bool:
    return bool(
        wordpress_media_id is not None
        and wordpress_media_id in excluded_wordpress_media_ids(website)
    )


def is_image_metadata_excluded(
    website: Website | None,
    image: ImageMetadata | None,
) -> bool:
    return bool(
        image
        and is_wordpress_media_excluded(website, image.wordpress_media_id)
    )


def filter_wordpress_media_ids(
    website: Website | None,
    media_ids: tuple[int, ...] | list[int],
) -> tuple[int, ...]:
    excluded = excluded_wordpress_media_ids(website)
    return tuple(media_id for media_id in media_ids if media_id not in excluded)


def wordpress_source_matches_policy(
    website: Website | None,
    source_url: str | None,
) -> bool:
    policy = website_external_media_policy(website)
    if policy is None or not website_external_media_identity_is_exact(website, policy):
        return False
    if not source_url:
        return False
    return _normalize_origin(source_url) == policy.wordpress_source_origin


def website_external_media_identity_is_exact(
    website: Website | None,
    policy: WebsiteExternalMediaPolicy | None = None,
) -> bool:
    if website is None:
        return False
    policy = policy or website_external_media_policy(website)
    if policy is None:
        return False
    return bool(
        website.id == policy.website_id
        and website.business_id == policy.business_id
        and website.brand_id == policy.brand_id
        and _normalize_text(website.website_name) == policy.website_name
        and _normalize_domain(website.domain) == policy.expected_website_domain
        and _normalize_origin(website.public_url)
        == policy.expected_website_public_origin
    )


def website_external_media_policy_snapshot(website: Website | None) -> dict[str, object]:
    policy = website_external_media_policy(website)
    if policy is None:
        payload: dict[str, object] = {
            "scope": "website_identity",
            "observed_website_id": website.id if website else None,
            "version": 1,
            "excluded_wordpress_media_ids": [],
        }
    else:
        domain = _normalize_domain(website.domain)
        origin = _normalize_origin(website.public_url)
        name = _normalize_text(website.website_name)
        payload = {
            "scope": "website_identity",
            "website_id": policy.website_id,
            "business_id": policy.business_id,
            "brand_id": policy.brand_id,
            "observed_website_id": website.id,
            "observed_business_id": website.business_id,
            "observed_brand_id": website.brand_id,
            "website_name": policy.website_name,
            "expected_website_domain": policy.expected_website_domain,
            "expected_website_public_origin": policy.expected_website_public_origin,
            "expected_configuration_identity": dict(
                policy.expected_configuration_identity
            ),
            "observed_website_domain": domain,
            "observed_website_public_origin": origin,
            "identity_status": (
                "exact"
                if website_external_media_identity_is_exact(website, policy)
                else "drifted_fail_closed"
            ),
            "wordpress_source_origin": policy.wordpress_source_origin,
            "version": policy.version,
            "excluded_wordpress_media_ids": sorted(
                policy.excluded_wordpress_media_ids
            ),
            "reason": policy.reason,
        }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {**payload, "fingerprint": hashlib.sha256(encoded).hexdigest()}


def _normalize_domain(value: str | None) -> str:
    cleaned = (value or "").strip().lower().rstrip(".")
    if "://" in cleaned:
        parsed = urlsplit(cleaned)
        cleaned = (parsed.hostname or "").lower().rstrip(".")
    return cleaned


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _normalize_origin(value: str | None) -> str:
    parsed = urlsplit((value or "").strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    authority = host if port is None or default_port else f"{host}:{port}"
    return f"{scheme}://{authority}"
