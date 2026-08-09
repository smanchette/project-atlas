from datetime import UTC, datetime
import re
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    Business,
    City,
    County,
    GeneratedPage,
    ImageMetadata,
    PageImageAssignment,
    Service,
    Website,
)
from app.schemas.qa import (
    PageQAResult,
    QABatchCandidate,
    QABatchRequest,
    QABatchResponse,
    QACheckItem,
)
from app.services.draft_generation import FORBIDDEN_PHRASES
from app.services.page_type_review import review_contract_for, valid_faqs
from app.services.website_context import build_website_context
from app.services.website_scope import require_page_website, require_single_website_selection
from app.services.website_media_safety import is_image_metadata_excluded

PLACEHOLDER_PATTERNS = (
    "lorem ipsum",
    "[city]",
    "{city}",
    "[service]",
    "{service}",
    "insert text",
    "placeholder text",
    "todo:",
    "tbd",
)

CHECK_REMEDIATION = {
    "title": ("content", "Add a clear title appropriate to this page type."),
    "meta_title": ("content", "Add a concise SEO title appropriate to this page type."),
    "meta_description": ("content", "Add a useful summary grounded in approved information."),
    "h1": ("content", "Add one clear H1 appropriate to this page type."),
    "intro": ("content", "Add an introduction that fulfills the page's Planning Record."),
    "why_it_matters": ("content", "Explain why this service matters for local property owners."),
    "signs_section": ("content", "Add practical signs customers can look for."),
    "process_section": ("content", "Describe the service process with careful, non-absolute wording."),
    "prep_section": ("content", "Add preparation and re-entry guidance appropriate to the service."),
    "call_to_action": ("content", "Add the approved primary visitor action for this page."),
    "faqs": ("content", "Add at least one complete customer question and answer."),
    "city_name": ("city_county_info", "Add the assigned city name naturally to the page content."),
    "service_name": ("content", "Name the assigned service naturally in the page content."),
    "phone": ("business_info", "Add the current business phone number to the call to action."),
    "license_operator": (
        "business_info",
        "Add the configured license number and certified operator where appropriate.",
    ),
    "unsafe_phrases": (
        "safety_wording",
        "Replace absolute claims with careful wording such as often, may, or can help.",
    ),
    "county_county": (
        "city_county_info",
        'Remove the duplicated county suffix so the location reads "County" only once.',
    ),
    "placeholders": ("content", "Replace template markers and unfinished copy with reviewed text."),
    "hero_assigned": ("media", "Assign one reviewed hero image to this page."),
    "hero_reviewed": ("media", "Review the assigned hero image before approval."),
    "hero_alt_text": ("media", "Add reviewed or page-specific alt text to the hero image."),
    "assigned_images_reviewed": ("media", "Review or remove every unreviewed page image assignment."),
    "excluded_external_media": (
        "media",
        "Remove assignments that reference Website-scoped excluded external media.",
    ),
    "preview_route": ("preview", "Generate a structured draft so the internal preview can render."),
}


