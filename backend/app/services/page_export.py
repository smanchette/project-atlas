import json
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    Business,
    City,
    County,
    GeneratedPage,
    ImageMetadata,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    Service,
    Website,
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
from app.services.media_display_presets import (
    DisplayPresetError,
    effective_assignment_display_preset,
)
from app.services.page_type_review import (
    draft_content_sections,
    review_contract_for,
    validate_draft_contract,
)
from app.services.page_composition import (
    PageCompositionError,
    read_composition_for_generated_page,
)
from app.services.page_media_roles import (
    SemanticMediaRoleError,
    resolve_semantic_media_role,
)
from app.services.scoped_media_authorizations import (
    current_scoped_media_authorization,
    governed_assignment_authorization_errors,
)
from app.services.page_qa import EffectivePageQAState, effective_page_qa_state
from app.services.website_context import build_website_context
from app.services.website_scope import require_page_website, require_single_website_selection
from app.services.website_media_safety import is_image_metadata_excluded


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
    require_page_website(session, page)
    business = session.get(Business, page.business_id)
    service = session.get(Service, page.service_id) if page.service_id else None
    city = session.get(City, page.city_id) if page.city_id else None
    county = session.get(County, page.county_id) if page.county_id else None
    if not business:
        raise HTTPException(status_code=409, detail="Page export requires Business data")
    try:
        contract = review_contract_for(page)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if contract.require_service and not service:
        raise HTTPException(status_code=409, detail="Page export requires Service data")
    if contract.require_city and not city:
        raise HTTPException(status_code=409, detail="Page export requires City data")
    if contract.require_county and not county:
        raise HTTPException(status_code=409, detail="Page export requires County data")

    draft = page.draft_content or {}
    website_context = build_website_context(session, page_id=page_id)
    suggested_slug = (
        generate_suggested_slug(service, city)
        if contract.schema == "legacy-city-service-v1" and service and city
        else slugify(page.page_slug)
    )
    url_slug = page.page_slug or suggested_slug
    conflicts = _slug_conflicts(
        session,
        page.id or page_id,
        page.website_id or 0,
        suggested_slug,
    )
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
    qa_state = effective_page_qa_state(session, page)
    faqs = _faq_items(draft.get("faq_items"))
    canonical_url = _canonical_url(website_context.website.public_url, url_slug)
    warnings = _readiness_warnings(
        session,
        page,
        draft=draft,
        seo=seo,
        media=media,
        slug_conflicts=conflicts,
        contract=contract,
        qa_state=qa_state,
    )
    return PageExportPackage(
        page_id=page.id or page_id,
        page_status=page.status,
        qa_status=_effective_qa_status(qa_state),
        page_title=page_title,
        url_slug=url_slug,
        h1=h1,
        seo=seo,
        content_sections=draft_content_sections(contract, draft),
        faq_items=faqs,
        cta_block=_text(draft.get("call_to_action")),
        city=city.city_name if city else None,
        county=county.county_name if county else None,
        state=(city.state if city else county.state if county else business.state),
        service=service.service_name if service else None,
        business_name=business.company_name,
        phone=business.phone,
        website=website_context.website.public_url,
        email=business.email,
        license_number=business.license_number,
        certified_operator=business.certified_operator,
        assigned_media=media,
        json_ld=(
            _json_ld(
                business=business,
                service=service,
                city=city,
                county=county,
                faqs=faqs,
                page_title=page_title,
                canonical_url=canonical_url,
                website_url=website_context.website.public_url,
                license_label=str(website_context.website.configuration.get("license_label") or "License"),
                operator_title=str(
                    website_context.website.configuration.get("certified_operator_title")
                    or "Certified Operator"
                ),
            )
            if contract.schema == "legacy-city-service-v1" and service and city and county
            else _generic_json_ld(
                business=business,
                faqs=faqs,
                page_title=page_title,
                canonical_url=canonical_url,
                website_url=website_context.website.public_url,
            )
        ),
        canonical_url_preview=canonical_url,
        slug_conflicts=conflicts,
        export_ready=not any(item.severity == "blocker" for item in warnings),
        warnings=warnings,
    )


