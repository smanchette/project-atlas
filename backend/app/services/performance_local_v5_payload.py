from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
from typing import Any
from urllib.parse import urlsplit

from sqlmodel import Session, select

from app.models import (
    Brand,
    BrandAsset,
    Business,
    GeneratedPage,
    GeneratedPageRevision,
    ImageMetadata,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    ThemeFamily,
    ThemeFamilyVersion,
    Website,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
)
from app.schemas.performance_local_v5 import (
    PerformanceLocalV5LogoIdentity,
    PerformanceLocalV5MediaIdentity,
    PerformanceLocalV5PayloadBuild,
    PerformanceLocalV5SourceBindings,
    PerformanceLocalV5UnavailablePayloadIdentity,
)
from app.services import theme_configurations as theme_service
from app.services.page_composition import (
    PageCompositionError,
    read_composition_for_generated_page,
)
from app.services.page_composition_history import (
    PageCompositionHistoryError,
    current_composition_revision,
)
from app.services.page_qa import effective_page_qa_state
from app.services.scoped_media_authorizations import (
    ScopedMediaAuthorizationError,
    current_scoped_media_authorization,
    scoped_media_authorization_errors,
)


PERFORMANCE_LOCAL_V5_SCHEMA = "project-atlas-performance-local-v5-wordpress@1"
PERFORMANCE_LOCAL_V5_META_KEY = "_project_atlas_performance_local_v5_v1"
PERFORMANCE_LOCAL_V5_TEMPLATE_PATH = (
    "project-atlas-metadata-bridge/templates/performance-local-v5-page.php"
)
PERFORMANCE_LOCAL_V5_CANONICAL_JSON_CONTRACT = (
    "sorted-object-keys|preserved-list-order|utf8|compact|unicode-unescaped"
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SAFE_BASENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CONTROL_OR_HTML = re.compile(r"[\x00-\x1f\x7f<>]")
_PRIVATE_DELIVERY_KEYS = frozenset({"recipient_email", "from_email"})
_FORM_COMPONENT_KEYS = frozenset(
    {"campaign_banner", "compact_estimate_form", "sticky_mobile_action_bar"}
)
_ESTIMATE_DESTINATION = "/request-an-estimate/"


class PerformanceLocalV5PayloadError(ValueError):
    """Fail-closed current-state V5 payload construction error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 409,
        code: str = "performance_local_v5_payload_blocked",
        required_media: list[PerformanceLocalV5MediaIdentity] | None = None,
        required_logo_media: list[PerformanceLocalV5LogoIdentity] | None = None,
        source_identity: PerformanceLocalV5UnavailablePayloadIdentity | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.required_media = list(required_media or [])
        self.required_logo_media = list(required_logo_media or [])
        self.source_identity = source_identity


def canonical_performance_local_v5_json(value: Any) -> bytes:
    """Canonical bytes shared exactly with the Bridge's PHP JSON hash."""

    return _canonical_performance_local_v5_json_text(value).encode("utf-8")


def _canonical_performance_local_v5_json_text(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    if type(value) is int:
        return str(value)
    if type(value) is float:
        return _php_json_float(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(
            _canonical_performance_local_v5_json_text(item) for item in value
        ) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Canonical V5 JSON object keys must be strings.")
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False, allow_nan=False)
            + ":"
            + _canonical_performance_local_v5_json_text(value[key])
            for key in sorted(value)
        ) + "}"
    raise TypeError(
        f"Canonical V5 JSON cannot encode {type(value).__name__}."
    )


def _php_json_float(value: float) -> str:
    """Match PHP ``json_encode`` float tokens under preserve-zero-fraction."""

    if not math.isfinite(value):
        raise ValueError("Canonical V5 JSON rejects non-finite numbers.")
    encoded = repr(value).lower()
    if "e" not in encoded:
        return encoded
    mantissa, exponent = encoded.split("e", 1)
    if "." not in mantissa:
        mantissa += ".0"
    sign = ""
    if exponent[0] in "+-":
        sign = exponent[0]
        exponent = exponent[1:]
    exponent = exponent.lstrip("0") or "0"
    return f"{mantissa}e{sign}{exponent}"


def performance_local_v5_payload_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_performance_local_v5_json(value)).hexdigest()


def build_performance_local_v5_staging_payload(
    session: Session,
    page_id: int,
) -> PerformanceLocalV5PayloadBuild:
    """Build one canonical current City-Service -> WordPress V5 metadata value.

    The function is deliberately independent of durable V5 registration so a
    candidate can be validated while the separately governed registration plan
    remains blocked. It neither flushes nor commits.
    """

    pending_before = _pending_identity(session)
    try:
        with session.no_autoflush:
            result = _build(session, page_id)
    except (PageCompositionError, PageCompositionHistoryError, ValueError) as exc:
        if isinstance(exc, PerformanceLocalV5PayloadError):
            raise
        raise PerformanceLocalV5PayloadError(str(exc)) from exc
    if _pending_identity(session) != pending_before:
        raise PerformanceLocalV5PayloadError(
            "V5 payload construction attempted to stage an Atlas write.",
            code="performance_local_v5_payload_write_detected",
        )
    return result


def inspect_performance_local_v5_media_identities(
    session: Session,
    page_id: int,
) -> list[PerformanceLocalV5MediaIdentity]:
    """Read exact page-media/auth identities even when remote sync is absent."""

    page = session.get(GeneratedPage, page_id)
    if page is None or page.id is None or page.page_type != "city_service":
        raise PerformanceLocalV5PayloadError(
            "Media inspection requires an existing City-Service Generated Page.",
            status_code=422,
        )
    planned = _exactly_one(
        list(
            session.exec(
                select(PlannedPage).where(PlannedPage.generated_page_id == page.id)
            ).all()
        ),
        "current Planned Page",
    )
    resolved = read_composition_for_generated_page(session, page.id)
    return _current_media_identities(
        session,
        page=page,
        planned=planned,
        resolved_components=resolved.effective_components,
    )


