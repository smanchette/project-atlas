from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Any, Mapping

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    Business,
    City,
    County,
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    ImageMetadata,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    Service,
    SitePlan,
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
from app.services.page_type_review import (
    PageTypeReviewContract,
    review_contract_for,
    valid_faqs,
)
from app.services.page_composition import (
    PageCompositionError,
    read_composition_for_generated_page,
)
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

PAGE_QA_ALGORITHM_KEY = "atlas-page-qa"
PAGE_QA_ALGORITHM_VERSION = "2"
PAGE_QA_RULESET_KEY = "atlas-page-qa-rules"
PAGE_QA_RULESET_VERSION = "2"


@dataclass(frozen=True)
class PageQAAuthoritativeState:
    website_id: int | None
    site_plan_id: int | None
    planned_page_id: int | None
    latest_generated_page_revision_id: int | None
    content_hash: str
    source_hash: str
    page_composition_id: int | None
    composition_version: int | None
    composition_source_hash: str | None
    qa_ruleset_hash: str


@dataclass(frozen=True)
class PageQAEvaluatorInputSnapshot:
    """One immutable serialization used by both QA checks and source identity."""

    page_id: int
    website_id: int | None
    contract: PageTypeReviewContract
    serialized_source: str
    content_hash: str
    source_hash: str
    qa_ruleset_hash: str

    def payload(self) -> dict[str, Any]:
        return json.loads(self.serialized_source)


