import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.models import (
    Business,
    City,
    County,
    GeneratedPage,
    GeneratedPageRevision,
    ImageMetadata,
    PageImageAssignment,
    Service,
)
from app.schemas.page_export import (
    BulkExportCandidate,
    BulkExportPreview,
    ExportMediaReference,
    ExportSEO,
    ExportWarning,
    PageExportPackage,
)
from app.services.draft_generation import FORBIDDEN_PHRASES


CONTENT_SECTION_KEYS = (
    "intro",
    "why_it_matters",
    "signs_section",
    "process_section",
    "prep_section",
    "realtor_property_manager_section",
    "service_explanation",
    "local_city_section",
    "why_choose_section",
)
EXPORT_UNSAFE_PHRASES = tuple(dict.fromkeys((*FORBIDDEN_PHRASES, "guaranteed")))


def generate_suggested_slug(service: Service, city: City) -> str:
    service_part = service.service_slug or service.service_name
    city_part = city.city_slug or city.city_name
    return slugify(f"{service_part}-{city_part}-{city.state}")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", normalized.lower())).strip("-")


def build_page_export_package(session: Session, page_id: int) -> PageExportPackage:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    business = session.get(Business, page.business_id)
    service = session.get(Service, page.service_id)
    city = session.get(City, page.city_id) if page.city_id else None
    county = session.get(County, page.county_id) if page.county_id else None
    if not business or not service or not city or not county:
        raise HTTPException(status_code=409, detail="Page export requires business, service, city, and county data")

    draft = page.draft_content or {}
    suggested_slug = generate_suggested_slug(service, city)
    url_slug = page.page_slug or suggested_slug
    conflicts = _slug_conflicts(session, page.id or page_id, suggested_slug)
    meta_title = _text(draft.get("meta_title") or page.meta_title)
    meta_description = _text(draft.get("meta_description") or page.meta_description)
    page_title = _text(draft.get("title") or page.page_title)
    h1 = _text(draft.get("h1") or page.h1)
    seo = ExportSEO(
        meta_title=meta_title,
        meta_description=meta_description,
        social_title=meta_title,
        social_description=meta_description,
        suggested_url_slug=suggested_slug,
    )
    media = _media_references(session, page.id or page_id)
    faqs = _faq_items(draft.get("faq_items"))
    canonical_url = _canonical_url(business.website, url_slug)
    warnings = _readiness_warnings(
        session,
        page,
        draft=draft,
        seo=seo,
        media=media,
        slug_conflicts=conflicts,
    )
    return PageExportPackage(
        page_id=page.id or page_id,
        page_status=page.status,
        qa_status=page.qa_status,
        page_title=page_title,
        url_slug=url_slug,
        h1=h1,
        seo=seo,
        content_sections={
            key: _text(draft.get(key))
            for key in CONTENT_SECTION_KEYS
            if _text(draft.get(key))
        },
        faq_items=faqs,
        cta_block=_text(draft.get("call_to_action")),
        city=city.city_name,
        county=county.county_name,
        state=city.state,
        service=service.service_name,
        business_name=business.company_name,
        phone=business.phone,
        website=business.website,
        email=business.email,
        license_number=business.license_number,
        certified_operator=business.certified_operator,
        assigned_media=media,
        json_ld=_json_ld(
            business=business,
            service=service,
            city=city,
            county=county,
            faqs=faqs,
            page_title=page_title,
            canonical_url=canonical_url,
        ),
        canonical_url_preview=canonical_url,
        slug_conflicts=conflicts,
        export_ready=not any(item.severity == "blocker" for item in warnings),
        warnings=warnings,
    )


def preview_bulk_export(session: Session, page_ids: list[int]) -> BulkExportPreview:
    packages = build_selected_packages(session, page_ids)
    candidates = [
        BulkExportCandidate(
            page_id=package.page_id,
            page_title=package.page_title,
            url_slug=package.url_slug,
            export_ready=package.export_ready,
            warning_count=sum(item.severity == "warning" for item in package.warnings),
            blocker_count=sum(item.severity == "blocker" for item in package.warnings),
        )
        for package in packages
    ]
    return BulkExportPreview(
        selected_count=len(candidates),
        export_ready_count=sum(item.export_ready for item in candidates),
        warning_count=sum(item.warning_count for item in candidates),
        blocker_count=sum(item.blocker_count for item in candidates),
        candidates=candidates,
    )


def build_selected_packages(session: Session, page_ids: list[int]) -> list[PageExportPackage]:
    unique_ids = list(dict.fromkeys(page_ids))
    packages = [build_page_export_package(session, page_id) for page_id in unique_ids]
    if len(packages) != len(unique_ids):
        raise HTTPException(status_code=404, detail="One or more generated pages were not found")
    return packages