def _build(session: Session, page_id: int) -> PerformanceLocalV5PayloadBuild:
    page = session.get(GeneratedPage, page_id)
    if page is None or page.id is None:
        raise PerformanceLocalV5PayloadError(
            "The requested Generated Page was not found.",
            status_code=404,
            code="performance_local_v5_page_not_found",
        )
    if page.page_type != "city_service":
        raise PerformanceLocalV5PayloadError(
            "Performance Local V5 staging accepts only a City-Service page.",
            code="performance_local_v5_page_type_blocked",
        )
    if type(page.wordpress_post_id) is not int or page.wordpress_post_id <= 0:
        raise PerformanceLocalV5PayloadError(
            "The Generated Page has no exact positive WordPress post binding.",
            code="performance_local_v5_wordpress_target_mismatch",
        )
    if page.website_id is None:
        raise PerformanceLocalV5PayloadError("Generated Page has no Website binding.")

    website = _record(session, Website, page.website_id, "Website")
    business = _record(session, Business, page.business_id, "Business")
    if website.business_id != business.id or website.status != "active":
        raise PerformanceLocalV5PayloadError(
            "Generated Page Website/Business ownership is not current and exact."
        )
    if website.brand_id is None:
        raise PerformanceLocalV5PayloadError("The Website has no governed Brand.")
    brand = _record(session, Brand, website.brand_id, "Brand")
    if brand.business_id != business.id or brand.status != "active":
        raise PerformanceLocalV5PayloadError("The governed Brand scope is invalid.")

    planned_rows = list(
        session.exec(
            select(PlannedPage).where(PlannedPage.generated_page_id == page.id)
        ).all()
    )
    planned = _exactly_one(planned_rows, "current Planned Page")
    if (
        planned.id is None
        or planned.website_id != website.id
        or planned.page_type != page.page_type
        or planned.intended_slug != page.page_slug
    ):
        raise PerformanceLocalV5PayloadError("The Planned Page scope is not exact.")

    qa_state = effective_page_qa_state(session, page)
    if not qa_state.ready or qa_state.record is None or qa_state.record.id is None:
        raise PerformanceLocalV5PayloadError(
            "The page lacks one current, exact, warning-free ready QA result.",
            code="performance_local_v5_qa_stale",
        )
    qa = qa_state.record
    if qa.latest_generated_page_revision_id is None:
        raise PerformanceLocalV5PayloadError("Current QA has no Generated Page revision.")
    page_revision = _record(
        session,
        GeneratedPageRevision,
        qa.latest_generated_page_revision_id,
        "Generated Page revision",
    )
    if page_revision.generated_page_id != page.id:
        raise PerformanceLocalV5PayloadError("Generated Page revision crosses page scope.")

    composition_rows = list(
        session.exec(
            select(PageComposition).where(PageComposition.generated_page_id == page.id)
        ).all()
    )
    composition = _exactly_one(composition_rows, "Page Composition")
    if composition.id is None or composition.status != "current":
        raise PerformanceLocalV5PayloadError("The page Composition is not current.")
    composition_revision = current_composition_revision(session, composition)
    if composition_revision.id is None:
        raise PerformanceLocalV5PayloadError("Composition revision identity is missing.")
    if (
        composition_revision.generated_page_revision_id != page_revision.id
        or qa.page_composition_id != composition.id
        or qa.composition_version != composition.composition_version
        or qa.composition_source_hash != composition.source_hash
    ):
        raise PerformanceLocalV5PayloadError(
            "QA, Generated Page revision, and Composition head are not the same current state.",
            code="performance_local_v5_source_binding_stale",
        )

    resolved = read_composition_for_generated_page(session, page.id)
    components = {
        item.instance_key: item.resolved_data for item in resolved.effective_components
    }
    if len(components) != len(resolved.effective_components):
        raise PerformanceLocalV5PayloadError("Composition instance keys are not unique.")
    header = _component(components, "website_header")
    footer_source = _component(components, "website_footer")
    _require_public_identity(header, business, brand)

    form_components, form_configuration = _current_governed_form_components(
        session, website.id
    )
    form_source = form_components["compact_estimate_form"].configuration_payload
    action_source = form_components["sticky_mobile_action_bar"].configuration_payload
    form = _form_payload(form_source)
    call_label = _text(action_source.get("call_label"), "call label")
    estimate_action = _approved_estimate_action(form_components)
    estimate_label = estimate_action["label"]
    phone_href = _phone_href(business.phone)

    source_bindings = PerformanceLocalV5SourceBindings(
        generated_page_revision_id=page_revision.id,
        generated_page_revision_hash=_sha(
            page_revision.draft_hash_after, "Generated Page revision hash"
        ),
        page_composition_id=composition.id,
        composition_version=composition.composition_version,
        page_composition_revision_id=composition_revision.id,
        page_composition_revision_hash=_sha(
            composition_revision.revision_hash, "Composition revision hash"
        ),
        composition_source_hash=_sha(
            composition.source_hash, "Composition source hash"
        ),
        qa_result_id=qa.id,
        qa_result_hash=_sha(qa.result_hash, "QA result hash"),
    )
    unavailable_identity = PerformanceLocalV5UnavailablePayloadIdentity(
        website_id=website.id,
        planned_page_id=planned.id,
        generated_page_id=page.id,
        wordpress_post_id=page.wordpress_post_id,
        source_bindings=source_bindings,
    )

    media_identities = _current_media_identities(
        session,
        page=page,
        planned=planned,
        resolved_components=resolved.effective_components,
    )
    logo_identities = _current_logo_identities(
        session,
        website=website,
        brand=brand,
        header=header,
        footer=footer_source,
    )
    missing_media = [item for item in media_identities if not item.ready]
    unusable_logo_paths = [
        item for item in logo_identities if item.payload_src is None
    ]
    if missing_media or unusable_logo_paths:
        raise PerformanceLocalV5PayloadError(
            "One or more governed page-media identities require exact remote "
            "media sync, or a governed Brand-Asset path cannot satisfy the "
            "Bridge contract.",
            code="REMOTE_MEDIA_SYNC_REQUIRED",
            required_media=media_identities,
            required_logo_media=logo_identities,
            source_identity=unavailable_identity,
        )
    media_by_target = _media_components_by_target(resolved.effective_components)
    media_identity_by_target = {
        item.target_component_instance_key: item for item in media_identities
    }
    logo_identity_by_role = {item.role: item for item in logo_identities}

    page_h1 = _text(page.h1, "Page H1")
    hero_source = _component(components, "hero")
    if (
        hero_source.get("title") != page_h1
        or hero_source.get("page_type") != page.page_type
        or hero_source.get("phone") != business.phone
    ):
        raise PerformanceLocalV5PayloadError(
            "The resolved hero differs from current governed Page/contact state."
        )

    sections: list[dict[str, Any]] = []
    for instance_key, media_instance in (
        ("service_summary:why_it_matters", "service_summary:why_it_matters"),
        ("content_section:signs_section", "content_section:signs_section"),
        ("content_section:process_section", None),
        ("content_section:prep_section", None),
        ("content_section:realtor_property_manager_section", None),
    ):
        source = _component(components, instance_key)
        media_source = media_by_target[media_instance] if media_instance else None
        sections.append(
            {
                "key": _text(source.get("key"), f"{instance_key} key"),
                "heading": _text(source.get("heading"), f"{instance_key} heading"),
                "body": _text(source.get("body"), f"{instance_key} body"),
                "media": (
                    _media(
                        media_source,
                        media_identity_by_target[media_instance].payload_src,
                    )
                    if media_source and media_instance
                    else None
                ),
            }
        )
    final_cta = _component(components, "final_cta")
    current_cta = (page.draft_content or {}).get("call_to_action")
    if final_cta.get("body") != current_cta:
        raise PerformanceLocalV5PayloadError(
            "The resolved final conversion differs from the current governed CTA."
        )
    sections.append(
        {
            "key": "final_conversion",
            "heading": _text(final_cta.get("heading"), "final conversion heading"),
            "body": _text(final_cta.get("body"), "final conversion body"),
            "media": None,
        }
    )

    related_source = _component(components, "destination_cards")
    related_pages = [
        {
            "label": _text(item.get("label"), "related-page label"),
            "href": _internal_href(item.get("slug"), "related-page slug"),
            "relationship_type": _text(
                item.get("relationship_type"), "related-page relationship"
            ),
        }
        for item in _objects(related_source.get("links"), "related-page links")
    ]
    faq_source = _component(components, "faq")
    faq = [
        {
            "question": _text(item.get("question"), "FAQ question"),
            "answer": _text(item.get("answer"), "FAQ answer"),
        }
        for item in _objects(faq_source.get("items"), "FAQ items")
    ]

    utility = _component(components, "utility_navigation")
    primary = _component(components, "primary_navigation")
    footer_navigation = _component(components, "footer_navigation")
    resolved_theme = _object(resolved.resolved_theme, "resolved Theme")
    if resolved_theme.get("fallback_used") is not False:
        raise PerformanceLocalV5PayloadError("The current Composition uses fallback Theme tokens.")
    source_theme = _object(resolved_theme.get("source_identity"), "Theme identity")
    effective_tokens = _object(resolved_theme.get("effective_tokens"), "Theme tokens")

    payload_identity_inputs = [
        {
            "path": f"atlas/planned-page/{planned.id}",
            "sha256": performance_local_v5_payload_sha256(
                _planned_page_identity(planned)
            ),
        },
        {
            "path": f"atlas/generated-page-revision/{page_revision.id}",
            "sha256": _sha(page_revision.draft_hash_after, "Generated Page revision hash"),
        },
        {
            "path": f"atlas/page-composition-revision/{composition_revision.id}",
            "sha256": _sha(composition_revision.revision_hash, "Composition revision hash"),
        },
        {
            "path": f"atlas/generated-page-qa-result/{qa.id}",
            "sha256": _sha(qa.result_hash, "QA result hash"),
        },
        {
            "path": f"atlas/website/{website.id}",
            "sha256": performance_local_v5_payload_sha256(_website_identity(website)),
        },
        {
            "path": f"atlas/business/{business.id}",
            "sha256": performance_local_v5_payload_sha256(_business_identity(business)),
        },
        {
            "path": f"atlas/brand/{brand.id}",
            "sha256": performance_local_v5_payload_sha256(_brand_identity(brand)),
        },
        {
            "path": f"atlas/website-theme-configuration/{form_configuration.id}",
            "sha256": _sha(
                form_configuration.integrity_fingerprint,
                "governed form configuration fingerprint",
            ),
        },
        *[
            {
                "path": f"atlas/website-theme-component-configuration/{item.id}",
                "sha256": _sha(
                    item.integrity_fingerprint,
                    f"{item.component_key} component fingerprint",
                ),
            }
            for item in sorted(form_components.values(), key=lambda value: value.id or 0)
        ],
        *[
            {
                "path": f"atlas/image-metadata/{item.image_metadata_id}",
                "sha256": item.checksum_sha256,
            }
            for item in media_identities
        ],
        *[
            {
                "path": f"atlas/brand-asset/{item.brand_asset_id}",
                "sha256": item.checksum_sha256,
            }
            for item in {
                value.brand_asset_id: value for value in logo_identities
            }.values()
        ],
        *[
            {
                "path": f"atlas/scoped-media-authorization/{item.authorization_id}",
                "sha256": item.authorization_fingerprint,
            }
            for item in media_identities
        ],
    ]

    payload = {
        "schema_version": PERFORMANCE_LOCAL_V5_SCHEMA,
        "surface": "city_service",
        # This field is retained by the already-installed exact Bridge schema;
        # environment authorization is enforced independently by the Bridge.
        "rehearsal_only": True,
        "payload_identity": {
            "fixture_key": "city_service",
            "source_page": f"generated-page:{page.id}",
            "source_composition": (
                f"composition:{composition.id}:v{composition.composition_version}"
            ),
            "source_hash": _sha(composition.source_hash, "Composition source hash"),
            "frozen_inputs": payload_identity_inputs,
        },
        "website": {
            "identity": f"website:{website.id}",
            "display_name": _text(header.get("display_name"), "Website display name"),
            "company_name": _text(business.company_name, "company name"),
            "tagline": _text(brand.tagline, "Brand tagline"),
            "phone_display": _text(business.phone, "public phone"),
            "phone_href": phone_href,
            "contact_email": _optional_email(business.email),
            "header_logo": _logo(
                header,
                "header_logo",
                logo_identity_by_role["header_logo"].payload_src,
            ),
            "footer_logo": _logo(
                footer_source,
                "footer_logo",
                logo_identity_by_role["footer_logo"].payload_src,
            ),
        },
        "navigation": {
            "utility": _navigation_items(utility),
            "primary": _navigation_items(primary),
            "mobile_label": "Menu",
        },
        "page": {
            "page_type": "city_service",
            "title": _text(page.page_title, "Page title"),
            "slug": _slug(page.page_slug, "Page slug"),
            "meta_title": _text(page.meta_title, "meta title"),
            "meta_description": _text(page.meta_description, "meta description"),
            "h1": page_h1,
        },
        "sticky_action": {
            "phone": {"label": call_label, "href": phone_href},
            "action": {
                "mode": "estimate",
                "label": estimate_label,
                "href": estimate_action["href"],
            },
        },
        "hero": {
            "eyebrow": "City Service",
            "h1": page_h1,
            "introduction": _text(hero_source.get("intro"), "hero introduction"),
            "media": _media(
                media_by_target["hero"],
                media_identity_by_target["hero"].payload_src,
            ),
            "call_action": {"label": call_label, "href": phone_href},
            "estimate_action": {
                "label": estimate_label,
                "href": estimate_action["href"],
            },
        },
        "sections": sections,
        "related_pages": related_pages,
        "faq": faq,
        "optional_modules": {"review_trust": None, "location_map": None},
        "form": form,
        "conditional": {"estimate": None, "special": None},
        "footer": {
            "navigation": _footer_navigation_items(footer_navigation),
            "company_name": _text(business.company_name, "footer company name"),
            "phone_display": _text(business.phone, "footer phone"),
            "contact_email": _optional_email(business.email),
            "logo": _logo(
                footer_source,
                "footer_logo",
                logo_identity_by_role["footer_logo"].payload_src,
            ),
        },
        "theme": {
            "family": "performance-local",
            "version": 5,
            "source_theme": {
                "key": _text(source_theme.get("theme_key"), "source Theme key"),
                "version": _positive_int(
                    source_theme.get("theme_version"), "source Theme version"
                ),
                "token_contract_version": _positive_int(
                    source_theme.get("token_contract_version"),
                    "source Theme token contract",
                ),
                "token_hash_sha256": _sha(
                    source_theme.get("token_hash_sha256"), "source Theme token hash"
                ),
            },
            "tokens": deepcopy(effective_tokens),
        },
    }
    _reject_private_delivery(payload)
    payload_sha256 = performance_local_v5_payload_sha256(payload)
    return PerformanceLocalV5PayloadBuild(
        website_id=website.id,
        planned_page_id=planned.id,
        generated_page_id=page.id,
        wordpress_post_id=page.wordpress_post_id,
        metadata_key=PERFORMANCE_LOCAL_V5_META_KEY,
        payload_schema=PERFORMANCE_LOCAL_V5_SCHEMA,
        template_value=None,
        template_path=PERFORMANCE_LOCAL_V5_TEMPLATE_PATH,
        payload=payload,
        payload_sha256=payload_sha256,
        source_bindings=source_bindings,
        required_media=media_identities,
        required_logo_media=logo_identities,
    )