def preview_bulk_export(
    session: Session,
    page_ids: list[int],
    *,
    website_id: int | None = None,
) -> BulkExportPreview:
    packages = build_selected_packages(session, page_ids, website_id=website_id)
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


def build_selected_packages(
    session: Session,
    page_ids: list[int],
    *,
    website_id: int | None = None,
) -> list[PageExportPackage]:
    unique_ids = list(dict.fromkeys(page_ids))
    pages = [session.get(GeneratedPage, page_id) for page_id in unique_ids]
    if any(page is None for page in pages):
        raise HTTPException(status_code=404, detail="One or more generated pages were not found")
    require_single_website_selection(
        session,
        [page for page in pages if page is not None],
        website_id=website_id,
        operation="Bulk export",
    )
    packages = [build_page_export_package(session, page_id) for page_id in unique_ids]
    if len(packages) != len(unique_ids):
        raise HTTPException(status_code=404, detail="One or more generated pages were not found")
    return packages


def package_json(package: PageExportPackage) -> bytes:
    return (
        json.dumps(package.model_dump(mode="json"), indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _slug_conflicts(
    session: Session,
    page_id: int,
    website_id: int,
    suggested_slug: str,
) -> list[int]:
    pages = session.exec(
        select(GeneratedPage).where(
            GeneratedPage.id != page_id,
            GeneratedPage.website_id == website_id,
            GeneratedPage.page_slug == suggested_slug,
        )
    ).all()
    return [page.id for page in pages if page.id is not None]


def _media_references(session: Session, page_id: int) -> list[ExportMediaReference]:
    page = session.get(GeneratedPage, page_id)
    website = session.get(Website, page.website_id) if page else None
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
        governed_identity = _governed_media_export_identity(
            session,
            page,
            assignment,
        )
        try:
            semantic_role = resolve_semantic_media_role(
                assignment,
                session=session,
            )
        except SemanticMediaRoleError as exc:
            _governed_export_conflict(str(exc))
        requirement = (
            session.get(
                PlannedPageMediaRequirement,
                assignment.media_requirement_id,
            )
            if assignment.media_requirement_id is not None
            else None
        )
        try:
            effective_display_preset = effective_assignment_display_preset(
                assignment,
                requirement=requirement,
                semantic_role=semantic_role,
            )
        except DisplayPresetError as exc:
            if assignment.media_requirement_id is not None:
                _governed_export_conflict(str(exc))
            raise HTTPException(
                status_code=409,
                detail=f"Page-media export blocked: {exc}",
            ) from exc
        image = session.get(ImageMetadata, assignment.image_metadata_id)
        if not image:
            if assignment.media_requirement_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Governed page-media export references a missing media asset.",
                )
            continue
        if is_image_metadata_excluded(website, image):
            continue
        references.append(
            ExportMediaReference(
                image_id=image.id or 0,
                image_role=semantic_role,
                sort_order=assignment.sort_order,
                **governed_identity,
                image_title=image.image_title,
                alt_text=assignment.override_alt_text or image.reviewed_alt_text or image.alt_text or "",
                asset_url=image.asset_url,
                optimized_url=image.optimized_url,
                thumbnail_url=image.thumbnail_url,
                stored_display_preset=assignment.display_preset,
                effective_display_preset=effective_display_preset,
                display_preset=effective_display_preset,
                focal_x=assignment.override_focal_x if assignment.override_focal_x is not None else image.focal_x,
                focal_y=assignment.override_focal_y if assignment.override_focal_y is not None else image.focal_y,
                review_status=image.review_status,
            )
        )
    return references


def _governed_media_export_identity(
    session: Session,
    page: GeneratedPage | None,
    assignment: PageImageAssignment,
) -> dict[str, Any]:
    """Return durable placement identity, failing closed for malformed V2 bindings.

    Legacy assignments intentionally retain their prior export semantics by
    emitting null governed-identity fields. Governed V1 placements expose the
    identity they already possess. V2 placements additionally require their
    persisted exact component-instance selector to resolve in the current
    semantic composition; export never derives or substitutes that selector.
    """

    empty = {
        "media_requirement_id": None,
        "media_requirement_version": None,
        "placement_key": None,
        "target_component_key": None,
        "target_component_instance_key": None,
        "placement_contract_version": None,
        "scoped_authorization_id": None,
        "scoped_authorization_version": None,
        "scoped_authorization_fingerprint": None,
        "scoped_authorization_terms": [],
        "scoped_reuse_policy": None,
    }
    authorization_errors = governed_assignment_authorization_errors(
        session,
        assignment,
    )
    if authorization_errors:
        _governed_export_conflict(" ".join(authorization_errors))
    if assignment.media_requirement_id is None:
        return empty
    if page is None or page.id is None:
        _governed_export_conflict("Generated Page identity is missing.")

    requirement = session.get(
        PlannedPageMediaRequirement,
        assignment.media_requirement_id,
    )
    if requirement is None:
        _governed_export_conflict("Media requirement is missing.")
    planned = session.get(PlannedPage, assignment.planned_page_id)
    if planned is None:
        _governed_export_conflict("Planned Page identity is missing.")
    if (
        assignment.generated_page_id != page.id
        or assignment.website_id != page.website_id
        or assignment.planned_page_id != planned.id
        or planned.generated_page_id != page.id
        or planned.website_id != page.website_id
        or requirement.id != assignment.media_requirement_id
        or requirement.website_id != page.website_id
        or requirement.business_id != page.business_id
        or requirement.site_plan_id != planned.site_plan_id
        or requirement.planned_page_id != planned.id
    ):
        _governed_export_conflict(
            "Media placement crosses its Generated Page, Planned Page, Website, "
            "Business, or Site Plan boundary."
        )
    if (
        requirement.lifecycle_status != "active"
        or requirement.requirement_state not in {"required", "advisory"}
    ):
        _governed_export_conflict("Media requirement is not an active exportable placement.")
    if assignment.placement_contract_version != requirement.contract_version:
        _governed_export_conflict("Placement contract version is stale or inconsistent.")
    asset = session.get(ImageMetadata, assignment.image_metadata_id)
    website = session.get(Website, page.website_id)
    if asset is None or website is None:
        _governed_export_conflict(
            "Governed page-media export cannot resolve its asset or Website."
        )
    authorization = current_scoped_media_authorization(
        session,
        requirement.id or 0,
    )

    target_instance_key = getattr(
        requirement,
        "target_component_instance_key",
        None,
    )
    if requirement.contract_version >= 2:
        if (
            not isinstance(target_instance_key, str)
            or not target_instance_key
            or target_instance_key != target_instance_key.strip()
        ):
            _governed_export_conflict(
                "V2 media requirement is missing its exact component-instance selector."
            )
        _validate_v2_export_target(
            session,
            page.id,
            requirement,
            target_instance_key,
        )

    return {
        "media_requirement_id": requirement.id,
        "media_requirement_version": requirement.version,
        "placement_key": requirement.placement_key,
        "target_component_key": requirement.component_or_section,
        "target_component_instance_key": target_instance_key,
        "placement_contract_version": requirement.contract_version,
        "scoped_authorization_id": authorization.id if authorization else None,
        "scoped_authorization_version": (
            authorization.authorization_version if authorization else None
        ),
        "scoped_authorization_fingerprint": (
            authorization.authorization_fingerprint if authorization else None
        ),
        "scoped_authorization_terms": (
            list(authorization.authorization_terms) if authorization else []
        ),
        "scoped_reuse_policy": authorization.reuse_policy if authorization else None,
    }


def _validate_v2_export_target(
    session: Session,
    generated_page_id: int,
    requirement: PlannedPageMediaRequirement,
    target_instance_key: str,
) -> None:
    try:
        composition = read_composition_for_generated_page(
            session,
            generated_page_id,
        )
    except PageCompositionError as exc:
        _governed_export_conflict(
            f"V2 media target cannot be verified in a current composition: {exc}"
        )

    targets = [
        item
        for item in composition.effective_components
        if item.instance_key == target_instance_key
        and item.component_key == requirement.component_or_section
    ]
    if len(targets) != 1:
        _governed_export_conflict(
            "V2 media target does not resolve exactly once to the governed semantic "
            "component instance."
        )

    placements = [
        item
        for item in composition.effective_components
        if item.component_key == "media_placement"
        and item.input_bindings.get("media_requirement_id") == requirement.id
    ]
    if len(placements) != 1:
        _governed_export_conflict(
            "V2 media requirement does not resolve exactly once in the current composition."
        )
    bindings = placements[0].input_bindings
    if (
        bindings.get("target_component_key") != requirement.component_or_section
        or bindings.get("target_component_instance_key") != target_instance_key
        or bindings.get("placement_contract_version")
        != requirement.contract_version
    ):
        _governed_export_conflict(
            "V2 media composition binding does not match the durable exact target "
            "and placement contract version."
        )


def _governed_export_conflict(message: str) -> None:
    raise HTTPException(
        status_code=409,
        detail=f"Governed page-media export blocked: {message}",
    )


def _readiness_warnings(
    session: Session,
    page: GeneratedPage,
    *,
    draft: dict[str, Any],
    seo: ExportSEO,
    media: list[ExportMediaReference],
    slug_conflicts: list[int],
    contract,
    qa_state: EffectivePageQAState,
) -> list[ExportWarning]:
    warnings: list[ExportWarning] = []
    website = session.get(Website, page.website_id)
    excluded_assignment_count = 0
    for assignment in session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.generated_page_id == page.id,
            PageImageAssignment.status == "active",
        )
    ).all():
        image = session.get(ImageMetadata, assignment.image_metadata_id)
        if is_image_metadata_excluded(website, image):
            excluded_assignment_count += 1
    if excluded_assignment_count:
        _warn(
            warnings,
            "excluded_external_media",
            "blocker",
            (
                f"{excluded_assignment_count} active assignment(s) reference "
                "Website-scoped excluded external media."
            ),
        )
    if page.status != "approved":
        _warn(warnings, "page_not_approved", "blocker", "Page is not approved.")
    if qa_state.classification == "missing_qa":
        _warn(warnings, "qa_not_ready", "blocker", "QA has not been run.")
    elif not qa_state.current:
        reason = qa_state.reasons[0] if qa_state.reasons else "Saved QA is not current."
        _warn(
            warnings,
            "qa_stale",
            "blocker",
            f"Saved QA is stale or identity-mismatched: {reason}",
        )
    elif qa_state.result is None:
        _warn(warnings, "qa_stale", "blocker", "Current QA evidence is unavailable.")
    elif (
        qa_state.result.readiness_status == "blocked"
        or qa_state.result.failed_count > 0
    ):
        _warn(warnings, "qa_blocked", "blocker", "QA is blocked.")
    elif not qa_state.ready:
        _warn(warnings, "qa_not_ready", "blocker", "QA is not currently ready.")

    contract_errors = validate_draft_contract(page, draft)
    for error in contract_errors:
        _warn(
            warnings,
            f"contract_{error['field'].replace('.', '_')}",
            "blocker",
            error["message"],
        )
    heroes = [item for item in media if item.image_role == "hero"]
    if contract.media_policy == "required" and not heroes:
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


