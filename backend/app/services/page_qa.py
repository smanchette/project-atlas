from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import ipaddress
import json
import re
import unicodedata
from typing import Any, Mapping
from urllib.parse import urlsplit

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
from app.services.page_composition_history import (
    PageCompositionHistoryError,
    current_composition_revision,
    read_composition_revision,
)
from app.services.page_media_roles import (
    SemanticMediaRoleError,
    resolve_semantic_media_role,
)
from app.services.scoped_media_authorizations import (
    governed_assignment_authorization_errors,
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

# This is the exact accepted ruleset identity carried by the active legacy
# City-Service QA rows.  It is intentionally frozen: the automatic CTA refresh
# may recognize it only as an immutable predecessor, never as current QA.
LEGACY_CITY_SERVICE_QA_RULESET_HASH = (
    "9ed072fc1adbc09300a8f62583ef15ad0659f409407c24d8f78dabd9741f2c55"
)
LEGACY_CITY_SERVICE_QA_CHECK_KEYS = (
    "title",
    "meta_title",
    "meta_description",
    "h1",
    "intro",
    "call_to_action",
    "why_it_matters",
    "signs_section",
    "process_section",
    "prep_section",
    "faqs",
    "city_name",
    "service_name",
    "phone",
    "license_operator",
    "unsafe_phrases",
    "county_county",
    "placeholders",
    "hero_assigned",
    "hero_reviewed",
    "hero_alt_text",
    "assigned_images_reviewed",
    "preview_route",
)

CITY_SERVICE_PUBLIC_CTA_POLICY = {
    "schema": "atlas-city-service-public-cta-policy@1",
    "nonpublic_draft_fields": ("internal_notes", "status"),
    "public_generated_page_fields": (
        "page_title",
        "meta_title",
        "meta_description",
        "h1",
    ),
    "governed_text_normalization": "NFKC_trim_casefold",
    "ownership": ("company_or_brand", "service", "city"),
    "governed_contact_channels": ("phone", "public_email", "website_public_url"),
    "configured_invalid_contact": "does_not_become_unconfigured",
    "public_email_syntax": "single_ascii_mailbox_with_dot_domain",
    "safe_destination_schemes": ("http", "https", "mailto", "tel"),
    "bare_domain_destinations": "validated_as_public_url_destinations",
    "public_url_syntax": "validated_http_origin_host_labels_port_and_controls",
    "unicode_phone_separators": "normalized_before_exact_governed_comparison",
    "safe_internal_destination_prefixes": ("/", "#"),
    "private_delivery_keys": ("recipient_email", "from_email"),
    "credential_visibility": "configured_values_absent_from_ordinary_public_fields",
    "public_marker_values": (*PLACEHOLDER_PATTERNS, "demo"),
    "malformed_constructs": ("||", ";;", ",,", "()", "[]", "{}"),
}

CITY_SERVICE_CHECK_REMEDIATION = {
    "cta_ownership": (
        "content",
        "Identify the governed company or brand, assigned service, and assigned city in the CTA.",
    ),
    "cta_contact": (
        "business_info",
        "Use a configured public phone, public contact email, or governed Website URL.",
    ),
    "cta_destinations": (
        "business_info",
        "Remove ungoverned contact details and use only safe governed or internal destinations.",
    ),
    "cta_private_delivery": (
        "business_info",
        "Keep private recipient and From configuration out of public draft fields.",
    ),
    "cta_credentials": (
        "business_info",
        "Remove automatic credential output unless an approved public Credentials component is configured.",
    ),
    "cta_format": (
        "content",
        "Correct malformed separators, empty groups, or dangling conjunctions in the CTA.",
    ),
    "cta_public_markers": (
        "content",
        "Replace placeholder or demo content with reviewed public CTA copy.",
    ),
}


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
    payload = {
        "algorithm_key": PAGE_QA_ALGORITHM_KEY,
        "algorithm_version": PAGE_QA_ALGORITHM_VERSION,
        "ruleset_key": PAGE_QA_RULESET_KEY,
        "ruleset_version": PAGE_QA_RULESET_VERSION,
        "contract": asdict(contract),
        "forbidden_phrases": sorted(FORBIDDEN_PHRASES),
        "placeholder_patterns": list(PLACEHOLDER_PATTERNS),
        "check_remediation": CHECK_REMEDIATION,
    }
    if contract.schema == "legacy-city-service-v1":
        # Bind the City-Service-only policy without changing any unrelated page
        # type's durable QA identity.
        payload["city_service_public_cta_policy"] = CITY_SERVICE_PUBLIC_CTA_POLICY
        payload["city_service_check_remediation"] = CITY_SERVICE_CHECK_REMEDIATION
    return _canonical_hash(payload)


def _semantic_qa_source_snapshot(
    session: Session,
    page: GeneratedPage,
    *,
    contract: PageTypeReviewContract | None = None,
    legacy_city_service_policy: bool = False,
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
        authorization_errors = governed_assignment_authorization_errors(
            session,
            assignment,
        )
        if authorization_errors:
            raise HTTPException(status_code=409, detail=" ".join(authorization_errors))
        try:
            semantic_role = resolve_semantic_media_role(assignment, session=session)
        except SemanticMediaRoleError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        media_identity = {
                "role": (
                    assignment.image_role
                    if assignment.media_requirement_id is None
                    else semantic_role
                ),
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
        if assignment.media_requirement_id is not None:
            # Governed roles retain their opaque storage identity independently
            # from the canonical semantic projection. Legacy snapshots remain
            # byte-for-byte compatible with prior exact QA source hashes.
            media_identity["storage_role_token"] = assignment.image_role
        media.append(media_identity)
    media.sort(
        key=lambda value: json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=_json_default,
        )
    )
    business_snapshot = {
        "company_name": business.company_name,
        "brand_name": website_context.brand.public_name,
        "phone": business.phone,
        "license_number": business.license_number,
        "certified_operator": business.certified_operator,
    }
    if contract.schema == "legacy-city-service-v1" and not legacy_city_service_policy:
        # Public CTA email validation consumes this value.  Scope the added
        # input to City-Service so every unrelated QA source hash stays exact.
        business_snapshot["public_email"] = business.email

    page_snapshot = {
        "page_type": page.page_type,
        "page_title": page.page_title,
        "page_slug": page.page_slug,
        "meta_title": page.meta_title,
        "meta_description": page.meta_description,
        "h1": page.h1,
        "draft_content": page.draft_content or {},
    }
    return {
        "page": page_snapshot,
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
        "business": business_snapshot,
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
            current_composition_revision(session, composition)
            resolved_composition = read_composition_for_generated_page(
                session,
                page.id or 0,
            )
        except (PageCompositionError, PageCompositionHistoryError) as exc:
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


def resolve_qa_composition_revision(
    session: Session,
    qa_result: GeneratedPageQAResult | int,
):
    """Resolve one bound QA row to only its exact immutable composition state."""

    record = (
        session.get(GeneratedPageQAResult, qa_result)
        if isinstance(qa_result, int)
        else qa_result
    )
    if record is None:
        raise ValueError("Generated Page QA result was not found.")
    binding = (
        record.page_composition_id,
        record.composition_version,
        record.composition_source_hash,
    )
    if binding == (None, None, None):
        raise ValueError("Generated Page QA result has no composition binding.")
    if any(value is None for value in binding):
        raise ValueError("Generated Page QA result has a partial composition binding.")
    try:
        revision = read_composition_revision(
            session,
            record.page_composition_id,
            record.composition_version,
            generated_page_id=record.generated_page_id,
            website_id=record.website_id,
        )
    except PageCompositionHistoryError as exc:
        raise ValueError(
            f"Generated Page QA composition evidence is invalid: {exc}"
        ) from exc
    if (
        revision.source_hash != record.composition_source_hash
        or revision.site_plan_id != record.site_plan_id
        or revision.planned_page_id != record.planned_page_id
    ):
        raise ValueError(
            "Generated Page QA result crosses its exact historical composition scope."
        )
    return revision


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def evaluate_page_qa(session: Session, page_id: int) -> PageQAResult:
    return _evaluate_page_qa(
        session,
        page_id,
        legacy_city_service_policy=False,
    )


def _evaluate_page_qa(
    session: Session,
    page_id: int,
    *,
    legacy_city_service_policy: bool,
) -> PageQAResult:
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
    website = evaluator_inputs["website"]
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

    if (
        contract.schema == "legacy-city-service-v1"
        and not legacy_city_service_policy
    ):
        _evaluate_city_service_public_cta(
            checks,
            draft=draft,
            page_public_fields={
                "page_title": page_inputs.get("page_title"),
                "meta_title": page_inputs.get("meta_title"),
                "meta_description": page_inputs.get("meta_description"),
                "h1": page_inputs.get("h1"),
            },
            business=business,
            website=website,
            service=service,
            city=city,
        )
    else:
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
                value.lower() in public_text_lower
                for value in required_operator_values
            )
            _check(
                checks,
                key="license_operator",
                label="License and operator information",
                passed=operator_present,
                pass_message=(
                    "Configured license and operator information appears in the draft."
                ),
                fail_message=(
                    "Configured license or certified operator information is missing."
                ),
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


def _qa_record_projection_matches_page(
    page: GeneratedPage,
    record: GeneratedPageQAResult,
) -> bool:
    try:
        result = _record_as_result(record)
        expected_projection = _normalized_page_qa_projection(result)
        raw_projection = page.qa_result
        if not isinstance(raw_projection, dict) or set(raw_projection) != set(
            expected_projection
        ):
            return False
        raw_exact_projection = {
            key: value for key, value in raw_projection.items() if key != "checked_at"
        }
        expected_exact_projection = {
            key: value
            for key, value in expected_projection.items()
            if key != "checked_at"
        }
        if raw_exact_projection != expected_exact_projection:
            return False
        projection = PageQAResult.model_validate(
            {**raw_projection, "persisted": True}
        )
        normalized_projection = _normalized_page_qa_projection(projection)
    except Exception:
        return False
    return bool(
        normalized_projection == expected_projection
        and page.qa_status == record.readiness_status
        and page.qa_checked_at is not None
        and _utc(page.qa_checked_at) == _utc(record.evaluated_at)
    )


def is_exact_legacy_city_service_qa_predecessor(
    session: Session,
    page: GeneratedPage,
    record: GeneratedPageQAResult,
) -> bool:
    """Recognize only the frozen, identity-exact pre-policy QA evidence.

    This is a one-way transition predicate for the guarded automatic CTA
    refresh. It deliberately does not make legacy evidence current or ready.
    """

    if page.id is None or page.page_type != "city_service":
        return False
    try:
        contract = review_contract_for(page)
        if contract.schema != "legacy-city-service-v1":
            return False
        current_records = _current_qa_records(session, page.id)
        authoritative = authoritative_page_qa_state(session, page)
        legacy_source = _semantic_qa_source_snapshot(
            session,
            page,
            contract=contract,
            legacy_city_service_policy=True,
        )
        expected_legacy_result = _evaluate_page_qa(
            session,
            page.id,
            legacy_city_service_policy=True,
        )
        raw_check_payload = record.check_payload
        if not isinstance(raw_check_payload, list):
            return False
        checks = [
            QACheckItem.model_validate(value)
            for value in raw_check_payload
        ]
    except (HTTPException, ValueError, TypeError):
        return False

    if (
        len(current_records) != 1
        or current_records[0].id != record.id
        or record.lifecycle_status != "current"
        or record.website_id != authoritative.website_id
        or record.site_plan_id != authoritative.site_plan_id
        or record.planned_page_id != authoritative.planned_page_id
        or record.latest_generated_page_revision_id
        != authoritative.latest_generated_page_revision_id
        or record.content_hash != authoritative.content_hash
        or record.page_composition_id != authoritative.page_composition_id
        or record.composition_version != authoritative.composition_version
        or record.composition_source_hash != authoritative.composition_source_hash
        or record.qa_algorithm_key != PAGE_QA_ALGORITHM_KEY
        or record.qa_algorithm_version != PAGE_QA_ALGORITHM_VERSION
        or record.qa_ruleset_key != PAGE_QA_RULESET_KEY
        or record.qa_ruleset_version != PAGE_QA_RULESET_VERSION
        or record.qa_ruleset_hash != LEGACY_CITY_SERVICE_QA_RULESET_HASH
        or record.source_hash != _canonical_hash(legacy_source)
        or record.result_hash
        != qa_result_record_hash(record.model_dump(mode="python"))
        or not _qa_record_projection_matches_page(page, record)
    ):
        return False

    expected_check_payload = [
        item.model_dump(mode="json") for item in expected_legacy_result.checks
    ]
    return bool(
        tuple(item.key for item in checks) == LEGACY_CITY_SERVICE_QA_CHECK_KEYS
        and len(checks) == len(LEGACY_CITY_SERVICE_QA_CHECK_KEYS)
        and raw_check_payload == expected_check_payload
        and record.passed_count == expected_legacy_result.passed_count
        and record.warning_count == expected_legacy_result.warning_count
        and record.failed_count == expected_legacy_result.failed_count
        and record.readiness_status == expected_legacy_result.readiness_status
    )


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
        raw_exact_projection = {
            key: value for key, value in raw_projection.items() if key != "checked_at"
        }
        expected_exact_projection = {
            key: value for key, value in expected_projection.items() if key != "checked_at"
        }
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
        raw_exact_projection != expected_exact_projection
        or normalized_projection != expected_projection
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


def _evaluate_city_service_public_cta(
    checks: list[QACheckItem],
    *,
    draft: Mapping[str, Any],
    page_public_fields: Mapping[str, Any] | None = None,
    business: Mapping[str, Any] | None,
    website: Mapping[str, Any] | None,
    service: Mapping[str, Any] | None,
    city: Mapping[str, Any] | None,
) -> None:
    """Evaluate the governed ordinary-public City-Service CTA contract.

    Internal notes and draft workflow status are deliberately outside the
    public projection. Credential checks compare only exact configured source
    values; they do not redact rendered text or use a credential keyword list.
    """

    public_draft = {
        key: value
        for key, value in draft.items()
        if key not in CITY_SERVICE_PUBLIC_CTA_POLICY["nonpublic_draft_fields"]
    }
    public_projection = {
        "draft": public_draft,
        "generated_page": dict(page_public_fields or {}),
    }
    public_text = " ".join(_iter_strings(public_projection))
    public_text_folded = _normalized_governed_text(public_text)
    cta = draft.get("call_to_action")
    cta_text = cta.strip() if isinstance(cta, str) else ""
    cta_folded = cta_text.casefold()

    company_values = [
        value.casefold()
        for value in (
            business.get("company_name") if business else None,
            business.get("brand_name") if business else None,
        )
        if _has_text(value)
    ]
    ownership_present = bool(company_values) and any(
        value in cta_folded for value in company_values
    )
    ownership_present = bool(
        ownership_present
        and service
        and _has_text(service.get("service_name"))
        and service["service_name"].casefold() in cta_folded
        and city
        and _has_text(city.get("city_name"))
        and city["city_name"].casefold() in cta_folded
    )
    _check(
        checks,
        key="cta_ownership",
        label="Governed CTA ownership",
        passed=ownership_present,
        pass_message="CTA identifies the governed company, service, and city.",
        fail_message="CTA does not identify the governed company, service, and city.",
    )

    cta_contact_tokens = _public_contact_tokens(cta_text)
    cta_email_tokens = _public_email_tokens(cta_contact_tokens)
    cta_destination_tokens = _public_destination_tokens(cta_contact_tokens)
    cta_phone_scan_text = cta_text.casefold()
    for token in [*cta_email_tokens, *cta_destination_tokens]:
        cta_phone_scan_text = cta_phone_scan_text.replace(token.casefold(), " ")
    cta_phone_tokens = _public_phone_tokens(cta_phone_scan_text)

    public_contact_tokens = _public_contact_tokens(public_text)
    public_email_tokens = _public_email_tokens(public_contact_tokens)
    public_destination_tokens = _public_destination_tokens(public_contact_tokens)
    public_phone_scan_text = public_text.casefold()
    for token in [*public_email_tokens, *public_destination_tokens]:
        public_phone_scan_text = public_phone_scan_text.replace(token.casefold(), " ")
    public_phone_tokens = _public_phone_tokens(public_phone_scan_text)
    raw_governed_phone = (
        str(business.get("phone") or "").strip() if business else ""
    )
    governed_phone_values = set(_phone_candidates(raw_governed_phone))
    raw_governed_email = (
        str(business.get("public_email") or "").strip().casefold()
        if business
        else ""
    )
    governed_email = _normalized_public_email(raw_governed_email) or ""
    governed_public_url = (
        str(website.get("public_url") or "").strip() if website else ""
    )

    governed_phone_present = bool(
        governed_phone_values.intersection(cta_phone_tokens)
        or any(
            token.casefold().startswith("tel:")
            and _is_safe_public_destination(
                token,
                public_url=governed_public_url,
                public_email=governed_email,
                phone_values=governed_phone_values,
            )
            for token in cta_destination_tokens
        )
    )
    governed_email_present = bool(
        governed_email and governed_email in cta_email_tokens
    )
    governed_url_present = bool(
        governed_public_url
        and any(
            _is_governed_public_url_destination(
                token,
                public_url=governed_public_url,
            )
            for token in cta_destination_tokens
        )
    )
    configured_contact_count = sum(
        bool(value)
        for value in (
            raw_governed_phone,
            raw_governed_email,
            governed_public_url,
        )
    )
    contact_present = bool(
        configured_contact_count == 0
        or governed_phone_present
        or governed_email_present
        or governed_url_present
    )
    _check(
        checks,
        key="cta_contact",
        label="Governed public CTA contact",
        passed=contact_present,
        pass_message=(
            "CTA uses a configured public contact channel."
            if configured_contact_count
            else "No public contact channel is configured; CTA ownership remains explicit."
        ),
        fail_message="CTA is missing a configured public contact channel.",
    )

    email_destinations_safe = all(
        token == governed_email for token in public_email_tokens
    )
    phone_destinations_safe = all(
        token in governed_phone_values for token in public_phone_tokens
    )
    other_destinations_safe = all(
        _is_safe_public_destination(
            token,
            public_url=governed_public_url,
            public_email=governed_email,
            phone_values=governed_phone_values,
        )
        for token in public_destination_tokens
    )
    _check(
        checks,
        key="cta_destinations",
        label="Governed public contact details and destinations",
        passed=(
            email_destinations_safe
            and phone_destinations_safe
            and other_destinations_safe
        ),
        pass_message="Public draft fields contain only governed contact details and safe destinations.",
        fail_message="A public draft field contains an ungoverned contact detail or unsafe destination.",
    )

    private_keys = {
        str(value).casefold()
        for value in CITY_SERVICE_PUBLIC_CTA_POLICY["private_delivery_keys"]
    }
    _check(
        checks,
        key="cta_private_delivery",
        label="Private delivery configuration absent",
        passed=not _contains_mapping_key(public_draft, private_keys),
        pass_message="Public draft fields contain no private delivery configuration.",
        fail_message="Public draft fields contain private recipient or From configuration.",
    )

    governed_credentials = [
        _normalized_governed_text(value)
        for value in (
            business.get("license_number") if business else None,
            business.get("certified_operator") if business else None,
        )
        if _has_text(value)
    ]
    leaked_credentials = [
        value for value in governed_credentials if value in public_text_folded
    ]
    _check(
        checks,
        key="cta_credentials",
        label="No automatic public credential output",
        passed=not leaked_credentials,
        pass_message="Governed credential values remain outside ordinary public draft fields.",
        fail_message="An ordinary public draft field exposes a governed credential value.",
    )

    _check(
        checks,
        key="cta_format",
        label="Well-formed CTA copy",
        passed=not _cta_has_malformed_separators(cta_text),
        pass_message="CTA separators and conjunctions are well formed.",
        fail_message="CTA contains a malformed separator, empty group, or dangling conjunction.",
    )

    marker_values = CITY_SERVICE_PUBLIC_CTA_POLICY["public_marker_values"]
    marker_found = any(
        marker.casefold() in cta_folded
        for marker in marker_values
        if marker.casefold() != "demo"
    ) or "demo" in _plain_words(cta_text)
    _check(
        checks,
        key="cta_public_markers",
        label="No placeholder or demo CTA output",
        passed=not marker_found,
        pass_message="CTA contains no placeholder or demo output.",
        fail_message="CTA contains placeholder or demo output.",
    )


def _public_contact_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value)
    variants = [normalized]
    without_url_controls = normalized.translate(
        {ord("\t"): None, ord("\r"): None, ord("\n"): None}
    )
    if without_url_controls != normalized:
        # WHATWG URL parsing strips these controls. Preserve a second token
        # view so a construct such as `/\t/host` remains `//host` and fails
        # the governed internal-destination check instead of splitting into
        # two apparently safe path fragments.
        variants.append(without_url_controls)

    tokens: list[str] = []
    for translated in variants:
        for character in '<>()[]{}"\'':
            translated = translated.replace(character, " ")
        tokens.extend(
            token.strip(".,!?;")
            for token in translated.split()
            if token.strip(".,!?;")
        )
    return tokens


def _public_email_tokens(tokens: list[str]) -> set[str]:
    values: set[str] = set()
    for token in tokens:
        if "@" not in token:
            continue
        separated = token
        for separator in "?&=,;":
            separated = separated.replace(separator, " ")
        for candidate in separated.split():
            if "@" not in candidate:
                continue
            if candidate.casefold().startswith("mailto:"):
                candidate = candidate[7:]
            if candidate.count("@") != 1:
                values.add(candidate.casefold())
                continue
            local, domain = candidate.rsplit("@", 1)
            # Retain malformed email-like identities so the governed allowlist
            # comparison fails closed instead of silently discarding them.
            values.add(candidate.casefold())
            if not local or not domain or "." not in domain:
                continue
    return values


def _looks_like_uri(token: str) -> bool:
    candidate = _whatwg_trimmed_destination_token(token)
    lowered = candidate.casefold()
    if lowered.startswith(("/", "#", "\\")):
        return len(candidate) > 1
    if lowered.startswith("www.") or "://" in lowered:
        return True
    if _looks_like_bare_domain(candidate):
        return True
    if ":" not in candidate:
        return False
    scheme, _separator, remainder = candidate.partition(":")
    valid_scheme = bool(
        scheme
        and scheme[0].isalpha()
        and all(character.isalnum() or character in "+-." for character in scheme)
    )
    if not valid_scheme:
        return False
    if remainder:
        return True
    return scheme.casefold() in {
        *CITY_SERVICE_PUBLIC_CTA_POLICY["safe_destination_schemes"],
        "data",
        "javascript",
        "vbscript",
    }


def _whatwg_trimmed_destination_token(token: str) -> str:
    # WHATWG trims leading/trailing ASCII whitespace and C0 controls before
    # parsing. Classification must observe that browser-equivalent token so
    # a control-prefixed network path cannot disappear from destination QA.
    return token.strip("".join(chr(value) for value in range(0x21)))


def _looks_like_bare_domain(token: str) -> bool:
    candidate = _bare_domain_candidate(token)
    return bool(
        candidate is not None
        and "@" not in candidate
        and "://" not in candidate
        and _normalized_public_url(candidate)
    )


def _bare_domain_candidate(token: str) -> str | None:
    candidate = unicodedata.normalize("NFKC", token)
    if candidate.endswith(":"):
        candidate = candidate[:-1]
    return None if candidate.endswith(":") else candidate


def _public_destination_tokens(tokens: list[str]) -> list[str]:
    return [token for token in tokens if _looks_like_uri(token)]


def _public_phone_tokens(value: str) -> set[str]:
    value = unicodedata.normalize("NFKC", value)
    values: set[str] = set()
    allowed = set("0123456789+()-. \u00a0\u2007\u2009\u202f\u2010\u2011\u2012\u2013\u2014\u2212")
    candidate: list[str] = []

    def flush() -> None:
        digits = _digits("".join(candidate))
        if len(digits) >= 7:
            values.add(digits)
        candidate.clear()

    for index, character in enumerate(value):
        if character in allowed:
            candidate.append(character)
        elif (
            character == "/"
            and index > 0
            and index + 1 < len(value)
            and value[index - 1].isdigit()
            and value[index + 1].isdigit()
        ):
            candidate.append(character)
        else:
            flush()
    flush()
    return values


def _normalized_public_email(value: str) -> str | None:
    candidate = unicodedata.normalize("NFKC", value).strip().casefold()
    if (
        not candidate
        or len(candidate) > 254
        or candidate.count("@") != 1
        or any(character.isspace() for character in candidate)
        or any(character in "?&=,;:/#" for character in candidate)
    ):
        return None
    local, domain = candidate.rsplit("@", 1)
    if (
        not local
        or len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or not domain
        or len(domain) > 253
    ):
        return None
    local_allowed = set(
        "abcdefghijklmnopqrstuvwxyz0123456789.!#$%&'*+-/=?^_`{|}~"
    )
    if any(character not in local_allowed for character in local):
        return None
    labels = domain.split(".")
    if len(labels) < 2 or any(not label for label in labels):
        return None
    for label in labels:
        if (
            len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or any(
                not (character.isascii() and (character.isalnum() or character == "-"))
                for character in label
            )
        ):
            return None
    if len(labels[-1]) < 2 or not all(character.isalpha() for character in labels[-1]):
        return None
    return candidate


def _normalized_public_url(value: str) -> tuple[str, str, int] | None:
    candidate = value.strip()
    if (
        not candidate
        or any(ord(character) < 33 for character in candidate)
        or "\\" in candidate
    ):
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or not hostname
    ):
        return None
    hostname = hostname.casefold()
    if hostname.startswith("[") or ":" in hostname:
        return None
    if all(character.isdigit() or character == "." for character in hostname):
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            return None
    elif not _valid_public_domain(hostname):
        return None
    scheme = parsed.scheme.casefold()
    return scheme, hostname, port or (443 if scheme == "https" else 80)


def _valid_public_domain(hostname: str) -> bool:
    labels = hostname.split(".")
    if len(labels) < 2 or any(not label for label in labels):
        return False
    labels_valid = all(
        len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(
            character.isascii()
            and (character.isalnum() or character == "-")
            for character in label
        )
        for label in labels
    )
    top_level = labels[-1]
    return bool(
        labels_valid
        and len(top_level) >= 2
        and (
            all(character.isascii() and character.isalpha() for character in top_level)
            or top_level.startswith("xn--")
        )
    )


def _is_safe_public_destination(
    token: str,
    *,
    public_url: str,
    public_email: str,
    phone_values: set[str],
) -> bool:
    lowered = token.casefold()
    if "\\" in token:
        return False
    if lowered.startswith("#"):
        return len(token) > 1
    if lowered.startswith("/"):
        return len(token) > 1 and not lowered.startswith("//")
    if lowered.startswith("mailto:"):
        parsed = urlsplit(token)
        return bool(
            public_email
            and parsed.scheme.casefold() == "mailto"
            and parsed.path.casefold() == public_email
            and not parsed.query
            and not parsed.fragment
            and "," not in parsed.path
            and ";" not in parsed.path
        )
    if lowered.startswith("tel:"):
        destination = _digits(token[4:])
        return bool(destination and destination in phone_values)

    return _is_governed_public_url_destination(token, public_url=public_url)


def _is_governed_public_url_destination(
    token: str,
    *,
    public_url: str,
) -> bool:
    expected_origin = _normalized_public_url(public_url)
    candidate = token
    if token.casefold().startswith("www."):
        candidate = f"https://{token}"
    elif _looks_like_bare_domain(token):
        bare_domain = _bare_domain_candidate(token)
        if bare_domain is None:
            return False
        candidate = f"https://{bare_domain}"
    candidate_origin = _normalized_public_url(candidate)
    return bool(expected_origin is not None and candidate_origin == expected_origin)


def _contains_mapping_key(value: Any, keys: set[str]) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).casefold() in keys or _contains_mapping_key(nested, keys)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(_contains_mapping_key(nested, keys) for nested in value)
    return False