def _current_governed_form_components(
    session: Session,
    website_id: int,
) -> tuple[dict[str, WebsiteThemeComponentConfiguration], WebsiteThemeConfiguration]:
    # Import locally to keep the pure payload primitives usable without a
    # module-initialization cycle. The plan is read-only and is the canonical
    # all-missing/exact/conflict decision for durable V5 state.
    from app.services.performance_local_v5_registration import (
        PERFORMANCE_LOCAL_V5_CONFIGURATION_KEY,
        plan_performance_local_v5_registration,
    )

    registration = plan_performance_local_v5_registration(session, website_id)
    if registration.status == "CONFLICT":
        raise PerformanceLocalV5PayloadError(
            "Durable Performance Local V5 state is partial or conflicting: "
            + "; ".join(registration.blockers),
            code="performance_local_v5_registration_conflict",
        )
    contract_version = 5 if registration.status == "UNCHANGED" else 3
    statement = (
        select(WebsiteThemeComponentConfiguration)
        .join(
            WebsiteThemeConfiguration,
            WebsiteThemeConfiguration.id
            == WebsiteThemeComponentConfiguration.website_theme_configuration_id,
        )
        .join(
            ThemeFamilyVersion,
            ThemeFamilyVersion.id
            == WebsiteThemeComponentConfiguration.theme_family_version_id,
        )
        .join(ThemeFamily, ThemeFamily.id == ThemeFamilyVersion.theme_family_id)
        .where(
            WebsiteThemeComponentConfiguration.website_id == website_id,
            WebsiteThemeComponentConfiguration.lifecycle_status == "current",
            WebsiteThemeComponentConfiguration.component_key.in_(_FORM_COMPONENT_KEYS),
            ThemeFamily.family_key == "performance-local",
            ThemeFamilyVersion.version == contract_version,
        )
    )
    if registration.status == "UNCHANGED":
        statement = statement.where(
            WebsiteThemeConfiguration.id
            == registration.identity.website_theme_configuration_id,
            WebsiteThemeConfiguration.configuration_key
            == PERFORMANCE_LOCAL_V5_CONFIGURATION_KEY,
            WebsiteThemeConfiguration.lifecycle_status == "active",
        )
    else:
        statement = statement.where(
            WebsiteThemeConfiguration.lifecycle_status.in_(
                {"draft", "approved", "active"}
            )
        )
    rows = list(session.exec(statement).all())
    if len(rows) != 3 or {item.component_key for item in rows} != _FORM_COMPONENT_KEYS:
        raise PerformanceLocalV5PayloadError(
            f"The current governed V{contract_version} form/action graph is not one exact three-node graph.",
            code="performance_local_v5_form_graph_blocked",
        )
    configuration_ids = {item.website_theme_configuration_id for item in rows}
    if len(configuration_ids) != 1:
        raise PerformanceLocalV5PayloadError("Form/action components cross configurations.")
    configuration = _record(
        session,
        WebsiteThemeConfiguration,
        next(iter(configuration_ids)),
        "Website Theme configuration",
    )
    by_key = {item.component_key: item for item in rows}
    for item in rows:
        try:
            theme_service._validate_component_configuration(session, item)
        except theme_service.ThemeConfigurationError as exc:
            raise PerformanceLocalV5PayloadError(
                f"The governed V{contract_version} {item.component_key} component is invalid: {exc}",
                code="performance_local_v5_form_graph_blocked",
            ) from exc
        if (
            not item.enabled
            or item.component_contract_version != contract_version
            or item.scope_type != "website_default"
            or item.planned_page_id is not None
            or item.rollback_identity is not None
            or item.rollback_at is not None
        ):
            raise PerformanceLocalV5PayloadError(
                f"The governed V{contract_version} {item.component_key} component is not enabled and exact.",
                code="performance_local_v5_form_graph_blocked",
            )
    form_id = by_key["compact_estimate_form"].id
    if (
        form_id is None
        or by_key["compact_estimate_form"].destination_component_configuration_id
        is not None
        or by_key["campaign_banner"].destination_component_configuration_id
        != form_id
        or by_key["sticky_mobile_action_bar"].destination_component_configuration_id
        != form_id
    ):
        raise PerformanceLocalV5PayloadError(
            "The governed conversion actions do not resolve the exact enabled estimate form.",
            code="performance_local_v5_form_graph_blocked",
        )
    if registration.status == "UNCHANGED" and (
        configuration.lifecycle_status != "active"
        or configuration.id
        != registration.identity.website_theme_configuration_id
        or configuration.materialized_theme_id
        != registration.identity.materialized_theme_id
        or configuration.website_theme_selection_id
        != registration.identity.website_theme_selection_id
    ):
        raise PerformanceLocalV5PayloadError(
            "The durable V5 form/action graph is not the exact active selected configuration.",
            code="performance_local_v5_form_graph_blocked",
        )
    return by_key, configuration