def evaluate_page_qa(session: Session, page_id: int) -> PageQAResult:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")

    require_page_website(session, page)
    website_context = build_website_context(session, page_id=page_id)
    business = website_context.business
    service = session.get(Service, page.service_id) if page.service_id else None
    city = session.get(City, page.city_id) if page.city_id else None
    county = session.get(County, page.county_id) if page.county_id else None
    draft = page.draft_content or {}
    try:
        contract = review_contract_for(page)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    public_text = " ".join(_iter_strings(draft))
    public_text_lower = public_text.lower()
    checks: list[QACheckItem] = []

    _required(checks, "title", "Page title", draft.get("title") or page.page_title)
    _required(checks, "meta_title", "Meta title", draft.get("meta_title") or page.meta_title)
    _required(
        checks,
        "meta_description",
        "Meta description",
        draft.get("meta_description") or page.meta_description,
    )
    _required(checks, "h1", "H1", draft.get("h1") or page.h1)
    _required(checks, "intro", "Introduction", draft.get("intro"))
    _required(checks, "call_to_action", "Call to action", draft.get("call_to_action"))

    if contract.schema == "planned-page-draft-v1":
        _check(
            checks,
            key="draft_schema",
            label="Page-type draft contract",
            passed=(
                draft.get("schema_version") == contract.schema
                and draft.get("page_type") == page.page_type
            ),
            pass_message=f"{page.page_type} uses the approved {contract.schema} contract.",
            fail_message="Draft schema or page type does not match the Generated Page.",
        )
        sections = {
            str(item.get("key")): item
            for item in draft.get("sections", [])
            if isinstance(item, dict) and _has_text(item.get("key"))
        }
        for section_key in contract.required_section_keys:
            section = sections.get(section_key)
            _required(
                checks,
                f"section_{section_key}",
                f"{section_key.replace('_', ' ').title()} section",
                section.get("body") if section else None,
            )
        if contract.require_faqs:
            faqs = draft.get("faq_items")
            _check(
                checks,
                key="faqs",
                label="FAQs",
                passed=valid_faqs(faqs),
                pass_message=(
                    f"{len(faqs)} complete FAQ items found."
                    if isinstance(faqs, list)
                    else "FAQs found."
                ),
                fail_message="At least one complete FAQ question and answer is required.",
            )
        if contract.require_service:
            service_present = bool(service and service.service_name.lower() in public_text_lower)
            _check(
                checks,
                key="service_name",
                label="Service name present",
                passed=service_present,
                pass_message=(
                    f"{service.service_name} appears in the draft."
                    if service
                    else "Service appears in the draft."
                ),
                fail_message="The assigned service name is missing from the draft.",
            )
        if contract.require_county:
            county_present = bool(
                county and county.county_name.lower() in public_text_lower
            )
            _check(
                checks,
                key="county_name",
                label="County name present",
                passed=county_present,
                pass_message=(
                    f"{county.county_name} appears in the draft."
                    if county
                    else "County appears in the draft."
                ),
                fail_message="The assigned County name is missing from the draft.",
            )
    else:
        _required(checks, "why_it_matters", "Why it matters section", draft.get("why_it_matters"))
        _required(checks, "signs_section", "Signs section", draft.get("signs_section"))
        _required(checks, "process_section", "Process section", draft.get("process_section"))
        _required(checks, "prep_section", "Preparation section", draft.get("prep_section"))
        faqs = draft.get("faq_items")
        _check(
            checks,
            key="faqs",
            label="FAQs",
            passed=valid_faqs(faqs),
            pass_message=(
                f"{len(faqs)} complete FAQ items found."
                if isinstance(faqs, list)
                else "FAQs found."
            ),
            fail_message="At least one complete FAQ question and answer is required.",
        )
        city_present = bool(city and city.city_name.lower() in public_text_lower)
        _check(
            checks,
            key="city_name",
            label="City name present",
            passed=city_present,
            pass_message=(
                f"{city.city_name} appears in the draft." if city else "City appears in the draft."
            ),
            fail_message="The assigned city name is missing from the draft.",
        )
        service_present = bool(service and service.service_name.lower() in public_text_lower)
        _check(
            checks,
            key="service_name",
            label="Service name present",
            passed=service_present,
            pass_message=(
                f"{service.service_name} appears in the draft."
                if service
                else "Service appears in the draft."
            ),
            fail_message="The assigned service name is missing from the draft.",
        )

    phone_present = bool(
        business
        and any(candidate in _digits(public_text) for candidate in _phone_candidates(business.phone))
    )
    _check(
        checks,
        key="phone",
        label="Phone number present",
        passed=phone_present,
        pass_message="Business phone number appears in the draft.",
        fail_message="Business phone number is missing from the draft.",
    )

    if contract.schema == "legacy-city-service-v1":
        required_operator_values = [
            value
            for value in (
                business.license_number if business else None,
                business.certified_operator if business else None,
            )
            if _has_text(value)
        ]
        operator_present = all(
            value.lower() in public_text_lower for value in required_operator_values
        )
        _check(
            checks,
            key="license_operator",
            label="License and operator information",
            passed=operator_present,
            pass_message="Configured license and operator information appears in the draft.",
            fail_message="Configured license or certified operator information is missing.",
            severity="warning",
        )

    unsafe_found = [phrase for phrase in FORBIDDEN_PHRASES if phrase in public_text_lower]
    _check(
        checks,
        key="unsafe_phrases",
        label="Safe wording",
        passed=not unsafe_found,
        pass_message="No prohibited absolute claims found.",
        fail_message=f"Unsafe wording found: {', '.join(unsafe_found)}.",
    )
    _check(
        checks,
        key="county_county",
        label='No "County County" duplication',
        passed="county county" not in public_text_lower,
        pass_message="No duplicated county suffix found.",
        fail_message='Draft contains "County County".',
    )

    placeholder_found = [pattern for pattern in PLACEHOLDER_PATTERNS if pattern in public_text_lower]
    _check(
        checks,
        key="placeholders",
        label="No obvious placeholders",
        passed=not placeholder_found,
        pass_message="No obvious placeholder copy found.",
        fail_message=f"Placeholder copy found: {', '.join(placeholder_found)}.",
    )

    website = session.get(Website, page.website_id)
    assignments = session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.generated_page_id == page.id,
            PageImageAssignment.status == "active",
        )
    ).all()
    assignment_images = [
        (assignment, session.get(ImageMetadata, assignment.image_metadata_id))
        for assignment in assignments
    ]
    excluded_assignment_count = sum(
        1
        for _, image in assignment_images
        if is_image_metadata_excluded(website, image)
    )
    if excluded_assignment_count:
        _check(
            checks,
            key="excluded_external_media",
            label="No excluded external media assigned",
            passed=False,
            pass_message="No assigned image is excluded by Website media policy.",
            fail_message=(
                f"{excluded_assignment_count} assignment(s) reference excluded "
                "external media."
            ),
        )

    if contract.media_policy == "required":
        assignment_images = [
            pair
            for pair in assignment_images
            if not is_image_metadata_excluded(website, pair[1])
        ]
        hero_pair = next(
            (
                pair
                for pair in assignment_images
                if pair[0].image_role == "hero" and pair[1] is not None
            ),
            None,
        )
        _check(
            checks,
            key="hero_assigned",
            label="Hero image assigned",
            passed=hero_pair is not None,
            pass_message="A hero image is assigned.",
            fail_message="A reviewed hero image must be assigned.",
        )
        hero_reviewed = bool(
            hero_pair and hero_pair[1] and hero_pair[1].review_status == "reviewed"
        )
        _check(
            checks,
            key="hero_reviewed",
            label="Hero image reviewed",
            passed=hero_reviewed,
            pass_message="Hero image is reviewed.",
            fail_message="Hero image is missing or not reviewed.",
        )
        hero_alt = ""
        if hero_pair and hero_pair[1]:
            hero_alt = (
                hero_pair[0].override_alt_text
                or hero_pair[1].reviewed_alt_text
                or hero_pair[1].alt_text
                or ""
            )
        _check(
            checks,
            key="hero_alt_text",
            label="Hero alt text present",
            passed=_has_text(hero_alt),
            pass_message="Hero image has reviewed or page-specific alt text.",
            fail_message="Hero image alt text is missing.",
        )
        unreviewed_count = sum(
            1
            for _, image in assignment_images
            if image is None or image.review_status != "reviewed"
        )
        _check(
            checks,
            key="assigned_images_reviewed",
            label="All assigned images reviewed",
            passed=unreviewed_count == 0,
            pass_message="All assigned images are reviewed.",
            fail_message=f"{unreviewed_count} assigned image(s) are unreviewed or missing.",
        )

    _check(
        checks,
        key="preview_route",
        label="Preview route available",
        passed=page.id is not None and bool(draft),
        pass_message=f"Preview is available at /generated-pages/{page.id}/preview.",
        fail_message="A structured draft is required before preview is available.",
    )

    failed_count = sum(item.status == "fail" for item in checks)
    warning_count = sum(item.status == "warning" for item in checks)
    passed_count = sum(item.status == "pass" for item in checks)
    readiness_status = (
        "blocked"
        if failed_count
        else "needs_review"
        if warning_count
        else "ready"
    )
    return PageQAResult(
        page_id=page.id or page_id,
        readiness_status=readiness_status,
        checked_at=datetime.now(UTC),
        passed_count=passed_count,
        warning_count=warning_count,
        failed_count=failed_count,
        checks=checks,
        persisted=False,
    )


