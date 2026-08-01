from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.models import GeneratedPage


ReviewSchema = Literal["planned-page-draft-v1", "legacy-city-service-v1"]
MediaReviewPolicy = Literal["deferred", "required"]


@dataclass(frozen=True)
class PageTypeReviewContract:
    page_type: str
    schema: ReviewSchema
    required_section_keys: tuple[str, ...] = ()
    require_faqs: bool = False
    require_service: bool = False
    require_city: bool = False
    require_county: bool = False
    media_policy: MediaReviewPolicy = "deferred"


PLANNED_PAGE_CONTRACTS: dict[str, PageTypeReviewContract] = {
    "home": PageTypeReviewContract(
        page_type="home",
        schema="planned-page-draft-v1",
        required_section_keys=("primary_services", "trust", "service_area"),
    ),
    "about": PageTypeReviewContract(
        page_type="about",
        schema="planned-page-draft-v1",
        required_section_keys=("company_story", "experience", "mission"),
    ),
    "contact": PageTypeReviewContract(
        page_type="contact",
        schema="planned-page-draft-v1",
        required_section_keys=("ways_to_contact", "hours", "service_area"),
    ),
    "service": PageTypeReviewContract(
        page_type="service",
        schema="planned-page-draft-v1",
        required_section_keys=("service_overview", "approved_guidance", "service_area"),
        require_service=True,
    ),
    "county": PageTypeReviewContract(
        page_type="county",
        schema="planned-page-draft-v1",
        required_section_keys=(
            "service_county_intro",
            "cities_served",
            "how_service_works",
            "customer_expectations",
            "preparation_guidance",
            "trust_and_license",
            "related_city_services",
        ),
        require_service=True,
        require_county=True,
    ),
    "informational": PageTypeReviewContract(
        page_type="informational",
        schema="planned-page-draft-v1",
        required_section_keys=("approved_information", "next_steps"),
    ),
    "faq": PageTypeReviewContract(
        page_type="faq",
        schema="planned-page-draft-v1",
        required_section_keys=("contact",),
        require_faqs=True,
    ),
}

CITY_SERVICE_CONTRACT = PageTypeReviewContract(
    page_type="city_service",
    schema="legacy-city-service-v1",
    require_faqs=True,
    require_service=True,
    require_city=True,
    require_county=True,
    media_policy="required",
)

DEFERRED_PAGE_TYPES = frozenset({"city"})


def review_contract_for(page: GeneratedPage) -> PageTypeReviewContract:
    if page.page_type == "city_service":
        return CITY_SERVICE_CONTRACT
    contract = PLANNED_PAGE_CONTRACTS.get(page.page_type)
    if not contract:
        raise ValueError(f"Page type is not reviewable in this milestone: {page.page_type}")
    return contract


def validate_draft_contract(
    page: GeneratedPage,
    draft: dict[str, Any],
) -> list[dict[str, str]]:
    try:
        contract = review_contract_for(page)
    except ValueError as exc:
        return [{"field": "page_type", "message": str(exc)}]

    errors: list[dict[str, str]] = []
    for field in ("title", "meta_title", "meta_description", "h1", "intro", "call_to_action"):
        if not _has_text(draft.get(field)):
            errors.append(
                {
                    "field": field,
                    "message": f"{field.replace('_', ' ').title()} is required.",
                }
            )

    if contract.schema == "planned-page-draft-v1":
        if draft.get("schema_version") != contract.schema:
            errors.append(
                {
                    "field": "schema_version",
                    "message": "The planned-page draft schema is missing or unsupported.",
                }
            )
        if draft.get("page_type") != page.page_type:
            errors.append(
                {
                    "field": "page_type",
                    "message": "Draft page type does not match the Generated Page.",
                }
            )
        sections = draft.get("sections")
        if not isinstance(sections, list):
            errors.append({"field": "sections", "message": "Draft sections are required."})
        else:
            keys: list[str] = []
            for index, section in enumerate(sections):
                if not isinstance(section, dict):
                    errors.append(
                        {
                            "field": f"sections.{index}",
                            "message": "Each section must be a structured object.",
                        }
                    )
                    continue
                key = section.get("key")
                if not _has_text(key) or not _has_text(section.get("heading")) or not _has_text(
                    section.get("body")
                ):
                    errors.append(
                        {
                            "field": f"sections.{index}",
                            "message": "Section key, heading, and body are required.",
                        }
                    )
                    continue
                keys.append(str(key))
            if len(keys) != len(set(keys)):
                errors.append(
                    {"field": "sections", "message": "Draft section keys must be unique."}
                )
            missing = [key for key in contract.required_section_keys if key not in keys]
            unexpected = [key for key in keys if key not in contract.required_section_keys]
            if missing:
                errors.append(
                    {
                        "field": "sections",
                        "message": f"Required section(s) missing: {', '.join(missing)}.",
                    }
                )
            if unexpected:
                errors.append(
                    {
                        "field": "sections",
                        "message": f"Unexpected section(s): {', '.join(unexpected)}.",
                    }
                )
    else:
        for field in (
            "why_it_matters",
            "signs_section",
            "process_section",
            "prep_section",
            "realtor_property_manager_section",
        ):
            if not _has_text(draft.get(field)):
                errors.append(
                    {
                        "field": field,
                        "message": f"{field.replace('_', ' ').title()} is required.",
                    }
                )

    if contract.require_faqs and not valid_faqs(draft.get("faq_items")):
        errors.append(
            {
                "field": "faq_items",
                "message": "At least one complete FAQ question and answer is required.",
            }
        )

    if contract.require_service and page.service_id is None:
        errors.append({"field": "service_id", "message": "A Service relationship is required."})
    if contract.require_city and page.city_id is None:
        errors.append({"field": "city_id", "message": "A City relationship is required."})
    if contract.require_county and page.county_id is None:
        errors.append({"field": "county_id", "message": "A County relationship is required."})
    return errors


def draft_content_sections(
    contract: PageTypeReviewContract,
    draft: dict[str, Any],
) -> dict[str, str]:
    if contract.schema == "planned-page-draft-v1":
        result = {"intro": _text(draft.get("intro"))}
        for section in draft.get("sections") or []:
            if isinstance(section, dict) and _has_text(section.get("key")):
                result[str(section["key"])] = _text(section.get("body"))
        return {key: value for key, value in result.items() if value}
    keys = (
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
    return {key: _text(draft.get(key)) for key in keys if _text(draft.get(key))}


def valid_faqs(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(
            isinstance(item, dict)
            and _has_text(item.get("question"))
            and _has_text(item.get("answer"))
            for item in value
        )
    )


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