def _approved_estimate_action(
    components: dict[str, WebsiteThemeComponentConfiguration],
) -> dict[str, str]:
    form = components["compact_estimate_form"].configuration_payload
    banner = components["campaign_banner"].configuration_payload
    sticky = components["sticky_mobile_action_bar"].configuration_payload
    label = _text(sticky.get("estimate_label"), "estimate label")
    required_sticky_state = {
        "call_source": "governed_website_identity",
        "desktop_sticky_header": True,
        "mobile_sticky_bottom": True,
        "hide_while_hero_actions_visible": True,
        "hide_while_navigation_open": True,
        "protect_form_focus": True,
        "safe_area_support": True,
        "prevent_content_obstruction": True,
    }
    if any(sticky.get(key) != value for key, value in required_sticky_state.items()):
        raise PerformanceLocalV5PayloadError(
            "The governed sticky action is not the supported exact estimate-action policy.",
            code="performance_local_v5_action_blocked",
        )
    if (
        banner.get("intent") != "evergreen_conversion"
        or banner.get("cta_label") != label
        or form.get("submit_label") != label
    ):
        raise PerformanceLocalV5PayloadError(
            "The governed campaign, sticky action, and estimate form do not resolve one approved estimate action.",
            code="performance_local_v5_action_blocked",
        )
    return {"label": label, "href": _ESTIMATE_DESTINATION}