def _generic_json_ld(
    *,
    business: Business,
    faqs: list[dict[str, str]],
    page_title: str,
    canonical_url: str,
    website_url: str,
) -> dict[str, Any]:
    website = _website_base(website_url)
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
            }
        ),
        {
            "@type": "WebPage",
            "name": page_title,
            "url": canonical_url,
            "about": {"@id": business_id},
        },
    ]
    if faqs:
        graph.append(
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": item["answer"],
                        },
                    }
                    for item in faqs
                ],
            }
        )
    return {"@context": "https://schema.org", "@graph": graph}


def _json_ld(
    *,
    business: Business,
    service: Service,
    city: City,
    county: County,
    faqs: list[dict[str, str]],
    page_title: str,
    canonical_url: str,
    website_url: str,
    license_label: str,
    operator_title: str,
) -> dict[str, Any]:
    website = _website_base(website_url)
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
                        "propertyID": license_label,
                        "value": business.license_number,
                    }
                    if business.license_number
                    else None
                ),
                "employee": (
                    {
                        "@type": "Person",
                        "name": business.certified_operator,
                        "jobTitle": operator_title,
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


def _effective_qa_status(qa_state: EffectivePageQAState) -> str:
    if qa_state.current and qa_state.result is not None:
        return qa_state.result.readiness_status
    return "not_run"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