@dataclass(frozen=True)
class EffectivePageQAState:
    classification: str
    reasons: tuple[str, ...]
    record: GeneratedPageQAResult | None = None
    result: PageQAResult | None = None

    @property
    def current(self) -> bool:
        return self.classification == "current_exact_identity_match"

    @property
    def ready(self) -> bool:
        return bool(
            self.current
            and self.result is not None
            and self.result.readiness_status == "ready"
            and self.result.failed_count == 0
            and self.result.warning_count == 0
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


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    raise TypeError(f"Unsupported QA hash value: {type(value).__name__}")


def historical_qa_payload_hash(payload: Mapping[str, Any]) -> str:
    """Return the immutable integrity hash for preserved pre-binding evidence."""

    return _canonical_hash(dict(payload))


def qa_result_record_hash(values: Mapping[str, Any]) -> str:
    """Hash the exact identity and outcome fields of one durable QA result."""

    evaluated_at = values.get("evaluated_at")
    if isinstance(evaluated_at, datetime):
        evaluated_at = _utc(evaluated_at).isoformat()
    payload = {
        "website_id": values.get("website_id"),
        "site_plan_id": values.get("site_plan_id"),
        "planned_page_id": values.get("planned_page_id"),
        "generated_page_id": values.get("generated_page_id"),
        "latest_generated_page_revision_id": values.get(
            "latest_generated_page_revision_id"
        ),
        "content_hash": values.get("content_hash"),
        "source_hash": values.get("source_hash"),
        "page_composition_id": values.get("page_composition_id"),
        "composition_version": values.get("composition_version"),
        "composition_source_hash": values.get("composition_source_hash"),
        "qa_algorithm_key": values.get("qa_algorithm_key"),
        "qa_algorithm_version": values.get("qa_algorithm_version"),
        "qa_ruleset_key": values.get("qa_ruleset_key"),
        "qa_ruleset_version": values.get("qa_ruleset_version"),
        "qa_ruleset_hash": values.get("qa_ruleset_hash"),
        "readiness_status": values.get("readiness_status"),
        "passed_count": values.get("passed_count"),
        "warning_count": values.get("warning_count"),
        "failed_count": values.get("failed_count"),
        "check_payload": values.get("check_payload"),
        "evaluated_at": evaluated_at,
    }
    return _canonical_hash(payload)


def _content_hash(page: GeneratedPage) -> str:
    return _canonical_hash(page.draft_content or {})


def _qa_ruleset_hash(contract: PageTypeReviewContract) -> str:
    return _canonical_hash(
        {
            "algorithm_key": PAGE_QA_ALGORITHM_KEY,
            "algorithm_version": PAGE_QA_ALGORITHM_VERSION,
            "ruleset_key": PAGE_QA_RULESET_KEY,
            "ruleset_version": PAGE_QA_RULESET_VERSION,
            "contract": asdict(contract),
            "forbidden_phrases": sorted(FORBIDDEN_PHRASES),
            "placeholder_patterns": list(PLACEHOLDER_PATTERNS),
            "check_remediation": CHECK_REMEDIATION,
        }
    )


def _semantic_qa_source_snapshot(
    session: Session,
    page: GeneratedPage,
    *,
    contract: PageTypeReviewContract | None = None,
) -> dict[str, Any]:
    """Build a remap-stable snapshot of only inputs consumed by page QA."""

    website_context = build_website_context(session, page_id=page.id or 0)
    business = website_context.business
    website = session.get(Website, page.website_id)
    service = session.get(Service, page.service_id) if page.service_id else None
    city = session.get(City, page.city_id) if page.city_id else None
    county = session.get(County, page.county_id) if page.county_id else None
    contract = contract or review_contract_for(page)
    assignments = list(
        session.exec(
            select(PageImageAssignment)
            .where(
                PageImageAssignment.generated_page_id == page.id,
                PageImageAssignment.status == "active",
            )
            .order_by(PageImageAssignment.id)
        ).all()
    )
    media: list[dict[str, Any]] = []
    for assignment in assignments:
        image = session.get(ImageMetadata, assignment.image_metadata_id)
        media.append(
            {
                "role": assignment.image_role,
                "sort_order": assignment.sort_order,
                "status": assignment.status,
                "override_alt_text": assignment.override_alt_text,
                "display_preset": assignment.display_preset,
                "asset": (
                    {
                        "media_key": image.media_key,
                        "media_version": image.media_version,
                        "checksum_sha256": image.checksum_sha256,
                        "review_status": image.review_status,
                        "alt_text": image.alt_text,
                        "reviewed_alt_text": image.reviewed_alt_text,
                        "governance_status": image.governance_status,
                        "wordpress_media_id": image.wordpress_media_id,
                        "retired_at": image.retired_at,
                    }
                    if image
                    else None
                ),
                "excluded_by_website_policy": is_image_metadata_excluded(
                    website, image
                ),
            }
        )
    media.sort(
        key=lambda value: json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=_json_default,
        )
    )
    return {
        "page": {
            "page_type": page.page_type,
            "page_title": page.page_title,
            "page_slug": page.page_slug,
            "meta_title": page.meta_title,
            "meta_description": page.meta_description,
            "h1": page.h1,
            "draft_content": page.draft_content or {},
        },
        "website": (
            {
                "website_name": website.website_name,
                "domain": website.domain,
                "public_url": website.public_url,
                "status": website.status,
                # Website-scoped media exclusions are selected partly from
                # durable Website configuration. Bind the complete approved
                # configuration so a policy change can never reuse old QA.
                "configuration": website.configuration or {},
            }
            if website
            else None
        ),
        "business": {
            "company_name": business.company_name,
            "brand_name": website_context.brand.public_name,
            "phone": business.phone,
            "license_number": business.license_number,
            "certified_operator": business.certified_operator,
        },
        "service": (
            {"service_name": service.service_name, "service_slug": service.service_slug}
            if service
            else None
        ),
        "city": (
            {"city_name": city.city_name, "city_slug": city.city_slug}
            if city
            else None
        ),
        "county": (
            {"county_name": county.county_name, "state": county.state}
            if county
            else None
        ),
        "review_contract": asdict(contract),
        "media": media,
    }


def _capture_page_qa_evaluator_inputs(
    session: Session,
    page: GeneratedPage,
    contract: PageTypeReviewContract,
) -> PageQAEvaluatorInputSnapshot:
    if page.id is None:
        raise ValueError("Generated Page must be persisted before QA evaluation.")
    source = _semantic_qa_source_snapshot(
        session,
        page,
        contract=contract,
    )
    serialized_source = _canonical_json(source)
    return PageQAEvaluatorInputSnapshot(
        page_id=page.id,
        website_id=page.website_id,
        contract=contract,
        serialized_source=serialized_source,
        content_hash=_canonical_hash(source["page"]["draft_content"]),
        source_hash=hashlib.sha256(serialized_source.encode("utf-8")).hexdigest(),
        qa_ruleset_hash=_qa_ruleset_hash(contract),
    )