def _current_media_identities(
    session: Session,
    *,
    page: GeneratedPage,
    planned: PlannedPage,
    resolved_components: list[Any],
) -> list[PerformanceLocalV5MediaIdentity]:
    media_components = [
        item
        for item in resolved_components
        if item.component_key == "media_placement" and item.variant == "approved_media"
    ]
    identities: list[PerformanceLocalV5MediaIdentity] = []
    for component in media_components:
        requirement_id = component.input_bindings.get("media_requirement_id")
        assignment_id = component.input_bindings.get("page_image_assignment_id")
        if type(requirement_id) is not int or type(assignment_id) is not int:
            raise PerformanceLocalV5PayloadError("Governed media binding is incomplete.")
        requirement = _record(
            session, PlannedPageMediaRequirement, requirement_id, "media requirement"
        )
        assignment = _record(
            session, PageImageAssignment, assignment_id, "media assignment"
        )
        image = _record(
            session, ImageMetadata, assignment.image_metadata_id, "image metadata"
        )
        website = _record(session, Website, planned.website_id, "media Website")
        if (
            requirement.planned_page_id != planned.id
            or requirement.website_id != page.website_id
            or requirement.lifecycle_status != "active"
            or assignment.generated_page_id != page.id
            or assignment.planned_page_id != planned.id
            or assignment.media_requirement_id != requirement.id
            or assignment.status != "active"
            or image.website_id != page.website_id
            or image.governance_status != "approved"
            or image.checksum_sha256 is None
            or not isinstance(image.file_name, str)
            or not image.file_name.strip()
            or image.file_name != image.file_name.strip()
            or not isinstance(image.mime_type, str)
            or not image.mime_type.startswith("image/")
            or type(image.width) is not int
            or image.width <= 0
            or type(image.height) is not int
            or image.height <= 0
            or assignment.assignment_version is None
            or assignment.media_version != image.media_version
            or requirement.target_component_instance_key is None
            or image.media_key is None
            or image.media_version is None
        ):
            raise PerformanceLocalV5PayloadError(
                f"Media requirement {requirement_id} is not an exact current governed assignment."
            )
        try:
            authorization = current_scoped_media_authorization(
                session, requirement.id
            )
        except ScopedMediaAuthorizationError as exc:
            raise PerformanceLocalV5PayloadError(
                f"Media requirement {requirement_id} authorization lineage is invalid: {exc}"
            ) from exc
        if authorization is None or authorization.id is None:
            raise PerformanceLocalV5PayloadError(
                f"Media requirement {requirement_id} lacks a current scoped authorization."
            )
        authorization_errors = scoped_media_authorization_errors(
            session,
            authorization,
            asset=image,
            requirement=requirement,
            page=planned,
            website=website,
            assignment=assignment,
        )
        if authorization_errors:
            raise PerformanceLocalV5PayloadError(
                f"Media requirement {requirement_id} scoped authorization is stale: "
                + "; ".join(authorization_errors)
            )
        resolved = _object(component.resolved_data, "resolved media")
        if resolved.get("media_id") not in {None, image.id}:
            raise PerformanceLocalV5PayloadError("Resolved media identity changed.")
        wordpress_path = _verified_wordpress_media_path(image)
        identities.append(
            PerformanceLocalV5MediaIdentity(
                requirement_id=requirement.id,
                placement_key=requirement.placement_key,
                target_component_instance_key=requirement.target_component_instance_key,
                assignment_id=assignment.id,
                assignment_version=assignment.assignment_version,
                image_metadata_id=image.id,
                media_key=image.media_key,
                media_version=image.media_version,
                source_filename=_source_filename(image.file_name, "media source filename"),
                source_mime_type=_image_mime_type(
                    image.mime_type, "media source MIME type"
                ),
                source_width=image.width,
                source_height=image.height,
                checksum_sha256=_sha(image.checksum_sha256, "media checksum"),
                authorization_id=authorization.id,
                authorization_version=authorization.authorization_version,
                authorization_fingerprint=_sha(
                    authorization.authorization_fingerprint,
                    "scoped media authorization fingerprint",
                ),
                wordpress_media_id=image.wordpress_media_id,
                wordpress_media_url=image.wordpress_media_url,
                payload_src=wordpress_path,
                ready=wordpress_path is not None,
                blocker=(
                    None
                    if wordpress_path is not None
                    else "REMOTE_MEDIA_SYNC_REQUIRED"
                ),
            )
        )
    if len(identities) != 3:
        raise PerformanceLocalV5PayloadError(
            "The City-Service page requires exactly three governed V5 media assignments."
        )
    return sorted(identities, key=lambda item: item.requirement_id)