def save_page_qa(session: Session, page_id: int, *, commit: bool = True) -> PageQAResult:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    result = evaluate_page_qa(session, page_id)
    page.qa_status = result.readiness_status
    page.qa_result = result.model_dump(mode="json", exclude={"persisted"})
    page.qa_checked_at = result.checked_at
    session.add(page)
    if commit:
        session.commit()
        session.refresh(page)
    return result.model_copy(update={"persisted": True})


def get_page_qa(session: Session, page_id: int) -> PageQAResult:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    if page.qa_result and not _page_has_excluded_external_media(session, page):
        return PageQAResult.model_validate({**page.qa_result, "persisted": True})
    return evaluate_page_qa(session, page_id)


def _page_has_excluded_external_media(
    session: Session,
    page: GeneratedPage,
) -> bool:
    website = session.get(Website, page.website_id)
    assignments = session.exec(
        select(PageImageAssignment).where(
            PageImageAssignment.generated_page_id == page.id,
            PageImageAssignment.status == "active",
        )
    ).all()
    return any(
        is_image_metadata_excluded(
            website,
            session.get(ImageMetadata, assignment.image_metadata_id),
        )
        for assignment in assignments
    )


def preview_qa_batch(session: Session, payload: QABatchRequest) -> QABatchResponse:
    pages = _filtered_pages(session, payload)
    results = [evaluate_page_qa(session, page.id or 0) for page in pages]
    return _batch_response(session, pages, results, saved_count=0)