def package_json(package: PageExportPackage) -> bytes:
    return (
        json.dumps(package.model_dump(mode="json"), indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _slug_conflicts(session: Session, page_id: int, suggested_slug: str) -> list[int]:
    pages = session.exec(
        select(GeneratedPage).where(
            GeneratedPage.id != page_id,
            GeneratedPage.page_slug == suggested_slug,
        )
    ).all()
    return [page.id for page in pages if page.id is not None]


def _media_references(session: Session, page_id: int) -> list[ExportMediaReference]:
    assignments = session.exec(
        select(PageImageAssignment)
        .where(
            PageImageAssignment.generated_page_id == page_id,
            PageImageAssignment.status == "active",
        )
        .order_by(PageImageAssignment.image_role, PageImageAssignment.sort_order, PageImageAssignment.id)
    ).all()
    references: list[ExportMediaReference] = []
    for assignment in assignments:
        image = session.get(ImageMetadata, assignment.image_metadata_id)
        if not image:
            continue
        references.append(
            ExportMediaReference(
                image_id=image.id or 0,
                image_role=assignment.image_role,
                sort_order=assignment.sort_order,
                image_title=image.image_title,
                alt_text=assignment.override_alt_text or image.reviewed_alt_text or image.alt_text or "",
                asset_url=image.asset_url,
                optimized_url=image.optimized_url,
                thumbnail_url=image.thumbnail_url,
                display_preset=assignment.display_preset,
                focal_x=assignment.override_focal_x if assignment.override_focal_x is not None else image.focal_x,
                focal_y=assignment.override_focal_y if assignment.override_focal_y is not None else image.focal_y,
                review_status=image.review_status,
            )
        )
    return references


def _readiness_warnings(
    session: Session,
    page: GeneratedPage,
    *,
    draft: dict[str, Any],
    seo: ExportSEO,
    media: list[ExportMediaReference],
    slug_conflicts: list[int],
) -> list[ExportWarning]:
    warnings: list[ExportWarning] = []
    if page.status != "approved":
        _warn(warnings, "page_not_approved", "blocker", "Page is not approved.")
    if page.qa_status == "blocked":
        _warn(warnings, "qa_blocked", "blocker", "QA is blocked.")
    elif page.qa_status != "ready":
        _warn(warnings, "qa_not_ready", "blocker", "QA is not currently ready.")
    latest_revision_at = session.exec(
        select(func.max(GeneratedPageRevision.created_at)).where(
            GeneratedPageRevision.generated_page_id == page.id
        )
    ).one()
    if latest_revision_at and (
        page.qa_checked_at is None
        or _timestamp(latest_revision_at) > _timestamp(page.qa_checked_at)
    ):
        _warn(warnings, "qa_stale", "blocker", "The draft was edited after the latest QA check.")

    heroes = [item for item in media if item.image_role == "hero"]
    if not heroes:
        _warn(warnings, "hero_missing", "blocker", "A hero image is not assigned.")
    if any(not item.alt_text.strip() for item in media):
        _warn(warnings, "alt_text_missing", "blocker", "One or more assigned images are missing alt text.")
    if slug_conflicts:
        _warn(
            warnings,
            "slug_conflict",
            "blocker",
            f"Suggested slug conflicts with page ID(s): {', '.join(map(str, slug_conflicts))}.",
        )
    if not seo.meta_title:
        _warn(warnings, "meta_title_missing", "blocker", "Meta title is missing.")
    elif len(seo.meta_title) > 60:
        _warn(warnings, "meta_title_long", "warning", "Meta title is longer than 60 characters.")
    if not seo.meta_description:
        _warn(warnings, "meta_description_missing", "blocker", "Meta description is missing.")
    elif len(seo.meta_description) > 160:
        _warn(warnings, "meta_description_long", "warning", "Meta description is longer than 160 characters.")

    public_text = json.dumps(draft, ensure_ascii=True).lower()
    unsafe = [phrase for phrase in EXPORT_UNSAFE_PHRASES if phrase in public_text]
    if unsafe:
        _warn(
            warnings,
            "unsafe_phrase",
            "blocker",
            f"Unsafe wording appears in the draft: {', '.join(unsafe)}.",
        )
    return warnings


def _json_ld(
    *,
    business: Business,
    service: Service,
    city: City,
    county: County,
    faqs: list[dict[str, str]],
    page_title: str,
    canonical_url: str,
) -> dict[str, Any]:
    website = _website_base(business.website)
    business_id = f"{website}/#business" if website else "#business"
    graph: list[dict[str, Any]] = [
        _without_empty(
            {
                "@type": "LocalBusiness",
                "@id": business_id,
                "name": business.company_name,
                "url": website or None,
                "telephone": business.phone,
                "email": business.email,
                "identifier": (
                    {
                        "@type": "PropertyValue",
                        "propertyID": "Florida License",
                        "value": business.license_number,
                    }
                    if business.license_number
                    else None
                ),
                "employee": (
                    {
                        "@type": "Person",
                        "name": business.certified_operator,
                        "jobTitle": "Certified Operator",
                    }
                    if business.certified_operator
                    else None
                ),
                "areaServed": [
                    {"@type": "City", "name": city.city_name},
                    {"@type": "AdministrativeArea", "name": county.county_name},
                ],
            }
        ),
        {
            "@type": "Service",
            "name": service.service_name,
            "serviceType": service.service_name,
            "provider": {"@id": business_id},
            "areaServed": [
                {"@type": "City", "name": city.city_name},
                {"@type": "AdministrativeArea", "name": county.county_name},
            ],
        },
        {
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": item["question"],
                    "acceptedAnswer": {"@type": "Answer", "text": item["answer"]},
                }
                for item in faqs
            ],
        },
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": business.company_name,
                    "item": website or canonical_url,
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": service.service_name,
                },
                {
                    "@type": "ListItem",
                    "position": 3,
                    "name": page_title,
                    "item": canonical_url,
                },
            ],
        },
    ]
    return {"@context": "https://schema.org", "@graph": graph}


def _canonical_url(website: str | None, slug: str) -> str:
    base = _website_base(website)
    return f"{base}/{slug}/" if base else f"/{slug}/"


def _website_base(website: str | None) -> str:
    value = (website or "").strip().rstrip("/")
    if not value:
        return ""
    if not urlparse(value).scheme:
        value = f"https://{value}"
    return value


def _faq_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {"question": _text(item.get("question")), "answer": _text(item.get("answer"))}
        for item in value
        if isinstance(item, dict) and _text(item.get("question")) and _text(item.get("answer"))
    ]


def _warn(warnings: list[ExportWarning], code: str, severity: str, message: str) -> None:
    warnings.append(ExportWarning(code=code, severity=severity, message=message))


def _without_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None and item != ""}


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