def _current_logo_identities(
    session: Session,
    *,
    website: Website,
    brand: Brand,
    header: dict[str, Any],
    footer: dict[str, Any],
) -> list[PerformanceLocalV5LogoIdentity]:
    identities: list[PerformanceLocalV5LogoIdentity] = []
    for role, source in (("header_logo", header), ("footer_logo", footer)):
        resolved_assets = _object(source.get("identity_assets"), "identity assets")
        resolved = _object(resolved_assets.get(role), f"identity asset {role}")
        asset_id = resolved.get("asset_id")
        if type(asset_id) is not int or asset_id <= 0:
            raise PerformanceLocalV5PayloadError(
                f"The governed {role} Brand Asset identity is missing.",
                code="performance_local_v5_logo_identity_blocked",
            )
        asset = _record(session, BrandAsset, asset_id, f"{role} Brand Asset")
        governed_url = asset.optimized_url or asset.asset_url
        if (
            asset.business_id != website.business_id
            or asset.brand_id != brand.id
            or asset.status != "approved"
            or not isinstance(asset.approved_by, str)
            or not asset.approved_by.strip()
            or asset.approved_at is None
            or resolved.get("asset_key") != asset.asset_key
            or resolved.get("version") != asset.version
            or resolved.get("asset_type") != asset.asset_type
            or resolved.get("asset_url") != governed_url
            or resolved.get("accessibility_description")
            != asset.accessibility_description
            or not isinstance(asset.original_filename, str)
            or not isinstance(asset.mime_type, str)
            or type(asset.width) is not int
            or asset.width <= 0
            or type(asset.height) is not int
            or asset.height <= 0
        ):
            raise PerformanceLocalV5PayloadError(
                f"The governed {role} Brand Asset differs from its current approved identity.",
                code="performance_local_v5_logo_identity_blocked",
            )
        payload_src = _verified_brand_asset_path(governed_url)
        identities.append(
            PerformanceLocalV5LogoIdentity(
                role=role,
                brand_asset_id=asset.id,
                asset_key=_text(asset.asset_key, f"{role} Brand Asset key"),
                asset_version=asset.version,
                checksum_sha256=_sha(
                    asset.checksum_sha256, f"{role} Brand Asset checksum"
                ),
                source_filename=_source_filename(
                    asset.original_filename, f"{role} source filename"
                ),
                source_mime_type=_image_mime_type(
                    asset.mime_type, f"{role} source MIME type"
                ),
                source_width=asset.width,
                source_height=asset.height,
                governed_asset_url=_text(governed_url, f"{role} governed URL"),
                payload_src=payload_src,
                # A Bridge-compatible path is sufficient to construct and
                # validate the candidate payload, but it is not durable proof
                # that the exact Brand Asset exists on WordPress.
                ready=False,
                blocker="REMOTE_MEDIA_SYNC_REQUIRED",
            )
        )
    return identities


def _media_components_by_target(
    resolved_components: list[Any],
) -> dict[str, dict[str, Any]]:
    by_target: dict[str, dict[str, Any]] = {}
    for component in resolved_components:
        if component.component_key != "media_placement" or component.variant != "approved_media":
            continue
        target = component.input_bindings.get("target_component_instance_key")
        if not isinstance(target, str) or not target:
            raise PerformanceLocalV5PayloadError(
                "Approved media lacks its governed target-component identity."
            )
        if target in by_target:
            raise PerformanceLocalV5PayloadError(
                f"More than one approved media assignment targets {target}."
            )
        by_target[target] = _object(component.resolved_data, "resolved media")
    expected = {
        "hero",
        "service_summary:why_it_matters",
        "content_section:signs_section",
    }
    if set(by_target) != expected:
        raise PerformanceLocalV5PayloadError(
            "The City-Service page does not resolve the exact three governed media placements."
        )
    return by_target