def authoritative_page_qa_state(
    session: Session,
    page: GeneratedPage,
    *,
    evaluator_snapshot: PageQAEvaluatorInputSnapshot | None = None,
) -> PageQAAuthoritativeState:
    """Resolve the exact current page identity that a QA result must bind."""

    if evaluator_snapshot is not None and (
        evaluator_snapshot.page_id != page.id
        or evaluator_snapshot.website_id != page.website_id
    ):
        raise ValueError("Generated Page identity changed during QA evaluation.")
    website_id = (
        evaluator_snapshot.website_id
        if evaluator_snapshot is not None
        else page.website_id
    )
    planned_pages = list(
        session.exec(
            select(PlannedPage).where(PlannedPage.generated_page_id == page.id)
        ).all()
    )
    if len(planned_pages) > 1:
        raise ValueError("Generated Page has multiple Planned Page owners.")
    planned = planned_pages[0] if planned_pages else None
    plan = session.get(SitePlan, planned.site_plan_id) if planned else None
    if planned and (
        planned.website_id != website_id
        or plan is None
        or plan.website_id != website_id
    ):
        raise ValueError("Generated Page crosses its Website or Site Plan boundary.")

    revisions = list(
        session.exec(
            select(GeneratedPageRevision)
            .where(GeneratedPageRevision.generated_page_id == page.id)
            .order_by(
                GeneratedPageRevision.created_at.desc(),
                GeneratedPageRevision.id.desc(),
            )
        ).all()
    )
    latest_revision = revisions[0] if revisions else None
    content_hash = (
        evaluator_snapshot.content_hash
        if evaluator_snapshot is not None
        else _content_hash(page)
    )
    if (
        latest_revision is not None
        and latest_revision.draft_hash_after != content_hash
    ):
        raise ValueError(
            "Generated Page content is not represented by its latest revision."
        )
    all_compositions = list(
        session.exec(
            select(PageComposition).where(PageComposition.generated_page_id == page.id)
        ).all()
    )
    current_compositions = [
        composition
        for composition in all_compositions
        if composition.status == "current"
    ]
    if len(current_compositions) > 1:
        raise ValueError("Generated Page has multiple current Page Compositions.")
    if all_compositions and not current_compositions:
        raise ValueError("Generated Page has no current Page Composition.")
    composition = current_compositions[0] if current_compositions else None
    if composition is not None:
        try:
            resolved_composition = read_composition_for_generated_page(
                session,
                page.id or 0,
            )
        except PageCompositionError as exc:
            raise ValueError(
                f"Generated Page Composition is not authoritative: {exc}"
            ) from exc
        if resolved_composition.id != composition.id:
            raise ValueError("Generated Page Composition identity changed during QA.")
    if evaluator_snapshot is None:
        contract = review_contract_for(page)
        evaluator_snapshot = _capture_page_qa_evaluator_inputs(
            session,
            page,
            contract,
        )
    return PageQAAuthoritativeState(
        website_id=website_id,
        site_plan_id=plan.id if plan else None,
        planned_page_id=planned.id if planned else None,
        latest_generated_page_revision_id=(
            latest_revision.id if latest_revision else None
        ),
        content_hash=content_hash,
        source_hash=evaluator_snapshot.source_hash,
        page_composition_id=composition.id if composition else None,
        composition_version=(composition.composition_version if composition else None),
        composition_source_hash=(composition.source_hash if composition else None),
        qa_ruleset_hash=evaluator_snapshot.qa_ruleset_hash,
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def evaluate_page_qa(session: Session, page_id: int) -> PageQAResult:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")

    require_page_website(session, page)
    try:
        contract = review_contract_for(page)
        evaluator_snapshot = _capture_page_qa_evaluator_inputs(
            session,
            page,
            contract,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    evaluator_inputs = evaluator_snapshot.payload()
    page_inputs = evaluator_inputs["page"]
    business = evaluator_inputs["business"]
    service = evaluator_inputs["service"]
    city = evaluator_inputs["city"]
    county = evaluator_inputs["county"]
    media = evaluator_inputs["media"]
    draft = page_inputs["draft_content"]
    page_type = page_inputs["page_type"]
    public_text = " ".join(_iter_strings(draft))
    public_text_lower = public_text.lower()
    checks: list[QACheckItem] = []

    _required(
        checks,
        "title",
        "Page title",
        draft.get("title") or page_inputs["page_title"],
    )
    _required(
        checks,
        "meta_title",
        "Meta title",
        draft.get("meta_title") or page_inputs["meta_title"],
    )
    _required(
        checks,
        "meta_description",
        "Meta description",
        draft.get("meta_description") or page_inputs["meta_description"],
    )
    _required(checks, "h1", "H1", draft.get("h1") or page_inputs["h1"])
    _required(checks, "intro", "Introduction", draft.get("intro"))
    _required(checks, "call_to_action", "Call to action", draft.get("call_to_action"))

    if contract.schema == "planned-page-draft-v1":
        _check(
            checks,
            key="draft_schema",
            label="Page-type draft contract",
            passed=(
                draft.get("schema_version") == contract.schema
                and draft.get("page_type") == page_type
            ),
            pass_message=f"{page_type} uses the approved {contract.schema} contract.",
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
            service_present = bool(
                service and service["service_name"].lower() in public_text_lower
            )
            _check(
                checks,
                key="service_name",
                label="Service name present",
                passed=service_present,
                pass_message=(
                    f"{service['service_name']} appears in the draft."
                    if service
                    else "Service appears in the draft."
                ),
                fail_message="The assigned service name is missing from the draft.",
            )
        if contract.require_county:
            county_present = bool(
                county and county["county_name"].lower() in public_text_lower
            )
            _check(
                checks,
                key="county_name",
                label="County name present",
                passed=county_present,
                pass_message=(
                    f"{county['county_name']} appears in the draft."
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
        city_present = bool(city and city["city_name"].lower() in public_text_lower)
        _check(
            checks,
            key="city_name",
            label="City name present",
            passed=city_present,
            pass_message=(
                f"{city['city_name']} appears in the draft."
                if city
                else "City appears in the draft."
            ),
            fail_message="The assigned city name is missing from the draft.",
        )
        service_present = bool(
            service and service["service_name"].lower() in public_text_lower
        )
        _check(
            checks,
            key="service_name",
            label="Service name present",
            passed=service_present,
            pass_message=(
                f"{service['service_name']} appears in the draft."
                if service
                else "Service appears in the draft."
            ),
            fail_message="The assigned service name is missing from the draft.",
        )

    phone_present = bool(
        business
        and any(
            candidate in _digits(public_text)
            for candidate in _phone_candidates(business.get("phone"))
        )
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
                business.get("license_number") if business else None,
                business.get("certified_operator") if business else None,
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

    excluded_assignment_count = sum(
        1
        for assignment in media
        if assignment["excluded_by_website_policy"]
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
            assignment
            for assignment in media
            if not assignment["excluded_by_website_policy"]
        ]
        hero_pair = next(
            (
                assignment
                for assignment in assignment_images
                if assignment["role"] == "hero" and assignment["asset"] is not None
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
            hero_pair
            and hero_pair["asset"]
            and hero_pair["asset"]["review_status"] == "reviewed"
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
        if hero_pair and hero_pair["asset"]:
            hero_alt = (
                hero_pair["override_alt_text"]
                or hero_pair["asset"]["reviewed_alt_text"]
                or hero_pair["asset"]["alt_text"]
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
            for assignment in assignment_images
            if assignment["asset"] is None
            or assignment["asset"]["review_status"] != "reviewed"
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
    checked_at = datetime.now(UTC)
    try:
        identity = authoritative_page_qa_state(
            session,
            page,
            evaluator_snapshot=evaluator_snapshot,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"QA evaluation blocked by non-authoritative page identity: {exc}",
        ) from exc
    record_values = {
        **asdict(identity),
        "generated_page_id": page.id or page_id,
        "qa_algorithm_key": PAGE_QA_ALGORITHM_KEY,
        "qa_algorithm_version": PAGE_QA_ALGORITHM_VERSION,
        "qa_ruleset_key": PAGE_QA_RULESET_KEY,
        "qa_ruleset_version": PAGE_QA_RULESET_VERSION,
        "readiness_status": readiness_status,
        "passed_count": passed_count,
        "warning_count": warning_count,
        "failed_count": failed_count,
        "check_payload": [item.model_dump(mode="json") for item in checks],
        "evaluated_at": checked_at,
    }
    return PageQAResult(
        page_id=page.id or page_id,
        website_id=identity.website_id,
        site_plan_id=identity.site_plan_id,
        planned_page_id=identity.planned_page_id,
        latest_generated_page_revision_id=(
            identity.latest_generated_page_revision_id
        ),
        content_hash=identity.content_hash,
        source_hash=identity.source_hash,
        page_composition_id=identity.page_composition_id,
        composition_version=identity.composition_version,
        composition_source_hash=identity.composition_source_hash,
        qa_algorithm_key=PAGE_QA_ALGORITHM_KEY,
        qa_algorithm_version=PAGE_QA_ALGORITHM_VERSION,
        qa_ruleset_key=PAGE_QA_RULESET_KEY,
        qa_ruleset_version=PAGE_QA_RULESET_VERSION,
        qa_ruleset_hash=identity.qa_ruleset_hash,
        readiness_status=readiness_status,
        checked_at=checked_at,
        passed_count=passed_count,
        warning_count=warning_count,
        failed_count=failed_count,
        checks=checks,
        result_hash=qa_result_record_hash(record_values),
        lifecycle_status="candidate",
        currentness_status="candidate_not_persisted",
        currentness_reasons=[],
        persisted=False,
    )


def save_page_qa(session: Session, page_id: int, *, commit: bool = True) -> PageQAResult:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    result = evaluate_page_qa(session, page_id)
    if result.site_plan_id is None or result.planned_page_id is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "QA persistence requires one exact Planned Page and Site Plan owner."
            ),
        )

    current_records = _current_qa_records(session, page.id or page_id)
    if len(current_records) > 1:
        raise HTTPException(
            status_code=409,
            detail="Generated Page has multiple current QA results; QA persistence failed closed.",
        )
    prior = current_records[0] if current_records else None
    if prior is not None:
        prior.lifecycle_status = "superseded"
        prior.updated_at = result.checked_at
        session.add(prior)

    record = GeneratedPageQAResult(
        website_id=result.website_id,
        site_plan_id=result.site_plan_id,
        planned_page_id=result.planned_page_id,
        generated_page_id=page.id or page_id,
        latest_generated_page_revision_id=(
            result.latest_generated_page_revision_id
        ),
        content_hash=result.content_hash,
        source_hash=result.source_hash,
        page_composition_id=result.page_composition_id,
        composition_version=result.composition_version,
        composition_source_hash=result.composition_source_hash,
        qa_algorithm_key=result.qa_algorithm_key,
        qa_algorithm_version=result.qa_algorithm_version,
        qa_ruleset_key=result.qa_ruleset_key,
        qa_ruleset_version=result.qa_ruleset_version,
        qa_ruleset_hash=result.qa_ruleset_hash,
        readiness_status=result.readiness_status,
        passed_count=result.passed_count,
        warning_count=result.warning_count,
        failed_count=result.failed_count,
        check_payload=[item.model_dump(mode="json") for item in result.checks],
        evaluated_at=result.checked_at,
        lifecycle_status="current",
        supersedes_qa_result_id=prior.id if prior else None,
        result_hash=result.result_hash,
        historical_payload=None,
        created_at=result.checked_at,
        updated_at=result.checked_at,
    )
    session.add(record)
    session.flush()
    persisted = result.model_copy(
        update={
            "qa_result_id": record.id,
            "lifecycle_status": "current",
            "currentness_status": "current_exact_identity_match",
            "currentness_reasons": [],
            "persisted": True,
        }
    )
    page.qa_status = persisted.readiness_status
    page.qa_result = persisted.model_dump(mode="json", exclude={"persisted"})
    page.qa_checked_at = persisted.checked_at
    session.add(page)
    if commit:
        session.commit()
        session.refresh(page)
        session.refresh(record)
    return persisted


def reconcile_page_qa(
    session: Session,
    page_id: int,
    *,
    commit: bool = True,
) -> PageQAResult:
    """Persist QA only when the page lacks one exact current bound result.

    This is the governed repair path for historical, missing, stale, or
    identity-mismatched evidence. Re-running reconciliation against an already
    current page is intentionally mutation-free.
    """

    page = session.get(GeneratedPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Generated page not found")
    effective = effective_page_qa_state(session, page)
    if effective.current and effective.result is not None:
        return effective.result
    return save_page_qa(session, page_id, commit=commit)


def get_page_qa(session: Session, page_id: int) -> PageQAResult:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    effective = effective_page_qa_state(session, page)
    if effective.current and effective.result is not None:
        return effective.result
    fresh = evaluate_page_qa(session, page_id)
    return fresh.model_copy(
        update={
            "currentness_status": effective.classification,
            "currentness_reasons": list(effective.reasons),
            "persisted": False,
        }
    )


def generated_page_with_effective_qa(
    session: Session,
    page: GeneratedPage,
) -> dict[str, Any]:
    """Project authoritative QA currentness into Generated Page API reads."""

    values = page.model_dump(mode="python")
    effective = effective_page_qa_state(session, page)
    if effective.current and effective.result is not None:
        values["qa_status"] = effective.result.readiness_status
        values["qa_result"] = effective.result.model_dump(mode="json")
        values["qa_checked_at"] = effective.result.checked_at
        return values

    values["qa_status"] = "not_run"
    values["qa_checked_at"] = None
    raw = page.qa_result
    if isinstance(raw, dict):
        values["qa_result"] = {
            **raw,
            "persisted": False,
            "currentness_status": effective.classification,
            "currentness_reasons": list(effective.reasons),
        }
    else:
        values["qa_result"] = None
    return values


def _current_qa_records(
    session: Session,
    generated_page_id: int,
) -> list[GeneratedPageQAResult]:
    return list(
        session.exec(
            select(GeneratedPageQAResult)
            .where(
                GeneratedPageQAResult.generated_page_id == generated_page_id,
                GeneratedPageQAResult.lifecycle_status == "current",
            )
            .order_by(GeneratedPageQAResult.id)
        ).all()
    )


def _record_as_result(record: GeneratedPageQAResult) -> PageQAResult:
    return PageQAResult(
        qa_result_id=record.id,
        page_id=record.generated_page_id,
        website_id=record.website_id,
        site_plan_id=record.site_plan_id,
        planned_page_id=record.planned_page_id,
        latest_generated_page_revision_id=(
            record.latest_generated_page_revision_id
        ),
        content_hash=record.content_hash or "",
        source_hash=record.source_hash or "",
        page_composition_id=record.page_composition_id,
        composition_version=record.composition_version,
        composition_source_hash=record.composition_source_hash,
        qa_algorithm_key=record.qa_algorithm_key or "",
        qa_algorithm_version=record.qa_algorithm_version or "",
        qa_ruleset_key=record.qa_ruleset_key or "",
        qa_ruleset_version=record.qa_ruleset_version or "",
        qa_ruleset_hash=record.qa_ruleset_hash or "",
        readiness_status=record.readiness_status,
        checked_at=record.evaluated_at,
        passed_count=record.passed_count,
        warning_count=record.warning_count,
        failed_count=record.failed_count,
        checks=record.check_payload or [],
        result_hash=record.result_hash,
        lifecycle_status=record.lifecycle_status,
        currentness_status="current_exact_identity_match",
        currentness_reasons=[],
        persisted=True,
    )


def _normalized_page_qa_projection(result: PageQAResult) -> dict[str, Any]:
    values = result.model_dump(mode="json", exclude={"persisted"})
    values["checked_at"] = _utc(result.checked_at).isoformat()
    return values


def effective_page_qa_state(
    session: Session,
    page_or_id: GeneratedPage | int,
) -> EffectivePageQAState:
    """Return the one fail-closed QA state used by every downstream gate."""

    page = (
        session.get(GeneratedPage, page_or_id)
        if isinstance(page_or_id, int)
        else page_or_id
    )
    if page is None or page.id is None:
        return EffectivePageQAState(
            "orphaned_qa", ("Generated Page does not exist.",)
        )
    current_records = _current_qa_records(session, page.id)
    if len(current_records) > 1:
        return EffectivePageQAState(
            "duplicate_current_qa",
            ("Multiple current QA results exist for the Generated Page.",),
        )
    if not current_records:
        payload = page.qa_result
        if payload is None:
            return EffectivePageQAState(
                "missing_qa", ("No persisted QA result exists.",)
            )
        if not isinstance(payload, dict):
            return EffectivePageQAState(
                "otherwise_invalid", ("Persisted QA payload is malformed.",)
            )
        embedded_page_id = payload.get("page_id")
        if embedded_page_id != page.id:
            return EffectivePageQAState(
                "wrong_page_identity",
                (
                    "Persisted QA page identity does not match the Generated Page "
                    f"({embedded_page_id!r} != {page.id}).",
                ),
            )
        qa_result_id = payload.get("qa_result_id")
        if type(qa_result_id) is int:
            referenced = session.get(GeneratedPageQAResult, qa_result_id)
            if referenced and referenced.generated_page_id != page.id:
                return EffectivePageQAState(
                    "wrong_page_identity",
                    ("Persisted QA result belongs to another Generated Page.",),
                )
        return EffectivePageQAState(
            "otherwise_invalid",
            ("Persisted QA evidence is legacy and lacks exact identity binding.",),
        )

    record = current_records[0]
    try:
        authoritative = authoritative_page_qa_state(session, page)
    except (ValueError, HTTPException) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return EffectivePageQAState(
            "otherwise_invalid", (f"Authoritative QA identity is invalid: {detail}",), record
        )
    if record.website_id != authoritative.website_id:
        return EffectivePageQAState(
            "wrong_website_identity",
            ("QA Website identity does not match the Generated Page.",),
            record,
        )
    if record.site_plan_id != authoritative.site_plan_id:
        return EffectivePageQAState(
            "wrong_site_plan_identity",
            ("QA Site Plan identity does not match the Generated Page.",),
            record,
        )
    if record.planned_page_id != authoritative.planned_page_id:
        return EffectivePageQAState(
            "otherwise_invalid",
            ("QA Planned Page identity does not match the Generated Page.",),
            record,
        )
    if (
        record.latest_generated_page_revision_id
        != authoritative.latest_generated_page_revision_id
    ):
        return EffectivePageQAState(
            "stale_generated_revision",
            ("QA evaluated an earlier Generated Page revision.",),
            record,
        )
    if record.content_hash != authoritative.content_hash:
        return EffectivePageQAState(
            "stale_content_hash",
            ("QA content hash does not match the current draft.",),
            record,
        )
    if (
        record.page_composition_id != authoritative.page_composition_id
        or record.composition_version != authoritative.composition_version
        or record.composition_source_hash
        != authoritative.composition_source_hash
    ):
        return EffectivePageQAState(
            "stale_composition",
            ("QA composition identity is not current.",),
            record,
        )
    if (
        record.qa_algorithm_key != PAGE_QA_ALGORITHM_KEY
        or record.qa_algorithm_version != PAGE_QA_ALGORITHM_VERSION
        or record.qa_ruleset_key != PAGE_QA_RULESET_KEY
        or record.qa_ruleset_version != PAGE_QA_RULESET_VERSION
        or record.qa_ruleset_hash != authoritative.qa_ruleset_hash
    ):
        return EffectivePageQAState(
            "stale_qa_algorithm",
            ("QA algorithm or ruleset identity is not current.",),
            record,
        )
    if record.source_hash != authoritative.source_hash:
        return EffectivePageQAState(
            "otherwise_invalid",
            ("QA evaluator inputs changed after evaluation.",),
            record,
        )
    expected_hash = qa_result_record_hash(record.model_dump(mode="python"))
    if record.result_hash != expected_hash:
        return EffectivePageQAState(
            "otherwise_invalid",
            ("QA result integrity hash is invalid.",),
            record,
        )
    try:
        result = _record_as_result(record)
        expected_projection = _normalized_page_qa_projection(result)
        raw_projection = page.qa_result
        if not isinstance(raw_projection, dict) or set(raw_projection) != set(
            expected_projection
        ):
            raise ValueError("Generated Page QA projection shape is not exact.")
        projection = PageQAResult.model_validate(
            {**raw_projection, "persisted": True}
        )
        normalized_projection = _normalized_page_qa_projection(projection)
    except Exception:
        return EffectivePageQAState(
            "otherwise_invalid",
            ("Generated Page QA projection is missing or malformed.",),
            record,
        )
    if (
        normalized_projection != expected_projection
        or page.qa_status != record.readiness_status
        or page.qa_checked_at is None
        or _utc(page.qa_checked_at) != _utc(record.evaluated_at)
    ):
        return EffectivePageQAState(
            "otherwise_invalid",
            ("Generated Page QA projection does not match its durable QA result.",),
            record,
        )
    return EffectivePageQAState(
        "current_exact_identity_match", (), record, result
    )


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