def run_qa_batch(session: Session, payload: QABatchRequest) -> QABatchResponse:
    pages = _filtered_pages(session, payload)
    results = [
        save_page_qa(session, page.id or 0, commit=False)
        for page in pages
    ]
    session.commit()
    return _batch_response(session, pages, results, saved_count=len(results))


def _filtered_pages(session: Session, payload: QABatchRequest) -> list[GeneratedPage]:
    if payload.page_ids:
        requested = [session.get(GeneratedPage, page_id) for page_id in payload.page_ids]
        if any(page is None for page in requested):
            raise HTTPException(status_code=404, detail="One or more generated pages were not found")
        require_single_website_selection(
            session,
            [page for page in requested if page is not None],
            website_id=payload.website_id,
            operation="Batch QA",
        )
    statement = select(GeneratedPage)
    if payload.website_id is not None:
        statement = statement.where(GeneratedPage.website_id == payload.website_id)
    if payload.page_ids:
        statement = statement.where(GeneratedPage.id.in_(payload.page_ids))
    if payload.county_ids:
        statement = statement.where(GeneratedPage.county_id.in_(payload.county_ids))
    if payload.city_ids:
        statement = statement.where(GeneratedPage.city_id.in_(payload.city_ids))
    if payload.page_status:
        statement = statement.where(GeneratedPage.status == payload.page_status)
    pages = list(session.exec(statement.order_by(GeneratedPage.id)).all())
    require_single_website_selection(
        session,
        pages,
        website_id=payload.website_id,
        operation="Batch QA",
    )
    return pages


def _batch_response(
    session: Session,
    pages: list[GeneratedPage],
    results: list[PageQAResult],
    *,
    saved_count: int,
) -> QABatchResponse:
    candidates: list[QABatchCandidate] = []
    for page, result in zip(pages, results, strict=True):
        city = session.get(City, page.city_id) if page.city_id else None
        candidates.append(
            QABatchCandidate(
                page_id=page.id or 0,
                page_title=page.page_title,
                city_name=city.city_name if city else "",
                readiness_status=result.readiness_status,
                passed_count=result.passed_count,
                warning_count=result.warning_count,
                failed_count=result.failed_count,
            )
        )
    return QABatchResponse(
        matched_count=len(candidates),
        ready_count=sum(item.readiness_status == "ready" for item in candidates),
        needs_review_count=sum(
            item.readiness_status == "needs_review" for item in candidates
        ),
        blocked_count=sum(item.readiness_status == "blocked" for item in candidates),
        saved_count=saved_count,
        candidates=candidates,
    )


def _required(
    checks: list[QACheckItem],
    key: str,
    label: str,
    value: Any,
) -> None:
    _check(
        checks,
        key=key,
        label=label,
        passed=_has_text(value),
        pass_message=f"{label} is present.",
        fail_message=f"{label} is required.",
    )


def _check(
    checks: list[QACheckItem],
    *,
    key: str,
    label: str,
    passed: bool,
    pass_message: str,
    fail_message: str,
    severity: str = "blocker",
) -> None:
    issue_location, suggested_fix = CHECK_REMEDIATION.get(
        key,
        ("content", "Review this item and correct the related page information."),
    )
    checks.append(
        QACheckItem(
            key=key,
            label=label,
            status="pass" if passed else "warning" if severity == "warning" else "fail",
            severity=severity,
            message=pass_message if passed else fail_message,
            suggested_fix=suggested_fix,
            issue_location=issue_location,
        )
    )


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _iter_strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_strings(nested)


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _phone_candidates(phone: str | None) -> list[str]:
    candidates = [_digits(part) for part in re.split(r"[/|,;]", phone or "")]
    return [candidate for candidate in candidates if len(candidate) >= 7]