def _form_payload(source: dict[str, Any]) -> dict[str, Any]:
    fields = _objects(source.get("fields"), "form fields")
    if [item.get("field_key") for item in fields] != [
        "name",
        "phone",
        "postal-code",
        "requested-service",
        "message",
    ]:
        raise PerformanceLocalV5PayloadError("The governed five-field form changed.")
    normalized: list[dict[str, Any]] = []
    for index, field in enumerate(fields, start=1):
        validation = _object(field.get("validation_contract"), "form validation")
        maximum = _positive_int(field.get("maximum_length"), "form maximum length")
        minimum = validation.get("minimum_length")
        if type(minimum) is not int or minimum < 0:
            raise PerformanceLocalV5PayloadError("Form minimum length is invalid.")
        if field.get("order") != index or validation.get("maximum_length") != maximum:
            raise PerformanceLocalV5PayloadError("Form ordering/length binding changed.")
        if type(field.get("required")) is not bool:
            raise PerformanceLocalV5PayloadError("Form required flag is invalid.")
        normalized.append(
            {
                "field_key": _text(field.get("field_key"), "form field key"),
                "label": _text(field.get("label"), "form field label"),
                "required": field["required"],
                "control": _text(field.get("control"), "form control"),
                "input_type": _text(field.get("input_type"), "form input type"),
                "order": index,
                "maximum_length": maximum,
                "validation": {
                    "rule": _text(validation.get("rule"), "form validation rule"),
                    "minimum_length": minimum,
                    "maximum_length": maximum,
                },
            }
        )
    return {
        "state": "disabled",
        "anchor": "estimate-form",
        "submit_label": _text(source.get("submit_label"), "form submit label"),
        "notice": _text(source.get("preview_notice"), "form notice"),
        "fields": normalized,
    }


def _component(components: dict[str, dict[str, Any]], key: str | None) -> dict[str, Any]:
    if key is None or key not in components:
        raise PerformanceLocalV5PayloadError(f"Required Composition component is missing: {key}.")
    return _object(components[key], f"Composition component {key}")


def _navigation_items(source: dict[str, Any]) -> list[dict[str, Any]]:
    items = _objects(source.get("items"), "navigation items")
    labels = {
        _positive_int(item.get("navigation_item_id"), "navigation item id"): _text(
            item.get("label"), "navigation label"
        )
        for item in items
    }
    result = []
    for item in items:
        if item.get("status") != "active":
            raise PerformanceLocalV5PayloadError("Navigation contains a non-active item.")
        parent_id = item.get("parent_navigation_item_id")
        parent_label = None if parent_id is None else labels.get(parent_id)
        if parent_id is not None and parent_label is None:
            raise PerformanceLocalV5PayloadError("Navigation parent is unresolved.")
        result.append(
            {
                "label": _text(item.get("label"), "navigation label"),
                "href": _internal_href(item.get("slug"), "navigation slug"),
                "parent_label": parent_label,
            }
        )
    return result


def _footer_navigation_items(source: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"label": item["label"], "href": item["href"]}
        for item in _navigation_items(source)
    ]


def _media(source: dict[str, Any], payload_src: str | None) -> dict[str, Any]:
    focal_x = source.get("focal_x")
    focal_y = source.get("focal_y")
    if (
        not isinstance(focal_x, (int, float))
        or isinstance(focal_x, bool)
        or not 0 <= focal_x <= 1
        or not isinstance(focal_y, (int, float))
        or isinstance(focal_y, bool)
        or not 0 <= focal_y <= 1
    ):
        raise PerformanceLocalV5PayloadError("Media focal positions are invalid.")
    if payload_src is None:
        raise PerformanceLocalV5PayloadError(
            "Governed media lacks an exact verified WordPress upload identity.",
            code="REMOTE_MEDIA_SYNC_REQUIRED",
        )
    return {
        "src": _upload_path(payload_src, "verified WordPress media path"),
        "alt": _text(source.get("alt_text"), "media alt text"),
        "title": _optional_text(source.get("image_title"), "media title"),
        "focal_x": focal_x,
        "focal_y": focal_y,
    }


def _logo(
    source: dict[str, Any], key: str, payload_src: str | None
) -> dict[str, str]:
    identities = _object(source.get("identity_assets"), "identity assets")
    asset = _object(identities.get(key), f"identity asset {key}")
    if payload_src is None:
        raise PerformanceLocalV5PayloadError(
            f"Governed {key} lacks an exact verified Bridge upload identity.",
            code="REMOTE_MEDIA_SYNC_REQUIRED",
        )
    return {
        "src": _upload_path(payload_src, f"verified {key} asset"),
        "alt": _text(asset.get("accessibility_description"), f"{key} alt text"),
    }


def _require_public_identity(source: dict[str, Any], business: Business, brand: Brand) -> None:
    if (
        source.get("company_name") != business.company_name
        or source.get("phone") != business.phone
        or source.get("email") != business.email
        or source.get("tagline") != brand.tagline
    ):
        raise PerformanceLocalV5PayloadError(
            "Resolved Website identity differs from current Business/Brand/contact state."
        )


def _business_identity(record: Business) -> dict[str, Any]:
    return {
        "id": record.id,
        "company_name": record.company_name,
        "brand_name": record.brand_name,
        "business_type": record.business_type,
        "phone": record.phone,
        "email": record.email,
        "website": record.website,
        "main_city": record.main_city,
        "state": record.state,
    }


def _brand_identity(record: Brand) -> dict[str, Any]:
    return {
        "id": record.id,
        "business_id": record.business_id,
        "brand_name": record.brand_name,
        "tagline": record.tagline,
        "identity_settings": record.identity_settings,
        "status": record.status,
    }


def _website_identity(record: Website) -> dict[str, Any]:
    return {
        "id": record.id,
        "business_id": record.business_id,
        "brand_id": record.brand_id,
        "website_name": record.website_name,
        "domain": record.domain,
        "public_url": record.public_url,
        "locale": record.locale,
        "primary_language": record.primary_language,
        "configuration": record.configuration,
        "status": record.status,
    }