def _plain_words(value: str) -> list[str]:
    translated = value.casefold()
    for character in ",.;:!?()[]{}|/\\":
        translated = translated.replace(character, " ")
    return translated.split()


def _normalized_governed_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _cta_has_malformed_separators(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    folded = stripped.casefold()
    if any(
        construct in folded
        for construct in CITY_SERVICE_PUBLIC_CTA_POLICY["malformed_constructs"]
    ):
        return True
    words = _plain_words(stripped)
    if not words or words[0] in {"and", "or"} or words[-1] in {"and", "or"}:
        return True
    if any(
        left in {"and", "or"} and right in {"and", "or"}
        for left, right in zip(words, words[1:])
    ):
        return True
    if stripped.endswith(("/", "|", ",", ";")):
        return True
    compact = "".join(character for character in folded if not character.isspace())
    if any(
        separator + punctuation in compact
        for separator in (",", ";", "|")
        for punctuation in (".", "!", "?")
    ):
        return True
    return any(
        stripped.count(left) != stripped.count(right)
        for left, right in (("(", ")"), ("[", "]"), ("{", "}"))
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
    issue_location, suggested_fix = CITY_SERVICE_CHECK_REMEDIATION.get(
        key,
        CHECK_REMEDIATION.get(
            key,
            ("content", "Review this item and correct the related page information."),
        ),
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