def _planned_page_identity(record: PlannedPage) -> dict[str, Any]:
    """Stable current identity bound to the private transport envelope."""

    return {
        "id": record.id,
        "website_id": record.website_id,
        "site_plan_id": record.site_plan_id,
        "page_type": record.page_type,
        "working_name": record.working_name,
        "intended_slug": record.intended_slug,
        "service_id": record.service_id,
        "city_id": record.city_id,
        "county_id": record.county_id,
        "parent_planned_page_id": record.parent_planned_page_id,
        "planning_status": record.planning_status,
        "generated_page_id": record.generated_page_id,
    }


def _phone_href(value: Any) -> str:
    display = _text(value, "public phone")
    digits = re.sub(r"\D", "", display)
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) < 8 or len(digits) > 15 or digits.startswith("0"):
        raise PerformanceLocalV5PayloadError("The public phone cannot form a safe tel URI.")
    return f"tel:+{digits}"


def _upload_path(value: Any, label: str) -> str:
    source = _text(value, label)
    parsed = urlsplit(source)
    if (
        parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or (parsed.scheme and parsed.scheme not in {"http", "https"})
        or (parsed.scheme and not parsed.netloc)
        or (parsed.netloc and not parsed.scheme)
    ):
        raise PerformanceLocalV5PayloadError(
            f"{label} is not an exact Bridge-compatible governed upload path.",
            code="REMOTE_MEDIA_SYNC_REQUIRED",
        )
    path = parsed.path
    if not path.startswith("/wp-content/uploads/atlas-v5/"):
        raise PerformanceLocalV5PayloadError(
            f"{label} is not an exact Bridge-compatible governed upload path.",
            code="REMOTE_MEDIA_SYNC_REQUIRED",
        )
    relative = path.removeprefix("/wp-content/uploads/atlas-v5/")
    if (
        not relative
        or "\\" in relative
        or any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts)
        or any(not _SAFE_BASENAME.fullmatch(part) for part in PurePosixPath(relative).parts)
    ):
        raise PerformanceLocalV5PayloadError(f"{label} has an unsafe upload path.")
    if PurePosixPath(relative).suffix.lower() not in {
        ".avif",
        ".jpeg",
        ".jpg",
        ".png",
        ".svg",
        ".webp",
    }:
        raise PerformanceLocalV5PayloadError(f"{label} has an unsupported image type.")
    return path


def _verified_wordpress_media_path(image: ImageMetadata) -> str | None:
    if (
        type(image.wordpress_media_id) is not int
        or image.wordpress_media_id <= 0
        or not isinstance(image.wordpress_media_url, str)
        or image.wordpress_media_status
        not in {"uploaded", "verified", "active", "available", "reconciled"}
        or image.wordpress_media_checksum != image.checksum_sha256
    ):
        return None
    try:
        return _upload_path(image.wordpress_media_url, "WordPress media URL")
    except PerformanceLocalV5PayloadError:
        return None


def _verified_brand_asset_path(value: Any) -> str | None:
    try:
        return _upload_path(value, "Brand Asset URL")
    except PerformanceLocalV5PayloadError:
        return None


def _internal_href(value: Any, label: str) -> str:
    slug = _slug(value, label)
    return "/" if slug == "home" else f"/{slug}/"


def _slug(value: Any, label: str) -> str:
    text = _text(value, label)
    if not _SAFE_SLUG.fullmatch(text):
        raise PerformanceLocalV5PayloadError(f"{label} is not a safe slug.")
    return text


def _optional_email(value: Any) -> str | None:
    if value is None:
        return None
    email = _text(value, "public contact email")
    if email.count("@") != 1 or "." not in email.rsplit("@", 1)[1]:
        raise PerformanceLocalV5PayloadError("The public contact email is malformed.")
    return email


def _reject_private_delivery(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        forbidden = _PRIVATE_DELIVERY_KEYS.intersection(value)
        if forbidden:
            raise PerformanceLocalV5PayloadError(
                f"Private delivery configuration entered {path}: {sorted(forbidden)}.",
                code="performance_local_v5_private_delivery_leak",
            )
        for key, nested in value.items():
            _reject_private_delivery(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_private_delivery(nested, f"{path}[{index}]")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PerformanceLocalV5PayloadError(f"{label} must be a JSON object.")
    return value


def _objects(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise PerformanceLocalV5PayloadError(f"{label} must be an object array.")
    return value


def _text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or _CONTROL_OR_HTML.search(value)
    ):
        raise PerformanceLocalV5PayloadError(f"{label} must be exact plain text.")
    return value


def _optional_text(value: Any, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _source_filename(value: Any, label: str) -> str:
    filename = _text(value, label)
    if filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise PerformanceLocalV5PayloadError(
            f"{label} must be one exact path-free filename."
        )
    return filename


def _image_mime_type(value: Any, label: str) -> str:
    mime = _text(value, label)
    if mime not in {
        "image/avif",
        "image/jpeg",
        "image/png",
        "image/svg+xml",
        "image/webp",
    }:
        raise PerformanceLocalV5PayloadError(f"{label} is unsupported.")
    return mime


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise PerformanceLocalV5PayloadError(f"{label} must be a positive integer.")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise PerformanceLocalV5PayloadError(f"{label} is not lowercase SHA-256.")
    return value


def _exactly_one(values: list[Any], label: str) -> Any:
    if len(values) != 1:
        raise PerformanceLocalV5PayloadError(
            f"Expected exactly one {label}; found {len(values)}."
        )
    return values[0]


def _record(session: Session, model: Any, record_id: int, label: str) -> Any:
    record = session.get(model, record_id)
    if record is None or getattr(record, "id", None) is None:
        raise PerformanceLocalV5PayloadError(f"{label} was not found.")
    return record


def _pending_identity(session: Session) -> tuple[frozenset[int], frozenset[int], frozenset[int]]:
    return (
        frozenset(id(item) for item in session.new),
        frozenset(id(item) for item in session.dirty),
        frozenset(id(item) for item in session.deleted),
    )
